# Agent Router (Legacy)

**File**: `orchestrator/app/routers/agent.py`

**Base path**: `/api/agent`

## Purpose

Legacy command-style agent execution endpoints. Superseded by the streaming agent system in `chat.py` and the external agent API in `external_agent.py`. Retained for back-compat with older clients.

## Endpoints

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/execute` | user | Execute an agent command and return the structured response. |
| GET | `/history/{project_id}` | user | List agent command log entries for a project. |
| GET | `/stats` | user | Aggregate usage stats for the current user's agent commands. |
| GET | `/health` | user | Health check for the agent subsystem. |

## Auth

All endpoints require `current_active_user`. Project access is scoped to the owner via `project_id`.

## Related

- Models: `AgentCommandLog` in [models.py](../../../orchestrator/app/models.py).
- Schemas: `AgentCommandResponse`, `AgentCommandLogSchema`, `AgentCommandStatsResponse` in [schemas.py](../../../orchestrator/app/schemas.py).
- For the current agent flow, see [chat.md](chat.md) and [external-agent.md](external-agent.md).
