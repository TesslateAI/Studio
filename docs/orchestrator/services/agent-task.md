# Agent Task Payload - Serializable Task Envelope

**File**: `orchestrator/app/services/agent_task.py` (72 lines)

Serializable envelope for dispatching agent tasks from the API layer to the ARQ worker fleet. Encapsulates all information the worker needs to execute an agent task without further database lookups for context.

## When to Load This Context

Load this context when:
- Modifying the data sent from the chat router to the worker
- Adding new fields to the agent execution context
- Debugging serialization issues between API and worker
- Understanding the ARQ job dispatch interface

## Key Files

| File | Purpose |
|------|---------|
| `orchestrator/app/services/agent_task.py` | AgentTaskPayload dataclass |
| `orchestrator/app/services/agent_context.py` | Builds the context that goes into the payload |
| `orchestrator/app/worker.py` | Deserializes and executes the payload |
| `orchestrator/app/routers/chat.py` | Creates and enqueues the payload |

## Related Contexts

- **[worker.md](./worker.md)**: Worker that receives and executes the payload
- **[agent-context.md](./agent-context.md)**: Builds the pre-computed context fields
- **[pubsub.md](./pubsub.md)**: Events published during task execution

## AgentTaskPayload Fields

| Field | Type | Purpose |
|-------|------|---------|
| `task_id` | `str` | Unique identifier for this task (UUID) |
| `user_id` | `str` | ID of the user who initiated the request |
| `project_id` | `str` | ID of the project being worked on |
| `chat_id` | `str` | ID of the chat conversation |
| `message` | `str` | The user's message / instruction |
| `agent_id` | `str` | ID of the agent configuration to use |
| `model_name` | `str` | LLM model name (e.g., `"claude-sonnet-4-20250514"`) |
| `container_name` | `str` | Resolved container name for tool execution |
| `view` | `str` | UI view context (e.g., `"code"`, `"preview"`) |
| `edit_mode` | `str` | Editing mode (e.g., `"full"`, `"component"`) |
| `chat_history` | `list[dict]` | Pre-built chat history (from `_get_chat_history()`) |
| `project_context` | `dict` | Pre-built project context (architecture, git, TESSLATE.md) |
| `webhook_url` | `str or None` | Optional callback URL for external integrations |

## Serialization

The payload must be JSON-serializable for transport through the ARQ Redis queue.

### `to_dict() -> dict`

Converts the payload to a JSON-safe dictionary:

```python
payload = AgentTaskPayload(
    task_id="abc-123",
    user_id="user-456",
    project_id="proj-789",
    chat_id="chat-012",
    message="Add a dark mode toggle to the header",
    agent_id="agent-345",
    model_name="claude-sonnet-4-20250514",
    container_name="frontend",
    view="code",
    edit_mode="full",
    chat_history=[
        {"role": "user", "content": "Create a React app"},
        {"role": "assistant", "content": "I'll set up..."}
    ],
    project_context={
        "architecture": {...},
        "git": {...},
        "tesslate_md": "# My Project\n..."
    },
    webhook_url=None
)

# Serialize for ARQ
data = payload.to_dict()
# Returns a plain dict with all fields JSON-serializable
```

### Enqueuing to ARQ

```python
from arq import ArqRedis

arq_pool: ArqRedis = await create_pool(RedisSettings(...))

await arq_pool.enqueue_job(
    "execute_agent_task",
    payload.to_dict()
)
```

The worker receives the dict and uses it directly -- there is no deserialization back into `AgentTaskPayload`. The worker accesses fields via dictionary key lookup.

## Usage Flow

```
┌────────────────────┐
│  Chat Router       │
│  (routers/chat.py) │
│                    │
│  1. Parse request  │
│  2. Build context  │
│  3. Create payload │
│  4. Enqueue job    │
└────────┬───────────┘
         │
         │  payload.to_dict() → ARQ Redis queue
         │
         ▼
┌────────────────────┐
│  ARQ Worker        │
│  (worker.py)       │
│                    │
│  5. Dequeue job    │
│  6. Read payload   │
│  7. Run agent      │
│  8. Publish events │
│  9. Webhook call   │
└────────────────────┘
```

### In the Chat Router

```python
# routers/chat.py (simplified)
from app.services.agent_context import build_agent_context
from app.services.agent_task import AgentTaskPayload

@router.post("/stream")
async def stream_chat(request: ChatRequest, ...):
    task_id = str(uuid.uuid4())

    # Pre-build all context
    context = await build_agent_context(project, chat, request.container_name, db)

    # Create payload envelope
    payload = AgentTaskPayload(
        task_id=task_id,
        user_id=str(user.id),
        project_id=str(project.id),
        chat_id=str(chat.id),
        message=request.message,
        agent_id=str(agent.id),
        model_name=request.model or agent.default_model,
        container_name=context["container"],
        view=request.view,
        edit_mode=request.edit_mode,
        chat_history=context["chat_history"],
        project_context=context,
        webhook_url=request.webhook_url
    )

    # Dispatch to worker fleet
    await arq_pool.enqueue_job("execute_agent_task", payload.to_dict())

    return {"task_id": task_id}
```

### In the Worker

```python
# worker.py (simplified)
async def execute_agent_task(ctx, payload_dict: dict):
    task_id = payload_dict["task_id"]
    message = payload_dict["message"]
    model = payload_dict["model_name"]
    history = payload_dict["chat_history"]
    context = payload_dict["project_context"]

    # Run agent with pre-built context
    agent = create_agent(model=model, context=context)
    result = await agent.run(message, history)

    # Optional webhook callback
    if payload_dict.get("webhook_url"):
        await send_webhook_callback(payload_dict["webhook_url"], result)
```

## Design Decisions

### Why Pre-Build Context?

The context is built in the API pod (which has a database connection and can exec into containers) rather than in the worker pod. This avoids:
- Workers needing direct database access for context loading
- Redundant container exec commands during agent execution
- Race conditions where project state changes between dispatch and execution

### Why Not Deserialize Back?

The worker accesses the payload as a plain dict rather than reconstructing an `AgentTaskPayload` instance. This keeps the worker's dependency surface minimal and avoids import issues if the payload class changes.

### Why Include Chat History Inline?

Chat history is included directly in the payload rather than just a chat_id reference. This ensures the worker has a consistent snapshot of the history at dispatch time, even if new messages arrive while the task is queued.
