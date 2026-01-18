# Minikube Setup Guide

This guide covers deploying Tesslate Studio to a local Kubernetes cluster using Minikube from a completely fresh start.

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

## Fresh Start: Complete Setup

Follow these steps to get Tesslate Studio running on minikube from scratch.

### Step 1: Create Minikube Cluster

```powershell
# Start minikube with custom profile name
minikube start -p tesslate --driver=docker --memory=4096 --cpus=2

# Enable ingress addon (required for routing)
minikube -p tesslate addons enable ingress

# Verify cluster is running
kubectl get nodes
```

### Step 2: Start Tunnel (Required for Ingress)

Open a **separate terminal** and run:

```powershell
# This must run continuously in the background
minikube -p tesslate tunnel
```

Keep this terminal open while using the cluster. The tunnel allows `*.localhost` domains to route to your services.

### Step 3: Build All Docker Images

Build all three images with `--no-cache` to ensure fresh builds:

```powershell
# Build backend image
docker build --no-cache -t tesslate-backend:latest -f orchestrator/Dockerfile orchestrator/

# Build frontend image
docker build --no-cache -t tesslate-frontend:latest -f app/Dockerfile.prod app/

# Build devserver image (for user project containers)
docker build --no-cache -t tesslate-devserver:latest -f orchestrator/Dockerfile.devserver orchestrator/
```

### Step 4: Load Images into Minikube

Minikube runs its own Docker daemon. Load images into it:

```powershell
minikube -p tesslate image load tesslate-backend:latest
minikube -p tesslate image load tesslate-frontend:latest
minikube -p tesslate image load tesslate-devserver:latest
```

### Step 5: Configure Secrets

Copy and configure the secrets file:

```powershell
# Copy template if not exists
cp k8s/.env.example k8s/.env.minikube

# Edit with your values
notepad k8s/.env.minikube
```

Required values in `.env.minikube`:
- `DATABASE_URL` - PostgreSQL connection string (default works for local)
- `SECRET_KEY` - JWT signing key (generate a random string)
- `LITELLM_API_KEY` - Your LLM API key (OpenAI, Anthropic, etc.)

### Step 6: Apply Kubernetes Manifests

```powershell
# Apply all manifests for minikube
kubectl apply -k k8s/overlays/minikube

# Wait for pods to be ready
kubectl rollout status deployment/postgres -n tesslate --timeout=120s
kubectl rollout status deployment/tesslate-backend -n tesslate --timeout=120s
kubectl rollout status deployment/tesslate-frontend -n tesslate --timeout=120s
```

### Step 7: Run Seed Scripts

Seed the database with marketplace agents and bases:

```powershell
# Get backend pod name
$POD = kubectl get pods -n tesslate -l app=tesslate-backend -o jsonpath='{.items[0].metadata.name}'

# Copy and run seed scripts
kubectl cp scripts/seed/seed_marketplace_agents.py tesslate/${POD}:/tmp/seed_marketplace_agents.py
kubectl exec -n tesslate $POD -- python /tmp/seed_marketplace_agents.py

kubectl cp scripts/seed/seed_opensource_agents.py tesslate/${POD}:/tmp/seed_opensource_agents.py
kubectl exec -n tesslate $POD -- python /tmp/seed_opensource_agents.py

# Seed bases (already in container)
kubectl exec -n tesslate $POD -- python /app/seed_bases.py
```

### Step 8: Access the Application

With the tunnel running, access at:

- **Frontend**: http://localhost/
- **Backend API**: http://localhost/api/

User project containers will be accessible at `http://{project-slug}-{container}.localhost`

## Key Differences from AWS EKS

| Feature | Minikube | AWS EKS |
|---------|----------|---------|
| **Protocol** | HTTP (no TLS) | HTTPS (TLS) |
| **VolumeSnapshots** | Not supported | EBS snapshots |
| **Hibernation** | Pod stops, PVC persists | Snapshot created |
| **Data persistence** | PVC survives restarts | Snapshot-based |
| **DNS resolution** | Via tunnel | Public DNS |

### What Works on Minikube

- Creating and running projects
- Container preview (via `*.localhost`)
- Code editing and AI chat
- File management
- All API functionality

### What Doesn't Work on Minikube

- **VolumeSnapshots/Timeline** - Minikube doesn't support EBS snapshots
- **Hibernation with snapshots** - Projects just stop, no snapshot created
- **HTTPS** - Local dev uses HTTP only

### Data Persistence on Minikube

Your project data persists as long as:
- Pod restarts → Data survives (PVC remains)
- Minikube stops/starts → Data survives (PVCs persist)
- Minikube cluster deleted → **Data lost**

## Updating Images

**CRITICAL**: Minikube caches images and does NOT overwrite existing images with the same tag. Always delete old images before loading new ones.

### Update Backend

```powershell
# 1. Delete old image from minikube
minikube -p tesslate ssh -- docker rmi -f tesslate-backend:latest

# 2. Rebuild with --no-cache
docker build --no-cache -t tesslate-backend:latest -f orchestrator/Dockerfile orchestrator/

# 3. Load new image
minikube -p tesslate image load tesslate-backend:latest

# 4. Restart pod
kubectl delete pod -n tesslate -l app=tesslate-backend

# 5. Wait for ready
kubectl rollout status deployment/tesslate-backend -n tesslate --timeout=120s
```

### Update Frontend

```powershell
minikube -p tesslate ssh -- docker rmi -f tesslate-frontend:latest
docker build --no-cache -t tesslate-frontend:latest -f app/Dockerfile.prod app/
minikube -p tesslate image load tesslate-frontend:latest
kubectl delete pod -n tesslate -l app=tesslate-frontend
```

### Update Devserver

```powershell
minikube -p tesslate ssh -- docker rmi -f tesslate-devserver:latest
docker build --no-cache -t tesslate-devserver:latest -f orchestrator/Dockerfile.devserver orchestrator/
minikube -p tesslate image load tesslate-devserver:latest
```

## Environment Configuration

Key settings in `k8s/overlays/minikube/backend-patch.yaml`:

| Setting | Value | Description |
|---------|-------|-------------|
| `K8S_DEVSERVER_IMAGE` | `tesslate-devserver:latest` | Image for user containers |
| `K8S_IMAGE_PULL_SECRET` | (empty) | No registry secret needed |
| `K8S_IMAGE_PULL_POLICY` | `Never` | Use local images |
| `K8S_WILDCARD_TLS_SECRET` | (empty) | No TLS, use HTTP |

## Common Issues and Fixes

### Image Not Updating After Rebuild

**Problem**: Code changes not appearing after rebuilding.

**Solution**: Delete image from minikube first:
```powershell
minikube -p tesslate ssh -- docker rmi -f tesslate-backend:latest
# Then rebuild and load
```

### Pod Stuck in ImagePullBackOff

**Problem**: Pod cannot pull the image.

**Solution**: Load image into minikube:
```powershell
minikube -p tesslate image load tesslate-backend:latest
kubectl delete pod -n tesslate -l app=tesslate-backend
```

### Container Preview Stuck on "Health Checking"

**Problem**: Container is running but preview won't load.

**Possible causes**:
1. Tunnel not running → Start `minikube -p tesslate tunnel`
2. Ingress not ready → Wait or check `kubectl get ingress -n proj-*`

### User Container 503 Error

**Problem**: Project container URL returns 503.

**Solution**:
```powershell
# Check pod status
kubectl get pods -n proj-<project-uuid>

# Check logs
kubectl logs -n proj-<project-uuid> <pod-name> -c dev-server
```

### Database Migration Errors

**Problem**: Backend fails to start with migration errors.

**Solution**: The backend now runs migrations automatically on startup. If you need to reset:
```powershell
# Delete postgres PVC to start fresh
kubectl delete pvc postgres-pvc -n tesslate
kubectl delete pod -n tesslate -l app=postgres
# Wait for postgres to restart, then restart backend
kubectl delete pod -n tesslate -l app=tesslate-backend
```

## Quick Reference Commands

```powershell
# Cluster Management
minikube start -p tesslate --driver=docker
minikube stop -p tesslate
minikube delete -p tesslate  # WARNING: Deletes all data

# Check Status
kubectl get pods -n tesslate
kubectl get pods --all-namespaces | grep proj-
kubectl logs -f deployment/tesslate-backend -n tesslate

# Image Management
minikube -p tesslate ssh -- docker images | grep tesslate
minikube -p tesslate image load <image>:<tag>

# Apply Manifests
kubectl apply -k k8s/overlays/minikube

# Port Forwarding (alternative to tunnel)
kubectl port-forward -n tesslate svc/tesslate-frontend-service 5000:80
kubectl port-forward -n tesslate svc/tesslate-backend-service 8000:8000
```

## Clean Restart

To completely reset and start fresh:

```powershell
# Delete the minikube cluster
minikube delete -p tesslate

# Remove local Docker images (optional)
docker rmi tesslate-backend:latest tesslate-frontend:latest tesslate-devserver:latest

# Start fresh
minikube start -p tesslate --driver=docker --memory=4096 --cpus=2
minikube -p tesslate addons enable ingress

# Follow "Fresh Start" steps above
```

## Next Steps

- [AWS Deployment](aws-deployment.md) - Deploy to production
- [Troubleshooting](troubleshooting.md) - More debugging tips
