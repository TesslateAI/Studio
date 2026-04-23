# Orchestrator Routers

API routers for OpenSail's FastAPI backend. Each module exposes an `APIRouter` that `orchestrator/app/main.py` includes once.

## Layout

```
orchestrator/app/routers/
├── <flat modules>.py   # Cookie/session or tsk-auth API endpoints
├── desktop/            # Desktop sidecar routes (session auth via Tauri shell)
└── public/             # tsk-key authenticated external API (/api/public, /api/v1)
```

## Full Router Index

Every router file in `orchestrator/app/routers/` (and its `desktop/` and `public/` subpackages) maps to a documentation entry below. Files grouped into a single doc (Tesslate Apps, desktop package, public package) are listed in that doc's File Index.

### Top-level routers (`orchestrator/app/routers/*.py`)

| File | Base path | Doc |
|------|-----------|-----|
| `admin.py` | `/api/admin` | [admin.md](admin.md) |
| `admin_marketplace.py` | `/api/admin-marketplace` | [apps.md](apps.md) |
| `agent.py` | `/api/agent` | [agent.md](agent.md) |
| `agents.py` | `/api/agents` | [agents.md](agents.md) |
| `app_billing.py` | `/api/apps/billing` | [apps.md](apps.md) |
| `app_bundles.py` | `/api/app-bundles` | [apps.md](apps.md) |
| `app_installs.py` | `/api/app-installs` | [apps.md](apps.md) |
| `app_runtime.py` | `/api/apps/runtime` | [apps.md](apps.md) |
| `app_runtime_status.py` | `/api/app-installs` | [apps.md](apps.md) |
| `app_schedules.py` | `/api/app-installs` | [apps.md](apps.md) |
| `app_submissions.py` | `/api/app-submissions` | [apps.md](apps.md) |
| `app_triggers.py` | `/api/app-instances/{id}/trigger/{name}` | [apps.md](apps.md) |
| `app_versions.py` | `/api/app-versions` | [apps.md](apps.md) |
| `app_yanks.py` | `/api/app-yanks` | [apps.md](apps.md) |
| `auth.py` | `/api/auth` | [auth.md](auth.md) |
| `billing.py` | `/api/billing` | [billing.md](billing.md) |
| `channels.py` | `/api/channels` | [channels.md](channels.md) |
| `chat.py` | `/api/chat` | [chat.md](chat.md) |
| `creators.py` | `/api/creators` | [creators.md](creators.md) |
| `deployment_credentials.py` | `/api/deployment-credentials` | [deployment-credentials.md](deployment-credentials.md) |
| `deployment_oauth.py` | `/api/deployment-oauth` | [deployment-oauth.md](deployment-oauth.md) |
| `deployment_targets.py` | `/api/projects/{slug}/deployment-targets` | [deployment-targets.md](deployment-targets.md) |
| `deployments.py` | `/api/deployments` | [deployments.md](deployments.md) |
| `design.py` | `/api/projects/{slug}/design` | [design.md](design.md) |
| `desktop_pair.py` | `/api/desktop`, `/api/v1/desktop` | [desktop.md](desktop.md) |
| `external_agent.py` | `/api/external` | [external-agent.md](external-agent.md) |
| `feature_flags.py` | `/api/feature-flags` | [feature-flags.md](feature-flags.md) |
| `feedback.py` | `/api/feedback` | [feedback.md](feedback.md) |
| `gateway.py` | `/api/gateway` | [gateway.md](gateway.md) |
| `git.py` | `/api/git` | [git.md](git.md) |
| `git_providers.py` | `/api/git-providers` | [git-providers.md](git-providers.md) |
| `github.py` | `/api/github` | [github.md](github.md) |
| `internal.py` | `/api/internal` | [internal.md](internal.md) |
| `kanban.py` | `/api/kanban` | [kanban.md](kanban.md) |
| `magic_link.py` | `/api/auth/magic-link` | [magic-link.md](magic-link.md) |
| `marketplace.py` | `/api/marketplace` | [marketplace.md](marketplace.md) |
| `marketplace_apps.py` | `/api/marketplace-apps` | [apps.md](apps.md) |
| `marketplace_local.py` | `/api/desktop/marketplace` | [desktop.md](desktop.md) |
| `mcp.py` | `/api/mcp` | [mcp.md](mcp.md) |
| `mcp_oauth.py` | `/api/mcp/oauth` | [mcp-oauth.md](mcp-oauth.md) |
| `mcp_server.py` | `/api/mcp-servers`, `/api/mcp/server` | [mcp.md](mcp.md) |
| `node_config.py` | `/api/chat/node-config`, `/api/projects/*/containers/*/config` | [node-config.md](node-config.md) |
| `projects.py` | `/api/projects` | [projects.md](projects.md) |
| `proxy.py` | `/v1` | [proxy.md](proxy.md) |
| `referrals.py` | `/api` | [referrals.md](referrals.md) |
| `schedules.py` | `/api/schedules` | [schedules.md](schedules.md) |
| `secrets.py` | `/api/secrets` | [secrets.md](secrets.md) |
| `shell.py` | `/api/shell` | [shell.md](shell.md) |
| `snapshots.py` | `/api/projects/{id}/snapshots` | [snapshots.md](snapshots.md) |
| `tasks.py` | `/api/tasks` | [tasks.md](tasks.md) |
| `teams.py` | `/api/teams` | [teams.md](teams.md) |
| `terminal.py` | `/api/terminal` | [terminal.md](terminal.md) |
| `test_helpers.py` | `/api/__test__` | [test-helpers.md](test-helpers.md) |
| `themes.py` | `/api/themes` | [themes.md](themes.md) |
| `two_fa.py` | `/api/auth` | [two-fa.md](two-fa.md) |
| `users.py` | `/api/users` | [users.md](users.md) |
| `version.py` | `/api/version` | [version.md](version.md) |
| `webhooks.py` | `/api/webhooks` | [webhooks.md](webhooks.md) |

### Desktop subpackage (`orchestrator/app/routers/desktop/*.py`)

All submodules mount under `/api/desktop` via `desktop/__init__.py`. See [desktop.md](desktop.md).

| File | Purpose |
|------|---------|
| `desktop/__init__.py` | Assembles the desktop router. |
| `desktop/_helpers.py` | Shared helpers (probe, git root, serializers). |
| `desktop/auth.py` | Cloud pairing auth shim. |
| `desktop/directories.py` | Connected directories CRUD. |
| `desktop/handoff.py` | Local/cloud agent handoff. |
| `desktop/projects.py` | Folder import + sync endpoints. |
| `desktop/sessions.py` | Agent sessions + ticket diff. |
| `desktop/tickets.py` | Agent tickets list + approve. |
| `desktop/tray.py` | Runtime probe + tray state. |

### Public subpackage (`orchestrator/app/routers/public/*.py`)

All modules are tsk-auth and registered via `public/__init__.py`. See [public.md](public.md).

| File | Prefix |
|------|--------|
| `public/__init__.py` | (aggregator) |
| `public/_deps.py` | (helpers) |
| `public/_shared.py` | (helpers) |
| `public/agents.py` | `/api/v1/agents` |
| `public/agents_handoff.py` | `/api/v1/agents/handoff` |
| `public/k8s_projects.py` | `/api/v1/k8s/projects` |
| `public/marketplace.py` | `/api/public/marketplace` |
| `public/marketplace_install.py` | `/api/v1/marketplace` |
| `public/models.py` | `/api/v1` |
| `public/projects_sync.py` | `/api/v1/projects/sync` |

## Common Patterns

### Authentication

All cookie/session routers inject the current user via FastAPI dependencies:

```python
from ..users import current_active_user, current_superuser

@router.get("/endpoint")
async def my_endpoint(
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    ...
```

- `current_active_user`: JWT (cookie or bearer).
- `current_superuser`: platform admin.
- `current_optional_user`: public endpoints that add user-specific context when logged in.
- `require_api_scope(Permission.X)`: tsk-key API (used by `public/`, `proxy.py`, `external_agent.py`).
- HMAC signature: `app_triggers.py` (per-schedule key over raw body).
- Internal shared secret: `internal.py` (`verify_internal_secret`).
- Provider signature: `webhooks.py` (Stripe), `channels.py` (Telegram/Slack/Discord/WhatsApp).

### Database Session

```python
from ..database import get_db

async def handler(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Model).where(...))
    return result.scalars().all()
```

### Background Tasks

For short fire-and-forget work use FastAPI `BackgroundTasks`. For long-running agent tasks, enqueue via ARQ (cloud) or the local asyncio queue (desktop); clients poll `/api/tasks/{task_id}/status` or subscribe to SSE.

### Streaming

Agent and logs streams use Server-Sent Events:

```python
from fastapi.responses import StreamingResponse

async def gen():
    yield f"data: {json.dumps(event)}\n\n"

return StreamingResponse(gen(), media_type="text/event-stream")
```

### WebSocket

Used for interactive terminal, container log streaming, and progress channels. Auth is passed via query parameter.

### Pagination

```python
@router.get("/items")
async def list_items(skip: int = Query(0, ge=0), limit: int = Query(20, le=100)):
    ...
```

## Adding a New Router

1. Create `orchestrator/app/routers/<name>.py`.
2. Expose `router = APIRouter(prefix="/api/<name>", tags=["<name>"])`.
3. Import and `app.include_router(...)` in `orchestrator/app/main.py`.
4. Add request/response schemas to `orchestrator/app/schemas.py` (or a `schemas_<domain>.py` sibling).
5. Document here: add a row to the index above and create `docs/orchestrator/routers/<name>.md`.
6. Add tests under `orchestrator/tests/test_routers/`.

## Security Reminders

1. Verify ownership before allowing access (`get_project_by_slug`, `get_project_with_access`, `check_team_permission`).
2. Validate input via Pydantic schemas.
3. Use SQLAlchemy parameterized queries; never string-concatenate SQL.
4. Encrypt credentials (Fernet) at rest; redact on read.
5. Log security-relevant events (auth failures, permission denials, admin actions).
6. Rate-limit sensitive endpoints (login, password reset, invitation emails, uploads).
7. Sanitize file paths and S3/CAS keys.

## Related Documentation

- API schemas: [../schemas.md](../schemas.md)
- Database models: [../models/CLAUDE.md](../models/CLAUDE.md)
- Services: [../services/CLAUDE.md](../services/CLAUDE.md)
- Agent system: [../agent/CLAUDE.md](../agent/CLAUDE.md)
- Deployment modes: [../orchestration/CLAUDE.md](../orchestration/CLAUDE.md)
- Apps feature: [../../apps/CLAUDE.md](../../apps/CLAUDE.md)
- Desktop client: [../../desktop/CLAUDE.md](../../desktop/CLAUDE.md)
