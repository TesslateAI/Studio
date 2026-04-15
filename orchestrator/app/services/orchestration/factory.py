"""
Orchestrator Factory

Provides centralized creation and caching of orchestrators based on deployment mode.
This eliminates the need for scattered if/else blocks checking deployment mode.
"""

import logging

from .base import BaseOrchestrator
from .deployment_mode import DeploymentMode

logger = logging.getLogger(__name__)

# Cached orchestrator instances (singleton pattern)
_orchestrators: dict[DeploymentMode, BaseOrchestrator] = {}


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
    def create_orchestrator(mode: DeploymentMode | None = None) -> BaseOrchestrator:
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

        # Desktop is a shell mode — projects resolve per-row via resolve_for_project.
        # When no project context is available, fall back to LOCAL (the desktop default).
        if mode == DeploymentMode.DESKTOP:
            mode = DeploymentMode.LOCAL

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

        elif mode == DeploymentMode.LOCAL:
            from .local import LocalOrchestrator

            orchestrator = LocalOrchestrator()
            logger.info("[ORCHESTRATOR] Created Local orchestrator")

        else:
            raise ValueError(f"Unsupported deployment mode: {mode}")

        # Cache the instance
        _orchestrators[mode] = orchestrator

        return orchestrator

    @staticmethod
    def resolve_for_project(project: object) -> BaseOrchestrator:
        """
        Resolve the orchestrator for a specific project row.

        Reads `project.runtime` (`local` | `docker` | `k8s`) and returns the
        matching cached orchestrator. Projects without a runtime attribute
        fall back to the deployment-wide mode; under `DEPLOYMENT_MODE=desktop`
        the default is `local` so legacy rows still open in-process.

        Values map as follows:
          - "local"      → DeploymentMode.LOCAL
          - "docker"     → DeploymentMode.DOCKER
          - "k8s"        → DeploymentMode.KUBERNETES
          - unset / None → deployment-wide default (with desktop → LOCAL)
        """
        runtime = getattr(project, "runtime", None)
        if runtime is None:
            mode = OrchestratorFactory.get_deployment_mode()
            if mode == DeploymentMode.DESKTOP:
                mode = DeploymentMode.LOCAL
            return OrchestratorFactory.create_orchestrator(mode)

        runtime_str = str(runtime).lower()
        mapping = {
            "local": DeploymentMode.LOCAL,
            "docker": DeploymentMode.DOCKER,
            "k8s": DeploymentMode.KUBERNETES,
            "kubernetes": DeploymentMode.KUBERNETES,
        }
        target = mapping.get(runtime_str)
        if target is None:
            raise ValueError(
                f"Unsupported Project.runtime: '{runtime}'. Expected one of: local, docker, k8s"
            )
        return OrchestratorFactory.create_orchestrator(target)

    @staticmethod
    def is_docker_mode() -> bool:
        """Check if running in Docker deployment mode."""
        return OrchestratorFactory.get_deployment_mode() == DeploymentMode.DOCKER

    @staticmethod
    def is_kubernetes_mode() -> bool:
        """Check if running in Kubernetes deployment mode."""
        return OrchestratorFactory.get_deployment_mode() == DeploymentMode.KUBERNETES

    @staticmethod
    def is_local_mode() -> bool:
        """Check if running in local or desktop deployment mode.

        Both LOCAL and DESKTOP use the LocalOrchestrator / LocalPTYBroker stack.
        DESKTOP is the Tauri shell mode whose per-project runtime defaults to LOCAL.
        """
        mode = OrchestratorFactory.get_deployment_mode()
        return mode in (DeploymentMode.LOCAL, DeploymentMode.DESKTOP)

    @staticmethod
    def clear_cache() -> None:
        """Clear cached orchestrator instances (for testing)."""
        global _orchestrators
        _orchestrators = {}
        logger.info("[ORCHESTRATOR] Cleared orchestrator cache")


def get_orchestrator(mode: DeploymentMode | None = None) -> BaseOrchestrator:
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


def is_local_mode() -> bool:
    """
    Convenience function to check local (filesystem + subprocess) deployment mode.

    Use this instead of:
        if settings.deployment_mode == "local":

    Use this:
        if is_local_mode():
    """
    return OrchestratorFactory.is_local_mode()


def get_deployment_mode() -> DeploymentMode:
    """
    Get the current deployment mode.

    Returns:
        DeploymentMode enum value
    """
    return OrchestratorFactory.get_deployment_mode()
