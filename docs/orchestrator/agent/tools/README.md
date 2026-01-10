# Agent Tools System

The tools system enables AI agents to interact with the development environment through a unified, extensible interface. Tools handle file operations, shell commands, project management, and more.

## What Are Tools?

Tools are functions that agents can call to perform actions:

```python
# Agent requests tool execution via JSON
{
  "tool_name": "write_file",
  "parameters": {
    "file_path": "src/App.jsx",
    "content": "import React from 'react'..."
  }
}

# Tool executes and returns result
{
  "success": true,
  "tool": "write_file",
  "result": {
    "message": "Wrote 15 lines (423 bytes) to 'src/App.jsx'",
    "file_path": "src/App.jsx",
    "preview": "import React from 'react'...",
    "details": {"size_bytes": 423, "line_count": 15}
  }
}
```

## Tool Categories

Tools are organized by function:

| Category | Tool Count | Purpose |
|----------|------------|---------|
| **File Operations** | 4 | Read, write, edit files |
| **Shell Commands** | 4 | Execute commands, manage sessions |
| **Project Management** | 1 | Query project metadata |
| **Planning** | 2 | Task planning and tracking |
| **Web Operations** | 1 | Fetch external content |
| **Graph Operations** | 9 | Container management (graph view only) |

## Architecture

```
┌─────────────────────────────────────────────┐
│           ToolRegistry                      │
│  (Central registration and execution)       │
├─────────────────────────────────────────────┤
│                                             │
│  Tool Definition:                           │
│  ┌───────────────────────────────────────┐ │
│  │ - name: "write_file"                  │ │
│  │ - description: "Write file content"   │ │
│  │ - parameters: JSON schema             │ │
│  │ - executor: async function            │ │
│  │ - category: ToolCategory.FILE_OPS     │ │
│  │ - examples: ["..."]                   │ │
│  └───────────────────────────────────────┘ │
│                                             │
│  Execution Flow:                            │
│  1. Validate tool exists                    │
│  2. Check edit mode (allow/ask/plan)        │
│  3. Request approval if needed              │
│  4. Execute tool function                   │
│  5. Return standardized result              │
│                                             │
└─────────────────────────────────────────────┘
```

## Tool Registration

### Registering a Tool

```python
from orchestrator.app.agent.tools.registry import Tool, ToolCategory

registry.register(Tool(
    name="my_tool",
    description="What this tool does (shown to LLM)",
    category=ToolCategory.FILE_OPS,
    parameters={
        "type": "object",
        "properties": {
            "param1": {
                "type": "string",
                "description": "What param1 does"
            },
            "param2": {
                "type": "integer",
                "description": "What param2 does"
            }
        },
        "required": ["param1"]
    },
    executor=my_tool_executor,
    examples=[
        '{"tool_name": "my_tool", "parameters": {"param1": "value"}}',
        '{"tool_name": "my_tool", "parameters": {"param1": "value", "param2": 42}}'
    ],
    system_prompt="Optional additional instructions for this tool"
))
```

### Tool Executor Function

```python
async def my_tool_executor(
    params: Dict[str, Any],
    context: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Execute the tool.

    Args:
        params: Tool parameters from agent
        context: Execution context (user_id, project_id, db, etc.)

    Returns:
        Dict with success status and result
    """
    param1 = params.get("param1")
    if not param1:
        raise ValueError("param1 is required")

    # Do the work
    result = perform_operation(param1)

    # Return standardized output
    return success_output(
        message="Operation completed",
        result_data=result,
        details={"info": "extra info"}
    )
```

## Tool Execution

### Through ToolRegistry

```python
from orchestrator.app.agent.tools.registry import get_tool_registry

registry = get_tool_registry()

result = await registry.execute(
    tool_name="write_file",
    parameters={"file_path": "test.txt", "content": "Hello"},
    context={
        "user_id": user.id,
        "project_id": project.id,
        "edit_mode": "allow",
        "db": db
    }
)

if result["success"]:
    print("File written:", result["result"]["file_path"])
else:
    print("Error:", result["error"])
```

### Result Format

All tools return a standardized structure:

```python
# Success
{
    "success": True,
    "tool": "tool_name",
    "result": {
        "message": "Human-readable success message",
        # Tool-specific fields
        "file_path": "...",
        "content": "...",
        "details": {...}
    }
}

# Failure
{
    "success": False,
    "tool": "tool_name",
    "error": "Error message",
    # Optional additional context
    "result": {
        "message": "Detailed error explanation",
        "suggestion": "How to fix the error",
        "problematic_input": "..."
    }
}

# Approval Required (ask mode)
{
    "approval_required": True,
    "tool": "tool_name",
    "parameters": {...},
    "session_id": "chat-id"
}
```

## Edit Mode Control

Tools respect three edit modes:

### Allow Mode (edit_mode='allow')
All tools execute immediately without approval.

### Ask Mode (edit_mode='ask')
Dangerous tools require user approval:

```python
DANGEROUS_TOOLS = {
    'write_file', 'patch_file', 'multi_edit',  # File modifications
    'bash_exec', 'shell_exec', 'shell_open',   # Shell operations
    'web_fetch'                                 # Web operations
}
```

Safe tools (read_file, get_project_info, todo_read) execute immediately.

### Plan Mode (edit_mode='plan')
All dangerous tools blocked with error:

```python
{
    "success": False,
    "tool": "write_file",
    "error": "Plan mode active - write_file is disabled. "
            "You can only read files and gather information. "
            "Explain what changes you would make instead."
}
```

## Available Tools Overview

### File Operations (4 tools)

| Tool | Purpose | Parameters |
|------|---------|------------|
| `read_file` | Read file contents | file_path |
| `write_file` | Write complete file | file_path, content |
| `patch_file` | Search/replace edit | file_path, search, replace |
| `multi_edit` | Multiple patches atomically | file_path, edits[] |

### Shell Operations (4 tools)

| Tool | Purpose | Parameters |
|------|---------|------------|
| `bash_exec` | One-off command | command, wait_seconds |
| `shell_open` | Open persistent session | command |
| `shell_exec` | Execute in session | session_id, command, wait_seconds |
| `shell_close` | Close session | session_id |

### Project Operations (1 tool)

| Tool | Purpose | Parameters |
|------|---------|------------|
| `get_project_info` | Get project metadata | None |

### Planning Operations (2 tools)

| Tool | Purpose | Parameters |
|------|---------|------------|
| `todo_read` | Read task list | None |
| `todo_write` | Update task list | todos[] |

### Web Operations (1 tool)

| Tool | Purpose | Parameters |
|------|---------|------------|
| `web_fetch` | Fetch external URL | url |

### Graph Operations (9 tools)

Only available in graph/architecture view:

| Tool | Purpose |
|------|---------|
| `graph_start_container` | Start specific container |
| `graph_stop_container` | Stop specific container |
| `graph_start_all` | Start all containers |
| `graph_stop_all` | Stop all containers |
| `graph_container_status` | Get container status |
| `graph_add_container` | Add container to grid |
| `graph_add_browser_preview` | Add browser preview node |
| `graph_add_connection` | Connect containers |
| `graph_remove_item` | Remove grid item |

## Adding New Tools

### 1. Create Tool Module

```python
# orchestrator/app/agent/tools/my_category/my_tool.py

import logging
from typing import Dict, Any
from ..registry import Tool, ToolCategory
from ..output_formatter import success_output, error_output
from ..retry_config import tool_retry

logger = logging.getLogger(__name__)

@tool_retry  # Auto-retry on transient failures
async def my_tool_executor(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Execute my custom tool."""
    # Validate parameters
    required_param = params.get("required_param")
    if not required_param:
        raise ValueError("required_param is required")

    # Get context
    user_id = context["user_id"]
    project_id = context["project_id"]

    try:
        # Do the work
        result = await perform_operation(required_param)

        return success_output(
            message=f"Successfully processed {required_param}",
            result_data=result
        )

    except Exception as e:
        logger.error(f"[MY-TOOL] Failed: {e}")
        return error_output(
            message=f"Operation failed: {str(e)}",
            suggestion="Check your input and try again"
        )

def register_my_tools(registry):
    """Register custom tools."""
    registry.register(Tool(
        name="my_tool",
        description="Performs custom operation",
        category=ToolCategory.PROJECT,
        parameters={
            "type": "object",
            "properties": {
                "required_param": {
                    "type": "string",
                    "description": "The input to process"
                }
            },
            "required": ["required_param"]
        },
        executor=my_tool_executor,
        examples=['{"tool_name": "my_tool", "parameters": {"required_param": "value"}}']
    ))
```

### 2. Register in Global Registry

```python
# orchestrator/app/agent/tools/registry.py

def _register_all_tools(registry: ToolRegistry):
    from .file_ops import register_all_file_tools
    from .shell_ops import register_all_shell_tools
    # ... existing imports ...
    from .my_category import register_my_tools  # Add import

    register_all_file_tools(registry)
    register_all_shell_tools(registry)
    # ... existing registrations ...
    register_my_tools(registry)  # Register your tools
```

### 3. Test the Tool

```python
import asyncio
from orchestrator.app.agent.tools.registry import get_tool_registry

async def test_my_tool():
    registry = get_tool_registry()

    result = await registry.execute(
        tool_name="my_tool",
        parameters={"required_param": "test"},
        context={
            "user_id": user.id,
            "project_id": project.id,
            "edit_mode": "allow",
            "db": db
        }
    )

    assert result["success"] is True
    print("Tool executed successfully!")

asyncio.run(test_my_tool())
```

## Helper Utilities

### Output Formatters

```python
from orchestrator.app.agent.tools.output_formatter import (
    success_output,
    error_output,
    format_file_size,
    pluralize
)

# Success
success_output(
    message="Wrote 150 lines",
    file_path="src/App.jsx",
    content="...",
    details={"size": 4500}
)

# Error
error_output(
    message="File not found",
    suggestion="Use bash_exec with 'ls' to check available files",
    file_path="missing.txt"
)

# Formatting
format_file_size(4500)  # "4.4 KB"
pluralize(5, "file")    # "5 files"
pluralize(1, "file")    # "1 file"
```

### Retry Configuration

```python
from orchestrator.app.agent.tools.retry_config import tool_retry

@tool_retry
async def my_tool_executor(...):
    # Automatically retries on:
    # - ConnectionError
    # - TimeoutError
    # - IOError
    # Up to 3 attempts with exponential backoff (1s, 2s, 4s)
    pass
```

## Best Practices

### 1. Use Descriptive Names

```python
# ❌ Bad
name="do_thing"

# ✅ Good
name="write_file"
```

### 2. Provide Clear Descriptions

```python
# ❌ Bad
description="Does stuff with files"

# ✅ Good
description="Write complete file content (creates if doesn't exist). "
           "Use patch_file or multi_edit for editing existing files."
```

### 3. Validate Parameters

```python
# ❌ Bad
file_path = params.get("file_path")  # Might be None!

# ✅ Good
file_path = params.get("file_path")
if not file_path:
    raise ValueError("file_path parameter is required")
```

### 4. Return Helpful Errors

```python
# ❌ Bad
return {"success": False, "error": "Failed"}

# ✅ Good
return error_output(
    message="File 'config.json' does not exist",
    suggestion="Use bash_exec with 'ls' to check available files",
    exists=False,
    file_path="config.json"
)
```

### 5. Add Examples

```python
examples=[
    # Show common use cases
    '{"tool_name": "patch_file", "parameters": {"file_path": "src/App.jsx", ...}}',
    # Show edge cases
    '{"tool_name": "patch_file", "parameters": {"file_path": "nested/dir/file.js", ...}}'
]
```

## Related Documentation

- `registry.md` - Tool registry internals
- `file-ops.md` - File operation tools
- `shell-ops.md` - Shell command tools
- `graph-ops.md` - Graph view container tools
- `approval.md` - User approval system

## Key Files

| File | Purpose |
|------|---------|
| `tools/registry.py` | Tool registration and execution (400 lines) |
| `tools/output_formatter.py` | Standardized output formatting |
| `tools/retry_config.py` | Automatic retry decorator |
| `tools/approval_manager.py` | User approval for ask mode |
| `tools/file_ops/` | File operation tools |
| `tools/shell_ops/` | Shell command tools |
| `tools/graph_ops/` | Container management tools |
| `tools/project_ops/` | Project metadata tools |
| `tools/planning_ops/` | Task planning tools |
| `tools/web_ops/` | Web fetching tools |
