# OpenSail Environment Variable Reference

Comprehensive reference for every environment variable consumed by OpenSail. Variables are grouped by category. Sources:

- Repo-root `.env.example` (dev / Docker Compose)
- Repo-root `.env.prod.example` (production Docker Compose)
- `orchestrator/app/config.py` (backend settings, the canonical reader)
- `orchestrator/app/config_features.py` (feature flags)
- Frontend `config.ts` (reads `VITE_*` at build time, `window._env_.*` at runtime)
- Kustomize overlays under `k8s/overlays/*` (sets runtime values per environment)

In every "Read by" cell below, `config.py` means `orchestrator/app/config.py`.

## Quick conventions

| Convention | Meaning |
|------------|---------|
| `TSL_FEATURE_*` | Boolean feature flag consumed by `config_features.py` |
| `K8S_*` | Kubernetes deployment mode settings |
| `VITE_*` | Build-time frontend env (reads from `.env` files via Vite) |
| `window._env_.*` | Runtime frontend env (set by K8s ConfigMap or Docker entrypoint) |
| `STRIPE_*` | Stripe keys and price IDs |
| `SMTP_*` | Email transport |
| `LITELLM_*` | AI gateway |
| `S3_*` | Object storage (projects, CAS) |

## Required core

| Variable | Purpose | Read by |
|----------|---------|---------|
| `SECRET_KEY` | JWT signing + general crypto fallback | `config.py` |
| `INTERNAL_API_SECRET` | Shared secret for cluster-internal callers (Hub GC, btrfs CSI) hitting `/api/internal/*`. Desktop mode ignores. | `config.py` |
| `DEPLOYMENT_MODE` | `docker`, `kubernetes`, or `desktop`. Selects orchestrator backend, DB driver, queue, pub/sub. | `config.py`, factory modules |
| `DATABASE_URL` | SQLAlchemy async URL. Docker default points at the `postgres` service. Desktop uses SQLite. | `config.py` |

## Database (Postgres)

| Variable | Purpose |
|----------|---------|
| `POSTGRES_DB` | Database name |
| `POSTGRES_USER` | DB user |
| `POSTGRES_PASSWORD` | DB password |
| `POSTGRES_PORT` | Host port (compose dev default 5432) |

Tests use `docker-compose.test.yml` with a fixed `tesslate_test / tesslate_test / testpass` on port 5433.

## Redis / pub-sub / task queue

| Variable | Purpose |
|----------|---------|
| `REDIS_URL` | ARQ + RedisPubSub connection. Empty string falls back to in-memory (single-process dev only). |
| `WORKER_MAX_JOBS` | Concurrent agent tasks per ARQ worker pod (default 10) |
| `WORKER_JOB_TIMEOUT` | Task timeout seconds (default 600) |

Desktop uses `LocalTaskQueue` (asyncio + apscheduler) and `LocalPubSub` instead; no Redis vars required.

## LiteLLM / AI gateway

| Variable | Purpose |
|----------|---------|
| `LITELLM_API_BASE` | Proxy URL (e.g. `https://your-litellm.example.com/v1`) |
| `LITELLM_MASTER_KEY` | Master key for creating per-user virtual keys |
| `LITELLM_DEFAULT_MODELS` | Comma-separated model list granted to new users |
| `LITELLM_TEAM_ID` | LiteLLM team / access group |
| `LITELLM_EMAIL_DOMAIN` | Internal email domain stamped into LiteLLM users |
| `LITELLM_INITIAL_BUDGET` | Starting budget (USD) per user |
| `COMPACTION_SUMMARY_MODEL` | Cheap model for context compaction |
| `DEFAULT_THINKING_EFFORT` | Extended thinking effort for supported models |

## Agent limits

| Variable | Purpose |
|----------|---------|
| `AGENT_MAX_COST` | Global cost cap across all runs (USD, default 20.0) |
| `AGENT_MAX_ITERATIONS` | Global iteration cap (0 = unlimited) |
| `AGENT_MAX_COST_PER_RUN` | Per-run cap (USD, default 5.0) |

## Container cleanup (Docker mode)

| Variable | Purpose |
|----------|---------|
| `CONTAINER_CLEANUP_INTERVAL_MINUTES` | How often the reaper runs (default 2) |
| `CONTAINER_CLEANUP_TIER1_IDLE_MINUTES` | Pause idle containers after N minutes (default 15) |
| `CONTAINER_CLEANUP_TIER2_PAUSED_HOURS` | Remove paused containers after N hours (default 24) |

## Logging

| Variable | Purpose |
|----------|---------|
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` (default INFO) |

## JWT / auth tokens

| Variable | Purpose |
|----------|---------|
| `ALGORITHM` | JWT algorithm (default HS256) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Access token TTL (default 30) |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Refresh token TTL (default 14) |

## Frontend (build + runtime)

| Variable | Purpose | Mode |
|----------|---------|------|
| `VITE_API_URL` | API base URL (empty for Vite proxy, or `http://localhost:8000`) | Dev build |
| `VITE_ALLOWED_HOSTS` | Comma-separated host allowlist for Vite dev server | Dev build |
| `VITE_PUBLIC_POSTHOG_KEY` | PostHog project key | Dev build |
| `VITE_PUBLIC_POSTHOG_HOST` | PostHog host (default `https://app.posthog.com`) | Dev build |
| `window._env_.API_URL` | Runtime API base. Must NOT include `/api` (frontend code prepends it) | Prod |
| `window._env_.POSTHOG_KEY`, `window._env_.POSTHOG_HOST` | Runtime PostHog config | Prod |

## Domain and port

| Variable | Purpose |
|----------|---------|
| `APP_DOMAIN` | Apex domain (no protocol). Used for routing, OAuth redirects, project subdomains, CORS wildcard |
| `APP_PROTOCOL` | `http` or `https` |
| `APP_PORT` / `APP_SECURE_PORT` | Public HTTP / HTTPS ports |
| `TRAEFIK_DASHBOARD_PORT` | Traefik dashboard port (dev) |
| `BACKEND_PORT` | Uvicorn port |
| `FRONTEND_PORT` | Vite dev port |
| `APP_BASE_URL` | Full base URL (constructed from protocol + domain unless overridden) |
| `DEV_SERVER_BASE_URL` | Dev container preview base (K8s only) |
| `TRAEFIK_ADDITIONAL_HOST_RULE` | Extra hostnames in Traefik routing rules |
| `CHOKIDAR_USEPOLLING`, `CHOKIDAR_INTERVAL`, `WATCHPACK_POLLING` | Docker volume polling for hot reload on Windows / macOS |

## CORS / cookies / CSRF

| Variable | Purpose |
|----------|---------|
| `CORS_ORIGINS` | Comma-separated allowed origins |
| `ALLOWED_HOSTS` | Host header allowlist |
| `COOKIE_SECURE` | `true` in production (HTTPS required) |
| `COOKIE_SAMESITE` | `lax`, `strict`, `none` |
| `COOKIE_DOMAIN` | Scope cookies to apex (e.g. `.tesslate.com`) for subdomain access |
| `CSRF_SECRET_KEY` | Separate key for CSRF tokens (falls back to `SECRET_KEY`) |
| `CSRF_TOKEN_MAX_AGE` | CSRF token TTL seconds (default 86400) |

## Traefik (Docker mode)

| Variable | Purpose |
|----------|---------|
| `TRAEFIK_BASIC_AUTH` | `htpasswd`-format admin credential for dashboard |
| `TRAEFIK_CERT_RESOLVER` | `letsencrypt` (dev) or `cloudflare` (prod, wildcard) |
| `CF_DNS_API_TOKEN` | Cloudflare API token for DNS challenge (prod) |

## OAuth providers (login)

All optional; absence disables the provider gracefully.

| Variable | Provider |
|----------|----------|
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI` | Google |
| `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `GITHUB_OAUTH_REDIRECT_URI` | GitHub |

## OAuth providers (deployment targets)

| Variable | Provider |
|----------|----------|
| `VERCEL_CLIENT_ID`, `VERCEL_CLIENT_SECRET`, `VERCEL_OAUTH_REDIRECT_URI` | Vercel |
| `NETLIFY_CLIENT_ID`, `NETLIFY_CLIENT_SECRET`, `NETLIFY_OAUTH_REDIRECT_URI` | Netlify |
| `HEROKU_CLIENT_ID`, `HEROKU_CLIENT_SECRET`, `HEROKU_OAUTH_REDIRECT_URI` | Heroku |
| `DIGITALOCEAN_CLIENT_ID`, `DIGITALOCEAN_CLIENT_SECRET`, `DIGITALOCEAN_OAUTH_REDIRECT_URI` | DigitalOcean |

## OAuth providers (MCP `platform_app`)

Used when an MCP server does not advertise RFC 7591 DCR.

| Variable | Provider |
|----------|----------|
| `MCP_OAUTH_APP_GITHUB_CLIENT_ID`, `MCP_OAUTH_APP_GITHUB_CLIENT_SECRET` | GitHub Copilot MCP |
| `MCP_OAUTH_APP_SLACK_CLIENT_ID`, `MCP_OAUTH_APP_SLACK_CLIENT_SECRET` | Slack MCP |

## Deployments (multi-provider)

| Variable | Purpose |
|----------|---------|
| `DEPLOYMENT_ENCRYPTION_KEY` | Base64 Fernet key for encrypting provider credentials (falls back to derived from `SECRET_KEY`) |
| `DEPLOYMENT_TIMEOUT` | Deploy operation timeout seconds (default 600) |
| `DEPLOYMENT_BUILD_DIR` | Default build output dir (default `dist`) |
| `CLOUDFLARE_API_BASE`, `VERCEL_API_BASE`, `NETLIFY_API_BASE` | Override provider API base URLs |
| `CONTAINER_PUSH_TIMEOUT` | Kaniko push timeout (default 900s) |
| `KANIKO_IMAGE` | Kaniko executor image |
| `CONTAINER_PUSH_DEFAULT_CPU`, `CONTAINER_PUSH_DEFAULT_MEMORY` | Kaniko resource requests |

## Stripe / billing

| Variable | Purpose |
|----------|---------|
| `STRIPE_SECRET_KEY` | Secret API key (`sk_test_*` or `sk_live_*`) |
| `STRIPE_PUBLISHABLE_KEY` | Publishable key |
| `STRIPE_WEBHOOK_SECRET` | Webhook signing secret |
| `STRIPE_CONNECT_CLIENT_ID` | Stripe Connect client ID (creator payouts) |
| `STRIPE_BASIC_PRICE_ID`, `STRIPE_PRO_PRICE_ID`, `STRIPE_ULTRA_PRICE_ID` | Monthly subscription prices |
| `STRIPE_BASIC_ANNUAL_PRICE_ID`, `STRIPE_PRO_ANNUAL_PRICE_ID`, `STRIPE_ULTRA_ANNUAL_PRICE_ID` | Annual subscription prices |
| `STRIPE_PREMIUM_PRICE_ID` | Legacy single-tier premium price (prod example) |
| `CREDIT_PACKAGE_SMALL`, `CREDIT_PACKAGE_MEDIUM`, `CREDIT_PACKAGE_LARGE`, `CREDIT_PACKAGE_TEAM` | One-time credit purchase prices in cents |
| `ADDITIONAL_DEPLOY_PRICE` | Per-slot deploy upcharge in cents |
| `PREMIUM_SUBSCRIPTION_PRICE` | Legacy flat premium price in cents (prod example) |
| `FREE_MAX_PROJECTS`, `PREMIUM_MAX_PROJECTS` | Legacy per-tier project caps (prod example) |
| `SIGNUP_BONUS_CREDITS`, `SIGNUP_BONUS_EXPIRY_DAYS` | Signup bonus pool |
| `CREATOR_REVENUE_SHARE`, `PLATFORM_REVENUE_SHARE` | Revenue split decimals (must sum to 1) |
| `USAGE_INVOICE_DAY` | Day of month (1..28) to generate usage invoices |

## SMTP / 2FA

| Variable | Purpose |
|----------|---------|
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_USE_TLS`, `SMTP_SENDER_EMAIL` | SMTP transport for magic links and 2FA codes |
| `TWO_FA_ENABLED` | Require 6-digit email 2FA after password login (default false) |

## Analytics

| Variable | Purpose |
|----------|---------|
| `VITE_PUBLIC_POSTHOG_KEY`, `VITE_PUBLIC_POSTHOG_HOST` | PostHog project (empty to disable) |

## Kubernetes (user-project runtime)

| Variable | Purpose |
|----------|---------|
| `K8S_DEVSERVER_IMAGE` | Image for user containers. Minikube uses `tesslate-devserver:latest`; prod uses the ECR URL (`<ECR_REGISTRY>/tesslate-devserver:latest`). |
| `K8S_IMAGE_PULL_SECRET` | Registry pull secret (`ecr-credentials` in prod) |
| `K8S_STORAGE_CLASS` | StorageClass for project PVCs (`tesslate-btrfs` minikube, `tesslate-block-storage` prod) |
| `K8S_SNAPSHOT_CLASS` | VolumeSnapshotClass (`tesslate-btrfs-snapshots` minikube, `tesslate-ebs-snapshots` prod) |
| `K8S_SNAPSHOT_RETENTION_DAYS` | Days to keep soft-deleted snapshots (default 30) |
| `K8S_MAX_SNAPSHOTS_PER_PROJECT` | Max snapshots in the timeline (default 5) |
| `K8S_SNAPSHOT_READY_TIMEOUT_SECONDS` | Snapshot readiness timeout (default 300) |
| `K8S_HIBERNATION_IDLE_MINUTES` | Auto-hibernate after N idle minutes (default 10) |
| `K8S_HYDRATION_TIMEOUT_SECONDS`, `K8S_DEHYDRATION_TIMEOUT_SECONDS` | Hibernation transitions |
| `K8S_PVC_SIZE` | Per-project PVC size (default 5Gi) |
| `K8S_PVC_STORAGE_CLASS`, `K8S_PVC_ACCESS_MODE` | Dynamic PVC config for S3-backed mode |
| `K8S_ENABLE_POD_AFFINITY` | Pin multi-container projects to same node |
| `K8S_RWX_STORAGE_CLASS` | ReadWriteMany class for shared source code |
| `K8S_INGRESS_CLASS` | Ingress class name (default `nginx`) |
| `K8S_NAMESPACE_PER_PROJECT` | Namespace-per-project isolation (default true) |
| `K8S_ENABLE_NETWORK_POLICIES` | Create NetworkPolicies for project isolation (default true) |
| `K8S_WILDCARD_TLS_SECRET` | TLS secret for wildcard cert (empty = HTTP, e.g. minikube) |
| `K8S_INGRESS_DOMAIN` | Apex domain for user-project ingress (AWS overlay aliases `APP_DOMAIN`) |
| `K8S_USE_S3_STORAGE` | Use S3 hibernation instead of PVCs (default false) |

## Volume Hub + btrfs CSI

| Variable | Purpose |
|----------|---------|
| `VOLUME_HUB_ADDRESS` | Hub gRPC endpoint (default `tesslate-volume-hub.kube-system.svc:9750`) |
| `TEMPLATE_BUILD_STORAGE_CLASS` | StorageClass for template builds (`tesslate-btrfs`) |
| `TEMPLATE_BUILD_NODEOPS_ADDRESS` | NodeOps gRPC endpoint |
| `FILEOPS_ENABLED` | Use FileOps gRPC service for v2 file operations (default true) |
| `FILEOPS_TIMEOUT` | FileOps RPC timeout seconds (default 30) |
| `COMPUTE_MAX_CONCURRENT_PODS` | Max concurrent compute pods (default 5) |
| `COMPUTE_POD_TIMEOUT` | Pod readiness timeout (default 600) |
| `COMPUTE_REAPER_INTERVAL_SECONDS` | Orphan pod reaper interval (default 60) |
| `COMPUTE_REAPER_MAX_AGE_SECONDS` | Max pod age before reaping (default 900) |

## S3 / object storage

| Variable | Purpose |
|----------|---------|
| `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | Credentials |
| `S3_ENDPOINT_URL` | Custom endpoint (DO Spaces, MinIO); omit for AWS |
| `S3_BUCKET_NAME` | Projects bucket (default `tesslate-projects`) |
| `S3_REGION` | Region (default `us-east-1`) |
| `S3_PROJECTS_PREFIX` | Key prefix (default `projects`) |

## Web search

| Variable | Purpose |
|----------|---------|
| `WEB_SEARCH_PROVIDER` | `tavily`, `brave`, or `duckduckgo` (default tavily) |
| `TAVILY_API_KEY` | Tavily API key |
| `BRAVE_SEARCH_API_KEY` | Brave Search API key |

## Messaging channels

| Variable | Purpose |
|----------|---------|
| `AGENT_DISCORD_WEBHOOK_URL` | Webhook URL used by the agent `send_message` tool |
| `CHANNEL_ENCRYPTION_KEY` | Fernet key for encrypting per-user channel credentials (Telegram, Slack, Discord, WhatsApp) |

## MCP (Model Context Protocol)

| Variable | Purpose |
|----------|---------|
| `MCP_TOOL_CACHE_TTL` | MCP tool schema cache TTL seconds (default 300) |
| `MCP_TOOL_TIMEOUT` | MCP tool call timeout seconds (default 30) |
| `MCP_MAX_SERVERS_PER_USER` | Cap on installed MCP servers per user (default 20) |

## Gateway (communication protocol v2)

| Variable | Purpose |
|----------|---------|
| `GATEWAY_ENABLED` | Enable gateway runner (default false) |
| `GATEWAY_SHARD` | Shard identifier for multi-instance gateway |
| `GATEWAY_TICK_INTERVAL` | Scheduler tick interval seconds |
| `GATEWAY_SESSION_IDLE_MINUTES` | Idle timeout for gateway sessions |
| `GATEWAY_VOICE_TRANSCRIPTION` | Enable voice message transcription |

## Desktop (Tauri sidecar)

| Variable | Purpose |
|----------|---------|
| `OPENSAIL_HOME` | Desktop data directory override. Resolved by `orchestrator/app/services/desktop_paths.py`. |
| `TEST_HELPERS_ENABLED` | Enable test-only routes (set in CI E2E) |
| `BUILD_SHA` | Deployment identifier reported by `/api/version` (CI sets this) |

## Feature flags (Tesslate Apps)

Registered in `orchestrator/app/config_features.py`. Every flag is a boolean, default OFF unless noted. Set via environment variables named `TSL_FEATURE_<FLAG>` where `<FLAG>` is the dotted flag name upper-cased with dots replaced by underscores.

| Flag | Env variable | Default |
|------|--------------|---------|
| `apps.manifest_schema_v1` | `TSL_FEATURE_APPS_MANIFEST_SCHEMA_V1` | false |
| `apps.publish` | `TSL_FEATURE_APPS_PUBLISH` | false |
| `apps.install` | `TSL_FEATURE_APPS_INSTALL` | false |
| `apps.runtime.ui` | `TSL_FEATURE_APPS_RUNTIME_UI` | false |
| `apps.runtime.chat` | `TSL_FEATURE_APPS_RUNTIME_CHAT` | false |
| `apps.runtime.scheduled` | `TSL_FEATURE_APPS_RUNTIME_SCHEDULED` | false |
| `apps.runtime.triggered` | `TSL_FEATURE_APPS_RUNTIME_TRIGGERED` | false |
| `apps.runtime.mcp_tool` | `TSL_FEATURE_APPS_RUNTIME_MCP_TOOL` | false |
| `apps.hosted_agent` | `TSL_FEATURE_APPS_HOSTED_AGENT` | false |
| `apps.source_view` | `TSL_FEATURE_APPS_SOURCE_VIEW` | false |
| `apps.fork` | `TSL_FEATURE_APPS_FORK` | false |
| `apps.bundles` | `TSL_FEATURE_APPS_BUNDLES` | false |
| `apps.review.stage1` | `TSL_FEATURE_APPS_REVIEW_STAGE1` | false |
| `apps.review.stage2` | `TSL_FEATURE_APPS_REVIEW_STAGE2` | false |
| `apps.review.stage3` | `TSL_FEATURE_APPS_REVIEW_STAGE3` | false |
| `apps.yank` | `TSL_FEATURE_APPS_YANK` | false |
| `apps.yank.critical_two_admin` | `TSL_FEATURE_APPS_YANK_CRITICAL_TWO_ADMIN` | **true** (governance policy) |
| `apps.billing.dispatcher` | `TSL_FEATURE_APPS_BILLING_DISPATCHER` | false |
| `apps.billing.revenue_split` | `TSL_FEATURE_APPS_BILLING_REVENUE_SPLIT` | false |
| `apps.triggers.webhook` | `TSL_FEATURE_APPS_TRIGGERS_WEBHOOK` | false |
| `apps.triggers.mcp_event` | `TSL_FEATURE_APPS_TRIGGERS_MCP_EVENT` | false |
| `apps.triggers.app_invocation` | `TSL_FEATURE_APPS_TRIGGERS_APP_INVOCATION` | false |
| `apps.canvas.hosted_agent_node` | `TSL_FEATURE_APPS_CANVAS_HOSTED_AGENT_NODE` | false |
| `apps.embedding.postmessage` | `TSL_FEATURE_APPS_EMBEDDING_POSTMESSAGE` | false |

Always-on platform capabilities advertised alongside the flag set (not overridable): `cas_bundle`, `volume_fork`, `volume_snapshot`, `manifest_schema_2025_02`. Manifest schemas supported by the parser: `2025-01`, `2025-02`. Runtime API versions: `1.0`.

## Testing

| Variable | Purpose |
|----------|---------|
| `TEST_HELPERS_ENABLED` | Expose test-only routes (CI only) |
| `PLAYWRIGHT_BASE_URL` | Base URL for Playwright E2E |

The CI workflow (`.github/workflows/ci.yml`) sets `SECRET_KEY=test-secret-key-*`, `DEPLOYMENT_MODE=docker`, `LITELLM_API_BASE=http://localhost:4000/v1`, `LITELLM_MASTER_KEY=test-key`, and points `DATABASE_URL` at the Postgres 15 service on port 5433.

## Where each file is read

| File | Primary reader |
|------|----------------|
| Root `.env.example` | `docker-compose.yml`, `config.py` (via dotenv), Vite (for `VITE_*`) |
| Root `.env.prod.example` | `docker-compose.prod.yml` |
| `k8s/.env.minikube` (gitignored) | Kustomize secret generator (`k8s/overlays/minikube/secrets/`) |
| Kustomize overlays (`k8s/overlays/*/backend-patch.yaml`) | Patches the backend Deployment `env` at apply time |
| Terraform `kubernetes.tf` | Creates `tesslate-app-secrets`, `postgres-secret`, `s3-credentials`; auto-mounted via `envFrom` |
| `orchestrator/app/config.py` | Canonical Python reader (Pydantic settings) |
| `orchestrator/app/config_features.py` | Feature flags |
| `app/vite.config.ts`, `app/src/lib/config.ts` | Frontend (reads `VITE_*` at build, `window._env_.*` at runtime) |
