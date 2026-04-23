# Tesslate Apps Routers

Tesslate Apps is the distribution/runtime system for user-built OpenSail projects published to the marketplace. The feature spans many routers; each file is small and single-purpose. For the full feature overview see [../../apps/CLAUDE.md](../../apps/CLAUDE.md).

## Router Index

| File | Base path | Purpose |
|------|-----------|---------|
| `marketplace_apps.py` | `/api/marketplace-apps` | Browse the app catalog (list, detail, versions) + storefront purchase handoff. |
| `app_versions.py` | `/api/app-versions` | Publish an immutable AppVersion, fetch version detail, run compatibility report. |
| `app_installs.py` | `/api/app-installs` | Install an app into a user/project, list installs, uninstall. |
| `app_runtime_status.py` | `/api/app-installs` (shared prefix) | Runtime status, SSE events, start/stop, per-install schedule rows. |
| `app_schedules.py` | `/api/app-installs` (shared prefix) | Schedule CRUD for an installed app instance. |
| `app_runtime.py` | `/api/apps/runtime` | Create/teardown app runtime sessions and invocations for the embedded runner. |
| `app_billing.py` | `/api/apps/billing` | Wallet, ledger, spend records, platform wallet (admin). |
| `app_submissions.py` | `/api/app-submissions` | Staged approval pipeline (stage0/stage1/stage2/advance/check runs). |
| `app_yanks.py` | `/api/app-yanks` | Yank/unpublish workflow (create, approve, reject, appeal, list). |
| `app_triggers.py` | `/api/app-instances/{id}/trigger/{name}` | External trigger endpoint (HMAC-authenticated per schedule key). |
| `app_bundles.py` | `/api/app-bundles` | Curated AppVersion bundles (create, list, get, publish, yank, install). |
| `admin_marketplace.py` | `/api/admin-marketplace` | Admin queue (submissions + yanks), monitoring runs, adversarial runs, reputation, stats. |

## Endpoints

### marketplace_apps.py

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `` | user | List published apps (paginated). |
| GET | `/{app_id}` | user | App detail. |
| GET | `/{app_id}/versions` | user | List AppVersions for an app. |
| POST | (storefront handoff) | user | Purchase / handoff (see source for route). |

### app_versions.py

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/publish` | user | Publish a new AppVersion (201). Stages CAS bundle + manifest. |
| GET | `/{app_version_id}` | user | Version detail. |
| GET | `/{app_version_id}/compat` | user | Compatibility report against current runtime. |

### app_installs.py

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/install` | user | Install an app (201); idempotent via `AppInstallAttempt` saga. |
| GET | `/mine` | user | List the caller's installs. |
| GET | `/{app_instance_id}` | user | Install detail. |
| POST | `/{app_instance_id}/uninstall` | user | Uninstall. |

### app_runtime_status.py

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/{instance_id}/runtime` | user | Runtime status. |
| GET | `/{instance_id}/events` | user | SSE event stream (runtime + schedule events). |
| POST | `/{instance_id}/start` | user | Start (202). |
| POST | `/{instance_id}/stop` | user | Stop. |
| GET | `/{instance_id}/schedules` | user | Schedules bound to this install. |
| PATCH | `/{instance_id}/schedules/{schedule_id}` | user | Update a schedule. |

### app_schedules.py

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | (list) | user | Schedules for an app install. |
| POST | (create) | user | Add a schedule. |
| POST | (lifecycle) | user | See source for pause/trigger operations. |

### app_runtime.py

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | (sessions) | user | Start a runtime session. |
| DELETE | `/sessions/{session_id}` | user | End a runtime session. |
| POST | (invocations) | user | Invoke a registered action inside a session. |
| DELETE | `/invocations/{session_id}` | user | Cancel an invocation. |

### app_billing.py

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/wallet` | user | User wallet state. |
| GET | `/wallet/creator` | creator | Creator wallet state. |
| GET | `/wallet/ledger` | user | Ledger rows. |
| GET | `/spend` | user | Spend rollups. |
| GET | `/spend/summary` | user | Summary. |
| POST | `/spend/record` | service | Record a spend entry (201). |
| GET | `/wallet/admin/platform` | admin | Platform-wide wallet. |

### app_submissions.py

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/` | admin | Queue list. |
| GET | `/{submission_id}` | admin | Submission detail. |
| POST | `/{submission_id}/advance` | admin | Advance stage. |
| POST | `/{submission_id}/checks` | admin | Record a per-stage check. |
| POST | `/{submission_id}/scan/stage1` | admin | Kick off Stage 1 scanner. |
| POST | `/{submission_id}/scan/stage2` | admin | Kick off Stage 2 sandbox run. |

### app_yanks.py

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/` | admin | Create a yank request. |
| POST | `/{yank_request_id}/approve` | admin | Approve (critical needs 2 admins). |
| POST | `/{yank_request_id}/reject` | admin | Reject. |
| POST | `/{yank_request_id}/appeal` | creator | Creator appeal. |
| GET | `/` | admin | List yank requests. |

### app_triggers.py

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/app-instances/{id}/trigger/{name}` | HMAC | External trigger fire; HMAC-SHA256 over the raw body with a per-schedule key. |

### app_bundles.py

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `` | admin | Create a bundle (201). |
| GET | `` | user | List bundles. |
| GET | `/{bundle_id}` | user | Bundle detail. |
| POST | `/{bundle_id}/publish` | admin | Publish (204). |
| POST | `/{bundle_id}/yank` | admin | Yank (204). |
| POST | `/{bundle_id}/install` | user | Install all bundle items. |

### admin_marketplace.py

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/queue` | admin | Submission queue. |
| GET | `/yank-queue` | admin | Yank queue. |
| POST | `/monitoring/runs` | admin | Record a monitoring run. |
| PATCH | `/monitoring/runs/{run_id}` | admin | Update monitoring run (204). |
| POST | `/adversarial/runs` | admin | Launch an adversarial run. |
| POST | `/reputation/{user_id}` | admin | Adjust creator reputation (204). |
| GET | `/stats` | admin | Admin dashboard stats. |

## Auth

- Mutating operations under `/api/app-*` require `current_active_user` and ownership (install-owner or creator).
- `admin_marketplace.py` and submission/yank workflows require `current_superuser`.
- `app_triggers.py` is HMAC-authenticated, not user-scoped.
- `spend/record` is service-scoped (called by the runner, not end users).

## Related

- Models: `MarketplaceApp`, `AppVersion`, `AppInstance`, `AppInstallAttempt`, `AppSubmission`, `SubmissionCheck`, `YankRequest`, `YankAppeal`, `AppBundle`, `AppBundleItem` in [models.py](../../../orchestrator/app/models.py).
- Services: `services/apps/` (installer, publisher, submissions, yanks, bundles, runtime, stage1/2 scanners, schedule triggers).
- Feature overview: [../../apps/CLAUDE.md](../../apps/CLAUDE.md).
