# Kubernetes Infrastructure

This directory documents OpenSail's Kubernetes deployment configuration using Kustomize.

## Overview

OpenSail uses **Kustomize** for Kubernetes manifest management, with a base configuration that is customized per environment using overlays.

**Location**: `c:/Users/Smirk/Downloads/Tesslate-Studio/k8s/`

```
k8s/
├── base/                    # Base manifests (shared)
│   ├── kustomization.yaml
│   ├── namespace/           # tesslate namespace
│   ├── core/                # Backend, frontend, worker, cleanup cronjob
│   ├── database/            # PostgreSQL
│   ├── ingress/             # Main ingress
│   ├── security/            # RBAC, network policies, quotas
│   ├── redis/               # Redis deployment
│   └── minio/               # MinIO (for local S3)
└── overlays/                # Environment-specific patches
    ├── minikube/            # Local development
    │   ├── kustomization.yaml
    │   ├── backend-patch.yaml
    │   ├── frontend-patch.yaml
    │   ├── ingress-patch.yaml
    │   ├── storage-class.yaml
    │   └── secrets/         # Local secrets (gitignored)
    ├── aws-base/            # Shared AWS configuration
    │   ├── backend-patch.yaml
    │   ├── worker-patch.yaml
    │   └── ...
    ├── aws-beta/            # Beta environment
    └── aws-production/      # Production environment
```

## Deployment Strategy

### Base Layer

Contains environment-agnostic manifests:
- Core application components (backend, frontend, database)
- Security policies (RBAC, network policies)
- Resource quotas
- Base ingress configuration

### Overlay Layer

Patches base manifests with environment-specific values:
- **Minikube**: Local images, MinIO for S3, no TLS
- **AWS**: ECR images, native S3, TLS with cert-manager

## Key Concepts

### Namespace Strategy

**Platform Namespace** (`tesslate`):
- Backend deployment
- Frontend deployment
- PostgreSQL database
- Cleanup cronjob
- Shared secrets and configmaps

**User Project Namespaces** (`proj-{uuid}`):
- One namespace per project
- Isolated networking via NetworkPolicy
- Ephemeral storage (PVC deleted on hibernation)
- Dynamically created by backend

### Resource Types

**Deployments** (all with `revisionHistoryLimit: 3`):
- `tesslate-backend`: Orchestrator API
- `tesslate-frontend`: React UI
- `tesslate-worker`: ARQ worker for agent tasks
- `postgres`: Database
- `redis`: Redis server

**Services**:
- `tesslate-backend-service`: ClusterIP (port 8000)
- `tesslate-frontend-service`: ClusterIP (port 80)
- `postgres`: ClusterIP (port 5432)
- `redis`: ClusterIP (port 6379)

**Ingress**:
- `tesslate-ingress`: Routes platform traffic
- User project ingresses: Created dynamically per project

**CronJobs**:
- `dev-environment-cleanup`: Hibernates idle projects every 2 minutes

**RBAC**:
- `tesslate-backend-sa`: ServiceAccount for backend
- `tesslate-dev-environments-manager`: ClusterRole for namespace management
- `tesslate-backend-cluster-access`: ClusterRoleBinding

**NetworkPolicies**:
- Default deny ingress
- Explicit allow rules for platform components
- DNS egress for all pods
- External egress for backend

### Kustomize Workflow

**Build without applying** (dry run):
```bash
kubectl kustomize k8s/overlays/minikube
```

**Apply directly**:
```bash
kubectl apply -k k8s/overlays/minikube
```

**Diff before applying**:
```bash
kubectl diff -k k8s/overlays/minikube
```

## Environment Configurations

### Minikube (Local Development)

**Purpose**: Test Kubernetes deployment locally

**Key Settings**:
- Image pull policy: `Never` (use local images)
- Storage class: `minikube-hostpath`
- S3: MinIO in `minio-system` namespace
- Domain: None (use port-forward or tunnel)
- TLS: Disabled

**Deploy**:
```bash
kubectl apply -k k8s/overlays/minikube
```

**Access**:
```bash
# Option 1: Tunnel (requires admin)
minikube -p tesslate tunnel

# Option 2: Port-forward
kubectl port-forward -n tesslate svc/tesslate-frontend-service 5000:80
kubectl port-forward -n tesslate svc/tesslate-backend-service 8000:8000
```

### AWS EKS (Production)

**Purpose**: Production deployment

**Key Settings**:
- Image pull policy: `Always` (check for updates)
- Storage class: `tesslate-block-storage` (EBS gp3)
- S3: Native AWS S3 via IRSA
- Domain: `your-domain.com` (beta), `opensail.tesslate.com` (production)
- TLS: Enabled via cert-manager

**Overlays**: Split into shared base + environment-specific patches:
- `k8s/overlays/aws-base/` - Shared AWS configuration (backend-patch, worker-patch)
- `k8s/overlays/aws-beta/` - Beta environment patches (replicas, resources, rollout strategy)
- `k8s/overlays/aws-production/` - Production environment patches

**Deploy**:
```bash
# Recommended: use aws-deploy.sh
./scripts/aws-deploy.sh deploy-k8s beta
./scripts/aws-deploy.sh deploy-k8s production
```

**Access**:
```
https://your-domain.com          (beta)
https://opensail.tesslate.com   (production)
```

## Resource Limits

### Backend Pod

**Minikube**:
- Requests: 256Mi RAM, 100m CPU
- Limits: 512Mi RAM, 500m CPU

**AWS**:
- Requests: 512Mi RAM, 250m CPU
- Limits: 2Gi RAM, 2000m CPU

### Frontend Pod

**Both**:
- Requests: 128Mi RAM, 50m CPU
- Limits: 256Mi RAM, 200m CPU

### User Project Pods

**Default** (configurable in `kubernetes/helpers.py`):
- Requests: 256Mi RAM, 100m CPU
- Limits: 1Gi RAM, 1000m CPU

## Storage Configuration

### Platform Storage

**PostgreSQL PVC**:
- Name: `postgres-pvc`
- Size: 10Gi
- Access mode: ReadWriteOnce
- Reclaim policy: Retain

### User Project Storage

**Ephemeral PVC per project**:
- Name: `{project-slug}-pvc`
- Size: 5Gi (configurable via `K8S_PVC_SIZE`)
- Access mode: ReadWriteOnce
- Reclaim policy: Delete (cleaned up on hibernation)

**S3 Backing**:
- Projects persisted to S3 before PVC deletion
- Restored from S3 on next access

## Networking

### Service Mesh

No service mesh currently. Direct ClusterIP services with NGINX Ingress.

### Network Policies

See [network-policies.md](network-policies.md) for detailed configuration.

**Summary**:
- Default deny all ingress in all namespaces
- Explicit allow from NGINX Ingress
- Backend can reach all namespaces (for project management)
- DNS egress allowed for all
- External egress for backend and user projects

### Ingress Configuration

**Platform Ingress** (`tesslate-ingress`):
```yaml
spec:
  rules:
  - host: your-domain.com  # Patched by overlay
    http:
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

**User Project Ingress** (created dynamically):
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {project-slug}-ingress
  namespace: proj-{uuid}
  annotations:
    nginx.ingress.kubernetes.io/proxy-hide-headers: X-Frame-Options
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - "*.{project-slug}.your-domain.com"
    secretName: tesslate-wildcard-tls
  rules:
  - host: "{container}.{project-slug}.your-domain.com"
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: {container}-service
            port: 3000
```

## Security

### RBAC

See [rbac.md](rbac.md) for detailed configuration.

**ServiceAccount**: `tesslate-backend-sa`
- Used by: Backend deployment, cleanup cronjob
- Permissions: Cluster-wide namespace and resource management

### Network Policies

See [network-policies.md](network-policies.md).

**Isolation**: Each user project namespace has default deny ingress.

### Secrets Management

**Minikube**: Secrets in `k8s/overlays/minikube/secrets/` (gitignored)
- Generated from `.env.minikube` (see `k8s/scripts/generate-secrets.sh`)

**AWS**: Secrets created via kubectl (not in git)
- Managed separately per environment

**Secret Types**:
- `postgres-secret`: Database credentials
- `s3-credentials`: S3/MinIO access
- `tesslate-app-secrets`: API keys, OAuth, domain config

### Pod Security

**User Project Pods**:
- Run as non-root user (uid 1000)
- No privileged mode
- Read-only root filesystem (future improvement)

## Monitoring & Observability

### Health Checks

**Backend**:
- Startup probe: `/health` (initial delay 10s)
- Liveness probe: `/health` (every 10s)
- Readiness probe: `/health` (every 5s)

**Frontend**:
- Liveness probe: TCP socket 80
- Readiness probe: HTTP GET `/`

### Logging

**Pod logs**:
```bash
kubectl logs -n tesslate deployment/tesslate-backend
kubectl logs -n tesslate deployment/tesslate-backend -f  # follow
kubectl logs -n tesslate deployment/tesslate-backend --tail=100
```

**User project logs**:
```bash
kubectl logs -n proj-{uuid} {pod-name} -c dev-server
kubectl logs -n proj-{uuid} {pod-name} -c hydrate-project  # init container
```

### Metrics

**Resource usage**:
```bash
kubectl top pods -n tesslate
kubectl top nodes
```

**Future**: Prometheus + Grafana for metrics and alerting

## Troubleshooting

### Pod Not Starting

```bash
# Check pod status
kubectl get pods -n tesslate

# Check events
kubectl describe pod -n tesslate {pod-name}

# Check logs
kubectl logs -n tesslate {pod-name}

# Check previous container logs (if crash looping)
kubectl logs -n tesslate {pod-name} --previous
```

### Image Pull Errors

**Minikube**:
```bash
# Verify image exists in Minikube
minikube -p tesslate ssh -- docker images | grep tesslate

# Load image if missing
minikube -p tesslate image load tesslate-backend:latest
```

**AWS**:
```bash
# Verify image exists in ECR
aws ecr describe-images --repository-name tesslate-backend --region us-east-1

# Push if missing
docker push <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend:latest
```

### Service Not Reachable

```bash
# Check service
kubectl get svc -n tesslate
kubectl describe svc -n tesslate tesslate-backend-service

# Check endpoints (should list pod IPs)
kubectl get endpoints -n tesslate tesslate-backend-service

# Test from another pod
kubectl run -n tesslate test-pod --rm -it --image=curlimages/curl -- curl http://tesslate-backend-service:8000/health
```

### Ingress Not Working

```bash
# Check ingress
kubectl get ingress -n tesslate
kubectl describe ingress -n tesslate tesslate-ingress

# Check ingress controller logs
kubectl logs -n ingress-nginx deployment/ingress-nginx-controller --tail=50

# Restart ingress controller (clears cache)
kubectl rollout restart deployment/ingress-nginx-controller -n ingress-nginx
```

### Namespace Stuck Deleting

```bash
# Check finalizers
kubectl get ns proj-{uuid} -o yaml

# Remove finalizers
kubectl patch ns proj-{uuid} -p '{"metadata":{"finalizers":[]}}' --type=merge
```

## Deployment Procedures

### Initial Setup (Minikube)

```bash
# 1. Start cluster
minikube start -p tesslate --driver=docker --memory=4096 --cpus=2

# 2. Enable ingress addon
minikube -p tesslate addons enable ingress

# 3. Build and load images
docker build -t tesslate-backend:latest -f orchestrator/Dockerfile .
minikube -p tesslate image load tesslate-backend:latest

docker build -t tesslate-frontend:latest -f app/Dockerfile.prod app/
minikube -p tesslate image load tesslate-frontend:latest

docker build -t tesslate-devserver:latest -f orchestrator/Dockerfile.devserver .
minikube -p tesslate image load tesslate-devserver:latest

# 4. Create secrets
cp k8s/overlays/minikube/.env.example k8s/overlays/minikube/.env.minikube
# Edit .env.minikube with actual values
k8s/scripts/generate-secrets.sh minikube

# 5. Deploy MinIO
kubectl apply -k k8s/base/minio

# 6. Deploy platform
kubectl apply -k k8s/overlays/minikube

# 7. Wait for pods
kubectl wait --for=condition=ready pod -l app=tesslate-backend -n tesslate --timeout=300s

# 8. Access
minikube -p tesslate tunnel
# OR
kubectl port-forward -n tesslate svc/tesslate-frontend-service 5000:80
```

### Initial Setup (AWS EKS)

```bash
# 1. Provision infrastructure
cd k8s/terraform/aws
terraform init
terraform apply

# 2. Configure kubectl
aws eks update-kubeconfig --region us-east-1 --name <EKS_CLUSTER_NAME>

# 3. Create secrets
kubectl create secret generic tesslate-app-secrets -n tesslate \
  --from-literal=SECRET_KEY={value} \
  --from-literal=DATABASE_URL={value} \
  --from-literal=LITELLM_API_BASE={value} \
  --from-literal=LITELLM_MASTER_KEY={value} \
  # ... (see k8s/overlays/aws/README.md for full list)

# 4. Build and push images
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com

docker build --no-cache -t tesslate-backend:latest -f orchestrator/Dockerfile .
docker tag tesslate-backend:latest <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend:latest
docker push <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend:latest
# Repeat for frontend and devserver

# 5. Deploy platform
kubectl apply -k k8s/overlays/aws

# 6. Wait for pods
kubectl wait --for=condition=ready pod -l app=tesslate-backend -n tesslate --timeout=300s

# 7. Verify ingress
kubectl get ingress -n tesslate
```

### Updating Deployment

**Code changes**:
```bash
# 1. Build new image (ALWAYS use --no-cache)
docker build --no-cache -t tesslate-backend:latest -f orchestrator/Dockerfile .

# 2. Push (Minikube: load, AWS: push to ECR)
# Minikube:
minikube -p tesslate ssh -- docker rmi -f tesslate-backend:latest
minikube -p tesslate image load tesslate-backend:latest

# AWS:
docker tag tesslate-backend:latest <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend:latest
docker push <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend:latest

# 3. Force pod restart
kubectl delete pod -n tesslate -l app=tesslate-backend

# 4. Verify
kubectl logs -n tesslate deployment/tesslate-backend --tail=50
```

**Manifest changes**:
```bash
# 1. Edit manifests in k8s/base/ or k8s/overlays/{env}/

# 2. Apply changes
kubectl apply -k k8s/overlays/{env}

# 3. If deployment spec changed, rollout automatically happens
kubectl rollout status deployment/tesslate-backend -n tesslate
```

## Related Documentation

- [base/README.md](base/README.md): Base manifest documentation
- [overlays/README.md](overlays/README.md): Overlay configuration
- [rbac.md](rbac.md): RBAC configuration
- [network-policies.md](network-policies.md): Network security
- [s3-sandwich.md](s3-sandwich.md): Hibernation pattern
- [../../deployment/kubernetes.md](../../deployment/kubernetes.md): Deployment procedures

## Per-group base documentation

| Group | Doc |
|-------|-----|
| `k8s/base/namespace/` | [base/namespace.md](base/namespace.md) |
| `k8s/base/core/` | [base/core.md](base/core.md) |
| `k8s/base/database/` | [base/database.md](base/database.md) |
| `k8s/base/redis/` | [base/redis.md](base/redis.md) |
| `k8s/base/ingress/` | [base/ingress.md](base/ingress.md) |
| `k8s/base/security/` | [base/security.md](base/security.md) |
| `k8s/base/volume-hub/` | [base/volume-hub.md](base/volume-hub.md) |
| `k8s/base/compute-pool/` | [base/compute-pool.md](base/compute-pool.md) |

## Scripts

| Group | Doc |
|-------|-----|
| `k8s/scripts/` | [scripts/README.md](scripts/README.md) |

## Related assets

- `k8s/litellm/config.yaml` is documented at [litellm.md](litellm.md).
- Storage stack source lives at `services/btrfs-csi/`; see [../../services/btrfs-csi/CLAUDE.md](../../services/btrfs-csi/CLAUDE.md).
- In-container supervisor is documented at [../../services/tsinit/CLAUDE.md](../../services/tsinit/CLAUDE.md).

## References

- Kustomize docs: https://kustomize.io/
- Kubernetes docs: https://kubernetes.io/docs/
- NGINX Ingress: https://kubernetes.github.io/ingress-nginx/
- cert-manager: https://cert-manager.io/
