# Terminal Router

**File**: `orchestrator/app/routers/terminal.py`

**Base path**: `/api/terminal`

## Purpose

Interactive terminal UI surface. Lists connectable targets (containers/pods) for a project and opens a WebSocket to exec into one.

## Endpoints

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/{project_slug}/targets` | owner | List terminal targets (containers / pods) for the project. |
| WS | `/{project_slug}/connect` | user (ws) | Bidirectional PTY stream for the chosen target. |

## Auth

Both endpoints require an authenticated user; the WebSocket auth token is passed via query string. Ownership/team access is verified before opening the PTY.

## Related

- Non-interactive session API: [shell.md](shell.md).
- Orchestrators: [../orchestration/CLAUDE.md](../orchestration/CLAUDE.md) for the Docker-exec and kubectl-exec backends.
