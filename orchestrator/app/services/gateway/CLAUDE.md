# services/gateway

## Purpose
The unified messaging gateway — maintains persistent platform connections
(Telegram, Slack, Discord, WhatsApp, etc.), routes inbound messages to the
agent system via `TaskQueue`, and streams real-time status back to users.

## Key files
- `runner.py` — `GatewayRunner`: adapter lifecycle, per-session ordering,
  stream watcher (real-time tool status), and delivery consumer.
- `scheduler.py` — `CronScheduler`: tick-based agent schedule dispatcher.
- `schedule_parser.py` — natural-language → cron expression.

## Backend abstraction
- Agent event streams are consumed via `app.services.pubsub.get_pubsub()`.
  Both `RedisPubSub` (cloud) and `LocalPubSub` (desktop sidecar) implement
  `subscribe_agent_events`, so the stream watcher runs identically in both
  modes.
- Task enqueue goes through `app.services.task_queue.get_task_queue()`.

## Desktop-mode caveat (no Redis)
When `settings.redis_url` is empty:

- `_delivery_consumer` is a no-op. The delivery stream is a cross-process
  Redis Stream used to route responses from the worker to the gateway pod
  that owns the session; in single-process desktop mode there is no such
  boundary, and the worker's `XADD` to `gateway_delivery_stream` is also
  skipped. Response delivery through non-browser channels is therefore
  disabled on desktop — re-enable by configuring `redis_url`.
- `_reload_listener` is a no-op. Hot-reload via `tesslate:gateway:reload`
  pub/sub is Redis-only; on desktop, reload `GatewayRunner._sync_adapters()`
  directly from the same process.
- Heartbeat and status keys (`tesslate:gateway:active:*`,
  `tesslate:gateway:status`) are skipped — these are observability only.

Everything else — inbound message handling, schedule dispatch, per-session
ordering, stream-watcher typing/status updates — runs identically to cloud.

## Related contexts
- `app/services/pubsub/CLAUDE.md`
- `app/services/task_queue/CLAUDE.md`
- `docs/orchestrator/routers/CLAUDE.md` → gateway.py, schedules.py

## When to load
- Adding a new messaging channel adapter or changing session ordering.
- Touching the stream watcher or delivery routing.
- Porting gateway features to the desktop sidecar.
