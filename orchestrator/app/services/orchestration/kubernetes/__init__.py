"""
Kubernetes Orchestration Module - S3 Sandwich Architecture

This module contains all Kubernetes-specific orchestration code:
- KubernetesClient: Low-level Kubernetes API interactions
- KubernetesHelpers: Helper functions for manifests, init containers, S3 lifecycle
- KubernetesContainerManager: Container lifecycle management

S3 Sandwich Pattern:
1. On start: Hydrate project from S3 (init container)
2. During use: Work on block storage (fast local I/O)
3. On stop: Dehydrate project to S3 (preStop hook)

Pod Affinity:
- Multi-container projects share a single PVC
- Pod affinity ensures all containers run on the same node
- Required for ReadWriteOnce (RWO) block storage

These are used internally by KubernetesOrchestrator.
"""

from .client import KubernetesClient, get_k8s_client
from .helpers import (
    # Pod Affinity
    create_pod_affinity_spec,
    get_standard_labels,
    # PVC and Deployment
    create_pvc_manifest,
    create_file_manager_deployment,
    create_container_deployment,
    create_service_manifest,
    create_ingress_manifest,
    create_network_policy_manifest,
    # Script generation
    generate_git_clone_script,
    generate_s3_upload_script,
    generate_s3_download_script,
)
from .manager import KubernetesContainerManager, get_k8s_container_manager

__all__ = [
    # Client
    "KubernetesClient",
    "get_k8s_client",
    # Pod Affinity Helpers
    "create_pod_affinity_spec",
    "get_standard_labels",
    # Manifest Helpers
    "create_pvc_manifest",
    "create_file_manager_deployment",
    "create_container_deployment",
    "create_service_manifest",
    "create_ingress_manifest",
    "create_network_policy_manifest",
    # Script generation
    "generate_git_clone_script",
    "generate_s3_upload_script",
    "generate_s3_download_script",
    # Manager
    "KubernetesContainerManager",
    "get_k8s_container_manager",
]
