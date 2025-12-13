"""
Abstract Base Orchestrator

Defines the common interface that all container orchestrators must implement.
This ensures feature parity between Docker and Kubernetes deployments.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional
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
        self,
        project,
        containers: List,
        connections: List,
        user_id: UUID,
        db: AsyncSession
    ) -> Dict[str, Any]:
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
    async def stop_project(
        self,
        project_slug: str,
        project_id: UUID,
        user_id: UUID
    ) -> None:
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
        self,
        project,
        containers: List,
        connections: List,
        user_id: UUID,
        db: AsyncSession
    ) -> Dict[str, Any]:
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
    async def get_project_status(
        self,
        project_slug: str,
        project_id: UUID
    ) -> Dict[str, Any]:
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
        all_containers: List,
        connections: List,
        user_id: UUID,
        db: AsyncSession
    ) -> Dict[str, Any]:
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
        self,
        project_slug: str,
        project_id: UUID,
        container_name: str,
        user_id: UUID
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
        self,
        project_slug: str,
        project_id: UUID,
        container_name: str,
        user_id: UUID
    ) -> Dict[str, Any]:
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
        file_path: str
    ) -> Optional[str]:
        """
        Read a file from a container.

        Args:
            user_id: User ID
            project_id: Project ID
            container_name: Container name
            file_path: Relative path within project

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
        content: str
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
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        file_path: str
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
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        directory: str = "."
    ) -> List[Dict[str, Any]]:
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

    # =========================================================================
    # SHELL OPERATIONS (for agent tools)
    # =========================================================================

    @abstractmethod
    async def execute_command(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        command: List[str],
        timeout: int = 120,
        working_dir: Optional[str] = None
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
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str
    ) -> Dict[str, Any]:
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
        self,
        user_id: UUID,
        project_id: str,
        container_name: Optional[str] = None
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
    # CLEANUP
    # =========================================================================

    @abstractmethod
    async def cleanup_idle_environments(
        self,
        idle_timeout_minutes: int = 30
    ) -> List[str]:
        """
        Cleanup idle environments based on deployment mode strategy.

        Docker: Two-tier cleanup (scale to 0, then delete)
        Kubernetes: Hibernation to S3 or scale to 0

        Args:
            idle_timeout_minutes: Minutes of inactivity before action

        Returns:
            List of project keys that were cleaned up
        """
        pass

    # =========================================================================
    # UTILITY METHODS (default implementations)
    # =========================================================================

    def get_container_url(
        self,
        project_slug: str,
        container_name: str
    ) -> str:
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
        safe_name = container_name.lower().replace(' ', '-').replace('_', '-')
        safe_name = ''.join(c for c in safe_name if c.isalnum() or c == '-')

        # Build hostname
        hostname = f"{project_slug}-{safe_name}.{settings.app_domain}"

        # Protocol based on deployment mode
        protocol = "https" if self.deployment_mode.is_kubernetes else "http"

        return f"{protocol}://{hostname}"
