# services/task_queue

## Purpose
Backend-agnostic background job dispatch. Cloud uses ARQ (Redis); desktop uses
an in-process asyncio worker pool. Both expose the same `TaskQueue` Protocol so
routers can `await get_task_queue().enqueue(name, *args, _defer_by=...)`.

## Key files
- `base.py` — `TaskQueue` Protocol.
- `arq_queue.py` — `ArqTaskQueue`: lazy ARQ pool, forwards to `enqueue_job`.
- `local_queue.py` — `LocalTaskQueue`: FIFO `asyncio.Queue`, N workers, delayed
  dispatch via `asyncio.sleep`. Handlers resolved by name through
  `app.services.agent_handlers.TASK_HANDLERS`.
- `__init__.py` — `get_task_queue()` factory.

## Related contexts
- `app/services/agent_handlers.py` — shared handler registry (same callables
  ARQ exposes via `WorkerSettings.functions`).
- `app/worker.py` — owns the actual handler bodies.
- `app/services/pubsub/CLAUDE.md` — mirror split for pub/sub.

## When to load
- Adding a new enqueue site or background job.
- Changing handler signatures (must stay `(ctx, *args, **kwargs)` for ARQ).
- Wiring the desktop sidecar event loop.
