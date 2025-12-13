"""
Services Module

This module contains all backend services for Tesslate Studio.

Key Submodules:
- orchestration: Unified container orchestration (Docker/K8s)
- deployment: External deployment providers (Vercel, Netlify, Cloudflare)
- litellm_service: AI model routing via LiteLLM

Usage:
    # Orchestration (preferred)
    from app.services.orchestration import get_orchestrator, is_docker_mode

    # Legacy (deprecated - use orchestration module instead)
    from app.services.docker_compose_orchestrator import get_compose_orchestrator
    from app.services.kubernetes_orchestrator import get_kubernetes_orchestrator
"""

# Re-export orchestration module for convenience
from .orchestration import (
    get_orchestrator,
    is_docker_mode,
    is_kubernetes_mode,
    get_deployment_mode,
    DeploymentMode,
    BaseOrchestrator,
)

__all__ = [
    # Orchestration
    "get_orchestrator",
    "is_docker_mode",
    "is_kubernetes_mode",
    "get_deployment_mode",
    "DeploymentMode",
    "BaseOrchestrator",
]
