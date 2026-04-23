# Deploying projects to external targets

OpenSail ships with 22 external deployment targets wired into the Architecture
Panel. You draw an edge from a container node to a deploy-target node, the
orchestrator builds the container's working directory, and the target provider
takes over from there. The same project can fan out to multiple targets, run
A/B variants against separate providers, and carry distinct environment
variables per target (production, staging, preview).

## 1. What this does

A **deployment target** is a first-class node on the React Flow canvas.
Containers (frontend, backend, worker) connect to targets via dashed orange
deployment edges. One container can feed many targets, and one target accepts
many containers. Each target owns its own:

- Provider (vercel, netlify, fly, etc.)
- Environment (production, staging, preview)
- Env-var overrides (`deployment_env` JSON column)
- Deployment history with per-version rollback
- Live connection state (is a credential saved for this provider)

Source files: `orchestrator/app/models.py` defines `DeploymentTarget`,
`DeploymentTargetConnection`, `Deployment`, `DeploymentCredential`. The
canvas component is `app/src/components/DeploymentTargetNode.tsx`; the edge
is `app/src/components/edges/DeploymentEdge.tsx`.

## 2. Provider catalog

22 targets grouped by deploy-type. The classification lives in
`orchestrator/app/services/deployment/manager.py` (`_providers`,
`_container_providers`, `_export_providers`) and is mirrored in
`app/src/components/DeploymentTargetNode.tsx` (`getDeployType`).

### Serverless and full-stack (11)

| Provider | Slug | Auth | Notes |
|---|---|---|---|
| Vercel | `vercel` | OAuth | Source-mode default, framework detection |
| Netlify | `netlify` | OAuth | Pre-built upload via Netlify Files API |
| Cloudflare Pages and Workers | `cloudflare` | API token | Pre-built, `account_id` required |
| DigitalOcean App Platform (source) | `digitalocean` | API token | Requires git remote on project |
| Railway | `railway` | API token | Requires git remote |
| Fly.io | `fly` | API token | Container push to Fly Machines |
| Heroku | `heroku` | API key | Source tarball upload |
| Render | `render` | API key | Requires git remote |
| Koyeb | `koyeb` | API token | Serverless, optional `org_slug` |
| Zeabur | `zeabur` | API key | ZIP upload, `region` optional |
| Northflank | `northflank` | API token | Requires git remote |

### Static hosting (4)

| Provider | Slug | Auth | Notes |
|---|---|---|---|
| GitHub Pages | `github-pages` | GitHub PAT | `repo` scope, static only |
| Surge | `surge` | email + token | Run `surge token` in CLI to fetch |
| Deno Deploy | `deno-deploy` | Access token | `org_id` required |
| Firebase Hosting | `firebase` | Service-account JSON | `site_id` required |

### Container push (4)

| Provider | Slug | Auth | Notes |
|---|---|---|---|
| AWS App Runner | `aws-apprunner` | Access key + secret | Pushes to ECR, then App Runner |
| GCP Cloud Run | `gcp-cloudrun` | Service-account JSON | Pushes to Artifact Registry |
| Azure Container Apps | `azure-container-apps` | Tenant, client, secret, subscription | Pushes to ACR |
| DigitalOcean Container Apps | `do-container` | API token | Pushes to DOCR |

### Registry and export (3)

| Provider | Slug | Auth | Notes |
|---|---|---|---|
| Docker Hub | `dockerhub` | Username + PAT | Registry push only, no runtime |
| GitHub Container Registry | `ghcr` | Username + PAT (`write:packages`) | Registry push only |
| Download / Export | `download` | None | Zip archive delivered to the browser |

## 3. Connecting a provider

Open **Settings, Deployments** (`app/src/pages/settings/DeploymentSettings.tsx`).
Each provider card reads its requirements from the `/api/deployment-credentials/providers`
catalog served by `DeploymentManager.list_available_providers()`.

Two auth flavors:

- **OAuth** (Vercel, Netlify): click Connect, the popup kicks off
  `/api/deployment-oauth/vercel/authorize` or
  `/api/deployment-oauth/netlify/authorize`. Callback handlers in
  `orchestrator/app/routers/deployment_oauth.py` exchange the code, encrypt
  the token with the Fernet key in `deployment_encryption.py`, and persist a
  `DeploymentCredential` row.
- **API token** (everything else): fill the required fields. Field labels and
  per-field help strings come from `app/src/lib/deployment-providers.ts`
  (`PROVIDER_CREDENTIAL_HELP`). The same strings render as a hover tooltip on
  the canvas node when the target is still unconnected.

Credentials are user-scoped by default. Pass `project_id` in the create
request to pin a credential to a single project; the resolver in
`get_credential_for_deployment` (`routers/deployments.py`) prefers a
project-scoped credential over the user default.

Rotate a credential by reconnecting from the same Settings card. The old row
is updated in place, so any targets already bound to it stay connected.

## 4. Architecture Panel usage

1. In the project view, open the Architecture Panel.
2. Drag a **Deployment Target** from the node palette. Pick a provider from
   the list of 22 and drop it on the canvas. The orchestrator creates a
   `DeploymentTarget` row via `POST /api/projects/{slug}/deployment-targets`.
3. Draw an edge from a container node's right handle to the target node's
   left handle. The edge posts to
   `/api/projects/{slug}/deployment-targets/{target_id}/connect/{container_id}`,
   which inserts a `DeploymentTargetConnection`.
4. Click the environment label (`production` / `staging` / `preview`) on the
   target header to cycle values. This writes back to `DeploymentTarget.environment`.
5. Double-click the target (or use the card menu) to edit env-var overrides,
   custom build command, or display name. Per-edge overrides live in
   `DeploymentTargetConnection.deployment_settings`.
6. The Deployment History panel on the node pulls the last 10 rows from
   `/deployment-targets/{target_id}/history`.

## 5. Triggering a deploy

Three entry points, all feed the same pipeline:

- **Target node "Deploy" button**: calls
  `POST /api/projects/{slug}/deployment-targets/{target_id}/deploy` and loops
  over every connected container in one request. This is the standard path.
- **Deploy modal** (`app/src/components/modals/DeploymentModal.tsx`): the
  legacy per-project path that still backs the top-right Deploy button. Calls
  `POST /api/deployments/{project_slug}/deploy` with provider, deployment_mode,
  env_vars, and custom_domain.
- **Agent tool**: the agent runner can deploy on behalf of the user. See
  `packages/tesslate-agent/docs/DOCS.md` for the tool surface.

## 6. What happens server-side

When a deploy is triggered (source/file mode), the orchestrator runs this
pipeline inside `routers/deployments.py::deploy_project` or
`routers/deployment_targets.py::deploy_target`:

1. RBAC check via `get_project_with_access(Permission.DEPLOYMENT_CREATE)`.
2. Resolve credential with project-override precedence.
3. Decrypt the token with `deployment_encryption.get_deployment_encryption_service()`.
4. Insert a `Deployment` row with `status="building"` so the UI shows progress.
5. Pick the primary build container, ensure it is running via
   `get_orchestrator().get_container_status()`.
6. If `deployment_mode == "source"`, skip the build (provider builds remotely).
   Otherwise invoke `get_deployment_builder().trigger_build()` which runs
   `npm run build` (or container-specific build) inside the live container.
7. Collect files with `builder.collect_deployment_files()` (honoring
   `container.output_directory`).
8. Hand files to the provider via `DeploymentManager.get_provider(name, creds)`.
   Source-mode providers call `provider.deploy(files, config)`. Container-push
   providers go through `provider.push_image()` then `provider.deploy_image()`.
9. Update the `Deployment` row with `status`, `deployment_url`, `logs`,
   `completed_at`, and `deployment_metadata`.
10. Poll or stream provider status where supported (Vercel, Netlify, and
    cloud providers expose async status); otherwise the initial response
    carries the final state.

All deployment tokens stay on the server. The frontend only ever receives
the `deployment_url`, `status`, and `logs`.

## 7. A/B deploys

Because each target is an independent node, the same container can connect
to two or more targets. Drop a second Vercel target set to `preview` and a
third Netlify target set to `staging`, then wire the same frontend container
into all three. Each target has its own `Deployment` history, so rollback,
URLs, and env-var overrides are isolated. This is the recommended pattern
for:

- Split traffic between Vercel (production) and Cloudflare Pages (preview).
- Deploy the same static build to GitHub Pages and Surge for redundancy.
- Keep `staging.myapp.com` on Fly.io while production runs on AWS App Runner.

## 8. Environment matrix

Env vars flow through a four-layer merge in
`routers/deployment_targets.py::_build_source_env_vars`. Later layers win:

1. **Auto-derived**: `project.git_remote_url` becomes `_TESSLATE_REPO_URL` for
   git-required providers.
2. **Target-level**: `DeploymentTarget.deployment_env` JSON column. Set this
   for values that apply to every container connected to the target
   (`NODE_ENV=production`).
3. **Connection-level**: `DeploymentTargetConnection.deployment_settings["env_vars"]`.
   Use for per-container differences between the same target.
4. **Request-level**: `env_vars` passed in the deploy call. One-off overrides
   from the modal or agent.

Internal keys prefixed with `_TESSLATE_` (see `services/deployment/base.py`,
`INTERNAL_ENV_PREFIX`) are stripped before anything is sent to the provider.
The `environment` column (`production`, `staging`, `preview`) is metadata for
the UI; it is not automatically forwarded as an env var, so add `NODE_ENV`
or `VERCEL_ENV` yourself on the target's `deployment_env`.

## 9. Per-provider caveats

- **Vercel**: defaults to `source` mode so Vercel runs the build on its own
  infrastructure. Pass `team_id` in metadata for team accounts; leave empty
  for personal. OAuth via `/api/deployment-oauth/vercel/authorize` with PKCE.
- **Netlify**: file-upload API does not trigger a remote build, so OpenSail
  defaults to `pre-built`. The local build must complete before the upload.
- **Cloudflare Pages and Workers**: `pre-built` only. The provider upload uses
  the dispatch namespace in metadata if set; `account_id` is mandatory.
- **Fly.io**: deploys to Fly Machines, not the legacy Nomad stack. Set
  `org_slug` for multi-org accounts. Volumes are not auto-created; declare
  them in the container's `fly.toml`.
- **AWS App Runner**: requires ECR access. The provider pushes the image to
  a per-region ECR repository using the supplied IAM key, then creates an
  App Runner service pointing at the pushed tag.
- **GitHub Pages**: static only. The `token` needs the `repo` scope; the
  provider publishes to the `gh-pages` branch.
- **Docker Hub and GHCR**: registry-only. No runtime is stood up, no URL is
  returned; the button label switches to "Export".
- **Download / Export**: bundles the build output as a zip and returns a
  signed URL. No credentials required.
- **DigitalOcean**: two slugs share the same backend class. `digitalocean` is
  the source-mode alias (git deploy), `do-container` is the image-push alias
  (DOCR + App Platform container spec).

## 10. Rolling back

From the target node's deployment history, click **Rollback** on any prior
successful row. The UI calls
`POST /api/projects/{slug}/deployment-targets/{target_id}/rollback/{deployment_id}`.
The orchestrator creates a new `Deployment` row with
`version="{prev}-rollback"`, linked via `deployment_metadata.rollback_from`.
Full provider-API rollback (Vercel alias swap, Fly release pin) is tracked
in the same handler and rolls forward when each provider implements it.

## 11. Credential security

- Every `access_token_encrypted` column is Fernet-encrypted with the key
  configured on the backend (see `deployment_encryption.py`). Decryption
  happens only inside the deployment pipeline, never in the API response.
- Credentials are scoped to `user_id`. Add `project_id` to create an override
  that only applies to that project (useful for team members with different
  Vercel accounts).
- `GET /api/deployment-credentials` returns metadata and the `is_default`
  flag; it never returns the token.
- Rotation: reconnect via Settings. Revoked tokens will start returning 401
  from the provider; the deployment fails with a clear error and the target
  node flips back to "Not Connected" on the next credential sync.
- Provider-scoped metadata (team IDs, registry names, regions) is stored in
  `provider_metadata` JSON, plaintext. Do not put secondary secrets there;
  always use the encrypted token field.

## 12. Common errors

| Message | Likely cause | Fix |
|---|---|---|
| `No credentials found for {provider}` | No `DeploymentCredential` for user and project | Connect the provider in Settings, or pass `project_id` on the credential |
| `Please connect your {provider} account first` | Target is on the canvas but credential lookup returned None | Same as above; the target node will show a yellow "Not Connected" banner |
| `Container {name} is not running` | Orchestrator can't exec a build in a stopped container | Start the project from the canvas, wait for green status, retry |
| `Build failed: {stderr}` | Container build command failed | Check `container.build_command`, install missing deps, look at logs in the Deployment row |
| `This provider deploys from a git repository...` | Git-required provider with no remote (`railway`, `render`, `digitalocean`, `github-pages`, `northflank`) | Link a repo via the Git panel |
| `OAuth scope` or 401 from Vercel/Netlify | Token expired or scope revoked | Reconnect the provider in Settings |
| `External provider deployments are not available in desktop mode` | Desktop sidecar tried to hit cloud providers | Deploy from cloud OpenSail; desktop only runs local and docker runtimes |
| Provider 403 "quota exceeded" | Free-tier limit (projects, bandwidth, build minutes) | Upgrade the provider plan, or deploy to a second target |
| Build timeout | Long build blocks the sync request | Split into smaller containers or rely on source-mode where the provider builds remotely |

## 13. Where to next

- **Publish an app**: once a deploy works, the project can become a Tesslate
  App. See `docs/apps/CLAUDE.md` for the publish pipeline, bundles, and
  submission stages.
- **Gateway and channels**: wire a deployed backend to Telegram, Discord,
  Slack, or WhatsApp via the gateway. See `docs/orchestrator/routers/CLAUDE.md`
  (`channels.py`, `gateway.py`).
- **Agent-driven deploys**: let the AI agent deploy as part of a task. See
  `packages/tesslate-agent/docs/DOCS.md`.
- **Observability**: track deploy success rates, build durations, and
  provider latency with the OTel stack in
  `docs/guides/enterprise-observability.md`.
