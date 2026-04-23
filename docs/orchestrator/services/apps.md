# Tesslate Apps Services

**Directory**: `orchestrator/app/services/apps/`

Service layer for the OpenSail Tesslate Apps feature: publish a project as an app, run approvals, install, run, meter, bill, and unpublish.

## When to load

Load this doc when:
- Working on the publish, install, approval, or yank flow.
- Adding a new check to the staged approval pipeline.
- Modifying LiteLLM key minting for hosted agents or app runtime sessions.
- Changing app billing dispatch, settlement, or spend metering.

## File map

### Publish and fork

| File | Purpose |
|------|---------|
| `publisher.py` | Promote an `app_source` project into a new immutable `AppVersion`. Writes CAS bundle, computes semver, enforces manifest validation. |
| `fork.py` | Fork a `MarketplaceApp` into a new creator-owned row (creates a new app identity plus first version draft). |
| `bundles.py` | Curator-authored collections of AppVersions (`AppBundle`, `AppBundleItem`). CRUD plus install-as-a-bundle. |
| `reserved_handles.py` | Static list of handles that cannot be claimed by users or apps (e.g. `admin`, `api`). |

### Manifest

| File | Purpose |
|------|---------|
| `app_manifest.py` | Pydantic mirror of `app_manifest_2025_01.schema.json`. Typed view used after structural validation. |
| `manifest_parser.py` | Two-layer validator: JSON Schema (hash-pinned) then Pydantic. Entry point for reading `app.manifest.json`. |
| `manifest_merger.py` | Publish-time merger: `.tesslate/config.json` + creator overrides: `app.manifest.json` (schema 2025-02). |
| `compatibility.py` | Pure `AppVersion` compatibility check against current Studio feature flags. Wraps `app.config_features`. |

### Install saga

| File | Purpose |
|------|---------|
| `installer.py` | Single-transaction installer: materializes an approved `AppVersion` into a user `Project`. Uses `AppInstallAttempt` saga ledger. |
| `install_reaper.py` | Orphan reaper for the installer saga; cleans up `AppInstallAttempt` rows where install crashed between volume create and project commit. |
| `source_view.py` | Listing source files for an installed app; enforces `source_visibility` policy from the manifest. |
| `env_resolver.py` | Resolves `Container.environment_vars` into K8s `V1EnvVar` entries, expanding `${secret:<name>/<key>}` to `valueFrom.secretKeyRef`. |
| `secret_propagator.py` | Copies platform `Secret`s referenced by the manifest into the project namespace so `secretKeyRef` works (K8s secrets are namespace-local). |
| `project_scopes.py` | Project-vs-App boundary helpers. Filters out `app_instance` projects from lists meant to show only user-authored projects. |

### Approval pipeline

| File | Purpose |
|------|---------|
| `submissions.py` | Stage machine: `stage0 -> stage1 -> stage2 -> stage3 -> approved\|rejected`. Enforces `VALID_TRANSITIONS` and terminal states. |
| `stage1_scanner.py` | Stage1 "AI-assisted review" scanner. Deterministic structural scan (manifest, permissions, reserved paths). |
| `stage2_sandbox.py` | Stage2 "sandbox eval" runner. Deterministic scoring stub; executes the app in an ephemeral sandbox namespace. |
| `monitoring.py` | `MonitoringRun` / `AdversarialRun` primitives + creator-reputation helpers. |
| `monitoring_sweep.py` | Periodic canary sweep that re-runs the adversarial suite against an already-approved `AppVersion`. |
| `_auto_approve_flag.py` | Single source of truth for `TSL_APPS_DEV_AUTO_APPROVE` / `TSL_APPS_SKIP_APPROVAL` dev-mode flags. |

### Yanks

| File | Purpose |
|------|---------|
| `yanks.py` | Yank workflow with two-admin rule for `critical` severity. Handles `YankRequest`, `YankAppeal`. |

### Runtime

| File | Purpose |
|------|---------|
| `runtime.py` | App runtime session lifecycle: mint session-tier or invocation-tier LiteLLM key, attach to running `AppInstance`. |
| `runtime_urls.py` | Single source of truth for container preview URL shape. Shared by `compute_manager` (pod/ingress) and routers (runtime API). |
| `hosted_agent_runtime.py` | Mint LiteLLM keys for manifest-declared hosted agents (`compute.hosted_agents[*]`). |
| `warm_pool.py` | DB-backed pre-minted invocation keys per hosted agent to cut cold-start latency. |
| `key_lifecycle.py` | Pure state machine for the three-tier LiteLLM key model (session / invocation / nested). No DB or I/O: consumed by `litellm_keys.py`. |
| `app_invocations.py` | Scheduled/webhook dispatch into a running `AppInstance`. Scheduler enqueues `invoke_app_instance_task` per trigger. |
| `schedule_triggers.py` | Ingestion + draining worker for app schedule triggers (two entrypoints). |

### Billing and events

| File | Purpose |
|------|---------|
| `billing_dispatcher.py` | Resolves who pays (creator, installer, team) per spend dimension declared in an `AppInstance`'s `wallet_mix`. |
| `settlement_worker.py` | Sweeps unsettled `spend_records` rows into `wallet_ledger_entries` on a timer. |
| `event_bus.py` | Producer for Postgres row: Redis Streams fanout. Whitelisted tables only. |
| `db_event_dispatcher.py` | ARQ cron task that drains `tesslate:db_events:*` Streams and dispatches to subscribers. |
| `audit.py` | Thin audit logger for Tesslate Apps events. Uses `AuditLog` from `models_team`. |

## Callers

| Caller | Service(s) used |
|--------|-----------------|
| `routers/app_versions.py` | `publisher`, `manifest_parser`, `compatibility` |
| `routers/app_submissions.py` | `submissions`, `stage1_scanner`, `stage2_sandbox`, `monitoring` |
| `routers/app_installs.py` | `installer`, `env_resolver`, `secret_propagator`, `source_view` |
| `routers/app_runtime.py` | `runtime`, `runtime_urls`, `hosted_agent_runtime`, `warm_pool`, `app_invocations` |
| `routers/app_yanks.py` | `yanks` |
| `routers/app_bundles.py` | `bundles` |
| `routers/app_billing.py` | `billing_dispatcher`, `settlement_worker` |
| ARQ cron | `monitoring_sweep`, `settlement_worker`, `db_event_dispatcher`, `schedule_triggers`, `install_reaper` |
| `services/litellm_keys.py` | `key_lifecycle` (pure FSM) |

## Related

- [../../apps/CLAUDE.md](../../apps/CLAUDE.md): feature-level overview of Tesslate Apps.
- [litellm.md](./litellm.md): LiteLLM proxy integration; `litellm_keys.py` wires `key_lifecycle` to the proxy.
- [volume-manager.md](./volume-manager.md): `installer` uses `hub_client.create_volume_from_bundle` for CAS restore.
