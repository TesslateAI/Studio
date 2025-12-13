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

Usage:
    from app.services.orchestration import get_orchestrator, DeploymentMode

    # Get orchestrator based on config
    orchestrator = get_orchestrator()

    # Or get specific orchestrator
    orchestrator = get_orchestrator(DeploymentMode.KUBERNETES)

    # Use unified interface
    result = await orchestrator.start_project(project, containers, connections, user_id, db)
"""

from .deployment_mode import DeploymentMode
from .base import BaseOrchestrator
from .factory import (
    get_orchestrator,
    OrchestratorFactory,
    is_docker_mode,
    is_kubernetes_mode,
    get_deployment_mode,
)

__all__ = [
    # Enums
    "DeploymentMode",
    # Base class
    "BaseOrchestrator",
    # Factory
    "get_orchestrator",
    "OrchestratorFactory",
    # Convenience functions
    "is_docker_mode",
    "is_kubernetes_mode",
    "get_deployment_mode",
]
