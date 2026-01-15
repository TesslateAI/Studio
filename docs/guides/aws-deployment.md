# AWS EKS Production Deployment

This guide covers deploying Tesslate Studio to AWS Elastic Kubernetes Service (EKS) for production use.

## Infrastructure Overview

| Component | Value | Description |
|-----------|-------|-------------|
| Region | us-east-1 | AWS region |
| Cluster | <EKS_CLUSTER_NAME> | EKS cluster name |
| Domain | your-domain.com | Production domain (Cloudflare DNS) |
| Registry | ECR | Amazon Elastic Container Registry |
| Storage | EBS + VolumeSnapshots | Project persistence via snapshots |
| AWS User | <AWS_IAM_USER> | Deployment credentials |

## Prerequisites

### Required Software

| Software | Version | Purpose |
|----------|---------|---------|
| AWS CLI | v2+ | AWS management |
| kubectl | Latest | Kubernetes CLI |
| Docker | Latest | Container builds |

### AWS Credentials

Configure AWS CLI with the `<AWS_IAM_USER>` user credentials:

```powershell
aws configure
# AWS Access Key ID: <your-access-key>
# AWS Secret Access Key: <your-secret-key>
# Default region name: us-east-1
# Default output format: json
```

## Initial Setup

### 1. Configure kubectl for EKS

```powershell
# Update kubeconfig for EKS cluster
aws eks update-kubeconfig --region us-east-1 --name <EKS_CLUSTER_NAME>

# Verify connection
kubectl get nodes
kubectl get pods -n tesslate
```

### 2. Login to ECR

```powershell
# Get ECR login token and authenticate Docker
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com
```

Replace `<AWS_ACCOUNT_ID>` with your actual AWS account ID.

## Quick Deploy (Single Image)

Use this workflow when you have changed only one component.

### Deploy Frontend Changes

```powershell
# 1. Login to ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com

# 2. Build, tag, and push
docker build --no-cache -t tesslate-frontend:latest -f app/Dockerfile.prod app/
docker tag tesslate-frontend:latest <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-frontend:latest
docker push <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-frontend:latest

# 3. Delete pod to force pull new image
kubectl delete pod -n tesslate -l app=tesslate-frontend

# 4. Verify new pod is running
kubectl get pods -n tesslate
```

### Deploy Backend Changes

```powershell
# 1. Login to ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com

# 2. Build, tag, and push
docker build --no-cache -t tesslate-backend:latest -f orchestrator/Dockerfile orchestrator/
docker tag tesslate-backend:latest <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend:latest
docker push <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend:latest

# 3. Delete pod to force pull new image
kubectl delete pod -n tesslate -l app=tesslate-backend

# 4. Restart ingress controller to refresh endpoint routing
kubectl rollout restart deployment/ingress-nginx-controller -n ingress-nginx
kubectl rollout status deployment/ingress-nginx-controller -n ingress-nginx --timeout=120s

# 5. Verify new pod is running
kubectl get pods -n tesslate
```

### Deploy Devserver Changes

```powershell
# Build, tag, and push devserver (user project containers)
docker build --no-cache -t tesslate-devserver:latest -f orchestrator/Dockerfile.devserver orchestrator/
docker tag tesslate-devserver:latest <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-devserver:latest
docker push <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-devserver:latest
```

## Full Build and Push (All Images)

Use this workflow for major releases or when multiple components have changed.

```powershell
# Login to ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com

# Build, tag, and push backend
docker build --no-cache -t tesslate-backend:latest -f orchestrator/Dockerfile orchestrator/
docker tag tesslate-backend:latest <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend:latest
docker push <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend:latest

# Build, tag, and push frontend
docker build --no-cache -t tesslate-frontend:latest -f app/Dockerfile.prod app/
docker tag tesslate-frontend:latest <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-frontend:latest
docker push <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-frontend:latest

# Build, tag, and push devserver
docker build --no-cache -t tesslate-devserver:latest -f orchestrator/Dockerfile.devserver orchestrator/
docker tag tesslate-devserver:latest <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-devserver:latest
docker push <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-devserver:latest

# Delete all pods to pull new images
kubectl delete pod -n tesslate -l app=tesslate-frontend
kubectl delete pod -n tesslate -l app=tesslate-backend

# Restart ingress controller
kubectl rollout restart deployment/ingress-nginx-controller -n ingress-nginx
```

## Applying Manifests

```powershell
# Apply all manifests for AWS
kubectl apply -k k8s/overlays/aws

# Wait for deployments to be ready
kubectl rollout status deployment/tesslate-backend -n tesslate --timeout=120s
kubectl rollout status deployment/tesslate-frontend -n tesslate --timeout=120s
```

## Verifying Deployment

### Check Pod Status

```powershell
# Check all pods
kubectl get pods -n tesslate -o wide

# Check user project pods
kubectl get pods --all-namespaces | grep proj-
```

### Check Logs

```powershell
# Backend logs
kubectl logs -n tesslate deployment/tesslate-backend --tail=100
kubectl logs -n tesslate deployment/tesslate-backend -f  # Follow

# Frontend logs
kubectl logs -n tesslate deployment/tesslate-frontend --tail=100
```

### Check Ingress

```powershell
# Check tesslate ingress
kubectl get ingress -n tesslate

# Check all ingresses (including user projects)
kubectl get ingress --all-namespaces | grep proj-

# Check NGINX ingress controller logs
kubectl logs -n ingress-nginx deployment/ingress-nginx-controller --tail=50
```

### Execute Commands in Pod

```powershell
# Use MSYS_NO_PATHCONV=1 on Windows to prevent path translation
MSYS_NO_PATHCONV=1 kubectl exec -n tesslate deployment/tesslate-backend -- cat /app/app/config.py
MSYS_NO_PATHCONV=1 kubectl exec -n tesslate deployment/tesslate-backend -- python -c "print('hello')"

# Verify frontend assets
MSYS_NO_PATHCONV=1 kubectl exec -n tesslate deployment/tesslate-frontend -- ls -la /usr/share/nginx/html/assets/ | grep index
```

## SSL Certificates

### Check Certificate Status

```powershell
# List certificates
kubectl get certificate -n tesslate

# Check certificate details
kubectl describe certificate tesslate-wildcard-tls -n tesslate
```

### Troubleshoot Certificate Issues

```powershell
# Check cert-manager logs
kubectl logs -n cert-manager deployment/cert-manager --tail=50

# Check certificate status
kubectl describe certificate tesslate-wildcard-tls -n tesslate
```

For Cloudflare certificates, ensure the API token has:
- Zone:Zone:Read permission
- Zone:DNS:Edit permission

## Secrets Management

### View Secrets

```powershell
# View secrets (base64 encoded)
kubectl get secret tesslate-secrets -n tesslate -o yaml
```

### Update Secrets

```powershell
# Update a secret value
kubectl create secret generic tesslate-secrets -n tesslate \
  --from-literal=SECRET_KEY=xxx \
  --from-literal=DATABASE_URL=xxx \
  --dry-run=client -o yaml | kubectl apply -f -
```

## Cleanup Orphaned Namespaces

When projects are deleted, their namespaces should be cleaned up automatically. If orphaned namespaces remain:

```powershell
# List orphaned project namespaces
kubectl get ns | grep proj-

# Delete orphaned namespace (cascades to all resources)
kubectl delete ns proj-<project-uuid>
```

## AWS EKS Configuration

Key settings in `k8s/overlays/aws/backend-patch.yaml`:

| Setting | Value | Description |
|---------|-------|-------------|
| `K8S_DEVSERVER_IMAGE` | `<AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-devserver:latest` | ECR image for user containers |
| `K8S_IMAGE_PULL_SECRET` | `ecr-credentials` | Registry pull secret |
| `K8S_STORAGE_CLASS` | `tesslate-block-storage` | EBS storage class |
| `K8S_SNAPSHOT_CLASS` | `tesslate-ebs-snapshots` | VolumeSnapshotClass |
| `COOKIE_DOMAIN` | `.your-domain.com` | Cookie domain for auth |
| `replicas` | `1` | Single replica (tasks stored in-memory) |

## Common Issues and Fixes

### Container Start Fails with WebSocket Error

**Error**: `WebSocketBadStatusException: Handshake status 200 OK`

**Cause**: Bug in kubernetes Python client v34.x where REST calls get routed through WebSocket.

**Solution**: Pin kubernetes client to <32.0.0 in pyproject.toml, or wait for upstream fix.

### SSL Certificate Doesn't Cover Subdomains

**Error**: `ERR_CERT_AUTHORITY_INVALID for foo.bar.your-domain.com`

**Cause**: Wildcard certs (*.your-domain.com) only cover ONE level of subdomain.

**Solution**: Enable Cloudflare proxy (orange cloud) with SSL mode "Full", or change URL structure.

### Orphaned Namespaces Causing Slowness

**Cause**: When projects are deleted but K8s namespaces aren't cleaned up, NGINX Ingress Controller repeatedly tries to resolve them.

**Solution**: The `delete_project_namespace()` method handles cleanup on project deletion. Manually delete orphaned namespaces if needed.

### ECR Credentials Expired

**Error**: Authentication required when pushing to ECR.

**Solution**:
```powershell
# Re-login to ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com
```

### Site Not Loading After Backend Restart

**Cause**: NGINX Ingress Controller has stale backend endpoint cache.

**Solution**:
```powershell
# Restart ingress controller
kubectl rollout restart deployment/ingress-nginx-controller -n ingress-nginx
kubectl rollout status deployment/ingress-nginx-controller -n ingress-nginx --timeout=120s
```

## Resource Monitoring

```powershell
# Check pod resource usage
kubectl top pods -n tesslate

# Check node resource usage
kubectl top nodes
```

## Next Steps

- [Image Update Workflow](image-update-workflow.md) - Complete build and deploy workflow
- [Database Migrations](database-migrations.md) - Manage schema changes
- [Troubleshooting](troubleshooting.md) - More debugging tips
