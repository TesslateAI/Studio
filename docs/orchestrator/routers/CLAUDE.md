# Orchestrator Routers Agent Context

**Purpose**: API endpoint development for OpenSail's FastAPI backend.

**Load when**: Adding or modifying routers, HTTP handlers, WebSocket endpoints, or auth flows.

## Scope

Every Python file in these directories is documented here or in a linked per-router doc:

- `orchestrator/app/routers/*.py` (flat modules; cookie/session or tsk auth)
- `orchestrator/app/routers/desktop/*.py` (sidecar routes, mounted at `/api/desktop`)
- `orchestrator/app/routers/public/*.py` (tsk-key public API; `/api/public/*` and `/api/v1/*`)

See [README.md](README.md) for the full index and the per-file to per-doc mapping.

## Docs by Router

Every router has a doc entry. Use [README.md](README.md) for the complete matrix. Summary:

### Core / project workflow

- [projects.md](projects.md): `projects.py` (CRUD, files, containers, setup-config, analyze, hibernate, ensure-environment).
- [chat.md](chat.md): `chat.py` (agent streaming, WS, multi-session chat, ARQ dispatch, undo).
- [node-config.md](node-config.md): `node_config.py` (container config + mid-chat interactive input).
- [tasks.md](tasks.md): `tasks.py` (task status + WS).
- [kanban.md](kanban.md): `kanban.py` (board, tasks `TSK-NNNN`, notes).
- [snapshots.md](snapshots.md): `snapshots.py` (CAS timeline, branches, restore).
- [shell.md](shell.md) + [terminal.md](terminal.md): persistent shell sessions + interactive PTY.
- [design.md](design.md): `design.py` (OID index + AST apply-diff).
- [secrets.md](secrets.md): per-user API keys, custom providers, model preferences.

### Auth and users

- [auth.md](auth.md): `auth.py` (refresh, logout, dev-server verify-access).
- [two-fa.md](two-fa.md): `two_fa.py` (email 2FA login).
- [magic-link.md](magic_link.md) (file: `magic_link.py`): passwordless login.
- [users.md](users.md): `users.py` (preferences, profile, handle).
- [teams.md](teams.md): `teams.py` (teams, members, invites, project access, audit log).
- [referrals.md](referrals.md): `referrals.py`.
- [creators.md](creators.md): `creators.py` (public creator profiles).
- [feedback.md](feedback.md): `feedback.py`.

### Agents and tools

- [agents.md](agents.md): `agents.py` (user agents, tool catalog).
- [agent.md](agent.md): `agent.py` (legacy command endpoints).
- [external-agent.md](external-agent.md): `external_agent.py` (tsk-key invoke + SSE + webhooks).
- [schedules.md](schedules.md): `schedules.py` (cron-scheduled agent tasks).
- [gateway.md](gateway.md): `gateway.py` (gateway status, platforms, identity pairing).
- [channels.md](channels.md): `channels.py` (messaging channel configs + webhooks).

### Marketplace and apps

- [marketplace.md](marketplace.md): `marketplace.py` (agents/skills/bases/MCP/themes).
- [mcp.md](mcp.md): `mcp.py`, `mcp_server.py` (user MCP + streamable-HTTP server).
- [mcp-oauth.md](mcp-oauth.md): `mcp_oauth.py` (per-user OAuth for MCP connectors).
- [themes.md](themes.md): `themes.py` (public theme API).
- [apps.md](apps.md): all Tesslate Apps routers (`marketplace_apps.py`, `app_versions.py`, `app_installs.py`, `app_runtime.py`, `app_runtime_status.py`, `app_schedules.py`, `app_billing.py`, `app_submissions.py`, `app_yanks.py`, `app_triggers.py`, `app_bundles.py`, `admin_marketplace.py`).

### Billing and deployments

- [billing.md](billing.md): `billing.py` (subscriptions, credits).
- [webhooks.md](webhooks.md): `webhooks.py` (Stripe inbound).
- [deployments.md](deployments.md): `deployments.py` (Vercel/Netlify/Cloudflare).
- [deployment-credentials.md](deployment-credentials.md): `deployment_credentials.py`.
- [deployment-oauth.md](deployment-oauth.md): `deployment_oauth.py`.
- [deployment-targets.md](deployment-targets.md): `deployment_targets.py`.

### Git

- [git.md](git.md): `git.py` (init/commit/push/pull).
- [git-providers.md](git-providers.md): `git_providers.py` (GitHub/GitLab/Bitbucket OAuth, repo listing).
- [github.md](github.md): `github.py` (legacy GitHub-only routes).

### Admin and ops

- [admin.md](admin.md): `admin.py`.
- [internal.md](internal.md): `internal.py` (cluster-internal secret auth).
- [feature-flags.md](feature-flags.md): `feature_flags.py`.
- [version.md](version.md): `version.py`.
- [test-helpers.md](test-helpers.md): `test_helpers.py` (test-only).

### Proxies and SDKs

- [proxy.md](proxy.md): `proxy.py` (OpenAI-compat `/v1` for external callers).
- [public.md](public.md): every `public/*.py` router (tsk-auth external API).
- [desktop.md](desktop.md): every `desktop/*.py` router plus `desktop_pair.py` and `marketplace_local.py`.

## Auth Matrix

| Dependency | Router examples | Token |
|------------|-----------------|-------|
| `current_active_user` | most `/api/*` routers | cookie JWT or bearer |
| `current_superuser` | admin.py, admin_marketplace.py, moderation hooks | bearer/cookie + superuser flag |
| `current_optional_user` | themes.py, marketplace.py browse, creators.py | optional |
| `require_api_scope(Permission.X)` | public/* routers, external_agent.py, proxy.py | `tsk_` key |
| HMAC-SHA256 over body | app_triggers.py | per-schedule key |
| `verify_internal_secret` | internal.py | shared cluster secret |
| Provider signature | webhooks.py (Stripe), channels.py | provider-signed |
| State token | deployment_oauth.py callbacks, git_providers.py callbacks, mcp_oauth.py callback | signed state |

## Common Patterns

### Project access

```python
project = await get_project_by_slug(db, project_slug, current_user.id)   # owner only
# or for team-aware access:
project = await get_project_with_access(db, project_slug, current_user)  # dual-scope
```

### Schema validation

Request/response bodies use Pydantic. Shared schemas live in `schemas.py`, `schemas_team.py`, and `schemas_auth.py`. Public routers inline their schemas per convention.

### Background + long-running tasks

- FastAPI `BackgroundTasks` for fire-and-forget side effects.
- ARQ queue (cloud) or `LocalTaskQueue` (desktop) for agent work.
- `TaskManager` for progress rows polled by the frontend.
- Redis Streams + SSE/WS for real-time event broadcast.

### Orchestrator factory

Routers should not hardcode Docker vs K8s. Use:

```python
from ..services.orchestration.factory import get_orchestrator
orchestrator = get_orchestrator(project=project)
```

## Middleware Stack (order matters)

1. `ProxyHeadersMiddleware` handles `X-Forwarded-*`.
2. `DynamicCORSMiddleware` matches wildcard subdomains.
3. `CSRFProtectionMiddleware` validates CSRF tokens.
4. Security headers (CSP, `X-Content-Type-Options`).

## Testing

```bash
pytest orchestrator/tests/test_routers/
pytest orchestrator/tests/test_routers/test_projects.py -v
```

Public-router tests live in `orchestrator/tests/public/` (mirror the `public/` package layout).

## Common Gotchas

- `deployments.py` `trigger_build()` parameter names are `custom_build_command` and `volume_name`, not `build_command` / `working_directory`. See [deployments.md](deployments.md).
- Registration order of `users.py` matters: it is included BEFORE the fastapi-users `/{id}` catch-all in `main.py`.
- Desktop routes must never 5xx on probe or cloud failure. Degrade to a well-formed payload. See [desktop.md](desktop.md).
- Public routers must never accept session auth; always use `require_api_scope(...)`. See [public.md](public.md).
- `internal.py` endpoints must not be exposed through ingress.
- K8s resource names: never derive `container.name` from `container.directory` (or vice versa). See root [docs/orchestrator/CLAUDE.md](../CLAUDE.md).

## Related

- Schemas: [../schemas.md](../schemas.md).
- Models: [../models/CLAUDE.md](../models/CLAUDE.md).
- Services: [../services/CLAUDE.md](../services/CLAUDE.md).
- Agent system: [../agent/CLAUDE.md](../agent/CLAUDE.md).
- Apps feature: [../../apps/CLAUDE.md](../../apps/CLAUDE.md).
- Desktop client: [../../desktop/CLAUDE.md](../../desktop/CLAUDE.md).
