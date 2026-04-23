# Kubernetes Base Manifests

This directory contains environment-agnostic Kubernetes manifests that form the foundation of OpenSail's platform deployment.

**Location**: `c:/Users/Smirk/Downloads/Tesslate-Studio/k8s/base/`

## Structure

```
base/
├── kustomization.yaml           # Base Kustomize config
├── namespace/
│   └── tesslate.yaml            # Platform namespace
├── core/
│   ├── backend-deployment.yaml  # Orchestrator deployment
│   ├── backend-service.yaml     # Backend ClusterIP service
│   ├── frontend-deployment.yaml # React frontend deployment
│   ├── frontend-service.yaml    # Frontend ClusterIP service
│   └── cleanup-cronjob.yaml     # Idle environment cleanup
├── database/
│   ├── postgres-deployment.yaml # PostgreSQL deployment
│   ├── postgres-service.yaml    # PostgreSQL service
│   └── postgres-pvc.yaml        # PostgreSQL persistent volume
├── ingress/
│   └── main-ingress.yaml        # Platform ingress rules
├── security/
│   ├── rbac.yaml                # ServiceAccount, ClusterRole, ClusterRoleBinding
│   ├── network-policies.yaml    # Network isolation rules
│   └── resource-quotas.yaml     # Namespace resource limits
└── minio/                       # Local S3 (Minikube only)
    ├── minio-namespace.yaml
    ├── minio-deployment.yaml
    ├── minio-service.yaml
    ├── minio-pvc.yaml
    └── minio-init-job.yaml
```

## Core Components

### Backend Deployment

**File**: `core/backend-deployment.yaml`

**Purpose**: FastAPI orchestrator that manages projects, containers, and AI agents

**Key Configuration**:
- Image: `tesslate-backend:latest` (overridden by overlays)
- Port: 8000
- Service account: `tesslate-backend-sa` (for K8s API access)
- Health checks: `/health` endpoint
- Environment: ~50 env vars from secrets and configmaps

**Probes**:
- Startup: 10s initial delay, 5s period, 24 failures (2 minutes total)
- Liveness: 10s period, 5s timeout
- Readiness: 5s period, 3s timeout

**Resources** (defaults, overridden by overlays):
- Requests: 512Mi RAM, 250m CPU
- Limits: 1Gi RAM, 1000m CPU

### Frontend Deployment

**File**: `core/frontend-deployment.yaml`

**Purpose**: React UI served via NGINX

**Key Configuration**:
- Image: `tesslate-frontend:latest` (overridden by overlays)
- Port: 80
- Health checks: HTTP GET `/`

**Resources**:
- Requests: 128Mi RAM, 50m CPU
- Limits: 256Mi RAM, 200m CPU

### Cleanup CronJob

**File**: `core/cleanup-cronjob.yaml`

**Purpose**: Hibernate idle user projects (S3 Sandwich pattern)

**Schedule**: `*/2 * * * *` (every 2 minutes)

**Logic**:
1. Get list of project namespaces (`proj-*`)
2. Check last activity time in database
3. If idle > `K8S_HIBERNATION_IDLE_MINUTES`:
   - Trigger dehydration (PreStop hooks upload to S3)
   - Delete namespace (cascades to PVC, pods)
4. Project stays in S3 for next hydration

**Service Account**: Uses `tesslate-backend-sa` (same as backend)

**Concurrency**: `Forbid` (don't run multiple cleanup jobs simultaneously)

### PostgreSQL Deployment

**File**: `database/postgres-deployment.yaml`

**Purpose**: Platform database for users, projects, chat history

**Key Configuration**:
- Image: `postgres:15-alpine`
- Port: 5432
- PVC: `postgres-pvc` (10Gi)
- Credentials: From `postgres-secret`

**Health Check**: `pg_isready` command

**Resources**:
- Requests: 256Mi RAM, 100m CPU
- Limits: 512Mi RAM, 500m CPU

### Main Ingress

**File**: `ingress/main-ingress.yaml`

**Purpose**: Route external traffic to platform services

**Routes** (host patched by overlays):
```
/api      → tesslate-backend-service:8000
/         → tesslate-frontend-service:80
```

**Annotations**:
- `nginx.ingress.kubernetes.io/proxy-body-size: 50m` (large file uploads)
- `nginx.ingress.kubernetes.io/proxy-read-timeout: 3600` (long WebSocket connections)
- `nginx.ingress.kubernetes.io/use-regex: true` (path matching)

**TLS**: Configured in overlays (disabled for Minikube, enabled for AWS)

## Security

### RBAC

**File**: `security/rbac.yaml`

**ServiceAccount**: `tesslate-backend-sa`
- Used by backend deployment and cleanup cronjob
- Needs cluster-wide permissions to manage user project namespaces

**ClusterRole**: `tesslate-dev-environments-manager`
- Namespaces: create, delete, get, list, watch, patch, update
- Core resources: pods, services, PVCs, secrets, configmaps
- Apps: deployments, replicasets, statefulsets
- Networking: ingresses, networkpolicies
- Batch: jobs, cronjobs
- Events: get, list, watch (for troubleshooting)

**ClusterRoleBinding**: `tesslate-backend-cluster-access`
- Binds `tesslate-backend-sa` to `tesslate-dev-environments-manager`

**Why ClusterRole?**: Backend must create/delete namespaces and manage resources across `proj-*` namespaces. Role (namespaced) would only work within `tesslate` namespace.

### Network Policies

**File**: `security/network-policies.yaml`

See [../network-policies.md](../network-policies.md) for detailed documentation.

**Policies**:
1. `default-deny-ingress`: Block all ingress by default
2. `allow-ingress-controller`: Allow from NGINX Ingress namespace
3. `allow-backend-from-frontend`: Frontend → Backend (port 8000)
4. `allow-postgres-from-backend`: Backend → Postgres (port 5432)
5. `allow-dns-egress`: All pods → kube-dns
6. `allow-backend-egress`: Backend → all namespaces + external

**Philosophy**: Default deny, explicit allow. Principle of least privilege.

### Resource Quotas

**File**: `security/resource-quotas.yaml`

**Purpose**: Prevent resource exhaustion in `tesslate` namespace

**Limits** (defaults):
- CPU requests: 4 cores
- Memory requests: 8Gi
- CPU limits: 8 cores
- Memory limits: 16Gi
- PVCs: 5
- Services: 10

**Note**: User project namespaces (`proj-*`) don't have quotas (enforced per-project by backend).

## MinIO (Local S3)

**Files**: `minio/*.yaml`

**Purpose**: S3-compatible storage for Minikube (AWS EKS uses native S3)

**Namespace**: `minio-system` (separate from `tesslate`)

**Components**:
- Deployment: MinIO server (port 9000 API, 9001 console)
- Service: ClusterIP for backend access
- PVC: 10Gi for object storage
- Init job: Create `tesslate-projects` bucket on startup

**Access**:
- API: `http://minio.minio-system.svc.cluster.local:9000`
- Console: Port-forward to 9001 for web UI

**Credentials**: From `minio-credentials` secret in `minio-system` namespace

**Note**: Only deployed in Minikube overlay, not AWS.

## Kustomization

**File**: `kustomization.yaml`

**Namespace**: `tesslate` (all resources created in this namespace by default)

**Resources**: Lists all YAML files to include

**Images**: Declares image names (tags and registries overridden by overlays)
- `tesslate-backend:latest`
- `tesslate-frontend:latest`
- `tesslate-devserver:latest`

**ConfigMap Generator**: Creates `tesslate-config` with base settings
- `DEPLOYMENT_MODE=kubernetes`
- `K8S_NAMESPACE_PER_PROJECT=true`
- `K8S_ENABLE_NETWORK_POLICIES=true`

**Common Labels**: Applied to all resources
- `app.kubernetes.io/name: tesslate-studio`
- `app.kubernetes.io/managed-by: kustomize`

## Usage

### Preview Generated Manifests

```bash
kubectl kustomize k8s/base
```

**Note**: Base alone is not deployable (missing secrets, host configuration). Always deploy via overlay.

### Deploy via Overlay

```bash
# Minikube
kubectl apply -k k8s/overlays/minikube

# AWS
kubectl apply -k k8s/overlays/aws
```

### Modify Base

**When to modify base**:
- Adding new resource type (deployment, service, etc.)
- Changing configuration that applies to ALL environments
- Adding new RBAC rule
- Modifying network policies

**When NOT to modify base**:
- Environment-specific values (images, domains, TLS)
- Secrets
- Resource limits (vary by environment)

**Process**:
1. Edit YAML file in appropriate subdirectory
2. Add to `kustomization.yaml` if new resource
3. Test with Minikube: `kubectl apply -k k8s/overlays/minikube`
4. Verify pods start correctly
5. Deploy to AWS: `kubectl apply -k k8s/overlays/aws`

## Related Documentation

- [../README.md](../README.md): Kubernetes overview
- [../overlays/README.md](../overlays/README.md): Overlay configuration
- [../rbac.md](../rbac.md): RBAC details
- [../network-policies.md](../network-policies.md): Network security
