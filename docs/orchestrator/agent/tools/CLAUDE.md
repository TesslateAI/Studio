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

- `orchestrator/app/agent/tools/project_ops/` - Project metadata
  - `metadata.py` - get_project_info

- `orchestrator/app/agent/tools/planning_ops/` - Task planning
  - `todos.py` - todo_read, todo_write

- `orchestrator/app/agent/tools/web_ops/` - Web operations
  - `fetch.py` - web_fetch

### View-Scoped Tools
- `orchestrator/app/agent/tools/view_scoped_factory.py` - Create view-specific tool registries
- `orchestrator/app/agent/tools/view_scoped_registry.py` - ViewScopedToolRegistry class
- `orchestrator/app/agent/tools/providers/` - Tool providers for views

## Tool Categories Summary

| Category | Tools | Files |
|----------|-------|-------|
| **File Operations** | 4 | `file_ops/read_write.py`, `file_ops/edit.py` |
| **Shell Operations** | 4 | `shell_ops/bash.py`, `shell_ops/session.py`, `shell_ops/execute.py` |
| **Project Operations** | 1 | `project_ops/metadata.py` |
| **Planning Operations** | 2 | `planning_ops/todos.py` |
| **Web Operations** | 1 | `web_ops/fetch.py` |
| **Graph Operations** | 9 | `graph_ops/containers.py`, `graph_ops/grid.py`, `graph_ops/shell.py` |

## Related Contexts

This context relates to:
- **Agent Context** (`orchestrator/app/agent/CLAUDE.md`) - Agent system that uses tools
- **Orchestration Services** - Services that tools interact with (file I/O, shell execution)
- **Chat Router** (`orchestrator/app/routers/chat.py`) - Tool execution endpoint

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
