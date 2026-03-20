# Tesslate Studio - Minikube Development Environment

This directory contains scripts for setting up and testing Tesslate Studio's S3 Sandwich architecture on a local Minikube cluster.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     Minikube Cluster                            │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐  ┌─────────────────────────────────────┐  │
│  │  minio-system   │  │           tesslate                   │  │
│  │  ┌───────────┐  │  │  ┌──────────┐  ┌──────────────────┐ │  │
│  │  │   MinIO   │  │  │  │ Backend  │  │  User Projects   │ │  │
│  │  │ (S3 API)  │◄─┼──┼──│          │  │                  │ │  │
│  │  └───────────┘  │  │  └──────────┘  │  ┌────────────┐  │ │  │
│  │                 │  │                │  │ Frontend   │  │ │  │
│  │  Bucket:        │  │  ┌──────────┐  │  │ Container  │  │ │  │
│  │  tesslate-      │  │  │ Frontend │  │  └────────────┘  │ │  │
│  │  projects       │  │  │   App    │  │  ┌────────────┐  │ │  │
│  │                 │  │  └──────────┘  │  │ Backend    │  │ │  │
│  └─────────────────┘  │                │  │ Container  │  │ │  │
│                       │  ┌──────────┐  │  └────────────┘  │ │  │
│                       │  │ Postgres │  │         ▲        │ │  │
│                       │  │    DB    │  │    Pod Affinity  │ │  │
│                       │  └──────────┘  │    (Same Node)   │ │  │
│                       │                └──────────────────┘ │  │
│                       └─────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## S3 Sandwich Pattern

The S3 Sandwich pattern provides efficient project hibernation:

1. **Hydration (Start)**: Download project from S3 → Extract to PVC
2. **Active Work**: Dev server runs, changes happen on fast block storage
3. **Dehydration (Stop)**: Compress project → Upload to S3 → Delete resources

This allows:
- ✅ Fast local I/O during development
- ✅ Persistent storage across sessions
- ✅ Efficient resource cleanup when idle
- ✅ Pay only for active compute time

## Prerequisites

- Docker Desktop (running)
- Minikube (`brew install minikube` or `choco install minikube`)
- kubectl (`brew install kubectl` or `choco install kubernetes-cli`)

## Quick Start

```bash
# Setup Minikube with MinIO
./setup.sh

# Run S3 Sandwich tests
./test-s3-sandwich.sh

# Run Pod Affinity tests
./test-pod-affinity.sh

# Teardown resources (keep cluster)
./teardown.sh

# Teardown everything (delete cluster)
./teardown.sh --all
```

## Scripts

| Script | Description |
|--------|-------------|
| `setup.sh` | Creates Minikube cluster, deploys MinIO, and applies Kustomize overlays |
| `teardown.sh` | Removes resources, optionally deletes cluster |
| `test-s3-sandwich.sh` | Tests hydration/dehydration with MinIO |
| `test-pod-affinity.sh` | Tests multi-container pod scheduling |

## MinIO Console Access

```bash
# Port-forward MinIO console
kubectl port-forward -n minio-system svc/minio 9001:9001

# Open http://localhost:9001
# Login: tesslate-admin / tesslate-secret-key-change-in-prod
```

## Useful Commands

```bash
# Check pod status
kubectl get pods -n tesslate
kubectl get pods -n minio-system

# View logs
kubectl logs -n tesslate -f <pod-name>

# Check S3 bucket contents (via MinIO pod)
kubectl exec -n minio-system deploy/minio -- mc ls local/tesslate-projects

# Open Kubernetes dashboard
minikube dashboard --profile tesslate
```

## Troubleshooting

### Pods stuck in Pending

Check if storage is available:
```bash
kubectl get pvc -n tesslate
kubectl describe pvc <pvc-name> -n tesslate
```

### MinIO not accessible

Check MinIO pod logs:
```bash
kubectl logs -n minio-system deploy/minio
```

### Pod affinity failures

If pods can't schedule due to affinity, check node resources:
```bash
kubectl describe nodes
kubectl get events -n tesslate
```

## Configuration

Storage class for Minikube uses `k8s.io/minikube-hostpath` provisioner for PVCs.

VolumeSnapshot support is provided by the **btrfs-CSI driver**, which is built and deployed during setup:
- `tesslate-btrfs-csi-node` (DaemonSet in `kube-system`) - CSI node driver for btrfs-based snapshots
- `tesslate-volume-hub` (Deployment in `kube-system`) - Volume lifecycle and placement management
- VolumeSnapshot CRDs from kubernetes-csi/external-snapshotter v8.2.0

This enables Timeline/hibernation snapshot features that previously only worked on AWS EKS.

See `k8s/overlays/minikube/` for Minikube-specific configuration:
- `storage-class.yaml` - StorageClass definition
- `backend-patch.yaml` - Backend deployment patches
- `secrets/` - Local development secrets
