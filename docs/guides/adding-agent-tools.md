# Adding Agent Tools

This guide covers how to create new tools for the AI agent system in Tesslate Studio.

## Overview

Agent tools allow the AI to perform actions in user development environments. Each tool has:
- A name and description (shown to the LLM)
- A parameter schema (JSON Schema)
- An async executor function
- A category for organization

### Tool Location

Tools are organized in modules under:
```
orchestrator/app/agent/tools/
├── file_ops/       # File operations (read, write, edit)
├── shell_ops/      # Shell commands (bash, shell sessions)
├── project_ops/    # Project management
├── planning_ops/   # Task planning (todos)
├── web_ops/        # Web fetch operations
├── graph_ops/      # Graph/architecture view tools
└── registry.py     # Tool registry and registration
```

## Understanding the Tool Class

Tools are defined using the `Tool` dataclass in `registry.py`:

```python
@dataclass
class Tool:
    """
    Represents a tool that the agent can use.

    Attributes:
        name: Unique tool identifier
        description: What the tool does (shown to LLM)
        parameters: JSON schema for parameters
        executor: Async function that executes the tool
        category: Tool category
        examples: Example usage patterns
        system_prompt: Optional additional instructions for this tool
    """
    name: str
    description: str
    parameters: Dict[str, Any]
    executor: Callable
    category: ToolCategory
    examples: Optional[List[str]] = None
    system_prompt: Optional[str] = None
```

### Tool Categories

```python
class ToolCategory(Enum):
    FILE_OPS = "file_operations"
    SHELL = "shell_commands"
    PROJECT = "project_management"
    BUILD = "build_operations"
    VIEW_GRAPH = "graph_view_tools"  # Tools only available in graph view
```

## Step 1: Create the Tool File

Create a new directory or file under `orchestrator/app/agent/tools/`. For example, `code_analysis/`:

```
orchestrator/app/agent/tools/
└── code_analysis/
    ├── __init__.py
    └── analyzer.py
```

### __init__.py

```python
"""
Code Analysis Tools Module

Tools for analyzing code quality, complexity, and structure.
"""

from .analyzer import register_all_analysis_tools


def register_all_code_analysis_tools(registry):
    """Register all code analysis tools."""
    register_all_analysis_tools(registry)


__all__ = [
    "register_all_code_analysis_tools",
]
```

## Step 2: Implement the Executor Function

Create `analyzer.py`:

```python
"""
Code Analysis Tools

Tools for analyzing code in user development environments.
"""

import logging
from typing import Dict, Any

from ..registry import Tool, ToolCategory
from ..output_formatter import success_output, error_output
from ..retry_config import tool_retry

logger = logging.getLogger(__name__)


@tool_retry
async def analyze_code_tool(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Analyze code for quality metrics.

    Args:
        params: Tool parameters
            - file_path: Path to the file to analyze
            - metrics: List of metrics to compute (optional)
        context: Execution context
            - user_id: UUID of the user
            - project_id: Project ID
            - project_slug: Project slug
            - container_directory: Container subdirectory (for scoped agents)

    Returns:
        Dict with analysis results or error
    """
    file_path = params.get("file_path")
    if not file_path:
        return error_output(
            message="file_path parameter is required",
            suggestion="Provide the path to the file you want to analyze"
        )

    metrics = params.get("metrics", ["complexity", "lines", "functions"])

    # Extract context
    user_id = context["user_id"]
    project_id = str(context["project_id"])
    project_slug = context.get("project_slug")
    container_directory = context.get("container_directory")

    logger.info(f"[ANALYZE-CODE] Analyzing '{file_path}' - project_slug: {project_slug}")

    # Get orchestrator to read the file
    from ....services.orchestration import get_orchestrator

    try:
        orchestrator = get_orchestrator()
        content = await orchestrator.read_file(
            user_id=user_id,
            project_id=project_id,
            container_name=context.get("container_name"),
            file_path=file_path,
            project_slug=project_slug,
            subdir=container_directory
        )

        if content is None:
            return error_output(
                message=f"File '{file_path}' does not exist",
                suggestion="Use bash_exec with 'ls' to find available files"
            )

        # Perform analysis
        results = {
            "file_path": file_path,
            "lines": len(content.split('\n')),
            "characters": len(content),
        }

        # Add metric-specific analysis
        if "functions" in metrics:
            # Simple function count (for Python/JS)
            results["function_count"] = content.count('def ') + content.count('function ')

        if "complexity" in metrics:
            # Simple complexity estimate
            complexity_keywords = ['if ', 'for ', 'while ', 'case ', 'catch ']
            results["complexity_score"] = sum(content.count(kw) for kw in complexity_keywords)

        return success_output(
            message=f"Analyzed '{file_path}': {results['lines']} lines, complexity score {results.get('complexity_score', 'N/A')}",
            file_path=file_path,
            analysis=results
        )

    except Exception as e:
        logger.error(f"[ANALYZE-CODE] Failed to analyze '{file_path}': {e}")
        return error_output(
            message=f"Failed to analyze '{file_path}': {str(e)}",
            suggestion="Check if the file exists and is readable",
            file_path=file_path
        )
```

## Step 3: Register the Tool

Add the registration function:

```python
def register_all_analysis_tools(registry):
    """Register all code analysis tools."""

    registry.register(Tool(
        name="analyze_code",
        description="Analyze code for quality metrics like complexity, line count, and function count. Use this before making significant changes to understand the codebase.",
        parameters={
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file relative to project root (e.g., 'src/App.jsx')"
                },
                "metrics": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Metrics to compute: complexity, lines, functions (default: all)",
                    "default": ["complexity", "lines", "functions"]
                }
            },
            "required": ["file_path"]
        },
        executor=analyze_code_tool,
        category=ToolCategory.FILE_OPS,
        examples=[
            '{"tool_name": "analyze_code", "parameters": {"file_path": "src/components/Header.jsx"}}',
            '{"tool_name": "analyze_code", "parameters": {"file_path": "src/utils/helpers.ts", "metrics": ["complexity"]}}'
        ],
        system_prompt="Use this tool to understand code complexity before refactoring."
    ))

    logger.info("Registered 1 code analysis tool")
```

## Step 4: Add to Registry

Edit `orchestrator/app/agent/tools/registry.py` to include your new tools:

```python
def _register_all_tools(registry: ToolRegistry):
    """Register all essential tools from modular structure."""
    from .file_ops import register_all_file_tools
    from .shell_ops import register_all_shell_tools
    from .project_ops import register_all_project_tools
    from .planning_ops import register_all_planning_tools
    from .web_ops import register_all_web_tools
    from .code_analysis import register_all_code_analysis_tools  # Add import

    # Register essential tools
    register_all_file_tools(registry)
    register_all_shell_tools(registry)
    register_all_project_tools(registry)
    register_all_planning_tools(registry)
    register_all_web_tools(registry)
    register_all_code_analysis_tools(registry)  # Add registration

    logger.info(f"Registered {len(registry._tools)} essential tools total")
```

## Step 5: Handle Tool Execution Context

The execution context provides important information:

```python
context = {
    "user_id": UUID,           # User making the request
    "project_id": str,         # Project ID
    "project_slug": str,       # Project slug (e.g., "my-app-k3x8n2")
    "container_directory": str, # Container subdirectory for scoped agents
    "container_name": str,      # Container name
    "edit_mode": str,          # "ask", "plan", or "auto"
    "chat_id": str,            # Chat session ID
    "db": AsyncSession,        # Database session (if needed)
}
```

## Step 6: Use Output Formatters

Use the standardized output formatters for consistent responses:

```python
from ..output_formatter import success_output, error_output, format_file_size, pluralize

# Success response
return success_output(
    message="Operation completed successfully",
    file_path=file_path,
    content=result,
    details={"key": "value"}
)

# Error response
return error_output(
    message="Operation failed",
    suggestion="Try this instead...",
    file_path=file_path,
    details={"error": str(e)}
)
```

## Step 7: Add Retry Logic

Use the `@tool_retry` decorator for automatic retries on transient failures:

```python
from ..retry_config import tool_retry

@tool_retry
async def my_tool(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Tool with automatic retry on transient failures."""
    # Retries automatically on: ConnectionError, TimeoutError, IOError
    # Fails immediately on: FileNotFoundError, PermissionError, ValueError
    ...
```

## Testing the Tool

### 1. Unit Tests

Create `orchestrator/tests/agent/tools/test_code_analysis.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch

from app.agent.tools.code_analysis.analyzer import analyze_code_tool


@pytest.mark.asyncio
async def test_analyze_code_success():
    """Test successful code analysis."""
    params = {"file_path": "src/App.jsx"}
    context = {
        "user_id": "test-user-id",
        "project_id": "test-project-id",
        "project_slug": "test-project",
    }

    # Mock the orchestrator
    with patch('app.agent.tools.code_analysis.analyzer.get_orchestrator') as mock_get_orch:
        mock_orchestrator = AsyncMock()
        mock_orchestrator.read_file.return_value = "function test() {\n  if (true) {\n    return 1;\n  }\n}"
        mock_get_orch.return_value = mock_orchestrator

        result = await analyze_code_tool(params, context)

        assert result["success"] is True
        assert "analysis" in result
        assert result["analysis"]["lines"] == 5


@pytest.mark.asyncio
async def test_analyze_code_file_not_found():
    """Test analysis of non-existent file."""
    params = {"file_path": "nonexistent.js"}
    context = {
        "user_id": "test-user-id",
        "project_id": "test-project-id",
        "project_slug": "test-project",
    }

    with patch('app.agent.tools.code_analysis.analyzer.get_orchestrator') as mock_get_orch:
        mock_orchestrator = AsyncMock()
        mock_orchestrator.read_file.return_value = None
        mock_get_orch.return_value = mock_orchestrator

        result = await analyze_code_tool(params, context)

        assert result["success"] is False
        assert "does not exist" in result["message"]
```

### 2. Integration Testing

Test with the agent by sending a chat message:

```
User: Analyze the complexity of src/App.jsx
Agent: [Uses analyze_code tool]
```

## Dangerous Tools and Edit Modes

Tools that modify state should be registered as "dangerous" in the registry:

```python
# In registry.py execute() method:
DANGEROUS_TOOLS = {
    'write_file', 'patch_file', 'multi_edit',  # File modifications
    'bash_exec', 'shell_exec', 'shell_open',   # Shell operations
    'web_fetch',                                # Web operations
}
```

Edit modes control dangerous tool execution:
- **plan**: Blocks all dangerous tools
- **ask**: Requires user approval before execution
- **auto**: Executes without confirmation

Read-only tools (like `analyze_code`) do not need to be in the dangerous list.

## Creating Scoped Tool Registries

For specialized agents with limited tool access:

```python
from .registry import create_scoped_tool_registry

# Create a registry with only specific tools
scoped_registry = create_scoped_tool_registry(
    tool_names=["read_file", "analyze_code", "get_project_info"],
    tool_configs={
        "read_file": {
            "description": "Read project files for analysis",
            "examples": ["...custom examples..."],
        }
    }
)
```

## Best Practices

### 1. Clear Descriptions

Write descriptions that help the LLM understand when to use the tool:

```python
description="Analyze code for quality metrics like complexity, line count, and function count. Use this before making significant changes to understand the codebase."
```

### 2. Comprehensive Examples

Provide realistic examples:

```python
examples=[
    '{"tool_name": "analyze_code", "parameters": {"file_path": "src/App.jsx"}}',
    '{"tool_name": "analyze_code", "parameters": {"file_path": "src/utils.ts", "metrics": ["complexity"]}}',
]
```

### 3. Helpful Error Messages

Include suggestions in error responses:

```python
return error_output(
    message="File not found",
    suggestion="Use 'ls' command to find available files in the directory"
)
```

### 4. Logging

Log important operations for debugging:

```python
logger.info(f"[TOOL-NAME] Starting operation: {params}")
logger.error(f"[TOOL-NAME] Operation failed: {e}")
```

### 5. Non-Blocking Operations

For long-running operations, consider async execution:

```python
import asyncio

async def long_running_tool(params, context):
    # Run CPU-intensive work in thread pool
    result = await asyncio.get_event_loop().run_in_executor(
        None,  # Default executor
        cpu_intensive_function,
        params
    )
    return success_output(message="Complete", result=result)
```

## Skills System

In addition to tools, agents can be extended with **skills** — reusable knowledge modules that inject domain-specific guidelines into the agent's context. Unlike tools (which execute code), skills provide declarative knowledge as markdown content.

### How Skills Differ from Tools

| Aspect | Tool | Skill |
|--------|------|-------|
| Type | Executable function | Markdown knowledge |
| Stored as | `Tool` dataclass in registry | `MarketplaceAgent` with `item_type='skill'` |
| Execution | Called via tool_call | Injected into system prompt context |
| DB field | `tools` (JSON list) | `skill_body` (Text) |
| Assignment | Via `tool_configs` on agent | Via `agent_skill_assignments` table |

### Skill Body Format

Skills are stored in the `skill_body` column of `MarketplaceAgent` records:

```markdown
## Vercel React Best Practices

### Guidelines
- Prefer React Server Components for data fetching
- Use Suspense boundaries for streaming UI
- Leverage Next.js App Router conventions
- Implement proper caching with revalidation strategies
```

### Adding New Skills

Skills are seeded via `orchestrator/app/seeds/skills.py`. To add a new skill:

1. Add an entry to the `OPENSOURCE_SKILLS` list in `orchestrator/app/seeds/skills.py`
2. Include `item_type: "skill"`, a `slug`, `skill_body` or `fallback_skill_body`, and optionally a `github_raw_url` for fetching from GitHub
3. Run the seed: `docker exec -e PYTHONPATH=/app tesslate-orchestrator python /tmp/seed_skills.py`

Skills are assigned to agents per-user via the `agent_skill_assignments` table (migration 0024).

### Key Files

| File | Purpose |
|------|---------|
| `orchestrator/app/seeds/skills.py` | Skill definitions and seeding logic |
| `scripts/seed/seed_skills.py` | Standalone seed script |
| `orchestrator/alembic/versions/0024_add_skills_system.py` | Database migration |

## Complete Example

See `orchestrator/app/agent/tools/file_ops/read_write.py` for a complete, production-ready tool implementation.

## Next Steps

- [Adding Routers](adding-routers.md) - Create API endpoints
- [Universal Project Setup](universal-project-setup.md) - Understand .tesslate/config.json
- [Troubleshooting](troubleshooting.md) - Debug tool issues
- [Local Development](local-development.md) - Test your tools
