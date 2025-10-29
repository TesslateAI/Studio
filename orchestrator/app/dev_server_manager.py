"""
Development server manager facade - Deployment strategy selector.

This module provides a unified interface for container management that works
with both Docker+Traefik (local development) and Kubernetes (production) deployments.

The deployment mode is selected via the DEPLOYMENT_MODE environment variable:
- "docker": Uses Docker containers with Traefik routing (default)
- "kubernetes": Uses Kubernetes Deployments, Services, and Ingresses

Both implementations expose the same interface, so the rest of the application
doesn't need to know which deployment mode is being used.
"""

from typing import Optional
from .config import get_settings
from .base_container_manager import BaseContainerManager
import logging

logger = logging.getLogger(__name__)

# Lazy import to avoid loading unused dependencies
_container_manager_instance: Optional[BaseContainerManager] = None


def get_container_manager() -> BaseContainerManager:
    """
    Get the appropriate container manager based on deployment mode.

    Returns:
        BaseContainerManager instance (either Docker or Kubernetes implementation)
    """
    global _container_manager_instance

    if _container_manager_instance is not None:
        return _container_manager_instance

    settings = get_settings()
    deployment_mode = settings.deployment_mode.lower()

    logger.info(f"Initializing container manager for deployment mode: {deployment_mode}")

    if deployment_mode == "kubernetes":
        from .k8s_container_manager import KubernetesContainerManager
        _container_manager_instance = KubernetesContainerManager()
        logger.info("✅ Kubernetes container manager initialized")
    elif deployment_mode == "docker":
        from .docker_container_manager import DockerContainerManager
        _container_manager_instance = DockerContainerManager()
        logger.info("✅ Docker container manager initialized")
    else:
        logger.error(f"Invalid DEPLOYMENT_MODE: {deployment_mode}. Must be 'docker' or 'kubernetes'")
        raise ValueError(
            f"Invalid DEPLOYMENT_MODE: {deployment_mode}. "
            f"Must be 'docker' or 'kubernetes'. Check your .env file."
        )

    return _container_manager_instance


# Global instance - lazy initialization based on deployment mode
# This maintains backward compatibility with existing code that imports dev_container_manager
dev_container_manager: Optional[BaseContainerManager] = None


def __getattr__(name):
    """
    Module-level attribute access for backward compatibility.

    This allows existing code like `from .dev_server_manager import dev_container_manager`
    to continue working while lazily initializing the correct manager.
    """
    global dev_container_manager

    if name == "dev_container_manager":
        if dev_container_manager is None:
            dev_container_manager = get_container_manager()
        return dev_container_manager

    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
