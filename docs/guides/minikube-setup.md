# Minikube Setup Guide

Run OpenSail on a local Kubernetes cluster using Minikube. This guide walks from an empty machine to a working cluster with the btrfs CSI driver, Volume Hub, NGINX Ingress, MinIO (S3 simulation), PostgreSQL, and Redis.

> Every `kubectl` command in this guide includes `--context=tesslate`. That is a hard project rule. Never use `kubectl config use-context` or any context-switching helper. Cronjobs and other processes can change the active context mid-session, so the context must be pinned on every call.

For agent internals (tools, streaming, task payloads), see [packages/tesslate-agent/docs/DOCS.md](../../packages/tesslate-agent/docs/DOCS.md).

## 1. What you will run

| Component | Namespace | Purpose |
|-----------|-----------|---------|
| OpenSail backend | `tesslate` | FastAPI orchestrator |
| OpenSail frontend | `tesslate` | React UI served by nginx |
| PostgreSQL | `tesslate` | Primary database |
| Redis | `tesslate` | Pub/sub and task queue |
| MinIO | `minio-system` | S3-compatible object store |
| btrfs CSI driver | `kube-system` | Per-node btrfs subvolumes and snapshots |
| Volume Hub | `kube-system` | Volume orchestrator, cache placement, S3 sync |
| Snapshot controller | `kube-system` | Kubernetes VolumeSnapshot CRDs |
| NGINX Ingress | `ingress-nginx` | HTTP routing to frontend and backend |

Minikube profile name is `tesslate`. All application URLs terminate at `http://localhost` or `http://*.localhost` via the NGINX Ingress addon. Production uses NGINX Ingress with TLS; Traefik is only used in the Docker Compose dev mode, not here.

## 2. Prerequisites

### Software

| Tool | Min version | Install |
|------|-------------|---------|
| Docker | 24.x | [Docker Desktop](https://docs.docker.com/get-docker/) or `docker-ce` |
| Minikube | 1.33 | `brew install minikube`, `choco install minikube`, or [direct download](https://minikube.sigs.k8s.io/docs/start/) |
| kubectl | 1.29 | `brew install kubectl` or `choco install kubernetes-cli` |

### Hardware

Minimum for a single-user dev loop with one project running:

- 4 CPU cores available to Docker
- 8 GB RAM available to Docker
- 40 GB free disk for the Minikube VM image

### btrfs requirement

The btrfs CSI driver needs a btrfs filesystem inside the Minikube VM. The Docker driver's base image already ships with btrfs tools, and the driver creates its subvolume pool at `/mnt/tesslate-pool` inside the node. No host filesystem changes are required when using `--driver docker`. If you switch to a different driver (kvm2, hyperkit), make sure the guest OS has `btrfs-progs` and a mountable btrfs partition.

### Hosts file entries

Add the following to `/etc/hosts` (Linux/macOS) or `C:\Windows\System32\drivers\etc\hosts` (Windows). The Minikube IP is printed by `minikube ip --profile tesslate` after startup; user project containers always resolve through `*.localhost` thanks to NGINX Ingress.

```
127.0.0.1 localhost
127.0.0.1 minio.localhost
```

Project container URLs follow the pattern `http://<slug>-<container>.localhost` and are resolved by NGINX Ingress when the `minikube tunnel` is running.

## 3. Start the cluster

```bash
minikube start \
  --profile tesslate \
  --cpus 4 \
  --memory 8g \
  --disk-size 40g \
  --driver docker \
  --addons ingress \
  --addons storage-provisioner \
  --addons metrics-server
```

The `ingress` addon installs NGINX Ingress in the `ingress-nginx` namespace. The `tesslate` profile is what every `--context=tesslate` flag in this guide refers to.

Verify the cluster is up:

```bash
kubectl --context=tesslate get nodes
kubectl --context=tesslate get pods -n ingress-nginx
```

In a second terminal, start the tunnel so Ingress can receive requests on `localhost`:

```bash
minikube tunnel --profile tesslate
```

Leave that terminal open while you use the cluster.

## 4. Install prerequisites (snapshot controller + btrfs CSI driver)

OpenSail depends on Kubernetes `VolumeSnapshot` resources for hibernation and timeline features. Install the CRDs and the snapshot controller first, then deploy the btrfs CSI driver.

### Snapshot controller CRDs

```bash
SNAP_VERSION=v8.2.0
CRD_BASE="https://raw.githubusercontent.com/kubernetes-csi/external-snapshotter/${SNAP_VERSION}/client/config/crd"
CTRL_BASE="https://raw.githubusercontent.com/kubernetes-csi/external-snapshotter/${SNAP_VERSION}/deploy/kubernetes/snapshot-controller"

kubectl --context=tesslate apply -f ${CRD_BASE}/snapshot.storage.k8s.io_volumesnapshotclasses.yaml
kubectl --context=tesslate apply -f ${CRD_BASE}/snapshot.storage.k8s.io_volumesnapshotcontents.yaml
kubectl --context=tesslate apply -f ${CRD_BASE}/snapshot.storage.k8s.io_volumesnapshots.yaml

kubectl --context=tesslate apply -f ${CTRL_BASE}/rbac-snapshot-controller.yaml
kubectl --context=tesslate apply -f ${CTRL_BASE}/setup-snapshot-controller.yaml
```

### Build and load the btrfs CSI image

```bash
docker build -t tesslate-btrfs-csi:latest -f services/btrfs-csi/Dockerfile services/btrfs-csi/
minikube -p tesslate image load tesslate-btrfs-csi:latest
```

### Apply the minikube overlay

The overlay at `services/btrfs-csi/overlays/minikube/` bundles the CSI node DaemonSet, the Volume Hub Deployment, and `tesslate-btrfs-csi-config` secret (via `csi-credentials.yaml`). Copy the example credentials file first:

```bash
cp services/btrfs-csi/overlays/minikube/csi-credentials.example.yaml \
   services/btrfs-csi/overlays/minikube/csi-credentials.yaml
```

Edit `csi-credentials.yaml` if you change the MinIO admin password. The default `change-me-to-a-secure-password` matches the example MinIO secret, which you will update in section 6. Both values must agree.

Then deploy:

```bash
kubectl --context=tesslate apply -k services/btrfs-csi/overlays/minikube
kubectl --context=tesslate rollout status daemonset/tesslate-btrfs-csi-node -n kube-system --timeout=120s
kubectl --context=tesslate rollout status deployment/tesslate-volume-hub -n kube-system --timeout=120s
```

This deploys:

- `tesslate-btrfs-csi-node` DaemonSet in `kube-system` (one pod per node, manages btrfs subvolumes and file operations)
- `tesslate-volume-hub` Deployment in `kube-system` (volume orchestrator plus the CSI provisioner and snapshotter sidecars)
- `tesslate-image-precache` DaemonSet (pre-pulls the devserver image on every node)

## 5. Volume Hub

Volume Hub is the storageless orchestrator that sits above the per-node btrfs CSI driver. It owns volume placement and cache coordination and exposes a gRPC API at `tesslate-volume-hub.kube-system.svc:9750`. The backend talks to it through `orchestrator/app/services/hub_client.py`.

Responsibilities:

- `CreateVolume` picks a node with capacity and creates an empty or template-cloned subvolume.
- `EnsureCached` guarantees a volume is present on the node where a pod is about to be scheduled (fast path if already local, otherwise peer-transfer or S3 restore).
- `TriggerSync` kicks a CAS upload to MinIO when a project hibernates.
- `DeleteVolume` removes the subvolume and any S3 objects it owns.

The base manifests live in `k8s/base/volume-hub/`. The minikube overlay above pulls them in via `resources: [..., ../../../../k8s/base/volume-hub]` and patches the image pull policy to `Never` so the locally loaded `tesslate-btrfs-csi:latest` image is used.

Verify it is up:

```bash
kubectl --context=tesslate get pods -n kube-system -l app=tesslate-volume-hub
kubectl --context=tesslate logs -n kube-system deploy/tesslate-volume-hub -c hub
```

## 6. Configure secrets

Each secret lives in `k8s/overlays/minikube/secrets/` with a matching `.example.yaml` file. Copy and edit each one:

```bash
cd k8s/overlays/minikube/secrets

cp app-secrets.example.yaml      app-secrets.yaml
cp postgres-secret.example.yaml  postgres-secret.yaml
cp s3-credentials.example.yaml   s3-credentials.yaml
cp minio-credentials.example.yaml minio-credentials.yaml

cd -
```

Fill in the required values. The bare minimum for a working cluster:

| File | Key | Notes |
|------|-----|-------|
| `app-secrets.yaml` | `SECRET_KEY` | Generate: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `app-secrets.yaml` | `INTERNAL_API_SECRET` | Same generator; must match `ORCHESTRATOR_INTERNAL_SECRET` in `tesslate-btrfs-csi-config` |
| `app-secrets.yaml` | `DATABASE_URL` | `postgresql+asyncpg://tesslate_user:<password>@postgres:5432/tesslate_dev` |
| `app-secrets.yaml` | `LITELLM_API_BASE`, `LITELLM_MASTER_KEY` | Your LiteLLM proxy or OpenAI-compatible endpoint |
| `postgres-secret.yaml` | `POSTGRES_PASSWORD` | Must match the password embedded in `DATABASE_URL` above |
| `s3-credentials.yaml` | `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | Must match `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` |
| `minio-credentials.yaml` | `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` | MinIO admin credentials |

Leave OAuth, Stripe, and SMTP blank unless you need those flows during local development. The backend boots fine with empty values.

OAuth callbacks in the example point at `http://localhost/api/auth/<provider>/callback`. When a provider enforces HTTPS callbacks, you will not be able to test them on pure minikube; use Cloudflare tunnel (see `k8s/overlays/minikube/cloudflare-tunnel/`) if needed.

### Optional: Llama API secret for seeded apps

The seeded `crm-demo` and `nightly-digest` apps reference a cluster secret called `llama-api-credentials`. Without it those pods fail to start. Create it once:

```bash
kubectl --context=tesslate -n tesslate create secret generic llama-api-credentials \
  --from-literal=api_key='<your-llama-api-key>'
```

## 7. Deploy OpenSail

### Build and load the application images

```bash
docker build -t tesslate-backend:latest    -f orchestrator/Dockerfile          orchestrator/
docker build -t tesslate-frontend:latest   -f app/Dockerfile.prod              app/
docker build -t tesslate-devserver:latest  -f orchestrator/Dockerfile.devserver .

minikube -p tesslate image load tesslate-backend:latest
minikube -p tesslate image load tesslate-frontend:latest
minikube -p tesslate image load tesslate-devserver:latest
```

The devserver image is the base image used for every user project container. The minikube overlay sets `K8S_DEVSERVER_IMAGE=tesslate-devserver:latest` and `K8S_IMAGE_PULL_POLICY=Never`, so the image must already exist inside the node before any project starts.

### Deploy MinIO

MinIO runs in its own namespace with its own PVC. The overlay at `k8s/overlays/minikube/minio/` wires up the namespace, deployment, service, PVC, init job, and credentials.

```bash
kubectl --context=tesslate apply -k k8s/overlays/minikube/minio
kubectl --context=tesslate wait --for=condition=ready pod -l app=minio -n minio-system --timeout=180s
```

The init job (`minio-init-job.yaml`) creates the `tesslate-projects` bucket and the `tesslate-btrfs-snapshots` bucket used by the CSI driver's CAS sync.

### Deploy the application

```bash
kubectl --context=tesslate apply -k k8s/overlays/minikube
```

This applies everything in `k8s/base/` (namespace, backend, frontend, postgres, redis, ingress, security, volume-hub references) plus the minikube-specific patches (local images, `imagePullPolicy: Never`, HTTP-only ingress, single replicas).

Wait for each deployment to become ready:

```bash
kubectl --context=tesslate rollout status deployment/postgres          -n tesslate --timeout=180s
kubectl --context=tesslate rollout status deployment/redis             -n tesslate --timeout=120s
kubectl --context=tesslate rollout status deployment/tesslate-backend  -n tesslate --timeout=300s
kubectl --context=tesslate rollout status deployment/tesslate-frontend -n tesslate --timeout=180s
```

The backend runs Alembic migrations on startup. If the first pod fails with a migration error, it will retry; wait a minute before investigating.

## 8. Access the app

With the tunnel running (section 3) the NGINX Ingress answers on `localhost`. No port-forwarding needed for normal use.

| URL | What it serves |
|-----|----------------|
| `http://localhost/` | Frontend |
| `http://localhost/api/` | Backend API |
| `http://<slug>-<container>.localhost/` | User project preview (e.g., `http://my-app-k3x8n2-frontend.localhost`) |
| `http://minio.localhost/` | MinIO S3 API (after adding an Ingress rule or via port-forward below) |

Alternative access without the tunnel, using port-forward:

```bash
kubectl --context=tesslate port-forward -n tesslate svc/tesslate-frontend-service 5000:80
kubectl --context=tesslate port-forward -n tesslate svc/tesslate-backend-service  8000:8000
kubectl --context=tesslate port-forward -n minio-system svc/minio 9001:9001
```

OpenSail does not run Traefik in Kubernetes. Traefik is only the Docker Compose dev mode router; NGINX Ingress serves the same role in this guide.

## 9. Seed the database

The seeding scripts live at `scripts/seed/`. Run them in order, same as the Docker guide, but through `kubectl exec`:

```bash
BACKEND_POD=$(kubectl --context=tesslate get pods -n tesslate \
  -l app=tesslate-backend -o jsonpath='{.items[0].metadata.name}')

for script in \
  seed_marketplace_bases.py \
  seed_marketplace_agents.py \
  seed_opensource_agents.py \
  seed_skills.py \
  seed_themes.py \
  seed_mcp_servers.py \
  seed_community_bases.py
do
  kubectl --context=tesslate cp "scripts/seed/$script" "tesslate/${BACKEND_POD}:/tmp/$script"
  kubectl --context=tesslate exec -n tesslate "$BACKEND_POD" -- python "/tmp/$script"
done
```

Individual failures are non-fatal; the remaining scripts can still run. Re-running a seed script is idempotent.

## 10. Create a project

From the frontend at `http://localhost/`, create a project. Behind the scenes:

1. The backend creates a namespace `proj-<uuid>` with NetworkPolicy isolation.
2. Volume Hub picks a node with capacity and creates a btrfs subvolume, cloning from the template snapshot if one exists.
3. A PVC referencing the btrfs CSI storage class `tesslate-btrfs` is created. PVC size defaults to `K8S_PVC_SIZE=5Gi`.
4. One Deployment and Service is created per container declared in `.tesslate/config.json`. If multiple containers are declared, pod affinity rules keep them on the same node so they share the volume without cross-node traffic.
5. An Ingress rule is added for each exposed container, routed on `http://<slug>-<container>.localhost`.

Inspect what landed:

```bash
kubectl --context=tesslate get ns | grep proj-
NS=<proj-uuid>
kubectl --context=tesslate get all,pvc,ingress -n $NS
kubectl --context=tesslate describe pod -n $NS -l app=frontend
```

## 11. Snapshots and hibernation

OpenSail keeps up to `K8S_MAX_SNAPSHOTS_PER_PROJECT=5` `VolumeSnapshot` objects per project as a timeline. Idle projects hibernate after `K8S_HIBERNATION_IDLE_MINUTES=10` minutes: the backend triggers Volume Hub `TriggerSync` to push the CAS content to MinIO, then tears down the compute pod while keeping the volume cached on its node.

Watch snapshots and volume state:

```bash
NS=<proj-uuid>
kubectl --context=tesslate get volumesnapshots     -n $NS
kubectl --context=tesslate get volumesnapshotcontents
kubectl --context=tesslate get pvc                 -n $NS
kubectl --context=tesslate logs -n kube-system deploy/tesslate-volume-hub -c hub --tail=100
```

When you click Start on a hibernated project, Volume Hub will restore from the cached subvolume if the node still has it, or pull the CAS objects back from MinIO otherwise.

## 12. Common commands

Always include `--context=tesslate`.

```bash
# Status
kubectl --context=tesslate get pods -n tesslate
kubectl --context=tesslate get pods -A | grep proj-
kubectl --context=tesslate get events -n tesslate --sort-by='.lastTimestamp'

# Logs
kubectl --context=tesslate logs -f deployment/tesslate-backend  -n tesslate
kubectl --context=tesslate logs -f deployment/tesslate-frontend -n tesslate
kubectl --context=tesslate logs -n kube-system deploy/tesslate-volume-hub -c hub

# Shell into backend
kubectl --context=tesslate exec -it deployment/tesslate-backend -n tesslate -- /bin/bash

# Restart a deployment after rebuilding an image
minikube -p tesslate ssh -- docker rmi -f tesslate-backend:latest
docker build -t tesslate-backend:latest -f orchestrator/Dockerfile orchestrator/
minikube -p tesslate image load tesslate-backend:latest
kubectl --context=tesslate rollout restart deployment/tesslate-backend -n tesslate

# Reapply manifests after editing the overlay
kubectl --context=tesslate apply -k k8s/overlays/minikube

# Port-forward anything
kubectl --context=tesslate port-forward -n tesslate svc/tesslate-backend-service 8000:8000
```

On Windows Git Bash, prefix `kubectl` and `docker exec` calls with `MSYS_NO_PATHCONV=1` so paths are not mangled.

## 13. Teardown

Remove application resources but keep the cluster:

```bash
./k8s/scripts/minikube/teardown.sh
```

Or manually:

```bash
kubectl --context=tesslate delete namespace tesslate      --ignore-not-found
kubectl --context=tesslate delete namespace minio-system  --ignore-not-found
kubectl --context=tesslate delete storageclass tesslate-block-storage --ignore-not-found
```

Destroy the whole cluster and reclaim disk:

```bash
./k8s/scripts/minikube/teardown.sh --all
# or
minikube delete --profile tesslate
```

User project data is lost when the cluster is deleted. PVCs survive a `minikube stop` / `minikube start` cycle.

## 14. Troubleshooting

### `btrfs: command not found` or CSI node pod CrashLoops

The Minikube VM image must have btrfs tools available. Use `--driver docker` (confirmed working) and confirm the init container for `tesslate-btrfs-csi-node` completed:

```bash
kubectl --context=tesslate describe pod -n kube-system -l app=tesslate-btrfs-csi-node
kubectl --context=tesslate logs       -n kube-system -l app=tesslate-btrfs-csi-node -c init-btrfs
```

If you changed driver, recreate the cluster.

### Snapshot controller missing, no `VolumeSnapshot` API

Symptom: `no matches for kind "VolumeSnapshot" in version "snapshot.storage.k8s.io/v1"`. Re-run the CRD and controller steps in section 4. Verify with:

```bash
kubectl --context=tesslate get crds | grep snapshot.storage.k8s.io
kubectl --context=tesslate get pods  -n kube-system -l app=snapshot-controller
```

### DNS resolution for `*.localhost`

Modern browsers resolve `*.localhost` to `127.0.0.1` automatically. If a container preview stalls on "health checking":

1. Confirm `minikube tunnel --profile tesslate` is still running.
2. `kubectl --context=tesslate get ingress -A | grep proj-` and check the rule exists.
3. `kubectl --context=tesslate describe ingress -n proj-<uuid>` and look for controller errors.

If your OS does not resolve `*.localhost`, add the specific host to `/etc/hosts` pointing at `127.0.0.1`.

### Pod stuck in `ImagePullBackOff`

Local images were not loaded into Minikube, or the tag drifted. Load again:

```bash
minikube -p tesslate image ls | grep tesslate
minikube -p tesslate image load tesslate-backend:latest
kubectl --context=tesslate rollout restart deployment/tesslate-backend -n tesslate
```

### Pod in `CrashLoopBackOff`

```bash
kubectl --context=tesslate describe pod <pod> -n <namespace>
kubectl --context=tesslate logs <pod> -n <namespace> --previous
```

Common causes: wrong `DATABASE_URL` in `app-secrets.yaml`, Postgres not ready yet, `INTERNAL_API_SECRET` mismatch between `tesslate-app-secrets` and `tesslate-btrfs-csi-config`, missing `llama-api-credentials` for seeded apps.

### Database reset

```bash
kubectl --context=tesslate delete pvc postgres-pvc -n tesslate
kubectl --context=tesslate delete pod -l app=postgres -n tesslate
kubectl --context=tesslate rollout restart deployment/tesslate-backend -n tesslate
```

## 15. Where to next

- Docker Compose dev loop (fastest inner loop, no Kubernetes): [docker-setup.md](./docker-setup.md)
- Production deployment on AWS EKS: [aws-deployment.md](./aws-deployment.md)
- Agent internals (tools, streaming, task payloads): [packages/tesslate-agent/docs/DOCS.md](../../packages/tesslate-agent/docs/DOCS.md)
- Real-time agent architecture (ARQ, pub/sub, WebSocket): [real-time-agent-architecture.md](./real-time-agent-architecture.md)
- Environment variables reference: [environment-variables.md](./environment-variables.md)
