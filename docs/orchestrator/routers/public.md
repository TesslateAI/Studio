# Public API Routers

External API surface authenticated via `tsk_` `ExternalAPIKey` tokens. Consumed by the desktop client, SDKs, and on-prem deployments.

- `/api/public/*` is read-only public catalog (marketplace browse).
- `/api/v1/*` is everything authenticated.

Internal/session-auth routers live one directory up. See [../../packages/CLAUDE.md](../../packages/CLAUDE.md) for SDK consumers.

## File Index

| File | Prefix | Purpose |
|------|--------|---------|
| `public/marketplace.py` | `/api/public/marketplace` | Browse agents, skills, bases, MCP servers, themes. Purchase-gated manifest/body downloads. |
| `public/models.py` | `/api/v1` | OpenAI-compatible chat completions, model list, usage. |
| `public/agents.py` | `/api/v1/agents` | Task inspection, cancel, step history for external agent runs. |
| `public/agents_handoff.py` | `/api/v1/agents/handoff` | Upload/download/pause/resume agent handoff blobs. |
| `public/marketplace_install.py` | `/api/v1/marketplace` | Install marketplace items, list installed, ack install receipt. |
| `public/projects_sync.py` | `/api/v1/projects/sync` | Project sync push/pull/manifest/history. |
| `public/k8s_projects.py` | `/api/v1/k8s/projects` | Manage K8s-mode projects remotely (create, lifecycle, events, logs, exec). |
| `public/_shared.py` | (helpers) | Cache headers, sort, ownership filter, pagination. |
| `public/_deps.py` | (helpers) | `scoped()` dependency + audit helpers. |
| `public/__init__.py` | (n/a) | Exports `public_routers` list consumed by `main.py`. |

## Endpoints

### public/marketplace.py

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/agents` | tsk | Browse marketplace agents. |
| GET | `/agents/{slug}` | tsk | Agent detail. |
| GET | `/agents/{slug}/manifest` | tsk (purchased) | Download agent manifest. |
| GET | `/skills` | tsk | Browse skills. |
| GET | `/skills/{slug}` | tsk | Skill detail. |
| GET | `/skills/{slug}/body` | tsk (purchased) | Download skill body. |
| GET | `/bases` | tsk | Browse bases. |
| GET | `/bases/{slug}` | tsk | Base detail. |
| GET | `/mcp-servers` | tsk | Browse MCP servers. |
| GET | `/mcp-servers/{slug}` | tsk | MCP server detail. |
| GET | `/themes` | tsk | Browse themes. |
| GET | `/themes/{slug}` | tsk | Theme detail. |

### public/models.py

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/chat/completions` | tsk | OpenAI-compatible chat completions (routed via LiteLLM). |
| GET | `/models` | tsk | List available models. |
| GET | `/usage` | tsk | Usage and cost for the caller. |

### public/agents.py

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/tasks` | tsk | List agent tasks. |
| POST | `/tasks/{task_id}/cancel` | tsk | Cancel a running task. |
| GET | `/tasks/{task_id}/steps` | tsk | Step history (progressive persistence). |

### public/agents_handoff.py

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/upload` | tsk | Upload handoff payload. |
| GET | `/download/{task_id}` | tsk | Download handoff. |
| POST | `/{task_id}/pause` | tsk | Pause an in-flight task. |
| POST | `/{task_id}/resume` | tsk | Resume. |

### public/marketplace_install.py

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/install` | tsk | Install a marketplace item into the caller's library/project. |
| GET | `/installed` | tsk | List installs. |
| POST | `/install/{receipt_id}/ack` | tsk | Acknowledge receipt. |

### public/projects_sync.py

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/push` | tsk | Push project snapshot. |
| GET | `/pull/{snapshot_id}` | tsk | Pull snapshot. |
| GET | `/manifest/{project_id}` | tsk | Project manifest. |
| GET | `/history/{project_id}` | tsk | Snapshot history. |

### public/k8s_projects.py

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `` | tsk | Create a remote K8s project. |
| GET | `/{project_slug}` | tsk | Project detail. |
| POST | `/{project_slug}/start` | tsk | Start containers (202). |
| POST | `/{project_slug}/stop` | tsk | Stop. |
| POST | `/{project_slug}/restart` | tsk | Restart (202). |
| DELETE | `/{project_slug}` | tsk | Delete. |
| GET | `/{project_slug}/events` | tsk | SSE events for the project. |
| GET | `/{project_slug}/logs/{container_name}` | tsk | Container logs. |
| WS | `/{project_slug}/exec` | tsk | Exec into a pod. |

## Auth

Every route uses `require_api_scope(Permission.X)` or `scoped(...)`. Session auth is never accepted here.

## Related

- API key management: [external-agent.md](external-agent.md) plus `auth_external.py`.
- Permissions enum: [../../../orchestrator/app/permissions.py](../../../orchestrator/app/permissions.py).
- SDK consumers: [../../packages/CLAUDE.md](../../packages/CLAUDE.md).
- Public router guide: `orchestrator/app/routers/public/CLAUDE.md`.
