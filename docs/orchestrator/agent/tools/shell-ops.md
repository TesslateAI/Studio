# Shell Operation Tools

Shell operation tools enable agents to execute commands in user development containers.

## Tools Overview

| Tool | Purpose | Session Management | Use Case |
|------|---------|-------------------|----------|
| `bash_exec` | One-off command | Auto-managed | Quick commands (npm install, ls) |
| `shell_open` | Open session | Manual | Persistent shell for multiple commands |
| `shell_exec` | Execute in session | Manual | Execute command in open session |
| `shell_close` | Close session | Manual | Cleanup when done |

## bash_exec (Convenience Wrapper)

**File**: `orchestrator/app/agent/tools/shell_ops/bash.py`

Execute a single command with automatic session management.

### Parameters

```python
{
    "command": "npm install",
    "wait_seconds": 2.0  # Optional, default 2.0
}
```

### Session Reuse

`bash_exec` reuses shell sessions within the same agent run for efficiency:

```python
# First call: opens new session
bash_exec("npm install")

# Second call: reuses same session
bash_exec("npm run build")

# Session persists until agent run completes
```

Session ID is stored in `context['_bash_session_id']` and automatically managed.

### Returns

```python
# Success
{
    "success": True,
    "tool": "bash_exec",
    "result": {
        "message": "Executed 'npm install'",
        "output": "added 234 packages in 5.2s\n\n23 packages are looking for funding...",
        "details": {
            "command": "npm install",
            "exit_code": 0,
            "session_reused": True
        }
    }
}

# Error
{
    "success": False,
    "tool": "bash_exec",
    "error": "Command execution failed: ...",
    "result": {
        "message": "Command execution failed",
        "suggestion": "Check your command syntax and try again",
        "details": {"command": "npm install", "error": "..."}
    }
}
```

### Implementation

```python
@tool_retry
async def bash_exec_tool(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    command = params.get("command")
    wait_seconds = params.get("wait_seconds", 2.0)

    if not command:
        raise ValueError("command parameter is required")

    # Check for reusable session
    session_id = context.get("_bash_session_id")
    session_created = False

    try:
        # 1. Open session only if we don't have one
        if not session_id:
            session_result = await shell_open_executor({}, context)
            if not session_result.get("success"):
                return error_output(
                    message="Failed to open shell session",
                    suggestion="Check if the dev container is running"
                )

            session_id = session_result["session_id"]
            session_created = True
            context["_bash_session_id"] = session_id

        # 2. Execute command
        exec_result = await shell_exec_executor({
            "session_id": session_id,
            "command": command,
            "wait_seconds": wait_seconds
        }, context)

        # 3. Return result (session stays open for reuse)
        return success_output(
            message=f"Executed '{command}'",
            output=exec_result.get("output", ""),
            details={
                "command": command,
                "exit_code": 0,
                "session_reused": not session_created
            }
        )

    except Exception as e:
        # On error, close and clear session
        if session_id:
            try:
                await shell_close_executor({"session_id": session_id}, context)
                context.pop("_bash_session_id", None)
            except Exception:
                pass

        return error_output(
            message=f"Command execution failed: {str(e)}",
            suggestion="Check your command syntax and try again",
            details={"command": command, "error": str(e)}
        )
```

### Usage Examples

```python
# Install dependencies
{
  "tool_name": "bash_exec",
  "parameters": {
    "command": "npm install"
  }
}

# List files
{
  "tool_name": "bash_exec",
  "parameters": {
    "command": "ls -la"
  }
}

# Run tests with longer wait
{
  "tool_name": "bash_exec",
  "parameters": {
    "command": "npm test",
    "wait_seconds": 5.0
  }
}

# Multiple commands in sequence (reuses session)
[
  {
    "tool_name": "bash_exec",
    "parameters": {"command": "cd src"}
  },
  {
    "tool_name": "bash_exec",
    "parameters": {"command": "ls -la"}
  }
]
```

### When to Use

Use `bash_exec` for:
- One-off commands
- Simple operations
- Commands that don't depend on previous state

For interactive workflows, use `shell_open` + `shell_exec` instead.

## shell_open

**File**: `orchestrator/app/agent/tools/shell_ops/session.py`

Open a persistent shell session in the dev container.

### Parameters

```python
{
    "command": "/bin/sh"  # Optional, default /bin/sh
}
```

Alpine-based containers use `/bin/sh`, not `/bin/bash`.

### Returns

```python
# Success
{
    "success": True,
    "tool": "shell_open",
    "result": {
        "message": "Opened shell session abc123xyz",
        "session_id": "abc123xyz",
        "details": {"command": "/bin/sh"}
    }
}

# Error - session limit reached
{
    "success": False,
    "tool": "shell_open",
    "error": "Session limit reached. 3 active session(s):\n  - abc123 (created: ..., last active: ...)\n  - def456 (created: ..., last active: ...)\n  - ghi789 (created: ..., last active: ...)\n\nOptions: 1) Use existing session_id with shell_exec, or 2) Close old session with shell_close."
}
```

### Implementation

```python
async def shell_open_executor(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    from ....services.shell_session_manager import get_shell_session_manager

    project_id = context["project_id"]
    command = params.get("command", "/bin/sh")
    user_id = context["user_id"]
    db = context["db"]
    container_name = context.get("container_name")

    session_manager = get_shell_session_manager()

    try:
        session_info = await session_manager.create_session(
            user_id=user_id,
            project_id=project_id,
            db=db,
            command=command,
            container_name=container_name
        )

        session_id = session_info["session_id"]

        return success_output(
            message=f"Opened shell session {session_id}",
            session_id=session_id,
            details={"command": command}
        )

    except HTTPException as e:
        if e.status_code == 429:
            # Get existing sessions for error message
            existing_sessions = await session_manager.list_sessions(user_id, project_id, db)

            session_list = "\n".join([
                f"  - {s['session_id']} (created: {s['created_at']}, last active: {s['last_activity_at']})"
                for s in existing_sessions
            ])

            error_msg = (
                f"Session limit reached. {len(existing_sessions)} active session(s):\n{session_list}\n\n"
                f"Options: 1) Use existing session_id with shell_exec, or 2) Close old session with shell_close."
            )

            raise ValueError(error_msg)
        else:
            raise
```

### Usage Examples

```python
# Open default shell
{
  "tool_name": "shell_open",
  "parameters": {}
}

# Open specific shell
{
  "tool_name": "shell_open",
  "parameters": {
    "command": "/bin/sh"
  }
}
```

## shell_exec

**File**: `orchestrator/app/agent/tools/shell_ops/execute.py`

Execute command in an existing shell session.

### Parameters

```python
{
    "session_id": "abc123xyz",
    "command": "npm run dev",
    "wait_seconds": 2.0  # Optional, default 2.0
}
```

### Returns

```python
# Success
{
    "success": True,
    "tool": "shell_exec",
    "result": {
        "message": "Executed command in session abc123xyz",
        "output": "> vite\n\nVITE v4.0.0  ready in 234 ms\n\n  ➜  Local:   http://localhost:5173/",
        "session_id": "abc123xyz",
        "command": "npm run dev"
    }
}
```

### Implementation

```python
async def shell_exec_executor(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    from ....services.shell_session_manager import get_shell_session_manager

    session_id = params.get("session_id")
    command = params.get("command")
    wait_seconds = params.get("wait_seconds", 2.0)

    if not session_id or not command:
        raise ValueError("session_id and command parameters are required")

    session_manager = get_shell_session_manager()

    # Execute command in session
    output = await session_manager.execute_command(
        session_id=session_id,
        command=command,
        wait_seconds=wait_seconds,
        db=context["db"]
    )

    return success_output(
        message=f"Executed command in session {truncate_session_id(session_id)}",
        output=output,
        session_id=session_id,
        command=command
    )
```

### Usage Examples

```python
# Interactive workflow
# 1. Open session
{
  "tool_name": "shell_open",
  "parameters": {}
}
# Returns: {"session_id": "abc123xyz"}

# 2. Navigate directory
{
  "tool_name": "shell_exec",
  "parameters": {
    "session_id": "abc123xyz",
    "command": "cd src"
  }
}

# 3. List files
{
  "tool_name": "shell_exec",
  "parameters": {
    "session_id": "abc123xyz",
    "command": "ls -la"
  }
}

# 4. Check git status
{
  "tool_name": "shell_exec",
  "parameters": {
    "session_id": "abc123xyz",
    "command": "git status"
  }
}
```

## shell_close

**File**: `orchestrator/app/agent/tools/shell_ops/session.py`

Close an active shell session to free resources.

### Parameters

```python
{
    "session_id": "abc123xyz"
}
```

### Returns

```python
# Success
{
    "success": True,
    "tool": "shell_close",
    "result": {
        "message": "Closed shell session abc123xyz",
        "session_id": "abc123xyz"
    }
}
```

### Implementation

```python
async def shell_close_executor(params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    from ....services.shell_session_manager import get_shell_session_manager

    session_id = params["session_id"]
    db = context["db"]

    session_manager = get_shell_session_manager()
    await session_manager.close_session(session_id, db)

    return success_output(
        message=f"Closed shell session {session_id}",
        session_id=session_id
    )
```

### Usage Examples

```python
# Close session when done
{
  "tool_name": "shell_close",
  "parameters": {
    "session_id": "abc123xyz"
  }
}
```

## Session Management

### ShellSessionManager

**File**: `orchestrator/app/services/shell_session_manager.py`

Manages persistent shell sessions with WebSocket connections.

### Session Lifecycle

```
1. shell_open
   └─> Create WebSocket connection to container
   └─> Store session in database
   └─> Return session_id

2. shell_exec (multiple times)
   └─> Send command over WebSocket
   └─> Wait for output
   └─> Return output

3. shell_close
   └─> Close WebSocket
   └─> Delete session from database
```

### Session Limits

Per project limits:
- **Max concurrent sessions**: 5 (configurable)
- **Reason**: Prevent resource exhaustion

When limit is reached, agent must either:
1. Reuse existing session
2. Close old session before opening new one

### Session Cleanup

Automatic cleanup:
- Sessions timeout after 30 minutes of inactivity
- Cleanup job runs periodically
- Orphaned sessions are closed

## Working with Docker vs Kubernetes

All shell tools work transparently with both deployment modes:

### Docker Mode
- Executes via `docker exec`
- Direct container access
- Faster execution

### Kubernetes Mode
- Executes via K8s API
- Pod exec commands
- More complex but scalable

### Unified Interface

```python
from orchestrator.app.services.orchestration import get_orchestrator

orchestrator = get_orchestrator()

# Execute command (works in Docker and K8s)
result = await orchestrator.execute_command(
    user_id=user.id,
    project_id=project.id,
    container_name=None,  # Use default container
    command=["npm", "install"],
    timeout=180
)
```

## Best Practices

### 1. Use bash_exec for Simple Commands

```python
# ✅ Good: Quick one-off command
{
  "tool_name": "bash_exec",
  "parameters": {"command": "npm install"}
}
```

### 2. Use shell_open + shell_exec for Interactive Workflows

```python
# ✅ Good: Multi-step workflow with state
[
  {"tool_name": "shell_open", "parameters": {}},
  {"tool_name": "shell_exec", "parameters": {"session_id": "abc", "command": "cd src"}},
  {"tool_name": "shell_exec", "parameters": {"session_id": "abc", "command": "ls -la"}},
  {"tool_name": "shell_close", "parameters": {"session_id": "abc"}}
]
```

### 3. Always Close Sessions

```python
# ❌ Bad: Leaves session open
{
  "tool_name": "shell_open",
  "parameters": {}
}
# ... use session ...
# (never closes)

# ✅ Good: Cleans up
{
  "tool_name": "shell_open",
  "parameters": {}
}
# ... use session ...
{
  "tool_name": "shell_close",
  "parameters": {"session_id": "..."}
}
```

### 4. Adjust wait_seconds for Long Commands

```python
# ❌ Bad: Default 2s may not be enough
{
  "tool_name": "bash_exec",
  "parameters": {"command": "npm test"}  # May take >2s
}

# ✅ Good: Increase wait time
{
  "tool_name": "bash_exec",
  "parameters": {"command": "npm test", "wait_seconds": 10.0}
}
```

### 5. Check Command Output

```python
# Agent should verify success
THOUGHT: I'll run npm install and check the output for errors.

{
  "tool_name": "bash_exec",
  "parameters": {"command": "npm install"}
}

# Then verify output doesn't contain "ERR!"
```

## Common Use Cases

### Install Dependencies

```python
{
  "tool_name": "bash_exec",
  "parameters": {"command": "npm install"}
}
```

### Run Build

```python
{
  "tool_name": "bash_exec",
  "parameters": {"command": "npm run build", "wait_seconds": 5.0}
}
```

### Check File Structure

```python
{
  "tool_name": "bash_exec",
  "parameters": {"command": "ls -la src/"}
}
```

### Run Tests

```python
{
  "tool_name": "bash_exec",
  "parameters": {"command": "npm test", "wait_seconds": 10.0}
}
```

### Git Operations

```python
[
  {"tool_name": "bash_exec", "parameters": {"command": "git status"}},
  {"tool_name": "bash_exec", "parameters": {"command": "git add ."}},
  {"tool_name": "bash_exec", "parameters": {"command": "git commit -m 'Update components'"}}
]
```

## Retry Strategy

All shell tools use `@tool_retry` decorator for transient failures:

```python
@tool_retry
async def bash_exec_tool(...):
    # Retries on:
    # - ConnectionError
    # - TimeoutError
    # - IOError
    #
    # Exponential backoff: 1s → 2s → 4s
```

## Related Files

- `orchestrator/app/agent/tools/shell_ops/__init__.py` - Tool registration
- `orchestrator/app/services/shell_session_manager.py` - Session management
- `orchestrator/app/services/orchestration/base_orchestrator.py` - Orchestrator interface
- `orchestrator/app/agent/tools/output_formatter.py` - Result formatting
- `orchestrator/app/agent/tools/retry_config.py` - Retry decorator
