# MCP OAuth Router

**File**: `orchestrator/app/routers/mcp_oauth.py`

**Base path**: `/api/mcp/oauth`

## Purpose

OAuth connector flow for MCP servers that require per-user authorization (e.g., Google Drive, Slack). Complements [mcp.md](mcp.md) (install/manage) by handling the browser redirect/callback dance required before a server can be bound to an agent.

## Endpoints

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/start` | user | Begin an OAuth flow for an installed MCP server. Returns `flow_id` and authorize URL. |
| GET | `/callback` | state | Provider redirects here with `code`; the orchestrator exchanges the code and marks the flow complete. |
| GET | `/status/{flow_id}` | user | Poll status (pending/succeeded/failed). Used by the UI to close the popup. |

## Auth

`start` and `status` require `current_active_user`; `callback` authenticates via the signed `state` parameter.

## Related

- MCP management: [mcp.md](mcp.md).
- MCP server marketplace catalog: `mcp_server.py`.
- Model: `UserMcpConfig` in [models.py](../../../orchestrator/app/models.py).
