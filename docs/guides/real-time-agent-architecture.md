# Real-Time Agent Architecture Guide

## Overview

Tesslate Studio uses a distributed agent execution system that separates request handling from computation. API pods accept requests and return immediately, worker pods execute long-running agent tasks, and Redis provides the communication fabric between them. This architecture ensures the API remains responsive, agent tasks survive pod restarts, and multiple consumers (WebSocket clients, SSE clients, polling clients) can observe the same execution in real time.

## System Interaction Diagram

```
Frontend (WebSocket)                    External Client (API Key)
  |                                       |
  v                                       v
+-------------------------------------------------------+
|                    API Pod                              |
|  (main.py + routers/chat.py + routers/external_agent)  |
|                                                         |
|  1. Create Chat + Message in DB                         |
|  2. Build AgentTaskPayload (agent_context.py)           |
|  3. Enqueue to ARQ (Redis queue)                        |
|  4. Return task_id immediately (non-blocking)           |
|                                                         |
|  Also handles:                                          |
|  - WebSocket event forwarding (subscribe to Redis)      |
|  - SSE streaming (subscribe to Redis Stream)            |
|  - Status polling (query TaskManager)                   |
+-------------------------------------------------------+
          |                          ^
          | enqueue                  | subscribe
          v                          |
+-------------------------------------------------------+
|                      Redis                              |
|                                                         |
|  Pub/Sub Channels:                                      |
|    tesslate:ws:{user_id}    -> WS event forwarding      |
|    tesslate:ws:{project_id} -> project-scoped events    |
|                                                         |
|  Streams:                                               |
|    tesslate:agent:stream:{task_id} -> durable events    |
|    (XADD on each step, XREAD for consumers)             |
|                                                         |
|  Keys:                                                  |
|    project:{project_id}:lock     -> heartbeat lock      |
|    task:{task_id}:cancel         -> cancellation flag    |
|    session:{session_id}:owner    -> session ownership    |
|    arq:queue                     -> ARQ task queue       |
+-------------------------------------------------------+
          |                          ^
          | dequeue                  | publish events
          v                          |
+-------------------------------------------------------+
|                   Worker Pod                            |
|  (worker.py - same Docker image as API)                 |
|                                                         |
|  1. Pick up AgentTaskPayload from ARQ queue             |
|  2. Acquire project lock (fail-fast if held)            |
|  3. Run agent.run(message, context)                     |
|     |                                                   |
|     +-- For each iteration:                             |
|     |   a. Check cancellation flag in Redis             |
|     |   b. Call LLM (LiteLLM -> OpenAI/Anthropic)       |
|     |   c. Execute tool calls                           |
|     |   d. Publish agent_step to Redis Stream (XADD)    |
|     |   e. INSERT AgentStep row in DB (progressive)     |
|     |   f. Publish WS event via Redis Pub/Sub           |
|     |                                                   |
|  4. Publish agent_event("done") to Redis Stream         |
|  5. Finalize Message in DB (status, token counts)       |
|  6. Release project lock                                |
|  7. Enqueue webhook callback (if webhook_url provided)  |
+-------------------------------------------------------+
          |
          v
+-------------------------------------------------------+
|                    PostgreSQL                            |
|                                                         |
|  Tables:                                                |
|    chats          - Chat sessions (origin: "web"|"api") |
|    messages       - User and assistant messages          |
|    agent_steps    - Each tool call / text step           |
|    external_api_keys - Hashed API keys for auth         |
|    projects       - Project metadata and state           |
+-------------------------------------------------------+
```

## Request Lifecycle

### 1. Client Sends Request

**From the UI (WebSocket):**
The frontend sends a chat message over an established WebSocket connection. The API pod's `chat.py` router handles it.

**From an external system (HTTP):**
An external client sends `POST /api/external/agent/invoke` with a Bearer token. The `external_agent.py` router handles it.

### 2. API Pod Prepares the Task

Both paths converge on the same preparation logic:

1. **Create/reuse chat session** - For UI requests, the existing chat is used. For external requests, a new chat with `origin="api"` is created.
2. **Persist the user message** - INSERT into `messages` table so the conversation is durable.
3. **Build agent context** (`agent_context.py`) - Gathers project file tree, container state, environment info, and conversation history into a structured payload.
4. **Construct `AgentTaskPayload`** - A serializable object containing everything the worker needs: message content, agent configuration, project context, user identity, callback URLs.
5. **Enqueue to ARQ** - Push the payload onto the Redis-backed ARQ queue. This is a fast O(1) operation.
6. **Return immediately** - The API pod returns a `task_id` to the client. No blocking. The client can now subscribe to events or poll for status.

### 3. Worker Picks Up the Task

The ARQ worker (running in a separate pod, same Docker image) dequeues the task:

1. **Acquire project lock** - A Redis key with TTL acts as a heartbeat lock. If another worker is already running a task on the same project, the new task fails fast (prevents concurrent modifications to the same codebase).
2. **Instantiate the agent** - Uses `factory.py` to create an agent with the appropriate tools and system prompt.
3. **Execute the agent loop** - The agent runs iteratively:
   - Call the LLM with conversation context and available tools
   - If the LLM returns tool calls, execute them (file writes, shell commands, etc.)
   - After each iteration, check the cancellation flag in Redis
   - Publish each step to both the Redis Stream (for SSE/polling consumers) and Redis Pub/Sub (for WebSocket consumers)
   - INSERT each `AgentStep` row into PostgreSQL immediately (progressive persistence)
4. **Finalize** - Update the message record with final status, token usage, and response text. Publish a `done` event. Release the project lock.
5. **Webhook callback** - If a `webhook_url` was provided, enqueue an ARQ task to POST the results to that URL.

### 4. Client Receives Updates

**WebSocket (UI):**
The API pod subscribes to Redis Pub/Sub on channels scoped to the user and project. When events arrive, they are forwarded over the WebSocket to the frontend, which renders agent steps in real time.

**SSE (External):**
The client opens a long-lived HTTP connection to `GET /api/external/agent/events/{task_id}`. The API pod uses `XREAD` on the Redis Stream for that task, forwarding each entry as an SSE event. If the connection drops, the client reconnects with `last_event_id` and the server replays missed events via `XRANGE`.

**Polling (External):**
The client periodically calls `GET /api/external/agent/status/{task_id}`. The API pod queries the TaskManager (which checks both in-memory state and Redis) and returns the current status.

## Key Design Patterns

### 1. Progressive Persistence

Every agent step is inserted into the `agent_steps` database table as it happens, not batched at the end. This means:

- If the worker crashes mid-execution, all completed steps are preserved
- The UI can display partial progress even after a failure
- Chat history is accurate and complete regardless of task outcome
- Steps have ordering metadata for correct reconstruction

### 2. Redis Fallback (Graceful Degradation)

The system is designed to work without Redis, falling back to in-memory-only operation:

- **Without Redis**: Tasks run in-process (no ARQ queue), events are delivered directly via in-memory pub/sub, locks are process-local. This mode works for single-pod development.
- **With Redis**: Tasks are distributed across worker pods, events flow through Redis Pub/Sub and Streams, locks are distributed. This mode is required for production multi-pod deployments.

The codebase uses conditional checks rather than hard dependencies, so a Redis outage degrades gracefully rather than causing total failure.

### 3. Non-Blocking Everything

No endpoint blocks waiting for agent completion:

- `invoke` returns immediately after enqueuing
- `events` uses async generators (SSE streaming, no thread blocking)
- `status` is a simple read from TaskManager state
- WebSocket event forwarding is async pub/sub subscription
- Webhook callbacks are enqueued as separate ARQ tasks

This ensures the API pod can handle many concurrent requests even when agents are running long tasks.

### 4. Cross-Pod Visibility

In a multi-pod deployment, the user's HTTP request may hit a different API pod than the one that enqueued the task, and the worker is always a different pod. Redis provides the shared state:

- **Pub/Sub channels** ensure WebSocket events reach the correct API pod (the one holding the user's WebSocket connection)
- **Redis Streams** provide durable, ordered event logs that any API pod can read for SSE delivery
- **Redis keys** provide distributed locks and cancellation flags visible to all pods

### 5. Heartbeat Locks

Project locks use a TTL-based pattern:

1. Worker acquires lock: `SET project:{id}:lock {worker_id} EX 30 NX`
2. Worker refreshes lock every 10 seconds (heartbeat)
3. If the worker crashes, the lock expires after 30 seconds
4. New workers can acquire the lock after expiry

This prevents two workers from modifying the same project simultaneously while avoiding permanent lock deadlocks from crashed workers.

### 6. Distributed Cleanup

Background maintenance tasks (expired lock cleanup, orphaned task detection) must run on exactly one pod to avoid conflicts:

1. A single cleanup lock is held by one API/worker pod
2. That pod runs periodic background tasks
3. If the lock holder dies, another pod acquires the lock after TTL expiry
4. Cleanup tasks are idempotent, so duplicate execution is safe (just wasteful)

## Data Flow: Agent Step Events

Each agent step follows this path from worker to client:

```
Worker: agent executes tool call
  |
  +--> INSERT agent_steps row (PostgreSQL)     [durable storage]
  |
  +--> XADD to Redis Stream                    [SSE consumers]
  |      tesslate:agent:stream:{task_id}
  |
  +--> PUBLISH to Redis Pub/Sub                [WebSocket consumers]
         tesslate:ws:{user_id}
         tesslate:ws:{project_id}
```

Each consumer type reads from a different source:

| Consumer | Source | Delivery |
|----------|--------|----------|
| WebSocket (UI) | Redis Pub/Sub | Real-time push |
| SSE (External) | Redis Stream | Real-time push + replay |
| Polling (External) | TaskManager / DB | On-demand pull |
| Page reload (UI) | PostgreSQL `agent_steps` | Full history |

## Cancellation Flow

```
Client: sends cancel request
  |
  v
API Pod: SET task:{task_id}:cancel 1 EX 300
  |
  v
Worker: checks cancellation flag between iterations
  |
  +--> If set: stop agent loop, publish "cancelled" event, release lock
  +--> If not set: continue to next iteration
```

Cancellation is cooperative. The agent completes its current iteration (including any in-flight tool call) before checking the flag. This ensures the project is left in a consistent state.

## Infrastructure Requirements

### Redis

| Environment | Implementation | Notes |
|-------------|---------------|-------|
| Docker Compose | Standalone Redis container | Defined in `docker-compose.yml` |
| Kubernetes (Minikube) | Redis pod in `tesslate` namespace | Single replica |
| AWS EKS (Production) | Amazon ElastiCache (Redis) | Managed, multi-AZ |

Redis is used for:
- ARQ task queue (agent job distribution)
- Pub/Sub channels (real-time WebSocket event forwarding)
- Streams (durable SSE event logs per task)
- Key-value (project locks, cancellation flags, session ownership)

### ARQ Worker Pods

Workers run the same Docker image as the API backend but with a different entrypoint:

```
# API pod entrypoint
uvicorn app.main:app

# Worker pod entrypoint
arq app.worker.WorkerSettings
```

In Kubernetes, the worker is a separate Deployment with its own replica count, resource limits, and scaling configuration. Workers need:
- Access to Redis (for queue + pub/sub + streams)
- Access to PostgreSQL (for reading context and writing steps)
- Access to the Kubernetes API (for executing commands in project containers)
- Network access to LLM providers (OpenAI, Anthropic via LiteLLM)

### Database Tables

| Table | Purpose |
|-------|---------|
| `agent_steps` | Individual steps (tool calls, text outputs) with ordering and metadata |
| `external_api_keys` | SHA-256 hashed API keys with expiration and project scoping |
| `chats` | Chat sessions with `origin` field distinguishing `"web"` vs `"api"` |
| `messages` | User and assistant messages with status tracking and token counts |

## Configuration

All settings are in `orchestrator/app/config.py`:

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `redis_url` | `str` | `redis://localhost:6379` | Redis connection string (also accepts `rediss://` for TLS) |
| `worker_max_jobs` | `int` | `10` | Maximum concurrent agent tasks per worker pod |
| `worker_job_timeout` | `int` | `600` | Maximum seconds a single agent task can run before timeout |
| `worker_max_tries` | `int` | `2` | Number of retry attempts for failed tasks |

### Environment-Specific Configuration

| Setting | Docker Compose | Minikube | AWS EKS |
|---------|---------------|----------|---------|
| `redis_url` | `redis://redis:6379` | `redis://redis-service:6379` | `rediss://tesslate-redis.xxx.cache.amazonaws.com:6379` |
| Worker replicas | 1 (docker-compose service) | 1 (k8s Deployment) | 2+ (k8s Deployment with HPA) |
| Job timeout | 600s | 600s | 600s |

## Failure Modes and Recovery

### Worker Crashes Mid-Task

1. Progressive persistence ensures all completed steps are in the database
2. The project heartbeat lock expires after TTL (30s)
3. The Redis Stream retains all published events (clients can still read history)
4. The task status transitions to `"failed"` when ARQ detects the lost worker
5. The user can retry by sending a new message

### Redis Unavailable

1. ARQ cannot enqueue new tasks -- invoke endpoints return 503
2. Existing WebSocket connections lose real-time updates
3. SSE streams disconnect
4. Polling still works (reads from TaskManager/DB)
5. When Redis recovers, new tasks can be enqueued normally
6. In-flight tasks on workers continue (they already have their payload)

### Database Unavailable

1. New invocations fail (cannot create chat/message)
2. In-flight tasks fail when trying to persist steps
3. Agent steps are lost if they were published to Redis but not yet written to DB
4. Recovery: tasks can be retried after DB recovery

### Network Partition (API pod cannot reach Worker pod via Redis)

1. Tasks remain in the ARQ queue until a worker can dequeue them
2. Events published by the worker are buffered in Redis
3. API pods will receive events when connectivity is restored
4. Redis Streams provide durability -- no events are lost

## Related Documentation

### Services
- [Pub/Sub System](../orchestrator/services/pubsub.md) - Redis pub/sub and streams implementation
- [Worker](../orchestrator/services/worker.md) - ARQ worker configuration and task execution
- [Distributed Lock](../orchestrator/services/distributed-lock.md) - Heartbeat lock implementation
- [Agent Task](../orchestrator/services/agent-task.md) - AgentTaskPayload structure and lifecycle
- [Agent Context](../orchestrator/agent/agent-context.md) - Project context builder for agent invocations
- [Session Router](../orchestrator/services/session-router.md) - Shell session ownership and routing

### Routers
- [External Agent API](../orchestrator/routers/external-agent.md) - External API endpoints (invoke, events, status, keys)
- [Chat Router](../orchestrator/routers/chat.md) - UI-facing chat and WebSocket endpoints

### Infrastructure
- [Kubernetes Architecture](../infrastructure/kubernetes/CLAUDE.md) - K8s deployment manifests including worker
- [Docker Setup](docker-setup.md) - Docker Compose setup including Redis and worker services
- [AWS Deployment](aws-deployment.md) - Terraform-managed ElastiCache and EKS worker configuration
