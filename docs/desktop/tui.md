# Textual TUI Client

Terminal-based agent client for headless and server environments. An
alternative frontend to the OpenSail desktop app and browser UI.
Intended for SSH sessions, CI pipelines, or any context where a graphical
window is unavailable.

## Entry Point

```
python -m tesslate_agent.tui
```

Source: `packages/tesslate-agent/src/tesslate_agent/` (tui submodule).

Framework: [Textual](https://textual.textualize.io/) — async Python, ANSI
terminal, no browser dependency.

## Environment Variables

Both variables are required. The TUI does not prompt for credentials at
startup.

| Variable | Description |
|----------|-------------|
| `TESSLATE_API_URL` | Base URL of the running sidecar or cloud orchestrator (e.g. `http://127.0.0.1:PORT`). Do not include `/api`. |
| `TESSLATE_BEARER` | Bearer token issued by the sidecar handshake or a cloud API key. |

When connecting to the local desktop sidecar, `TESSLATE_API_URL` and
`TESSLATE_BEARER` are available from the sidecar's `TESSLATE_READY {port} {bearer}`
stdout line (see `desktop/src-tauri/src/sidecar.rs`).

## Layout

```
+------------------------------------------------------+
| [Project Selector]  Sidebar (left)                   |
|  - project list via GET /api/projects                |
|  - active project highlighted                        |
+------------------------------------------------------+
| [Trajectory Stream]  Main panel                      |
|  - live AgentStep events from SSE stream             |
|  - tool call names, outputs, status icons            |
|  - approval gate prompts rendered inline (see below) |
+------------------------------------------------------+
| [Input bar]  Bottom panel                            |
|  - free-text task entry                              |
|  - y / n / always responses for approval gates       |
+------------------------------------------------------+
| [Status bar]                                         |
|  - task ref (TSK-NNNN), runtime clock, budget used   |
|  - connection state (connected / reconnecting)       |
+------------------------------------------------------+
```

## Connecting to the Orchestrator

The TUI connects to the same REST and SSE endpoints the browser frontend uses.
No separate protocol is required.

- Project list: `GET /api/projects` (standard projects endpoint).
- Start an agent task: `POST /api/chat/agent/stream` (or the external agent
  invoke endpoint if using an API key).
- Live events: subscribes to the Redis/Local stream via the WebSocket or SSE
  endpoint that delivers `AgentStep` payloads.

This means the TUI is compatible with both backends:
- **LocalTaskQueue** (desktop sidecar, no Redis) — in-process queue; events
  arrive via `LocalPubSub`.
- **ArqTaskQueue** (cloud / Docker) — ARQ + Redis; events arrive via Redis
  Streams.

The TUI does not need to know which backend is active; it consumes the same
HTTP/SSE surface in both cases.

## Approval Gates

When an agent hits a capability gated by `"ask"` in `.tesslate/permissions.json`
(see `docs/desktop/permissions.md`), the TUI handles the gate inline:

1. The trajectory stream pauses.
2. An approval prompt is rendered in the main panel:
   ```
   Agent requests: shell — run `npm install`
   [y] Allow once   [n] Deny   [always] Always allow
   ```
3. The user types `y`, `n`, or `always` in the input bar and presses Enter.
4. `always` writes the decision back to `.tesslate/permissions.json`
   immediately (atomic write via `PermissionStore.persist_decision`).
5. The stream resumes.

`confirmation_mode` in the `tui` block of `permissions.json` controls whether
the prompt blocks the stream (`"blocking"`, default) or renders alongside it
(`"inline"`).

## Relationship to Other Clients

The TUI is not a replacement for the desktop app; it is an additional client
targeting server and headless contexts. All three clients (browser, desktop,
TUI) share the same orchestrator API surface:

| Client | Transport | Approval gate |
|--------|-----------|---------------|
| Browser | HTTP + WebSocket | Web Push / in-app toast |
| Desktop app | Tauri loopback + SSE | Tray notification / approval card |
| TUI | REST + SSE | Inline terminal prompt |

## Key Files

| File | Role |
|------|------|
| `packages/tesslate-agent/src/tesslate_agent/` | TUI module root |
| `orchestrator/app/services/permission_store.py` | `PermissionStore` — read and write `.tesslate/permissions.json` |
| `orchestrator/app/services/task_queue/local_queue.py` | `LocalTaskQueue` — in-process queue used by desktop sidecar |
| `orchestrator/app/services/task_queue/arq_queue.py` | `ArqTaskQueue` — Redis-backed queue used by cloud/Docker |
| `orchestrator/app/services/pubsub/local_pubsub.py` | `LocalPubSub` — in-process event stream for desktop mode |
| `desktop/src-tauri/src/sidecar.rs` | Sidecar spawn and bearer handshake |

## Related Contexts

- `docs/desktop/CLAUDE.md` — desktop architecture overview
- `docs/desktop/permissions.md` — permission schema and approval gate details
- `orchestrator/app/services/task_queue/CLAUDE.md` — LocalTaskQueue vs ArqTaskQueue
- `orchestrator/app/services/pubsub/CLAUDE.md` — LocalPubSub vs RedisPubSub
- `docs/guides/real-time-agent-architecture.md` — end-to-end agent event streaming
