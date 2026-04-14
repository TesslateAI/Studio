"""
Orchestration Module - Unified Container Management for Docker and Kubernetes

This module provides a unified interface for managing container orchestration
across different deployment modes (Docker Compose, Kubernetes).

Architecture:
- DeploymentMode enum: Defines supported deployment modes
- BaseOrchestrator: Abstract interface all orchestrators implement
- OrchestratorFactory: Creates the appropriate orchestrator based on config
- DockerOrchestrator: Docker Compose implementation
- KubernetesOrchestrator: Kubernetes implementation
- LocalOrchestrator: Direct filesystem + subprocess implementation

Usage:
    from app.services.orchestration import get_orchestrator, DeploymentMode

    # Get orchestrator based on config
    orchestrator = get_orchestrator()

    # Or get specific orchestrator
    orchestrator = get_orchestrator(DeploymentMode.KUBERNETES)

    # Use unified interface
    result = await orchestrator.start_project(project, containers, connections, user_id, db)
"""

from .base import BaseOrchestrator
from .deployment_mode import DeploymentMode
from .factory import (
    OrchestratorFactory,
    get_deployment_mode,
    get_orchestrator,
    is_docker_mode,
    is_kubernetes_mode,
    is_local_mode,
)
from .local import PTY_SESSIONS, LocalOrchestrator, PtySessionRegistry

__all__ = [
    # Enums
    "DeploymentMode",
    # Base class
    "BaseOrchestrator",
    # Concrete orchestrators (re-exported for direct instantiation in tests)
    "LocalOrchestrator",
    # Factory
    "get_orchestrator",
    "OrchestratorFactory",
    # Convenience functions
    "is_docker_mode",
    "is_kubernetes_mode",
    "is_local_mode",
    "get_deployment_mode",
    # PTY session registry
    "PtySessionRegistry",
    "PTY_SESSIONS",
]
