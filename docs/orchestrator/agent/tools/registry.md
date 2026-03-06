# Tool Registry

**File**: `orchestrator/app/agent/tools/registry.py` (400 lines)

The ToolRegistry manages tool registration, lookup, and execution with edit mode control and approval flow.

## Tool Class

Defines the structure of a tool:

```python
@dataclass
class Tool:
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON schema
    executor: Callable  # Async function
    category: ToolCategory
    examples: Optional[List[str]] = None
    system_prompt: Optional[str] = None
```

### Fields

- **name**: Unique identifier (e.g., "read_file", "bash_exec")
- **description**: What the tool does (shown to LLM in system prompt)
- **parameters**: JSON Schema defining parameters
- **executor**: Async function that executes the tool
- **category**: Tool category for organization
- **examples**: Example tool calls for LLM reference
- **system_prompt**: Additional instructions specific to this tool

### Example

```python
Tool(
    name="write_file",
    description="Write complete file content (creates if doesn't exist)",
    parameters={
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to file relative to project root"
            },
            "content": {
                "type": "string",
                "description": "Complete content to write"
            }
        },
        "required": ["file_path", "content"]
    },
    executor=write_file_tool,
    category=ToolCategory.FILE_OPS,
    examples=[
        '{"tool_name": "write_file", "parameters": {"file_path": "src/App.jsx", "content": "..."}}'
    ]
)
```

## ToolCategory Enum

Organizes tools into categories:

```python
class ToolCategory(Enum):
    FILE_OPS = "file_operations"
    SHELL = "shell_commands"
    PROJECT = "project_management"
    BUILD = "build_operations"
    VIEW_GRAPH = "graph_view_tools"
```

Categories help with:
- Organization in system prompts
- Filtering tools by function
- View-scoped tool selection

## ToolRegistry Class

### Initialization

```python
class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Tool] = {}
```

Starts with empty tool dictionary. Tools are added via `register()`.

### register()

Add a tool to the registry:

```python
def register(self, tool: Tool):
    if tool.name in self._tools:
        logger.warning(f"Overwriting existing tool: {tool.name}")
    self._tools[tool.name] = tool
    logger.info(f"Registered tool: {tool.name} (category: {tool.category.value})")
```

**Usage**:
```python
registry = ToolRegistry()
registry.register(Tool(name="my_tool", ...))
```

### get()

Retrieve a tool by name:

```python
def get(self, name: str) -> Optional[Tool]:
    return self._tools.get(name)
```

**Usage**:
```python
tool = registry.get("read_file")
if tool:
    print(f"Found: {tool.description}")
```

### list_tools()

List all tools, optionally filtered by category:

```python
def list_tools(self, category: Optional[ToolCategory] = None) -> List[Tool]:
    if category:
        return [t for t in self._tools.values() if t.category == category]
    return list(self._tools.values())
```

**Usage**:
```python
# All tools
all_tools = registry.list_tools()

# File operation tools only
file_tools = registry.list_tools(ToolCategory.FILE_OPS)
```

### get_system_prompt_section()

Generate formatted tool descriptions for LLM system prompt:

```python
def get_system_prompt_section(self) -> str:
    sections = []

    # Group by category
    for category in ToolCategory:
        tools = self.list_tools(category)
        if tools:
            sections.append(f"\n## {category.value.replace('_', ' ').title()}\n")
            for i, tool in enumerate(tools, 1):
                sections.append(f"{i}. {tool.to_prompt_format()}\n")

    return "\n".join(sections)
```

Output example:
```
## File Operations

1. read_file: Read the contents of a file from the project directory.
  Parameters:
  - file_path (string, required): Path to the file relative to project root
  Examples:
    {"tool_name": "read_file", "parameters": {"file_path": "src/App.jsx"}}

2. write_file: Write complete file content (creates if doesn't exist).
  Parameters:
  - file_path (string, required): Path to the file relative to project root
  - content (string, required): Complete content to write
  ...
```

### execute()

**The core method** - executes a tool with edit mode control:

```python
async def execute(
    self,
    tool_name: str,
    parameters: Dict[str, Any],
    context: Dict[str, Any]
) -> Dict[str, Any]:
    # 1. Validate tool exists
    # 2. Check edit mode
    # 3. Request approval if needed
    # 4. Execute tool
    # 5. Return result
```

#### Parameters

- **tool_name**: Name of tool to execute
- **parameters**: Tool parameters from agent
- **context**: Execution context
  - `user_id`: User UUID
  - `project_id`: Project UUID
  - `db`: Database session
  - `edit_mode`: "allow" | "ask" | "plan"
  - `skip_approval_check`: bool (internal use)
  - Other context passed to tool executor

#### Returns

```python
# Success
{
    "success": True,
    "tool": "tool_name",
    "result": {...}  # Tool-specific result
}

# Error
{
    "success": False,
    "tool": "tool_name",
    "error": "Error message"
}

# Approval Required
{
    "approval_required": True,
    "tool": "tool_name",
    "parameters": {...},
    "session_id": "..."
}
```

## Edit Mode Control

The registry automatically enforces edit mode restrictions:

### Dangerous Tools

```python
DANGEROUS_TOOLS = {
    'write_file', 'patch_file', 'multi_edit',  # File modifications
    'bash_exec', 'shell_exec', 'shell_open',   # Shell operations
    'web_fetch'                                 # Web operations
}
```

### Plan Mode Logic

```python
if edit_mode == 'plan' and is_dangerous:
    return {
        "success": False,
        "tool": tool_name,
        "error": f"Plan mode active - {tool_name} is disabled. "
                 "You can only read files and gather information."
    }
```

### Ask Mode Logic

```python
if edit_mode == 'ask' and is_dangerous and not skip_approval:
    from .approval_manager import get_approval_manager
    approval_mgr = get_approval_manager()

    session_id = context.get('chat_id', 'default')

    if not approval_mgr.is_tool_approved(session_id, tool_name):
        # Return approval request
        return {
            "approval_required": True,
            "tool": tool_name,
            "parameters": parameters,
            "session_id": session_id
        }
```

### Allow Mode Logic

```python
# No restrictions - execute directly
result = await tool.executor(parameters, context)
```

## Global Registry

Singleton pattern for global tool registry:

```python
_registry: Optional[ToolRegistry] = None

def get_tool_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
        _register_all_tools(_registry)
    return _registry
```

### _register_all_tools()

Registers all built-in tools:

```python
def _register_all_tools(registry: ToolRegistry):
    from .file_ops import register_all_file_tools
    from .shell_ops import register_all_shell_tools
    from .project_ops import register_all_project_tools
    from .planning_ops import register_all_planning_tools
    from .web_ops import register_all_web_tools

    register_all_file_tools(registry)      # 4 tools
    register_all_shell_tools(registry)     # 4 tools
    register_all_project_tools(registry)   # 1 tool
    register_all_planning_tools(registry)  # 2 tools
    register_all_web_tools(registry)       # 1 tool

    logger.info(f"Registered {len(registry._tools)} essential tools total")
```

## Scoped Tool Registry

Create registry with only specific tools:

```python
def create_scoped_tool_registry(
    tool_names: List[str],
    tool_configs: Optional[Dict[str, Dict[str, Any]]] = None
) -> ToolRegistry:
    """
    Create a ToolRegistry containing only specified tools.

    Args:
        tool_names: List of tool names to include
        tool_configs: Optional custom configurations per tool

    Returns:
        New ToolRegistry with only specified tools
    """
    scoped_registry = ToolRegistry()
    global_registry = get_tool_registry()

    for name in tool_names:
        tool = global_registry.get(name)
        if tool:
            # Apply custom config if provided
            if name in tool_configs:
                config = tool_configs[name]
                custom_tool = replace(
                    tool,
                    description=config.get("description", tool.description),
                    examples=config.get("examples", tool.examples),
                    system_prompt=config.get("system_prompt", tool.system_prompt)
                )
                scoped_registry.register(custom_tool)
            else:
                scoped_registry.register(tool)

    return scoped_registry
```

### Usage

```python
# Basic scoping
tools = create_scoped_tool_registry([
    "read_file",
    "write_file",
    "bash_exec"
])

# With custom configs
tools = create_scoped_tool_registry(
    ["read_file", "bash_exec"],
    tool_configs={
        "read_file": {
            "description": "Read React component files",
            "examples": ['{"tool_name": "read_file", "parameters": {"file_path": "src/Button.tsx"}}']
        }
    }
)
```

## Tool Execution Flow

Complete flow from agent request to result:

```
1. Agent generates JSON tool call
   {"tool_name": "write_file", "parameters": {...}}

2. Agent parser extracts tool call
   ToolCall(name="write_file", parameters={...})

3. ToolRegistry.execute() called
   └─> Validate tool exists
   └─> Check edit mode
       ├─ Plan mode + dangerous → Block
       ├─ Ask mode + dangerous → Request approval
       └─ Allow mode → Continue

4. Tool executor function runs
   └─> Validate parameters
   └─> Perform operation
   └─> Return standardized result

5. Result returned to agent
   {"success": true, "result": {...}}

6. Agent receives tool result
   └─> Formats as "Tool Results:" section
   └─> Feeds back to LLM for next iteration
```

## Complete Example

### Registering Custom Tool

```python
from orchestrator.app.agent.tools.registry import (
    Tool,
    ToolCategory,
    get_tool_registry
)
from orchestrator.app.agent.tools.output_formatter import (
    success_output,
    error_output
)

async def my_custom_tool_executor(
    params: Dict[str, Any],
    context: Dict[str, Any]
) -> Dict[str, Any]:
    """Custom tool implementation."""
    input_value = params.get("input")
    if not input_value:
        raise ValueError("input parameter is required")

    try:
        # Perform custom operation
        result = await process_input(input_value)

        return success_output(
            message=f"Processed {input_value}",
            result_data=result
        )

    except Exception as e:
        return error_output(
            message=f"Failed to process: {str(e)}",
            suggestion="Check input format"
        )

# Register tool
registry = get_tool_registry()
registry.register(Tool(
    name="my_custom_tool",
    description="Processes custom input data",
    category=ToolCategory.PROJECT,
    parameters={
        "type": "object",
        "properties": {
            "input": {
                "type": "string",
                "description": "Input data to process"
            }
        },
        "required": ["input"]
    },
    executor=my_custom_tool_executor,
    examples=[
        '{"tool_name": "my_custom_tool", "parameters": {"input": "test"}}'
    ]
))
```

### Using Tool

```python
# Execute tool
result = await registry.execute(
    tool_name="my_custom_tool",
    parameters={"input": "test_data"},
    context={
        "user_id": user.id,
        "project_id": project.id,
        "edit_mode": "allow",
        "db": db
    }
)

# Handle result
if result["success"]:
    print("Success:", result["result"])
else:
    print("Error:", result["error"])
```

## Best Practices

### 1. Use Descriptive Tool Names

```python
# ❌ Bad
name="do_file"

# ✅ Good
name="write_file"
```

### 2. Provide Clear Parameter Descriptions

```python
parameters={
    "type": "object",
    "properties": {
        "file_path": {
            "type": "string",
            "description": "Path to file relative to project root (e.g., 'src/App.jsx')"
        }
    }
}
```

### 3. Include Examples

```python
examples=[
    '{"tool_name": "write_file", "parameters": {"file_path": "src/App.jsx", "content": "..."}}'
]
```

### 4. Handle Errors Gracefully

```python
try:
    result = await perform_operation()
    return success_output(...)
except FileNotFoundError as e:
    return error_output(
        message=f"File not found: {e}",
        suggestion="Use bash_exec with 'ls' to check available files"
    )
```

### 5. Log Tool Execution

```python
logger.info(f"[TOOL-EXEC] Starting tool: {tool_name}")
logger.info(f"[TOOL-EXEC] Completed tool: {tool_name}, success={result['success']}")
```

## Related Files

- `orchestrator/app/agent/tools/approval_manager.py` - Approval system
- `orchestrator/app/agent/tools/output_formatter.py` - Result formatting
- `orchestrator/app/agent/tools/retry_config.py` - Retry decorator
- `orchestrator/app/agent/iterative_agent.py` - Uses ToolRegistry
- `orchestrator/app/agent/react_agent.py` - Uses ToolRegistry
