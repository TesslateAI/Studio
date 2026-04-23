# AWS EKS Deployment

This guide walks you through deploying OpenSail to AWS EKS for production. It covers the shared platform stack, the per-environment stack (beta or production), image builds, secrets, DNS, TLS, seeding, scaling, observability, and rollbacks.

Everything here targets the two production-class environments:

| Environment | Cluster name | kubectl context | Domain (example) |
|---|---|---|---|
| Beta | `tesslate-beta-eks` | `tesslate-beta-eks` | `your-domain.com` |
| Production | `tesslate-production-eks` | `tesslate-production-eks` | `opensail.tesslate.com` |

ECR account: **<AWS_ACCOUNT_ID>** in `us-east-1`. Every `kubectl` example below includes `--context=tesslate-production-eks` or `--context=tesslate-beta-eks`. Never switch contexts with `kubectl config use-context` or `kctx`; cronjobs and other processes can flip your active context mid-session.

For agent internals, see [packages/tesslate-agent/docs/DOCS.md](../../packages/tesslate-agent/docs/DOCS.md). For cluster access roles and onboarding, see [eks-cluster-access.md](eks-cluster-access.md).

## 1. What you will deploy

Each per-environment stack provisions:

- **VPC** (`10.0.0.0/16` by default) with three public and three private subnets across three AZs, NAT gateway, internet gateway.
- **EKS cluster** at Kubernetes `1.35` with managed node groups (on-demand and spot) plus OIDC provider for IRSA.
- **S3 bucket** for project hibernation and content-addressable storage (CAS), encrypted at rest.
- **IAM roles (IRSA)** for the backend service account (S3 access), EBS CSI driver, cluster-autoscaler, external-dns, cert-manager, and the `eks-deployer` admin role.
- **NGINX Ingress Controller** fronted by an AWS Network Load Balancer.
- **cert-manager** with a Cloudflare DNS01 ClusterIssuer for wildcard TLS (Let's Encrypt).
- **external-dns** that reconciles Cloudflare DNS records from Ingress annotations.
- **Cloudflare DNS records** for apex and wildcard (`*.domain`) pointing at the NLB.
- **btrfs CSI driver + Volume Hub** (`services/btrfs-csi/`) in `kube-system` for per-project subvolume storage with S3/CAS sync.
- **LiteLLM** deployment (self-hosted model proxy) with optional RDS backend.
- **Application workloads** in the `tesslate` namespace: backend, frontend, worker, Redis, Postgres (or external RDS), cleanup CronJobs.

The **shared stack** (`k8s/terraform/shared/`) provisions resources used by all environments: ECR repositories, a small `tesslate-platform-eks` cluster for internal tools (Headscale VPN, etc.), and platform-level NGINX Ingress + cert-manager + Cloudflare DNS.

## 2. Prerequisites

| Tool | Version | Notes |
|---|---|---|
| AWS CLI | v2 | `aws sts get-caller-identity` must succeed |
| Terraform | >= 1.5 | Provider pinning handled in `main.tf` |
| kubectl | matches EKS 1.35 | Installed locally |
| Helm | v3 | For cert-manager / ingress Helm charts if applying manually |
| Docker | latest with buildx | Needed for `linux/amd64` builds |
| Cloudflare | API token | Permissions: `Zone:DNS:Edit`, `Zone:Zone:Read` on your zone |

IAM requirements:

- An AWS account with the ability to create VPC, EKS, IAM, S3, and ECR resources.
- An IAM user (for example `<AWS_IAM_USER>`) listed in `eks_admin_iam_arns` for the target environment. See [eks-cluster-access.md](eks-cluster-access.md) for adding team members to `team-observer`, `team-deployer`, `team-debugger`, or `team-admin` roles.
- AWS Secrets Manager access to `tesslate/terraform/{production,beta,shared}` for pulling tfvars.

Windows / MSYS note: prefix `kubectl` or `docker exec` commands with `MSYS_NO_PATHCONV=1` to stop Git Bash from rewriting paths.

## 3. First-time provision order

Always apply the shared stack first. The per-environment stack references ECR image URLs built in the shared stack via computed locals (`local.ecr_*_url` in `k8s/terraform/aws/ecr.tf`), so without ECR the image pulls fail.

```bash
# 1. Download tfvars for the shared stack
./scripts/terraform/secrets.sh download shared

# 2. Apply the shared stack (ECR, platform EKS, platform ingress, Headscale)
./scripts/aws-deploy.sh init shared
./scripts/aws-deploy.sh plan shared
./scripts/aws-deploy.sh apply shared

# 3. Apply your per-environment stack (beta first is a good idea)
./scripts/terraform/secrets.sh download beta
./scripts/aws-deploy.sh terraform beta    # init + plan + apply

# 4. Apply production
./scripts/terraform/secrets.sh download production
./scripts/aws-deploy.sh terraform production
```

Each per-environment `terraform apply` takes 15 to 20 minutes on the first run. Subsequent applies that only touch secrets or Helm charts complete in under two minutes.

## 4. Environments: beta vs production

The two environments are fully isolated: separate VPCs, separate EKS clusters, separate state files, and separate tfvars stored in AWS Secrets Manager.

| Item | Beta | Production |
|---|---|---|
| Terraform state key | `beta/terraform.tfstate` | `production/terraform.tfstate` |
| Backend config | `backend-beta.hcl` | `backend-production.hcl` |
| tfvars file | `terraform.beta.tfvars` | `terraform.production.tfvars` |
| Secret in Secrets Manager | `tesslate/terraform/beta` | `tesslate/terraform/production` |
| Kustomize overlay | `k8s/overlays/aws-beta/` | `k8s/overlays/aws-production/` |
| ECR tag convention | `:beta` | `:production` |
| kubectl context | `tesslate-beta-eks` | `tesslate-production-eks` |

The `aws-deploy.sh` helper auto-detects backend drift: if your local `.terraform/terraform.tfstate` points at the wrong environment, it reinitializes with the correct backend HCL before running plan or apply.

## 5. Secrets management

Three Kubernetes secrets in the `tesslate` namespace are fully terraform-managed from `k8s/terraform/aws/kubernetes.tf`:

- `tesslate-app-secrets`: app-level config (`APP_DOMAIN`, `LITELLM_MASTER_KEY`, OAuth client secrets, Stripe keys, SMTP, PostHog, etc.).
- `postgres-secret`: Postgres credentials.
- `s3-credentials`: S3 bucket config (the backend pod uses IRSA for auth, so no static AWS keys land in the secret).

The backend, frontend, and worker Deployments mount these via `envFrom`. This is the auto-sync half of the pattern: **every key added to a terraform-managed secret is available as a pod env var on the next rollout, with no kustomize edit required**.

The other half is explicit `env` entries in `k8s/overlays/aws-base/backend-patch.yaml`. Those entries live under a `$patch: replace` directive so the base manifest's env array is wiped and only static values plus one alias (`K8S_INGRESS_DOMAIN -> APP_DOMAIN`) remain.

Decision rule:

- Secret-managed value (domain, API key, OAuth client secret, Stripe key, SMTP password, etc.): add to terraform's `kubernetes.tf` secret. It flows into the pod automatically.
- Static config (feature flag, class name, pod affinity toggle, replica count patch): add to the overlay in `k8s/overlays/aws-base/backend-patch.yaml` or an environment-specific `env-patch.yaml`.

To rotate a secret:

```bash
./scripts/terraform/secrets.sh download production
# edit k8s/terraform/aws/terraform.production.tfvars
./scripts/aws-deploy.sh plan production
./scripts/aws-deploy.sh apply production
./scripts/terraform/secrets.sh upload production
./scripts/aws-deploy.sh reload production backend worker
```

The `reload` step rolls pods to pick up the new secret values.

## 6. EKS access

Regular humans assume one of the team roles (`team-observer`, `team-deployer`, `team-debugger`, `team-admin`). Terraform, CI, and a small list of named admins (`<AWS_IAM_USER>`, `tesslate-bigboss`) assume the `eks-deployer` role.

One-time kubectl setup after access is granted:

```bash
# Configure kubectl for both environments with explicit role assumption
aws eks update-kubeconfig \
  --region us-east-1 \
  --name tesslate-production-eks \
  --alias tesslate-production-eks \
  --role-arn arn:aws:iam::<AWS_ACCOUNT_ID>:role/tesslate-production-eks-eks-deployer

aws eks update-kubeconfig \
  --region us-east-1 \
  --name tesslate-beta-eks \
  --alias tesslate-beta-eks \
  --role-arn arn:aws:iam::<AWS_ACCOUNT_ID>:role/tesslate-beta-eks-eks-deployer

# Verify
kubectl --context=tesslate-production-eks get nodes
kubectl --context=tesslate-beta-eks get nodes
```

`aws-deploy.sh` invokes `aws eks update-kubeconfig` under the hood with the right `--role-arn` every time it touches a cluster, so you do not need to rerun the command above for its subcommands.

Team members who are not in `eks_admin_iam_arns` should use named AWS CLI profiles with `role_arn` entries for the team role they need. Full onboarding and AWS profile examples live in [eks-cluster-access.md](eks-cluster-access.md).

## 7. Build and push images

Six images live in ECR under account `<AWS_ACCOUNT_ID>` in `us-east-1`:

| Repository | Dockerfile | Purpose |
|---|---|---|
| `tesslate-backend` | `orchestrator/Dockerfile` | FastAPI + ARQ worker |
| `tesslate-frontend` | `app/Dockerfile.prod` | React + Vite SPA behind NGINX |
| `tesslate-devserver` | `orchestrator/Dockerfile.devserver` | User project container base |
| `tesslate-ast` | `services/ast/Dockerfile` | AST parser sidecar of the backend pod |
| `tesslate-btrfs-csi` | `services/btrfs-csi/Dockerfile` | CSI driver + Volume Hub |
| `tesslate-markitdown`, `tesslate-deerflow` | `seeds/apps/.../Dockerfile` | Seeded Tesslate Apps, mirrored for in-cluster pull |

Tag convention: `:production` or `:beta` for first-class images; `:latest` for seeded app images (they are content fixtures, not per-env). The `build` subcommand of `aws-deploy.sh` wires all of this up and always targets `linux/amd64` so Apple Silicon builds still run on amd64 EKS nodes.

```bash
# Build, push, apply manifests, and roll the relevant Deployments for all core images
./scripts/aws-deploy.sh build production

# Build a single image (faster; still applies manifests and rolls its Deployment)
./scripts/aws-deploy.sh build production backend
./scripts/aws-deploy.sh build beta frontend

# Build multiple explicit images in parallel
./scripts/aws-deploy.sh build beta backend frontend worker

# Reuse the Docker build cache (the default is --no-cache)
./scripts/aws-deploy.sh build beta backend --cached

# Build the Volume Hub and CSI driver; rolls kube-system daemonset and Deployment
./scripts/aws-deploy.sh build production compute
```

`build` performs these steps:

1. Sync git submodules (the agent runner in `packages/tesslate-agent` is COPY'd into the backend image).
2. `aws ecr get-login-password | docker login` against `<ECR_REGISTRY>`.
3. `docker buildx build --platform linux/amd64 --push` in parallel across selected images.
4. `aws eks update-kubeconfig` with the `eks-deployer` role for the target environment.
5. `kubectl apply -k k8s/overlays/aws-{env}` to pick up any manifest updates.
6. Rolling restart of the impacted Deployments plus a parallel `kubectl rollout status --timeout=300s`.
7. If the backend was rebuilt, `python -m scripts.seed_apps` runs inside the backend pod to upsert the Tesslate Apps registry.

If you prefer manual image management, the raw commands look like this:

```bash
aws ecr get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin <ECR_REGISTRY>

docker buildx build --platform linux/amd64 --no-cache \
  -t <ECR_REGISTRY>/tesslate-backend:production \
  -f orchestrator/Dockerfile . --push
```

See [image-update-workflow.md](image-update-workflow.md) for the full tag strategy, cache management, and multi-image release choreography.

## 8. Deploy

After images are in ECR, apply Kubernetes manifests for the environment:

```bash
# One-shot apply + status wait via the helper
./scripts/aws-deploy.sh deploy-k8s production

# Apply compute layer (btrfs CSI + Volume Hub) independently
./scripts/aws-deploy.sh deploy-compute production

# Or apply directly with kubectl
kubectl apply -k k8s/overlays/aws-production --context=tesslate-production-eks
kubectl rollout status deployment/tesslate-backend  -n tesslate --context=tesslate-production-eks --timeout=300s
kubectl rollout status deployment/tesslate-frontend -n tesslate --context=tesslate-production-eks --timeout=300s
kubectl rollout status deployment/tesslate-worker   -n tesslate --context=tesslate-production-eks --timeout=300s
```

For targeted restarts after a config change:

```bash
./scripts/aws-deploy.sh reload production                  # applies manifests, rolls backend/frontend/worker
./scripts/aws-deploy.sh reload production backend worker   # rolls only those two
./scripts/aws-deploy.sh reload production litellm          # syncs LiteLLM ConfigMap and rolls LiteLLM
./scripts/aws-deploy.sh reload production volume-hub       # rolls Volume Hub in kube-system
```

## 9. Verify

```bash
# Cluster is reachable and nodes are Ready
kubectl --context=tesslate-production-eks get nodes

# Core pods Ready
kubectl --context=tesslate-production-eks get pods -n tesslate -o wide

# CSI driver and Volume Hub
kubectl --context=tesslate-production-eks get pods -n kube-system \
  -l 'app in (tesslate-btrfs-csi-node,tesslate-volume-hub)'

# Ingress exposed through the NLB
kubectl --context=tesslate-production-eks get ingress -A

# NLB DNS target (useful when configuring Cloudflare manually)
kubectl --context=tesslate-production-eks get svc -n ingress-nginx ingress-nginx-controller \
  -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'

# Health probe through the public URL
curl -sI https://opensail.tesslate.com/api/health
```

Log in through the browser against `https://<your-domain>/` and confirm the dashboard loads and you can create a project.

## 10. DNS and TLS

DNS and certificates are fully managed by terraform and in-cluster controllers:

- **Cloudflare DNS records** (`dns.tf`) create CNAMEs for the apex domain and `*.domain` pointing at the NLB hostname, proxied through Cloudflare.
- **external-dns** reconciles additional records from Ingress annotations (per-project subdomains when users deploy preview projects).
- **cert-manager** runs a `ClusterIssuer` that uses the Cloudflare API token for DNS01 challenges. It mints a wildcard Let's Encrypt certificate stored in the `tesslate-wildcard-tls` Secret, referenced by all Ingress resources through `K8S_WILDCARD_TLS_SECRET`.
- **Cloudflare SSL mode** should be `Full (strict)` so browser to edge and edge to NLB are both encrypted.

Check certificate state:

```bash
kubectl --context=tesslate-production-eks get certificate -n tesslate
kubectl --context=tesslate-production-eks describe certificate tesslate-wildcard-tls -n tesslate
kubectl --context=tesslate-production-eks logs -n cert-manager deploy/cert-manager --tail=100
```

The first issuance takes two to five minutes. If `Ready=False` for longer than ten minutes, check `kubectl describe certificaterequest` and cert-manager logs for Cloudflare API errors.

Important: the frontend's `api-url` in the `frontend-config` ConfigMap (managed in terraform's `kubernetes.tf`) must be the base domain only, for example `https://opensail.tesslate.com`. `app/src/lib/api.ts` already prefixes `/api` to every path; putting `/api` in the base URL causes double `/api/api/` paths and universal 404s.

## 11. Seed the production database

Run this once after the initial terraform apply, not on every deploy. The seeds are upserted by slug, so running twice is safe but wastes several minutes.

```bash
CTX=tesslate-production-eks

# Marketplace base templates (Next.js, FastAPI, etc.)
kubectl --context=$CTX exec -n tesslate deploy/tesslate-backend -- \
  python -m scripts.seeds.seed_marketplace_bases

# Marketplace agents (official + community)
kubectl --context=$CTX exec -n tesslate deploy/tesslate-backend -- \
  python -m scripts.seeds.seed_marketplace_agents
kubectl --context=$CTX exec -n tesslate deploy/tesslate-backend -- \
  python -m scripts.seeds.seed_opensource_agents

# Skills, MCP servers, themes
kubectl --context=$CTX exec -n tesslate deploy/tesslate-backend -- \
  python -m scripts.seeds.seed_skills
kubectl --context=$CTX exec -n tesslate deploy/tesslate-backend -- \
  python -m scripts.seeds.seed_mcp_servers
kubectl --context=$CTX exec -n tesslate deploy/tesslate-backend -- \
  python -m scripts.seeds.seed_themes

# Tesslate Apps registry (the build subcommand already does this if backend was rebuilt)
kubectl --context=$CTX exec -n tesslate deploy/tesslate-backend -- \
  python -m scripts.seed_apps
```

See [database-migrations.md](database-migrations.md) for schema migrations. Run migrations before seeds on every version bump.

## 12. Scaling

Three independent layers:

- **Pod replicas**: `k8s/overlays/aws-production/replicas-patch.yaml` sets backend, frontend, worker, and ingress controller replica counts. For hotfix scale-up, `kubectl --context=tesslate-production-eks scale deploy/tesslate-backend -n tesslate --replicas=4`.
- **HPA**: the metrics-server addon is enabled by `enable_metrics_server = true`, so you can add an `HorizontalPodAutoscaler` per Deployment.
- **Cluster autoscaler**: installed by terraform (`enable_cluster_autoscaler = true`) with IRSA. The on-demand node group scales between `eks_node_min_size` and `eks_node_max_size` in tfvars; the spot node group scales up to `eks_spot_max_size`. User project workloads prefer the spot node group.

To add a dedicated node group (GPU, memory-optimized, etc.), set `additional_node_groups` in tfvars and apply. The schema is in `variables.tf`.

The worker Deployment defaults to a single replica because in-memory task state is still partially colocated with the process; scale it cautiously and watch Redis queue depth via the worker logs.

## 13. Observability

- **Control plane logs**: CloudWatch log group `/aws/eks/tesslate-{env}-eks/cluster`.
  ```bash
  aws logs tail /aws/eks/tesslate-production-eks/cluster --since 15m
  ```
- **Workload logs**: `kubectl --context=tesslate-production-eks logs -n tesslate deploy/tesslate-backend -f`.
- **OTEL collector + structured logging**: see [enterprise-observability.md](enterprise-observability.md) for deploying the OpenTelemetry Collector, wiring exporters, and enabling the audit log stream.
- **Metrics**: `kubectl --context=tesslate-production-eks top pods -n tesslate` and `kubectl top nodes`. For historical data, install `kube-prometheus-stack` via Helm or route metrics from the OTEL Collector to CloudWatch.

## 14. Updates and migrations

The happy path for a release:

1. Merge to `main`.
2. Trigger the `Deploy Production` workflow (`.github/workflows/deploy-production.yml`) in GitHub Actions. It downloads `tesslate/terraform/production` from Secrets Manager, runs `terraform plan -detailed-exitcode`, applies, runs `./scripts/aws-deploy.sh deploy-k8s production`, and then `./scripts/aws-deploy.sh build production`.
3. Or manually: `./scripts/aws-deploy.sh build production` from your workstation.
4. If schema changed, run migrations before the pods rolling-restart finishes: `kubectl --context=tesslate-production-eks exec -n tesslate deploy/tesslate-backend -- alembic upgrade head`.

Pods roll one at a time on `rollout restart` so the Deployment is always serving traffic. For a hard cutover or a very large schema migration, drain traffic first using the procedure in [safe-shutdown-procedure.md](safe-shutdown-procedure.md).

See [image-update-workflow.md](image-update-workflow.md) for the full tag strategy and when to rebuild each image.

## 15. Rollback and safe shutdown

Rollback a single Deployment:

```bash
kubectl --context=tesslate-production-eks rollout history deploy/tesslate-backend -n tesslate
kubectl --context=tesslate-production-eks rollout undo deploy/tesslate-backend -n tesslate
kubectl --context=tesslate-production-eks rollout status deploy/tesslate-backend -n tesslate --timeout=300s
```

Rollback a bad image tag: repush the previous known-good digest as `:production` or bump the `newTag` in `k8s/overlays/aws-production/kustomization.yaml` to a specific SHA and `kubectl apply -k`.

For planned downtime, maintenance windows, draining user pods cleanly, or pausing the task queue before a risky migration, follow [safe-shutdown-procedure.md](safe-shutdown-procedure.md).

## 16. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `AccessDenied: eks:DescribeCluster` | Your IAM user is not in a team group or `eks_admin_iam_arns` | Assume a team role (Option A/B in [eks-cluster-access.md](eks-cluster-access.md)) |
| `error: You must be logged in to the server (Unauthorized)` | kubeconfig was written without `--role-arn` | Re-run `aws eks update-kubeconfig` with `--role-arn` while the assumed role is active |
| `ErrImagePull` / `unauthorized` on a `tesslate-*` image | ECR login expired or wrong region / account | `aws ecr get-login-password --region us-east-1 \| docker login --username AWS --password-stdin <ECR_REGISTRY>`, then retry `build` |
| `no match for platform in manifest` on pod startup | Image was built on arm64 | Rebuild with `docker buildx build --platform linux/amd64` (the `build` subcommand does this by default) |
| Ingress returns 503 | Backend pod not Ready, or ingress-controller cache stale after a backend restart | Check `kubectl get pods -n tesslate` and `kubectl rollout restart deploy/ingress-nginx-controller -n ingress-nginx --context=tesslate-production-eks` |
| Certificate stuck `Ready=False` | Cloudflare API token missing DNS edit permission, or wrong zone | Check cert-manager logs; verify the token has `Zone:Zone:Read` and `Zone:DNS:Edit` on the correct zone |
| Frontend calls go to `/api/api/...` | `api-url` ConfigMap includes `/api` | Set `frontend_api_url = "https://opensail.tesslate.com"` in tfvars (no `/api`) and reapply |
| Backend pod `CrashLoopBackOff` immediately | Secret rotation broke a required key, or `tesslate-app-secrets` missing a key consumed via `envFrom` | `kubectl describe pod` and `kubectl logs --previous`; check `kubernetes.tf` secret contents |
| `No module named 'tesslate_agent'` in backend | Git submodule not initialized before `docker build` | `git submodule update --init --recursive`, rebuild (the `build` script handles this automatically) |
| Volume Hub pods stuck in Terminating | CSI DaemonSet rolled at the same time as Hub | Wait for `tesslate-btrfs-csi-node` rollout to stabilize; the `build compute` and `reload volume-hub` subcommands sequence these correctly |
| Orphaned `proj-*` namespaces | Project was deleted before its namespace drained | `kubectl get ns \| grep proj-` then `kubectl delete ns proj-<uuid> --context=tesslate-production-eks` |
| `terraform apply` times out on Helm resources | cert-manager or external-dns is pending due to DNS issues | Apply with `-target=module.eks` first, then re-run full apply once cluster is Ready |
| `Backend mismatch!` on `plan` | Local `.terraform/` points at a different environment | `aws-deploy.sh` reinitializes automatically; if it fails, `rm -rf k8s/terraform/aws/.terraform && ./scripts/aws-deploy.sh init {env}` |

For anything not covered here, load `docs/infrastructure/kubernetes/CLAUDE.md` for broader K8s context, `docs/orchestrator/services/pubsub.md` for Redis and worker issues, and [enterprise-observability.md](enterprise-observability.md) for tracing and log aggregation.
