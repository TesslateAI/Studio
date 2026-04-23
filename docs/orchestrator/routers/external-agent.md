# External Agent API

## Purpose

The External Agent API enables external systems (Slack bots, CLI tools, Discord bots, webhooks, custom integrations) to invoke Tesslate AI agents programmatically. It provides a complete lifecycle: authenticate with API keys, invoke an agent task, stream or poll for results, and optionally receive webhook callbacks on completion.

**Key source files:**
- `orchestrator/app/routers/external_agent.py` - Router with all endpoints
- `orchestrator/app/auth_external.py` - Bearer token authentication dependency

## Authentication

External API requests authenticate via Bearer tokens in the `Authorization` header:

```
Authorization: Bearer tsk_a1b2c3d4e5f6...
```

### Token Format

- Prefix: `tsk_`
- Body: 32 random hex characters
- Example: `tsk_8f3a1b2c4d5e6f7a8b9c0d1e2f3a4b5c`

### How Auth Works (`auth_external.py`)

1. Extract `Bearer tsk_...` from `Authorization` header
2. Compute SHA-256 hash of the raw token
3. Look up the hash in the `external_api_keys` table
4. Validate:
   - Key exists and `is_active = True`
   - Key has not expired (`expires_at` is null or in the future)
5. Load the associated `User` from the key's `user_id`
6. Attach `_api_key_record` to the user object for downstream scope checks (e.g., project scoping)
7. Return the user object as the authenticated principal

If any validation step fails, the endpoint returns `401 Unauthorized`.

### Project Scoping

API keys can optionally be scoped to a specific project. When a key has `project_id` set, the `invoke` endpoint validates that the requested project matches the key's scope. Unscoped keys can access any project the user owns.

## Endpoints

### 1. POST `/api/external/agent/invoke`

Invoke an AI agent on a project. This is the primary entry point for external integrations.

**Auth**: Bearer token (`tsk_...`)

**Request Body** (`ExternalAgentInvokeRequest`):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `project_id` | `UUID` | Yes | Target project ID |
| `message` | `str` | Yes | User message / instruction for the agent |
| `container_id` | `UUID` | No | Specific container to target (defaults to primary) |
| `agent_id` | `UUID` | No | Specific agent to use (defaults to project's agent) |
| `webhook_url` | `str` | No | URL to POST results to on completion |

**Response** (`ExternalAgentInvokeResponse`):

| Field | Type | Description |
|-------|------|-------------|
| `task_id` | `str` | Unique identifier for tracking this agent task |
| `chat_id` | `UUID` | Chat session ID created for this invocation |
| `events_url` | `str` | SSE endpoint URL for streaming events |
| `status` | `str` | Initial status (always `"queued"`) |

**How it works:**

1. Validates the API key has access to the requested project
2. Creates a new chat session with `origin="api"` to distinguish from UI chats
3. Creates the user message record in the database
4. Builds project context via `agent_context.py` (file tree, container state, etc.)
5. Constructs an `AgentTaskPayload` with all necessary context
6. Enqueues the payload to ARQ (Redis task queue) for worker processing
7. Returns the `task_id` and `events_url` immediately (non-blocking)

**Example:**

```bash
curl -X POST https://opensail.tesslate.com/api/external/agent/invoke \
  -H "Authorization: Bearer tsk_8f3a1b2c4d5e6f7a8b9c0d1e2f3a4b5c" \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "550e8400-e29b-41d4-a716-446655440000",
    "message": "Add error handling to the /api/users endpoint",
    "webhook_url": "https://my-server.com/hooks/tesslate"
  }'
```

**Response:**

```json
{
  "task_id": "arq:task:abc123",
  "chat_id": "660e8400-e29b-41d4-a716-446655440000",
  "events_url": "/api/external/agent/events/arq:task:abc123",
  "status": "queued"
}
```

### 2. GET `/api/external/agent/events/{task_id}`

Stream real-time agent events via Server-Sent Events (SSE). This is the recommended way to follow agent execution in real time.

**Auth**: Bearer token (`tsk_...`)

**Path Parameters:**

| Field | Type | Description |
|-------|------|-------------|
| `task_id` | `str` | Task ID from the invoke response |

**Query Parameters:**

| Field | Type | Description |
|-------|------|-------------|
| `last_event_id` | `str` | Optional. Resume from this event ID (for reconnection) |

**Event Stream Format:**

```
event: agent_step
id: evt_001
data: {"type": "tool_call", "tool": "write_file", "args": {"path": "src/api.ts"}, ...}

event: agent_step
id: evt_002
data: {"type": "text", "content": "I've updated the error handling..."}

event: done
id: evt_003
data: {"status": "completed", "response": "Done. Added try-catch blocks..."}
```

**Reconnection:**

If the SSE connection drops, clients can reconnect by passing the last received event ID:

```
GET /api/external/agent/events/{task_id}?last_event_id=evt_002
```

This uses `subscribe_agent_events_from()` to replay missed events from the Redis stream before switching to live subscription. This guarantees no events are lost during reconnection.

**Example:**

```bash
curl -N -H "Authorization: Bearer tsk_8f3a1b2c..." \
  https://opensail.tesslate.com/api/external/agent/events/arq:task:abc123
```

### 3. GET `/api/external/agent/status/{task_id}`

Poll for agent task status. Use this as an alternative to SSE when streaming is not practical (e.g., simple webhook integrations, CI pipelines).

**Auth**: Bearer token (`tsk_...`)

**Path Parameters:**

| Field | Type | Description |
|-------|------|-------------|
| `task_id` | `str` | Task ID from the invoke response |

**Response** (`ExternalAgentStatusResponse`):

| Field | Type | Description |
|-------|------|-------------|
| `status` | `str` | `"queued"`, `"running"`, `"completed"`, `"failed"`, `"cancelled"` |
| `response` | `str?` | Final agent response text (null until completed) |
| `iterations` | `int` | Number of agent iterations completed |
| `tool_calls` | `int` | Number of tool calls executed |
| `started_at` | `datetime?` | When the worker picked up the task |
| `completed_at` | `datetime?` | When the task finished |

**Example:**

```bash
curl -H "Authorization: Bearer tsk_8f3a1b2c..." \
  https://opensail.tesslate.com/api/external/agent/status/arq:task:abc123
```

**Response:**

```json
{
  "status": "completed",
  "response": "I've added comprehensive error handling to the /api/users endpoint...",
  "iterations": 3,
  "tool_calls": 5,
  "started_at": "2026-02-26T10:00:01Z",
  "completed_at": "2026-02-26T10:00:15Z"
}
```

## API Key Management

These endpoints are authenticated via standard session auth (not Bearer tokens) and are used by the Tesslate UI to manage API keys.

### POST `/api/external/keys`

Create a new API key for the authenticated user.

**Rate Limit**: Maximum 10 active keys per user.

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | `str` | Yes | Human-readable key name |
| `expires_at` | `datetime` | No | Optional expiration timestamp |
| `project_id` | `UUID` | No | Optional project scope |

**Response** (`ExternalAPIKeyResponse`):

Returns key metadata including the **raw key** (`tsk_...`). This is the **only time** the raw key is returned. It cannot be retrieved later.

```json
{
  "id": "key-uuid",
  "name": "My Slack Bot",
  "key_prefix": "tsk_8f3a",
  "raw_key": "tsk_8f3a1b2c4d5e6f7a8b9c0d1e2f3a4b5c",
  "is_active": true,
  "created_at": "2026-02-26T10:00:00Z",
  "expires_at": null,
  "project_id": null
}
```

**Key generation process:**

1. Generate 32 random hex characters
2. Prepend `tsk_` prefix
3. Compute SHA-256 hash of the full token
4. Store only the hash and a 4-character prefix in the database
5. Return the raw key to the user once

### GET `/api/external/keys`

List all API keys for the authenticated user.

**Response**: Array of `ExternalAPIKeyResponse` objects. The `raw_key` field is **always null** in list responses (keys cannot be retrieved after creation).

### DELETE `/api/external/keys/{key_id}`

Deactivate (soft delete) an API key. The key record remains in the database with `is_active = False` but can no longer be used for authentication.

**Path Parameters:**

| Field | Type | Description |
|-------|------|-------------|
| `key_id` | `UUID` | API key ID to deactivate |

**Response**: `204 No Content` on success.

## Schemas Reference

All schemas are defined in `orchestrator/app/schemas.py`.

### `ExternalAPIKeyResponse`

API key metadata. The `raw_key` field is only populated on creation.

```python
class ExternalAPIKeyResponse(BaseModel):
    id: UUID
    name: str
    key_prefix: str          # First 4 chars of the token (for identification)
    raw_key: Optional[str]   # Full token, only returned on creation
    is_active: bool
    created_at: datetime
    expires_at: Optional[datetime]
    project_id: Optional[UUID]
```

### `ExternalAgentInvokeRequest`

Request body for invoking an agent.

```python
class ExternalAgentInvokeRequest(BaseModel):
    project_id: UUID
    message: str
    container_id: Optional[UUID]
    agent_id: Optional[UUID]
    webhook_url: Optional[str]
```

### `ExternalAgentInvokeResponse`

Response from a successful invoke call.

```python
class ExternalAgentInvokeResponse(BaseModel):
    task_id: str
    chat_id: UUID
    events_url: str
    status: str              # Always "queued" on creation
```

### `ExternalAgentStatusResponse`

Current status of an agent task.

```python
class ExternalAgentStatusResponse(BaseModel):
    status: str              # queued | running | completed | failed | cancelled
    response: Optional[str]
    iterations: int
    tool_calls: int
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
```

## Integration Patterns

### Synchronous (Poll until done)

```python
import requests, time

API = "https://opensail.tesslate.com/api/external"
HEADERS = {"Authorization": "Bearer tsk_..."}

# Invoke
resp = requests.post(f"{API}/agent/invoke", headers=HEADERS, json={
    "project_id": "...",
    "message": "Fix the login bug"
})
task_id = resp.json()["task_id"]

# Poll
while True:
    status = requests.get(f"{API}/agent/status/{task_id}", headers=HEADERS).json()
    if status["status"] in ("completed", "failed", "cancelled"):
        print(status["response"])
        break
    time.sleep(2)
```

### Asynchronous (SSE streaming)

```python
import sseclient, requests

API = "https://opensail.tesslate.com/api/external"
HEADERS = {"Authorization": "Bearer tsk_..."}

resp = requests.post(f"{API}/agent/invoke", headers=HEADERS, json={
    "project_id": "...",
    "message": "Add dark mode support"
})
events_url = resp.json()["events_url"]

stream = requests.get(f"https://opensail.tesslate.com{events_url}",
                       headers=HEADERS, stream=True)
client = sseclient.SSEClient(stream)
for event in client.events():
    print(f"[{event.event}] {event.data}")
    if event.event == "done":
        break
```

### Webhook Callback

```python
# Invoke with webhook_url - server will POST results when done
requests.post(f"{API}/agent/invoke", headers=HEADERS, json={
    "project_id": "...",
    "message": "Refactor the auth module",
    "webhook_url": "https://my-server.com/hooks/tesslate"
})
# Your webhook endpoint receives the completed status payload
```

## Related Documentation

- [Pub/Sub System](../services/pubsub.md) - Redis pub/sub and streams used for event delivery
- [Worker](../services/worker.md) - ARQ worker that executes agent tasks
- [Agent Task](../services/agent-task.md) - AgentTaskPayload structure and task lifecycle
- [Agent Context](../agent/agent-context.md) - How project context is built for agent invocations
- [Chat Router](chat.md) - UI-facing chat endpoints (contrast with external API)
