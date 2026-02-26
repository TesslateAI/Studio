# Worker Service - Decoupled Agent Task Execution

**File**: `orchestrator/app/worker.py` (509 lines)

Decoupled async task execution with durable state persistence and real-time streaming. Uses ARQ (Redis-based task queue) to process agent tasks dispatched from the API layer. Each task runs a full agent lifecycle: acquire lock, execute agent iterations with progressive step persistence, publish events to Redis Streams, finalize the message, and optionally call a webhook.

## When to Load This Context

Load this context when:
- Debugging agent task execution failures
- Modifying how agent results are persisted
- Working on the progressive step persistence pattern
- Adding new worker job types
- Understanding the agent event streaming pipeline
- Configuring worker scaling (concurrency, timeouts)

## Key Files

| File | Purpose |
|------|---------|
| `orchestrator/app/worker.py` | Worker implementation and ARQ job functions |
| `orchestrator/app/services/agent_task.py` | AgentTaskPayload definition |
| `orchestrator/app/services/agent_context.py` | Context builder (runs before dispatch) |
| `orchestrator/app/services/pubsub.py` | Event publishing (Redis Streams + Pub/Sub) |
| `orchestrator/app/services/distributed_lock.py` | Project lock for concurrency control |
| `orchestrator/app/agent/stream_agent.py` | Agent execution engine |
| `orchestrator/app/config.py` | Worker configuration settings |
| `k8s/base/core/worker-deployment.yaml` | K8s worker deployment manifest |
| `docker-compose.yml` | Docker worker service definition |

## Related Contexts

- **[pubsub.md](./pubsub.md)**: Redis Streams and Pub/Sub event publishing
- **[agent-task.md](./agent-task.md)**: Payload serialization and dispatch
- **[agent-context.md](./agent-context.md)**: Pre-built execution context
- **[distributed-lock.md](./distributed-lock.md)**: Project-level lock coordination
- **[../agent/CLAUDE.md](../agent/CLAUDE.md)**: Agent execution engine

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Agent Task Lifecycle                         │
│                                                                     │
│  API Pod                          Worker Pod                        │
│  ┌─────────────────┐             ┌─────────────────────────────┐   │
│  │ Chat Router      │             │ execute_agent_task()         │   │
│  │                  │  Enqueue    │                             │   │
│  │ Build context    │───────────►│ 1. Acquire project lock     │   │
│  │ Create payload   │  (ARQ      │ 2. Start heartbeat task     │   │
│  │ Enqueue job      │   Redis)   │ 3. Create agent instance    │   │
│  └─────────────────┘             │ 4. Run agent iterations     │   │
│                                  │    ├─ LLM call              │   │
│                                  │    ├─ Tool execution        │   │
│                                  │    ├─ Save AgentStep row    │   │
│                                  │    └─ Publish event         │   │
│                                  │ 5. Finalize Message         │   │
│                                  │ 6. Release project lock     │   │
│                                  │ 7. Publish "done" event     │   │
│                                  │ 8. Webhook callback         │   │
│                                  └─────────────────────────────┘   │
│                                           │                         │
│                                           │ Events                  │
│                                           ▼                         │
│                                  ┌─────────────────────────────┐   │
│                                  │ Redis Stream                 │   │
│                                  │ tesslate:agent:stream:{id}  │   │
│                                  └─────────────────────────────┘   │
│                                           │                         │
│                                           │ Forward                 │
│                                           ▼                         │
│                                  ┌─────────────────────────────┐   │
│                                  │ API Pod (PubSub subscriber)  │   │
│                                  │ → WebSocket → Client         │   │
│                                  └─────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

## Key Functions

### `execute_agent_task(ctx, payload_dict)`

Main entry point for agent task execution. This is the ARQ job function that runs the complete agent lifecycle.

```python
async def execute_agent_task(ctx, payload_dict: dict):
    """
    Full agent lifecycle:
    1. Acquire project lock (prevent concurrent agent runs)
    2. Start heartbeat background task (extend lock every 10s)
    3. Create agent instance from config
    4. Run agent with streaming iterations
    5. Persist each step to AgentStep table
    6. Publish each event to Redis Stream
    7. Finalize: update Message with result metadata
    8. Release lock, publish "done", call webhook
    """
```

### `_heartbeat_lock(lock, project_id, interval=10)`

Background asyncio task that extends the project lock every `interval` seconds. Runs concurrently with the agent execution to prevent the lock from expiring during long-running tasks.

```python
async def _heartbeat_lock(lock, project_id, interval=10):
    """Extend project lock TTL every 10 seconds."""
    while True:
        renewed = await lock.renew(f"project:{project_id}", ttl=30)
        if not renewed:
            logger.warning(f"Lost project lock for {project_id}")
            break
        await asyncio.sleep(interval)
```

The heartbeat is started as a background task and cancelled when the agent finishes.

### `send_webhook_callback(url, result)`

POST the agent's result to an external webhook URL. Used for API integrations where external systems need to be notified when an agent task completes.

```python
async def send_webhook_callback(url: str, result: dict):
    """POST result to external webhook URL."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            json=result,
            timeout=30.0
        )
        logger.info(f"Webhook callback to {url}: {response.status_code}")
```

The webhook URL is optional -- if not provided in the payload, this step is skipped.

### `_publish_error(task_id, error_message)`

Broadcast an error event to the Redis Stream so clients can display the error in the UI.

```python
async def _publish_error(task_id: str, error_message: str):
    """Publish error event and mark stream as done."""
    await publish_agent_event(task_id, {
        "type": "error",
        "error": error_message
    })
    await publish_agent_event(task_id, {
        "type": "done",
        "status": "error"
    })
```

## Progressive Step Persistence

Agent tasks can run many iterations (LLM call + tool execution cycles). Rather than waiting until the task completes to save results, each iteration is persisted immediately as an `AgentStep` row.

### AgentStep Table

Each iteration creates a row in the `AgentStep` table with the following `step_data` JSON structure:

```json
{
    "iteration": 3,
    "thought": "I need to update the header component...",
    "tool_calls": [
        {
            "tool": "write_file",
            "args": {"path": "/src/Header.tsx", "content": "..."},
            "call_id": "call_abc123"
        }
    ],
    "tool_results": [
        {
            "call_id": "call_abc123",
            "result": "File written successfully"
        }
    ],
    "response_text": null,
    "timestamp": "2026-02-26T12:34:56Z",
    "is_complete": false
}
```

### Metadata Flag

When steps are stored in the AgentStep table, the parent Message gets a metadata flag:

```python
message.metadata = {
    "steps_table": True,
    "task_id": "abc-123",
    "model": "claude-sonnet-4-20250514"
}
```

This flag tells the context builder (and frontend) to load steps from the AgentStep table rather than expecting them inline in the message content.

### Benefits

1. **Crash recovery**: If the worker crashes mid-task, completed steps are already persisted
2. **Real-time UI**: Frontend can query AgentStep rows to show progress before the task completes
3. **Reduced message size**: Message content stays compact; detailed steps live in their own table
4. **History resolution**: Chat history builder uses the `steps_table` flag to decide where to load steps from

## Configuration

### Worker Settings (config.py)

```python
class Settings:
    worker_max_jobs: int = 10          # Concurrent tasks per worker pod
    worker_job_timeout: int = 600      # 10 minutes max per task
    worker_max_tries: int = 2          # Retry once on failure
    redis_url: str = ""                # ARQ Redis connection
```

| Setting | Default | Purpose |
|---------|---------|---------|
| `worker_max_jobs` | 10 | Max concurrent agent tasks per pod |
| `worker_job_timeout` | 600s | Hard timeout per task (10 minutes) |
| `worker_max_tries` | 2 | Total attempts (1 retry) |

### ARQ Worker Class

```python
class WorkerSettings:
    functions = [execute_agent_task]
    redis_settings = RedisSettings(host=..., port=...)
    max_jobs = settings.worker_max_jobs
    job_timeout = settings.worker_job_timeout
    max_tries = settings.worker_max_tries
```

## Deployment

### Kubernetes

The worker runs as a separate Deployment sharing the same Docker image as the backend API, but with a different entrypoint.

**Manifest**: `k8s/base/core/worker-deployment.yaml`

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: tesslate-worker
  namespace: tesslate
spec:
  replicas: 1
  template:
    spec:
      containers:
        - name: worker
          image: tesslate-backend:latest   # Same image as API
          command: ["arq", "app.worker.WorkerSettings"]
          env:
            - name: REDIS_URL
              value: redis://redis:6379/0
          resources:
            requests:
              memory: 512Mi
              cpu: 250m
            limits:
              memory: 1Gi
              cpu: 1000m
```

### Docker Compose

```yaml
# docker-compose.yml
services:
  worker:
    build:
      context: ./orchestrator
      dockerfile: Dockerfile
    command: arq app.worker.WorkerSettings
    environment:
      REDIS_URL: redis://redis:6379/0
      DATABASE_URL: ${DATABASE_URL}
    depends_on:
      - redis
      - db
```

### Scaling

To handle more concurrent agent tasks, increase replicas:

```bash
# Kubernetes
kubectl scale deployment tesslate-worker -n tesslate --replicas=3

# Each replica handles up to worker_max_jobs concurrent tasks
# 3 replicas x 10 max_jobs = 30 concurrent agent tasks
```

## Error Handling

### Task-Level Errors

If the agent raises an unhandled exception, the worker:
1. Publishes an error event via `_publish_error()`
2. Updates the Message with error metadata
3. Releases the project lock
4. ARQ marks the job as failed

### Lock Acquisition Failure

If the project lock cannot be acquired (another task is already running on this project), the worker publishes an error event and returns without executing the agent.

### Timeout

If a task exceeds `worker_job_timeout` (default 10 minutes), ARQ terminates it. The project lock auto-expires after its TTL (30 seconds) and the heartbeat stops.

### Retry Behavior

With `max_tries=2`, a failed task is retried once. The retry receives the same payload dict. If the retry also fails, the job is marked as permanently failed in ARQ.

## Troubleshooting

### Task Stuck in Queue

1. Check ARQ queue length: `redis-cli LLEN arq:queue`
2. Verify worker is running: `kubectl get pods -n tesslate -l app=tesslate-worker`
3. Check worker logs: `kubectl logs -n tesslate -l app=tesslate-worker --tail=50`
4. Verify Redis connectivity from worker pod

### Task Fails Immediately

1. Check for lock contention: `redis-cli GET tesslate:project:lock:{project_id}`
2. Verify the payload is valid JSON (serialization issue)
3. Check worker logs for the specific error message
4. Confirm database connectivity from the worker pod

### Steps Not Persisting

1. Verify DATABASE_URL is set in the worker environment
2. Check for database connection errors in worker logs
3. Confirm AgentStep table exists (run migrations)
4. Check that `steps_table: True` is being set on the Message

### Events Not Reaching Frontend

1. Verify the worker is publishing to Redis Streams: `redis-cli XLEN tesslate:agent:stream:{task_id}`
2. Check PubSub subscriber is running on the API pod
3. Confirm WebSocket connection is established
4. See [pubsub.md](./pubsub.md) troubleshooting section

### Webhook Not Called

1. Verify `webhook_url` is present in the payload
2. Check worker logs for webhook callback status code
3. Confirm the webhook endpoint is reachable from the worker pod
4. Check for timeout (30-second limit on webhook calls)
