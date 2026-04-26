# Kubernetes Agent Context

You are working on OpenSail's Kubernetes configuration. This context provides quick reference for common Kubernetes tasks.

## File Locations

**Base manifests**: `k8s/base/`
**Overlays**: `k8s/overlays/{minikube,aws-base,aws-beta,aws-production}/`
**Terraform (per-env)**: `k8s/terraform/aws/`
**Terraform (shared)**: `k8s/terraform/shared/`

## kubectl Context Safety

**EVERY `kubectl` command MUST include `--context=<name>`.** Context switching (`kubectl config use-context`, `./scripts/kctx.sh`) is **BANNED** for agents — cronjobs and other processes can change the active context mid-session, causing accidental production mutations.

| Environment | `--context=` value | Domain |
|-------------|-------------------|--------|
| Production | `tesslate-production-eks` | `opensail.tesslate.com` |
| Beta | `tesslate-beta-eks` | beta domain |
| Minikube | `tesslate` | `localhost` |

**Correct usage:**
```bash
kubectl --context=tesslate get pods -n tesslate                    # minikube
kubectl --context=tesslate-production-eks get pods -n tesslate     # production
kubectl --context=tesslate-beta-eks get pods -n tesslate           # beta
```

**BANNED commands (agents must NEVER run these):**
```bash
kubectl config use-context ...    # BANNED — race condition with cronjobs
./scripts/kctx.sh ...             # BANNED — same problem
kubectl config set-context ...    # BANNED
```

`./scripts/kctx.sh` is available for **human operators only** in interactive terminals. Agents and automated scripts must use `--context=` on every command.

## Quick Commands

### Minikube

```bash
# Build and load image (CRITICAL: Delete first!)
minikube -p tesslate ssh -- docker rmi -f tesslate-backend:latest
docker build --no-cache -t tesslate-backend:latest -f orchestrator/Dockerfile .
minikube -p tesslate image load tesslate-backend:latest
kubectl delete pod -n tesslate -l app=tesslate-backend

# Deploy
kubectl apply -k k8s/overlays/minikube

# Access
kubectl port-forward -n tesslate svc/tesslate-frontend-service 5000:80
```

### AWS EKS

```bash
# Build and push
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com
docker build --no-cache -t tesslate-backend:latest -f orchestrator/Dockerfile .
docker tag tesslate-backend:latest <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend:latest
docker push <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend:latest

# Deploy
kubectl apply -k k8s/overlays/aws
kubectl delete pod -n tesslate -l app=tesslate-backend

# Restart ingress (clears cache)
kubectl rollout restart deployment/ingress-nginx-controller -n ingress-nginx
```

## Kustomize Structure

**Base** (`k8s/base/kustomization.yaml`):
- Defines common resources
- Sets namespace to `tesslate`
- Lists image names (without tags)

**Overlay** (`k8s/overlays/{env}/kustomization.yaml`):
- References base: `resources: [../../base]`
- Overrides images with registry and tag
- Applies patches for environment-specific config

**Worker Deployment** (`k8s/base/core/worker-deployment.yaml`):
- Runs same image as backend with `arq orchestrator.app.worker.WorkerSettings` command
- Shares `tesslate-secrets` and config with backend
- Separate resource limits for worker pods
- AWS overlay patch: `k8s/overlays/aws-base/worker-patch.yaml`
- `revisionHistoryLimit: 3`

**Redis** (`k8s/base/redis/`):
- `redis-deployment.yaml` - Single replica Redis with PVC persistence, `revisionHistoryLimit: 3`
- `redis-service.yaml` - ClusterIP service (port 6379)
- `redis-pvc.yaml` - 1Gi persistent volume claim
- ConfigMap with `maxmemory 512mb`, `volatile-lru` eviction, `appendonly yes`

**Base Deployment Defaults**:
- All deployments (backend, frontend, worker, postgres, redis, minio) include `revisionHistoryLimit: 3`
- CronJobs use `envFrom` with `secretRef` instead of individual `valueFrom` entries

## Common Tasks

### Adding Environment Variable

1. Edit `k8s/base/core/backend-deployment.yaml`
2. Add env var to container spec
3. If environment-specific, override in `k8s/overlays/{env}/backend-patch.yaml`
4. Apply: `kubectl apply -k k8s/overlays/{env}`

### Modifying Resource Limits

1. Edit deployment manifest or patch
2. Update `resources.requests` and `resources.limits`
3. Apply: `kubectl apply -k k8s/overlays/{env}`
4. Pods automatically restart with new limits

### Adding New Secret

1. **Minikube**: Add to `k8s/overlays/minikube/secrets/{secret-name}.yaml`
2. **AWS**: Create via kubectl: `kubectl create secret generic {name} -n tesslate --from-literal=KEY=value`
3. Reference in deployment: `valueFrom.secretKeyRef`

### Changing Image

1. **Base**: Update `images` section in `k8s/base/kustomization.yaml`
2. **Overlay**: Update `images` section in `k8s/overlays/{env}/kustomization.yaml`
3. Apply and restart pods

## Network Policies

**Location**: `k8s/base/security/network-policies.yaml`

**Structure**:
- One NetworkPolicy per rule
- `podSelector` defines which pods the policy applies to
- `policyTypes` defines direction (Ingress, Egress, or both)
- `ingress`/`egress` rules define allowed traffic

**Adding new rule**:
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-{source}-to-{dest}
  namespace: tesslate
spec:
  podSelector:
    matchLabels:
      app: {dest-app}
  policyTypes:
  - Ingress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: {source-app}
    ports:
    - protocol: TCP
      port: {port}
```

## RBAC

**Location**: `k8s/base/security/rbac.yaml`

**Components**:
1. ServiceAccount: `tesslate-backend-sa`
2. ClusterRole: `tesslate-dev-environments-manager` (defines permissions)
3. ClusterRoleBinding: `tesslate-backend-cluster-access` (grants permissions to SA)

**Adding permission**:
1. Edit ClusterRole
2. Add resource and verbs to `rules` section
3. Apply: `kubectl apply -k k8s/overlays/{env}`

## Storage Architecture (Hub + btrfs CSI)

Project storage uses a two-tier architecture: the **Volume Hub** (storageless orchestrator) coordinates **btrfs CSI node drivers** on each compute node. The Hub handles volume lifecycle, cache placement, and S3 sync; nodes handle local btrfs subvolume operations.

### Volume Hub

**Address**: `tesslate-volume-hub.kube-system.svc:9750` (gRPC, JSON codec)
**Image**: `tesslate-btrfs-csi:latest` with `--mode=hub`
**Namespace**: `kube-system`
**Manifests**: `k8s/base/volume-hub/` (deployment, service, rbac)

**Key RPCs** (service `volumehub.VolumeHub`):
| RPC | Purpose |
|-----|---------|
| `CreateVolume(template?, hint_node?)` | Create volume from template or empty; returns `(volume_id, node_name)` |
| `DeleteVolume(volume_id)` | Delete from Hub + S3 + all node caches (idempotent) |
| `EnsureCached(volume_id, candidate_nodes?)` | Ensure volume is on a live, schedulable node; peer-transfers or restores from CAS |
| `TriggerSync(volume_id)` | Trigger S3 sync on the owner node (non-blocking) |
| `VolumeStatus(volume_id)` | Returns `volume_id`, `owner_node`, `cached_nodes`, `last_sync` |
| `CreateServiceVolume(base_volume_id, service_name)` | Create ephemeral service subvolume (e.g. postgres data dir) |

### btrfs CSI Node Driver

**DaemonSet**: Runs on every compute node in `kube-system`
**Manifests**: `services/btrfs-csi/deploy/`
**CSI Driver name**: `btrfs.csi.tesslate.io`
**Node Service**: `tesslate-btrfs-csi-node-svc.kube-system.svc` (headless)
- Port `9741`: NodeOps gRPC (volume operations, template management)
- Port `9742`: FileOps gRPC (file read/write/list directly on subvolumes)

### Storage Classes

| StorageClass | Provisioner | Purpose |
|-------------|------------|---------|
| `tesslate-btrfs` | `btrfs.csi.tesslate.io` | Default for user project volumes |
| `tesslate-btrfs-nextjs` | `btrfs.csi.tesslate.io` | Pre-templated (parameter: `template: "nextjs"`) |
| `tesslate-block-storage` | `ebs.csi.aws.com` (AWS) / `k8s.io/minikube-hostpath` (Minikube) | Legacy EBS-backed PVCs (being phased out) |

### VolumeSnapshotClass

| Class | Driver | Policy |
|-------|--------|--------|
| `tesslate-btrfs-snapshots` | `btrfs.csi.tesslate.io` | Delete |

### Orchestrator Integration

| File | Purpose |
|------|---------|
| `orchestrator/app/services/volume_manager.py` | Thin client wrapping HubClient; singleton via `get_volume_manager()` |
| `orchestrator/app/services/hub_client.py` | Async gRPC client for Volume Hub RPCs |
| `orchestrator/app/services/snapshot_manager.py` | Legacy EBS VolumeSnapshot manager (still used for EBS-backed projects) |

### Config Settings (`config.py`)

| Setting | Default | Purpose |
|---------|---------|---------|
| `volume_hub_address` | `tesslate-volume-hub.kube-system.svc:9750` | Hub gRPC endpoint |
| `template_build_storage_class` | `tesslate-btrfs` | StorageClass for template builds (must be btrfs CSI) |
| `template_build_nodeops_address` | `tesslate-btrfs-csi-node-svc.kube-system.svc:9741` | NodeOps gRPC for template operations |
| `fileops_enabled` | `True` | Feature flag for v2 file operations via CSI |
| `fileops_timeout` | `30` | gRPC timeout for file operations (seconds) |
| `k8s_storage_class` | `tesslate-block-storage` | Legacy storage class (EBS-backed) |
| `k8s_snapshot_class` | `tesslate-ebs-snapshots` | Legacy EBS snapshot class |

### Deploy (Compute Stack)

The btrfs CSI driver + Volume Hub are deployed as a separate compute overlay:
```bash
# AWS
./scripts/aws-deploy.sh deploy-compute production

# Kustomize path
k8s/overlays/aws-production/compute/kustomization.yaml
k8s/overlays/aws-beta/compute/kustomization.yaml
```

### Legacy: EBS VolumeSnapshot

The `snapshot_manager.py` still handles EBS-backed VolumeSnapshots for projects that have not migrated to the Hub:
- `create_snapshot(pvc_name=...)` - Creates EBS snapshot (non-blocking)
- `restore_from_snapshot(pvc_name=...)` - Creates PVC from snapshot
- `cleanup_expired_snapshots()` - Removes old soft-deleted snapshots

**Cleanup cronjobs**: `k8s/base/core/`
- `cleanup-cronjob.yaml` - Runs every 2 minutes, creates snapshots for idle projects
- `snapshot-cleanup-cronjob.yaml` - Daily at 3 AM, deletes expired soft-deleted snapshots

**Timeline UI**: Frontend displays up to 5 snapshots per project for version history

## Debugging

### Pod crash loop
```bash
kubectl logs -n tesslate {pod-name} --previous
kubectl describe pod -n tesslate {pod-name}
```

### Image pull issues
```bash
# Minikube
minikube -p tesslate ssh -- docker images | grep tesslate

# AWS
aws ecr describe-images --repository-name tesslate-backend --region us-east-1
```

### Service not reachable
```bash
kubectl get endpoints -n tesslate tesslate-backend-service
kubectl run -n tesslate test --rm -it --image=curlimages/curl -- curl http://tesslate-backend-service:8000/health
```

### Ingress not routing
```bash
kubectl logs -n ingress-nginx deployment/ingress-nginx-controller --tail=50
kubectl rollout restart deployment/ingress-nginx-controller -n ingress-nginx
```

## Best Practices

1. **Use overlays, not base edits**: Modify environment-specific files in overlays
2. **Always --no-cache on builds**: Ensures code changes are included
3. **Delete before load (Minikube)**: `minikube image load` doesn't overwrite
4. **Restart ingress after backend changes**: Clears endpoint cache
5. **Test in Minikube first**: Catches K8s issues before production

---

## Network Boundary Security (issue #248)

The platform enforces network security at three independent layers so a single misconfiguration cannot create a breach.

### Layer 1 — Ingress block for `/api/internal/*`

`/api/internal/*` is blocked at the NGINX edge via `server-snippet` in `k8s/base/ingress/main-ingress.yaml`. External callers receive 403 before the request reaches the backend. Cluster-internal callers (Hub, GC) **must** use the ClusterIP DNS name directly:
```
http://tesslate-backend-service.tesslate.svc.cluster.local:8000/api/internal/...
```
They must **not** use the public Ingress hostname.

### Layer 2 — Shared-secret auth on `/api/internal/*`

All `/api/internal/*` routes require an `X-Internal-Secret` header matching `INTERNAL_API_SECRET` in the backend. Both secrets must be set consistently:

| Component | Secret variable | Secret source |
|-----------|----------------|---------------|
| Backend (`tesslate-backend`) | `INTERNAL_API_SECRET` | `tesslate-app-secrets` |
| Volume Hub (`tesslate-volume-hub`) | `ORCHESTRATOR_INTERNAL_SECRET` | `tesslate-btrfs-csi-config` |
| CSI node (`tesslate-btrfs-csi-node`) | `ORCHESTRATOR_INTERNAL_SECRET` | `tesslate-btrfs-csi-config` |

**Generating a secret value:**
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

**Grace period**: For the first 60 seconds after the backend starts, requests with a missing or wrong secret are allowed through with a warning (to avoid hard failures during rolling deploys). Set `INTERNAL_SECRET_GRACE_SECONDS=0` once both sides are confirmed stable.

**Desktop mode**: The Hub does not run in desktop mode, so `INTERNAL_API_SECRET` is ignored.

### Layer 3 — IMDS block in user project NetworkPolicies

All user project NetworkPolicies (`proj-*` namespaces) block `169.254.169.254/32` (the AWS IMDS endpoint) from both TCP 443 and TCP 80 egress rules. This prevents user code from stealing node IAM credentials via the metadata service.

The same IMDS except-block is applied to compute pool pods (`tesslate-compute-pool` namespace).

**Minikube impact**: None. `169.254.169.254` is not routed in the minikube virtual network — the block is a no-op locally.

### Runbook — Adding a New External Dependency

When any backend or worker code makes a new outbound call to an external service (new AI provider, OAuth endpoint, webhook target, etc.), egress to that target will be blocked in K8s environments by `default-deny-egress` unless an explicit rule is added.

**Steps:**
1. Identify the external service's hostname and port(s).
2. Add an egress rule to `allow-backend-egress` (or `allow-worker-egress` if the call originates from the ARQ worker) in `k8s/base/security/network-policies.yaml`.
3. Apply: `kubectl apply -k k8s/overlays/minikube --context=tesslate` and test.
4. Apply to beta, then production.

**Note**: In Minikube without Calico/Cilium CNI, NetworkPolicy is not enforced — the policy gap only surfaces in beta. Test with `kubectl exec` network probes to verify egress is working as expected.

### Runbook — Rolling Out Secret Changes

To rotate `INTERNAL_API_SECRET` / `ORCHESTRATOR_INTERNAL_SECRET`:

1. Update both secrets simultaneously in Terraform / K8s secrets.
2. Set `INTERNAL_SECRET_GRACE_SECONDS=120` temporarily to widen the window.
3. Deploy the backend (new secret active, grace period covers the hub rollover).
4. Deploy the btrfs-csi DaemonSet and Volume Hub.
5. Verify Hub calls succeed: `kubectl logs -n kube-system deployment/tesslate-volume-hub`.
6. Reset `INTERNAL_SECRET_GRACE_SECONDS=0`.

---

## Orchestrator Config Settings (K8s mode)

Full reference for K8s-related settings in `orchestrator/app/config.py`. Complements the smaller Volume Hub table above.

```python
# User container image
k8s_devserver_image: str           # Image for user containers (registry.digitalocean.com/tesslate-container-registry-nyc3/tesslate-devserver:latest)
k8s_image_pull_secret: str         # Registry secret (tesslate-container-registry-nyc3)

# Storage & snapshots
k8s_storage_class: str             # StorageClass for PVCs (tesslate-block-storage)
k8s_snapshot_class: str            # VolumeSnapshotClass (tesslate-ebs-snapshots)
k8s_snapshot_retention_days: int   # Days to keep soft-deleted snapshots (30)
k8s_max_snapshots_per_project: int # Max snapshots in timeline (5)
k8s_snapshot_ready_timeout_seconds: int  # Snapshot readiness timeout (300)
k8s_hibernation_idle_minutes: int  # Auto-hibernate after X idle minutes (10)
k8s_pvc_size: str                  # Default PVC size per project (5Gi)
k8s_enable_pod_affinity: bool      # Keep multi-container projects on same node

# Volume Hub + btrfs CSI
volume_hub_address: str            # Hub gRPC endpoint (tesslate-volume-hub.kube-system.svc:9750)
template_build_storage_class: str  # btrfs CSI storage class for templates (tesslate-btrfs)
template_build_nodeops_address: str # NodeOps gRPC endpoint for template builds
fileops_enabled: bool              # Feature flag for v2 file operations via CSI (True)
fileops_timeout: int               # gRPC timeout for file operations (30s)

# Compute pool
compute_max_concurrent_pods: int   # Max concurrent compute pods (5)
compute_pod_timeout: int           # Compute pod readiness timeout (600s)
compute_reaper_interval_seconds: int  # Orphaned-pod reaper interval (60s)
compute_reaper_max_age_seconds: int   # Max pod age before reaping (900s)

# Task queue / workers
redis_url: str                     # Redis connection string (empty = in-memory fallback)
worker_max_jobs: int               # Concurrent agent tasks per worker pod (10)
worker_job_timeout: int            # Task timeout in seconds (600)

# Web search
web_search_provider: str           # tavily, brave, or duckduckgo (default: tavily)
tavily_api_key: str                # Tavily API key
brave_search_api_key: str          # Brave Search API key

# Messaging channels
agent_discord_webhook_url: str     # Discord webhook URL for agent send_message tool
channel_encryption_key: str        # Fernet key for channel credential encryption

# MCP (Model Context Protocol)
mcp_tool_cache_ttl: int            # MCP tool schema cache TTL in seconds (300)
mcp_tool_timeout: int              # MCP tool call timeout in seconds (30)
mcp_max_servers_per_user: int      # Max installed MCP servers per user (20)

# Gateway (Communication Protocol v2)
gateway_enabled: bool              # Enable gateway process (False)
gateway_shard: str                 # Shard identifier for multi-instance gateway
gateway_tick_interval: int         # Scheduler tick interval in seconds
gateway_session_idle_minutes: int  # Idle timeout for gateway sessions
gateway_voice_transcription: bool  # Enable voice message transcription

# Agent
compaction_summary_model: str      # Cheap model for context summarization
default_thinking_effort: str       # Extended thinking effort for supported models
```

## Minikube vs Production Config

| Setting | Minikube | Production (AWS EKS) |
|---------|----------|----------------------|
| `K8S_DEVSERVER_IMAGE` | `tesslate-devserver:latest` | `<ECR_REGISTRY>/tesslate-devserver:latest` |
| `K8S_IMAGE_PULL_SECRET` | `` (empty) | `ecr-credentials` |
| `K8S_WILDCARD_TLS_SECRET` | `` (empty, use HTTP) | `tesslate-wildcard-tls` (use HTTPS) |
| `K8S_SNAPSHOT_CLASS` | `tesslate-btrfs-snapshots` (via btrfs CSI) | `tesslate-ebs-snapshots` |
| `K8S_STORAGE_CLASS` | `tesslate-btrfs` (btrfs CSI) | `tesslate-block-storage` (EBS gp3) |
| `TEMPLATE_BUILD_STORAGE_CLASS` | `tesslate-btrfs` | `tesslate-btrfs` |
| `VOLUME_HUB_ADDRESS` | `tesslate-volume-hub.kube-system.svc:9750` | `tesslate-volume-hub.kube-system.svc:9750` |

## AWS Overlay Conventions

### envFrom Auto-Sync

The AWS backend overlay (`k8s/overlays/aws-base/backend-patch.yaml`) uses a two-part strategy:

1. **`envFrom`** — auto-mounts ALL keys from 3 terraform-managed secrets (`tesslate-app-secrets`, `postgres-secret`, `s3-credentials`). Adding a new key in terraform's `kubernetes.tf` automatically makes it available in the pod — **no manual kustomize sync needed**.
2. **`env` with `$patch: replace`** — replaces the base manifest's env array with ONLY static values (not in any secret) and 1 alias mapping (`K8S_INGRESS_DOMAIN` → `APP_DOMAIN`). The `$patch: replace` prevents stale base entries from merging in.

**When adding new config:**
- **Secret-based values** (domain, API keys, OAuth, etc.): add to terraform `kubernetes.tf` secrets → automatically picked up via `envFrom`
- **Static values** (feature flags, class names, etc.): add to `backend-patch.yaml` env array

### Frontend Config: `API_URL` must NOT include `/api`

The frontend `api-url` in the `frontend-config` ConfigMap (managed by terraform `kubernetes.tf`) must be the **base domain only** (e.g., `https://opensail.tesslate.com`), NOT `https://opensail.tesslate.com/api`. All API calls in `app/src/lib/api.ts` already include the `/api` prefix in their paths, so including `/api` in the base URL causes double `/api/api/` paths.
