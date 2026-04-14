# Public API Services

Business logic backing `orchestrator/app/routers/public/*`. One service module per router surface — routers stay thin (auth + validation + HTTP shape), services own the DB work, external calls, and pure helpers.

## When to load this context

- Adding, modifying, or debugging logic behind any `/api/v1/*` or `/api/public/*` endpoint.
- Deciding where a helper belongs when the router is starting to accumulate non-HTTP logic.
- Writing tests that exercise service functions directly rather than going through the router.

## Current modules

| File | Backs | Purpose |
|------|-------|---------|
| `marketplace_install_service.py` | `routers/public/marketplace_install.py` | Resolve marketplace items by `{item_type, slug}`, enforce paid-item gates, record `UserPurchasedAgent` / `UserPurchasedBase` rows, build desktop download URLs. |
| `sync_service.py` | `routers/public/projects_sync.py` | Content-addressable storage for sync zip blobs, SHA-256 key derivation, manifest-diff conflict detection. Default backend is filesystem-rooted at `PROJECT_SYNC_STORAGE_ROOT`; swap with `set_sync_storage(...)` in tests. |

## Conventions

1. **One service per router.** Name it `<router_stem>_service.py` so the pairing is obvious (`agents.py` → `agents_service.py`). Share helpers across services through a smaller internal module only when genuinely cross-cutting.
2. **Pure functions + thin classes.** Services should be easy to call from tests without spinning up FastAPI. Pass the `AsyncSession` in; do not reach for request state.
3. **Raise `HTTPException` for user-facing errors.** Routers already understand it, and skipping the re-wrap in the router keeps call sites short. Use 4xx for client errors (missing item, unpaid gate), never 5xx for expected states.
4. **Inject pluggable backends.** External side effects (CAS writes, S3 uploads, subprocess calls) go behind a protocol + module-level getter/setter pair (`get_sync_storage` / `set_sync_storage`). Tests swap the implementation at setup; production picks up the real one lazily.
5. **No FastAPI imports beyond `HTTPException`.** If you find yourself importing `Request`, `Depends`, or `BackgroundTasks` here, the logic belongs in the router.
6. **Non-blocking side effects.** Audit writes, telemetry, and pub/sub fanout wrap in `try/except` + `logger.debug(..., exc_info=True)`. Never let an audit failure break the primary operation.
7. **Typed protocols over ABCs** for backend interfaces (`Protocol` from `typing`). Keeps the module loosely coupled and pytest fixtures don't need to subclass anything.

## Adding a new service

1. Create `<name>_service.py`. Stick to the `async def` + helper-function style you see in the existing modules.
2. Expose only what the router consumes via `__all__`.
3. Write unit tests in `orchestrator/tests/public/test_<router_name>.py` that exercise the service functions directly alongside the integration tests for the router.
4. If the service owns a pluggable backend, add `set_<backend>(...)` to the export surface so integration tests can inject an in-memory double.

## Gotchas

- **Relative imports** from this package go up **three** levels (`from ...models import ...`, `from ...permissions import Permission`). Same rule as `routers/public/*.py`.
- Models that already ship inside `orchestrator/app/models.py` live at `from ...models import Foo` — there is no `models/` package. Don't create one.
- The sync storage root is filesystem-based by default. In Kubernetes deployments we'll eventually front this with the Volume Hub CAS path (`services/btrfs-csi/pkg/cas/`); until then, treat `PROJECT_SYNC_STORAGE_ROOT` as an ops-owned durable mount.
- Scope + audit-log enforcement lives in the **router**, not the service. Services assume the caller is already authorized — do not duplicate scope checks here.

## Related contexts

- `orchestrator/app/routers/public/CLAUDE.md` — router conventions and URL rules.
- `orchestrator/app/routers/public/_deps.py` — `scoped(Permission)`, `audit_write(...)`, rate limiter. Services don't import these; routers pass through the scoped `User` and `AsyncSession`.
- `orchestrator/tests/public/CLAUDE.md` — test layout mirroring the router structure.
