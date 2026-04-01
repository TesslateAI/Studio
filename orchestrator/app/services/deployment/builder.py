"""
Deployment Builder Service.

This module handles building projects inside containers and collecting the built files
for deployment to various providers. Build commands and output directories are
configured per-container via the setup config UI, not auto-detected.
"""

import asyncio
import base64
import io
import logging
import os
import tarfile
from uuid import UUID

import docker

from .base import DeploymentFile

logger = logging.getLogger(__name__)


class BuildError(Exception):
    """Exception raised when build fails."""

    pass


class DeploymentBuilder:
    """
    Handles building projects and collecting deployment files.

    This service integrates with the existing container management system
    to run builds inside project containers and collect the resulting files.
    """

    def __init__(self):
        """Initialize the deployment builder."""
        self.container_manager = None
        self.docker_client = None
        self.dev_server_image = "tesslate-devserver:latest"

    def _get_docker_client(self):
        """Get or create Docker client."""
        if self.docker_client is None:
            self.docker_client = docker.from_env()
        return self.docker_client

    async def trigger_build(
        self,
        user_id: str,
        project_id: str,
        project_slug: str,
        custom_build_command: str | None = None,
        container_name: str | None = None,
        volume_name: str | None = None,
        container_directory: str | None = None,
        volume_id: str | None = None,
        cache_node: str | None = None,
        # Deprecated params kept for backwards compat — ignored
        framework: str | None = None,
        project_settings: dict | None = None,
        deployment_mode: str | None = None,
    ) -> tuple[bool, str]:
        """
        Trigger a build in an ephemeral pod (K8s) or via exec (Docker).

        In K8s mode, builds run in a separate ephemeral pod so the dev server
        isn't interrupted and lock files don't conflict. The pod mounts the
        same project volume and is cleaned up after the build completes.

        Args:
            user_id: User ID
            project_id: Project ID
            project_slug: Project slug (for container naming)
            custom_build_command: Build command (from Container.build_command)
            container_name: Specific container name to build in
            volume_name: Docker volume name
            container_directory: Subdirectory within the project
            volume_id: Project volume ID (K8s — for ephemeral build pod)
            cache_node: Node where volume is cached (K8s — for pod scheduling)

        Returns:
            Tuple of (success: bool, output: str)

        Raises:
            BuildError: If build fails
        """
        build_command = custom_build_command

        if not build_command:
            logger.info(f"No build command configured for project {project_id}, skipping build")
            return True, "No build command configured — skipping build step"

        try:
            # Compute working directory for multi-container projects
            if container_directory and container_directory not in (".", ""):
                work_dir = f"/app/{container_directory}"
            else:
                work_dir = "/app"

            # Install deps safety net (only if node_modules is missing)
            install_cmd = (
                "if [ -f bun.lock ] || [ -f bun.lockb ]; then bun install --frozen-lockfile; "
                "elif [ -f pnpm-lock.yaml ]; then pnpm install --frozen-lockfile; "
                "else npm install --prefer-offline --no-audit; fi"
            )

            from ..orchestration import get_orchestrator, is_kubernetes_mode

            orchestrator = get_orchestrator()
            effective_container = container_name or project_slug

            # Resolve actual project root on disk — container.directory
            # may not match where files were cloned (e.g. directory="."
            # but files live in /app/next-js-16/).
            work_dir = await self._find_project_root(
                orchestrator, user_id, project_id, effective_container, work_dir
            )
            logger.info(f"Running build command: {build_command} (work_dir: {work_dir})")

            full_cmd = (
                f"set -e && mkdir -p {work_dir} && cd {work_dir} "
                f"&& export NODE_ENV=production "
                f"&& ([ -d node_modules ] || ({install_cmd})) "
                f"&& {build_command} "
                f"&& echo BUILD_EXIT_CODE=0"
            )

            try:
                if is_kubernetes_mode() and volume_id:
                    # K8s: run build in an ephemeral pod so it doesn't conflict
                    # with the running dev server (no lock files, no port conflicts)
                    from ..compute_manager import get_compute_manager
                    from ..volume_manager import get_volume_manager

                    cm = get_compute_manager()
                    vm = get_volume_manager()
                    # Resolve live node from Hub (~5ms) for pod scheduling
                    live_node = await vm.get_volume_node(volume_id)
                    logger.info(
                        f"[BUILD] Using ephemeral pod for build (volume={volume_id}, node={live_node})"
                    )
                    output, exit_code, pod_name = await cm.run_command(
                        volume_id=volume_id,
                        node_name=live_node,
                        command=["/bin/sh", "-c", full_cmd],
                        timeout=300,
                    )
                    logger.info(f"[BUILD] Ephemeral pod {pod_name} finished (exit={exit_code})")
                else:
                    # Docker mode: exec into the running container
                    output = await orchestrator.execute_command(
                        user_id=UUID(user_id),
                        project_id=UUID(project_id),
                        container_name=effective_container,
                        command=["/bin/sh", "-c", full_cmd],
                        timeout=300,
                    )
            except RuntimeError as e:
                error_msg = f"Build failed: {str(e)}"
                logger.error(error_msg)
                raise BuildError(error_msg) from e

            # Verify the build actually produced output
            if "BUILD_EXIT_CODE=0" not in output:
                logger.error(
                    f"Build command did not complete successfully. Output: {output[:1000]}"
                )
                raise BuildError(f"Build command failed. Output: {output[:1000]}")

            logger.info(f"Build completed successfully for project {project_id}")
            return True, output

        except Exception as e:
            logger.error(f"Build failed for project {project_id}: {e}", exc_info=True)
            raise BuildError(f"Build failed: {e}") from e

    async def collect_deployment_files(
        self,
        user_id: str,
        project_id: str,
        custom_output_dir: str | None = None,
        collect_source: bool = False,
        container_directory: str | None = None,
        volume_name: str | None = None,
        container_name: str | None = None,
        volume_id: str | None = None,
        # Deprecated params kept for backwards compat — ignored
        framework: str | None = None,
        project_settings: dict | None = None,
    ) -> list[DeploymentFile]:
        """
        Collect files from the project for deployment.

        Args:
            user_id: User ID
            project_id: Project ID
            custom_output_dir: Output directory (from Container.output_directory, e.g. "dist", "out")
            collect_source: If True, collect source files; if False, collect built files
            container_directory: Subdirectory within project
            volume_name: Project slug (used for Docker shared volume path)
            container_name: Container name for orchestrator commands
            volume_id: Project volume ID (K8s — enables FileOps direct read)

        Returns:
            List of DeploymentFile objects

        Raises:
            FileNotFoundError: If build output directory doesn't exist
        """
        try:
            # Compute the target directory inside the container
            if container_directory and container_directory not in (".", ""):
                base_dir = f"/app/{container_directory}"
            else:
                base_dir = "/app"

            # K8s fast path: use FileOps gRPC to read directly from the btrfs
            # volume.  This avoids the slow tar|base64 over kubectl-exec path
            # which chokes on large build outputs (e.g. .next at 150 MB+).
            from ..orchestration import is_kubernetes_mode

            if volume_id and is_kubernetes_mode():
                # Resolve project root via FileOps (no exec needed)
                rel_base = base_dir.removeprefix("/app").lstrip("/") or "."
                rel_base = await self._find_project_root_via_fileops(volume_id, rel_base)

                if collect_source:
                    target_rel = rel_base
                    logger.info(f"Collecting source files via FileOps at {target_rel}")
                else:
                    output_dir = custom_output_dir or "dist"
                    target_rel = f"{rel_base}/{output_dir}" if rel_base != "." else output_dir
                    logger.info(f"Collecting built files via FileOps at {target_rel}")

                files = await self._collect_files_via_fileops(volume_id, target_rel)
                logger.info(f"Collected {len(files)} files via FileOps")
                return files

            # Resolve actual project root on disk (same as trigger_build)
            if container_name:
                from ..orchestration import get_orchestrator

                orchestrator = get_orchestrator()
                base_dir = await self._find_project_root(
                    orchestrator, user_id, project_id, container_name, base_dir
                )

            if collect_source:
                # Collect source files (provider will build remotely)
                target_dir = base_dir
                logger.info(f"Collecting source files from container at {target_dir}")
            else:
                # Collect built files from output directory
                output_dir = custom_output_dir or "dist"
                target_dir = f"{base_dir}/{output_dir}"
                logger.info(f"Collecting built files from container at {target_dir}")

            # Primary: use orchestrator to collect files (works for both Docker and K8s)
            if container_name:
                files = await self._collect_files_via_orchestrator(
                    user_id=user_id,
                    project_id=project_id,
                    container_name=container_name,
                    target_dir=target_dir,
                )
                logger.info(f"Collected {len(files)} files via orchestrator")
                return files

            # Fallback: direct filesystem for Docker shared volume
            if volume_name:
                volume_dir = f"/projects/{volume_name}"
                if container_directory and container_directory not in (".", ""):
                    volume_dir = f"{volume_dir}/{container_directory}"

                if not collect_source:
                    out = custom_output_dir or "dist"
                    volume_dir = f"{volume_dir}/{out}"

                logger.info(f"Collecting files from shared volume at {volume_dir}")
                if not os.path.exists(volume_dir):
                    raise FileNotFoundError(f"Build output directory not found: {volume_dir}")
                files = await self._collect_files_recursive(volume_dir, ".")
                logger.info(f"Collected {len(files)} files from volume")
                return files

            raise FileNotFoundError("No container_name or volume_name provided for file collection")

        except Exception as e:
            logger.error(f"Failed to collect deployment files: {e}", exc_info=True)
            raise

    async def _collect_files_recursive(self, directory: str, base_dir: str) -> list[DeploymentFile]:
        """
        Recursively collect all files from a directory.

        Args:
            directory: Absolute path to directory to scan
            base_dir: Base directory name for relative paths

        Returns:
            List of DeploymentFile objects
        """
        files = []
        ignored_patterns = {
            ".git",
            "node_modules",
            "__pycache__",
            ".DS_Store",
            ".env",
            ".env.local",
            ".env.production",
            ".env.development",
            "thumbs.db",
            ".next",
            "out",
            "dist",
            "build",
            ".turbo",
        }

        for root, dirs, filenames in os.walk(directory):
            # Filter out ignored directories
            dirs[:] = [d for d in dirs if d not in ignored_patterns]

            for filename in filenames:
                # Skip ignored files
                if filename in ignored_patterns or filename.startswith("."):
                    continue

                file_path = os.path.join(root, filename)
                relative_path = os.path.relpath(file_path, directory)

                # Read file content
                try:
                    # Use async file reading for better performance
                    content = await self._read_file_async(file_path)

                    files.append(DeploymentFile(path=relative_path, content=content))

                except Exception as e:
                    logger.warning(f"Failed to read file {file_path}: {e}")
                    continue

        return files

    async def _collect_files_via_orchestrator(
        self,
        user_id: str,
        project_id: str,
        container_name: str,
        target_dir: str,
    ) -> list[DeploymentFile]:
        """
        Collect files from the project container via orchestrator execute_command.

        Runs tar+base64 inside the pod/container and decodes the result.
        Works in both Docker and Kubernetes modes.

        Args:
            user_id: User ID
            project_id: Project ID
            container_name: Container name for orchestrator
            target_dir: Absolute path inside the container to collect from

        Returns:
            List of DeploymentFile objects
        """
        from ..orchestration import get_orchestrator

        orchestrator = get_orchestrator()

        # First verify the directory exists; if not, list parent contents for debugging
        check_output = await orchestrator.execute_command(
            user_id=UUID(user_id),
            project_id=UUID(project_id),
            container_name=container_name,
            command=[
                "/bin/sh",
                "-c",
                f"if [ -d {target_dir} ]; then echo EXISTS; "
                f"else echo NOT_FOUND; echo '---'; ls -la $(dirname {target_dir}) 2>&1 || true; fi",
            ],
            timeout=10,
        )

        if "NOT_FOUND" in check_output:
            raise FileNotFoundError(
                f"Directory not found in container: {target_dir}\n"
                f"Container contents:\n{check_output}"
            )

        # Tar the directory, base64 encode, and stream back
        excludes = (
            "--exclude=node_modules --exclude=.git --exclude=__pycache__ "
            "--exclude=.DS_Store --exclude=.env --exclude=.env.local "
            "--exclude=.env.production --exclude=.env.development "
            "--exclude=thumbs.db --exclude=.next --exclude=out "
            "--exclude=dist --exclude=build --exclude=.turbo"
        )
        cmd = f"tar -cf - -C {target_dir} {excludes} . 2>/dev/null | base64"

        output = await orchestrator.execute_command(
            user_id=UUID(user_id),
            project_id=UUID(project_id),
            container_name=container_name,
            command=["/bin/sh", "-c", cmd],
            timeout=120,
        )

        if not output or not output.strip():
            raise FileNotFoundError(f"No files found in {target_dir}")

        # Decode base64 and extract tar
        tar_bytes = base64.b64decode(output.strip())
        files = []

        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as tar:
            for member in tar.getmembers():
                if not member.isfile():
                    continue
                name = member.name
                if name.startswith("./"):
                    name = name[2:]
                if not name:
                    continue
                # Skip hidden files
                if any(part.startswith(".") for part in name.split("/")):
                    continue

                f = tar.extractfile(member)
                if f:
                    content = f.read()
                    files.append(DeploymentFile(path=name, content=content))

        return files

    async def _find_project_root_via_fileops(self, volume_id: str, expected_rel: str) -> str:
        """
        Find the actual project root directory using FileOps (no exec needed).

        Mirrors _find_project_root but reads from the btrfs volume directly.

        Args:
            volume_id: Volume ID for FileOps
            expected_rel: Expected relative path (e.g. "." or "frontend")

        Returns:
            Relative path to the project root (e.g. "." or "next-js-16")
        """
        from ..volume_manager import get_volume_manager

        vm = get_volume_manager()
        client = await vm.get_fileops_client(volume_id)

        indicators = ("package.json", "requirements.txt", "go.mod")

        # Check expected directory first
        for indicator in indicators:
            check_path = f"{expected_rel}/{indicator}" if expected_rel != "." else indicator
            try:
                info = await client.stat_path(volume_id, check_path, timeout=5)
                if not info.is_dir:
                    return expected_rel
            except Exception:
                continue

        # Scan one level deep under root
        try:
            entries = await client.list_dir(volume_id, ".", recursive=False, timeout=5)
            for entry in entries:
                if not entry.is_dir:
                    continue
                for indicator in indicators:
                    try:
                        info = await client.stat_path(
                            volume_id, f"{entry.name}/{indicator}", timeout=5
                        )
                        if not info.is_dir:
                            logger.info(
                                f"Project root resolved via FileOps: {expected_rel} → {entry.name}"
                            )
                            return entry.name
                    except Exception:
                        continue
        except Exception as e:
            logger.warning(f"Failed to scan project root via FileOps: {e}")

        return expected_rel

    async def _collect_files_via_fileops(
        self, volume_id: str, target_rel: str
    ) -> list[DeploymentFile]:
        """
        Collect deployment files directly from a btrfs volume via FileOps gRPC.

        Uses ListTree to enumerate files (with server-side exclusions) and
        concurrent ReadFile calls to fetch contents. This bypasses the slow
        tar|base64-over-exec path that chokes on large build outputs.

        Args:
            volume_id: Volume ID for FileOps
            target_rel: Relative path inside the volume (e.g. "." or ".next")

        Returns:
            List of DeploymentFile objects
        """
        from ..volume_manager import get_volume_manager

        vm = get_volume_manager()
        client = await vm.get_fileops_client(volume_id)

        # Verify the directory exists
        try:
            info = await client.stat_path(volume_id, target_rel, timeout=10)
            if not info.is_dir:
                raise FileNotFoundError(f"Not a directory: {target_rel}")
        except FileNotFoundError:
            raise
        except Exception as exc:
            raise FileNotFoundError(
                f"Directory not found on volume {volume_id}: {target_rel} ({exc})"
            ) from exc

        # List all files with server-side exclusions
        exclude_dirs = [
            "node_modules",
            ".git",
            "__pycache__",
            ".venv",
            "venv",
            ".cache",
            ".turbo",
            "coverage",
            ".nyc_output",
            "lost+found",
        ]
        exclude_files = [
            ".DS_Store",
            "Thumbs.db",
            ".env",
            ".env.local",
            ".env.production",
            ".env.development",
        ]
        exclude_exts = ["map", "lock"]

        entries = await client.list_tree(
            volume_id,
            target_rel,
            exclude_dirs=exclude_dirs,
            exclude_files=exclude_files,
            exclude_extensions=exclude_exts,
            timeout=30,
        )

        # Filter to files only, skip hidden files
        file_entries = []
        for entry in entries:
            if entry.is_dir:
                continue
            # Skip hidden files/directories in path
            rel = entry.path
            if any(part.startswith(".") for part in rel.split("/")):
                continue
            file_entries.append(entry)

        if not file_entries:
            raise FileNotFoundError(f"No files found in {target_rel}")

        logger.info(f"FileOps listed {len(file_entries)} files in {target_rel}")

        # Read files concurrently in batches to avoid overwhelming the gRPC server
        max_file_size = 10 * 1024 * 1024  # 10 MB per file
        batch_size = 50
        files: list[DeploymentFile] = []

        for i in range(0, len(file_entries), batch_size):
            batch = file_entries[i : i + batch_size]
            tasks = []
            for entry in batch:
                if entry.size > max_file_size:
                    logger.warning(f"Skipping oversized file {entry.path} ({entry.size} bytes)")
                    continue
                tasks.append(
                    self._read_single_file_via_fileops(client, volume_id, entry, target_rel)
                )

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    logger.warning(f"Failed to read file: {result}")
                    continue
                if result is not None:
                    files.append(result)

        return files

    async def _read_single_file_via_fileops(
        self, client, volume_id: str, entry, target_rel: str
    ) -> DeploymentFile | None:
        """Read a single file via FileOps and return a DeploymentFile."""
        try:
            content = await client.read_file(volume_id, entry.path, timeout=30)
            # Make path relative to the target directory
            rel_path = entry.path
            if target_rel != ".":
                prefix = target_rel.rstrip("/") + "/"
                if rel_path.startswith(prefix):
                    rel_path = rel_path[len(prefix) :]
            return DeploymentFile(path=rel_path, content=content)
        except Exception as e:
            logger.warning(f"Failed to read {entry.path}: {e}")
            return None

    async def _read_file_async(self, file_path: str) -> bytes:
        """Read a file asynchronously."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._read_file_sync, file_path)

    @staticmethod
    def _read_file_sync(file_path: str) -> bytes:
        """Read a file synchronously (for executor)."""
        with open(file_path, "rb") as f:
            return f.read()

    async def _find_project_root(
        self,
        orchestrator,
        user_id: str,
        project_id: str,
        container_name: str,
        expected_dir: str,
    ) -> str:
        """
        Find the actual project root directory inside the container.

        The container.directory field may not match where files were actually
        cloned (e.g. directory="." but files live in /app/next-js-16/).
        This method checks the expected path first, then scans one level
        deep under /app for a directory containing project root indicators
        (package.json, requirements.txt, go.mod).

        Args:
            orchestrator: Orchestrator instance
            user_id: User ID
            project_id: Project ID
            container_name: Container name for exec
            expected_dir: Expected working directory (e.g. "/app" or "/app/frontend")

        Returns:
            Actual project root path (e.g. "/app/next-js-16")
        """
        # Shell script: check expected dir first, then scan /app subdirs
        find_script = (
            f"if [ -f '{expected_dir}/package.json' ] || "
            f"[ -f '{expected_dir}/requirements.txt' ] || "
            f"[ -f '{expected_dir}/go.mod' ]; then "
            f"echo '{expected_dir}'; "
            f"else "
            f"for d in /app/*/; do "
            f'if [ -f "${{d}}package.json" ] || '
            f'[ -f "${{d}}requirements.txt" ] || '
            f'[ -f "${{d}}go.mod" ]; then '
            f'echo "${{d%/}}"; exit 0; fi; done; '
            f"echo '{expected_dir}'; fi"
        )
        try:
            result = await orchestrator.execute_command(
                user_id=UUID(user_id),
                project_id=UUID(project_id),
                container_name=container_name,
                command=["/bin/sh", "-c", find_script],
                timeout=10,
            )
            resolved = result.strip().split("\n")[0].strip()
            if resolved and resolved.startswith("/app"):
                if resolved != expected_dir:
                    logger.info(f"Project root resolved: {expected_dir} → {resolved}")
                return resolved
        except Exception as e:
            logger.warning(f"Failed to resolve project root, using {expected_dir}: {e}")

        return expected_dir

    async def _collect_files_from_volume(
        self, project_slug: str, subdirectory: str | None = None
    ) -> list[DeploymentFile]:
        """
        Collect files from the shared projects volume using direct filesystem access.

        Args:
            project_slug: Project slug
            subdirectory: Optional subdirectory within the project to collect from

        Returns:
            List of DeploymentFile objects
        """
        base_path = f"/projects/{project_slug}"
        if subdirectory and subdirectory != ".":
            base_path = f"{base_path}/{subdirectory}"

        logger.info(f"Collecting files from shared volume at {base_path}")

        if not os.path.exists(base_path):
            raise FileNotFoundError(f"Project path not found: {base_path}")

        try:
            files = await self._collect_files_recursive(base_path, ".")
            logger.info(f"Collected {len(files)} files from {base_path}")
            return files
        except Exception as e:
            logger.error(f"Failed to collect files from {base_path}: {e}", exc_info=True)
            raise FileNotFoundError(f"Failed to read from {base_path}: {str(e)}") from e

    async def _read_file_from_volume(self, project_slug: str, file_path: str) -> bytes | None:
        """Read a single file from the shared projects volume."""
        full_path = f"/projects/{project_slug}/{file_path}"

        try:
            if os.path.exists(full_path):
                with open(full_path, "rb") as f:
                    return f.read()
            return None
        except Exception as e:
            logger.warning(f"Failed to read file {full_path}: {e}")
            return None

    async def _directory_exists_in_volume(self, project_slug: str, directory_path: str) -> bool:
        """Check if a directory exists in the shared projects volume."""
        full_path = f"/projects/{project_slug}/{directory_path}"
        return os.path.isdir(full_path)


# Global singleton instance
_deployment_builder: DeploymentBuilder | None = None


def get_deployment_builder() -> DeploymentBuilder:
    """Get or create the global deployment builder instance."""
    global _deployment_builder

    if _deployment_builder is None:
        logger.debug("Initializing global deployment builder")
        _deployment_builder = DeploymentBuilder()

    return _deployment_builder
