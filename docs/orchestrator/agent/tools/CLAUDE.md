# Tools Context for Claude

**Purpose**: Agent tool development and modification

This context provides information about Tesslate Studio's agent tool system, including tool registration, execution, and creation patterns.

## Key Files

### Core Tool System
- `orchestrator/app/agent/tools/registry.py` - Tool registration and execution (400 lines)
- `orchestrator/app/agent/tools/approval_manager.py` - User approval system for ask mode
- `orchestrator/app/agent/tools/output_formatter.py` - Standardized output formatting
- `orchestrator/app/agent/tools/retry_config.py` - Automatic retry configuration

### Tool Categories
- `orchestrator/app/agent/tools/file_ops/` - File read/write/edit tools (3 files)
  - `read_write.py` - read_file, write_file
  - `edit.py` - patch_file, multi_edit
  - `__init__.py` - Registration

- `orchestrator/app/agent/tools/shell_ops/` - Shell command tools (4 files)
  - `bash.py` - bash_exec (convenience wrapper)
  - `session.py` - shell_open, shell_close (session management)
  - `execute.py` - shell_exec (execute in session)
  - `__init__.py` - Registration

- `orchestrator/app/agent/tools/graph_ops/` - Container management (3 files)
  - `containers.py` - Start/stop container tools
  - `grid.py` - Add/remove container/connection tools
  - `shell.py` - Open shell in container
  - `__init__.py` - Registration

- `orchestrator/app/agent/tools/project_ops/` - Project metadata and lifecycle
  - `metadata.py` - get_project_info
  - `project_control.py` - project_control (container lifecycle management)
  - `kanban.py` - kanban (board/task/column management with TSK-NNNN refs)

- `orchestrator/app/agent/tools/planning_ops/` - Task planning
  - `todos.py` - todo_read, todo_write
  - **Redis persistence**: Todos and plans are persisted to Redis for cross-pod visibility via `_persist_todos`/`_load_todos` (in `todos.py`) and `PlanManager._persist_plan`/`_load_plan`. In-memory storage remains the primary cache; Redis serves as a backing store with a 24-hour TTL.

- `orchestrator/app/agent/tools/web_ops/` - Web operations (3 tools)
  - `fetch.py` - web_fetch
  - `search.py` - web_search (searches the web via Tavily/Brave/DuckDuckGo)
  - `send_message.py` - send_message (sends messages via chat, Discord, webhook, or reply channel)
  - `providers.py` - Search provider abstraction (`SearchProvider` ABC with `TavilyProvider`, `BraveSearchProvider`, `DuckDuckGoProvider`)

- `orchestrator/app/agent/tools/skill_ops/` - Skill loading (1 tool)
  - `load_skill.py` - load_skill (loads full skill instructions on-demand from DB or project files)
  - **Progressive disclosure**: Only skill name + description are included in the system prompt; the agent calls `load_skill` to fetch the full instruction body when needed

- `orchestrator/app/agent/tools/schedule_ops/` - Schedule management (1 tool)
  - `manage_schedule.py` - manage_schedule (create, list, update, pause, resume, trigger, delete cron-scheduled agent tasks)
  - **Actions**: 7 actions via single tool — `create` (natural language or cron), `list`, `update`, `pause`, `resume`, `trigger` (immediate test run), `delete`
  - **Context**: Uses `user_id` and `project_id` from execution context; delegates to `schedule_parser.parse_schedule()` for NL→cron conversion

### View-Scoped Tools
- `orchestrator/app/agent/tools/view_scoped_factory.py` - Create view-specific tool registries
- `orchestrator/app/agent/tools/view_scoped_registry.py` - ViewScopedToolRegistry class
- `orchestrator/app/agent/tools/providers/` - Tool providers for views

## Tool Categories Summary

| Category | Tools | Files |
|----------|-------|-------|
| **File Operations** | 4 | `file_ops/read_write.py`, `file_ops/edit.py` |
| **Shell Operations** | 4 | `shell_ops/bash.py`, `shell_ops/session.py`, `shell_ops/execute.py` |
| **Project Operations** | 3 | `project_ops/metadata.py`, `project_ops/project_control.py`, `project_ops/kanban.py` |
| **Planning Operations** | 2 | `planning_ops/todos.py` |
| **Web Operations** | 3 | `web_ops/fetch.py`, `web_ops/search.py`, `web_ops/send_message.py` |
| **Skill Operations** | 1 | `skill_ops/load_skill.py` |
| **Schedule Operations** | 1 | `schedule_ops/manage_schedule.py` |
| **Graph Operations** | 9 | `graph_ops/containers.py`, `graph_ops/grid.py`, `graph_ops/shell.py` |

## Related Contexts

This context relates to:
- **Agent Context** (`orchestrator/app/agent/CLAUDE.md`) - Agent system that uses tools
- **Orchestration Services** - Services that tools interact with (file I/O, shell execution)
- **Chat Router** (`orchestrator/app/routers/chat.py`) - Tool execution endpoint
- **Skill Discovery** (`orchestrator/app/services/skill_discovery.py`) - Discovers available skills for the `load_skill` tool
- **Channel Service** (`orchestrator/app/services/channels/`) - Channel implementations used by `send_message` reply channel
- **Gateway Service** (`orchestrator/app/services/gateway/`) - Schedule parser and scheduler used by `manage_schedule` tool
- **MCP Service** (`orchestrator/app/services/mcp/`) - MCP tools dynamically registered on agent before task execution

## Quick Reference

### Registering a Tool

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

### Tool Executor Pattern

```python
from ..registry import Tool, ToolCategory
from ..output_formatter import success_output, error_output
from ..retry_config import tool_retry

@tool_retry
async def my_tool_executor(
    params: Dict[str, Any],
    context: Dict[str, Any]
) -> Dict[str, Any]:
    # 1. Validate parameters
    param = params.get("param")
    if not param:
        raise ValueError("param is required")

    # 2. Extract context
    user_id = context["user_id"]
    project_id = context["project_id"]

    # 3. Perform operation
    try:
        result = await do_work(param, user_id, project_id)
        return success_output(
            message="Success message",
            result_data=result
        )
    except Exception as e:
        return error_output(
            message=f"Failed: {str(e)}",
            suggestion="How to fix"
        )
```

### Edit Mode Handling

Edit mode control is automatic in ToolRegistry.execute():

```python
# Dangerous tools (write_file, bash_exec, etc.)
# - Allow mode: Execute immediately
# - Ask mode: Request approval first
# - Plan mode: Block with error

# Safe tools (read_file, get_project_info)
# - All modes: Execute immediately
```

### View-Scoped Tools

```python
from orchestrator.app.agent.tools.view_scoped_factory import create_view_scoped_tools

# Get tools for specific view
if view == "graph":
    tools = create_view_scoped_tools(
        view="graph",
        project_id=project.id,
        user_id=user.id
    )
    # Contains: graph_start_container, graph_add_connection, etc.
else:
    tools = create_scoped_tool_registry([
        "read_file", "write_file", "bash_exec"
    ])
```

## When to Load This Context

Load this context when:

1. **Tool Development**
   - Adding new tools to agent system
   - Modifying existing tool behavior
   - Creating custom tool categories

2. **Tool Debugging**
   - Tool execution failures
   - Parameter validation issues
   - Output formatting problems

3. **Approval System**
   - Implementing ask mode behavior
   - Debugging approval flow
   - Adding dangerous tool checks

4. **View-Scoped Tools**
   - Creating view-specific tools
   - Restricting tool access by view
   - Graph view tool development

5. **Integration**
   - Connecting tools to orchestration services
   - File I/O operations
   - Shell command execution

6. **Skill System**
   - Adding or modifying skills (DB or project file-based)
   - Debugging skill discovery or load_skill tool
   - Understanding progressive disclosure pattern

7. **Web Search**
   - Configuring search providers (Tavily, Brave, DuckDuckGo)
   - Modifying search result formatting
   - Adding new search providers

8. **Messaging Channels**
   - Adding new send_message channels
   - Debugging channel reply delivery
   - Understanding the reply channel flow (Telegram, Slack, Discord, WhatsApp)

9. **Agent Schedules**
   - Creating or managing cron-scheduled agent tasks via the manage_schedule tool
   - Debugging schedule parsing (natural language → cron) or schedule lifecycle
