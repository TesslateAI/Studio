# Shell Router

**File**: `orchestrator/app/routers/shell.py`

**Base path**: `/api/shell`

## Purpose

REST surface for persistent shell sessions that back the agent `session` tool (read/write/polled output, independent of any single WebSocket). See [terminal.md](terminal.md) for the interactive WebSocket surface used by the in-browser terminal.

## Endpoints

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/sessions` | user | Create a new shell session pinned to a project/container. |
| POST | `/sessions/{session_id}/write` | user | Write stdin to the session. |
| GET | `/sessions/{session_id}/output` | user | Read buffered stdout/stderr since last cursor. |
| GET | `/sessions` | user | List the caller's active sessions. |
| DELETE | `/sessions/{session_id}` | user | Terminate and clean up a session. |
| GET | `/sessions/{session_id}` | user | Session metadata (state, cwd, last activity). |

## Auth

All endpoints require `current_active_user` via `get_authenticated_user`. Sessions are owner-scoped.

## Related

- Agent tool: `orchestrator/app/agent/tools/session.py`.
- Cross-pod routing: `orchestrator/app/services/session_router.py`.
- Interactive terminal: [terminal.md](terminal.md).
