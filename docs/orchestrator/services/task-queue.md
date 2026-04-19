# Task Queue - Backend-Agnostic Job Dispatch

**Purpose**: Provides a unified `TaskQueue` protocol that abstracts background job dispatch. Cloud deployments use ARQ backed by Redis; the desktop sidecar uses an in-process asyncio worker pool. All routers and services enqueue jobs through `get_task_queue()` without knowing which backend is active.

## When to Load This Context

Load this context when:
- Adding a new enqueue site or background job type
- Changing handler signatures (must remain `(ctx, *args, **kwargs)` for ARQ compatibility)
- Debugging task execution in desktop or cloud mode
- Wiring the desktop sidecar event loop
- Modifying worker concurrency settings

## Key Files

| File | Purpose |
|------|---------|
| `orchestrator/app/services/task_queue/base.py` | `TaskQueue` Protocol (runtime-checkable) |
| `orchestrator/app/services/task_queue/arq_queue.py` | `ArqTaskQueue` — cloud implementation wrapping ARQ + Redis |
| `orchestrator/app/services/task_queue/local_queue.py` | `LocalTaskQueue` — desktop implementation using `asyncio.Queue` |
| `orchestrator/app/services/task_queue/__init__.py` | `get_task_queue()` factory; selects backend based on `redis_url` |
| `orchestrator/app/services/agent_handlers.py` | `TASK_HANDLERS` dict — shared handler registry used by both backends |
| `orchestrator/app/worker.py` | Actual handler bodies (`execute_agent_task`, `send_webhook_callback`, `refresh_templates`) |

## Protocol

```python
@runtime_checkable
class TaskQueue(Protocol):
    async def enqueue(
        self,
        name: str,
        *args: Any,
        _defer_by: float | None = None,
        **kwargs: Any,
    ) -> str:
        """Enqueue a job by handler name. Returns an opaque job id string."""
        ...
```

`_defer_by` is seconds to delay before the job runs. The returned job id is used primarily for logging and cancellation.

## Factory

```python
from app.services.task_queue import get_task_queue

q = get_task_queue()
job_id = await q.enqueue("execute_agent_task", payload_dict)
```

The factory picks a backend once and caches the singleton for the process lifetime:

| Condition | Backend |
|-----------|---------|
| `settings.redis_url` is set | `ArqTaskQueue` (cloud) |
| `settings.redis_url` is empty | `LocalTaskQueue` (desktop) |

`worker_max_jobs` from settings controls `LocalTaskQueue.max_workers` when Redis is absent (default `5`).

## Backends

### ArqTaskQueue (Cloud)

Wraps an ARQ Redis pool. Pool construction is lazy — the first `enqueue()` call builds it from `settings.redis_url`.

- Delayed dispatch uses ARQ's native `_defer_by` kwarg (converted to `datetime.timedelta`).
- Raises `RuntimeError` if the Redis pool cannot be created.
- The same handler names registered in `WorkerSettings.functions` (in `worker.py`) are the names passed to `enqueue()`.

```python
# How the cloud enqueues an agent task
await get_task_queue().enqueue("execute_agent_task", payload_dict)
```

### LocalTaskQueue (Desktop)

Single-process FIFO queue backed by `asyncio.Queue` with N concurrent worker coroutines.

Key behaviors:

- `start()` is called lazily on first `enqueue()` — no manual startup required.
- Workers are created as `asyncio.Task` instances; calling `stop()` cancels them cleanly.
- Delayed jobs (`_defer_by > 0`) use `asyncio.sleep` inside a `create_task`; cancelling the delay task skips the job.
- `cancel(job_id) -> bool` marks a pending job as skipped (best-effort). Running jobs are not interrupted here — use the Redis pub/sub cancellation signal for in-flight agent tasks.
- Each worker builds a `ctx` dict with `{"job_id": ..., "task_queue": self}` and passes it as the first positional argument to the handler, matching ARQ's `ctx` convention.

```python
# LocalTaskQueue lifecycle (managed automatically in practice)
q = LocalTaskQueue(max_workers=4)
await q.start()
job_id = await q.enqueue("execute_agent_task", payload_dict)
q.cancel(job_id)   # best-effort skip
await q.stop()     # cancels all workers and pending delayed tasks
```

## Handler Registry

Both backends resolve handlers by name through `agent_handlers.TASK_HANDLERS`:

```python
TASK_HANDLERS: dict[str, Callable[..., Any]] = {
    "execute_agent_task": execute_agent_task,
    "send_webhook_callback": send_webhook_callback,
    "refresh_templates": refresh_templates,
}
```

Handler bodies live in `orchestrator/app/worker.py`. `agent_handlers.py` re-exports references so the registry stays in one place without forking implementations.

To add a new background job:
1. Write the handler in `worker.py` with signature `async def my_handler(ctx, *args, **kwargs)`.
2. Add it to `TASK_HANDLERS` in `agent_handlers.py`.
3. Register it in `WorkerSettings.functions` in `worker.py` (ARQ side).
4. Call `await get_task_queue().enqueue("my_handler", ...)` from any router or service.

## Cancellation and Progress

Both backends rely on the progressive-persistence model in `AgentStep`:

- **Cancellation signal**: published to Redis pub/sub (cloud) or checked via a flag in `_Job.cancelled` (desktop). The agent loop polls between iterations.
- **Progress**: each agent iteration writes an `AgentStep` row and publishes to a Redis Stream (cloud) or the in-process pub/sub shim (desktop).

`LocalTaskQueue.cancel()` handles the pre-execution case; running jobs must observe the pub/sub cancellation signal to stop cleanly.

## Configuration

| Setting | Purpose | Default |
|---------|---------|---------|
| `redis_url` | If set, `ArqTaskQueue` is used; if empty, `LocalTaskQueue` is used | `""` |
| `worker_max_jobs` | `LocalTaskQueue` concurrency (max in-flight jobs) | `5` |
| `worker_job_timeout` | ARQ task timeout in seconds | `600` |

## Testing

Reset the process singleton between tests:

```python
from app.services.task_queue import _reset_task_queue_for_tests
_reset_task_queue_for_tests()
```

Inject a `LocalTaskQueue` directly in unit tests to avoid Redis:

```python
q = LocalTaskQueue(max_workers=1)
q.register("my_handler", my_mock_handler)
await q.enqueue("my_handler", arg1)
```

## Related Contexts

| Context | When to Load |
|---------|--------------|
| `docs/orchestrator/services/worker.md` | Handler bodies, ARQ `WorkerSettings`, agent task lifecycle |
| `docs/orchestrator/services/pubsub.md` | Redis Streams for event publishing, cancellation signals |
| `docs/orchestrator/services/agent-task.md` | `AgentTaskPayload` serialization envelope |
| `docs/orchestrator/services/distributed-lock.md` | Per-project lock acquired inside `execute_agent_task` |
