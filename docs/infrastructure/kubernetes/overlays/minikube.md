# Minikube Overlay Configuration

Configuration for local Kubernetes development using Minikube.

**Location**: `c:/Users/Smirk/Downloads/Tesslate-Studio/k8s/overlays/minikube/`

## Overview

The Minikube overlay configures OpenSail for local testing with:
- Local Docker images (no registry)
- MinIO for S3 storage
- Reduced resource limits
- No TLS/domain configuration

## Key Configuration

### Images

**Image Pull Policy**: `Never`
- CRITICAL: Minikube must use locally loaded images
- Without `Never`, Kubernetes tries to pull from Docker Hub (fails)

**Image Names**:
```yaml
images:
  - name: tesslate-backend
    newName: tesslate-backend
    newTag: latest
  - name: tesslate-frontend
    newName: tesslate-frontend
    newTag: latest
  - name: tesslate-devserver
    newName: tesslate-devserver
    newTag: latest
```

**Loading Images**:
```bash
# Delete old image first (CRITICAL - minikube image load doesn't overwrite)
minikube -p tesslate ssh -- docker rmi -f tesslate-backend:latest

# Build
docker build --no-cache -t tesslate-backend:latest -f orchestrator/Dockerfile orchestrator/

# Load into Minikube
minikube -p tesslate image load tesslate-backend:latest

# Force pod restart
kubectl delete pod -n tesslate -l app=tesslate-backend
```

### Storage

**Storage Class**: `minikube-hostpath` (Minikube default)
- Type: hostPath (directory on Minikube node)
- Access mode: ReadWriteOnce
- No explicit StorageClass resource needed (uses default)

**PVC Settings**:
- Size: 5Gi (per project)
- Reclaim policy: Delete

**btrfs-CSI Driver** (VolumeSnapshot support):
- The btrfs-CSI driver provides VolumeSnapshot capability on Minikube
- Deployed via `kubectl apply -k services/btrfs-csi/overlays/minikube`
- Runs in `kube-system` namespace as two components:
  - `tesslate-btrfs-csi-node` (DaemonSet) - CSI node driver for btrfs-based snapshots
  - `tesslate-volume-hub` (Deployment) - Volume lifecycle and placement management
- VolumeSnapshot CRDs from kubernetes-csi/external-snapshotter v8.2.0 must be installed
- Enables Timeline UI and hibernation snapshots that were previously AWS-only

### S3 Storage (MinIO)

**Namespace**: `minio-system` (separate from `tesslate`)

**Deployment**:
```bash
kubectl apply -k k8s/base/minio
```

**Service**:
- API: `minio.minio-system.svc.cluster.local:9000`
- Console: Port 9001 (port-forward for web UI)

**Credentials** (from `secrets/minio-credentials.yaml`):
```yaml
S3_ACCESS_KEY_ID: minioadmin
S3_SECRET_ACCESS_KEY: minioadmin
S3_BUCKET_NAME: tesslate-projects
S3_ENDPOINT_URL: http://minio.minio-system.svc.cluster.local:9000
S3_REGION: us-east-1
```

**Init Job**: Creates `tesslate-projects` bucket on startup

**Access Console**:
```bash
kubectl port-forward -n minio-system svc/minio 9001:9001
# Open http://localhost:9001
```

### Backend Configuration

**Patch File**: `backend-patch.yaml`

**Key Settings**:
```yaml
env:
  - name: K8S_DEVSERVER_IMAGE
    value: "tesslate-devserver:latest"  # No registry
  - name: K8S_IMAGE_PULL_SECRET
    value: ""  # No secret needed
  - name: K8S_IMAGE_PULL_POLICY
    value: "Never"  # Use local image
```

**Resources**:
```yaml
resources:
  requests:
    memory: "256Mi"
    cpu: "100m"
  limits:
    memory: "512Mi"
    cpu: "500m"
```

### Frontend Configuration

**Patch File**: `frontend-patch.yaml`

**Image Pull Policy**: `Never`

**Service**: NodePort (port 30080) - optional, use port-forward instead

### Ingress Configuration

**Patch File**: `ingress-patch.yaml`

**No Host**: Path-based routing only (no domain)
```yaml
spec:
  rules:
  - http:  # No host specified
      paths:
      - path: /api
        pathType: Prefix
        backend:
          service:
            name: tesslate-backend-service
            port: 8000
      - path: /
        pathType: Prefix
        backend:
          service:
            name: tesslate-frontend-service
            port: 80
```

**TLS**: Disabled

**Access**:
```bash
# Option 1: Tunnel (requires admin privileges)
minikube -p tesslate tunnel
# Access: http://localhost

# Option 2: Port-forward (recommended)
kubectl port-forward -n tesslate svc/tesslate-frontend-service 5000:80
kubectl port-forward -n tesslate svc/tesslate-backend-service 8000:8000
# Access: http://localhost:5000
```

## Secrets Management

### Generation Script

**Location**: `k8s/scripts/generate-secrets.sh`

**Usage**:
```bash
# 1. Create .env.minikube from template
cp k8s/overlays/minikube/.env.example k8s/overlays/minikube/.env.minikube

# 2. Edit .env.minikube with actual values
nano k8s/overlays/minikube/.env.minikube

# 3. Generate secret YAML files
k8s/scripts/generate-secrets.sh minikube
```

**Generated Files** (gitignored):
- `secrets/postgres-secret.yaml`
- `secrets/s3-credentials.yaml`
- `secrets/app-secrets.yaml`

### Required Secrets

**postgres-secret**:
```
POSTGRES_DB=tesslate_dev
POSTGRES_USER=tesslate_user
POSTGRES_PASSWORD=dev_password_change_me
```

**s3-credentials**:
```
S3_ACCESS_KEY_ID=minioadmin
S3_SECRET_ACCESS_KEY=minioadmin
S3_BUCKET_NAME=tesslate-projects
S3_ENDPOINT_URL=http://minio.minio-system.svc.cluster.local:9000
S3_REGION=us-east-1
```

**app-secrets** (essential keys):
```
SECRET_KEY=your-secret-key
DATABASE_URL=postgresql+asyncpg://tesslate_user:dev_password_change_me@postgres:5432/tesslate_dev
LITELLM_API_BASE=https://your-litellm-instance.com
LITELLM_MASTER_KEY=your-litellm-key
LITELLM_DEFAULT_MODELS=claude-sonnet-4.6,claude-opus-4.6
CORS_ORIGINS=http://localhost:5000,http://localhost
ALLOWED_HOSTS=localhost
APP_DOMAIN=localhost
APP_BASE_URL=http://localhost:5000
DEV_SERVER_BASE_URL=http://localhost
```

## Complete Setup Procedure

### 1. Start Minikube

```bash
minikube start -p tesslate --driver=docker --memory=8192 --cpus=4
minikube -p tesslate addons enable ingress
```

### 2. Build and Load Images

```bash
# Backend
docker build --no-cache -t tesslate-backend:latest -f orchestrator/Dockerfile orchestrator/
minikube -p tesslate image load tesslate-backend:latest

# Frontend
docker build --no-cache -t tesslate-frontend:latest -f app/Dockerfile.prod app/
minikube -p tesslate image load tesslate-frontend:latest

# Devserver
docker build --no-cache -t tesslate-devserver:latest -f orchestrator/Dockerfile.devserver orchestrator/
minikube -p tesslate image load tesslate-devserver:latest
```

### 3. Create Secrets

```bash
cp k8s/overlays/minikube/.env.example k8s/overlays/minikube/.env.minikube
# Edit .env.minikube
k8s/scripts/generate-secrets.sh minikube
```

### 4. Deploy MinIO

```bash
kubectl apply -k k8s/base/minio
kubectl wait --for=condition=ready pod -l app=minio -n minio-system --timeout=120s
```

### 5. Deploy Platform

```bash
kubectl apply -k k8s/overlays/minikube
kubectl wait --for=condition=ready pod -l app=tesslate-backend -n tesslate --timeout=300s
```

### 6. Access Platform

```bash
# Terminal 1: Port-forward frontend
kubectl port-forward -n tesslate svc/tesslate-frontend-service 5000:80

# Terminal 2: Port-forward backend (if direct API access needed)
kubectl port-forward -n tesslate svc/tesslate-backend-service 8000:8000

# Open browser
http://localhost:5000
```

## Troubleshooting

### Image not found

**Symptom**: `ImagePullBackOff` or `ErrImagePull`

**Check**:
```bash
minikube -p tesslate ssh -- docker images | grep tesslate
kubectl describe pod -n tesslate {pod-name} | grep Image
```

**Fix**:
```bash
# Load image
minikube -p tesslate image load tesslate-backend:latest

# Verify
minikube -p tesslate ssh -- docker images | grep tesslate-backend
```

### Old code running after rebuild

**Symptom**: Changes not reflected in pods

**Cause**: `minikube image load` doesn't overwrite existing images

**Fix**:
```bash
# Delete old image from Minikube
minikube -p tesslate ssh -- docker rmi -f tesslate-backend:latest

# Delete local image (optional but recommended)
docker rmi -f tesslate-backend:latest

# Rebuild with --no-cache
docker build --no-cache -t tesslate-backend:latest -f orchestrator/Dockerfile orchestrator/

# Load fresh image
minikube -p tesslate image load tesslate-backend:latest

# Force pod restart
kubectl delete pod -n tesslate -l app=tesslate-backend
```

### MinIO not accessible

**Symptom**: Backend logs show S3 connection errors

**Check**:
```bash
kubectl get pods -n minio-system
kubectl logs -n minio-system deployment/minio
```

**Fix**:
```bash
# Redeploy MinIO
kubectl delete ns minio-system
kubectl apply -k k8s/base/minio
```

### User project container not starting

**Symptom**: `proj-*` namespace pods in ImagePullBackOff

**Check**:
```bash
kubectl get pods -n proj-{uuid}
kubectl describe pod -n proj-{uuid} {pod-name} | grep Image
```

**Fix**: Verify devserver image is loaded
```bash
minikube -p tesslate ssh -- docker images | grep tesslate-devserver
# If not found:
minikube -p tesslate image load tesslate-devserver:latest
```

### Port-forward fails

**Symptom**: `unable to forward port` or connection refused

**Check**:
```bash
kubectl get pods -n tesslate
kubectl get svc -n tesslate
```

**Fix**: Ensure pod is running and service exists
```bash
kubectl port-forward -n tesslate deployment/tesslate-frontend 5000:80
```

## Resource Monitoring

### Check Resource Usage

```bash
# Node resources
kubectl top nodes

# Pod resources
kubectl top pods -n tesslate
kubectl top pods --all-namespaces

# Describe node
kubectl describe node minikube
```

### Adjust Minikube Resources

```bash
# Stop cluster
minikube stop -p tesslate

# Increase resources
minikube start -p tesslate --memory=8192 --cpus=4

# Redeploy
kubectl apply -k k8s/overlays/minikube
```

## Best Practices

1. **Always use --no-cache**: Ensures code changes are included in image
2. **Delete before load**: `minikube image load` doesn't overwrite
3. **Use port-forward, not tunnel**: Tunnel requires admin privileges
4. **Monitor resources**: Minikube has limited CPU/RAM, don't over-allocate
5. **Clean up regularly**: Delete unused namespaces, prune Docker images
6. **Test S3 operations**: Verify MinIO is working before testing hibernation

## Cleanup

### Delete Platform

```bash
kubectl delete -k k8s/overlays/minikube
```

### Delete MinIO

```bash
kubectl delete ns minio-system
```

### Delete Minikube Cluster

```bash
minikube delete -p tesslate
```

### Remove Images

```bash
# From Minikube
minikube -p tesslate ssh -- docker system prune -a -f

# From local Docker
docker rmi tesslate-backend:latest tesslate-frontend:latest tesslate-devserver:latest
```

## Complete file inventory

Every manifest in `k8s/overlays/minikube/`:

| File | Purpose |
|------|---------|
| `kustomization.yaml` | Root overlay manifest. |
| `apply.sh` | Prerequisites check + secret generation + kubectl apply wrapper. |
| `backend-patch.yaml` | Backend env patch (local secrets, storage class, snapshot class). |
| `frontend-patch.yaml` | Frontend image + `imagePullPolicy: Never`. |
| `frontend-config.yaml` | Frontend runtime ConfigMap (`api-url`). |
| `frontend-service-patch.yaml` | Service type patch for tunnel / port-forward. |
| `ingress-patch.yaml`, `ingress.yaml` | Host patched to `localhost`; TLS disabled. |
| `namespace-reaper-cronjob-patch.yaml` | Minikube schedule + env for the reaper cron. |
| `snapshot-cleanup-cronjob-patch.yaml` | Minikube-friendly snapshot cleanup cron. |
| `storage-class.yaml` | `tesslate-btrfs` StorageClass. |
| `secrets/app-secrets.yaml` + `.example.yaml` | Backend secrets template. |
| `secrets/postgres-secret.yaml` + `.example.yaml` | Postgres credentials template. |
| `secrets/minio-credentials.yaml` + `.example.yaml` | MinIO admin credentials template. |
| `secrets/s3-credentials.yaml` + `.example.yaml` | Backend S3 credentials template. |
| `minio/minio-namespace.yaml` | `Namespace minio-system`. |
| `minio/minio-deployment.yaml` | MinIO server. |
| `minio/minio-service.yaml` | ClusterIP. |
| `minio/minio-pvc.yaml` | 10Gi PVC. |
| `minio/minio-init-job.yaml` | Creates `tesslate-projects` bucket. |
| `minio/credentials.yaml` + `.example.yaml` | Admin creds. |
| `minio/minio-secret.yaml.template` | Legacy template kept for historical reference. |
| `snapshot-crds/setup-snapshot-controller.yaml` | External-snapshotter controller Deployment. |
| `snapshot-crds/rbac-snapshot-controller.yaml` | Controller RBAC. |
| `snapshot-crds/volumesnapshotclasses.yaml` | `VolumeSnapshotClass` CRD. |
| `snapshot-crds/volumesnapshotcontents.yaml` | `VolumeSnapshotContent` CRD. |
| `snapshot-crds/volumesnapshots.yaml` | `VolumeSnapshot` CRD. |
| `cloudflare-tunnel/cloudflare-tunnel-namespace.yaml` | `Namespace cloudflare-tunnel`. |
| `cloudflare-tunnel/cloudflare-tunnel-deployment.yaml` | `cloudflared` Deployment. |
| `cloudflare-tunnel/credentials.example.yaml` | Tunnel credentials template. |
