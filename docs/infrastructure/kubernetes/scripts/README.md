# k8s/scripts

Shell helpers for deploying, testing, and managing OpenSail on Kubernetes. Grouped by purpose.

## Deployment (`k8s/scripts/deployment/`)

| Script | Purpose |
|--------|---------|
| `install-prerequisites.sh` | Installs kubectl, kustomize, helm, and other CLI deps on a deployer host. |
| `setup-registry-auth.sh` | Configures ECR / DOCR / GCR login for the local docker daemon. |
| `build-push-images.sh` | Multi-image `docker buildx build --platform linux/amd64 --push` loop. ECR registry target. |
| `configure-domain.sh` | Writes the APP_DOMAIN + Cloudflare DNS records for a new environment. |
| `validate-manifests.sh` | Runs `kubectl kustomize` + `kubeval` against every overlay to catch syntax errors before apply. |
| `deploy-application.sh` | Applies the platform overlay (`tesslate` namespace workloads). |
| `deploy-user-namespace.sh` | Deploys / re-deploys a single `proj-{uuid}` namespace. |
| `deploy-k8s-file-persistence.sh` | Installs the storage stack (CSI driver, Volume Hub, storage classes). |
| `deploy-all.sh` | Runs prerequisites, registry auth, builds, validate, deploy-application, deploy-k8s-file-persistence. |
| `verify-deployment.sh` | Post-deploy smoke tests: pod readiness, ingress reachable, backend `/api/health`. |
| `cleanup.sh` | Tears down a test deployment (namespaces, PVCs, secrets). |

## Local deployment (`k8s/scripts/local-deployment/`)

Bare-metal / single-host k3s helpers for on-prem installs.

| Script | Purpose |
|--------|---------|
| `prepare-server.sh` | OS-level prep: kernel modules, swap off, firewall, users. |
| `install-kubernetes.sh` | Installs upstream kubelet/kubeadm. |
| `configure-cluster.sh` | Initialises the cluster and installs CNI. |
| `setup-all.sh` | Runs the three above in order. |
| `k3s-setup-all.sh` | Same, but provisioning with k3s instead of kubeadm. |
| `deploy-tesslate-k3s.sh` | Deploys OpenSail onto the freshly set up k3s cluster. |
| `deploy-tesslate.sh` | Deploys OpenSail onto a generic cluster (kubeadm or managed). |
| `manage-tesslate.sh` | Day-two ops wrapper: status, logs, restart, backup. |
| `build-images.sh` | Local image build (no registry push). |

## Minikube (`k8s/scripts/minikube/`)

| Script | Purpose |
|--------|---------|
| `setup.sh` | Starts minikube with the expected profile (`tesslate`), enables ingress + metrics-server, preloads images, applies the overlay. |
| `teardown.sh` | `minikube -p tesslate delete` and cleans associated docker volumes. |
| `test-pod-affinity.sh` | Smoke test: create two volumes with a preferred node, verify co-location. |
| `test-s3-sandwich.sh` | Exercises the hibernation + restore loop end-to-end on minikube. |

## Testing (`k8s/scripts/testing/`)

| Script | Purpose |
|--------|---------|
| `test-k8s-resources.sh` | Checks every expected ClusterRole / ServiceAccount / ResourceQuota exists and is bound correctly. |
| `test-security.sh` | Runs NetworkPolicy probes: frontend can reach backend, user namespaces cannot reach `tesslate`, IMDS is blocked. |

## Conventions

- Every script must use `kubectl --context=<name>` explicitly. Context switching is BANNED (see `docs/infrastructure/kubernetes/CLAUDE.md`).
- AWS scripts funnel through `./scripts/aws-deploy.sh` at the repo root, which delegates here.
- Scripts exit non-zero on first error (`set -euo pipefail`).
