"""
Kubernetes Orchestration Module - EBS VolumeSnapshot Architecture

This module contains all Kubernetes-specific orchestration code:
- KubernetesClient: Low-level Kubernetes API interactions
- KubernetesHelpers: Helper functions for manifests, init containers
- KubernetesContainerManager: Container lifecycle management

EBS VolumeSnapshot Pattern (replaces S3 Sandwich):
1. On stop: Create EBS VolumeSnapshot from PVC (< 5 seconds)
2. On start: Create PVC from snapshot (lazy load - instant)
3. Full volume preserved: node_modules included, no npm install needed

Pod Affinity:
- Multi-container projects share a single PVC
- Pod affinity ensures all containers run on the same node
- Required for ReadWriteOnce (RWO) block storage

These are used internally by KubernetesOrchestrator.
"""

from .client import KubernetesClient, get_k8s_client
from .helpers import (
    create_container_deployment,
    create_file_manager_deployment,
    create_ingress_manifest,
    create_network_policy_manifest,
    # Pod Affinity
    create_pod_affinity_spec,
    # PVC and Deployment
    create_pvc_manifest,
    create_service_manifest,
    # Script generation
    generate_git_clone_script,
    get_standard_labels,
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
    # Manager
    "KubernetesContainerManager",
    "get_k8s_container_manager",
]
