# Tool Approval System

**File**: `orchestrator/app/agent/tools/approval_manager.py`

The approval system enables "Ask Before Edit" mode where dangerous tool operations require user approval before execution.

## Overview

When edit mode is set to "ask", dangerous tools (file modifications, shell commands) cannot execute until the user approves. The approval manager tracks which tool types have been approved per session.

## Architecture

```
Agent requests dangerous tool
    ↓
ToolRegistry checks edit mode
    ↓
Is edit_mode == "ask"?
    ├─ No → Execute immediately
    └─ Yes → Check approval status
        ├─ Already approved → Execute
        └─ Not approved → Request approval
            ↓
        ApprovalManager creates request
            ↓
        Frontend displays approval UI
            ↓
        User chooses:
        ├─ Allow Once → Execute this time only
        ├─ Allow All → Approve this tool type for session
        └─ Stop → Cancel execution
```

## Dangerous Tools

Tools that require approval in "ask" mode:

```python
DANGEROUS_TOOLS = {
    'write_file',    # File modifications
    'patch_file',
    'multi_edit',
    'bash_exec',     # Shell operations
    'shell_exec',
    'shell_open',
    'web_fetch'      # Web operations (can leak data)
}
```

Safe tools always execute:
- `read_file`
- `get_project_info`
- `todo_read`
- `todo_write`

## ApprovalRequest Class

Represents a pending approval request:

```python
class ApprovalRequest:
    def __init__(self, approval_id: str, tool_name: str, parameters: Dict, session_id: str):
        self.approval_id = approval_id
        self.tool_name = tool_name
        self.parameters = parameters
        self.session_id = session_id
        self.event = asyncio.Event()  # Async wait mechanism
        self.response: Optional[str] = None  # 'allow_once', 'allow_all', 'stop'
```

### Fields

- **approval_id**: Unique ID for this request (UUID)
- **tool_name**: Name of tool requiring approval (e.g., "write_file")
- **parameters**: Tool parameters for user to review
- **session_id**: Chat session ID (for per-session approvals)
- **event**: AsyncIO event for waiting on user response
- **response**: User's choice (set when they respond)

## ApprovalManager Class

Manages approvals across all chat sessions.

### Initialization

```python
class ApprovalManager:
    def __init__(self):
        # session_id -> set of approved tool names
        self._approved_tools: Dict[str, Set[str]] = {}

        # approval_id -> ApprovalRequest
        self._pending_approvals: Dict[str, ApprovalRequest] = {}
```

### is_tool_approved()

Check if a tool type has been approved for the session:

```python
def is_tool_approved(self, session_id: str, tool_name: str) -> bool:
    """
    Check if a tool type has been approved for the session.

    Returns:
        True if tool was approved with "Allow All" for this session
    """
    if session_id not in self._approved_tools:
        return False
    return tool_name in self._approved_tools[session_id]
```

**Usage**:
```python
approval_mgr = get_approval_manager()

if approval_mgr.is_tool_approved("chat-123", "write_file"):
    # Already approved - execute directly
    result = await tool.executor(params, context)
else:
    # Need approval - request it
    approval_id, request = await approval_mgr.request_approval(...)
```

### approve_tool_for_session()

Mark a tool type as approved for the entire session:

```python
def approve_tool_for_session(self, session_id: str, tool_name: str):
    """
    Mark a tool type as approved for the entire session.

    Called when user clicks "Allow All" for a specific tool.
    """
    if session_id not in self._approved_tools:
        self._approved_tools[session_id] = set()

    self._approved_tools[session_id].add(tool_name)
    logger.info(f"[ApprovalManager] Approved {tool_name} for session {session_id}")
```

**Effect**: All future calls to this tool type in this session will execute without approval.

### clear_session_approvals()

Clear all approvals for a session:

```python
def clear_session_approvals(self, session_id: str):
    """
    Clear all approvals for a session.

    Called when /clear is used or session ends.
    """
    if session_id in self._approved_tools:
        del self._approved_tools[session_id]
        logger.info(f"[ApprovalManager] Cleared approvals for session {session_id}")
```

**When to call**:
- User types `/clear` in chat
- Chat session ends
- User wants to revoke approvals

### request_approval()

Request user approval for a tool execution:

```python
async def request_approval(
    self,
    tool_name: str,
    parameters: Dict,
    session_id: str
) -> tuple[str, ApprovalRequest]:
    """
    Request user approval for a tool execution.

    This function:
    1. Creates an approval request
    2. Returns the approval_id and request object
    3. Caller waits on request.event for user response

    Returns:
        Tuple of (approval_id, request)
    """
    approval_id = str(uuid4())
    request = ApprovalRequest(approval_id, tool_name, parameters, session_id)

    self._pending_approvals[approval_id] = request
    logger.info(f"[ApprovalManager] Created approval request {approval_id} for {tool_name}")

    return approval_id, request
```

**Usage Pattern**:
```python
# 1. Request approval
approval_id, request = await approval_mgr.request_approval(
    tool_name="write_file",
    parameters={"file_path": "src/App.jsx", "content": "..."},
    session_id="chat-123"
)

# 2. Emit event to frontend
yield {
    'type': 'approval_required',
    'data': {
        'approval_id': approval_id,
        'tool_name': "write_file",
        'tool_parameters': {"file_path": "src/App.jsx", "content": "..."},
        'tool_description': "Write file operation"
    }
}

# 3. Wait for user response
await request.event.wait()

# 4. Handle response
if request.response == 'stop':
    # User cancelled - stop execution
    return
elif request.response in ['allow_once', 'allow_all']:
    # User approved - execute tool
    result = await tool.executor(params, context)
```

### respond_to_approval()

Process user's approval response:

```python
def respond_to_approval(self, approval_id: str, response: str):
    """
    Process user's approval response.

    Args:
        approval_id: ID of the approval request
        response: User's choice ('allow_once', 'allow_all', 'stop')
    """
    if approval_id not in self._pending_approvals:
        logger.warning(f"[ApprovalManager] Unknown approval_id: {approval_id}")
        return

    request = self._pending_approvals[approval_id]
    request.response = response

    # If "Allow All", mark this tool as approved for the session
    if response == 'allow_all':
        self.approve_tool_for_session(request.session_id, request.tool_name)

    # Signal the waiting coroutine
    request.event.set()

    logger.info(f"[ApprovalManager] Received response '{response}' for {approval_id}")

    # Clean up
    del self._pending_approvals[approval_id]
```

**Called by**: Frontend sends approval response via WebSocket/HTTP

### get_pending_request()

Get a pending approval request by ID:

```python
def get_pending_request(self, approval_id: str) -> Optional[ApprovalRequest]:
    """Get a pending approval request by ID."""
    return self._pending_approvals.get(approval_id)
```

## Global Instance

Singleton pattern:

```python
_approval_manager: Optional[ApprovalManager] = None

def get_approval_manager() -> ApprovalManager:
    """Get or create the global approval manager instance."""
    global _approval_manager
    if _approval_manager is None:
        _approval_manager = ApprovalManager()
    return _approval_manager
```

## Integration with ToolRegistry

The approval flow is handled automatically in `ToolRegistry.execute()`:

```python
async def execute(
    self,
    tool_name: str,
    parameters: Dict[str, Any],
    context: Dict[str, Any]
) -> Dict[str, Any]:
    # ... validation ...

    edit_mode = context.get('edit_mode', 'ask')
    is_dangerous = tool_name in DANGEROUS_TOOLS

    # Ask mode: check approval
    skip_approval = context.get('skip_approval_check', False)
    if edit_mode == 'ask' and is_dangerous and not skip_approval:
        from .approval_manager import get_approval_manager
        approval_mgr = get_approval_manager()

        session_id = context.get('chat_id', 'default')

        # Check if already approved
        if not approval_mgr.is_tool_approved(session_id, tool_name):
            # Need approval
            logger.info(f"[ASK MODE] Approval required for {tool_name}")
            return {
                "approval_required": True,
                "tool": tool_name,
                "parameters": parameters,
                "session_id": session_id
            }
        else:
            logger.info(f"[ASK MODE] Tool {tool_name} already approved")

    # Execute tool
    result = await tool.executor(parameters, context)
    return result
```

## Agent Integration

Agents handle approval requests in their execution loop:

```python
# IterativeAgent/ReActAgent execution loop
tool_results = await self._execute_tool_calls(tool_calls, context)

# Check for approval requests
for idx, result in enumerate(tool_results):
    if result.get("approval_required"):
        from .tools.approval_manager import get_approval_manager
        approval_mgr = get_approval_manager()

        # Create approval request
        approval_id, request = await approval_mgr.request_approval(
            tool_name=result["tool"],
            parameters=result["parameters"],
            session_id=result["session_id"]
        )

        # Emit approval_required event
        yield {
            'type': 'approval_required',
            'data': {
                'approval_id': approval_id,
                'tool_name': result["tool"],
                'tool_parameters': result["parameters"],
                'tool_description': f"Execute {result['tool']} operation"
            }
        }

        logger.info(f"[Agent] Waiting for approval {approval_id}")

        # Wait for user response
        await request.event.wait()

        logger.info(f"[Agent] Received response: {request.response}")

        # Handle response
        if request.response == 'stop':
            # User cancelled - terminate agent execution
            yield {
                'type': 'complete',
                'data': {
                    'final_response': "Execution stopped by user.",
                    'completion_reason': 'user_stopped'
                }
            }
            return  # Terminate

        else:
            # allow_once or allow_all - retry execution
            approved_context = {**context, 'skip_approval_check': True}
            tool_results[idx] = await self.tools.execute(
                tool_name=tool_calls[idx].name,
                parameters=tool_calls[idx].parameters,
                context=approved_context
            )
```

## Frontend Integration

The frontend displays approval UI when it receives `approval_required` event:

### Approval UI

```typescript
// Event from agent
{
  type: 'approval_required',
  data: {
    approval_id: 'abc-123-def-456',
    tool_name: 'write_file',
    tool_parameters: {
      file_path: 'src/App.jsx',
      content: '...'
    },
    tool_description: 'Write file operation'
  }
}

// Display modal/popup with:
// - Tool name: "write_file"
// - Parameters preview
// - Three buttons:
//   - "Allow Once" → send 'allow_once'
//   - "Allow All write_file" → send 'allow_all'
//   - "Stop" → send 'stop'
```

### Sending Response

```typescript
// Send approval response
await fetch('/api/approval/respond', {
  method: 'POST',
  body: JSON.stringify({
    approval_id: 'abc-123-def-456',
    response: 'allow_all'  // or 'allow_once' or 'stop'
  })
});

// Backend calls:
approval_mgr.respond_to_approval(approval_id, response)
```

## Complete Flow Example

### 1. Agent Requests Tool

```python
# Agent wants to write file
{
  "tool_name": "write_file",
  "parameters": {
    "file_path": "src/App.jsx",
    "content": "import React..."
  }
}
```

### 2. ToolRegistry Checks Approval

```python
# In ToolRegistry.execute()
if edit_mode == 'ask' and tool_name == 'write_file':
    if not approval_mgr.is_tool_approved(session_id, "write_file"):
        return {
            "approval_required": True,
            "tool": "write_file",
            "parameters": {...},
            "session_id": "chat-123"
        }
```

### 3. Agent Emits Approval Event

```python
yield {
    'type': 'approval_required',
    'data': {
        'approval_id': 'abc-123',
        'tool_name': 'write_file',
        'tool_parameters': {...}
    }
}
```

### 4. Frontend Shows UI

User sees modal:
```
━━━━━━━━━━━━━━━━━━━━━━━━━━
 Approval Required

 write_file wants to:
 - Write to 'src/App.jsx'

 [Allow Once]  [Allow All]  [Stop]
━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### 5. User Responds

User clicks "Allow All".

Frontend sends:
```json
{
  "approval_id": "abc-123",
  "response": "allow_all"
}
```

### 6. ApprovalManager Processes Response

```python
approval_mgr.respond_to_approval("abc-123", "allow_all")

# Marks write_file as approved for session
# Sets request.event so agent continues
```

### 7. Agent Retries Tool

```python
# Agent continues execution
approved_context = {**context, 'skip_approval_check': True}
result = await tools.execute(
    tool_name="write_file",
    parameters={...},
    context=approved_context
)

# Tool executes successfully
# Future write_file calls in this session don't need approval
```

## Best Practices

### 1. Clear Approvals on Session End

```python
# When chat session ends
approval_mgr = get_approval_manager()
approval_mgr.clear_session_approvals(session_id)
```

### 2. Handle User Cancellation Gracefully

```python
if request.response == 'stop':
    # Don't just continue - inform user and stop
    yield {
        'type': 'complete',
        'data': {
            'final_response': "Task cancelled by user.",
            'completion_reason': 'user_stopped'
        }
    }
    return  # Terminate agent
```

### 3. Show Parameter Preview in UI

```python
# Frontend should show what the tool will do
tool_parameters: {
  file_path: 'src/App.jsx',
  content: 'import React...' (show first 100 chars)
}
```

### 4. Use Per-Session Approvals

```python
# Don't use global approvals - they persist across chats
# Always scope to session_id
approval_mgr.is_tool_approved(session_id, tool_name)
```

## Related Files

- `orchestrator/app/agent/tools/registry.py` - Approval check logic
- `orchestrator/app/agent/iterative_agent.py` - Approval handling in agent loop
- `orchestrator/app/agent/react_agent.py` - Approval handling in agent loop
- `orchestrator/app/routers/chat.py` - Chat endpoint that uses agents
- `app/src/components/chat/ApprovalModal.tsx` - Frontend approval UI (example)
