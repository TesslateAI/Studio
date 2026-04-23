# Gateway Services

**Directory**: `orchestrator/app/services/gateway/`

Standalone gateway process that holds persistent connections to messaging platforms (Telegram, Slack, Discord, WhatsApp, Signal, CLI), routes inbound messages into the agent system, and delivers responses back.

The gateway is a separate long-running process, not part of the API pod. It reads from a Redis delivery stream and uses hot-reloadable per-user adapters.

## When to load

Load this doc when:
- Adding or modifying a gateway adapter.
- Debugging cron-scheduled agent tasks.
- Writing a new natural-language schedule parser path.
- Wiring a new gateway event producer.

## File map

| File | Purpose |
|------|---------|
| `__init__.py` | Package marker. |
| `runner.py` | `GatewayRunner`: manages persistent platform connections, routes inbound messages to the agent system, consumes the Redis delivery stream (XREADGROUP), runs reconnect watcher, session reaper, media cache cleaner, reload listener. |
| `scheduler.py` | `CronScheduler`: timezone-aware cron tick that reads `agent_schedules` every interval and enqueues matching prompts via the task queue. |
| `schedule_parser.py` | Natural-language to cron parser ("every day at 9am", "weekdays at 5pm") that emits normalized five-field cron expressions. |

## Process boundaries

| Concern | Location |
|---------|----------|
| Inbound platform connections (polling, WebSocket, Socket Mode) | `runner.py` adapters |
| Outbound delivery (agent response: user) | `runner.py` reading `tesslate:gateway:deliver` stream |
| Cron evaluation | `scheduler.py` |
| Agent dispatch | enqueue via `services.task_queue.get_task_queue().enqueue("execute_agent_task", payload)` |

## Callers

| Caller | What it does |
|--------|--------------|
| `python -m app.services.gateway.runner` | Top-level process entry (K8s Deployment or Docker Compose service). |
| Worker `execute_agent_task` | After the agent finishes, publishes to the gateway delivery stream. `runner.py` picks it up and sends to the original channel. |
| `routers/schedules.py` | Writes `AgentSchedule` rows that `scheduler.py` reads. |

## Related

- [channels.md](./channels.md): per-platform adapter implementations used by `runner.py`.
- [pubsub.md](./pubsub.md): Redis Streams and pub/sub backbone used for delivery and hot reload.
- [task-queue.md](./task-queue.md): ARQ enqueue path for scheduler-produced tasks.
- `docs/orchestrator/routers/gateway.py` and `schedules.py` handle the API side.
