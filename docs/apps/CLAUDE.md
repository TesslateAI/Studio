# Purpose

Tesslate Apps turns Studio projects into distributable marketplace apps. A creator builds a project normally, publishes it as a versioned App, and end users install it from the marketplace. Each install materializes a new isolated Project backed by its own Hub volume. The feature is layered over the existing Project/Container/Volume infrastructure.

# Key Files

## Services (orchestrator/app/services/apps/)

| File | Role |
|------|------|
| `publisher.py` | `publish_version()` — parses manifest, compat-checks, writes `AppVersion(pending_stage1)` + `AppSubmission(stage0)`, publishes bundle to Hub |
| `installer.py` | `install_app()` — approval gate, compat re-check, Hub volume restore, creates `Project(app_role=app_instance)` + `AppInstance` |
| `submissions.py` | Stage state machine: `advance_stage()`, `record_check()`, `VALID_TRANSITIONS` dict |
| `stage1_scanner.py` | `run_stage1_scan()` — deterministic structural checks: manifest parse, feature support, MCP scope, disclosure, billing dims |
| `stage2_sandbox.py` | `run_stage2_eval()` — adversarial suite runner (stub score 0.7 in Wave 7; `STAGE2_SCORE_THRESHOLD = 0.5`) |
| `yanks.py` | `request_yank/approve_yank/reject_yank/file_appeal` — critical severity requires two distinct admin approvals |
| `bundles.py` | `create_bundle/publish_bundle/yank_bundle` — curated collections of AppVersions installed as a unit |
| `fork.py` | `fork_app()` — clones source AppVersion bundle to a new `app_source` Project for the forker |
| `runtime.py` | `mint_session/mint_invocation` — creates scoped LiteLLM keys per AppInstance, validates app is not yanked/deprecated |
| `billing_dispatcher.py` | `record_spend()` — appends unsettled `SpendRecord` rows; resolves payer from `wallet_mix` per dimension |
| `settlement_worker.py` | `settle_spend_batch()` (ARQ task) — debit payer, credit creator (net markup), credit platform; `SELECT ... FOR UPDATE SKIP LOCKED` |
| `compatibility.py` | `check()` — pure compat report (no I/O); compares manifest `required_features` + schema against current server |
| `manifest_parser.py` | `parse()` — validates raw JSON manifest against schema, returns typed `AppManifest` |
| `app_manifest.py` | Pydantic mirror of `app_manifest_2025_01.schema.json`; source of truth for manifest field names |
| `schedule_triggers.py` | `ingest_trigger_event()` / `process_trigger_events_batch()` — webhook → ARQ dispatch via `SKIP LOCKED` batch drain |
| `install_reaper.py` | Background sweep — orphaned `AppInstallAttempt(hub_created)` rows → Hub volume delete → mark `reaped` |
| `monitoring.py` / `monitoring_sweep.py` | Post-approval health monitoring for live AppVersions |
| `warm_pool.py` | Pre-warmed agent instances for hosted-agent compute model |
| `env_resolver.py` | Resolves connector env vars from consent record into container env |
| `secret_propagator.py` | Propagates resolved secrets into K8s pod environment at runtime |
| `key_lifecycle.py` | LiteLLM key state machine: `KeyTier` (session/invocation/nested), `KeyState` |
| `_auto_approve_flag.py` | `is_auto_approve_enabled()` — reads `TSL_APPS_DEV_AUTO_APPROVE` (or deprecated `TSL_APPS_SKIP_APPROVAL`) |

## Manifest Schemas

| File | Schema Version |
|------|---------------|
| `services/apps/app_manifest_2025_01.schema.json` | `2025-01` |
| `services/apps/app_manifest_2025_02.schema.json` | `2025-02` |

Key manifest sections: `meta`, `compatibility`, `surfaces`, `compute`, `state`, `connectors`, `billing`, `schedules`, `source_visibility`, `migrations`.

## Routers (orchestrator/app/routers/)

| Router | Prefix | Purpose |
|--------|--------|---------|
| `marketplace_apps.py` | `/api/apps/marketplace` | Browse, inspect, fork apps |
| `app_versions.py` | `/api/apps/versions` | List/get versions per app |
| `app_submissions.py` | `/api/apps/submissions` | Stage advance + check recording (admin-gated) |
| `app_installs.py` | `/api/apps/installs` | Install, list-mine, uninstall |
| `app_runtime.py` | `/api/apps/runtime` | Mint session/invocation keys |
| `app_runtime_status.py` | `/api/apps/runtime-status` | Per-instance liveness + primary URL |
| `app_billing.py` | `/api/apps/billing` | Wallet, spend records, ledger |
| `app_bundles.py` | `/api/apps/bundles` | Bundle CRUD + publish/yank |
| `app_yanks.py` | `/api/apps/yanks` | Yank request lifecycle |
| `app_schedules.py` | `/api/apps/schedules` | Schedule trigger management per instance |
| `app_triggers.py` | `/api/apps/triggers` | Inbound trigger event ingestion |
| `admin_marketplace.py` | `/api/admin/marketplace` | Admin workbench: review queue, yank queue, monitoring (superuser only) |
| `creators.py` | `/api/creators` | Public creator profile (agents, bases, themes — not apps-specific) |

# Data Models

## Core (orchestrator/app/models.py)

| Model | Table | Key Columns |
|-------|-------|-------------|
| `MarketplaceApp` | `marketplace_apps` | `slug`, `state` (draft/pending_stage1/.../approved/deprecated/yanked), `forkable` (true/restricted/no), `visibility` (public/private/team:\<uuid\>), `forked_from`, `handle`, `reputation` JSON |
| `AppVersion` | `app_versions` | `version`, `manifest_json`, `manifest_hash`, `bundle_hash`, `feature_set_hash`, `approval_state` (pending_stage1/stage1_approved/pending_stage2/stage2_approved/rejected/yanked), `yanked_is_critical`, `yanked_second_admin_id` |
| `AppInstance` | `app_instances` | `state` (installing/installed/upgrading/uninstalled/error), `update_policy` (manual/patch-auto/minor-auto/pinned), `wallet_mix` JSON, `consent_record` JSON, `volume_id`, `primary_container_id` |
| `AppInstallAttempt` | `app_install_attempts` | Saga ledger: `state` (hub_created/committed/reaped/reap_failed). Hub volume ID stored here before DB commit; reaper cleans orphans. |
| `AppSubmission` | `app_submissions` | `stage` (stage0–stage3/approved/rejected), `decision`, `reviewer_user_id`, `decision_notes` |
| `SubmissionCheck` | `submission_checks` | `check_name`, `status` (passed/failed/warning/errored), `details` JSON |
| `YankRequest` | `yank_requests` | `severity` (low/medium/critical), `status`, first + second admin IDs; DB CHECK `ck_yank_critical_two_admin` |
| `YankAppeal` | `yank_appeals` | 1:1 appeal on a `YankRequest` |
| `AppBundle` | `app_bundles` | `slug`, `state`, `consolidated_manifest_hash` (order-independent hash of member hashes) |
| `AppBundleItem` | `app_bundle_items` | `order_index`, `default_enabled`, `required` |
| `McpConsentRecord` | `mcp_consent_records` | Per-install scoped MCP consent grant |
| `Wallet` | `wallets` | `owner_type` (creator/platform/installer), `balance_usd`, `state` |
| `WalletLedgerEntry` | `wallet_ledger_entries` | Append-only, positive=credit/negative=debit |
| `SpendRecord` | `spend_records` | `dimension`, `payer`, `gross_usd`, `markup_pct`, `settled_at`; no FK to `app_instances` yet |
| `LiteLLMKeyLedger` | `litellm_key_ledger` | `tier` (session/invocation/nested), `budget_usd`, `app_instance_id` |
| `AdversarialSuite` | `adversarial_suites` | Named+versioned test suite pinned by CAS hash; used by stage2 |
| `ScheduleTriggerEvent` | `schedule_trigger_events` | Inbound trigger events queued for `AgentSchedule` dispatch |

## Project.app_role

The `Project` model has `app_role = Column(String(20), default="none")`:

| Value | Meaning |
|-------|---------|
| `"none"` | Ordinary user project (default) |
| `"app_source"` | Authoring project; creator publishes `AppVersion`s from it |
| `"app_instance"` | Runtime mount of an installed `AppVersion` (one per install) |

# Core Flows

## 1. Publish (creator)

```
Creator calls POST /api/apps/versions/publish
  └─> publisher.publish_version()
        1. parse_manifest() — validate against JSON Schema
        2. compatibility.check() — required_features vs server
        3. Load Project(app_role=app_source), assert volume_id present
        4. get-or-create MarketplaceApp (by slug)
        5. Guard duplicate (app_id, version)
        6. hub_client.publish_bundle() — persist bundle to Hub/CAS
        7. INSERT AppVersion(approval_state=pending_stage1)
        8. INSERT AppSubmission(stage=stage0)
  └─> Caller commits. stage1_scanner triggered (background or admin action).
```

## 2. Approval Pipeline

```
Stage0 (auto): stage1_scanner.run_stage1_scan()
  Checks: manifest_parses, features_supported, mcp_scope_safe_list (warn),
          disclosure_present, billing_dims_have_payer
  Pass → advance to stage1; any hard fail → rejected

Stage1 (admin policy): admin reviews via admin_marketplace workbench
  POST /api/admin/marketplace/submissions/{id}/advance {stage: "stage2"}

Stage2 (sandbox eval): stage2_sandbox.run_stage2_eval()
  Adversarial suite score >= STAGE2_SCORE_THRESHOLD (0.5)
  Pass → advance to stage3

Stage3 (admin final): admin final review → "approved" or "rejected"
  approved → AppVersion.approval_state = "stage2_approved"
              MarketplaceApp.state = "approved"
```

Dev bypass: `TSL_APPS_DEV_AUTO_APPROVE=1` skips all stages (blocked if `app_base_url` uses HTTPS).

## 3. Install (end user)

```
User calls POST /api/apps/installs
  body: {app_version_id, team_id, wallet_mix_consent, mcp_consents, update_policy}

  └─> installer.install_app()
        1. Approval gate: approval_state in {stage1_approved, stage2_approved}
        2. compatibility.check() — re-validate at install time
        3. Dedupe: AlreadyInstalledError if active instance exists
        4. hub_client.restore_bundle() → new volume (AppInstallAttempt hub_created)
        5. INSERT Project(app_role=app_instance) + Containers from manifest compute.containers
        6. INSERT AppInstance(state=installed) + McpConsentRecord rows
        7. AppInstallAttempt → committed
  └─> Returns: {app_instance_id, project_id, volume_id, node_name}
```

Orphan cleanup: `install_reaper` sweeps `AppInstallAttempt(hub_created)` with no linked instance → calls `hub_client.delete_volume()` → marks `reaped`.

## 4. Runtime (installed app)

```
POST /api/apps/runtime/sessions   → mint_session() — session-tier LiteLLM key
POST /api/apps/runtime/invocations → mint_invocation() — invocation-tier key

Validates: AppInstance.state == "installed", MarketplaceApp.state not in {yanked, deprecated}
Returns: {session_id, api_key, budget_usd, ttl_seconds}
  api_key returned ONCE only — caller must cache it.
```

## 5. Billing

```
Dimensions: ai_compute | general_compute | storage | egress | mcp_tool_call | platform_fee
Payers:     creator | platform | installer | byok

billing_dispatcher.record_spend()
  → appends SpendRecord (unsettled)

settlement_worker.settle_spend_batch() [ARQ, ~15s interval]
  → debit payer wallet
  → credit creator wallet at (gross * (1 - markup_pct))
  → credit platform wallet at (gross * markup_pct)
  BYOK + ai_compute = no-op (reason='byok_no_op')
  Uses SELECT ... FOR UPDATE SKIP LOCKED (multi-worker safe)
```

Split: 10% platform / 90% creator (configured via `markup_pct` in `wallet_mix`).

## 6. Yank Workflow

```
POST /api/apps/yanks         → request_yank(severity)
POST /api/apps/yanks/{id}/approve → approve_yank(admin_id)
  - low/medium: single admin approval
  - critical: requires TWO distinct admins (NeedsSecondAdminError on same admin)
POST /api/apps/yanks/{id}/reject  → reject_yank()
POST /api/apps/yanks/{id}/appeal  → file_appeal()

On approval: AppVersion.yanked_at set, state → "yanked"
```

## 7. Fork

```
POST /api/apps/marketplace/{slug}/fork
  └─> fork.fork_app()
        1. Assert source app forkable in {"true", "restricted"}
        2. hub_client.restore_bundle() → new volume for forker
        3. INSERT MarketplaceApp(state=draft, forked_from=source_app_id)
        4. INSERT Project(app_role=app_source) for forker to edit
```

## 8. Bundles

Groups of AppVersions installed as a unit. `consolidated_manifest_hash` is sorted over member hashes (order-independent dedup). Draft → approved | yanked via admin gate.

## 9. Schedule Triggers

`ScheduleTriggerEvent` rows ingested via `ingest_trigger_event()` (fast INSERT). Drained by `process_trigger_events_batch()` into ARQ agent tasks via `SELECT ... FOR UPDATE SKIP LOCKED`.

# Related Contexts

- `docs/orchestrator/models/CLAUDE.md` — full model reference
- `docs/orchestrator/routers/CLAUDE.md` — router conventions, auth dependencies
- `docs/orchestrator/services/config-json.md` — `.tesslate/config.json` schema (used by installer to materialize containers)
- `docs/orchestrator/services/worker.md` — ARQ worker, `settle_spend_batch` task registration
- `docs/orchestrator/orchestration/CLAUDE.md` — container lifecycle after install
- `orchestrator/app/services/apps/app_manifest_2025_01.schema.json` — canonical manifest schema

# When to Load

Load this context when:
- Building or debugging any `/api/apps/*` or `/api/admin/marketplace/*` endpoint
- Working on publisher, installer, submission pipeline, or yank workflow
- Modifying billing dimensions, wallet settlement, or spend attribution
- Changing manifest schema or compatibility checks
- Debugging install failures, orphaned Hub volumes, or reaper logic
- Adding new manifest surface kinds (`ui`, `chat`, `scheduled`, `triggered`, `mcp-tool`)
- Working on the admin review workbench or approval stage transitions
