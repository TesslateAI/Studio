# Minikube Setup Guide

This guide covers deploying Tesslate Studio to a local Kubernetes cluster using Minikube. This is useful for testing Kubernetes features before deploying to production.

## Prerequisites

### Required Software

| Software | Version | Purpose |
|----------|---------|---------|
| Docker Desktop | Latest | Container runtime |
| Minikube | Latest | Local Kubernetes cluster |
| kubectl | Latest | Kubernetes CLI |

### Install Minikube (Windows)

```powershell
# Using Chocolatey
choco install minikube

# Or download from https://minikube.sigs.k8s.io/docs/start/
```

### Install kubectl (Windows)

```powershell
# Using Chocolatey
choco install kubernetes-cli

# Or download from https://kubernetes.io/docs/tasks/tools/
```

## Starting the Cluster

### 1. Create Minikube Cluster

```powershell
# Start minikube with custom profile name
minikube start -p tesslate --driver=docker --memory=4096 --cpus=2

# Enable ingress addon
minikube -p tesslate addons enable ingress

# Verify cluster is running
kubectl get nodes
```

### 2. Start Tunnel (Required for Ingress)

Open a separate terminal and run:

```powershell
# This must run continuously in the background
minikube -p tesslate tunnel
```

Keep this terminal open while using the cluster.

## Building and Loading Images

### CRITICAL: Image Caching Behavior

Minikube caches images and does NOT overwrite existing images with the same tag. You MUST delete old images before loading new ones.

### Build and Load Backend Image

```powershell
# 1. Delete old image from minikube's Docker daemon
minikube -p tesslate ssh -- docker rmi -f tesslate-backend:latest

# 2. Delete local image and rebuild with --no-cache
docker rmi -f tesslate-backend:latest
docker build --no-cache -t tesslate-backend:latest -f orchestrator/Dockerfile orchestrator/

# 3. Load new image to minikube
minikube -p tesslate image load tesslate-backend:latest

# 4. Force pod restart
kubectl delete pod -n tesslate -l app=tesslate-backend
```

### Build and Load Frontend Image

```powershell
# 1. Delete old image from minikube
minikube -p tesslate ssh -- docker rmi -f tesslate-frontend:latest

# 2. Rebuild with --no-cache
docker rmi -f tesslate-frontend:latest
docker build --no-cache -t tesslate-frontend:latest -f app/Dockerfile.prod app/

# 3. Load to minikube
minikube -p tesslate image load tesslate-frontend:latest

# 4. Restart pod
kubectl delete pod -n tesslate -l app=tesslate-frontend
```

### Build and Load Devserver Image

The devserver image runs user project containers:

```powershell
# NOTE: Dockerfile is in orchestrator/, not devserver/
minikube -p tesslate ssh -- docker rmi -f tesslate-devserver:latest
docker rmi -f tesslate-devserver:latest
docker build --no-cache -t tesslate-devserver:latest -f orchestrator/Dockerfile.devserver orchestrator/
minikube -p tesslate image load tesslate-devserver:latest
```

## Applying Manifests

### 1. Create Secrets

Copy and configure the secrets file:

```powershell
# Copy template
cp k8s/.env.example k8s/.env.minikube

# Edit with your values (DATABASE_URL, SECRET_KEY, API keys, etc.)
notepad k8s/.env.minikube
```

### 2. Apply Manifests

```powershell
# Apply all manifests for minikube
kubectl apply -k k8s/overlays/minikube

# Wait for pods to be ready
kubectl rollout status deployment/tesslate-backend -n tesslate --timeout=120s
kubectl rollout status deployment/tesslate-frontend -n tesslate --timeout=120s
```

### 3. Verify Deployment

```powershell
# Check all pods are running
kubectl get pods -n tesslate

# Check services
kubectl get svc -n tesslate

# Check ingress
kubectl get ingress -n tesslate
```

## Accessing the Application

### Option 1: Port Forwarding (Recommended)

```powershell
# Frontend (in separate terminal)
kubectl port-forward -n tesslate svc/tesslate-frontend-service 5000:80

# Backend (in separate terminal)
kubectl port-forward -n tesslate svc/tesslate-backend-service 8000:8000
```

Access at:
- Frontend: http://localhost:5000
- Backend API: http://localhost:8000

### Option 2: Using Tunnel

With `minikube -p tesslate tunnel` running:

```powershell
# Get the ingress IP
kubectl get ingress -n tesslate
```

Add entries to your hosts file (as admin):
```
<INGRESS_IP> studio.localhost
```

## Verifying Deployment

### Check Pod Logs

```powershell
# Backend logs
kubectl logs -f deployment/tesslate-backend -n tesslate

# Frontend logs
kubectl logs -f deployment/tesslate-frontend -n tesslate
```

### Verify Image Content

```powershell
# Check if your code changes are deployed
kubectl exec -n tesslate deployment/tesslate-backend -- grep "your-search-string" /app/app/some_file.py
```

### Check Images in Minikube

```powershell
minikube -p tesslate ssh -- docker images | grep tesslate
```

## Common Issues and Fixes

### Image Not Updating After Rebuild

**Problem**: Code changes not appearing after rebuilding the image.

**Cause**: Minikube caches images and `image load` does not overwrite.

**Solution**:
```powershell
# Delete image from minikube first
minikube -p tesslate ssh -- docker rmi -f tesslate-backend:latest

# Then rebuild and load
docker build --no-cache -t tesslate-backend:latest -f orchestrator/Dockerfile orchestrator/
minikube -p tesslate image load tesslate-backend:latest
kubectl delete pod -n tesslate -l app=tesslate-backend
```

### Pod Stuck in ImagePullBackOff

**Problem**: Pod cannot pull the image.

**Cause**: Image not loaded into minikube.

**Solution**:
```powershell
minikube -p tesslate image load tesslate-backend:latest
kubectl delete pod -n tesslate -l app=tesslate-backend
```

### Tunnel Not Working

**Problem**: Cannot access services through ingress.

**Solution**: Run tunnel as administrator:
```powershell
# Run PowerShell as Administrator
minikube -p tesslate tunnel

# Or use port-forward instead
kubectl port-forward -n tesslate svc/tesslate-frontend-service 5000:80
```

### User Container ImagePullBackOff

**Problem**: User project pods fail with ImagePullBackOff.

**Cause**: K8S_DEVSERVER_IMAGE not set correctly.

**Solution**:
```powershell
# Check the environment variable
kubectl exec -n tesslate deployment/tesslate-backend -- env | grep K8S_DEVSERVER

# Should be: K8S_DEVSERVER_IMAGE=tesslate-devserver:latest
# This is set in k8s/overlays/minikube/backend-patch.yaml
```

### User Container 503 Error

**Problem**: User project URLs return 503.

**Solution**:
```powershell
# Check if pod is running
kubectl get pods -n proj-<project-uuid>

# Check pod events
kubectl describe pod -n proj-<project-uuid>

# Check init container logs (hydration)
kubectl logs -n proj-<uuid> <pod-name> -c hydrate-project

# Check dev server logs
kubectl logs -n proj-<uuid> <pod-name> -c dev-server
```

### NGINX Configuration Snippet Blocked

**Problem**: Ingress fails with "annotation not allowed" error.

**Cause**: Minikube's NGINX Ingress Controller has configuration-snippet disabled.

**Solution**: Use proxy-hide-header annotation instead (already configured in kubernetes_orchestrator.py).

## Quick Reference Commands

```powershell
# Cluster Management
minikube start -p tesslate --driver=docker
minikube stop -p tesslate
minikube delete -p tesslate

# Pod Management
kubectl get pods -n tesslate
kubectl describe pod <pod-name> -n tesslate
kubectl logs -f <pod-name> -n tesslate

# Image Management
minikube -p tesslate ssh -- docker images | grep tesslate
minikube -p tesslate image load <image>:<tag>

# Port Forwarding
kubectl port-forward -n tesslate svc/tesslate-frontend-service 5000:80
kubectl port-forward -n tesslate svc/tesslate-backend-service 8000:8000

# Apply Manifests
kubectl apply -k k8s/overlays/minikube
kubectl delete -k k8s/overlays/minikube
```

## Environment Configuration

Key settings in `k8s/overlays/minikube/backend-patch.yaml`:

| Setting | Value | Description |
|---------|-------|-------------|
| `K8S_DEVSERVER_IMAGE` | `tesslate-devserver:latest` | Image for user containers |
| `K8S_IMAGE_PULL_SECRET` | (empty) | No registry secret needed |
| `S3_ENDPOINT_URL` | `http://minio.minio-system.svc.cluster.local:9000` | MinIO for local S3 |

## Next Steps

- [AWS Deployment](aws-deployment.md) - Deploy to production
- [Image Update Workflow](image-update-workflow.md) - Complete build and deploy workflow
- [Troubleshooting](troubleshooting.md) - More debugging tips
