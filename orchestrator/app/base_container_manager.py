from abc import ABC, abstractmethod
from typing import Dict, Optional, List, Any
from uuid import UUID


class BaseContainerManager(ABC):
    """
    Abstract base class for container management systems.

    Enforces a common interface for both Docker and Kubernetes implementations,
    allowing the orchestrator to switch between deployment modes seamlessly.
    """

    @abstractmethod
    def _get_project_key(self, user_id: UUID, project_id: str) -> str:
        """Generate a unique project key for container/environment management."""
        pass

    @abstractmethod
    def _get_container_access_url(self, hostname: str) -> str:
        """Get the access URL for a development environment."""
        pass

    @abstractmethod
    async def start_container(self, project_path: str, project_id: str, user_id: UUID, **kwargs) -> str:
        """
        Start a development environment.

        Args:
            project_path: Path to project directory
            project_id: Project ID
            user_id: User ID
            **kwargs: Additional implementation-specific parameters

        Returns:
            Access URL for the development environment
        """
        pass

    @abstractmethod
    async def stop_container(self, project_id: str, user_id: UUID = None) -> None:
        """
        Stop and remove a development environment.

        Args:
            project_id: Project ID
            user_id: User ID (optional for backwards compatibility)
        """
        pass

    @abstractmethod
    async def restart_container(self, project_path: str, project_id: str, user_id: UUID) -> str:
        """
        Restart a development environment.

        Args:
            project_path: Path to project directory
            project_id: Project ID
            user_id: User ID

        Returns:
            Access URL for the development environment
        """
        pass

    @abstractmethod
    def get_container_url(self, project_id: str, user_id: UUID = None) -> Optional[str]:
        """
        Get the URL for a project's development environment.

        Args:
            project_id: Project ID
            user_id: User ID (optional for backwards compatibility)

        Returns:
            Access URL or None if not found
        """
        pass

    @abstractmethod
    async def get_container_status(self, project_id: str, user_id: UUID = None) -> Dict[str, Any]:
        """
        Get detailed status of a development environment.

        Args:
            project_id: Project ID
            user_id: User ID (optional for backwards compatibility)

        Returns:
            Dictionary with status information including:
            - status: Current status string
            - running: Boolean indicating if environment is running
            - url: Access URL (if available)
            - Additional implementation-specific fields
        """
        pass

    @abstractmethod
    async def get_all_containers(self) -> List[Dict[str, Any]]:
        """
        Returns a list of all running development environments with their metadata.

        Returns:
            List of dictionaries containing environment information
        """
        pass

    @abstractmethod
    async def stop_all_containers(self) -> None:
        """Stop all development environments."""
        pass

    @abstractmethod
    def track_activity(self, user_id: UUID, project_id: str) -> None:
        """
        Record activity for a project environment.

        Args:
            user_id: User ID
            project_id: Project ID
        """
        pass

    @abstractmethod
    async def cleanup_idle_environments(self, idle_timeout_minutes: int = 30) -> List[str]:
        """
        Cleanup environments that have been idle for longer than the timeout.

        Args:
            idle_timeout_minutes: Minutes of inactivity before cleanup (default: 30)

        Returns:
            List of cleaned up project keys
        """
        pass
