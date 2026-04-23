# AI Agent System

The AI agent system is the core of OpenSail's AI-powered development capabilities. It enables language models to write code, execute commands, and manage projects through a sophisticated tool-calling architecture.

## Architecture Overview

The agent system follows a modular, extensible design:

```
┌─────────────────────────────────────────────────────────┐
│                    Agent System                         │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌──────────────┐        ┌──────────────┐             │
│  │ AbstractAgent│◄───────│ Agent Factory│             │
│  │   (base.py)  │        │  (factory.py)│             │
│  └──────┬───────┘        └──────────────┘             │
│         │                                              │
│         │ Implementations:                             │
│    ┌────┴─────┬──────────────┬─────────────┐          │
│    │          │              │             │          │
│ ┌──▼───┐  ┌──▼────┐   ┌────▼────┐  ┌──────▼──────┐   │
│ │Stream│  │Iterative│  │ ReAct   │  │  Tesslate   │   │
│ │Agent │  │ Agent   │  │ Agent   │  │   Agent     │   │
│ └──┬───┘  └────┬────┘   └────┬────┘  └──────┬──────┘   │
│    │           │             │                         │
│    └───────────┴─────────────┘                         │
│                │                                        │
│         ┌──────▼──────┐                                │
│         │ToolRegistry │                                │
│         │ (registry.py)│                                │
│         └──────┬──────┘                                │
│                │                                        │
│    ┌───────────┴────────────┐                          │
│    │ Tool Categories:       │                          │
│    │ - File Ops (4 tools)   │                          │
│    │ - Shell Ops (4 tools)  │                          │
│    │ - Project Ops (1 tool) │                          │
│    │ - Planning Ops (2 tools)│                         │
│    │ - Web Ops (3 tools)    │                          │
│    │ - Skill Ops (1 tool)   │                          │
│    │ - Graph Ops (9 tools)  │                          │
│    └────────────────────────┘                          │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

## How Agents Work

### 1. Agent Initialization

Agents are created from marketplace database models using the factory pattern:

```python
from orchestrator.app.agent.factory import create_agent_from_db_model

# Fetch agent from marketplace
agent_model = await db.get(MarketplaceAgent, agent_id)

# Create agent instance with tools
agent = await create_agent_from_db_model(agent_model)

# Run agent with user request
async for event in agent.run(user_request, context):
    # Stream events to frontend
    yield event
```

### 2. LLM Integration

Agents use language models through a unified interface:

- **System Prompt**: Each agent has a custom system prompt that defines its behavior
- **Tool Schemas**: Tools are described in natural language with JSON parameter schemas
- **Marker Substitution**: System prompts can use `{mode}`, `{project_name}`, etc. for dynamic content
- **Model Adapters**: Support for OpenAI, Anthropic, and other LLM providers via LiteLLM

### 3. Tool Execution

The tool system enables agents to interact with the development environment:

```python
# Agent requests tool execution via JSON format
{
  "tool_name": "write_file",
  "parameters": {
    "file_path": "src/App.jsx",
    "content": "import React from 'react'..."
  }
}

# ToolRegistry executes tool and returns result
result = await registry.execute(
    tool_name="write_file",
    parameters={"file_path": "...", "content": "..."},
    context={"user_id": user.id, "project_id": project.id}
)
```

### 4. Edit Modes

The system supports three edit modes for user control:

- **Allow Mode** (`edit_mode='allow'`): Full access, execute all tools directly
- **Ask Mode** (`edit_mode='ask'`): Prompt user approval for dangerous operations
- **Plan Mode** (`edit_mode='plan'`): Read-only, create markdown plans instead of executing changes

## Agent Types Comparison

| Feature | StreamAgent | IterativeAgent | ReActAgent | TesslateAgent |
|---------|-------------|----------------|------------|---------------|
| **Use Case** | Simple streaming responses | Complex multi-step tasks | Explicit reasoning tasks | Production agent with full capabilities |
| **Tool Support** | No (code blocks only) | Yes (full tool registry) | Yes (full tool registry) | Yes (native function calling) |
| **Execution Loop** | Single LLM call | Think → Act → Observe loop | Thought → Action → Observation | Native tool loop with trajectory |
| **Error Recovery** | None | Automatic retry on errors | Automatic retry on errors | Automatic retry + context compaction |
| **Planning Mode** | No | No | No | Yes (plan_manager.py) |
| **Subagents** | No | No | No | Yes (subagent_manager.py) |
| **Trajectory** | No | No | No | Yes (trajectory.py) |
| **Best For** | Quick code generation | File operations, shell commands | Architecture planning, debugging | Full-featured development tasks |

## Tool System Overview

Tools are organized into categories:

### File Operations (4 tools)
- `read_file`: Read file contents
- `write_file`: Write complete file (creates if doesn't exist)
- `patch_file`: Surgical edit using search/replace
- `multi_edit`: Apply multiple patches atomically

### Shell Operations (4 tools)
- `bash_exec`: One-off command execution (convenience wrapper)
- `shell_open`: Open persistent shell session
- `shell_exec`: Execute command in existing session
- `shell_close`: Close shell session

### Project Operations (1 tool)
- `get_project_info`: Get project metadata and structure

### Planning Operations (2 tools)
- `todo_read`: Read current task list
- `todo_write`: Update task list with progress

### Web Operations (3 tools)
- `web_fetch`: Fetch external web content
- `web_search`: Search the web for current information (Tavily/Brave/DuckDuckGo with automatic fallback)
- `send_message`: Send messages via chat, Discord webhook, external webhook, or reply channel (Telegram, Slack, etc.)

### Skill Operations (1 tool)
- `load_skill`: Load full skill instructions on-demand (progressive disclosure -- only name + description in system prompt)

### Graph Operations (9 tools)
Used only in graph/architecture view for container management:
- Container lifecycle: `graph_start_container`, `graph_stop_container`, etc.
- Grid management: `graph_add_container`, `graph_add_connection`, etc.

## Creating a New Agent

### 1. Choose Agent Type

Select the base agent type that fits your use case:

- **StreamAgent**: For simple streaming responses without tools
- **IterativeAgent**: For general-purpose task execution with tools
- **ReActAgent**: For tasks requiring explicit reasoning steps

### 2. Write System Prompt

Create a system prompt that teaches the agent its purpose:

```python
system_prompt = """
You are a frontend development expert specializing in React.

Your goal: Build modern, accessible React components using best practices.

Guidelines:
- Use functional components with hooks
- Implement proper TypeScript types
- Follow accessibility standards (ARIA labels, semantic HTML)
- Use Tailwind CSS for styling

You can use {mode_instructions} to understand the current edit mode.
Project: {project_name}
"""
```

### 3. Select Tools

Choose which tools the agent should have access to:

```python
# Option 1: Use all tools
agent_model.tools = None  # Defaults to global registry

# Option 2: Restrict to specific tools
agent_model.tools = [
    "read_file",
    "write_file",
    "patch_file",
    "bash_exec"
]

# Option 3: Customize tool descriptions
agent_model.tool_configs = {
    "read_file": {
        "description": "Read React component files",
        "examples": ['{"tool_name": "read_file", "parameters": {"file_path": "src/components/Button.tsx"}}']
    }
}
```

### 4. Register in Marketplace

Create a marketplace agent entry:

```sql
INSERT INTO marketplace_agents (
    id, name, slug, agent_type, system_prompt,
    tools, tool_configs, price, is_public
) VALUES (
    gen_random_uuid(),
    'React Expert',
    'react-expert',
    'IterativeAgent',
    '<system_prompt>',
    ARRAY['read_file', 'write_file', 'patch_file', 'bash_exec'],
    '{"read_file": {"description": "..."}}'::jsonb,
    0.00,
    true
);
```

### 5. Test Agent

Use the factory to instantiate and test:

```python
from orchestrator.app.agent.factory import create_agent_from_db_model

agent_model = await db.get(MarketplaceAgent, agent_id)
agent = await create_agent_from_db_model(agent_model)

context = {
    "user_id": user.id,
    "project_id": project.id,
    "edit_mode": "allow",
    "db": db,
    "project_context": {
        "project_name": "MyApp",
        "project_description": "React application"
    }
}

async for event in agent.run("Create a Button component", context):
    print(event)
```

## TesslateAgent System

TesslateAgent is the production agent that uses native LLM function calling instead of JSON-in-text parsing. It adds several capabilities on top of the base agent system:

### Native Function Calling
Uses `tool_converter.py` to transform tool definitions into provider-native format (e.g., Anthropic tool_use, OpenAI function_calling). The LLM returns structured tool calls directly rather than embedding JSON in text.

### Subagent System
Managed by `subagent_manager.py`, allows the main agent to spawn specialized sub-agents for focused tasks. Subagents are configured per-agent in the marketplace (CRUD via `/api/marketplace/agents/{id}/subagents`).

### Trajectory Recording
`trajectory.py` and `trajectory_writer.py` record every agent step (tool calls, results, reasoning) for debugging, analytics, and replay. Trajectories are stored persistently.

### Planning Mode
`plan_manager.py` manages plan state when the agent operates in plan mode — creating structured plans before executing changes.

### Context Compaction
`compaction.py` handles automatic compaction of long conversation contexts to stay within token limits while preserving essential information.

### Apply Patch
`apply_patch.py` provides a unified diff-based file editing tool as an alternative to search/replace patches.

## Key Files

| File | Purpose |
|------|---------|
| `orchestrator/app/agent/base.py` | Abstract base class for all agents |
| `orchestrator/app/agent/factory.py` | Agent instantiation from database models |
| `orchestrator/app/agent/stream_agent.py` | Simple streaming agent implementation |
| `orchestrator/app/agent/iterative_agent.py` | Tool-calling agent with think-act-reflect loop |
| `orchestrator/app/agent/react_agent.py` | ReAct agent with explicit reasoning |
| `orchestrator/app/agent/tesslate_agent.py` | TesslateAgent with native function calling |
| `orchestrator/app/agent/subagent_manager.py` | Subagent lifecycle management |
| `orchestrator/app/agent/trajectory.py` | Trajectory recording |
| `orchestrator/app/agent/trajectory_writer.py` | Persistent trajectory storage |
| `orchestrator/app/agent/plan_manager.py` | Planning mode state |
| `orchestrator/app/agent/compaction.py` | Context compaction |
| `orchestrator/app/agent/apply_patch.py` | Unified diff-based file editing |
| `orchestrator/app/agent/tool_converter.py` | Tool-to-native-format conversion |
| `orchestrator/app/agent/features.py` | Agent feature flags |
| `orchestrator/app/agent/prompts.py` | System prompt templates and marker substitution |
| `orchestrator/app/agent/tools/registry.py` | Tool registration and execution |
| `orchestrator/app/agent/tools/approval_manager.py` | User approval system for ask mode |
| `orchestrator/app/agent/tools/web_ops/search.py` | Web search tool (Tavily/Brave/DuckDuckGo) |
| `orchestrator/app/agent/tools/web_ops/providers.py` | Search provider abstraction |
| `orchestrator/app/agent/tools/web_ops/send_message.py` | Send message tool (chat, Discord, webhook, reply) |
| `orchestrator/app/agent/tools/skill_ops/load_skill.py` | Skill loading via progressive disclosure |
| `orchestrator/app/services/skill_discovery.py` | Skill discovery from DB and project files |
| `orchestrator/app/services/channels/` | Messaging channel integrations |
| `orchestrator/app/services/mcp/` | MCP server management and tool bridging |

## Related Contexts

- **Tools System**: See `orchestrator/app/agent/tools/README.md`
- **Chat Router**: See `orchestrator/app/routers/chat.py` for agent execution
- **Orchestration Services**: See `orchestrator/app/services/orchestration/` for container operations
- **Skill Discovery**: See `orchestrator/app/services/skill_discovery.py` for skill catalog building
- **Channel Service**: See `orchestrator/app/services/channels/` for messaging channel integrations
- **MCP Service**: See `orchestrator/app/services/mcp/` for MCP server management

## When to Load This Context

Load this context when:
- Adding new agent types
- Modifying agent execution loop
- Implementing new tool calling patterns
- Debugging agent behavior
- Creating custom marketplace agents
