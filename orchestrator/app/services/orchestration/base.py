"""
Abstract Base Orchestrator

Defines the common interface that all container orchestrators must implement.
This ensures feature parity between Docker and Kubernetes deployments.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from .deployment_mode import DeploymentMode


class BaseOrchestrator(ABC):
    """
    Abstract base class for container orchestration.

    All orchestrators (Docker, Kubernetes) must implement this interface
    to ensure consistent behavior across deployment modes.

    This interface provides:
    - Project lifecycle management (start, stop, restart)
    - Individual container management
    - Status monitoring
    - File operations (for agent tools)
    - Shell execution (for agent tools)
    """

    @property
    @abstractmethod
    def deployment_mode(self) -> DeploymentMode:
        """Return the deployment mode this orchestrator handles."""
        pass

    # =========================================================================
    # PROJECT LIFECYCLE
    # =========================================================================

    @abstractmethod
    async def start_project(
        self, project, containers: list, connections: list, user_id: UUID, db: AsyncSession
    ) -> dict[str, Any]:
        """
        Start all containers for a project.

        Args:
            project: Project model
            containers: List of Container models
            connections: List of ContainerConnection models
            user_id: User ID
            db: Database session

        Returns:
            Dictionary with:
                - status: "running" or "error"
                - project_slug: Project slug
                - containers: Dict of container_name -> URL
                - Additional mode-specific info
        """
        pass

    @abstractmethod
    async def stop_project(self, project_slug: str, project_id: UUID, user_id: UUID) -> None:
        """
        Stop all containers for a project.

        Args:
            project_slug: Project slug
            project_id: Project ID
            user_id: User ID
        """
        pass

    @abstractmethod
    async def restart_project(
        self, project, containers: list, connections: list, user_id: UUID, db: AsyncSession
    ) -> dict[str, Any]:
        """
        Restart all containers for a project.

        Args:
            project: Project model
            containers: List of Container models
            connections: List of ContainerConnection models
            user_id: User ID
            db: Database session

        Returns:
            Same as start_project
        """
        pass

    @abstractmethod
    async def get_project_status(self, project_slug: str, project_id: UUID) -> dict[str, Any]:
        """
        Get status of all containers in a project.

        Args:
            project_slug: Project slug
            project_id: Project ID

        Returns:
            Dictionary with:
                - status: "running", "partial", "stopped", "not_found", or "error"
                - containers: Dict of container statuses
                - Additional mode-specific info
        """
        pass

    # =========================================================================
    # INDIVIDUAL CONTAINER MANAGEMENT
    # =========================================================================

    @abstractmethod
    async def start_container(
        self,
        project,
        container,
        all_containers: list,
        connections: list,
        user_id: UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """
        Start a single container for a project.

        Args:
            project: Project model
            container: Container model to start
            all_containers: List of all Container models in project
            connections: List of ContainerConnection models
            user_id: User ID
            db: Database session

        Returns:
            Dictionary with:
                - status: "running" or "error"
                - container_name: Container name
                - url: Access URL
        """
        pass

    @abstractmethod
    async def stop_container(
        self, project_slug: str, project_id: UUID, container_name: str, user_id: UUID
    ) -> None:
        """
        Stop a single container.

        Args:
            project_slug: Project slug
            project_id: Project ID
            container_name: Container name
            user_id: User ID
        """
        pass

    @abstractmethod
    async def get_container_status(
        self, project_slug: str, project_id: UUID, container_name: str, user_id: UUID
    ) -> dict[str, Any]:
        """
        Get status of a single container.

        Args:
            project_slug: Project slug
            project_id: Project ID
            container_name: Container name
            user_id: User ID

        Returns:
            Dictionary with:
                - status: "running", "stopped", "not_found", or "error"
                - url: Access URL (if running)
                - Additional mode-specific info
        """
        pass

    # =========================================================================
    # FILE OPERATIONS (for agent tools)
    # =========================================================================

    @abstractmethod
    async def read_file(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        file_path: str,
        project_slug: str = None,
        subdir: str = None,
        volume_id: str | None = None,
        cache_node: str | None = None,
    ) -> str | None:
        """
        Read a file from a container.

        Args:
            user_id: User ID
            project_id: Project ID
            container_name: Container name
            file_path: Relative path within project
            project_slug: Project slug (optional)
            subdir: Container subdirectory (optional, for multi-container projects)

        Returns:
            File content as string, or None if not found
        """
        pass

    @abstractmethod
    async def write_file(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        file_path: str,
        content: str,
        project_slug: str = None,
        subdir: str = None,
        volume_id: str | None = None,
        cache_node: str | None = None,
    ) -> bool:
        """
        Write a file to a container.

        Args:
            user_id: User ID
            project_id: Project ID
            container_name: Container name
            file_path: Relative path within project
            content: File content

        Returns:
            True if successful
        """
        pass

    @abstractmethod
    async def delete_file(
        self, user_id: UUID, project_id: UUID, container_name: str, file_path: str
    ) -> bool:
        """
        Delete a file from a container.

        Args:
            user_id: User ID
            project_id: Project ID
            container_name: Container name
            file_path: Relative path within project

        Returns:
            True if successful
        """
        pass

    @abstractmethod
    async def list_files(
        self, user_id: UUID, project_id: UUID, container_name: str, directory: str = "."
    ) -> list[dict[str, Any]]:
        """
        List files in a directory.

        Args:
            user_id: User ID
            project_id: Project ID
            container_name: Container name
            directory: Directory path relative to project root

        Returns:
            List of dicts with: name, type ("file" or "directory"), size, path
        """
        pass

    @abstractmethod
    async def list_tree(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        subdir: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Recursive filtered file tree (excludes node_modules, .git, binaries, etc.).

        Returns:
            List of dicts with: path, name, is_dir, size, mod_time
        """
        pass

    @abstractmethod
    async def read_file_content(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        file_path: str,
        subdir: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Read a single file's content.

        Returns:
            Dict with path, content, size — or None if not found
        """
        pass

    @abstractmethod
    async def read_files_batch(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        paths: list[str],
        subdir: str | None = None,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """
        Batch-read multiple files.

        Returns:
            Tuple of ([{path, content, size}], [error_paths])
        """
        pass

    # =========================================================================
    # SHELL OPERATIONS (for agent tools)
    # =========================================================================

    @abstractmethod
    async def execute_command(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        command: list[str],
        timeout: int = 120,
        working_dir: str | None = None,
    ) -> str:
        """
        Execute a command in a container.

        Args:
            user_id: User ID
            project_id: Project ID
            container_name: Container name
            command: Command to execute as list
            timeout: Timeout in seconds
            working_dir: Working directory (relative to project root)

        Returns:
            Command output (stdout + stderr)
        """
        pass

    @abstractmethod
    async def is_container_ready(
        self, user_id: UUID, project_id: UUID, container_name: str
    ) -> dict[str, Any]:
        """
        Check if a container is ready for commands.

        Args:
            user_id: User ID
            project_id: Project ID
            container_name: Container name

        Returns:
            Dictionary with:
                - ready: bool
                - message: Status message
                - Additional mode-specific info
        """
        pass

    # =========================================================================
    # ACTIVITY TRACKING
    # =========================================================================

    @abstractmethod
    def track_activity(
        self, user_id: UUID, project_id: str, container_name: str | None = None
    ) -> None:
        """
        Track activity for idle cleanup purposes.

        Args:
            user_id: User ID
            project_id: Project ID
            container_name: Container name (optional)
        """
        pass

    # =========================================================================
    # LOG STREAMING
    # =========================================================================

    @abstractmethod
    async def stream_logs(
        self,
        project_id: UUID,
        user_id: UUID,
        container_id: UUID | None = None,
        tail_lines: int = 100,
    ) -> AsyncIterator[str]:
        """
        Stream container logs as an async iterator.

        Args:
            project_id: Project ID
            user_id: User ID
            container_id: Specific container ID (None = default/first running container)
            tail_lines: Number of historical lines to include

        Yields:
            Log lines as strings
        """
        yield ""  # abstract — implemented by subclasses
        raise NotImplementedError

    # =========================================================================
    # UTILITY METHODS (default implementations)
    # =========================================================================

    def get_container_url(self, project_slug: str, container_name: str) -> str:
        """
        Generate the access URL for a container.

        Default implementation - can be overridden by subclasses.

        Args:
            project_slug: Project slug
            container_name: Container name

        Returns:
            Access URL for the container
        """
        from ...config import get_settings

        settings = get_settings()

        # Sanitize container name for URL
        safe_name = container_name.lower().replace(" ", "-").replace("_", "-")
        safe_name = "".join(c for c in safe_name if c.isalnum() or c == "-")

        # Build hostname
        hostname = f"{project_slug}-{safe_name}.{settings.app_domain}"

        # Protocol based on deployment mode
        protocol = "https" if self.deployment_mode.is_kubernetes else "http"

        return f"{protocol}://{hostname}"
