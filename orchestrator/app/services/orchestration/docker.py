"""
Docker Orchestrator

Docker Compose-based container orchestration for local development.
Implements the BaseOrchestrator interface for Docker deployments.

File Operations Architecture:
- Shared volume: tesslate-projects-data mounted at /projects
- Each project: /projects/{project-slug}/
- Multi-container projects: /projects/{project-slug}/{container-directory}/
- Orchestrator has direct filesystem access - no temp containers needed
"""

import asyncio
import contextlib
import json
import logging
import os
import re
import shutil
import socket
import subprocess
from collections.abc import AsyncIterator
from datetime import UTC
from pathlib import Path
from typing import Any
from uuid import UUID

import aiofiles
import aiofiles.os
import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import get_settings
from ..secret_manager_env import build_env_overrides
from .base import BaseOrchestrator
from .deployment_mode import DeploymentMode

logger = logging.getLogger(__name__)

# Shared projects volume mount point inside orchestrator
PROJECTS_BASE_PATH = Path("/projects")

# Binary file extensions to skip when reading content
BINARY_EXTENSIONS = {
    "png",
    "jpg",
    "jpeg",
    "gif",
    "ico",
    "svg",
    "webp",
    "bmp",
    "woff",
    "woff2",
    "ttf",
    "eot",
    "otf",
    "mp3",
    "mp4",
    "wav",
    "ogg",
    "webm",
    "avi",
    "mov",
    "pdf",
    "doc",
    "docx",
    "xls",
    "xlsx",
    "ppt",
    "pptx",
    "zip",
    "tar",
    "gz",
    "rar",
    "7z",
    "bin",
    "exe",
    "dll",
    "so",
    "dylib",
    "class",
    "jar",
    "pyc",
    "pyo",
    "lock",
    "map",
}

# Directories to exclude from file listings
EXCLUDED_DIRS = {
    "node_modules",
    ".git",
    "__pycache__",
    ".next",
    "dist",
    "build",
    ".venv",
    "venv",
    ".cache",
    ".turbo",
    "coverage",
    ".nyc_output",
    "lost+found",
}

# Files to exclude from listings
EXCLUDED_FILES = {".DS_Store", "Thumbs.db", ".env.local", ".ash_history"}


class DockerOrchestrator(BaseOrchestrator):
    """
    Docker Compose orchestrator for multi-container projects.

    Features:
    - Dynamic docker-compose.yml generation from Container models
    - Project-specific Docker networks for isolation
    - Traefik integration for routing
    - Volume vs bind mount support
    - Fast container status checks via Docker SDK
    """

    def __init__(self, use_volumes: bool = True):
        self.settings = get_settings()

        self.compose_files_dir = os.path.abspath("docker-compose-projects")
        os.makedirs(self.compose_files_dir, exist_ok=True)

        self.host_users_base = self._detect_host_users_path()
        self.use_volumes = use_volumes

        # Shared projects volume path — created by Docker/K8s at runtime;
        # skip silently if the process lacks permissions (e.g. test environments).
        self.projects_path = PROJECTS_BASE_PATH
        try:
            self.projects_path.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            logger.warning(
                "[DOCKER] Cannot create %s (permission denied); skipping", self.projects_path
            )

        logger.info("[DOCKER] Docker Compose orchestrator initialized")
        logger.info(f"[DOCKER] Storage mode: {'VOLUMES' if use_volumes else 'BIND_MOUNTS'}")
        logger.info(f"[DOCKER] Projects path: {self.projects_path}")
        logger.info(f"[DOCKER] Compose files directory: {self.compose_files_dir}")

    @property
    def deployment_mode(self) -> DeploymentMode:
        return DeploymentMode.DOCKER

    @property
    def supports_init_container(self) -> bool:
        return True

    @property
    def supports_volume_mount(self) -> bool:
        return True

    @property
    def writes_project_files_via_fs(self) -> bool:
        return True

    # =========================================================================
    # INTERNAL HELPERS
    # =========================================================================

    def _detect_host_users_path(self) -> str:
        """Detect the host path for /app/users (for Docker-in-Docker)."""
        if os.path.exists("/.dockerenv"):
            try:
                result = subprocess.run(
                    ["docker", "inspect", "-f", "{{ json .Mounts }}", socket.gethostname()],
                    capture_output=True,
                    text=True,
                    timeout=3,
                )

                if result.returncode == 0 and result.stdout.strip():
                    mounts = json.loads(result.stdout.strip())
                    for mount in mounts:
                        if mount.get("Destination") == "/app/users":
                            return mount.get("Source")

                    fallback = "/root/Tesslate-Studio/orchestrator/users"
                    logger.warning(
                        f"[DOCKER] Could not detect /app/users mount, using fallback: {fallback}"
                    )
                    return fallback
                else:
                    fallback = "/root/Tesslate-Studio/orchestrator/users"
                    logger.warning(f"[DOCKER] Docker inspect failed, using fallback: {fallback}")
                    return fallback

            except Exception as e:
                fallback = "/root/Tesslate-Studio/orchestrator/users"
                logger.warning(
                    f"[DOCKER] Error detecting host paths: {e}, using fallback: {fallback}"
                )
                return fallback
        else:
            host_path = os.path.abspath("users")
            logger.info(f"[DOCKER] Running on host, users base: {host_path}")
            return host_path

    def _convert_to_host_path(self, container_path: str) -> str:
        """Convert container path to host path for Docker-in-Docker."""
        if container_path.startswith("/app/users/"):
            relative_path = container_path[11:]
            host_path = os.path.join(self.host_users_base, relative_path)
            return host_path
        return container_path

    def _get_compose_file_path(self, project_slug: str) -> str:
        """Get the path to the docker-compose.yml file for a project."""
        return os.path.join(self.compose_files_dir, f"{project_slug}.yml")

    def _sanitize_service_name(self, name: str) -> str:
        """Sanitize a name for Docker service naming (DNS-safe)."""
        from ...services.project_setup.naming import sanitize_name

        return sanitize_name(name)

    def _resolve_service_name(self, container_name: str, project_slug: str) -> str:
        """Extract the Docker Compose service name from a container name.

        Handles both formats:
        - Full container name with slug prefix (Container.container_name):
          e.g. "my-proj-abc-next-js-16" → "next-js-16"
        - Display/service name (Container.name):
          e.g. "Next.js 16" → "next-js-16"
        """
        sanitized = self._sanitize_service_name(container_name)
        prefix = f"{project_slug}-"
        if sanitized.startswith(prefix):
            return sanitized[len(prefix) :]
        return sanitized

    # =========================================================================
    # PROJECT LIFECYCLE
    # =========================================================================

    async def start_project(
        self, project, containers: list, connections: list, user_id: UUID, db: AsyncSession
    ) -> dict[str, Any]:
        """Start all containers for a project using Docker Compose."""
        env_overrides = None
        if db:
            env_overrides = await build_env_overrides(db, project.id, containers)

        compose_file_path = await self._write_compose_file(
            project, containers, connections, user_id, env_overrides
        )

        logger.info(f"[DOCKER] Starting project {project.slug}...")

        try:
            process = await asyncio.create_subprocess_exec(
                "docker",
                "compose",
                "-f",
                compose_file_path,
                "-p",
                project.slug,
                "up",
                "-d",
                "--remove-orphans",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                logger.error(f"[DOCKER] Failed to start project: {error_msg}")
                raise RuntimeError(f"Docker Compose failed: {error_msg}")

            logger.info(f"[DOCKER] Project {project.slug} started successfully")

            # Connect Traefik to project network
            await self._connect_traefik_to_network(project.slug)

            # Build container URLs
            container_urls = {}
            for container in containers:
                service_name = self._sanitize_service_name(container.name)
                sanitized_name = f"{project.slug}-{service_name}"
                url = f"http://{sanitized_name}.{self.settings.app_domain}"
                container_urls[container.name] = url

            # Track activity in database
            await self.track_activity(user_id, str(project.id))

            return {
                "status": "running",
                "project_slug": project.slug,
                "network": f"tesslate-{project.slug}",
                "containers": container_urls,
                "compose_file": compose_file_path,
            }

        except Exception as e:
            logger.error(f"[DOCKER] Error starting project: {e}", exc_info=True)
            raise

    async def stop_project(self, project_slug: str, project_id: UUID, user_id: UUID) -> None:
        """Pause a project (HF-Spaces-style sleep).

        Runs ``docker compose stop`` which stops the containers but keeps
        them and the project network intact. A subsequent ``start_project``
        (``docker compose up -d``) resumes in seconds without recreating
        anything. Mirrors K8s scale-to-zero semantics.

        Full teardown (remove containers, network, volumes) lives in
        ``delete_project_namespace`` and is only called on uninstall.
        """
        compose_file_path = self._get_compose_file_path(project_slug)

        if not os.path.exists(compose_file_path):
            logger.warning(f"[DOCKER] Compose file not found for {project_slug}")
            return

        logger.info(f"[DOCKER] Pausing project {project_slug}...")

        try:
            process = await asyncio.create_subprocess_exec(
                "docker",
                "compose",
                "-f",
                compose_file_path,
                "-p",
                project_slug,
                "stop",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                logger.error(f"[DOCKER] Failed to stop project: {error_msg}")
                raise RuntimeError(f"Docker Compose failed: {error_msg}")

            logger.info(f"[DOCKER] Project {project_slug} paused successfully")

            # Disconnect Traefik from project network — safe even with
            # `compose stop` since we re-attach on the next start_project.
            await self._disconnect_traefik_from_network(project_slug)

        except Exception as e:
            logger.error(f"[DOCKER] Error stopping project: {e}", exc_info=True)
            raise

    async def delete_project_namespace(self, project_id: UUID, user_id: UUID) -> None:
        """Docker analogue of the K8s namespace delete: full teardown.

        Called on uninstall. Runs ``docker compose down`` (removes
        containers + network) and deletes the project directory. No-op if
        the project slug can't be resolved (caller handles via best-effort
        try/except).
        """
        _ = user_id  # interface parity with K8s orchestrator
        project_slug = await self._get_project_slug(project_id)
        if project_slug is None:
            logger.warning("[DOCKER] delete_project_namespace: no slug for project %s", project_id)
            return

        compose_file_path = self._get_compose_file_path(project_slug)
        if os.path.exists(compose_file_path):
            try:
                process = await asyncio.create_subprocess_exec(
                    "docker",
                    "compose",
                    "-f",
                    compose_file_path,
                    "-p",
                    project_slug,
                    "down",
                    "--remove-orphans",
                    "--volumes",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await process.communicate()
            except Exception:
                logger.exception("[DOCKER] compose down failed for %s (continuing)", project_slug)

        try:
            await self.delete_project_directory(project_slug)
        except Exception:
            logger.exception(
                "[DOCKER] delete_project_directory failed for %s (continuing)",
                project_slug,
            )

    async def restart_project(
        self, project, containers: list, connections: list, user_id: UUID, db: AsyncSession
    ) -> dict[str, Any]:
        """Restart all containers for a project."""
        await self.stop_project(project.slug, project.id, user_id)
        return await self.start_project(project, containers, connections, user_id, db)

    async def get_project_status(self, project_slug: str, project_id: UUID) -> dict[str, Any]:
        """Get status of all containers in a project."""
        compose_file_path = self._get_compose_file_path(project_slug)

        if not os.path.exists(compose_file_path):
            return {"status": "not_found", "containers": {}}

        try:
            process = await asyncio.create_subprocess_exec(
                "docker",
                "compose",
                "-f",
                compose_file_path,
                "-p",
                project_slug,
                "ps",
                "--format",
                "json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                return {"status": "error", "error": stderr.decode() if stderr else "Unknown error"}

            containers_status = {}
            if stdout:
                for line in stdout.decode().strip().split("\n"):
                    if line:
                        container_info = json.loads(line)
                        service_name = container_info["Service"]
                        is_running = container_info["State"] == "running"
                        # Include URL for running containers so frontend doesn't re-start them
                        container_url = (
                            f"http://{project_slug}-{service_name}.{self.settings.app_domain}"
                            if is_running
                            else None
                        )
                        containers_status[service_name] = {
                            "name": container_info["Name"],
                            "state": container_info["State"],
                            "status": container_info["Status"],
                            "running": is_running,
                            "url": container_url,
                        }

            all_running = (
                all(info["running"] for info in containers_status.values())
                if containers_status
                else False
            )

            return {
                "status": "running" if all_running else "partial",
                "containers": containers_status,
                "project_slug": project_slug,
            }

        except Exception as e:
            logger.error(f"[DOCKER] Error getting status: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}

    async def is_container_running(self, project_slug: str, container_name: str) -> bool:
        """
        Fast check if a specific container is running using Docker SDK.

        This is much faster than docker compose ps because it:
        - Uses Docker Python SDK (no subprocess spawn)
        - Checks single container (not all containers)
        - Returns boolean (no JSON parsing)

        Args:
            project_slug: Project slug
            container_name: Container name (will be sanitized)

        Returns:
            True if container is running, False otherwise
        """
        import docker

        service_name = self._resolve_service_name(container_name, project_slug)
        # Docker compose names containers as: {project}-{service}-1
        expected_container_name = f"{project_slug}-{service_name}-1"

        try:
            client = docker.from_env()
            container = client.containers.get(expected_container_name)
            return container.status == "running"
        except docker.errors.NotFound:
            return False
        except Exception as e:
            logger.debug(f"[DOCKER] Quick status check failed for {expected_container_name}: {e}")
            return False  # Fall back to full start flow

    # =========================================================================
    # INDIVIDUAL CONTAINER MANAGEMENT
    # =========================================================================

    async def start_container(
        self,
        project,
        container,
        all_containers: list,
        connections: list,
        user_id: UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """Start a single container in a project."""
        # Always regenerate compose file so env var changes and other
        # config updates are picked up on container restart.
        env_overrides = None
        if db:
            env_overrides = await build_env_overrides(db, project.id, all_containers)
        await self._write_compose_file(project, all_containers, connections, user_id, env_overrides)
        compose_file_path = self._get_compose_file_path(project.slug)

        service_name = self._sanitize_service_name(container.name)

        logger.info(f"[DOCKER] Starting container {container.name} (service: {service_name})...")

        process = await asyncio.create_subprocess_exec(
            "docker",
            "compose",
            "-f",
            compose_file_path,
            "-p",
            project.slug,
            "up",
            "-d",
            service_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            raise RuntimeError(f"Failed to start container: {error_msg}")

        logger.info(f"[DOCKER] Container {container.name} started")

        # Connect Traefik to network
        await self._connect_traefik_to_network(project.slug)

        sanitized_name = f"{project.slug}-{service_name}"
        url = f"http://{sanitized_name}.{self.settings.app_domain}"

        return {"status": "running", "container_name": container.name, "url": url}

    async def stop_container(
        self, project_slug: str, project_id: UUID, container_name: str, user_id: UUID
    ) -> None:
        """Stop a single container."""
        compose_file_path = self._get_compose_file_path(project_slug)

        if not os.path.exists(compose_file_path):
            raise FileNotFoundError(f"Compose file not found for {project_slug}")

        service_name = self._resolve_service_name(container_name, project_slug)

        logger.info(f"[DOCKER] Stopping container {container_name} (service: {service_name})...")

        process = await asyncio.create_subprocess_exec(
            "docker",
            "compose",
            "-f",
            compose_file_path,
            "-p",
            project_slug,
            "stop",
            service_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            raise RuntimeError(f"Failed to stop container: {error_msg}")

        logger.info(f"[DOCKER] Container {container_name} stopped")

    async def get_container_status(
        self, project_slug: str, project_id: UUID, container_name: str, user_id: UUID
    ) -> dict[str, Any]:
        """Get status of a single container."""
        project_status = await self.get_project_status(project_slug, project_id)

        if project_status["status"] == "not_found":
            return {"status": "not_found"}

        service_name = self._resolve_service_name(container_name, project_slug)
        container_info = project_status.get("containers", {}).get(service_name)

        if container_info:
            sanitized_name = f"{project_slug}-{service_name}"
            return {
                "status": "running" if container_info["running"] else "stopped",
                "url": f"http://{sanitized_name}.{self.settings.app_domain}"
                if container_info["running"]
                else None,
                **container_info,
            }

        return {"status": "not_found"}

    # =========================================================================
    # FILE OPERATIONS - Direct filesystem access to shared volume
    # Path: /projects/{project_slug}/{subdir?}/{file_path}
    # =========================================================================

    def get_project_path(self, project_slug: str) -> Path:
        """Get the filesystem path for a project."""
        return self.projects_path / project_slug

    def _safe_project_path(
        self, project_slug: str, file_path: str, subdir: str | None = None
    ) -> Path:
        """
        Resolve file_path and verify it stays within the project directory.

        Uses Path.resolve() to collapse all '..' and symlinks, then checks
        the resolved path is still under the project root. This is a
        containment check on the resolved absolute path, not pattern matching.

        Raises ValueError if the resolved path escapes the project boundary.
        """
        project_root = self.get_project_path(project_slug).resolve()

        base = project_root / subdir if subdir and subdir != "." else project_root

        resolved = (base / file_path).resolve()

        # Containment check: resolved path must be under the project root
        try:
            resolved.relative_to(project_root)
        except ValueError as err:
            raise ValueError(
                f"Path escapes project boundary: {file_path!r} "
                f"(resolved to {resolved}, outside {project_root})"
            ) from err

        return resolved

    async def ensure_project_directory(self, project_slug: str) -> Path:
        """Ensure the project directory exists."""
        project_path = self.get_project_path(project_slug)
        await aiofiles.os.makedirs(project_path, exist_ok=True)
        logger.debug(f"[DOCKER] Ensured project directory: {project_path}")
        return project_path

    async def delete_project_directory(self, project_slug: str) -> bool:
        """Delete a project's directory and all its contents."""
        project_path = self.get_project_path(project_slug)

        if not project_path.exists():
            logger.warning(f"[DOCKER] Project directory not found: {project_slug}")
            return False

        try:
            await asyncio.to_thread(shutil.rmtree, project_path)
            logger.info(f"[DOCKER] ✅ Deleted project directory: {project_slug}")
            return True
        except Exception as e:
            logger.error(f"[DOCKER] ❌ Failed to delete project directory {project_slug}: {e}")
            raise

    async def rename_directory(self, project_slug: str, old_name: str, new_name: str) -> bool:
        """Rename a subdirectory within a project."""
        project_path = self.get_project_path(project_slug)
        old_path = project_path / old_name
        new_path = project_path / new_name

        if not old_path.exists():
            raise FileNotFoundError(f"Directory '{old_name}' not found in project")
        if new_path.exists():
            raise FileExistsError(f"Directory '{new_name}' already exists in project")

        try:
            await asyncio.to_thread(shutil.move, str(old_path), str(new_path))
            logger.info(f"[DOCKER] ✅ Renamed directory: {old_name} -> {new_name}")
            return True
        except Exception as e:
            logger.error(f"[DOCKER] ❌ Failed to rename directory: {e}")
            raise

    async def copy_base_to_project(
        self,
        base_slug: str,
        project_slug: str,
        exclude_patterns: list[str] | None = None,
        target_subdir: str | None = None,
    ) -> None:
        """Copy a base from cache to a project directory."""
        if exclude_patterns is None:
            # node_modules is excluded — container installs deps on first boot
            # This avoids broken symlinks when copying between filesystems/platforms
            exclude_patterns = [
                ".git",
                "node_modules",
                ".next",
                "__pycache__",
                ".venv",
                "dist",
                "build",
                "*.pyc",
                ".DS_Store",
            ]

        target_display = f"{project_slug}/{target_subdir}" if target_subdir else project_slug
        logger.info(f"[DOCKER] Copying base {base_slug} to project {target_display}")

        cache_path = Path(f"/app/base-cache/{base_slug}")
        if not cache_path.exists():
            raise RuntimeError(f"Base cache not found: {cache_path}")

        if not any(cache_path.iterdir()):
            raise RuntimeError(f"Base cache {base_slug} is empty.")

        project_path = await self.ensure_project_directory(project_slug)
        destination_path = project_path / target_subdir if target_subdir else project_path

        if target_subdir:
            await aiofiles.os.makedirs(destination_path, exist_ok=True)

        try:

            def ignore_patterns(directory, files):
                ignored = []
                for f in files:
                    for pattern in exclude_patterns:
                        if pattern.startswith("*.") and f.endswith(pattern[1:]) or f == pattern:
                            ignored.append(f)
                            break
                return ignored

            await asyncio.to_thread(
                shutil.copytree,
                cache_path,
                destination_path,
                ignore=ignore_patterns,
                dirs_exist_ok=True,
                symlinks=True,  # Preserve symlinks (critical for node_modules/.bin/)
            )

            await asyncio.to_thread(self._fix_permissions, destination_path)
            logger.info(f"[DOCKER] ✅ Copied base {base_slug} to {target_display}")

        except Exception as e:
            logger.error(f"[DOCKER] ❌ Failed to copy base {base_slug}: {e}", exc_info=True)
            raise

    def _fix_permissions(self, path: Path) -> None:
        """Fix permissions for container user (uid 1000, gid 1000)."""
        try:
            for root, dirs, files in os.walk(path):
                os.chown(root, 1000, 1000)
                for d in dirs:
                    os.chown(os.path.join(root, d), 1000, 1000)
                for f in files:
                    os.chown(os.path.join(root, f), 1000, 1000)
        except (ImportError, PermissionError, KeyError, OSError):
            pass  # Skip on Windows or if permissions fail

    async def read_file(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        file_path: str,
        project_slug: str | None = None,
        subdir: str | None = None,
        volume_id: str | None = None,
        cache_node: str | None = None,
    ) -> str | None:
        """
        Read a file from a project directory.

        Args:
            project_slug: Project slug (preferred) - falls back to looking up by project_id
            file_path: Relative file path
            subdir: Optional subdirectory for multi-container projects (e.g., "frontend")
        """
        # Get project_slug if not provided
        if not project_slug:
            project_slug = await self._get_project_slug(project_id)
            if not project_slug:
                logger.error(f"[DOCKER] Could not find project slug for {project_id}")
                return None

        try:
            full_path = self._safe_project_path(project_slug, file_path, subdir)

            if not full_path.exists():
                return None

            async with aiofiles.open(full_path, encoding="utf-8") as f:
                return await f.read()

        except ValueError as e:
            logger.warning(f"[DOCKER] Path traversal blocked in read_file: {e}")
            return None
        except Exception as e:
            logger.error(f"[DOCKER] Failed to read file {file_path}: {e}")
            return None

    async def write_file(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        file_path: str,
        content: str,
        project_slug: str | None = None,
        subdir: str | None = None,
        volume_id: str | None = None,
        cache_node: str | None = None,
    ) -> bool:
        """
        Write a file to a project directory.

        Args:
            project_slug: Project slug (preferred)
            file_path: Relative file path
            content: File content
            subdir: Optional subdirectory for multi-container projects
        """
        if not project_slug:
            project_slug = await self._get_project_slug(project_id)
            if not project_slug:
                logger.error(f"[DOCKER] Could not find project slug for {project_id}")
                return False

        try:
            full_path = self._safe_project_path(project_slug, file_path, subdir)

            await aiofiles.os.makedirs(full_path.parent, exist_ok=True)

            async with aiofiles.open(full_path, "w", encoding="utf-8") as f:
                await f.write(content)

            logger.debug(f"[DOCKER] Wrote file {file_path} to project {project_slug}")
            return True

        except ValueError as e:
            logger.warning(f"[DOCKER] Path traversal blocked in write_file: {e}")
            return False
        except Exception as e:
            logger.error(f"[DOCKER] Failed to write file {file_path}: {e}")
            return False

    async def delete_file(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        file_path: str,
        project_slug: str | None = None,
        subdir: str | None = None,
    ) -> bool:
        """Delete a file from a project directory."""
        if not project_slug:
            project_slug = await self._get_project_slug(project_id)
            if not project_slug:
                return False

        try:
            full_path = self._safe_project_path(project_slug, file_path, subdir)

            if full_path.exists():
                await aiofiles.os.remove(full_path)
                logger.debug(f"[DOCKER] Deleted file {file_path}")
            return True

        except ValueError as e:
            logger.warning(f"[DOCKER] Path traversal blocked in delete_file: {e}")
            return False
        except Exception as e:
            logger.error(f"[DOCKER] Failed to delete file {file_path}: {e}")
            return False

    async def list_files(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        directory: str = ".",
        project_slug: str | None = None,
        max_files: int = 500,
    ) -> list[dict[str, Any]]:
        """List files in a project directory (excluding node_modules, .git, etc.)."""
        if not project_slug:
            project_slug = await self._get_project_slug(project_id)
            if not project_slug:
                return []

        try:
            walk_root = self._safe_project_path(project_slug, directory or ".")
        except ValueError as e:
            logger.warning(f"[DOCKER] Path traversal blocked in list_files: {e}")
            return []

        if not walk_root.exists():
            return []

        project_root = self.get_project_path(project_slug)
        files = []
        count = 0

        try:
            for root, dirs, filenames in os.walk(walk_root):
                dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]

                for filename in filenames:
                    if count >= max_files:
                        break
                    if filename in EXCLUDED_FILES:
                        continue

                    full_path = Path(root) / filename
                    rel_path = full_path.relative_to(project_root)

                    files.append({"path": str(rel_path), "name": filename, "type": "file"})
                    count += 1

                if count >= max_files:
                    break

            return files
        except Exception as e:
            logger.error(f"[DOCKER] Failed to list files: {e}")
            return []

    async def get_files_with_content(
        self,
        project_slug: str,
        max_files: int = 200,
        max_file_size: int = 100000,
        subdir: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get all files in a project with their content (for Monaco editor)."""
        try:
            project_path = self._safe_project_path(project_slug, subdir or ".")
        except ValueError as e:
            logger.warning(f"[DOCKER] Path traversal blocked in get_files_with_content: {e}")
            return []

        if not project_path.exists():
            return []

        files_with_content = []
        count = 0

        try:
            for root, dirs, filenames in os.walk(project_path):
                dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]

                # Detect empty directories (no files after exclusions, no remaining subdirs)
                non_excluded_files = [
                    f
                    for f in filenames
                    if f not in EXCLUDED_FILES
                    and (f.split(".")[-1].lower() if "." in f else "") not in BINARY_EXTENSIONS
                ]
                if not non_excluded_files and not dirs:
                    rel_path = Path(root).relative_to(project_path)
                    if str(rel_path) != ".":
                        files_with_content.append({"file_path": str(rel_path) + "/", "content": ""})

                for filename in filenames:
                    if count >= max_files:
                        break
                    if filename in EXCLUDED_FILES:
                        continue

                    ext = filename.split(".")[-1].lower() if "." in filename else ""
                    if ext in BINARY_EXTENSIONS:
                        continue

                    full_path = Path(root) / filename
                    rel_path = full_path.relative_to(project_path)

                    try:
                        file_size = full_path.stat().st_size
                        if file_size > max_file_size:
                            continue
                    except OSError:
                        continue

                    try:
                        async with aiofiles.open(full_path, encoding="utf-8") as f:
                            content = await f.read()

                        files_with_content.append({"file_path": str(rel_path), "content": content})
                        count += 1

                    except (OSError, UnicodeDecodeError):
                        continue

                if count >= max_files:
                    break

            logger.info(f"[DOCKER] Loaded {len(files_with_content)} files from {project_slug}")
            return files_with_content

        except Exception as e:
            logger.error(f"[DOCKER] Failed to get files with content: {e}")
            return []

    async def list_tree(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        subdir: str | None = None,
        project_slug: str | None = None,
    ) -> list[dict[str, Any]]:
        """Recursive filtered file tree via local filesystem."""
        if not project_slug:
            project_slug = await self._get_project_slug(project_id)
            if not project_slug:
                return []

        try:
            walk_root = self._safe_project_path(project_slug, subdir or ".")
        except ValueError as e:
            logger.warning(f"[DOCKER] Path traversal blocked in list_tree: {e}")
            return []

        if not walk_root.exists():
            return []

        entries: list[dict[str, Any]] = []
        try:
            for root, dirs, filenames in os.walk(walk_root):
                dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]

                rel_root = Path(root).relative_to(walk_root)

                # Emit directory entries (except root)
                for d in dirs:
                    dir_path = rel_root / d if str(rel_root) != "." else Path(d)
                    full = Path(root) / d
                    try:
                        st = full.stat()
                        entries.append(
                            {
                                "path": str(dir_path),
                                "name": d,
                                "is_dir": True,
                                "size": 0,
                                "mod_time": int(st.st_mtime),
                            }
                        )
                    except OSError:
                        entries.append(
                            {
                                "path": str(dir_path),
                                "name": d,
                                "is_dir": True,
                                "size": 0,
                                "mod_time": 0,
                            }
                        )

                for filename in filenames:
                    if filename in EXCLUDED_FILES:
                        continue
                    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
                    if ext in BINARY_EXTENSIONS:
                        continue

                    file_path = rel_root / filename if str(rel_root) != "." else Path(filename)
                    full = Path(root) / filename
                    try:
                        st = full.stat()
                        entries.append(
                            {
                                "path": str(file_path),
                                "name": filename,
                                "is_dir": False,
                                "size": st.st_size,
                                "mod_time": int(st.st_mtime),
                            }
                        )
                    except OSError:
                        continue

            return entries
        except Exception as e:
            logger.error(f"[DOCKER] Failed to list tree: {e}")
            return []

    async def read_file_content(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        file_path: str,
        subdir: str | None = None,
        project_slug: str | None = None,
    ) -> dict[str, Any] | None:
        """Read a single file from local filesystem."""
        if not project_slug:
            project_slug = await self._get_project_slug(project_id)
            if not project_slug:
                return None

        target = subdir + "/" + file_path if subdir else file_path
        try:
            full_path = self._safe_project_path(project_slug, target)
        except ValueError:
            return None

        if not full_path.exists() or not full_path.is_file():
            return None

        try:
            async with aiofiles.open(full_path, encoding="utf-8") as f:
                content = await f.read()
            return {"path": file_path, "content": content, "size": len(content)}
        except (OSError, UnicodeDecodeError):
            return None

    async def read_files_batch(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        paths: list[str],
        subdir: str | None = None,
        project_slug: str | None = None,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Batch-read multiple files from local filesystem."""
        if not project_slug:
            project_slug = await self._get_project_slug(project_id)
            if not project_slug:
                return [], list(paths)

        import asyncio

        async def _read_one(p: str) -> dict[str, Any] | None:
            return await self.read_file_content(
                user_id,
                project_id,
                container_name,
                p,
                subdir=subdir,
                project_slug=project_slug,
            )

        results = await asyncio.gather(*[_read_one(p) for p in paths], return_exceptions=True)
        files = []
        errors = []
        for p, result in zip(paths, results, strict=True):
            if isinstance(result, Exception) or result is None:
                errors.append(p)
            else:
                files.append(result)
        return files, errors

    async def project_exists(self, project_slug: str) -> bool:
        """Check if a project directory exists."""
        project_path = self.get_project_path(project_slug)
        return project_path.exists() and project_path.is_dir()

    async def project_has_files(self, project_slug: str, subdir: str | None = None) -> bool:
        """Check if a project (or subdirectory) has any files."""
        project_path = self.get_project_path(project_slug)
        if subdir:
            project_path = project_path / subdir

        if not project_path.exists():
            return False

        for _root, dirs, files in os.walk(project_path):
            dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
            if any(f for f in files if not f.startswith(".")):
                return True

        return False

    async def _get_project_slug(self, project_id: UUID) -> str | None:
        """Look up project slug from project_id."""
        from ...database import AsyncSessionLocal
        from ...models import Project

        try:
            async with AsyncSessionLocal() as db:
                from sqlalchemy import select

                result = await db.execute(select(Project).where(Project.id == project_id))
                project = result.scalar_one_or_none()
                return project.slug if project else None
        except Exception as e:
            logger.error(f"[DOCKER] Failed to get project slug: {e}")
            return None

    async def glob_files(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        pattern: str,
        directory: str = ".",
        project_slug: str | None = None,
    ) -> list[dict[str, Any]]:
        """Find files matching a glob pattern."""
        import fnmatch

        if not project_slug:
            project_slug = await self._get_project_slug(project_id)
            if not project_slug:
                return []

        project_path = self.get_project_path(project_slug)
        try:
            search_path = self._safe_project_path(project_slug, directory or ".")
        except ValueError as e:
            logger.warning(f"[DOCKER] Path traversal blocked in glob_files: {e}")
            return []

        matches = []
        try:
            if search_path.exists():
                for root, dirs, files in os.walk(search_path):
                    dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]

                    for filename in files:
                        if fnmatch.fnmatch(filename, pattern):
                            full_path = Path(root) / filename
                            rel_path = full_path.relative_to(project_path)
                            matches.append(
                                {
                                    "name": filename,
                                    "path": str(rel_path),
                                    "type": "file",
                                    "size": full_path.stat().st_size,
                                }
                            )

            return matches[:100]
        except Exception as e:
            logger.error(f"[DOCKER] Failed to glob files: {e}")
            return []

    async def grep_files(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        pattern: str,
        directory: str = ".",
        file_pattern: str = "*",
        case_sensitive: bool = True,
        max_results: int = 100,
        project_slug: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search file contents for a pattern."""
        import fnmatch

        if not project_slug:
            project_slug = await self._get_project_slug(project_id)
            if not project_slug:
                return []

        project_path = self.get_project_path(project_slug)
        try:
            search_path = self._safe_project_path(project_slug, directory or ".")
        except ValueError as e:
            logger.warning(f"[DOCKER] Path traversal blocked in grep_files: {e}")
            return []

        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            regex = re.compile(pattern, flags)
        except re.error as e:
            logger.error(f"[DOCKER] Invalid regex pattern: {e}")
            return []

        matches = []
        try:
            if search_path.exists():
                for root, dirs, files in os.walk(search_path):
                    dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]

                    for filename in files:
                        if not fnmatch.fnmatch(filename, file_pattern):
                            continue

                        full_path = Path(root) / filename
                        rel_path = full_path.relative_to(project_path)

                        try:
                            with open(full_path, errors="ignore") as f:
                                for line_num, line in enumerate(f, 1):
                                    if regex.search(line):
                                        matches.append(
                                            {
                                                "file": str(rel_path),
                                                "line": line_num,
                                                "content": line.strip()[:200],
                                                "match": True,
                                            }
                                        )

                                        if len(matches) >= max_results:
                                            return matches
                        except Exception:
                            continue

            return matches
        except Exception as e:
            logger.error(f"[DOCKER] Failed to grep files: {e}")
            return []

    # =========================================================================
    # SHELL OPERATIONS
    # =========================================================================

    async def execute_command(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str | None,
        command: list[str],
        timeout: int = 120,
        working_dir: str | None = None,
    ) -> str:
        """Execute a command in a container."""
        # Get container name from project
        # Docker Compose naming: {project_slug}-{service_name}-1
        from ...database import AsyncSessionLocal
        from ...models import Container as ContainerModel
        from ...models import Project

        async with AsyncSessionLocal() as db:
            from sqlalchemy import select

            result = await db.execute(select(Project).where(Project.id == project_id))
            project = result.scalar_one_or_none()

            # Resolve container_name when not provided
            if not container_name:
                result = await db.execute(
                    select(ContainerModel.name)
                    .where(ContainerModel.project_id == project_id)
                    .order_by(ContainerModel.created_at)
                    .limit(1)
                )
                container_name = result.scalar_one_or_none()

        if not project:
            raise RuntimeError(f"Project {project_id} not found")

        if not container_name:
            raise RuntimeError(f"No containers found for project {project_id}")

        service_name = self._resolve_service_name(container_name, project.slug)
        docker_container = f"{project.slug}-{service_name}"

        # Build command
        exec_cmd = ["docker", "exec"]
        if working_dir:
            exec_cmd.extend(["-w", f"/app/{working_dir}"])
        exec_cmd.append(docker_container)
        exec_cmd.extend(command)

        logger.info(f"[DOCKER] Executing: {' '.join(exec_cmd)}")

        try:
            process = await asyncio.create_subprocess_exec(
                *exec_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)

            output = stdout.decode() + stderr.decode()
            return output

        except TimeoutError:
            raise RuntimeError(f"Command timed out after {timeout} seconds") from None
        except Exception as e:
            raise RuntimeError(f"Command execution failed: {e}") from e

    async def is_container_ready(
        self, user_id: UUID, project_id: UUID, container_name: str
    ) -> dict[str, Any]:
        """Check if a container is ready for commands."""
        # Get project slug
        from ...database import AsyncSessionLocal
        from ...models import Project

        async with AsyncSessionLocal() as db:
            from sqlalchemy import select

            result = await db.execute(select(Project).where(Project.id == project_id))
            project = result.scalar_one_or_none()

        if not project:
            return {"ready": False, "message": "Project not found"}

        status = await self.get_container_status(project.slug, project_id, container_name, user_id)

        is_ready = status.get("status") == "running"
        return {
            "ready": is_ready,
            "message": "Container is ready"
            if is_ready
            else f"Container status: {status.get('status')}",
            **status,
        }

    # =========================================================================
    # ACTIVITY TRACKING (Database-based, consistent with K8s)
    # =========================================================================

    async def track_activity(
        self, user_id: UUID, project_id: str, container_name: str | None = None
    ) -> None:
        """Track activity in database (consistent with K8s)."""
        from datetime import datetime

        from sqlalchemy import update

        from ...database import AsyncSessionLocal
        from ...models import Project

        try:
            async with AsyncSessionLocal() as db:
                await db.execute(
                    update(Project)
                    .where(Project.id == UUID(project_id))
                    .values(last_activity=datetime.now(UTC))
                )
                await db.commit()
                logger.debug(f"[DOCKER] Activity tracked for project {project_id}")
        except Exception as e:
            logger.warning(f"[DOCKER] Failed to track activity: {e}")

    # =========================================================================
    # LOG STREAMING
    # =========================================================================

    async def stream_logs(
        self,
        project_id: UUID,
        user_id: UUID,
        container_id: UUID | None = None,
        tail_lines: int = 100,
    ) -> AsyncIterator[str]:
        import docker as docker_lib

        # Resolve container name
        if container_id:
            from sqlalchemy import select
            from sqlalchemy.orm import selectinload

            from ...database import AsyncSessionLocal
            from ...models import Container

            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Container)
                    .options(selectinload(Container.project))
                    .where(Container.id == container_id)
                )
                container_model = result.scalar_one_or_none()
                if not container_model:
                    logger.warning(f"[DOCKER] Container {container_id} not found in DB")
                    return
                # Compute the actual Docker container name the same way compose config does
                project_slug = container_model.project.slug
                service_name = self._sanitize_service_name(container_model.name)
                docker_container_name = f"{project_slug}-{service_name}"
        else:
            from ...utils.resource_naming import get_container_name

            docker_container_name = get_container_name(str(user_id), str(project_id))

        docker_client = docker_lib.from_env()
        stop_event = asyncio.Event()
        try:
            container = docker_client.containers.get(docker_container_name)
            log_stream = container.logs(
                stream=True, follow=True, stdout=True, stderr=True, tail=tail_lines
            )

            queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=1000)

            def _read_logs():
                try:
                    for line in log_stream:
                        if stop_event.is_set():
                            break
                        with contextlib.suppress(asyncio.QueueFull):
                            queue.put_nowait(line.decode("utf-8", errors="replace"))
                except Exception as e:
                    if not stop_event.is_set():
                        logger.error(f"[DOCKER] Log stream error: {e}")
                finally:
                    queue.put_nowait(None)

            asyncio.get_running_loop().run_in_executor(None, _read_logs)

            try:
                while True:
                    line = await queue.get()
                    if line is None:
                        break
                    yield line
            finally:
                stop_event.set()
        except docker_lib.errors.NotFound:
            logger.warning(
                f"[DOCKER] Container {docker_container_name} not found for log streaming"
            )
        finally:
            stop_event.set()
            docker_client.close()

    # =========================================================================
    # TRAEFIK INTEGRATION
    # =========================================================================

    async def _connect_traefik_to_network(self, project_slug: str) -> None:
        """Connect main Traefik directly to project network for routing."""
        network_name = f"tesslate-{project_slug}"

        try:
            logger.info(f"[DOCKER] Connecting tesslate-traefik to {network_name}...")

            connect_process = await asyncio.create_subprocess_exec(
                "docker",
                "network",
                "connect",
                network_name,
                "tesslate-traefik",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await connect_process.communicate()

            if connect_process.returncode == 0:
                logger.info(f"[DOCKER] tesslate-traefik connected to {network_name}")
            else:
                logger.debug(f"[DOCKER] tesslate-traefik already connected to {network_name}")

        except Exception as e:
            logger.warning(f"[DOCKER] Failed to connect Traefik to network: {e}")

    async def _disconnect_traefik_from_network(self, project_slug: str) -> None:
        """Disconnect Traefik from project network."""
        network_name = f"tesslate-{project_slug}"

        try:
            disconnect_process = await asyncio.create_subprocess_exec(
                "docker",
                "network",
                "disconnect",
                network_name,
                "tesslate-traefik",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await disconnect_process.communicate()

            if disconnect_process.returncode == 0:
                logger.info(f"[DOCKER] Traefik disconnected from {network_name}")
            else:
                logger.debug(f"[DOCKER] Traefik was not connected to {network_name}")

        except Exception as e:
            logger.warning(f"[DOCKER] Failed to disconnect Traefik from network: {e}")

    # =========================================================================
    # COMPOSE FILE GENERATION
    # =========================================================================

    async def _write_compose_file(
        self,
        project,
        containers: list,
        connections: list,
        user_id: UUID,
        env_overrides: dict[UUID, dict[str, str]] | None = None,
    ) -> str:
        """Generate and write docker-compose.yml file for a project."""
        compose_config = await self._generate_compose_config(
            project, containers, connections, user_id, env_overrides
        )

        compose_file_path = self._get_compose_file_path(project.slug)

        with open(compose_file_path, "w") as f:
            yaml.dump(compose_config, f, default_flow_style=False, sort_keys=False, width=1000000)

        logger.info(f"[DOCKER] Generated docker-compose.yml for project {project.slug}")
        return compose_file_path

    async def write_compose_file(
        self,
        project,
        containers: list,
        connections: list,
        user_id: UUID,
        env_overrides: dict[UUID, dict[str, str]] | None = None,
    ) -> str:
        """Public method to generate and write docker-compose.yml file."""
        return await self._write_compose_file(
            project, containers, connections, user_id, env_overrides
        )

    async def _generate_compose_config(
        self,
        project,
        containers: list,
        connections: list,
        user_id: UUID,
        env_overrides: dict[UUID, dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """
        Generate docker-compose.yml configuration from Container models.

        Features:
        - Project-specific network for complete isolation
        - Traefik integration for routing
        - Service containers (Postgres, Redis, etc.)
        - Base containers with TESSLATE.md config
        - Volume subpath isolation for security
        """
        # Create project-specific network for complete isolation
        network_name = f"tesslate-{project.slug}"

        # Base compose config with project-specific network
        compose_config = {
            "networks": {network_name: {"driver": "bridge", "name": network_name}},
            "services": {},
            "volumes": {},
        }

        # Build dependency map from connections
        dependencies_map = {}  # container_id -> [dependent_container_ids]
        for connection in connections:
            if connection.connection_type == "depends_on":
                target_id = str(connection.target_container_id)
                source_id = str(connection.source_container_id)

                if source_id not in dependencies_map:
                    dependencies_map[source_id] = []
                dependencies_map[source_id].append(target_id)

        # Generate service definitions for each container
        for container in containers:
            container_id = str(container.id)

            # Sanitize service name
            service_name = self._sanitize_service_name(container.name)

            # Handle service containers differently from base containers
            if container.container_type == "service":
                service_config = await self._generate_service_container_config(
                    project, container, service_name, network_name, user_id, env_overrides
                )
                if service_config:
                    compose_config["services"][service_name] = service_config["service"]
                    if "volume" in service_config:
                        compose_config["volumes"].update(service_config["volume"])
                continue

            # Base container logic
            base_image = "tesslate-devserver:latest"

            # Build volume mounts - mount entire project to /app
            # Each container uses working_dir to cd into its subdirectory
            # This matches K8s behavior where PVC is mounted at /app

            if self.use_volumes:
                # SECURE: Uses Docker Compose v2.23.0+ subpath feature
                # Mount entire project directory to /app
                volumes = [
                    {
                        "type": "volume",
                        "source": "tesslate-projects-data",
                        "target": "/app",
                        "volume": {"subpath": project.slug},
                    }
                ]
                project_work_dir = "/app"
            else:
                # Legacy bind mounts - mount entire project
                project_dir = f"users/{user_id}/{project.id}"
                container_path = f"/app/{project_dir}"
                host_path = self._convert_to_host_path(container_path)

                volumes = [f"{host_path}:/app"]
                project_work_dir = "/app"

            # Build environment variables
            if env_overrides and container.id in env_overrides:
                environment = env_overrides[container.id].copy()
            else:
                environment = (container.environment_vars or {}).copy()
            environment.update(
                {
                    "PROJECT_ID": str(project.id),
                    "CONTAINER_ID": str(container.id),
                    "CONTAINER_NAME": container.name,
                }
            )

            # Build ports
            ports = []
            if container.port and container.internal_port:
                ports.append(f"{container.port}:{container.internal_port}")

            # Build depends_on from connections
            depends_on = []
            if container_id in dependencies_map:
                for dep_id in dependencies_map[container_id]:
                    dep_container = next((c for c in containers if str(c.id) == dep_id), None)
                    if dep_container:
                        dep_service_name = self._sanitize_service_name(dep_container.name)
                        depends_on.append(dep_service_name)

            sanitized_container_name = f"{project.slug}-{service_name}"

            # Get startup command and port from TESSLATE.md
            startup_command, container_port = await self._get_container_config(project, container)

            # Add Traefik labels for routing
            labels = {
                "traefik.enable": "true",
                "com.tesslate.routable": "true",  # For Traefik discovery
                "traefik.docker.network": network_name,  # Use project network
                f"traefik.http.routers.{sanitized_container_name}.rule": f"Host(`{sanitized_container_name}.{self.settings.app_domain}`)",
                f"traefik.http.services.{sanitized_container_name}.loadbalancer.server.port": str(
                    container_port
                ),
                "com.tesslate.project": project.slug,
                "com.tesslate.container": container.name,
                "com.tesslate.user": str(user_id),
            }

            # Determine working directory
            if container.directory and container.directory != ".":
                working_dir = f"{project_work_dir}/{container.directory}"
            else:
                working_dir = project_work_dir

            # Build service definition
            service_config = {
                "image": base_image,
                "container_name": sanitized_container_name,
                "user": "1000:1000",  # Run as non-root
                "working_dir": working_dir,
                "networks": [network_name],  # Only project network
                "volumes": volumes,
                "environment": environment,
                "labels": labels,
                "restart": "unless-stopped",
                "command": startup_command,
                # Security: Block access to internal services
                "extra_hosts": [
                    "tesslate-orchestrator:127.0.0.1",
                    "tesslate-postgres:127.0.0.1",
                    "tesslate-redis:127.0.0.1",
                    "postgres:127.0.0.1",
                    "redis:127.0.0.1",
                ],
            }

            if ports:
                service_config["ports"] = ports

            if depends_on:
                service_config["depends_on"] = depends_on

            compose_config["services"][service_name] = service_config

        # Add shared projects-data volume as external
        if self.use_volumes:
            compose_config["volumes"]["tesslate-projects-data"] = {
                "external": True,
                "name": "tesslate-projects-data",
            }

        return compose_config

    async def _generate_service_container_config(
        self,
        project,
        container,
        service_name: str,
        network_name: str,
        user_id: UUID,
        env_overrides: dict[UUID, dict[str, str]] | None = None,
    ) -> dict[str, Any] | None:
        """Generate config for service containers (Postgres, Redis, etc.)."""
        from ...services.service_definitions import ServiceType, get_service

        service_def = get_service(container.service_slug)
        if not service_def:
            logger.error(f"[DOCKER] Service '{container.service_slug}' not found, skipping")
            return None

        # Skip external-only services
        is_external_only = service_def.service_type == ServiceType.EXTERNAL
        is_deployed_externally = getattr(container, "deployment_mode", "container") == "external"

        if is_external_only or is_deployed_externally:
            logger.info(f"[DOCKER] Skipping external service '{container.service_slug}'")
            return None

        sanitized_container_name = f"{project.slug}-{service_name}"
        service_volume_name = f"{project.slug}-{container.service_slug}-data"

        # Build volume mounts
        volume_mounts = []
        for volume_path in service_def.volumes:
            volume_mounts.append(f"{service_volume_name}:{volume_path}")

        # Build environment
        environment = service_def.environment_vars.copy()
        if env_overrides and container.id in env_overrides:
            environment.update(env_overrides[container.id])

        # Build labels
        labels = {
            "com.tesslate.project": project.slug,
            "com.tesslate.container": container.name,
            "com.tesslate.user": str(user_id),
            "com.tesslate.service": container.service_slug,
        }

        # Only add Traefik routing for HTTP services (not databases)
        if service_def.category in ["proxy", "storage", "search"]:
            labels.update(
                {
                    "traefik.enable": "true",
                    f"traefik.http.routers.{sanitized_container_name}.rule": f"Host(`{sanitized_container_name}.{self.settings.app_domain}`)",
                    f"traefik.http.services.{sanitized_container_name}.loadbalancer.server.port": str(
                        service_def.internal_port
                    ),
                }
            )
        else:
            labels["traefik.enable"] = "false"

        service_config = {
            "image": service_def.docker_image,
            "container_name": sanitized_container_name,
            "networks": [network_name],
            "volumes": volume_mounts,
            "environment": environment,
            "labels": labels,
            "restart": "unless-stopped",
        }

        if service_def.command:
            service_config["command"] = service_def.command

        if service_def.health_check:
            service_config["healthcheck"] = service_def.health_check

        logger.info(f"[DOCKER] Added service container: {container.service_slug}")

        return {
            "service": service_config,
            "volume": {service_volume_name: {"name": service_volume_name}},
        }

    async def _get_container_config(self, project, container) -> tuple:
        """
        Get startup command and port from DB record or .tesslate/config.json.

        Priority:
        1. Container DB record (startup_command set by setup-config or project creation)
        2. .tesslate/config.json
        3. Generic fallback (sleep infinity)

        Returns:
            (startup_command, port)
        """
        from ...services.base_config_parser import (
            get_app_startup_config,
            get_node_modules_fix_prefix,
        )

        # Priority 1: Container DB record (set by setup-config or project creation)
        if container.startup_command:
            port = container.effective_port
            deps_prefix = get_node_modules_fix_prefix()
            command = ["sh", "-c", deps_prefix + container.startup_command]
            logger.info(
                f"[DOCKER] Using startup_command from DB for '{container.name}': port={port}"
            )
            return command, port

        # Priority 2: .tesslate/config.json (unified config)
        if self.use_volumes:
            project_path = f"/projects/{project.slug}"
            try:
                command, port = get_app_startup_config(project_path, container.name)
                logger.info(f"[DOCKER] Using config for '{container.name}': port={port}")
                return command, port
            except Exception as e:
                logger.debug(f"[DOCKER] Could not use unified config: {e}")

        # Priority 3: Generic fallback
        container_port = container.effective_port
        logger.info(f"[DOCKER] No config found for '{container.name}', using sleep infinity")
        return ["sh", "-c", "sleep infinity"], container_port


# Singleton instance
_docker_orchestrator: DockerOrchestrator | None = None


def get_docker_orchestrator() -> DockerOrchestrator:
    """Get the singleton Docker orchestrator instance."""
    global _docker_orchestrator

    if _docker_orchestrator is None:
        use_volumes = os.getenv("USE_DOCKER_VOLUMES", "true").lower() == "true"
        _docker_orchestrator = DockerOrchestrator(use_volumes=use_volumes)

    return _docker_orchestrator
