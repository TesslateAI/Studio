# Agent Context Service - Execution Context Builder

**File**: `orchestrator/app/services/agent_context.py` (494 lines)

Constructs the complete execution context required for an agent task, including project metadata, container architecture, git status, chat history, TESSLATE.md documentation, and `.tesslate/config.json` configuration. This context is pre-built before dispatching to the worker to minimize database queries during agent execution.

## When to Load This Context

Load this context when:
- Modifying what information the agent receives before execution
- Debugging agent tasks that have stale or missing context
- Adding new context sources (e.g., new project metadata)
- Understanding how chat history is resolved from the AgentStep table
- Working on the TESSLATE.md project documentation flow

## Key Files

| File | Purpose |
|------|---------|
| `orchestrator/app/services/agent_context.py` | Context builder implementation |
| `orchestrator/app/services/agent_task.py` | AgentTaskPayload that carries the built context |
| `orchestrator/app/worker.py` | Consumes the context during agent execution |
| `orchestrator/app/models.py` | Message, AgentStep, Container, Project models |
| `orchestrator/app/agent/stream_agent.py` | Agent that receives the context |

## Related Contexts

- **[worker.md](./worker.md)**: Consumes the pre-built context during agent task execution
- **[agent-task.md](./agent-task.md)**: Serializable payload that carries the context
- **[../agent/CLAUDE.md](../agent/CLAUDE.md)**: AI agent system that uses the context
- **[../models/CLAUDE.md](../models/CLAUDE.md)**: Database models for Message, AgentStep, Container
- **[skill-discovery.md](./skill-discovery.md)**: Skill discovery integrated into context building
- **[mcp.md](./mcp.md)**: MCP tools bridged and registered during context assembly

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                  Agent Context Builder                            │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │  Container    │  │  Git         │  │  Chat History        │  │
│  │  Resolution   │  │  Context     │  │  Resolution          │  │
│  │              │  │              │  │                      │  │
│  │  _resolve_   │  │  _build_git_ │  │  _get_chat_history() │  │
│  │  container_  │  │  context()   │  │  → Message table     │  │
│  │  name()      │  │  → repo URL  │  │  → AgentStep table   │  │
│  │  → DNS-1123  │  │  → branch    │  │  → Inline fallback   │  │
│  │  compliant   │  │  → changes   │  │                      │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
│                                                                  │
│  ┌──────────────┐  ┌──────────────────────────────────────────┐ │
│  │  Architecture │  │  TESSLATE.md + .tesslate/config.json     │ │
│  │  Context      │  │  Documentation & Configuration           │ │
│  │              │  │                                          │ │
│  │  _build_     │  │  _build_tesslate_context()               │ │
│  │  architecture │  │  → Read TESSLATE.md from container      │ │
│  │  _context()  │  │  → Read .tesslate/config.json           │ │
│  │  → containers│  │  → Copy if missing                      │ │
│  │  → connections│  │  → Project-specific docs                │ │
│  │  → env vars  │  │                                          │ │
│  └──────────────┘  └──────────────────────────────────────────┘ │
│                                                                  │
│  ┌──────────────┐  ┌──────────────────────────────────────────┐ │
│  │  Skills       │  │  MCP Tools                               │ │
│  │  Discovery    │  │  Bridging                                │ │
│  │              │  │                                          │ │
│  │  discover_   │  │  McpManager.get_agent_tools()            │ │
│  │  skills()    │  │  → Discover server capabilities          │ │
│  │  → DB skills │  │  → Cache schemas in Redis                │ │
│  │  → File skills│  │  → Bridge into ToolRegistry             │ │
│  │  → Catalog   │  │  → Register on agent instance            │ │
│  └──────────────┘  └──────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

## Key Functions

### `_resolve_container_name(container) -> str`

Maps a Container database model to a DNS-1123 compliant service name suitable for Kubernetes. The resolved name is used in agent tool execution (shell commands target this container).

```python
# Container model with name "My Frontend App"
resolved = _resolve_container_name(container)
# Returns: "my-frontend-app"

# Rules:
# - Lowercase
# - Replace spaces and underscores with hyphens
# - Strip non-alphanumeric characters (except hyphens)
# - Must start and end with alphanumeric
# - Max 63 characters (DNS-1123 label limit)
```

### `_build_git_context(project, container_name, db) -> dict`

Fetches the current git state of the project from inside the running container.

```python
git_context = await _build_git_context(project, "frontend", db)
# Returns:
# {
#     "repo_url": "https://github.com/user/repo.git",
#     "branch": "main",
#     "has_changes": True,
#     "changed_files": ["src/App.tsx", "src/index.css"],
#     "sync_status": "ahead_by_2"
# }
```

This executes git commands inside the container via the orchestrator's `execute_command()`. If git is not initialized or the container is not running, it returns a minimal context with empty values rather than failing.

### `_build_architecture_context(project, containers, connections, db) -> dict`

Lists all containers in the project, their connections, and auto-injected environment variables.

```python
arch_context = await _build_architecture_context(project, containers, connections, db)
# Returns:
# {
#     "containers": [
#         {
#             "name": "frontend",
#             "type": "nextjs",
#             "port": 3000,
#             "env_vars": {"NEXT_PUBLIC_API_URL": "http://backend:8000"}
#         },
#         {
#             "name": "backend",
#             "type": "fastapi",
#             "port": 8000,
#             "env_vars": {"DATABASE_URL": "postgresql://..."}
#         }
#     ],
#     "connections": [
#         {"from": "frontend", "to": "backend", "env_var": "NEXT_PUBLIC_API_URL"}
#     ]
# }
```

### `_get_chat_history(chat_id, db, limit) -> list[dict]`

Loads recent messages for the chat, with special handling for agent responses that store their steps in the AgentStep table.

```python
history = await _get_chat_history(chat_id, db, limit=20)
# Returns list of message dicts with role, content, and metadata
```

#### Chat History Resolution Strategy

Agent response messages use a two-tier storage system:

1. **Check metadata flag**: If a Message has `metadata.steps_table == True`, its detailed content (tool calls, tool results, thoughts) is stored in the `AgentStep` table, not inline in the Message content.

2. **Load from AgentStep**: Query `AgentStep` rows for that message, ordered by `iteration`. Each row contains `step_data` JSON with the full iteration details.

3. **Fallback to inline**: If `steps_table` is not set, the message content and metadata contain the steps inline (legacy format).

```python
# Resolution pseudocode
for message in messages:
    if message.metadata.get("steps_table"):
        # New format: load from AgentStep table
        steps = await db.execute(
            select(AgentStep)
            .where(AgentStep.message_id == message.id)
            .order_by(AgentStep.iteration)
        )
        message_content = reconstruct_from_steps(steps)
    else:
        # Legacy format: steps are inline in metadata
        message_content = message.content
```

### `_build_tesslate_context(project, container_name, db) -> str`

Reads the TESSLATE.md file from the project container. If the file does not exist, it copies a default template into the container. This file serves as project-specific documentation that the agent uses for understanding the project structure and conventions.

```python
tesslate_md = await _build_tesslate_context(project, "frontend", db)
# Returns the contents of TESSLATE.md as a string
```

## Full Context Assembly

All sub-contexts are assembled into a single dict that becomes part of the `AgentTaskPayload`:

```python
context = {
    "project": {
        "id": str(project.id),
        "name": project.name,
        "slug": project.slug,
    },
    "container": resolved_container_name,
    "architecture": arch_context,
    "git": git_context,
    "chat_history": history,
    "tesslate_md": tesslate_md,
}
```

This context is serialized to JSON and sent to the ARQ worker queue, so the worker can execute the agent without needing database access for context loading.

## Usage

The context builder is called in the chat router before dispatching to the worker:

```python
from app.services.agent_context import build_agent_context

# In routers/chat.py
context = await build_agent_context(
    project=project,
    chat=chat,
    container_name=request.container_name,
    db=db
)

payload = AgentTaskPayload(
    task_id=task_id,
    user_id=user.id,
    project_id=project.id,
    chat_id=chat.id,
    message=request.message,
    context=context,
    # ... other fields
)

await arq_pool.enqueue_job("execute_agent_task", payload.to_dict())
```

## Performance Considerations

1. **Pre-building**: Context is built once before dispatch, not during agent execution. This avoids repeated database queries during the agent's iterative tool-call loop.

2. **Parallel fetching**: Git context, architecture context, and chat history can be fetched concurrently using `asyncio.gather()`.

3. **History limits**: `_get_chat_history()` accepts a `limit` parameter to cap the number of messages loaded. Large chat histories are truncated to the most recent messages.

4. **Non-blocking container commands**: Git commands executed inside containers use the orchestrator's async `execute_command()`, which does not block the event loop.

## Troubleshooting

### Agent Missing Project Context

1. Check that the project has running containers (context builder needs to exec into containers)
2. Verify the container name resolves correctly via `_resolve_container_name()`
3. Check worker logs for the received context payload

### Chat History Empty or Incomplete

1. Verify messages exist for the chat_id in the database
2. Check if `steps_table: True` messages have corresponding AgentStep rows
3. Confirm the history limit is not too restrictive

### TESSLATE.md Not Found

1. Check if the container has the file: exec into container and `cat TESSLATE.md`
2. Verify the template copy succeeded (check orchestrator logs)
3. Confirm the container is running when context is built

### Git Context Returns Empty Values

1. Verify git is initialized in the container: `git status`
2. Check that the remote is configured: `git remote -v`
3. Container must be running for git commands to execute
