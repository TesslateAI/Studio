# Per-Project Agent Permissions

Per-project agent permission system for OpenSail. Controls what
capabilities each agent (or all agents) may exercise within a project, and
routes gated operations through an appropriate approval mechanism depending on
the client context.

## Config File

Each project directory contains `.tesslate/permissions.json`. The file is
read at agent startup and written back when a user selects "Always allow"
at an approval gate.

### Schema v1

```json
{
  "schema_version": 1,
  "default_policy": "ask",
  "agents": {
    "*": {
      "shell": "ask",
      "network": "ask",
      "git_push": "deny",
      "file_write": "allow",
      "process_spawn": "ask"
    },
    "<agent_id>": {
      "shell": "allow",
      "network": "deny",
      "git_push": "deny",
      "file_write": "allow",
      "process_spawn": "deny"
    }
  },
  "budget": {
    "monthly_limit_usd": 20.0,
    "alert_threshold_pct": 80
  },
  "tui": {
    "preferred_theme": "dark",
    "confirmation_mode": "inline"
  }
}
```

### Field reference

| Field | Values | Description |
|-------|--------|-------------|
| `schema_version` | `1` | File format version; reserved for future migrations. |
| `default_policy` | `"ask"` / `"allow"` / `"deny"` | Fallback policy when a capability is absent from the matching agent entry. |
| `agents` | object | Per-agent capability overrides. Key `"*"` applies to all agents. More specific `agent_id` keys take precedence over `"*"`. |
| `shell` | policy string | Arbitrary shell command execution. |
| `network` | policy string | Outbound HTTP / socket access initiated by the agent. |
| `git_push` | policy string | `git push` and force-push operations. |
| `file_write` | policy string | Any write to a file tracked by the project. |
| `process_spawn` | policy string | Spawning long-lived background processes. |
| `budget.monthly_limit_usd` | float | Hard monthly spend cap in USD across all agents in this project. |
| `budget.alert_threshold_pct` | integer | Percentage of the cap at which a `budget_exhausted` notification fires. |
| `tui.preferred_theme` | string | Theme hint for TUI clients reading this file. |
| `tui.confirmation_mode` | `"inline"` / `"blocking"` | How approval gates are surfaced in TUI clients. |

## PermissionStore API

Implemented in `orchestrator/app/services/permission_store.py`.

```python
store = PermissionStore(project_dir)

result: PolicyResult = await store.check(agent_id, capability)
# result.policy  → "allow" | "deny" | "ask"
# result.source  → "agent_override" | "wildcard" | "default"

await store.persist_decision(agent_id, capability, "allow")
# Writes decision back to .tesslate/permissions.json immediately (atomic write).
```

`check(agent_id, capability)` resolution order:

1. Look up `agents[agent_id][capability]` — agent-specific override.
2. Fall back to `agents["*"][capability]` — wildcard override.
3. Fall back to `default_policy`.
4. If the file is absent or the field is missing, return `"ask"`.

## Policy Enforcement

### `allow`

The capability proceeds immediately. No gate fires. The decision is already
persisted in the file; no write occurs at call time.

### `deny`

The capability is rejected immediately. The agent receives a structured error
response. No user interaction occurs.

### `ask`

The request is routed to the approval gate appropriate for the active client:

| Client | Gate mechanism |
|--------|---------------|
| Desktop app | Tray notification (`approval_required` payload) → user clicks approve/deny in tray menu or floating approval card |
| TUI | Stream blocked; inline `y/n/always` prompt rendered in the bottom panel |
| Browser only | Web Push notification; user clicks approve/deny in browser or in-app toast |

Selecting "Always allow" at any gate calls `persist_decision(agent_id, capability, "allow")`, which writes back to `.tesslate/permissions.json` so future calls skip the gate.

## Pre-flight Checks

Pre-flight checks run in two places before every gated tool call:

1. **Agent bridge** (`orchestrator/app/services/tesslate_agent_adapter.py`) —
   intercepts tool calls from the agent loop before they reach the tool
   implementation and calls `permission_store.check(agent_id, capability)`.
2. **TUI** (`packages/tesslate-agent/`) — mirrors the same check client-side
   before sending the tool invocation to the sidecar, so approval prompts
   can be rendered inline without a server round-trip.

Both locations use the same `PermissionStore` interface; the TUI reads and
writes `.tesslate/permissions.json` directly from the local filesystem.

## Key Files

| File | Role |
|------|------|
| `orchestrator/app/services/permission_store.py` | `PermissionStore` — read, check, and persist permission decisions |
| `.tesslate/permissions.json` | Per-project config (inside every project directory) |
| `orchestrator/app/services/tesslate_agent_adapter.py` | Agent bridge — pre-flight gate in the server-side agent loop |
| `orchestrator/app/routers/desktop/tickets.py` | `POST /api/desktop/agents/{ticket_id}/approve` — tray approval endpoint |

## Related Contexts

- `docs/desktop/CLAUDE.md` — desktop architecture overview
- `docs/desktop/tui.md` — TUI approval prompt implementation
- `orchestrator/app/services/agent_approval.py` — server-side approval gate logic
- `docs/orchestrator/agent/CLAUDE.md` — agent loop and tool call pipeline
