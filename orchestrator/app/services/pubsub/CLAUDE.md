# services/pubsub

## Purpose
Backend-agnostic pub/sub + durable streams + distributed locks + cancellation
signals. Two implementations share one `PubSub` Protocol so the same orchestrator
code runs on the cloud (Redis + ARQ) and the desktop sidecar (in-process).

## Key files
- `base.py` — `PubSub` Protocol + shared channel/key prefixes.
- `redis_pubsub.py` — `RedisPubSub`: Redis Pub/Sub + Streams + Lua-scripted locks.
- `local_pubsub.py` — `LocalPubSub`: in-proc asyncio streams, per-group consumer
  cursors, dict-based locks with monotonic TTLs.
- `__init__.py` — `get_pubsub()` factory (Redis when `settings.redis_url` set,
  else Local). Re-exports the full public surface of the legacy monolithic
  `pubsub.py` module.

## Related contexts
- `app/services/task_queue/CLAUDE.md` — mirror split for job dispatch.
- `docs/orchestrator/services/pubsub.md` — higher-level architecture doc.
- `app/worker.py` — primary producer of agent events + lock holder.

## When to load
- Adding pub/sub call sites, new lock types, or touching agent event streaming.
- Debugging cross-pod WebSocket forwarding or stream replay semantics.
- Porting a feature to the desktop sidecar.
