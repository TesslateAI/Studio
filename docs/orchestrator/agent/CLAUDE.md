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
- `orchestrator/app/agent/tools/graph_ops/` - Container management tools for graph view

### TesslateAgent Supporting Files
- `orchestrator/app/agent/subagent_manager.py` - Subagent lifecycle and execution management
- `orchestrator/app/agent/apply_patch.py` - Apply patch tool for surgical file edits
- `orchestrator/app/agent/compaction.py` - Context compaction for long conversations
- `orchestrator/app/agent/plan_manager.py` - Planning mode state management
- `orchestrator/app/agent/trajectory.py` - Trajectory recording for agent steps
- `orchestrator/app/agent/trajectory_writer.py` - Persistent trajectory storage
- `orchestrator/app/agent/features.py` - Feature flags for agent capabilities
- `orchestrator/app/agent/tool_converter.py` - Convert tools to native function calling format

### Supporting Files
- `orchestrator/app/agent/parser.py` - Parse LLM responses for tool calls
- `orchestrator/app/agent/models.py` - Model adapters for LLM providers
- `orchestrator/app/agent/resource_limits.py` - Resource tracking and limits

## Related Contexts

This context relates to:
- **Tools Context** (`orchestrator/app/agent/tools/CLAUDE.md`) - Tool development
- **Chat Router** (`orchestrator/app/routers/chat.py`) - Agent execution endpoint
- **Services Context** - Orchestration services that tools interact with

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
