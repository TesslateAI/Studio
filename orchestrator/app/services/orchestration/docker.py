"""
Docker Orchestrator

Docker Compose-based container orchestration for local development.
Implements the BaseOrchestrator interface for Docker deployments.
"""

import os
import re
import yaml
import asyncio
import logging
import json
import socket
import subprocess
import time
from typing import Dict, List, Any, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from .base import BaseOrchestrator
from .deployment_mode import DeploymentMode

logger = logging.getLogger(__name__)


class DockerOrchestrator(BaseOrchestrator):
    """
    Docker Compose orchestrator for multi-container projects.

    Features:
    - Dynamic docker-compose.yml generation from Container models
    - Project-specific Docker networks for isolation
    - Traefik integration for routing
    - Volume vs bind mount support
    - Regional Traefik manager for multi-region routing
    """

    def __init__(self, use_volumes: bool = True):
        from ...config import get_settings
        self.settings = get_settings()

        self.compose_files_dir = os.path.abspath("docker-compose-projects")
        os.makedirs(self.compose_files_dir, exist_ok=True)

        self.host_users_base = self._detect_host_users_path()
        self.use_volumes = use_volumes

        # Activity tracking for cleanup
        self.activity_tracker: Dict[str, float] = {}
        self.paused_at_tracker: Dict[str, float] = {}

        logger.info(f"[DOCKER] Docker Compose orchestrator initialized")
        logger.info(f"[DOCKER] Storage mode: {'VOLUMES' if use_volumes else 'BIND_MOUNTS'}")
        logger.info(f"[DOCKER] Compose files directory: {self.compose_files_dir}")

    @property
    def deployment_mode(self) -> DeploymentMode:
        return DeploymentMode.DOCKER

    # =========================================================================
    # INTERNAL HELPERS
    # =========================================================================

    def _detect_host_users_path(self) -> str:
        """Detect the host path for /app/users (for Docker-in-Docker)."""
        if os.path.exists('/.dockerenv'):
            try:
                result = subprocess.run(
                    ["docker", "inspect", "-f", "{{ json .Mounts }}", socket.gethostname()],
                    capture_output=True,
                    text=True,
                    timeout=3
                )

                if result.returncode == 0 and result.stdout.strip():
                    mounts = json.loads(result.stdout.strip())
                    for mount in mounts:
                        if mount.get('Destination') == '/app/users':
                            return mount.get('Source')

                    fallback = "/root/Tesslate-Studio/orchestrator/users"
                    logger.warning(f"[DOCKER] Could not detect /app/users mount, using fallback: {fallback}")
                    return fallback
                else:
                    fallback = "/root/Tesslate-Studio/orchestrator/users"
                    logger.warning(f"[DOCKER] Docker inspect failed, using fallback: {fallback}")
                    return fallback

            except Exception as e:
                fallback = "/root/Tesslate-Studio/orchestrator/users"
                logger.warning(f"[DOCKER] Error detecting host paths: {e}, using fallback: {fallback}")
                return fallback
        else:
            host_path = os.path.abspath("users")
            logger.info(f"[DOCKER] Running on host, users base: {host_path}")
            return host_path

    def _convert_to_host_path(self, container_path: str) -> str:
        """Convert container path to host path for Docker-in-Docker."""
        if container_path.startswith('/app/users/'):
            relative_path = container_path[11:]
            host_path = os.path.join(self.host_users_base, relative_path)
            return host_path
        return container_path

    def _get_compose_file_path(self, project_slug: str) -> str:
        """Get the path to the docker-compose.yml file for a project."""
        return os.path.join(self.compose_files_dir, f"{project_slug}.yml")

    def _get_project_key(self, user_id: UUID, project_id: str) -> str:
        """Generate unique project key for tracking."""
        return f"user-{user_id}-project-{project_id}"

    def _sanitize_service_name(self, name: str) -> str:
        """Sanitize a name for Docker Compose service naming."""
        service_name = name.lower().replace(' ', '-').replace('_', '-').replace('.', '-')
        service_name = ''.join(c for c in service_name if c.isalnum() or c == '-')
        service_name = re.sub(r'-+', '-', service_name).strip('-')
        return service_name

    # =========================================================================
    # PROJECT LIFECYCLE
    # =========================================================================

    async def start_project(
        self,
        project,
        containers: List,
        connections: List,
        user_id: UUID,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Start all containers for a project using Docker Compose."""
        compose_file_path = await self._write_compose_file(
            project, containers, connections, user_id
        )

        logger.info(f"[DOCKER] Starting project {project.slug}...")

        try:
            process = await asyncio.create_subprocess_exec(
                'docker', 'compose',
                '-f', compose_file_path,
                '-p', project.slug,
                'up', '-d',
                '--remove-orphans',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
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
                url = f"http://{sanitized_name}.localhost"
                container_urls[container.name] = url

            # Track activity
            project_key = self._get_project_key(user_id, str(project.id))
            self.activity_tracker[project_key] = time.time()

            return {
                'status': 'running',
                'project_slug': project.slug,
                'network': f"tesslate-{project.slug}",
                'containers': container_urls,
                'compose_file': compose_file_path
            }

        except Exception as e:
            logger.error(f"[DOCKER] Error starting project: {e}", exc_info=True)
            raise

    async def stop_project(
        self,
        project_slug: str,
        project_id: UUID,
        user_id: UUID
    ) -> None:
        """Stop all containers for a project using Docker Compose."""
        compose_file_path = self._get_compose_file_path(project_slug)

        if not os.path.exists(compose_file_path):
            logger.warning(f"[DOCKER] Compose file not found for {project_slug}")
            return

        logger.info(f"[DOCKER] Stopping project {project_slug}...")

        try:
            process = await asyncio.create_subprocess_exec(
                'docker', 'compose',
                '-f', compose_file_path,
                '-p', project_slug,
                'down',
                '--remove-orphans',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                logger.error(f"[DOCKER] Failed to stop project: {error_msg}")
                raise RuntimeError(f"Docker Compose failed: {error_msg}")

            logger.info(f"[DOCKER] Project {project_slug} stopped successfully")

            # Disconnect Traefik from project network
            await self._disconnect_traefik_from_network(project_slug)

            # Clean up tracking
            project_key = self._get_project_key(user_id, str(project_id))
            self.activity_tracker.pop(project_key, None)
            self.paused_at_tracker.pop(project_key, None)

        except Exception as e:
            logger.error(f"[DOCKER] Error stopping project: {e}", exc_info=True)
            raise

    async def restart_project(
        self,
        project,
        containers: List,
        connections: List,
        user_id: UUID,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Restart all containers for a project."""
        await self.stop_project(project.slug, project.id, user_id)
        return await self.start_project(project, containers, connections, user_id, db)

    async def get_project_status(
        self,
        project_slug: str,
        project_id: UUID
    ) -> Dict[str, Any]:
        """Get status of all containers in a project."""
        compose_file_path = self._get_compose_file_path(project_slug)

        if not os.path.exists(compose_file_path):
            return {'status': 'not_found', 'containers': {}}

        try:
            process = await asyncio.create_subprocess_exec(
                'docker', 'compose',
                '-f', compose_file_path,
                '-p', project_slug,
                'ps', '--format', 'json',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                return {'status': 'error', 'error': stderr.decode() if stderr else "Unknown error"}

            containers_status = {}
            if stdout:
                for line in stdout.decode().strip().split('\n'):
                    if line:
                        container_info = json.loads(line)
                        containers_status[container_info['Service']] = {
                            'name': container_info['Name'],
                            'state': container_info['State'],
                            'status': container_info['Status'],
                            'running': container_info['State'] == 'running'
                        }

            all_running = all(
                info['running'] for info in containers_status.values()
            ) if containers_status else False

            return {
                'status': 'running' if all_running else 'partial',
                'containers': containers_status,
                'project_slug': project_slug
            }

        except Exception as e:
            logger.error(f"[DOCKER] Error getting status: {e}", exc_info=True)
            return {'status': 'error', 'error': str(e)}

    # =========================================================================
    # INDIVIDUAL CONTAINER MANAGEMENT
    # =========================================================================

    async def start_container(
        self,
        project,
        container,
        all_containers: List,
        connections: List,
        user_id: UUID,
        db: AsyncSession
    ) -> Dict[str, Any]:
        """Start a single container in a project."""
        compose_file_path = self._get_compose_file_path(project.slug)

        if not os.path.exists(compose_file_path):
            # Generate compose file if it doesn't exist
            await self._write_compose_file(project, all_containers, connections, user_id)

        service_name = self._sanitize_service_name(container.name)

        logger.info(f"[DOCKER] Starting container {container.name} (service: {service_name})...")

        process = await asyncio.create_subprocess_exec(
            'docker', 'compose',
            '-f', compose_file_path,
            '-p', project.slug,
            'up', '-d', service_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            raise RuntimeError(f"Failed to start container: {error_msg}")

        logger.info(f"[DOCKER] Container {container.name} started")

        # Connect Traefik to network
        await self._connect_traefik_to_network(project.slug)

        sanitized_name = f"{project.slug}-{service_name}"
        url = f"http://{sanitized_name}.localhost"

        return {
            'status': 'running',
            'container_name': container.name,
            'url': url
        }

    async def stop_container(
        self,
        project_slug: str,
        project_id: UUID,
        container_name: str,
        user_id: UUID
    ) -> None:
        """Stop a single container."""
        compose_file_path = self._get_compose_file_path(project_slug)

        if not os.path.exists(compose_file_path):
            raise FileNotFoundError(f"Compose file not found for {project_slug}")

        service_name = self._sanitize_service_name(container_name)

        logger.info(f"[DOCKER] Stopping container {container_name} (service: {service_name})...")

        process = await asyncio.create_subprocess_exec(
            'docker', 'compose',
            '-f', compose_file_path,
            '-p', project_slug,
            'stop', service_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            raise RuntimeError(f"Failed to stop container: {error_msg}")

        logger.info(f"[DOCKER] Container {container_name} stopped")

    async def get_container_status(
        self,
        project_slug: str,
        project_id: UUID,
        container_name: str,
        user_id: UUID
    ) -> Dict[str, Any]:
        """Get status of a single container."""
        project_status = await self.get_project_status(project_slug, project_id)

        if project_status['status'] == 'not_found':
            return {'status': 'not_found'}

        service_name = self._sanitize_service_name(container_name)
        container_info = project_status.get('containers', {}).get(service_name)

        if container_info:
            sanitized_name = f"{project_slug}-{service_name}"
            return {
                'status': 'running' if container_info['running'] else 'stopped',
                'url': f"http://{sanitized_name}.localhost" if container_info['running'] else None,
                **container_info
            }

        return {'status': 'not_found'}

    # =========================================================================
    # FILE OPERATIONS
    # =========================================================================

    async def read_file(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        file_path: str
    ) -> Optional[str]:
        """Read a file from a container."""
        # In Docker mode, files are on the shared volume accessible from orchestrator
        # Use the projects data volume path
        project_dir = f"/projects/{project_id}"
        full_path = os.path.join(project_dir, file_path)

        try:
            if os.path.exists(full_path):
                with open(full_path, 'r') as f:
                    return f.read()
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
        content: str
    ) -> bool:
        """Write a file to a container."""
        project_dir = f"/projects/{project_id}"
        full_path = os.path.join(project_dir, file_path)

        try:
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, 'w') as f:
                f.write(content)
            return True
        except Exception as e:
            logger.error(f"[DOCKER] Failed to write file {file_path}: {e}")
            return False

    async def delete_file(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        file_path: str
    ) -> bool:
        """Delete a file from a container."""
        project_dir = f"/projects/{project_id}"
        full_path = os.path.join(project_dir, file_path)

        try:
            if os.path.exists(full_path):
                os.remove(full_path)
            return True
        except Exception as e:
            logger.error(f"[DOCKER] Failed to delete file {file_path}: {e}")
            return False

    async def list_files(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        directory: str = "."
    ) -> List[Dict[str, Any]]:
        """List files in a directory."""
        project_dir = f"/projects/{project_id}"
        full_path = os.path.join(project_dir, directory)

        try:
            files = []
            if os.path.exists(full_path):
                for entry in os.scandir(full_path):
                    # Skip hidden files and node_modules
                    if entry.name.startswith('.') or entry.name == 'node_modules':
                        continue

                    files.append({
                        'name': entry.name,
                        'type': 'directory' if entry.is_dir() else 'file',
                        'size': entry.stat().st_size if entry.is_file() else 0,
                        'path': os.path.join(directory, entry.name) if directory != "." else entry.name
                    })
            return files
        except Exception as e:
            logger.error(f"[DOCKER] Failed to list files in {directory}: {e}")
            return []

    async def glob_files(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        pattern: str,
        directory: str = "."
    ) -> List[Dict[str, Any]]:
        """Find files matching a glob pattern."""
        import fnmatch

        project_dir = f"/projects/{project_id}"
        search_path = os.path.join(project_dir, directory)

        matches = []
        try:
            if os.path.exists(search_path):
                for root, dirs, files in os.walk(search_path):
                    # Skip common excluded directories
                    dirs[:] = [d for d in dirs if d not in ['node_modules', '.git', '__pycache__', '.next', 'dist', 'build']]

                    for filename in files:
                        if fnmatch.fnmatch(filename, pattern):
                            full_path = os.path.join(root, filename)
                            rel_path = os.path.relpath(full_path, project_dir)
                            matches.append({
                                'name': filename,
                                'path': rel_path,
                                'type': 'file',
                                'size': os.path.getsize(full_path)
                            })

            return matches[:100]  # Limit results
        except Exception as e:
            logger.error(f"[DOCKER] Failed to glob files with pattern {pattern}: {e}")
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
        max_results: int = 100
    ) -> List[Dict[str, Any]]:
        """Search file contents for a pattern."""
        import re
        import fnmatch

        project_dir = f"/projects/{project_id}"
        search_path = os.path.join(project_dir, directory)

        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            regex = re.compile(pattern, flags)
        except re.error as e:
            logger.error(f"[DOCKER] Invalid regex pattern: {e}")
            return []

        matches = []
        try:
            if os.path.exists(search_path):
                for root, dirs, files in os.walk(search_path):
                    # Skip common excluded directories
                    dirs[:] = [d for d in dirs if d not in ['node_modules', '.git', '__pycache__', '.next', 'dist', 'build']]

                    for filename in files:
                        if not fnmatch.fnmatch(filename, file_pattern):
                            continue

                        full_path = os.path.join(root, filename)
                        rel_path = os.path.relpath(full_path, project_dir)

                        try:
                            with open(full_path, 'r', errors='ignore') as f:
                                for line_num, line in enumerate(f, 1):
                                    if regex.search(line):
                                        matches.append({
                                            'file': rel_path,
                                            'line': line_num,
                                            'content': line.strip()[:200],  # Truncate long lines
                                            'match': True
                                        })

                                        if len(matches) >= max_results:
                                            return matches
                        except Exception:
                            continue  # Skip binary/unreadable files

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
        container_name: str,
        command: List[str],
        timeout: int = 120,
        working_dir: Optional[str] = None
    ) -> str:
        """Execute a command in a container."""
        # Get container name from project
        # Docker Compose naming: {project_slug}-{service_name}-1
        from ...models import Project
        from ...database import async_session_maker

        async with async_session_maker() as db:
            from sqlalchemy import select
            result = await db.execute(
                select(Project).where(Project.id == project_id)
            )
            project = result.scalar_one_or_none()

        if not project:
            raise RuntimeError(f"Project {project_id} not found")

        service_name = self._sanitize_service_name(container_name)
        docker_container = f"{project.slug}-{service_name}"

        # Build command
        exec_cmd = ['docker', 'exec']
        if working_dir:
            exec_cmd.extend(['-w', f'/app/{working_dir}'])
        exec_cmd.append(docker_container)
        exec_cmd.extend(command)

        logger.info(f"[DOCKER] Executing: {' '.join(exec_cmd)}")

        try:
            process = await asyncio.create_subprocess_exec(
                *exec_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )

            output = stdout.decode() + stderr.decode()
            return output

        except asyncio.TimeoutError:
            raise RuntimeError(f"Command timed out after {timeout} seconds")
        except Exception as e:
            raise RuntimeError(f"Command execution failed: {e}")

    async def is_container_ready(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str
    ) -> Dict[str, Any]:
        """Check if a container is ready for commands."""
        # Get project slug
        from ...models import Project
        from ...database import async_session_maker

        async with async_session_maker() as db:
            from sqlalchemy import select
            result = await db.execute(
                select(Project).where(Project.id == project_id)
            )
            project = result.scalar_one_or_none()

        if not project:
            return {'ready': False, 'message': 'Project not found'}

        status = await self.get_container_status(
            project.slug, project_id, container_name, user_id
        )

        is_ready = status.get('status') == 'running'
        return {
            'ready': is_ready,
            'message': 'Container is ready' if is_ready else f"Container status: {status.get('status')}",
            **status
        }

    # =========================================================================
    # ACTIVITY TRACKING
    # =========================================================================

    def track_activity(
        self,
        user_id: UUID,
        project_id: str,
        container_name: Optional[str] = None
    ) -> None:
        """Track activity for idle cleanup."""
        project_key = self._get_project_key(user_id, project_id)
        self.activity_tracker[project_key] = time.time()
        logger.debug(f"[DOCKER] Activity tracked for {project_key}")

    # =========================================================================
    # CLEANUP
    # =========================================================================

    async def cleanup_idle_environments(
        self,
        idle_timeout_minutes: int = 30
    ) -> List[str]:
        """Two-tier cleanup for Docker environments."""
        logger.info("[DOCKER] Starting idle environment cleanup...")

        cleaned = []
        current_time = time.time()
        idle_timeout_seconds = idle_timeout_minutes * 60

        # Check all tracked environments
        for project_key, last_activity in list(self.activity_tracker.items()):
            idle_time = current_time - last_activity
            idle_minutes = idle_time / 60

            if idle_time > idle_timeout_seconds:
                logger.info(f"[DOCKER] Cleaning up idle environment: {project_key} (idle {idle_minutes:.1f} min)")
                cleaned.append(project_key)

        logger.info(f"[DOCKER] Cleanup completed: {len(cleaned)} environments")
        return cleaned

    # =========================================================================
    # TRAEFIK INTEGRATION
    # =========================================================================

    async def _connect_traefik_to_network(self, project_slug: str) -> None:
        """Connect Traefik to project network for routing."""
        from ..regional_traefik_manager import get_regional_traefik_manager

        network_name = f"tesslate-{project_slug}"
        regional_manager = get_regional_traefik_manager()

        try:
            regional_index = await regional_manager.ensure_regional_for_project(project_slug)
            regional_traefik_name = regional_manager.get_regional_traefik_name(regional_index)

            logger.info(f"[DOCKER] Connecting {regional_traefik_name} to network {network_name}...")

            connect_process = await asyncio.create_subprocess_exec(
                'docker', 'network', 'connect', network_name, regional_traefik_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await connect_process.communicate()

            if connect_process.returncode == 0:
                logger.info(f"[DOCKER] {regional_traefik_name} connected to {network_name}")
            else:
                logger.debug(f"[DOCKER] {regional_traefik_name} already connected to {network_name}")

        except Exception as e:
            logger.warning(f"[DOCKER] Failed to connect Traefik to network: {e}")

    async def _disconnect_traefik_from_network(self, project_slug: str) -> None:
        """Disconnect Traefik from project network."""
        network_name = f"tesslate-{project_slug}"

        try:
            disconnect_process = await asyncio.create_subprocess_exec(
                'docker', 'network', 'disconnect', network_name, 'tesslate-traefik',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
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
        containers: List,
        connections: List,
        user_id: UUID
    ) -> str:
        """Generate and write docker-compose.yml file for a project."""
        compose_config = await self._generate_compose_config(
            project, containers, connections, user_id
        )

        compose_file_path = self._get_compose_file_path(project.slug)

        with open(compose_file_path, 'w') as f:
            yaml.dump(compose_config, f, default_flow_style=False, sort_keys=False, width=1000000)

        logger.info(f"[DOCKER] Generated docker-compose.yml for project {project.slug}")
        return compose_file_path

    async def write_compose_file(
        self,
        project,
        containers: List,
        connections: List,
        user_id: UUID
    ) -> str:
        """Public method to generate and write docker-compose.yml file."""
        return await self._write_compose_file(project, containers, connections, user_id)

    async def _generate_compose_config(
        self,
        project,
        containers: List,
        connections: List,
        user_id: UUID
    ) -> Dict[str, Any]:
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

        # Base compose config with ONLY project-specific network
        compose_config = {
            'networks': {
                network_name: {
                    'driver': 'bridge',
                    'name': network_name
                },
                # Regional Traefik network for routing (external)
                'tesslate-regional-traefik-network': {
                    'external': True
                }
            },
            'services': {},
            'volumes': {}
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
                    project, container, service_name, network_name, user_id
                )
                if service_config:
                    compose_config['services'][service_name] = service_config['service']
                    if 'volume' in service_config:
                        compose_config['volumes'].update(service_config['volume'])
                continue

            # Base container logic
            base_image = "tesslate-devserver:latest"

            # Build volume mounts with subpath isolation
            if self.use_volumes:
                # SECURE: Uses Docker Compose v2.23.0+ subpath feature
                volumes = [
                    {
                        'type': 'volume',
                        'source': 'tesslate-projects-data',
                        'target': '/app',
                        'volume': {
                            'subpath': project.slug
                        }
                    }
                ]
                project_work_dir = "/app"
            else:
                # Legacy bind mounts
                project_dir = f"users/{user_id}/{project.id}"
                container_dir = container.directory
                container_path = f"/app/{project_dir}/{container_dir}"
                host_path = self._convert_to_host_path(container_path)

                volumes = [f"{host_path}:/app"]
                project_work_dir = "/app"

            # Build environment variables
            environment = container.environment_vars or {}
            environment.update({
                'PROJECT_ID': str(project.id),
                'CONTAINER_ID': str(container.id),
                'CONTAINER_NAME': container.name,
            })

            # Build ports
            ports = []
            if container.port and container.internal_port:
                ports.append(f"{container.port}:{container.internal_port}")

            # Build depends_on from connections
            depends_on = []
            if container_id in dependencies_map:
                for dep_id in dependencies_map[container_id]:
                    dep_container = next(
                        (c for c in containers if str(c.id) == dep_id),
                        None
                    )
                    if dep_container:
                        dep_service_name = self._sanitize_service_name(dep_container.name)
                        depends_on.append(dep_service_name)

            sanitized_container_name = f"{project.slug}-{service_name}"

            # Get startup command and port from TESSLATE.md
            startup_command, container_port = await self._get_container_config(
                project, container
            )

            # Add Traefik labels for routing
            labels = {
                'traefik.enable': 'true',
                'traefik.docker.network': 'tesslate-regional-traefik-network',
                f'traefik.http.routers.{sanitized_container_name}.rule':
                    f'Host(`{sanitized_container_name}.localhost`)',
                f'traefik.http.services.{sanitized_container_name}.loadbalancer.server.port':
                    str(container_port),
                'com.tesslate.project': project.slug,
                'com.tesslate.container': container.name,
                'com.tesslate.user': str(user_id),
            }

            # Determine working directory
            if container.directory and container.directory != '.':
                working_dir = f"{project_work_dir}/{container.directory}"
            else:
                working_dir = project_work_dir

            # Build service definition
            service_config = {
                'image': base_image,
                'container_name': sanitized_container_name,
                'user': '1000:1000',  # Run as non-root
                'working_dir': working_dir,
                'networks': [network_name, 'tesslate-regional-traefik-network'],
                'volumes': volumes,
                'environment': environment,
                'labels': labels,
                'restart': 'unless-stopped',
                'command': startup_command,
                # Security: Block access to internal services
                'extra_hosts': [
                    'tesslate-orchestrator:127.0.0.1',
                    'tesslate-postgres:127.0.0.1',
                    'tesslate-redis:127.0.0.1',
                    'postgres:127.0.0.1',
                    'redis:127.0.0.1'
                ]
            }

            if ports:
                service_config['ports'] = ports

            if depends_on:
                service_config['depends_on'] = depends_on

            compose_config['services'][service_name] = service_config

        # Add shared projects-data volume as external
        if self.use_volumes:
            compose_config['volumes']['tesslate-projects-data'] = {
                'external': True,
                'name': 'tesslate-projects-data',
            }

        return compose_config

    async def _generate_service_container_config(
        self,
        project,
        container,
        service_name: str,
        network_name: str,
        user_id: UUID
    ) -> Optional[Dict[str, Any]]:
        """Generate config for service containers (Postgres, Redis, etc.)."""
        from ...services.service_definitions import get_service, ServiceType

        service_def = get_service(container.service_slug)
        if not service_def:
            logger.error(f"[DOCKER] Service '{container.service_slug}' not found, skipping")
            return None

        # Skip external-only services
        is_external_only = service_def.service_type == ServiceType.EXTERNAL
        is_deployed_externally = getattr(container, 'deployment_mode', 'container') == 'external'

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

        # Build labels
        labels = {
            'com.tesslate.project': project.slug,
            'com.tesslate.container': container.name,
            'com.tesslate.user': str(user_id),
            'com.tesslate.service': container.service_slug,
        }

        # Only add Traefik routing for HTTP services (not databases)
        if service_def.category in ["proxy", "storage", "search"]:
            labels.update({
                'traefik.enable': 'true',
                f'traefik.http.routers.{sanitized_container_name}.rule':
                    f'Host(`{sanitized_container_name}.localhost`)',
                f'traefik.http.services.{sanitized_container_name}.loadbalancer.server.port':
                    str(service_def.internal_port),
            })
        else:
            labels['traefik.enable'] = 'false'

        service_config = {
            'image': service_def.docker_image,
            'container_name': sanitized_container_name,
            'networks': [network_name],
            'volumes': volume_mounts,
            'environment': environment,
            'labels': labels,
            'restart': 'unless-stopped',
        }

        if service_def.command:
            service_config['command'] = service_def.command

        if service_def.health_check:
            service_config['healthcheck'] = service_def.health_check

        logger.info(f"[DOCKER] Added service container: {container.service_slug}")

        return {
            'service': service_config,
            'volume': {service_volume_name: {'name': service_volume_name}}
        }

    async def _get_container_config(
        self,
        project,
        container
    ) -> tuple:
        """
        Get startup command and port from TESSLATE.md config.

        Returns:
            (startup_command, port)
        """
        from ...services.base_config_parser import (
            get_base_config_from_volume,
            get_base_config_from_cache,
            generate_startup_command
        )

        base_config = None

        # Try reading from shared projects volume
        if self.use_volumes:
            try:
                base_config = await get_base_config_from_volume(project.slug)
            except Exception as e:
                logger.debug(f"[DOCKER] Could not read config from project: {e}")

        # Try cache if no volume config (marketplace bases)
        if not base_config and container.base:
            try:
                base_slug = container.base.slug
                base_config = await asyncio.to_thread(get_base_config_from_cache, base_slug)
            except Exception as e:
                logger.debug(f"[DOCKER] Could not read config from cache: {e}")

        # Determine port
        container_port = 3000  # Default
        if base_config and base_config.port:
            container_port = base_config.port
            logger.info(f"[DOCKER] Using port from TESSLATE.md: {container_port}")
        elif container.internal_port:
            container_port = container.internal_port
            logger.info(f"[DOCKER] Using port from database: {container_port}")

        # Generate startup command
        startup_command = generate_startup_command(base_config)
        logger.info(f"[DOCKER] Generated startup command for {container.name}")

        return startup_command, container_port


# Singleton instance
_docker_orchestrator: Optional[DockerOrchestrator] = None


def get_docker_orchestrator() -> DockerOrchestrator:
    """Get the singleton Docker orchestrator instance."""
    global _docker_orchestrator

    if _docker_orchestrator is None:
        use_volumes = os.getenv('USE_DOCKER_VOLUMES', 'true').lower() == 'true'
        _docker_orchestrator = DockerOrchestrator(use_volumes=use_volumes)

    return _docker_orchestrator
