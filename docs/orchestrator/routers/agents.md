# Agents Router (User Agents)

**File**: `orchestrator/app/routers/agents.py`

**Base path**: `/api/agents`

## Purpose

Lists the AI agents available to the current user (library + defaults) and exposes the tool catalog that agents can invoke. Distinct from [marketplace.md](marketplace.md) (browse/publish) and [agent.md](agent.md) (legacy execution).

## Endpoints

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/` | user | List agents available to the current user. |
| GET | `/{agent_id}` | user | Fetch a single agent (including system prompt and config). |
| GET | `/tools/available` | user | List every tool the agent runtime can bind (bash, read/write, web ops, skill ops, MCP bridge). |

## Auth

All endpoints require `current_active_user`.

## Related

- Models: `MarketplaceAgent`, `UserAgentLibrary` in [models.py](../../../orchestrator/app/models.py).
- Agent tools inventory: [../agent/tools/CLAUDE.md](../agent/tools/CLAUDE.md).
- Marketplace acquisition: [marketplace.md](marketplace.md).
