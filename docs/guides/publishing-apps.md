# Publishing Apps to the OpenSail Marketplace

This guide walks a creator from a working project all the way to an installable
OpenSail marketplace app. It is a user-facing how-to, not an API reference. For
the authoritative schema see `docs/specs/app-manifest-2025-02.md`, and for agent
wiring see `packages/tesslate-agent/docs/DOCS.md`.

## 1. Concepts

OpenSail apps sit on top of the same Project/Container/Volume primitives as
ordinary workspaces, with a few extra objects layered on.

| Term | What it is |
|------|------------|
| Workspace | A regular `Project` you develop in. When you turn it into an app source it becomes `Project(app_role="app_source")`. |
| AppVersion | An immutable, content-addressed snapshot of a workspace (manifest + bundle hash). Published once, never mutated. |
| MarketplaceApp | The public identity anchor: slug, handle, category, reputation, approval state. One app can have many `AppVersion`s. |
| AppInstance | A single user's installed copy. Installing mints a new `Project(app_role="app_instance")` with its own volume, containers, and permissions. |
| `wallet_mix` | Per-install JSON declaring who pays for each billing dimension (AI compute, general compute, storage, egress, MCP calls, platform fee). |
| `update_policy` | `auto`, `manual`, or `pinned`, per install. Controls whether new approved versions are pulled automatically. |
| Surface | The entrypoint kind the app exposes: `ui` (iframe), `chat` (scoped agent session), `scheduled` (cron), `triggered` (webhook or event), `mcp-tool` (callable by other agents). A headless app can declare `surfaces: []`. |

See `orchestrator/app/models.py` for the backing columns, and
`docs/apps/CLAUDE.md` for the full service map.

## 2. Build your workspace

Start with a regular OpenSail project. Use the chat surface to describe what
you want, or import code via the Desktop client's connected directories.

1. Create a project from the dashboard or `POST /api/projects`.
2. Add containers. Each container is a separate service (web, api, db, worker).
   The AI agent wires them through `orchestrator/app/routers/projects.py`
   `setup-config` by reading `.tesslate/config.json`.
3. Let the Librarian agent generate `.tesslate/config.json`. It captures
   `containers`, `startup_command`, and `connections` (see
   `docs/orchestrator/services/config-json.md`).
4. Declare inter-container dependencies as `env_injection` edges so the
   manifest knows, for example, that the `api` container needs `DATABASE_URL`
   from the `db` container. The CRM-with-Postgres seed at
   `seeds/apps/crm-with-postgres/app.manifest.json` is a full worked example.
5. Test it locally. Start the project, hit the primary container URL, exercise
   schedules, verify secrets resolve.

When you are ready to publish, set the project's `app_role` to `app_source`
(the Creator Studio UI does this for you on first publish).

## 3. The app manifest

The manifest is a JSON document that describes everything a fresh installer
needs to run your app: containers, surfaces, billing, scopes, schedules, MCP
tool schemas. The authoritative schema is
`orchestrator/app/services/apps/app_manifest_2025_02.schema.json`; the narrative
spec is `docs/specs/app-manifest-2025-02.md` with the v1 background at
`docs/specs/app-manifest-2025-01.md`.

Top-level keys:

```yaml
manifest_schema_version: "2025-02"
app:           { id, name, slug, version, description, category, forkable, handle? }
compatibility: { studio: { min, max? }, manifest_schema, runtime_api, required_features[] }
surfaces:      [ { kind, entrypoint?, name?, description?, tool_schema? } ]
compute:
  tier
  compute_model
  containers:  [ { name, image, primary, ports, env, startup_command, volumes?, resources? } ]
  connections: [ { source_container, target_container, connector_type, config } ]
  hosted_agents: [ ... ]
state:         { model, volume_size?, byo_database? }
connectors:    [ { id, kind, scopes, required, oauth?, secret_key? } ]
schedules:     [ { name, default_cron?, entrypoint?, execution, trigger_kind, editable?, optional? } ]
billing:       { ai_compute, general_compute, platform_fee, promotional_budget? }
listing:       { visibility, update_policy_default?, minimum_rollback_version? }
eval_scenarios: [ ... ]
```

Minimal single-container UI app (the `hello-node` seed):

```json
{
  "manifest_schema_version": "2025-02",
  "app": {
    "id": "com.tesslate.hello-node",
    "slug": "hello-node",
    "name": "Hello Node",
    "version": "0.1.0",
    "forkable": "true"
  },
  "compatibility": {
    "studio": {"min": "0.0.0"},
    "manifest_schema": "2025-02",
    "runtime_api": "^1.0",
    "required_features": []
  },
  "compute": {
    "tier": 1,
    "compute_model": "per-installer",
    "containers": [{
      "name": "web", "primary": true,
      "image": "tesslate-devserver:latest",
      "ports": [3000],
      "startup_command": "node /app/server.js",
      "env": {"PORT": "3000"}
    }],
    "connections": []
  },
  "surfaces": [{"kind": "ui", "entrypoint": "/"}],
  "state": {"model": "per-install-volume", "volume_size": "256Mi"},
  "billing": {
    "ai_compute":     {"payer": "platform"},
    "general_compute":{"payer": "platform"},
    "platform_fee":   {"model": "free"}
  },
  "listing": {"visibility": "public"}
}
```

Notes on common fields:

- `slug` is kebab-case, globally unique, and immutable after first publish.
- `version` is strict semver. Each publish must be strictly greater than the
  prior `AppVersion` for this app.
- `primary: true` marks the container whose URL backs `ui`/`chat` surfaces.
  Exactly one container must be primary when `containers[]` is non-empty.
- Secret-ref env values use the convention `"${secret:<name>/<key>}"`. They
  resolve at pod-spec time via `orchestrator/app/services/apps/env_resolver.py`.
- `connectors[]` declares OAuth scopes the installer must consent to.
- `eval_scenarios[]` supplies at least three happy-path prompts per entrypoint
  for public listings. They are used by Stage 2 sandbox eval.

## 4. Submit for publishing

From Creator Studio (`app/src/pages/CreatorStudioPage.tsx`) open your source
project and click Publish version, or drive the REST API:

```http
POST /api/apps/versions/publish
{ "project_id": "<uuid>", "manifest": { ... }, "app_id": null }
```

The router lives in `orchestrator/app/routers/app_versions.py`. The publisher
(`orchestrator/app/services/apps/publisher.py`) does the following, atomically:

1. Parse and validate the manifest against the frozen schema.
2. Run `compatibility.check()` against the running server.
3. Get or create the `MarketplaceApp` row (by slug).
4. Guard against duplicate `(app_id, version)`.
5. Publish the bundle to Volume Hub's CAS, capturing `bundle_hash`.
6. Insert `AppVersion(approval_state="pending_stage1")`.
7. Insert `AppSubmission(stage="stage0")`, which enters the review pipeline.

The Creator Publish form (`app/src/pages/CreatorAppPublishPage.tsx`) handles
slug/version validation, a skeleton manifest generator, JSON upload, and a
client-side compatibility preview before you hit Publish.

Private or team installs (manifest `listing.visibility: "private"` or
`"team:<uuid>"`) skip the public approval gate. They still pass through
Stage 0 and Stage 1 for structural checks, but never surface to the public
marketplace.

## 5. Approval pipeline

Every public submission walks a four-stage state machine. The transitions are
enforced by `orchestrator/app/services/apps/submissions.py`
(`VALID_TRANSITIONS`) and the per-stage logic lives alongside it.

| Stage | What happens | Service |
|-------|--------------|---------|
| Stage 0 | Intake. Submission row created, bundle persisted. | `publisher.py` |
| Stage 1 | Automated structural scan. Re-parses the manifest, confirms declared features are supported, checks MCP scopes against the safe-list, confirms disclosure fields and billing payers exist. Any hard fail rejects; warnings do not. | `stage1_scanner.py` |
| Stage 2 | Sandbox eval. Runs the app against an adversarial suite (`AdversarialSuite` rows) with a cheap model. Scores crashes, cost blowouts, prompt injection resistance. Needs score >= `STAGE2_SCORE_THRESHOLD` (0.5) to pass. | `stage2_sandbox.py` |
| Stage 3 | Human review by OpenSail admins in the Admin Marketplace Workbench (`app/src/pages/AdminSubmissionWorkbenchPage.tsx`, `AdminMarketplaceReviewPage.tsx`). | `admin_marketplace.py` |

On Stage 3 approval, `AppVersion.approval_state` becomes `stage2_approved` and
`MarketplaceApp.state` becomes `approved`. The version is now installable from
the public marketplace.

Stage 1 checks surface individual `SubmissionCheck` rows so creators can see
exactly which check failed. `AdminAdversarialSuitePage.tsx` exposes the suite
itself to admins.

Dev shortcut: setting `TSL_APPS_DEV_AUTO_APPROVE=1` skips all stages. The
platform blocks this whenever `app_base_url` is HTTPS, so it cannot be enabled
in production by accident.

## 6. Billing configuration

Billing is three independent dimensions. Every dimension declares a payer and
caps independently. The resolved payer for each spend event is the
`wallet_mix` entry on the `AppInstance`, negotiated at install time.

| Dimension | Default payer behavior | Default `on_cap` |
|-----------|------------------------|------------------|
| `ai_compute` | LLM token spend. Can be `creator`, `platform`, `installer`, or `byok` (bring-your-own key). | `pause` |
| `general_compute` | Container CPU, memory, storage, egress. Cannot be `byok`. | `degrade` |
| `platform_fee` | Subscription, one-time, or free. Orthogonal to compute. | `pause` |

```yaml
billing:
  ai_compute:
    payer: installer
    cap_usd_per_session: 1.00
    cap_usd_per_month_per_install: 50.00
  general_compute:
    payer: installer
    cap_usd_per_month_per_install: 10.00
    on_cap: degrade
  platform_fee:
    model: subscription
    price_usd: 9.00
    billing_period: monthly
    trial_days: 7
  promotional_budget:
    fund_usd: 500
    covers: [ai_compute]
    on_exhaust: flip_to_installer
```

The creator can fund a `promotional_budget` to pay AI costs themselves up to
`fund_usd`. When exhausted, the payer automatically flips to the installer so
the app does not stop working.

Settlement runs in ARQ via `settlement_worker.settle_spend_batch` (uses
`SELECT ... FOR UPDATE SKIP LOCKED` for safe concurrency). The platform keeps
`markup_pct` (default 10%) and credits the creator the rest. BYOK on AI compute
records a no-op `SpendRecord` with `reason='byok_no_op'`.

UI: the creator sets these from
`app/src/pages/CreatorBillingPage.tsx`. Installers see the resolved numbers in
`AppInstallWizard.tsx` before they click Install.

## 7. Installing apps

One-click install from `app/src/pages/AppsMarketplacePage.tsx` and
`AppDetailPage.tsx` launches the `AppInstallWizard` component. It collects:

- Team under which to install.
- OAuth consents for every `connectors[]` entry with `oauth: true`.
- `wallet_mix` consent (which payer is accepted per billing dimension).
- MCP scope consent per declared MCP server.
- Update policy (`auto`, `manual`, `pinned`).

On submit, `POST /api/apps/installs` reaches the installer at
`orchestrator/app/services/apps/installer.py`, which:

1. Verifies the AppVersion is in `stage1_approved` or `stage2_approved`.
2. Re-runs compatibility against the current server.
3. Dedupes against an existing active `AppInstance`.
4. Calls `hub_client.restore_bundle()` to materialize a new volume from the
   CAS bundle. An `AppInstallAttempt(state="hub_created")` row is written
   before the DB commit so a background reaper
   (`install_reaper.py`) can clean up crashed installs.
5. Inserts a new `Project(app_role="app_instance")` plus one `Container` row
   per entry in `compute.containers` and `ContainerConnection` rows for
   `compute.connections`.
6. Inserts the `AppInstance`, attaches `McpConsentRecord` rows, flips the
   attempt to `committed`.

The installer returns `{app_instance_id, project_id, volume_id, node_name}`.
Containers start through the normal orchestrator path
(`orchestrator/app/services/orchestration/factory.py`).

Installed apps show up in `app/src/pages/MyAppsPage.tsx`. The running UI is
hosted by `app/src/components/apps/IframeAppHost.tsx` with a signed URL scoped
to the install.

## 8. Bundles

Bundles group multiple AppVersions that should install together (for example
the Tesslate Starter Pack: a CRM app plus a nightly digest plus a center
dashboard that embeds the others).

- Model: `AppBundle` + `AppBundleItem` (`orchestrator/app/models.py`).
- Service: `orchestrator/app/services/apps/bundles.py` (`create_bundle`,
  `publish_bundle`, `yank_bundle`).
- Router: `orchestrator/app/routers/app_bundles.py`.
- UI: `app/src/pages/BundleDetailPage.tsx` plus
  `app/src/components/apps/BundleInstallWizard.tsx`.

`consolidated_manifest_hash` is computed over the sorted member manifest
hashes, so two semantically identical bundles dedup. The install wizard shows
a single consolidated consent screen covering every member's OAuth scopes.

The center dashboard pattern uses `app/src/components/apps/WorkspaceSurface.tsx`
to render an app that embeds its bundle siblings through signed iframes.

## 9. Forking

If the manifest declares `forkable: "true"`, any user can clone the app:

```http
POST /api/apps/marketplace/{slug}/fork
```

`orchestrator/app/services/apps/fork.py` restores the source bundle to a new
Hub volume, creates a new `MarketplaceApp(state="draft", forked_from=...)`
row, and hands the forker a `Project(app_role="app_source")` they can edit
and republish under their own slug. The marketplace surfaces fork lineage on
`AppDetailPage.tsx`.

`forkable: "restricted"` requires creator approval per fork request.
`forkable: "no"` disables fork entirely. Forks do not inherit the source's
consents or OAuth grants: the new owner re-wires hosted-agent tools and MCPs.
UI: `app/src/pages/ForkPage.tsx` and
`app/src/components/apps/ForkModal.tsx`.

## 10. Yanking

If a version needs to be pulled, anyone with creator or admin rights can file
a yank request (`orchestrator/app/services/apps/yanks.py`,
`orchestrator/app/routers/app_yanks.py`).

| Severity | Admin approvals | Typical reason |
|----------|-----------------|----------------|
| `low` | one admin | cosmetic bug |
| `medium` | one admin | functional bug |
| `critical` | two distinct admins | security or legal; enforced by DB `CHECK ck_yank_critical_two_admin` and service layer `NeedsSecondAdminError` |

Approved yanks flip `AppVersion.yanked_at` and `state = "yanked"`. Running
installs stop being able to mint new runtime keys via
`orchestrator/app/services/apps/runtime.py`, which refuses yanked and
deprecated apps.

Creators can file an appeal against a decision through `YankAppeal`. Admins
review from `app/src/pages/AdminYankCenterPage.tsx`.

## 11. Creator reputation

`MarketplaceApp.reputation` is a JSON blob refreshed by
`orchestrator/app/services/apps/monitoring.py` and its sweep worker
`monitoring_sweep.py`. Inputs:

- Star ratings and install count.
- Review score from post-install feedback.
- Uptime and crash metrics pulled from the compute tier.
- Approval history (rejections, prior yanks, appeal outcomes).

Aggregated creator reputation surfaces on the public creator profile
(`orchestrator/app/routers/creators.py`) and in admin tooling at
`app/src/pages/AdminCreatorReputationPage.tsx`.

## 12. SDK usage

For apps that call back into OpenSail (publish a new version from CI, open a
session against an install, invoke an MCP tool), ship against the versioned
SDKs under `packages/tesslate-app-sdk/`.

Python (`packages/tesslate-app-sdk/py/`):

```python
import asyncio
from tesslate_app_sdk import AppClient, AppSdkOptions, ManifestBuilder

async def main() -> None:
    opts = AppSdkOptions(base_url="https://opensail.tesslate.com", api_key="tsk_...")
    manifest = (
        ManifestBuilder()
        .app(slug="hello", name="Hello App", version="0.1.0")
        .surface(kind="iframe", entry="index.html")
        .billing(model="wallet-mix", default_budget_usd=0.25)
        .require_features(["apps.v1"])
        .build()
    )
    async with AppClient(opts) as client:
        pub = await client.publish_version(project_id="...", manifest=manifest)
        inst = await client.install_app(
            app_version_id=pub["app_version_id"],
            team_id="...",
            wallet_mix_consent={"accepted": True},
            mcp_consents=[],
        )
        sess = await client.begin_session(
            app_instance_id=inst["app_instance_id"], budget_usd=1.0, ttl_seconds=3600
        )
        # sess["api_key"] is returned once only; cache it.

asyncio.run(main())
```

TypeScript (`packages/tesslate-app-sdk/ts/`):

```ts
import { AppClient, ManifestBuilder } from "@tesslate/app-sdk";

const client = new AppClient({
  baseUrl: "https://opensail.tesslate.com",
  apiKey: process.env.TESSLATE_API_KEY!,
});

const manifest = new ManifestBuilder()
  .app({ slug: "hello", name: "Hello App", version: "0.1.0" })
  .surface({ kind: "iframe", entry: "index.html" })
  .billing({ model: "wallet-mix", default_budget_usd: 0.25 })
  .requireFeatures(["apps.v1"])
  .build();

const published = await client.publishVersion({ projectId: "...", manifest });
```

Both SDKs authenticate with a Tesslate external API key (`tsk_...`) via
`Authorization: Bearer`. CSRF is not needed because cookie sessions are not
used.

For the agent runtime that powers chat and hosted-agent surfaces, read
`packages/tesslate-agent/docs/DOCS.md`.

## 13. MCP surface

Any app can expose one or more of its entrypoints as MCP tools callable by
other agents. Declare each tool in `surfaces[]`:

```yaml
surfaces:
  - kind: mcp-tool
    entrypoint: tools/redline
    name: redline
    description: "Return tracked-change suggestions on a document."
    tool_schema:
      type: object
      properties:
        document_ref: { type: string }
      required: [document_ref]
```

`tool_schema` is a JSON Schema for the tool input. Stage 1 scans the declared
MCP scopes; Stage 2 exercises the tool against the adversarial suite. At
install time the user consents to the scopes via
`AppInstallWizard.tsx`, and the consent is recorded in `McpConsentRecord`.
Runtime bridging lives in `orchestrator/app/services/mcp/` (client, bridge,
manager).

`stateless` or `shared-db` state models are recommended for MCP tools because
they are called concurrently across invocations.

## 14. Scheduled triggers and webhooks

Every `schedules[]` entry gets an `AgentSchedule` row scoped to the install.
Two dimensions combine to make four shapes:

| `trigger_kind` | `execution` | Semantics |
|----------------|-------------|-----------|
| `cron` | `job` | Cron fires, a `V1Job` runs the `entrypoint` command in the primary container image. |
| `cron` | `http-post` | Cron fires, POST to `${primary_url}${entrypoint}` with an invocation-key auth header. |
| `webhook` | `job` | External POST to `/api/app-instances/{id}/trigger/{name}` kicks off a job. |
| `webhook` | `http-post` | External POST is forwarded to the primary container endpoint. |

Webhook authentication uses HMAC-SHA256 of the request body against
`trigger_config.webhook_secret` in header `X-Tesslate-Signature`.

Ingestion is fast: `schedule_triggers.ingest_trigger_event()` does a single
INSERT to `ScheduleTriggerEvent`, and
`process_trigger_events_batch()` drains them into ARQ tasks using
`SELECT ... FOR UPDATE SKIP LOCKED`. See
`orchestrator/app/services/apps/schedule_triggers.py` and the routers
`app_schedules.py` / `app_triggers.py`.

Installers manage schedules from the My Apps UI; creators declare the
defaults and editability in the manifest. The `nightly_digest` seed at
`seeds/apps/nightly_digest/app.manifest.json` is a full headless cron example
(`surfaces: []`, one cron schedule).

## 15. Admin review

Tesslate staff drive the approval queue from these pages:

- `app/src/pages/AdminSubmissionWorkbenchPage.tsx` for stage advance and
  per-check triage.
- `app/src/pages/AdminMarketplaceReviewPage.tsx` for the Stage 3 final review.
- `app/src/pages/AdminYankCenterPage.tsx` for yank requests, appeals, and the
  two-admin rule for critical severity.
- `app/src/pages/AdminAdversarialSuitePage.tsx` for managing the Stage 2
  eval suite.
- `app/src/pages/AdminCreatorReputationPage.tsx` for creator reputation
  overrides and audits.

All of these sit behind superuser auth on the router side
(`orchestrator/app/routers/admin_marketplace.py`).

## 16. Where to next

- Messaging and chat integrations: `docs/orchestrator/routers/CLAUDE.md`
  (gateway.py, channels.py).
- External agent API if you want to trigger your installed app from outside
  OpenSail: `docs/orchestrator/routers/external-agent.md`.
- Deployment targets for apps that also publish a hosted build (Vercel,
  Netlify, Cloudflare): `docs/orchestrator/routers/CLAUDE.md` deployments.py.
- Desktop distribution if you want your app installable on the Tauri shell:
  `docs/desktop/CLAUDE.md`.
- Agent authoring reference for hosted-agent surfaces:
  `packages/tesslate-agent/docs/DOCS.md`.
