# PubSub Service - Cross-Pod Communication Bridge

**File**: `orchestrator/app/services/pubsub.py` (643 lines)

Cross-pod communication bridge using Redis for WebSocket-connected clients. Provides three distinct subsystems for different communication patterns: status broadcasts, durable event streaming, and project-level locking.

## When to Load This Context

Load this context when:
- Working on real-time WebSocket event delivery
- Debugging agent event streaming across pods
- Implementing cross-pod notifications
- Working with project locks or cancellation signals
- Troubleshooting events not reaching WebSocket clients

## Key Files

| File | Purpose |
|------|---------|
| `orchestrator/app/services/pubsub.py` | PubSub implementation (all three subsystems) |
| `orchestrator/app/services/distributed_lock.py` | Project lock primitives used by PubSub |
| `orchestrator/app/services/cache_service.py` | Shared Redis connection pool |
| `orchestrator/app/worker.py` | Primary producer of agent events |
| `orchestrator/app/routers/chat.py` | WebSocket consumer of events |

## Related Contexts

- **[worker.md](./worker.md)**: ARQ worker that publishes agent events to Redis Streams
- **[distributed-lock.md](./distributed-lock.md)**: Lock primitives used for project locking
- **[cache.md](./cache.md)**: Shared Redis infrastructure
- **[session-router.md](./session-router.md)**: Cross-pod session ownership tracking

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         PubSub Service                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌───────────────────┐  ┌──────────────────┐  ┌─────────────────┐ │
│  │  Redis Pub/Sub    │  │  Redis Streams   │  │  Project Locks  │ │
│  │  (Status Updates) │  │  (Agent Events)  │  │  (Coordination) │ │
│  │                   │  │                  │  │                 │ │
│  │  Channel:         │  │  Stream Key:     │  │  Key:           │ │
│  │  tesslate:ws:     │  │  tesslate:agent: │  │  tesslate:      │ │
│  │  {user}:{project} │  │  stream:{task}   │  │  project:lock:  │ │
│  │                   │  │                  │  │  {project_id}   │ │
│  │  Pattern sub:     │  │  XADD for write  │  │                 │ │
│  │  tesslate:ws:*    │  │  XRANGE + XREAD  │  │  TTL: 30s       │ │
│  │                   │  │  BLOCK for read  │  │  Lua atomics    │ │
│  └───────────────────┘  └──────────────────┘  └─────────────────┘ │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │  Event Forwarding: Redis Streams → Local WebSocket Clients   │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │  Cancellation Signals: tesslate:agent:cancel:{task_id}       │ │
│  │  TTL: 10 minutes                                              │ │
│  └───────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

## Subsystem 1: Redis Pub/Sub (Status Updates)

Standard Redis Pub/Sub for lightweight, fire-and-forget status broadcasts. Used for project status changes, container lifecycle events, and general WebSocket notifications.

### Channel Pattern

```
tesslate:ws:{user_id}:{project_id}
```

A background subscriber listens on the pattern `tesslate:ws:*` and fans out received messages to locally connected WebSocket clients.

### Publishing Events

```python
from app.services.pubsub import publish_ws_event

# Broadcast a status update to all pods with connected clients
await publish_ws_event(
    user_id=str(user.id),
    project_id=str(project.id),
    event={
        "type": "container_status",
        "status": "running",
        "container": "frontend"
    }
)
```

### Subscriber Lifecycle

```python
from app.services.pubsub import start_subscriber, stop_subscriber

# Start during app startup (main.py)
await start_subscriber()

# Stop during app shutdown (main.py)
await stop_subscriber()
```

The subscriber runs as a background asyncio task. On each received message, it looks up locally connected WebSocket clients for the `{user_id}:{project_id}` pair and forwards the event.

## Subsystem 2: Redis Streams (Agent Events)

Durable event storage for agent execution. Unlike Pub/Sub, Redis Streams persist events so late-joining clients can replay missed events.

### Stream Key

```
tesslate:agent:stream:{task_id}
```

### Writing Events

```python
from app.services.pubsub import publish_agent_event

# Worker publishes events as agent executes
await publish_agent_event(
    task_id="abc-123",
    event={
        "type": "tool_call",
        "tool": "write_file",
        "path": "/src/App.tsx",
        "iteration": 3
    }
)
```

Events are written using `XADD`. When a `"done"` event is published, the stream is given a 1-hour TTL via `EXPIRE` so it auto-cleans.

### Reading Events (Replay + Live Tail)

```python
from app.services.pubsub import subscribe_agent_events

# Full replay from beginning, then live tail
async for event in subscribe_agent_events(task_id="abc-123"):
    if event.get("type") == "done":
        break
    process_event(event)
```

Internally this uses `XRANGE` for replaying existing events, then switches to `XREAD BLOCK` for live-tailing new events as they arrive.

### Reading From a Specific Point

```python
from app.services.pubsub import subscribe_agent_events_from

# Resume from a known stream ID (e.g., after reconnect)
async for event in subscribe_agent_events_from(
    task_id="abc-123",
    last_id="1700000000000-0"
):
    process_event(event)
```

## Subsystem 3: Project Locks

Prevents concurrent agent executions on the same project. Uses Redis `SET NX EX` with Lua scripts for atomic check-and-set operations.

### Lock Key

```
tesslate:project:lock:{project_id}
```

### Lock Properties

- **TTL**: 30 seconds (auto-expires if holder crashes)
- **Heartbeat**: Active holders extend the lock periodically
- **Atomic operations**: Lua scripts ensure check-and-set is a single Redis operation, preventing race conditions

### Usage

Project locks are acquired automatically by the worker before running an agent task and released on completion. The heartbeat extension runs every 10 seconds to keep the lock alive during long-running tasks.

## Cancellation Signals

Allow in-progress agent tasks to be cancelled from any pod.

### Key Pattern

```
tesslate:agent:cancel:{task_id}
```

### TTL

10 minutes. The key is set when a user requests cancellation and checked by the worker on each agent iteration. After 10 minutes the signal expires even if never consumed.

### Publishing a Cancellation

```python
from app.services.pubsub import publish_cancellation

await publish_cancellation(task_id="abc-123")
```

### Checking for Cancellation

```python
from app.services.pubsub import is_cancelled

if await is_cancelled(task_id="abc-123"):
    # Stop agent execution gracefully
    break
```

## Event Forwarding

The `_forward_agent_events_to_ws()` function bridges Redis Streams to local WebSocket clients. When a pod receives an agent task notification (via Pub/Sub), it checks whether any local WebSocket clients are interested in that task. If so, it spawns a background coroutine that subscribes to the Redis Stream and pushes events through the WebSocket connection.

### Cross-Source Visibility

```python
from app.services.pubsub import publish_agent_task_notification

# Notify all pods that a new agent task is running
# Pods with connected clients will start forwarding events
await publish_agent_task_notification(
    user_id=str(user.id),
    project_id=str(project.id),
    task_id="abc-123"
)
```

This ensures that regardless of which pod the worker runs on, the pod with the user's WebSocket connection will pick up and forward the events.

## Key Functions

| Function | Purpose |
|----------|---------|
| `start_subscriber()` | Start the background Pub/Sub listener |
| `stop_subscriber()` | Gracefully stop the subscriber |
| `publish_ws_event()` | Broadcast a status event via Pub/Sub |
| `publish_agent_event()` | Write an event to a Redis Stream |
| `subscribe_agent_events()` | Replay + live tail a Redis Stream |
| `subscribe_agent_events_from()` | Resume reading from a specific stream ID |
| `publish_agent_task_notification()` | Notify pods of a new agent task for forwarding |
| `publish_cancellation()` | Signal an agent task to stop |
| `is_cancelled()` | Check if a cancellation signal exists |

## Configuration

### Environment Variables

```bash
# Redis connection (shared with cache and ARQ)
REDIS_URL=redis://redis:6379/0
```

### Timeouts and TTLs

| Parameter | Value | Purpose |
|-----------|-------|---------|
| Project lock TTL | 30 seconds | Auto-release if holder crashes |
| Stream TTL after done | 1 hour | Cleanup completed task streams |
| Cancellation signal TTL | 10 minutes | Expire unchecked cancellations |
| `XREAD BLOCK` timeout | 5000ms | Long-poll interval for live tail |

## Deployment

### Docker Compose

```yaml
# docker-compose.yml
services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  orchestrator:
    environment:
      REDIS_URL: redis://redis:6379/0

  worker:
    environment:
      REDIS_URL: redis://redis:6379/0
```

Both the orchestrator (API pods) and worker pods connect to the same Redis instance. The orchestrator runs the subscriber; the worker publishes events.

### Kubernetes

In K8s, multiple backend replicas each run their own subscriber. The pattern subscription (`tesslate:ws:*`) means every pod receives every message, but only the pod with the relevant WebSocket client forwards it. This is intentional and safe -- the fan-out is filtered locally.

## Troubleshooting

### Events Not Reaching WebSocket Clients

1. Verify the subscriber is running: check logs for `"PubSub subscriber started"`
2. Confirm Redis connectivity: `redis-cli PING`
3. Check the channel pattern matches: `redis-cli PSUBSCRIBE "tesslate:ws:*"`
4. Verify WebSocket client is registered in the local connection map

### Agent Events Missing or Delayed

1. Check the stream exists: `redis-cli XLEN tesslate:agent:stream:{task_id}`
2. Verify the worker is publishing: check worker logs for `"Publishing agent event"`
3. Check if the stream has expired (1-hour TTL after done event)
4. Try manual replay: `redis-cli XRANGE tesslate:agent:stream:{task_id} - +`

### Lock Contention

1. Check who holds the lock: `redis-cli GET tesslate:project:lock:{project_id}`
2. Verify heartbeat is running: lock value should update every 10 seconds
3. If a lock is stuck, it will auto-expire after 30 seconds
4. For manual override (use with caution): `redis-cli DEL tesslate:project:lock:{project_id}`

### Cancellation Not Working

1. Verify the signal was set: `redis-cli GET tesslate:agent:cancel:{task_id}`
2. Check the worker is polling for cancellation on each iteration
3. Confirm the task_id matches between the cancel request and the running task

## Subsystem 4: Gateway Delivery Stream

Durable stream for routing agent responses back to the originating messaging platform (Telegram, Discord, Slack, etc.). Used by the gateway process to deliver agent output after task completion.

### Stream Key

```
tesslate:gateway:deliveries
```

Configurable via `settings.gateway_delivery_stream`. Capped at `settings.gateway_delivery_maxlen` (default: 10,000 entries).

### Consumer Group Pattern

Uses `XREADGROUP` for reliable, exactly-once processing across gateway shards:

```
Consumer group: gateway-shard-{shard}
Consumer name:  consumer-{pid}
```

Each gateway shard creates its own consumer group and reads with `>` (new messages only). Messages are acknowledged with `XACK` after successful delivery.

### Message Fields

| Field | Purpose |
|-------|---------|
| `config_id` | ChannelConfig UUID — identifies which adapter to use |
| `session_key` | Session key (format: `platform:chat_type:chat_id[:thread_id]`) |
| `response` | Agent response text to deliver |
| `task_id` | Agent task ID for audit logging |

### Writing Deliveries

The worker publishes deliveries after agent task completion when `gateway_deliver` is set on the task payload:

```python
await redis.xadd(
    settings.gateway_delivery_stream,
    {"config_id": config_id, "session_key": key, "response": text, "task_id": task_id},
    maxlen=settings.gateway_delivery_maxlen,
)
```

### Reading Deliveries (Gateway Process)

```python
entries = await redis.xreadgroup(
    group, consumer, {stream: ">"}, count=10, block=5000
)
for stream_name, messages in entries:
    for msg_id, data in messages:
        await process_delivery(data)
        await redis.xack(stream, group, msg_id)
```

### Related Redis Keys

| Key | Purpose | TTL |
|-----|---------|-----|
| `tesslate:gateway:status` | Gateway shard heartbeat (JSON) | 120s |
| `tesslate:gateway:active:{config_id}` | Per-adapter liveness | 60s |
| `tesslate:gateway:reload` | Pub/Sub channel for hot-reload signal | N/A |

### Troubleshooting

1. Check the stream exists and has entries: `redis-cli XLEN tesslate:gateway:deliveries`
2. Check consumer group info: `redis-cli XINFO GROUPS tesslate:gateway:deliveries`
3. Check pending (unacked) messages: `redis-cli XPENDING tesslate:gateway:deliveries gateway-shard-0`
4. Verify the gateway process is running: `redis-cli GET tesslate:gateway:status`
