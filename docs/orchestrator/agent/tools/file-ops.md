# File Operation Tools

File operation tools enable agents to read, write, and edit files in user development environments.

## Tools Overview

| Tool | Purpose | Files Modified | Use Case |
|------|---------|----------------|----------|
| `read_file` | Read file contents | None | Understanding code, checking configs |
| `write_file` | Write complete file | Creates/overwrites | New files, full rewrites |
| `patch_file` | Surgical edit | Updates existing | Small changes, bug fixes |
| `multi_edit` | Multiple patches | Updates existing | Batch refactoring |

## Architecture

Files are stored in two locations:

### Docker Mode
- **Path**: `/projects/{project-slug}/`
- **Access**: Direct filesystem via orchestrator
- **Volume**: Shared `tesslate-projects-data`

### Kubernetes Mode
- **Path**: `/app` (inside pod)
- **Access**: K8s API exec commands
- **Storage**: Ephemeral PVC + S3 (S3 Sandwich pattern)

All tools use the unified orchestrator interface which abstracts Docker/K8s differences.

## read_file

**File**: `orchestrator/app/agent/tools/file_ops/read_write.py`

Read complete file contents.

### Parameters

```python
{
    "file_path": "src/App.jsx"  # Path relative to project root
}
```

### Returns

```python
# Success
{
    "success": True,
    "tool": "read_file",
    "result": {
        "message": "Read 4.4 KB from 'src/App.jsx'",
        "file_path": "src/App.jsx",
        "content": "import React from 'react'...",
        "details": {
            "size_bytes": 4500,
            "lines": 150
        }
    }
}

# Error
{
    "success": False,
    "tool": "read_file",
    "error": "File 'src/App.jsx' does not exist",
    "result": {
        "message": "File 'src/App.jsx' does not exist",
        "suggestion": "Use execute_command with 'ls' or 'find' to browse available files",
        "exists": False,
        "file_path": "src/App.jsx"
    }
}
```

### Implementation

```python
@tool_retry
async def read_file_tool(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    file_path = params.get("file_path")
    if not file_path:
        raise ValueError("file_path parameter is required")

    user_id = context["user_id"]
    project_id = str(context["project_id"])
    container_name = context.get("container_name")

    from ....services.orchestration import get_orchestrator

    try:
        orchestrator = get_orchestrator()
        content = await orchestrator.read_file(
            user_id=user_id,
            project_id=project_id,
            container_name=container_name,
            file_path=file_path
        )

        if content is not None:
            return success_output(
                message=f"Read {format_file_size(len(content))} from '{file_path}'",
                file_path=file_path,
                content=content,
                details={
                    "size_bytes": len(content),
                    "lines": len(content.split('\n'))
                }
            )

    except Exception as e:
        logger.error(f"[READ-FILE] Failed to read '{file_path}': {e}")

    return error_output(
        message=f"File '{file_path}' does not exist",
        suggestion="Use execute_command with 'ls' or 'find' to browse available files",
        file_path=file_path
    )
```

### Usage Examples

```python
# Agent tool call
THOUGHT: I need to understand the current App component structure.

{
  "tool_name": "read_file",
  "parameters": {
    "file_path": "src/App.jsx"
  }
}

# Read nested file
{
  "tool_name": "read_file",
  "parameters": {
    "file_path": "src/components/auth/LoginForm.tsx"
  }
}
```

## write_file

**File**: `orchestrator/app/agent/tools/file_ops/read_write.py`

Write complete file contents (creates new or overwrites existing).

### Parameters

```python
{
    "file_path": "src/App.jsx",
    "content": "import React from 'react'..."
}
```

### When to Use

Use `write_file` for:
- Creating new files
- Complete file rewrites
- Small files where reading first isn't necessary

For editing existing files, prefer `patch_file` or `multi_edit` to save tokens.

### Returns

```python
# Success
{
    "success": True,
    "tool": "write_file",
    "result": {
        "message": "Wrote 150 lines (4.4 KB) to 'src/App.jsx'",
        "file_path": "src/App.jsx",
        "preview": "import React from 'react'...\n\n... (140 lines omitted) ...\n\nexport default App;",
        "details": {
            "size_bytes": 4500,
            "line_count": 150
        }
    }
}
```

### Implementation

```python
@tool_retry
async def write_file_tool(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    file_path = params.get("file_path")
    content = params.get("content")

    if not file_path:
        raise ValueError("file_path parameter is required")
    if content is None:
        raise ValueError("content parameter is required")

    # Generate preview (first 5 and last 5 lines)
    lines = content.split('\n')
    if len(lines) <= 10:
        preview = content
    else:
        preview = '\n'.join(lines[:5]) + f'\n\n... ({len(lines) - 10} lines omitted) ...\n\n' + '\n'.join(lines[-5:])

    from ....services.orchestration import get_orchestrator

    try:
        orchestrator = get_orchestrator()
        success = await orchestrator.write_file(
            user_id=context["user_id"],
            project_id=str(context["project_id"]),
            container_name=context.get("container_name"),
            file_path=file_path,
            content=content
        )

        if success:
            return success_output(
                message=f"Wrote {pluralize(len(lines), 'line')} ({format_file_size(len(content))}) to '{file_path}'",
                file_path=file_path,
                preview=preview,
                details={"size_bytes": len(content), "line_count": len(lines)}
            )

    except Exception as e:
        return error_output(
            message=f"Could not write to '{file_path}': {str(e)}",
            suggestion="Check if the directory exists and you have write permissions",
            file_path=file_path
        )
```

### Usage Examples

```python
# Create new file
{
  "tool_name": "write_file",
  "parameters": {
    "file_path": "src/components/Button.tsx",
    "content": "import React from 'react';\n\nexport function Button({ children, onClick }) {\n  return <button onClick={onClick}>{children}</button>;\n}"
  }
}

# Write config file
{
  "tool_name": "write_file",
  "parameters": {
    "file_path": ".env.example",
    "content": "API_KEY=your_key_here\nDATABASE_URL=postgresql://..."
  }
}
```

## patch_file

**File**: `orchestrator/app/agent/tools/file_ops/edit.py`

Apply surgical search/replace edit to existing file using fuzzy matching.

### Parameters

```python
{
    "file_path": "src/App.jsx",
    "search": "  <button className=\"bg-blue-500\">\n    Click Me\n  </button>",
    "replace": "  <button className=\"bg-green-500\">\n    Click Me\n  </button>"
}
```

### Fuzzy Matching

The tool uses fuzzy matching to handle whitespace variations:
- Normalizes indentation
- Handles tabs vs spaces
- Tolerates extra/missing whitespace

### Returns

```python
# Success
{
    "success": True,
    "tool": "patch_file",
    "result": {
        "message": "Successfully patched 'src/App.jsx'",
        "file_path": "src/App.jsx",
        "diff": "@@ -10,3 +10,3 @@\n-  <button className=\"bg-blue-500\">\n+  <button className=\"bg-green-500\">",
        "details": {
            "match_method": "exact",
            "size_bytes": 4520
        }
    }
}

# Error - no match found
{
    "success": False,
    "tool": "patch_file",
    "error": "Could not find matching code in 'src/App.jsx'",
    "result": {
        "message": "Could not find matching code",
        "suggestion": "Make sure the search block matches existing code exactly (including indentation)",
        "file_path": "src/App.jsx"
    }
}
```

### Implementation

```python
@tool_retry
async def patch_file_tool(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    file_path = params.get("file_path")
    search = params.get("search")
    replace = params.get("replace")

    # Validation...

    from ....utils.code_patching import apply_search_replace
    from ....services.orchestration import get_orchestrator

    # 1. Read current content
    orchestrator = get_orchestrator()
    current_content = await orchestrator.read_file(...)

    if current_content is None:
        return error_output(message="File does not exist", ...)

    # 2. Apply search/replace with fuzzy matching
    result = apply_search_replace(current_content, search, replace, fuzzy=True)

    if not result.success:
        return error_output(message="Could not find matching code", ...)

    # 3. Write patched content
    success = await orchestrator.write_file(..., content=result.content)

    # 4. Generate diff preview
    diff_preview = _generate_diff_preview(current_content, result.content)

    return success_output(
        message=f"Successfully patched '{file_path}'",
        file_path=file_path,
        diff=diff_preview,
        details={"match_method": result.match_method}
    )
```

### Usage Examples

```python
# Change button color
{
  "tool_name": "patch_file",
  "parameters": {
    "file_path": "src/App.jsx",
    "search": "  <button className=\"bg-blue-500\">\n    Click Me\n  </button>",
    "replace": "  <button className=\"bg-green-500\">\n    Click Me\n  </button>"
  }
}

# Update import
{
  "tool_name": "patch_file",
  "parameters": {
    "file_path": "src/App.jsx",
    "search": "import { useState } from 'react';",
    "replace": "import { useState, useEffect } from 'react';"
  }
}
```

### Best Practices

1. **Include Context**: Provide 3-5 lines around the change for uniqueness
2. **Preserve Indentation**: Match exact indentation from file
3. **Use Unique Blocks**: Avoid searching for common patterns like `}`
4. **Read First**: Always read file before patching to verify content

## multi_edit

**File**: `orchestrator/app/agent/tools/file_ops/edit.py`

Apply multiple search/replace edits to a single file atomically.

### Parameters

```python
{
    "file_path": "src/App.jsx",
    "edits": [
        {
            "search": "const [count, setCount] = useState(0)",
            "replace": "const [count, setCount] = useState(10)"
        },
        {
            "search": "bg-blue-500",
            "replace": "bg-green-500"
        }
    ]
}
```

### Execution Order

Edits are applied **sequentially** - each edit operates on the result of the previous edit:

```python
# Edit 1
original → edit1_search/replace → intermediate1

# Edit 2
intermediate1 → edit2_search/replace → intermediate2

# Edit 3
intermediate2 → edit3_search/replace → final
```

### Returns

```python
# Success
{
    "success": True,
    "tool": "multi_edit",
    "result": {
        "message": "Successfully applied 2 edits to 'src/App.jsx'",
        "file_path": "src/App.jsx",
        "diff": "@@ -5,3 +5,3 @@\n-const [count, setCount] = useState(0)\n+const [count, setCount] = useState(10)\n...",
        "details": {
            "edit_count": 2,
            "applied_edits": [
                {"index": 0, "match_method": "exact"},
                {"index": 1, "match_method": "fuzzy"}
            ]
        }
    }
}

# Partial failure (edit 2 failed)
{
    "success": False,
    "tool": "multi_edit",
    "error": "Edit 2/3 failed: could not find matching code",
    "result": {
        "message": "Edit 2/3 failed",
        "suggestion": "Make sure all search blocks match existing code",
        "details": {
            "edit_index": 1,
            "applied_edits": [{"index": 0, "match_method": "exact"}]
        }
    }
}
```

### When to Use

Use `multi_edit` when:
- Making multiple related changes to one file
- Refactoring function signatures
- Batch renaming variables
- More efficient than multiple `patch_file` calls

### Usage Examples

```python
# Refactor component props
{
  "tool_name": "multi_edit",
  "parameters": {
    "file_path": "src/components/UserCard.tsx",
    "edits": [
      {
        "search": "interface UserCardProps {\n  name: string;\n}",
        "replace": "interface UserCardProps {\n  name: string;\n  email: string;\n}"
      },
      {
        "search": "function UserCard({ name }: UserCardProps)",
        "replace": "function UserCard({ name, email }: UserCardProps)"
      },
      {
        "search": "  <div>{name}</div>",
        "replace": "  <div>\n    <p>{name}</p>\n    <p>{email}</p>\n  </div>"
      }
    ]
  }
}
```

## Deployment Awareness

All tools work with both Docker and Kubernetes:

### Orchestrator Interface

```python
from orchestrator.app.services.orchestration import get_orchestrator

orchestrator = get_orchestrator()

# Read file (works in Docker and K8s)
content = await orchestrator.read_file(
    user_id=user.id,
    project_id=project.id,
    container_name=None,  # Use default container
    file_path="src/App.jsx"
)

# Write file (works in Docker and K8s)
success = await orchestrator.write_file(
    user_id=user.id,
    project_id=project.id,
    container_name=None,
    file_path="src/App.jsx",
    content="..."
)
```

### Docker Implementation
- Direct filesystem access via shared volume
- Fast and simple

### Kubernetes Implementation
- K8s API exec: `kubectl exec -n namespace pod -- cat /app/src/App.jsx`
- More complex but enables pod isolation

## Retry Strategy

All file tools use `@tool_retry` decorator:

```python
@tool_retry
async def read_file_tool(...):
    # Automatically retries on:
    # - ConnectionError
    # - TimeoutError
    # - IOError
    #
    # Exponential backoff:
    # - Attempt 1: immediate
    # - Attempt 2: 1s delay
    # - Attempt 3: 2s delay
    # - Attempt 4: 4s delay
```

Non-retryable errors (FileNotFoundError, PermissionError) fail immediately.

## Best Practices

### 1. Read Before Write

```python
# ❌ Bad: Overwrite without reading
{
  "tool_name": "write_file",
  "parameters": {"file_path": "src/App.jsx", "content": "..."}
}

# ✅ Good: Read first to understand current state
[
  {
    "tool_name": "read_file",
    "parameters": {"file_path": "src/App.jsx"}
  },
  {
    "tool_name": "patch_file",
    "parameters": {"file_path": "src/App.jsx", "search": "...", "replace": "..."}
  }
]
```

### 2. Use Appropriate Tool

```python
# ❌ Bad: write_file for small change (wastes tokens)
{
  "tool_name": "write_file",
  "parameters": {"file_path": "src/App.jsx", "content": "<entire 500-line file>"}
}

# ✅ Good: patch_file for small change
{
  "tool_name": "patch_file",
  "parameters": {"file_path": "src/App.jsx", "search": "old", "replace": "new"}
}
```

### 3. Provide Context in Search Blocks

```python
# ❌ Bad: Too generic, may match multiple locations
"search": "return (<div>"

# ✅ Good: Unique context
"search": "function LoginForm() {\n  return (\n    <div className=\"login-form\">"
```

## Related Files

- `orchestrator/app/agent/tools/file_ops/__init__.py` - Tool registration
- `orchestrator/app/services/orchestration/base_orchestrator.py` - Orchestrator interface
- `orchestrator/app/utils/code_patching.py` - Fuzzy matching implementation
- `orchestrator/app/agent/tools/output_formatter.py` - Result formatting
- `orchestrator/app/agent/tools/retry_config.py` - Retry decorator
