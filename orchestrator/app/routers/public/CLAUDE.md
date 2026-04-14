# Public API Routers

External API surface authenticated via `tsk_` `ExternalAPIKey` tokens. Consumed by the desktop app, SDKs, and on-prem clients. Internal routers (session-auth, cookie-auth) live in `orchestrator/app/routers/` one level up — do NOT mix the two.

## When to load this context

- Adding or modifying any endpoint under `/api/public/*` or `/api/v1/*`.
- Touching `ExternalAPIKey` scopes or adding a new `Permission` for external access.
- Working on desktop-client features (see `desktop-todo/PUBLIC_API_GAPS.md`).

## Current files

| File | Prefix | Purpose |
|------|--------|---------|
| `marketplace.py` | `/api/public/marketplace` | Browse agents, skills, bases, MCP servers, themes. Purchase-gated manifest/body downloads. |
| `models.py` | `/api/v1` | OpenAI-compatible `/chat/completions` proxy, `/models`, `/usage`. |
| `_shared.py` | — | Helpers: `add_cache_headers`, `apply_sort`, `ownership_filter`, `paginated_response`. |
| `__init__.py` | — | Exports `public_routers` list, consumed by `main.py`. |

## Conventions (enforce on every new file)

1. **One router per file.** No cross-cutting endpoints. Share logic via `services/public/` (not yet created — add when needed).
2. **URL prefix is declared in the router itself**, not in `main.py`. Use `APIRouter(prefix="/api/v1/...")`.
3. **Scope declaration at module top** as a constant, e.g. `REQUIRED_SCOPE = Permission.MARKETPLACE_READ`. Makes it greppable for security audits.
4. **Auth via `require_api_scope(Permission.X)`** dependency on every route. Never accept session auth here — these routers are `tsk_`-only.
5. **Cache headers** on GET endpoints via `_shared.add_cache_headers`. Desktop relies on ETag/Cache-Control for offline UX.
6. **Pagination** via `_shared.paginated_response`. Don't hand-roll.
7. **Register in `__init__.py`** by appending to `public_routers`. `main.py` iterates the list — never import individual routers into `main.py`.
8. **Tests live in `tests/public/`** mirroring this directory structure. Unit tests per file, integration tests in `tests/public/integration/`.

## Adding a new public router

1. Create `orchestrator/app/routers/public/<name>.py`.
2. Add `router = APIRouter(prefix="/api/v1/<name>", tags=["public-<name>"])`.
3. Add a new `Permission.<NAME>_<ACTION>` entry in `orchestrator/app/permissions.py` if a new scope is needed.
4. Import the router into `__init__.py` and append to `public_routers`.
5. Create `tests/public/test_<name>.py` and (if write surface) `tests/public/integration/test_<name>_integration.py`.
6. Document the endpoints in `desktop-todo/PUBLIC_API_GAPS.md` (crossing them off the planned list).

## Gotchas

- Relative imports go up **three** levels from this package: `from ...models import ...`, not `from ..`. Easy to miss after moving a file from the flat `routers/` layout.
- Response schemas for public endpoints should be stable — external clients pin to them. Prefer adding new fields over changing existing ones; deprecate before removing.
- Rate limiting and audit logging are not yet centralized. When `_deps.py` is introduced, existing endpoints should migrate to it.

## Related contexts

- `orchestrator/app/auth_external.py` — `require_api_scope` dependency, API key hashing.
- `orchestrator/app/permissions.py` — `Permission` enum.
- `orchestrator/app/routers/external_agent.py` — older `/api/external/*` agent API, candidate for migration into this package as a back-compat shim.
- `desktop-todo/PUBLIC_API_GAPS.md` — planned additions.
