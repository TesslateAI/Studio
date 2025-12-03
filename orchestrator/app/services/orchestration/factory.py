"""
Orchestrator Factory

Provides centralized creation and caching of orchestrators based on deployment mode.
This eliminates the need for scattered if/else blocks checking deployment mode.
"""

import logging
from typing import Optional, Dict

from .deployment_mode import DeploymentMode
from .base import BaseOrchestrator

logger = logging.getLogger(__name__)

# Cached orchestrator instances (singleton pattern)
_orchestrators: Dict[DeploymentMode, BaseOrchestrator] = {}


class OrchestratorFactory:
    """
    Factory for creating orchestrator instances based on deployment mode.

    Uses lazy initialization and singleton pattern - orchestrators are
    created on first use and cached for subsequent calls.
    """

    @staticmethod
    def get_deployment_mode() -> DeploymentMode:
        """
        Get the current deployment mode from config.

        Returns:
            DeploymentMode enum value
        """
        from ...config import get_settings
        settings = get_settings()
        return DeploymentMode.from_string(settings.deployment_mode)

    @staticmethod
    def create_orchestrator(mode: Optional[DeploymentMode] = None) -> BaseOrchestrator:
        """
        Create or get cached orchestrator for the specified deployment mode.

        Args:
            mode: Deployment mode (default: from config)

        Returns:
            Orchestrator instance implementing BaseOrchestrator

        Raises:
            ValueError: If deployment mode is not supported
        """
        if mode is None:
            mode = OrchestratorFactory.get_deployment_mode()

        # Return cached instance if available
        if mode in _orchestrators:
            return _orchestrators[mode]

        # Create new instance
        orchestrator: BaseOrchestrator

        if mode == DeploymentMode.DOCKER:
            from .docker import DockerOrchestrator
            orchestrator = DockerOrchestrator()
            logger.info("[ORCHESTRATOR] Created Docker orchestrator")

        elif mode == DeploymentMode.KUBERNETES:
            from .kubernetes_orchestrator import KubernetesOrchestrator
            orchestrator = KubernetesOrchestrator()
            logger.info("[ORCHESTRATOR] Created Kubernetes orchestrator")

        else:
            raise ValueError(f"Unsupported deployment mode: {mode}")

        # Cache the instance
        _orchestrators[mode] = orchestrator

        return orchestrator

    @staticmethod
    def is_docker_mode() -> bool:
        """Check if running in Docker deployment mode."""
        return OrchestratorFactory.get_deployment_mode() == DeploymentMode.DOCKER

    @staticmethod
    def is_kubernetes_mode() -> bool:
        """Check if running in Kubernetes deployment mode."""
        return OrchestratorFactory.get_deployment_mode() == DeploymentMode.KUBERNETES

    @staticmethod
    def clear_cache() -> None:
        """Clear cached orchestrator instances (for testing)."""
        global _orchestrators
        _orchestrators = {}
        logger.info("[ORCHESTRATOR] Cleared orchestrator cache")


def get_orchestrator(mode: Optional[DeploymentMode] = None) -> BaseOrchestrator:
    """
    Get an orchestrator instance.

    This is the main entry point for obtaining an orchestrator.
    Uses the factory pattern with singleton caching.

    Args:
        mode: Deployment mode (default: from config)

    Returns:
        Orchestrator instance

    Example:
        # Get orchestrator for current config
        orchestrator = get_orchestrator()

        # Get specific orchestrator
        k8s_orchestrator = get_orchestrator(DeploymentMode.KUBERNETES)
    """
    return OrchestratorFactory.create_orchestrator(mode)


def is_docker_mode() -> bool:
    """
    Convenience function to check Docker deployment mode.

    Use this instead of:
        if settings.deployment_mode == "docker":

    Use this:
        if is_docker_mode():
    """
    return OrchestratorFactory.is_docker_mode()


def is_kubernetes_mode() -> bool:
    """
    Convenience function to check Kubernetes deployment mode.

    Use this instead of:
        if settings.deployment_mode == "kubernetes":

    Use this:
        if is_kubernetes_mode():
    """
    return OrchestratorFactory.is_kubernetes_mode()


def get_deployment_mode() -> DeploymentMode:
    """
    Get the current deployment mode.

    Returns:
        DeploymentMode enum value
    """
    return OrchestratorFactory.get_deployment_mode()
