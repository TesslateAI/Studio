"""
Deployment Builder Service.

This module handles building projects inside containers and collecting the built files
for deployment to various providers.
"""

import logging
import os
import asyncio
import docker
import tempfile
import tarfile
import io
from typing import List, Dict, Optional, Tuple
from pathlib import Path
from uuid import UUID

from .base import DeploymentFile
from ...services.framework_detector import FrameworkDetector
# Legacy container manager removed - multi-container projects only

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
        self.container_manager = None  # TODO: Update for multi-container system
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
        framework: Optional[str] = None,
        custom_build_command: Optional[str] = None,
        project_settings: Optional[Dict] = None,
        container_name: Optional[str] = None,
        volume_name: Optional[str] = None
    ) -> Tuple[bool, str]:
        """
        Trigger a build inside the project container.

        Args:
            user_id: User ID
            project_id: Project ID
            project_slug: Project slug (for container naming)
            framework: Framework type (auto-detected if not provided)
            custom_build_command: Custom build command override
            project_settings: Project settings dict (for cached framework info)
            container_name: Specific container name to build in (for multi-container projects)

        Returns:
            Tuple of (success: bool, output: str)

        Raises:
            BuildError: If build fails
        """
        try:
            # Get project path
            project_path = self._get_project_path(user_id, project_id)

            # Detect framework using priority: parameter > cached > auto-detect
            if not framework:
                # Try to use cached framework from project settings
                if project_settings and project_settings.get("framework"):
                    framework = project_settings["framework"]
                    logger.info(f"Using cached framework from project settings: {framework}")
                else:
                    # Fallback: Auto-detect from package.json
                    package_json_path = os.path.join(project_path, "package.json")
                    if os.path.exists(package_json_path):
                        with open(package_json_path, 'r') as f:
                            package_json_content = f.read()
                        framework, _ = FrameworkDetector.detect_from_package_json(package_json_content)
                        logger.info(f"Auto-detected framework: {framework}")
                    else:
                        framework = "vite"
                        logger.warning("No package.json found, defaulting to vite")

            # Get build command with priority: custom > cached > framework default
            if custom_build_command:
                build_command = custom_build_command
            elif project_settings and project_settings.get("build_command"):
                build_command = project_settings["build_command"]
                logger.info(f"Using cached build command from project settings: {build_command}")
            else:
                build_command = self._get_build_command(framework)

            if not build_command:
                logger.warning(f"Framework {framework} does not require a build step")
                return True, "No build required for this framework"

            logger.info(f"Running build command in container: {build_command}")

            # Execute build command in container
            # Note: execute_command_in_container expects a List[str] and raises RuntimeError on failure
            try:
                # For multi-container projects, execute directly with docker exec
                if container_name:
                    from ...utils.async_subprocess import run_async
                    logger.info(f"Executing build in specific container: {container_name}")

                    result = await run_async(
                        ["docker", "exec", container_name, "/bin/sh", "-c", f"cd /app && {build_command}"],
                        timeout=300,
                        capture_output=True,
                        text=True
                    )

                    output = result.stdout + result.stderr

                    if result.returncode != 0:
                        raise RuntimeError(f"Command failed with exit code {result.returncode}: {output}")
                else:
                    # Single container project - use container manager
                    output = await self.container_manager.execute_command_in_container(
                        user_id=UUID(user_id),
                        project_id=project_id,
                        command=["/bin/sh", "-c", f"cd /app && {build_command}"],
                        project_slug=project_slug
                    )
            except RuntimeError as e:
                error_msg = f"Build failed: {str(e)}"
                logger.error(error_msg)
                raise BuildError(error_msg)

            logger.info(f"Build completed successfully for project {project_id}")
            return True, output

        except Exception as e:
            logger.error(f"Build failed for project {project_id}: {e}", exc_info=True)
            raise BuildError(f"Build failed: {e}") from e

    async def collect_deployment_files(
        self,
        user_id: str,
        project_id: str,
        framework: Optional[str] = None,
        custom_output_dir: Optional[str] = None,
        project_settings: Optional[Dict] = None,
        collect_source: bool = False,
        container_directory: Optional[str] = None,
        volume_name: Optional[str] = None
    ) -> List[DeploymentFile]:
        """
        Collect files from the project for deployment.

        Args:
            user_id: User ID
            project_id: Project ID
            framework: Framework type (auto-detected if not provided)
            custom_output_dir: Custom output directory override
            project_settings: Project settings dict (for cached framework info)
            collect_source: If True, collect source files; if False, collect built files
            container_directory: Subdirectory within project (for multi-container projects)
            volume_name: Docker volume name (source of truth for Docker volume-based projects)

        Returns:
            List of DeploymentFile objects

        Raises:
            FileNotFoundError: If build output directory doesn't exist
        """
        try:
            # Volume-based file collection (source of truth)
            if volume_name:
                logger.info(f"Collecting files from Docker volume: {volume_name}")

                if collect_source:
                    # Collect all source files from volume
                    files = await self._collect_files_from_volume(
                        volume_name,
                        subdirectory=container_directory
                    )
                    logger.info(f"Collected {len(files)} source files from volume")
                    return files
                else:
                    # Collect built files from volume
                    # 1. Detect framework from volume
                    if not framework:
                        package_json_content = await self._read_file_from_volume(
                            volume_name,
                            "package.json"
                        )
                        if package_json_content:
                            framework, _ = FrameworkDetector.detect_from_package_json(
                                package_json_content.decode('utf-8')
                            )
                            logger.info(f"Auto-detected framework from volume: {framework}")
                        else:
                            framework = "vite"
                            logger.warning("No package.json found in volume, defaulting to vite")

                    # 2. Get output directory
                    if custom_output_dir:
                        output_dir = custom_output_dir
                    elif project_settings and project_settings.get("output_directory"):
                        output_dir = project_settings["output_directory"]
                    else:
                        output_dir = self._get_build_output_dir(framework)

                    # 3. Build subdirectory path for multi-container
                    if container_directory and container_directory != ".":
                        output_dir = f"{container_directory}/{output_dir}"

                    # 4. Verify build output exists
                    if not await self._directory_exists_in_volume(volume_name, output_dir):
                        raise FileNotFoundError(
                            f"Build output directory not found in volume {volume_name}: {output_dir}"
                        )

                    # 5. Collect files
                    files = await self._collect_files_from_volume(volume_name, subdirectory=output_dir)
                    logger.info(f"Collected {len(files)} built files from volume")
                    return files

            # FALLBACK: Original filesystem code for backward compatibility
            # Get project path
            project_path = self._get_project_path(user_id, project_id)

            # For multi-container projects, use the container's subdirectory
            if container_directory and container_directory != ".":
                project_path = os.path.join(project_path, container_directory)
                logger.info(f"Multi-container project: using directory {container_directory}")

            if collect_source:
                # Collect source files for deployment (Vercel will build)
                logger.info(f"Collecting source files from: {project_path}")
                files = await self._collect_files_recursive(project_path, ".")
                logger.info(f"Collected {len(files)} source files for deployment")
                return files

            else:
                # Collect built files (original behavior)
                # Detect framework using priority: parameter > cached > auto-detect
                if not framework:
                    # Try to use cached framework from project settings
                    if project_settings and project_settings.get("framework"):
                        framework = project_settings["framework"]
                        logger.debug(f"Using cached framework from project settings: {framework}")
                    else:
                        # Fallback: Auto-detect from package.json
                        package_json_path = os.path.join(project_path, "package.json")
                        if os.path.exists(package_json_path):
                            with open(package_json_path, 'r') as f:
                                package_json_content = f.read()
                            framework, _ = FrameworkDetector.detect_from_package_json(package_json_content)
                        else:
                            framework = "vite"

                # Get output directory with priority: custom > cached > framework default
                if custom_output_dir:
                    output_dir = custom_output_dir
                elif project_settings and project_settings.get("output_directory"):
                    output_dir = project_settings["output_directory"]
                    logger.debug(f"Using cached output directory from project settings: {output_dir}")
                else:
                    output_dir = self._get_build_output_dir(framework)
                build_path = os.path.join(project_path, output_dir)

                logger.info(f"Collecting deployment files from: {build_path}")

                # Verify build output exists
                if not os.path.exists(build_path):
                    error_msg = f"Build output directory not found: {build_path}"
                    logger.error(error_msg)
                    raise FileNotFoundError(error_msg)

                # Collect files
                files = await self._collect_files_recursive(build_path, output_dir)

                logger.info(f"Collected {len(files)} files for deployment")
                return files

        except Exception as e:
            logger.error(f"Failed to collect deployment files: {e}", exc_info=True)
            raise

    async def _collect_files_recursive(
        self,
        directory: str,
        base_dir: str
    ) -> List[DeploymentFile]:
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
            '.git', 'node_modules', '__pycache__', '.DS_Store',
            '.env', '.env.local', '.env.production', '.env.development',
            'thumbs.db', '.next/cache'
        }

        for root, dirs, filenames in os.walk(directory):
            # Filter out ignored directories
            dirs[:] = [d for d in dirs if d not in ignored_patterns]

            for filename in filenames:
                # Skip ignored files
                if filename in ignored_patterns or filename.startswith('.'):
                    continue

                file_path = os.path.join(root, filename)
                relative_path = os.path.relpath(file_path, directory)

                # Read file content
                try:
                    # Use async file reading for better performance
                    content = await self._read_file_async(file_path)

                    files.append(DeploymentFile(
                        path=relative_path,
                        content=content
                    ))

                except Exception as e:
                    logger.warning(f"Failed to read file {file_path}: {e}")
                    continue

        return files

    async def _read_file_async(self, file_path: str) -> bytes:
        """
        Read a file asynchronously.

        Args:
            file_path: Path to file

        Returns:
            File content as bytes
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._read_file_sync, file_path)

    @staticmethod
    def _read_file_sync(file_path: str) -> bytes:
        """
        Read a file synchronously (for executor).

        Args:
            file_path: Path to file

        Returns:
            File content as bytes
        """
        with open(file_path, 'rb') as f:
            return f.read()

    def _get_project_path(self, user_id: str, project_id: str) -> str:
        """
        Get the filesystem path to a project.

        Args:
            user_id: User ID
            project_id: Project ID

        Returns:
            Absolute path to project directory
        """
        from ...config import get_settings
        settings = get_settings()

        if settings.deployment_mode == "kubernetes":
            # Kubernetes uses shared PVC
            base_path = "/mnt/shared"
        else:
            # Docker uses local filesystem
            base_path = os.path.join(os.path.dirname(__file__), "../../../users")

        return os.path.join(base_path, f"{user_id}/{project_id}")

    def _get_build_command(self, framework: str) -> Optional[str]:
        """
        Get the build command for a framework.

        Args:
            framework: Framework type

        Returns:
            Build command string or None if no build needed
        """
        commands = {
            "vite": "npm run build",
            "nextjs": "npm run build",
            "react": "npm run build",
            "vue": "npm run build",
            "svelte": "npm run build",
            "angular": "npm run build",
            "go": "go build -o main",
            "python": None,  # No build for Python
            "node": None,  # No build for plain Node.js
        }

        return commands.get(framework.lower(), "npm run build")

    def _get_build_output_dir(self, framework: str) -> str:
        """
        Get the build output directory for a framework.

        Args:
            framework: Framework type

        Returns:
            Output directory name
        """
        output_dirs = {
            "vite": "dist",
            "nextjs": ".next",
            "react": "build",
            "vue": "dist",
            "svelte": "dist",
            "angular": "dist",
            "go": ".",
            "python": ".",
        }

        return output_dirs.get(framework.lower(), "dist")

    async def verify_build_output(
        self,
        user_id: str,
        project_id: str,
        framework: Optional[str] = None
    ) -> bool:
        """
        Verify that build output exists and is valid.

        Args:
            user_id: User ID
            project_id: Project ID
            framework: Framework type

        Returns:
            True if build output is valid
        """
        try:
            project_path = self._get_project_path(user_id, project_id)

            if not framework:
                # Read package.json to detect framework
                package_json_path = os.path.join(project_path, "package.json")
                if os.path.exists(package_json_path):
                    with open(package_json_path, 'r') as f:
                        package_json_content = f.read()
                    framework, _ = FrameworkDetector.detect_from_package_json(package_json_content)
                else:
                    framework = "vite"

            output_dir = self._get_build_output_dir(framework)
            build_path = os.path.join(project_path, output_dir)

            # Check if directory exists and has files
            if not os.path.exists(build_path):
                logger.error(f"Build output directory does not exist: {build_path}")
                return False

            # Check if directory has at least one file
            has_files = any(os.path.isfile(os.path.join(build_path, f)) for f in os.listdir(build_path))

            if not has_files:
                logger.error(f"Build output directory is empty: {build_path}")
                return False

            logger.info(f"Build output verified for project {project_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to verify build output: {e}", exc_info=True)
            return False

    async def _collect_files_from_volume(
        self,
        volume_name: str,
        subdirectory: Optional[str] = None
    ) -> List[DeploymentFile]:
        """
        Collect files from a Docker volume using a temporary container.

        This mirrors the pattern used in volume_manager.py for consistency.

        Args:
            volume_name: Name of the Docker volume
            subdirectory: Optional subdirectory within the volume to collect from

        Returns:
            List of DeploymentFile objects
        """
        logger.info(f"Collecting files from volume {volume_name}, subdirectory: {subdirectory or '.'}")

        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = f"/volume/{subdirectory}" if subdirectory else "/volume"

            docker_client = await asyncio.to_thread(self._get_docker_client)

            try:
                # Use docker cp to copy files from volume to local temp directory
                # This avoids all the tar streaming and encoding issues
                logger.info(f"[VOLUME] Using docker cp to extract files from {source_path}")

                def copy_from_volume():
                    # Create a long-lived container with the volume mounted
                    container = docker_client.containers.create(
                        image=self.dev_server_image,
                        command=["sleep", "30"],
                        volumes={volume_name: {'bind': '/volume', 'mode': 'ro'}},
                        user='root',
                        detach=True
                    )
                    try:
                        container.start()

                        # Use docker cp to copy files out
                        # get_archive returns (data_stream, stat_dict)
                        bits, stat = container.get_archive(source_path)

                        # Write stream to tar file
                        tar_bytes = b''.join(bits)

                        return tar_bytes
                    finally:
                        container.stop(timeout=1)
                        container.remove()

                tar_bytes = await asyncio.to_thread(copy_from_volume)

                logger.info(f"[VOLUME] Received {len(tar_bytes)} bytes via docker cp")
                logger.info(f"[VOLUME] First 10 bytes (hex): {tar_bytes[:10].hex()}")

                # Extract tar to temp directory
                tar_stream = io.BytesIO(tar_bytes)
                with tarfile.open(fileobj=tar_stream, mode='r') as tar:
                    await asyncio.to_thread(tar.extractall, temp_dir)

                # Collect files from temp directory
                files = await self._collect_files_recursive(temp_dir, ".")

                return files

            except Exception as e:
                logger.error(f"Failed to copy from volume: {e}", exc_info=True)
                raise FileNotFoundError(f"Failed to read from volume {volume_name}: {str(e)}")

    async def _read_file_from_volume(
        self,
        volume_name: str,
        file_path: str
    ) -> Optional[bytes]:
        """
        Read a single file from a Docker volume.

        Args:
            volume_name: Name of the Docker volume
            file_path: Path to the file within the volume

        Returns:
            File content as bytes, or None if file doesn't exist
        """
        try:
            docker_client = await asyncio.to_thread(self._get_docker_client)

            result = await asyncio.to_thread(
                docker_client.containers.run,
                image=self.dev_server_image,
                command=["sh", "-c", f"cat /volume/{file_path}"],
                volumes={volume_name: {'bind': '/volume', 'mode': 'ro'}},
                user='root',
                detach=False,
                remove=True,
                stdout=True,
                stderr=True
            )

            return result

        except docker.errors.ContainerError:
            # File not found
            return None

    async def _directory_exists_in_volume(
        self,
        volume_name: str,
        directory_path: str
    ) -> bool:
        """
        Check if a directory exists in a Docker volume.

        Args:
            volume_name: Name of the Docker volume
            directory_path: Path to the directory within the volume

        Returns:
            True if directory exists, False otherwise
        """
        try:
            docker_client = await asyncio.to_thread(self._get_docker_client)

            await asyncio.to_thread(
                docker_client.containers.run,
                image=self.dev_server_image,
                command=["sh", "-c", f"test -d /volume/{directory_path}"],
                volumes={volume_name: {'bind': '/volume', 'mode': 'ro'}},
                user='root',
                detach=False,
                remove=True,
                stdout=True,
                stderr=True
            )

            return True

        except docker.errors.ContainerError:
            return False


# Global singleton instance
_deployment_builder: Optional[DeploymentBuilder] = None


def get_deployment_builder() -> DeploymentBuilder:
    """
    Get or create the global deployment builder instance.

    Returns:
        The global DeploymentBuilder instance
    """
    global _deployment_builder

    if _deployment_builder is None:
        logger.debug("Initializing global deployment builder")
        _deployment_builder = DeploymentBuilder()

    return _deployment_builder
