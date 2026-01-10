# Infrastructure Agent Context

You are working on Tesslate Studio's infrastructure layer. This context provides essential information for debugging, modifying, and deploying infrastructure components.

## Your Role

When working on infrastructure:

1. **Understand the deployment mode** - Docker (local dev) vs Kubernetes (production)
2. **Check environment-specific configs** - Minikube vs AWS EKS have different settings
3. **Follow the S3 Sandwich pattern** - Kubernetes uses init containers for hydration
4. **Respect isolation boundaries** - Network policies and namespace per project
5. **Use proper image workflows** - Minikube needs `image load`, AWS uses ECR push

## Critical Files

### Kubernetes Manifests
- Base: `c:/Users/Smirk/Downloads/Tesslate-Studio/k8s/base/`
- Overlays: `c:/Users/Smirk/Downloads/Tesslate-Studio/k8s/overlays/{minikube,aws}/`
- Kustomization: `k8s/base/kustomization.yaml`, `k8s/overlays/*/kustomization.yaml`

### Docker Configuration
- Compose: `c:/Users/Smirk/Downloads/Tesslate-Studio/docker-compose.yml`
- Backend: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/Dockerfile`
- Frontend: `c:/Users/Smirk/Downloads/Tesslate-Studio/app/Dockerfile.prod`
- Devserver: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/Dockerfile.devserver`

### Terraform
- AWS EKS: `c:/Users/Smirk/Downloads/Tesslate-Studio/k8s/terraform/aws/eks.tf`
- ECR: `c:/Users/Smirk/Downloads/Tesslate-Studio/k8s/terraform/aws/ecr.tf`
- S3: `c:/Users/Smirk/Downloads/Tesslate-Studio/k8s/terraform/aws/s3.tf`

### Backend Configuration
- Config: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/config.py`
- K8s Orchestrator: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/orchestration/kubernetes_orchestrator.py`
- K8s Helpers: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/orchestration/kubernetes/helpers.py`

## Deployment Modes

### Docker Mode (Local Development)

**When**: Developer working on features on their laptop
**Where**: `DEPLOYMENT_MODE=docker` in `.env`

Key Characteristics:
- Traefik routes `*.localhost` to containers
- Projects at `./orchestrator/users/{user_id}/projects/{slug}/`
- Direct Docker CLI commands
- No S3 storage
- No namespace isolation

Common Tasks:
```bash
# Start services
docker-compose up -d

# View logs
docker-compose logs -f orchestrator

# Rebuild after code changes
docker-compose up -d --build orchestrator

# Access user project
curl http://frontend.my-app-k3x8n2.localhost
```

### Kubernetes Mode (Minikube Local Testing)

**When**: Testing Kubernetes deployment locally before production
**Where**: Minikube cluster on developer machine

Key Characteristics:
- Per-project namespaces: `proj-{uuid}`
- MinIO for S3 storage (in `minio-system` namespace)
- Local images loaded via `minikube image load`
- `imagePullPolicy: Never`
- Port-forward or tunnel for access

Common Tasks:
```bash
# Start cluster
minikube start -p tesslate --driver=docker --memory=4096 --cpus=2

# Build and load image (CRITICAL: Delete old image first!)
minikube -p tesslate ssh -- docker rmi -f tesslate-backend:latest
docker build --no-cache -t tesslate-backend:latest -f orchestrator/Dockerfile orchestrator/
minikube -p tesslate image load tesslate-backend:latest

# Force pod restart (rollout restart may use cached image)
kubectl delete pod -n tesslate -l app=tesslate-backend

# Deploy
kubectl apply -k k8s/overlays/minikube

# Access
minikube -p tesslate tunnel
# OR
kubectl port-forward -n tesslate svc/tesslate-frontend-service 5000:80
```

### Kubernetes Mode (AWS EKS Production)

**When**: Production deployment on AWS
**Where**: EKS cluster in us-east-1

Key Characteristics:
- Per-project namespaces: `proj-{uuid}`
- S3 bucket: `tesslate-projects-production-7761157a`
- ECR registry: `<AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com`
- `imagePullPolicy: Always`
- Domain: `your-domain.com`
- TLS via cert-manager + Cloudflare

Common Tasks:
```bash
# Configure kubectl
aws eks update-kubeconfig --region us-east-1 --name <EKS_CLUSTER_NAME>

# Login to ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com

# Build, tag, push (ALWAYS use --no-cache)
docker build --no-cache -t tesslate-backend:latest -f orchestrator/Dockerfile orchestrator/
docker tag tesslate-backend:latest <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend:latest
docker push <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend:latest

# Force pod restart (imagePullPolicy: Always pulls new image)
kubectl delete pod -n tesslate -l app=tesslate-backend

# Deploy manifests
kubectl apply -k k8s/overlays/aws

# Restart ingress after backend changes
kubectl rollout restart deployment/ingress-nginx-controller -n ingress-nginx
```

## S3 Sandwich Pattern (Kubernetes Only)

User projects in Kubernetes use ephemeral storage with S3 persistence:

### Lifecycle

1. **Hydration** (Init Container `hydrate-project`):
   ```
   - Check if project exists in S3
   - If exists: Download zip, extract to /workspace
   - If not: Copy template to /workspace
   - Exit (main container starts)
   ```

2. **Runtime** (Main Container `dev-server`):
   ```
   - User edits files on PVC (/workspace)
   - Fast local I/O
   - npm install, file operations work normally
   ```

3. **Dehydration** (PreStop Hook):
   ```
   - Triggered when pod terminates
   - Zip /workspace (exclude node_modules, .git, etc.)
   - Upload to S3
   - Exit (pod terminates)
   ```

4. **Cleanup** (CronJob every 2 minutes):
   ```
   - Find projects idle > K8S_HIBERNATION_IDLE_MINUTES
   - Delete namespace (cascades to PVC, pods)
   - Project stays in S3
   - Next access triggers re-hydration
   ```

### Key Environment Variables

- `S3_BUCKET_NAME`: Where projects are stored
- `S3_ENDPOINT_URL`: MinIO URL (local) or empty (AWS native)
- `K8S_HIBERNATION_IDLE_MINUTES`: Idle timeout (default: 30)
- `K8S_DEHYDRATION_EXCLUDE_PATTERNS`: Files to skip in zip

### Manifest Locations

Init container definition: `orchestrator/app/services/orchestration/kubernetes/helpers.py`
- Function: `_create_deployment_manifest()`
- Init container: `hydrate-project`
- PreStop hook in main container

## Network Policies

Kubernetes deployments use NetworkPolicies for security:

### Platform Namespace (`tesslate`)

**File**: `k8s/base/security/network-policies.yaml`

1. **default-deny-ingress**: Block all ingress by default
2. **allow-ingress-controller**: Allow from `ingress-nginx` namespace
3. **allow-backend-from-frontend**: Frontend → Backend (port 8000)
4. **allow-postgres-from-backend**: Backend → Postgres (port 5432)
5. **allow-dns-egress**: All pods → kube-dns
6. **allow-backend-egress**: Backend → all namespaces + external (for K8s API, S3, LiteLLM)

### User Project Namespaces (`proj-{uuid}`)

**Created by**: `kubernetes_orchestrator.py` when project starts

1. **default-deny-ingress**: Block all ingress
2. **allow-ingress-to-{container}**: Allow from `ingress-nginx` to specific container port
3. **allow-dns-egress**: Allow DNS resolution
4. **allow-external-egress**: Allow npm install, pip install, API calls

## RBAC

### ServiceAccount: `tesslate-backend-sa`

**File**: `k8s/base/security/rbac.yaml`

The backend needs cluster-wide permissions to manage user project namespaces.

**ClusterRole** `tesslate-dev-environments-manager`:
- **Namespaces**: create, delete, get, list, watch, patch, update
- **Core resources**: pods, services, PVCs, secrets, configmaps
- **Apps**: deployments, replicasets, statefulsets
- **Networking**: ingresses, networkpolicies
- **Batch**: jobs, cronjobs
- **Events**: get, list, watch (for troubleshooting)

**ClusterRoleBinding** `tesslate-backend-cluster-access`:
- Binds `tesslate-backend-sa` to `tesslate-dev-environments-manager`

**Why ClusterRole?**: Backend must create/delete namespaces and resources in `proj-*` namespaces, which requires cluster-wide permissions.

## Image Registry

### Minikube

**Images**: Built locally, loaded into Minikube's Docker daemon
```bash
tesslate-backend:latest
tesslate-frontend:latest
tesslate-devserver:latest
```

**Pull Policy**: `Never` (critical - must use local image)

**Workflow**:
1. Delete old image from Minikube: `minikube -p tesslate ssh -- docker rmi -f {image}:latest`
2. Delete local image: `docker rmi -f {image}:latest`
3. Build: `docker build --no-cache -t {image}:latest -f {dockerfile} {context}`
4. Load: `minikube -p tesslate image load {image}:latest`
5. Force pod restart: `kubectl delete pod -n tesslate -l app={image}`

**Why delete first?**: `minikube image load` does NOT overwrite existing images with same tag.

### AWS EKS

**Registry**: ECR in us-east-1
```
<AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend:latest
<AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-frontend:latest
<AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-devserver:latest
```

**Pull Policy**: `Always` (always check for new image)

**Workflow**:
1. Login: `aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin {registry}`
2. Build: `docker build --no-cache -t {image}:latest -f {dockerfile} {context}`
3. Tag: `docker tag {image}:latest {registry}/{image}:latest`
4. Push: `docker push {registry}/{image}:latest`
5. Force pod restart: `kubectl delete pod -n tesslate -l app={image}`

**Why delete pod?**: Forces Kubernetes to pull new image (even with same :latest tag).

## Storage Classes

### Minikube

**Name**: `minikube-hostpath` (default)
**Type**: hostPath on Minikube node
**Access Mode**: ReadWriteOnce
**Reclaim**: Delete

User PVCs automatically use default storage class.

### AWS EKS

**Name**: `tesslate-block-storage`
**Type**: EBS gp3
**Access Mode**: ReadWriteOnce
**Size**: 5Gi (per project)
**Encryption**: Enabled
**Reclaim**: Delete

**Defined in**: `k8s/terraform/aws/eks.tf` (resource `kubernetes_storage_class.gp3`)

**CSI Driver**: `ebs.csi.aws.com` (installed as EKS addon)

## Ingress

### Minikube

**Controller**: NGINX Ingress (Minikube addon)
**Domain**: None (path-based routing)
**TLS**: Disabled

**Enable addon**:
```bash
minikube -p tesslate addons enable ingress
```

**Access**:
- Tunnel: `minikube -p tesslate tunnel` (requires admin privileges)
- Port-forward: `kubectl port-forward -n tesslate svc/tesslate-frontend-service 5000:80`

### AWS EKS

**Controller**: NGINX Ingress (installed via Helm)
**Domain**: `your-domain.com`
**TLS**: Enabled via cert-manager + Cloudflare

**Wildcard Certificate**: `tesslate-wildcard-tls` (managed by cert-manager)
- Covers: `*.your-domain.com`, `*.*.your-domain.com` (two-level wildcard via Cloudflare proxy)

**Platform Routes**:
```
https://your-domain.com/      → tesslate-frontend-service:80
https://your-domain.com/api/* → tesslate-backend-service:8000
```

**User Project Routes** (created dynamically):
```
https://{container}.{slug}.your-domain.com → {container}-service:3000
```

**CRITICAL**: After backend restarts, NGINX cache may be stale:
```bash
kubectl rollout restart deployment/ingress-nginx-controller -n ingress-nginx
```

## Debugging

### Minikube Image Issues

**Problem**: Code changes not reflected in pods

**Diagnosis**:
```bash
# Check what images are in Minikube
minikube -p tesslate ssh -- docker images | grep tesslate

# Check pod image
kubectl describe pod -n tesslate {pod-name} | grep Image
```

**Solution**: Always delete old image before loading new one (see Image Registry section)

### AWS EKS User Container ImagePullBackOff

**Problem**: User project pods stuck in ImagePullBackOff

**Diagnosis**:
```bash
# Check pod events
kubectl describe pod -n proj-{uuid} {pod-name}

# Check backend env
kubectl exec -n tesslate deployment/tesslate-backend -- env | grep K8S_DEVSERVER_IMAGE
```

**Solution**: Verify `K8S_DEVSERVER_IMAGE` is set correctly in `k8s/overlays/aws/backend-patch.yaml`

### S3 Hydration Failures

**Problem**: User project pod crashes during startup

**Diagnosis**:
```bash
# Check init container logs
kubectl logs -n proj-{uuid} {pod-name} -c hydrate-project

# Check S3 credentials
kubectl get secret -n tesslate s3-credentials -o yaml
```

**Common Issues**:
- MinIO not running (Minikube): Check `kubectl get pods -n minio-system`
- Invalid S3 credentials: Check secret values
- Network policy blocking egress: Check `allow-external-egress` policy

### User Project 503 Errors

**Problem**: User accesses project URL, gets 503

**Diagnosis**:
```bash
# Check pod status
kubectl get pods -n proj-{uuid}

# Check dev server logs
kubectl logs -n proj-{uuid} {pod-name} -c dev-server

# Check ingress
kubectl get ingress -n proj-{uuid}
kubectl describe ingress -n proj-{uuid} {ingress-name}

# Check NGINX logs
kubectl logs -n ingress-nginx deployment/ingress-nginx-controller --tail=50
```

**Common Issues**:
- Pod not ready: Check readiness probe
- Service selector mismatch: Verify labels
- Ingress annotation issue: Check `proxy-hide-headers` annotation (not `configuration-snippet`)
- NGINX stale cache: Restart ingress controller

## Common Modifications

### Adding Environment Variable to Backend

1. **Add to base deployment**: `k8s/base/core/backend-deployment.yaml`
2. **Override in overlays** (if environment-specific): `k8s/overlays/{minikube,aws}/backend-patch.yaml`
3. **Add to config.py**: `orchestrator/app/config.py`
4. **Redeploy**: `kubectl apply -k k8s/overlays/{env}` and restart pods

### Changing User Container Resources

Edit: `orchestrator/app/services/orchestration/kubernetes/helpers.py`
Function: `_create_deployment_manifest()`
Section: `resources` in container spec

Default:
```python
resources={
    "requests": {"memory": "256Mi", "cpu": "100m"},
    "limits": {"memory": "1Gi", "cpu": "1000m"}
}
```

### Adding New Storage Class

1. **Create Terraform resource**: `k8s/terraform/aws/eks.tf`
2. **Reference in overlay**: `k8s/overlays/aws/storage-class.yaml` (if not in Terraform)
3. **Update backend env**: `K8S_STORAGE_CLASS={new-name}` in patch
4. **Redeploy**: `kubectl apply -k k8s/overlays/aws`

### Modifying S3 Lifecycle

Edit: `k8s/terraform/aws/s3.tf`
Resource: `aws_s3_bucket_lifecycle_configuration.tesslate_projects`

Example: Expire inactive projects after 180 days (uncomment rule)

## Quick Reference

### Namespaces
- `tesslate`: Platform services
- `ingress-nginx`: Ingress controller
- `minio-system`: MinIO (Minikube only)
- `proj-{uuid}`: User projects

### Service Accounts
- `tesslate-backend-sa`: Backend with cluster-wide permissions

### Secrets
- `tesslate-app-secrets`: API keys, OAuth, domain config
- `postgres-secret`: Database credentials
- `s3-credentials`: S3/MinIO credentials

### ConfigMaps
- `tesslate-config`: Deployment mode, K8s settings

### PersistentVolumeClaims
- `postgres-pvc`: Database data (10Gi)
- `{project-slug}-pvc`: User project data (5Gi ephemeral)

### CronJobs
- `dev-environment-cleanup`: Runs every 2 minutes, hibernates idle projects

## Best Practices

1. **Always use --no-cache for builds**: Ensures code changes are included
2. **Delete old images before loading new (Minikube)**: `image load` doesn't overwrite
3. **Delete pods after image push**: Forces pull of new image (even with :latest)
4. **Restart NGINX after backend changes**: Clears endpoint cache
5. **Use overlay patches**: Don't modify base manifests directly
6. **Test in Minikube before AWS**: Catches K8s-specific issues early
7. **Monitor S3 costs**: Large node_modules can inflate storage costs (use exclude patterns)
8. **Check namespace quotas**: Resource quotas prevent runaway project creation

## Emergency Procedures

### Stuck Namespace Deletion

```bash
# Remove finalizers
kubectl patch ns proj-{uuid} -p '{"metadata":{"finalizers":[]}}' --type=merge
```

### Out of Disk Space (Minikube)

```bash
# Clean unused Docker images
minikube -p tesslate ssh -- docker system prune -a -f

# Delete completed pods
kubectl delete pods --all-namespaces --field-selector=status.phase==Succeeded

# Delete orphaned PVCs
kubectl delete pvc --all-namespaces --field-selector=status.phase==Lost
```

### Backend Crash Loop

```bash
# Check logs
kubectl logs -n tesslate deployment/tesslate-backend --tail=100

# Check database connection
kubectl exec -n tesslate deployment/tesslate-backend -- nc -zv postgres 5432

# Check secrets
kubectl get secret -n tesslate tesslate-app-secrets -o yaml
```

### Certificate Issues (AWS)

```bash
# Check cert-manager
kubectl get certificate -n tesslate
kubectl describe certificate tesslate-wildcard-tls -n tesslate

# Check cert-manager logs
kubectl logs -n cert-manager deployment/cert-manager --tail=50

# Force renewal
kubectl delete certificate tesslate-wildcard-tls -n tesslate
kubectl apply -k k8s/overlays/aws
```
