# Image Update Workflow

This guide covers the complete build and deploy workflow for Tesslate Studio container images.

## Why --no-cache is Critical

Docker uses layer caching to speed up builds. However, this can cause issues:

1. **Stale dependencies**: `pip install` or `npm install` may use cached layers even when package.json/pyproject.toml changed
2. **Code not updated**: Source code may not be copied if Docker thinks the layer is unchanged
3. **Minikube caching**: Minikube additionally caches images and does NOT overwrite existing images with the same tag

**Always use `--no-cache` for deployment builds** to ensure your changes are included.

## Minikube Workflow

### Complete Build and Deploy

This is the recommended workflow for any code change:

```powershell
# ============================================
# Backend Image Update
# ============================================

# Step 1: Delete old image from minikube's Docker daemon
minikube -p tesslate ssh -- docker rmi -f tesslate-backend:latest

# Step 2: Delete local image and rebuild with --no-cache
docker rmi -f tesslate-backend:latest
docker build --no-cache -t tesslate-backend:latest -f orchestrator/Dockerfile orchestrator/

# Step 3: Load new image to minikube
minikube -p tesslate image load tesslate-backend:latest

# Step 4: Force pod restart (delete pod, not rollout restart)
kubectl delete pod -n tesslate -l app=tesslate-backend

# Step 5: Wait for new pod to be ready
kubectl rollout status deployment/tesslate-backend -n tesslate --timeout=120s

# Step 6: Verify fix is deployed
kubectl exec -n tesslate deployment/tesslate-backend -- grep "expected-string" /app/app/some_file.py
```

### Frontend Image Update

```powershell
# Delete old image from minikube
minikube -p tesslate ssh -- docker rmi -f tesslate-frontend:latest

# Rebuild with --no-cache
docker rmi -f tesslate-frontend:latest
docker build --no-cache -t tesslate-frontend:latest -f app/Dockerfile.prod app/

# Load to minikube
minikube -p tesslate image load tesslate-frontend:latest

# Restart pod
kubectl delete pod -n tesslate -l app=tesslate-frontend

# Verify
kubectl rollout status deployment/tesslate-frontend -n tesslate --timeout=120s
```

### Devserver Image Update

The devserver runs user project containers:

```powershell
# NOTE: Dockerfile is in orchestrator/, not devserver/
minikube -p tesslate ssh -- docker rmi -f tesslate-devserver:latest
docker rmi -f tesslate-devserver:latest
docker build --no-cache -t tesslate-devserver:latest -f orchestrator/Dockerfile.devserver orchestrator/
minikube -p tesslate image load tesslate-devserver:latest

# No pod restart needed - new user containers will use new image
```

### All Images (Full Rebuild)

```powershell
# Backend
minikube -p tesslate ssh -- docker rmi -f tesslate-backend:latest
docker rmi -f tesslate-backend:latest
docker build --no-cache -t tesslate-backend:latest -f orchestrator/Dockerfile orchestrator/
minikube -p tesslate image load tesslate-backend:latest
kubectl delete pod -n tesslate -l app=tesslate-backend

# Frontend
minikube -p tesslate ssh -- docker rmi -f tesslate-frontend:latest
docker rmi -f tesslate-frontend:latest
docker build --no-cache -t tesslate-frontend:latest -f app/Dockerfile.prod app/
minikube -p tesslate image load tesslate-frontend:latest
kubectl delete pod -n tesslate -l app=tesslate-frontend

# Devserver
minikube -p tesslate ssh -- docker rmi -f tesslate-devserver:latest
docker rmi -f tesslate-devserver:latest
docker build --no-cache -t tesslate-devserver:latest -f orchestrator/Dockerfile.devserver orchestrator/
minikube -p tesslate image load tesslate-devserver:latest

# Wait for all pods
kubectl rollout status deployment/tesslate-backend -n tesslate --timeout=120s
kubectl rollout status deployment/tesslate-frontend -n tesslate --timeout=120s
```

## AWS EKS Workflow

### Prerequisites

```powershell
# Login to ECR (required before push)
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com
```

### Backend Image Update

```powershell
# Step 1: Build with --no-cache
docker build --no-cache -t tesslate-backend:latest -f orchestrator/Dockerfile orchestrator/

# Step 2: Tag for ECR
docker tag tesslate-backend:latest <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend:latest

# Step 3: Push to ECR
docker push <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend:latest

# Step 4: Delete pod to force pull new image (imagePullPolicy is Always)
kubectl delete pod -n tesslate -l app=tesslate-backend

# Step 5: Restart ingress controller (prevents stale endpoint routing)
kubectl rollout restart deployment/ingress-nginx-controller -n ingress-nginx
kubectl rollout status deployment/ingress-nginx-controller -n ingress-nginx --timeout=120s

# Step 6: Verify
kubectl get pods -n tesslate
kubectl logs -n tesslate deployment/tesslate-backend --tail=10
```

### Frontend Image Update

```powershell
# Build, tag, push
docker build --no-cache -t tesslate-frontend:latest -f app/Dockerfile.prod app/
docker tag tesslate-frontend:latest <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-frontend:latest
docker push <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-frontend:latest

# Delete pod
kubectl delete pod -n tesslate -l app=tesslate-frontend

# Verify
kubectl get pods -n tesslate
MSYS_NO_PATHCONV=1 kubectl exec -n tesslate deployment/tesslate-frontend -- ls -la /usr/share/nginx/html/assets/ | grep index
```

### Devserver Image Update

```powershell
# Build, tag, push
docker build --no-cache -t tesslate-devserver:latest -f orchestrator/Dockerfile.devserver orchestrator/
docker tag tesslate-devserver:latest <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-devserver:latest
docker push <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-devserver:latest

# New user containers will automatically use the new image
```

### All Images (Full Release)

```powershell
# Login to ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com

# Backend
docker build --no-cache -t tesslate-backend:latest -f orchestrator/Dockerfile orchestrator/
docker tag tesslate-backend:latest <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend:latest
docker push <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend:latest

# Frontend
docker build --no-cache -t tesslate-frontend:latest -f app/Dockerfile.prod app/
docker tag tesslate-frontend:latest <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-frontend:latest
docker push <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-frontend:latest

# Devserver
docker build --no-cache -t tesslate-devserver:latest -f orchestrator/Dockerfile.devserver orchestrator/
docker tag tesslate-devserver:latest <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-devserver:latest
docker push <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-devserver:latest

# Restart pods
kubectl delete pod -n tesslate -l app=tesslate-frontend
kubectl delete pod -n tesslate -l app=tesslate-backend

# Restart ingress
kubectl rollout restart deployment/ingress-nginx-controller -n ingress-nginx
kubectl rollout status deployment/ingress-nginx-controller -n ingress-nginx --timeout=120s
```

## Verification Steps

### Check Image in Cluster

**Minikube:**
```powershell
minikube -p tesslate ssh -- docker images | grep tesslate
```

**AWS:**
```powershell
# Images are pulled from ECR, check pod's image
kubectl get pods -n tesslate -o jsonpath='{.items[*].spec.containers[*].image}'
```

### Check Pod is Using New Image

```powershell
# Check pod creation time (should be recent)
kubectl get pods -n tesslate -o wide

# Check specific code is present
MSYS_NO_PATHCONV=1 kubectl exec -n tesslate deployment/tesslate-backend -- grep "expected-string" /app/app/file.py
```

### Check Logs for Startup

```powershell
kubectl logs -n tesslate deployment/tesslate-backend --tail=50
kubectl logs -n tesslate deployment/tesslate-frontend --tail=50
```

## Rollback Procedures

### Quick Rollback (Previous Pod)

If you need to quickly revert:

```powershell
# Kubernetes keeps previous ReplicaSet
kubectl rollout undo deployment/tesslate-backend -n tesslate

# Check rollout history
kubectl rollout history deployment/tesslate-backend -n tesslate

# Rollback to specific revision
kubectl rollout undo deployment/tesslate-backend -n tesslate --to-revision=2
```

### Manual Rollback (Previous Image)

**AWS:** You can revert to a previous image by retagging:

```powershell
# Find previous image digest
aws ecr describe-images --repository-name tesslate-backend --query 'imageDetails[*].[imagePushedAt,imageDigest]' --output table

# Pull previous image and retag
docker pull <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend@sha256:<previous-digest>
docker tag <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend@sha256:<previous-digest> <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend:latest
docker push <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend:latest

# Restart pod
kubectl delete pod -n tesslate -l app=tesslate-backend
```

**Minikube:** Rebuild from a previous git commit:

```powershell
# Checkout previous commit
git checkout <previous-commit-hash>

# Rebuild and deploy
minikube -p tesslate ssh -- docker rmi -f tesslate-backend:latest
docker build --no-cache -t tesslate-backend:latest -f orchestrator/Dockerfile orchestrator/
minikube -p tesslate image load tesslate-backend:latest
kubectl delete pod -n tesslate -l app=tesslate-backend

# Return to current branch
git checkout -
```

## Common Mistakes

### 1. Forgetting --no-cache

**Wrong:**
```powershell
docker build -t tesslate-backend:latest -f orchestrator/Dockerfile orchestrator/
```

**Right:**
```powershell
docker build --no-cache -t tesslate-backend:latest -f orchestrator/Dockerfile orchestrator/
```

### 2. Not Deleting Minikube Image First

**Wrong:**
```powershell
docker build --no-cache -t tesslate-backend:latest ...
minikube -p tesslate image load tesslate-backend:latest  # Image already exists, not overwritten!
```

**Right:**
```powershell
minikube -p tesslate ssh -- docker rmi -f tesslate-backend:latest  # Delete first
docker build --no-cache -t tesslate-backend:latest ...
minikube -p tesslate image load tesslate-backend:latest  # Now it loads
```

### 3. Using Rollout Restart Instead of Delete Pod

**Less reliable:**
```powershell
kubectl rollout restart deployment/tesslate-backend -n tesslate
# May use cached image
```

**More reliable:**
```powershell
kubectl delete pod -n tesslate -l app=tesslate-backend
# Forces new pod creation with fresh image pull
```

### 4. Forgetting to Restart Ingress (AWS)

After backend restart, the ingress controller may have stale endpoints:

```powershell
# Always restart ingress after backend changes on AWS
kubectl rollout restart deployment/ingress-nginx-controller -n ingress-nginx
```

## Image Locations

| Image | Dockerfile | Context Directory |
|-------|-----------|-------------------|
| tesslate-backend | `orchestrator/Dockerfile` | `orchestrator/` |
| tesslate-frontend | `app/Dockerfile.prod` | `app/` |
| tesslate-devserver | `orchestrator/Dockerfile.devserver` | `orchestrator/` |

## Quick Reference

### Minikube One-Liner (Backend)

```powershell
minikube -p tesslate ssh -- docker rmi -f tesslate-backend:latest; docker rmi -f tesslate-backend:latest; docker build --no-cache -t tesslate-backend:latest -f orchestrator/Dockerfile orchestrator/; minikube -p tesslate image load tesslate-backend:latest; kubectl delete pod -n tesslate -l app=tesslate-backend
```

### AWS One-Liner (Backend)

```powershell
docker build --no-cache -t tesslate-backend:latest -f orchestrator/Dockerfile orchestrator/ && docker tag tesslate-backend:latest <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend:latest && docker push <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend:latest && kubectl delete pod -n tesslate -l app=tesslate-backend
```

## Next Steps

- [Minikube Setup](minikube-setup.md) - Local Kubernetes setup
- [AWS Deployment](aws-deployment.md) - Production deployment
- [Troubleshooting](troubleshooting.md) - Debug deployment issues
