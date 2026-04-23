# Desktop Notifications

Cross-platform notification dispatch layer for OpenSail. Delivers agent
lifecycle events to users whether they are running the desktop app, a browser
session, or have the window minimised to the system tray.

## Architecture

Two delivery channels share a single notification payload schema:

- **Web Push** — pushed to browser sessions via the Web Push protocol (VAPID).
- **OS tray notifications** — delivered on the desktop via `tauri-plugin-notification`
  when the main window is not visible.

The orchestrator side is implemented as a gateway adapter
(`orchestrator/app/services/gateway/notification_adapter.py`) that implements
`BaseAdapter` from the gateway framework. Unlike the optional platform adapters
(Telegram, Slack, etc.), the notification adapter is loaded unconditionally by
`GatewayRunner._sync_adapters()` on every start.

## Notification Payload

```json
{
  "type": "agent_complete" | "approval_required" | "budget_exhausted" | "heartbeat_done",
  "task_ref": "<TSK-NNNN>",
  "project_name": "<human-readable project name>",
  "message": "<short description>"
}
```

All fields are required. `task_ref` maps to `AgentTask.ref_id`; `project_name`
is the `Project.name` value.

## Web Push (Browser)

VAPID key pair:
- Generated once at first start.
- Persisted to `$TESSLATE_STUDIO_HOME/vapid.json` (readable only by the sidecar
  process on POSIX; created with mode `0600`).
- The VAPID public key is served to the browser via `GET /api/notifications/vapid-key`.

Subscription lifecycle:
- Browser calls `navigator.serviceWorker.ready`, then
  `pushManager.subscribe(vapidPublicKey)`.
- Subscription object posted to `POST /api/notifications/subscribe`.
- Subscription stored per-user in the database and used for every subsequent
  push for that user.

Service worker at `app/public/sw.js` handles incoming push events and surfaces
them as OS notifications via the Notifications API.

## Desktop (Tauri)

The sidecar publishes notification payloads to the `LocalPubSub` channel
`notifications:{user_id}`. The Tauri event bridge subscribes to this channel
and calls `tauri-plugin-notification`'s `notify()` to fire an OS-level
notification.

Visibility gating:
- When the main window is **visible and focused**: notification delivery is
  suppressed at the Tauri layer; the frontend renders in-app toast messages
  instead, sourced from the same SSE stream.
- When the main window is **hidden to tray**: OS notifications fire normally.

The sidecar also provides a server-sent events stream at
`GET /api/desktop/notifications/stream` for cases where the Tauri shell needs
to poll rather than rely on the pub/sub bridge (for example, during window
re-focus after a restart). This endpoint requires the loopback bearer token.

## Gateway Integration

The notification adapter participates in the standard gateway runner lifecycle:

1. `GatewayRunner.start()` calls `_sync_adapters()`, which instantiates
   `NotificationAdapter` unconditionally.
2. After an agent task completes (or requires approval), the worker publishes
   an event on the agent's Redis/Local stream.
3. The gateway stream watcher picks up the event and routes it to
   `NotificationAdapter.dispatch(payload, user_id)`.
4. `dispatch` fans out to all active subscriptions for `user_id`: Web Push
   endpoints in the database and, in desktop mode, the `LocalPubSub` channel.

In desktop mode (no Redis), the delivery path is in-process: `LocalPubSub`
replaces Redis Streams and the `LocalTaskQueue` replaces ARQ. The notification
adapter's `dispatch` method does not branch on deployment mode — it always
writes to `get_pubsub().publish(channel, payload)`.

## Key Files

| File | Role |
|------|------|
| `orchestrator/app/services/gateway/notification_adapter.py` | `NotificationAdapter(BaseAdapter)` — fan-out to push and pub/sub |
| `orchestrator/app/routers/desktop/tray.py` | `GET /api/desktop/notifications/stream` SSE endpoint |
| `orchestrator/app/services/pubsub/local_pubsub.py` | `LocalPubSub` — in-process pub/sub used in desktop mode |
| `orchestrator/app/services/pubsub/redis_pubsub.py` | `RedisPubSub` — Redis-backed pub/sub used in cloud/Docker mode |
| `desktop/src-tauri/src/tray.rs` | Tauri tray + window visibility state |
| `app/public/sw.js` | Service worker — handles Web Push events in browser |

## Related Contexts

- `docs/desktop/CLAUDE.md` — desktop architecture overview
- `orchestrator/app/services/gateway/CLAUDE.md` — gateway runner and adapter lifecycle
- `orchestrator/app/services/pubsub/CLAUDE.md` — pub/sub backend abstraction
- `docs/guides/real-time-agent-architecture.md` — agent event streaming end-to-end
