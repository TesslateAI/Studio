# Agent Context for Claude

**Purpose**: AI agent development and modification

This context provides information about Tesslate Studio's AI agent system, including agent types, tool calling, and execution patterns.

## Key Files

### Core Agent System
- `orchestrator/app/agent/base.py` - AbstractAgent interface that all agents implement
- `orchestrator/app/agent/factory.py` - Agent factory for creating instances from DB models
- `orchestrator/app/agent/prompts.py` - System prompt templates and marker substitution

### Agent Implementations
- `orchestrator/app/agent/stream_agent.py` - StreamAgent for simple streaming responses
- `orchestrator/app/agent/iterative_agent.py` - IterativeAgent with think-act-reflect loop
- `orchestrator/app/agent/react_agent.py` - ReActAgent with explicit reasoning steps
- `orchestrator/app/agent/tesslate_agent.py` - TesslateAgent with native function calling, trajectory, planning, and subagents

### Tool System
- `orchestrator/app/agent/tools/registry.py` - Tool registration and execution (400 lines)
- `orchestrator/app/agent/tools/approval_manager.py` - User approval system for ask mode
- `orchestrator/app/agent/tools/file_ops/` - File read/write/edit tools
- `orchestrator/app/agent/tools/shell_ops/` - Shell and command execution tools
- `orchestrator/app/agent/tools/web_ops/` - Web fetch, search, and send_message tools
  - `search.py` - web_search tool (searches via Tavily/Brave/DuckDuckGo)
  - `providers.py` - Search provider abstraction with automatic fallback
  - `send_message.py` - send_message tool (chat, Discord, webhook, or reply channel)
- `orchestrator/app/agent/tools/skill_ops/` - Skill loading via progressive disclosure
  - `load_skill.py` - Loads full skill instructions on-demand from DB or project files
- `orchestrator/app/agent/tools/project_ops/project_control.py` - project_control tool for container lifecycle management
- `orchestrator/app/agent/tools/graph_ops/` - Container management tools for graph view

### TesslateAgent Supporting Files
- `orchestrator/app/agent/subagent_manager.py` - Subagent lifecycle and execution management
- `orchestrator/app/agent/apply_patch.py` - Apply patch tool for surgical file edits
- `orchestrator/app/agent/compaction.py` - Context compaction for long conversations
- `orchestrator/app/agent/plan_manager.py` - Planning mode state management. Plans are persisted to Redis (24-hour TTL) for cross-pod visibility via `_persist_plan`/`_load_plan`. `get_plan_sync()` checks `context["_active_plan"]` first for pre-warmed plans injected by the worker, falling back to Redis and then in-memory cache.
- `orchestrator/app/agent/trajectory.py` - Trajectory recording for agent steps
- `orchestrator/app/agent/trajectory_writer.py` - Persistent trajectory storage
- `orchestrator/app/agent/features.py` - Feature flags for agent capabilities
- `orchestrator/app/agent/tool_converter.py` - Convert tools to native function calling format

### Supporting Files
- `orchestrator/app/agent/parser.py` - Parse LLM responses for tool calls
- `orchestrator/app/agent/models.py` - Model adapters and BYOK provider routing (see Provider Routing below)
- `orchestrator/app/agent/resource_limits.py` - Resource tracking: per-run cost limits ($5.00), iteration caps (env: `AGENT_MAX_ITERATIONS_PER_RUN`)

### Resource Limits & Iteration Controls
- `orchestrator/app/agent/resource_limits.py` - Resource tracking and limits (iteration caps, cost limits)
  - **Per-run cost limit**: $5.00 (primary safety net)
  - **Per-run iteration limit**: Controlled by `AGENT_MAX_ITERATIONS_PER_RUN` env var (default: unlimited)
  - **Note**: The cost limit is the primary guard against runaway agents. Iteration limits are disabled by default to allow agents to complete complex multi-step tasks.
- Subagent turn limits are configured in `subagent_manager.py` (default: 100 turns per subagent invocation)

## Provider Routing (`agent/models.py`)

`BUILTIN_PROVIDERS` is the single source of truth for BYOK (Bring Your Own Key) providers. Users add their own API keys and models — there are no hardcoded default model lists per provider.

### Current Built-in Providers

| Slug | Provider | Base URL |
|------|----------|----------|
| `openrouter` | OpenRouter | `https://openrouter.ai/api/v1` |
| `nano-gpt` | NanoGPT | `https://nano-gpt.com/api/v1` |
| `openai` | OpenAI | `https://api.openai.com/v1` |
| `anthropic` | Anthropic | `https://api.anthropic.com/v1` |
| `groq` | Groq | `https://api.groq.com/openai/v1` |
| `together` | Together AI | `https://api.together.xyz/v1` |
| `deepseek` | DeepSeek | `https://api.deepseek.com/v1` |
| `fireworks` | Fireworks AI | `https://api.fireworks.ai/inference/v1` |
| `z-ai` | Z.AI (ZhipuAI) | `https://api.z.ai/api/paas/v4` |

### Model Routing Flow

Model names use a prefix-based routing system:

1. **`builtin/gpt-4o`** → LiteLLM proxy (system models)
2. **`custom/my-ollama/neural-7b`** → User's custom provider
3. **`openrouter/z-ai/glm-5`** → OpenRouter API (strips `openrouter/`, sends `z-ai/glm-5`)
4. **`z-ai/glm-5`** → Z.AI API directly (strips `z-ai/`, sends `glm-5`)
5. **Unknown prefix** (e.g. `z-ai/glm-5` when z-ai not in BUILTIN_PROVIDERS) → DB fallback: looks up `UserCustomModel` to find parent provider, re-routes through that provider

Key distinction: A model like `z-ai/glm-5` means different things depending on context:
- On **OpenRouter**: it's the model identifier OpenRouter uses → route as `openrouter/z-ai/glm-5`
- On **Z.AI directly**: `z-ai` is the provider prefix → strips to `glm-5` for their API

### Adding a New Provider

1. Add entry to `BUILTIN_PROVIDERS` in `agent/models.py` (no `default_models` — users add their own)
2. It automatically becomes available for BYOK in the marketplace API
3. `is_byok_model()` in credit service auto-detects it (zero-cost routing)

## Worker-Based Execution

The real-time agent system introduces a decoupled execution model where agents run on dedicated worker pods instead of inline in the API request:

### Execution Flow

```
API Pod                          Worker Pod
  │                                │
  ├─ Build AgentTaskPayload        │
  ├─ Enqueue to ARQ (Redis)  ──►  ├─ Pick up job
  ├─ Return task_id to client      ├─ Acquire project lock
  │                                ├─ Create placeholder Message
  │   ◄── Redis Stream events ──── ├─ Run agent.run() loop
  │                                │  ├─ INSERT AgentStep per iteration
  │                                │  ├─ Check cancellation signal
  │                                │  └─ Heartbeat lock extension
  │                                ├─ Finalize Message
  │                                └─ Release lock + webhook callback
```

### Progressive Step Persistence

Each agent iteration is persisted as an `AgentStep` row immediately — not batched at the end. This means:
- **Crash recovery**: Partial work survives pod crashes
- **Real-time visibility**: Steps stream to clients via Redis Streams
- **History reconstruction**: Chat context loads from AgentStep table (metadata flag `steps_table: True`)

### Key Files
- `orchestrator/app/worker.py` - ARQ worker implementation
- `orchestrator/app/services/agent_task.py` - Task payload serialization
- `orchestrator/app/services/agent_context.py` - Context building
- `orchestrator/app/services/pubsub.py` - Event streaming
- `orchestrator/app/services/distributed_lock.py` - Project-level locks

### Configuration
- `worker_max_jobs`: Concurrent tasks per pod (default: 10)
- `worker_job_timeout`: Task timeout in seconds (default: 600)
- `worker_max_tries`: Retry count for transient failures (default: 2)

## Related Contexts

This context relates to:
- **Tools Context** (`orchestrator/app/agent/tools/CLAUDE.md`) - Tool development
- **Chat Router** (`orchestrator/app/routers/chat.py`) - Agent execution endpoint
- **Services Context** - Orchestration services that tools interact with
- **Worker** (`orchestrator/app/worker.py`) - Distributed agent execution
- **Pub/Sub** (`orchestrator/app/services/pubsub.py`) - Real-time event streaming
- **External API** (`orchestrator/app/routers/external_agent.py`) - External agent invocation
- **Skill Discovery** (`orchestrator/app/services/skill_discovery.py`) - Discovers available skills for progressive disclosure
- **Channel Service** (`orchestrator/app/services/channels/`) - Messaging channel integrations (Telegram, Slack, Discord, WhatsApp)
- **MCP Service** (`orchestrator/app/services/mcp/`) - MCP server management and tool bridging
- **Config System** (`orchestrator/app/services/base_config_parser.py`, `config_resolver.py`) - `.tesslate/config.json` parsing and resolution

## Agent Execution Patterns

### Pattern 1: Simple Streaming (StreamAgent)
```python
# User request → LLM → Extract code blocks → Save files
async for event in agent.run(user_request, context):
    if event['type'] == 'stream':
        # Real-time text chunks
        yield event['content']
    elif event['type'] == 'file_ready':
        # File extracted and saved
        print(f"Saved: {event['file_path']}")
```

### Pattern 2: Tool Loop (IterativeAgent/ReActAgent)
```python
# Iterative loop:
# 1. LLM generates response with tool calls
# 2. Parse tool calls from JSON in response
# 3. Execute tools via ToolRegistry
# 4. Feed results back to LLM
# 5. Repeat until task complete

while not is_complete:
    response = await model.chat(messages)
    tool_calls = parser.parse(response)

    if tool_calls:
        results = await execute_tools(tool_calls)
        messages.append({"role": "assistant", "content": response})
        messages.append({"role": "user", "content": format_results(results)})
    else:
        break  # No more actions
```

### Pattern 3: View-Scoped Tools
```python
# Different tool sets based on frontend view
if view == "graph":
    # Graph view: container management tools only
    tools = ViewScopedToolRegistry(
        base_tools=["read_file", "bash_exec"],
        view_tools=["graph_start_container", "graph_add_connection"]
    )
else:
    # Code view: standard file/shell tools
    tools = create_scoped_tool_registry([
        "read_file", "write_file", "patch_file",
        "bash_exec", "shell_open"
    ])
```

### Pattern 4: Native Function Calling (TesslateAgent)
```python
# TesslateAgent uses native LLM function calling instead of JSON parsing.
# Tools are converted to provider-native format via tool_converter.py.
# Supports trajectory recording, context compaction, planning mode, and subagents.

agent = TesslateAgent(
    system_prompt=prompt,
    tools=tool_registry,
    model_adapter=model,
    features=AgentFeatures(
        trajectory_enabled=True,
        compaction_enabled=True,
        planning_enabled=True,
        subagents_enabled=True,
    ),
)

async for event in agent.run(user_request, context):
    # Events: stream, tool_call, tool_result, plan_update, subagent_*, complete
    process_event(event)
```

## When to Load This Context

Load this context when:

1. **Agent Development**
   - Adding new agent types (subclass AbstractAgent)
   - Modifying agent execution loops
   - Implementing new reasoning patterns

2. **Tool Calling**
   - Adding tools to agent system
   - Debugging tool execution
   - Implementing custom tool logic

3. **Prompt Engineering**
   - Customizing system prompts
   - Adding marker substitution
   - Creating mode-specific instructions

4. **Marketplace Agents**
   - Creating new marketplace agent products
   - Configuring tool access for agents
   - Testing agent behavior

5. **Debugging**
   - Agent not executing tools correctly
   - Tool results not being processed
   - Error recovery issues

## Quick Reference

### Creating Agent Instance
```python
from orchestrator.app.agent.factory import create_agent_from_db_model

agent = await create_agent_from_db_model(
    agent_model=marketplace_agent,
    model_adapter=model,  # For IterativeAgent/ReActAgent
    tools_override=custom_tools  # Optional custom tool registry
)
```

### Running Agent
```python
context = {
    "user_id": user.id,
    "project_id": project.id,
    "db": db,
    "edit_mode": "allow",  # or "ask" or "plan"
    "project_context": {
        "project_name": "MyApp",
        "project_description": "..."
    }
}

async for event in agent.run(user_request, context):
    # Handle events: stream, agent_step, complete, error, etc.
    process_event(event)
```

### Registering Tool
```python
from orchestrator.app.agent.tools.registry import Tool, ToolCategory

registry.register(Tool(
    name="my_tool",
    description="What this tool does",
    category=ToolCategory.FILE_OPS,
    parameters={
        "type": "object",
        "properties": {
            "param1": {"type": "string", "description": "..."}
        },
        "required": ["param1"]
    },
    executor=my_tool_executor,
    examples=['{"tool_name": "my_tool", "parameters": {...}}']
))
```
