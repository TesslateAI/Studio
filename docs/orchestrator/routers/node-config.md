# Node Config Router

**File**: `orchestrator/app/routers/node_config.py`

## Purpose

Two related concerns:

1. Mid-chat interactive input: agents can pause and request structured input from the user (`input_id`). The client submits or cancels that input through this router.
2. Container node configuration on the project canvas (edit a container's config JSON).

## Endpoints

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/api/chat/node-config/{input_id}/submit` | user | Deliver structured input for a paused agent step. |
| POST | `/api/chat/node-config/{input_id}/cancel` | user | Cancel the input request. |
| GET | `/api/projects/{project_id}/containers/{container_id}/config` | user | Read the container's full config node. |
| PATCH | `/api/projects/{project_id}/containers/{container_id}/config` | user | Update container config (env, startup, ports). |
| POST | (additional container-config operation) | user | See source for the container-config mutation route. |

## Auth

All endpoints require `current_active_user` via `get_authenticated_user`; container endpoints additionally verify project ownership.

## Related

- Container model: `Container` in [models.py](../../../orchestrator/app/models.py).
- Agent streaming + pause signals: [chat.md](chat.md).
