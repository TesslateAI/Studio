"""
Kubernetes Orchestration Module

This module contains all Kubernetes-specific orchestration code:
- KubernetesClient: Low-level Kubernetes API interactions
- KubernetesHelpers: Helper functions for manifests, init containers, etc.
- KubernetesContainerManager: Container lifecycle management

These are used internally by KubernetesOrchestrator.
"""

from .client import KubernetesClient, get_k8s_client
from .helpers import (
    create_s3_init_container_manifest,
    create_dehydration_lifecycle_hook,
    create_dynamic_pvc_manifest,
    create_deployment_manifest_s3,
)
from .manager import KubernetesContainerManager, get_k8s_container_manager

__all__ = [
    # Client
    "KubernetesClient",
    "get_k8s_client",
    # Helpers
    "create_s3_init_container_manifest",
    "create_dehydration_lifecycle_hook",
    "create_dynamic_pvc_manifest",
    "create_deployment_manifest_s3",
    # Manager
    "KubernetesContainerManager",
    "get_k8s_container_manager",
]
