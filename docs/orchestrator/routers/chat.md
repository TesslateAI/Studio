# Chat Router

**File**: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/routers/chat.py` (2044 lines)

The chat router handles all AI agent interactions in Tesslate Studio. It supports both HTTP and WebSocket communication, allowing users to have conversations with AI agents that can read/write files, execute commands, and build applications.

## Overview

Chat in Tesslate Studio is project-scoped. Each project has one chat session where the user converses with an AI agent. The agent has access to the project's files and can perform actions through a set of tools.

The router supports:
- **HTTP chat**: Non-streaming, returns complete response
- **Streaming chat**: Server-Sent Events (SSE) for real-time updates
- **WebSocket chat**: Bidirectional real-time communication
- **Container-scoped agents**: Agents that work within specific containers

## Base Path

All endpoints are mounted at `/api/chat`

## Chat Management

### List Chats

```
GET /api/chat/
```

Returns all chat sessions for the authenticated user.

**Response**: Array of Chat objects

### List Standalone Sessions

```
GET /api/chat/sessions?limit=30&offset=0
```

Returns paginated standalone chat sessions for the authenticated user. Uses a single joined query with `outerjoin(Project)` to resolve project names — no N+1 queries.

**Query Parameters**:
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | int | 30 | Max sessions to return |
| `offset` | int | 0 | Pagination offset |

**Filters**: Only `origin="standalone"` sessions, excludes `status="deleted"`.

**Response**:
```json
{
  "sessions": [
    {
      "id": "uuid",
      "title": "My Chat",
      "status": "active",
      "origin": "standalone",
      "project_id": "uuid-or-null",
      "project_name": "My Project",
      "created_at": "2026-03-20T10:00:00Z",
      "updated_at": "2026-03-20T10:05:00Z"
    }
  ],
  "has_more": true
}
```

**Note**: `message_count` was removed from the response to eliminate the N+1 query pattern. Search was also removed — if needed in the future, implement with debounce on the frontend.

### Update Chat Project (Rate Limited)

```
PATCH /api/chat/{chat_id}/project
```

Connect or disconnect a project from a standalone chat session.

**Rate Limit**: 30 requests/minute per IP (via slowapi).

**Request Body**:
```json
{
  "project_id": "uuid-or-null"
}
```

**Response**:
```json
{
  "ok": true,
  "project_id": "uuid-or-null"
}
```

### Create Chat

```
POST /api/chat/
```

Creates a new chat session for a project. If a chat already exists for the project, returns the existing chat.

**Request Body**:
```json
{
  "project_id": "uuid"
}
```

**Response**: Chat object with id and project association

### Get Messages

```
GET /api/chat/{project_id}/messages
```

Returns all messages in the chat for a specific project, ordered chronologically.

**Response**:
```json
[
  {
    "id": "uuid",
    "chat_id": "uuid",
    "role": "user|assistant",
    "content": "Create a login page",
    "message_metadata": {...},
    "created_at": "2025-01-09T10:00:00Z"
  }
]
```

**Message Metadata**:

Assistant messages include metadata about agent iterations:
```json
{
  "steps": [
    {
      "iteration": 1,
      "thought": "I need to create a login component",
      "tool_calls": [
        {
          "name": "write_file",
          "arguments": {...},
          "result": {"success": true, ...}
        }
      ],
      "response_text": "I've created the login page..."
    }
  ],
  "agent_id": "uuid",
  "model": "claude-sonnet-4-5-20250929"
}
```

### Delete Messages

```
DELETE /api/chat/{project_id}/messages
```

Clears the chat history for a project. This also clears pending approvals.

**Response**:
```json
{
  "success": true,
  "message": "Deleted 25 messages",
  "deleted_count": 25
}
```

## Agent Chat - HTTP

### Non-Streaming Agent Chat

```
POST /api/chat/agent
```

Runs the agent and returns the complete response after all iterations finish. No real-time updates.

**Request Body**:
```json
{
  "project_id": "uuid",
  "message": "Add a dark mode toggle",
  "agent_id": "uuid",                 // Optional, uses default if not provided
  "container_name": "frontend",       // Optional, for container-scoped agents
  "container_directory": "app/src"    // Optional, working directory in container
}
```

**Response**:
```json
{
  "response": "I've added a dark mode toggle...",
  "iterations": [
    {
      "iteration": 1,
      "thought": "I need to add state management",
      "tool_calls": [...],
      "response_text": "Creating context..."
    }
  ],
  "total_iterations": 3,
  "agent_id": "uuid",
  "model": "claude-sonnet-4-5-20250929"
}
```

### Agent Approval

```
POST /api/chat/agent/approval
```

Handles user approval/denial for agent actions requiring permission.

**Request Body**:
```json
{
  "approval_id": "uuid",
  "approved": true,
  "reason": "Optional denial reason"
}
```

**Response**:
```json
{
  "message": "Approval recorded"
}
```

**Approval Flow**:

1. Agent requests approval via `ApprovalRequired` tool result
2. Backend creates approval record, broadcasts to WebSocket clients
3. Frontend shows approval dialog
4. User approves/denies via this endpoint
5. Agent resumes with approval decision

## Agent Chat - Streaming

### Streaming Agent Chat

```
POST /api/chat/agent/stream
```

Runs the agent with Server-Sent Events (SSE) for real-time progress updates.

**Request Body**: Same as HTTP agent chat

**Response**: StreamingResponse with `text/event-stream`

**Event Types**:

1. **Iteration Start**:
```json
{
  "type": "iteration_start",
  "iteration": 1
}
```

2. **Thought**:
```json
{
  "type": "thought",
  "content": "I need to create a new component..."
}
```

3. **Tool Call**:
```json
{
  "type": "tool_call",
  "tool_name": "write_file",
  "arguments": {
    "file_path": "src/components/Button.tsx",
    "content": "..."
  }
}
```

4. **Tool Result**:
```json
{
  "type": "tool_result",
  "tool_name": "write_file",
  "success": true,
  "result": {
    "message": "File written successfully"
  }
}
```

5. **Response Text**:
```json
{
  "type": "response_text",
  "content": "I've created the Button component..."
}
```

6. **Iteration Complete**:
```json
{
  "type": "iteration_complete",
  "iteration": 1
}
```

7. **Done**:
```json
{
  "type": "done",
  "total_iterations": 3
}
```

8. **Error**:
```json
{
  "type": "error",
  "error": "Error message"
}
```

**Client Example**:
```javascript
const eventSource = new EventSource('/api/chat/agent/stream', {
  method: 'POST',
  body: JSON.stringify({project_id, message}),
  headers: {'Content-Type': 'application/json'}
});

eventSource.onmessage = (event) => {
  const data = JSON.parse(event.data);

  switch(data.type) {
    case 'thought':
      console.log('Agent thinking:', data.content);
      break;
    case 'tool_call':
      console.log('Calling tool:', data.tool_name);
      break;
    case 'response_text':
      console.log('Agent response:', data.content);
      break;
    case 'done':
      eventSource.close();
      break;
  }
};
```

## Agent Chat - WebSocket

### WebSocket Connection

```
WebSocket: /api/chat/ws/{token}
```

Opens a bidirectional WebSocket connection for real-time agent interaction.

**Authentication**: Uses JWT token in URL path (since WebSocket doesn't support custom headers in browsers)

**Connection Setup**:
```javascript
// Get token from cookie or API
const token = getAuthToken();

// Connect to WebSocket
const ws = new WebSocket(`ws://api/chat/ws/${token}`);

ws.onopen = () => {
  console.log('Connected');

  // Send chat message
  ws.send(JSON.stringify({
    type: 'agent_message',
    project_id: 'uuid',
    message: 'Create a navbar',
    agent_id: 'uuid',  // Optional
    container_name: 'frontend',  // Optional
    container_directory: 'src'    // Optional
  }));
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  handleAgentEvent(data);
};
```

**Message Types (Client → Server)**:

1. **Agent Message**:
```json
{
  "type": "agent_message",
  "project_id": "uuid",
  "message": "Add user authentication",
  "agent_id": "uuid",
  "container_name": "backend",
  "container_directory": "src/api"
}
```

2. **Approval Response**:
```json
{
  "type": "approval_response",
  "approval_id": "uuid",
  "approved": true,
  "reason": "Optional"
}
```

**Message Types (Server → Client)**:

Same event types as streaming chat (thought, tool_call, tool_result, etc.)

**Connection Management**:

The WebSocket manager (`ConnectionManager` class) handles:
- Connection tracking per user/project
- Broadcasting to multiple clients
- Automatic reconnection on disconnect
- Message queuing during agent execution

## Helper Functions

### _build_git_context()

Builds Git repository context for the agent if the project has Git integration:

```python
git_context = await _build_git_context(project, user_id, db)
```

Returns formatted string with:
- Repository URL
- Current branch
- Uncommitted changes count
- Sync status (ahead/behind)
- Last commit info
- Auto-push status

Example output:
```
=== Git Repository ===
Repository: https://github.com/user/repo
Branch: main
Status: clean
Uncommitted Changes: 0
Remote: 2 ahead
Last Commit: Add login page (a3f2b1c8)
Auto-push: ENABLED
```

### _build_tesslate_context()

Reads `TESSLATE.md` from the project, which contains project-specific instructions for the agent:

```python
tesslate_context = await _build_tesslate_context(
    project,
    user_id,
    db,
    container_name="frontend",
    container_directory="app"
)
```

**Behavior**:
1. Tries to read `TESSLATE.md` from container (via orchestrator)
2. If not found, copies generic template from `orchestrator/template/TESSLATE.md`
3. Returns formatted context string

**TESSLATE.md Purpose**:

This file lets users customize agent behavior per-project:
- Framework-specific instructions
- Code style preferences
- Project structure conventions
- Testing requirements
- Deployment instructions

Example:
```markdown
# Tesslate Project Context

## Framework
Next.js 14 with App Router

## Code Style
- Use TypeScript strict mode
- Prefer functional components
- Use Tailwind CSS for styling

## Project Structure
- Pages in `app/`
- Components in `components/`
- API routes in `app/api/`

## Testing
- Write unit tests for utility functions
- Use Jest + React Testing Library
```

### _get_chat_history()

Fetches recent chat history for context continuity:

```python
history = await _get_chat_history(chat_id, db, limit=10)
```

Returns formatted messages with:
- User messages (original text)
- Assistant messages (thought + tool calls + response)
- Tool results as user feedback

This gives the agent context about what has been done previously, avoiding redundant work.

## Agent Factory Integration

The chat router uses the agent factory system to instantiate agents:

```python
from ..agent import create_agent_from_db_model

# Get marketplace agent or use default
if agent_id:
    marketplace_agent = await db.get(MarketplaceAgent, agent_id)
else:
    # Use default agent
    marketplace_agent = await db.scalar(
        select(MarketplaceAgent).where(
            MarketplaceAgent.slug == "default-agent"
        )
    )

# Create agent instance
agent = create_agent_from_db_model(
    db_model=marketplace_agent,
    model_adapter=model_adapter,
    user_id=current_user.id,
    project_id=project.id,
    container_name=container_name,
    container_directory=container_directory
)

# Run agent
result = await agent.run(
    user_request=message,
    context={
        "tesslate_context": tesslate_context,
        "git_context": git_context,
        "chat_history": chat_history
    }
)
```

## Container-Scoped Agents

Agents can be scoped to specific containers in multi-container projects:

**Request**:
```json
{
  "project_id": "uuid",
  "message": "Add API validation",
  "container_name": "backend",
  "container_directory": "src/api"
}
```

**Behavior**:
- Agent's file operations are scoped to the container's directory
- TESSLATE.md is read from container directory
- Tool paths are resolved relative to container directory

**Use Cases**:
- Frontend-specific agent: Works only in `frontend/` container
- Backend-specific agent: Works only in `backend/` container
- Prevents frontend agent from modifying backend code

## Context Building

Before running the agent, the router builds comprehensive context:

1. **Project Context** (TESSLATE.md): Project-specific instructions
2. **Git Context**: Repository status, branches, commits
3. **Chat History**: Recent conversation (last 10 messages)
4. **Container Info**: For multi-container projects
5. **File List**: Available files in the project

All context is passed to the agent's system prompt, helping it make informed decisions.

## WebSocket Manager

The `ConnectionManager` class handles WebSocket connections:

```python
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, chat_id: str):
        await websocket.accept()
        if chat_id not in self.active_connections:
            self.active_connections[chat_id] = []
        self.active_connections[chat_id].append(websocket)

    async def broadcast(self, message: dict, chat_id: str):
        if chat_id in self.active_connections:
            for connection in self.active_connections[chat_id]:
                await connection.send_json(message)
```

**Features**:
- Multiple clients can connect to the same chat
- All clients receive real-time updates
- Handles disconnections gracefully
- Used for file save notifications, agent updates, etc.

## Message Persistence

All chat messages are saved to the database:

```python
# Create user message
user_message = Message(
    chat_id=chat.id,
    role="user",
    content=message
)
db.add(user_message)

# Create assistant message with metadata
assistant_message = Message(
    chat_id=chat.id,
    role="assistant",
    content=final_response,
    message_metadata={
        "steps": iterations,
        "agent_id": str(agent_id),
        "model": model_name,
        "total_iterations": len(iterations)
    }
)
db.add(assistant_message)

await db.commit()
```

This allows:
- Chat history persistence across sessions
- Auditing of agent actions
- Training data collection (with user consent)
- Debugging agent behavior

## Example Workflows

### Simple Chat Interaction

1. **User sends message via WebSocket**:
   ```json
   {
     "type": "agent_message",
     "project_id": "uuid",
     "message": "Add a contact form"
   }
   ```

2. **Server builds context**:
   - Reads TESSLATE.md
   - Fetches Git status
   - Loads chat history

3. **Agent runs**:
   - Iteration 1: Analyzes request, plans approach
     - Tool: read_file("src/app/page.tsx")
     - Thought: "I'll add a contact form component"
   - Iteration 2: Creates component
     - Tool: write_file("src/components/ContactForm.tsx", content)
     - Tool: write_file("src/app/contact/page.tsx", content)
   - Iteration 3: Responds to user
     - Response: "I've created a contact form with validation..."

4. **Client receives events**:
   - `iteration_start`, `thought`, `tool_call`, `tool_result`, `response_text`, `done`

5. **Messages saved to database**:
   - User message: "Add a contact form"
   - Assistant message: "I've created a contact form..." (with metadata)

### Approval Flow

1. **Agent requests approval**:
   ```json
   {
     "type": "approval_required",
     "approval_id": "uuid",
     "action": "delete_file",
     "details": {
       "file_path": "src/old-component.tsx",
       "reason": "Replaced with new implementation"
     }
   }
   ```

2. **Frontend shows dialog**:
   "Agent wants to delete src/old-component.tsx. Allow?"

3. **User approves**:
   ```json
   {
     "type": "approval_response",
     "approval_id": "uuid",
     "approved": true
   }
   ```

4. **Agent continues execution**:
   - Tool: delete_file("src/old-component.tsx")
   - Success!

## Security Considerations

1. **Authentication**: All endpoints require valid JWT token
2. **Project Ownership**: Verified before allowing chat
3. **Container Scoping**: Prevents cross-container file access
4. **Approval System**: Dangerous operations require user confirmation
5. **Rate Limiting**: Chat messages rate-limited to prevent abuse
6. **Content Filtering**: User messages scanned for malicious content

## Performance Optimization

1. **Chat History Limit**: Only last 10 messages loaded for context
2. **Lazy Loading**: TESSLATE.md only read when needed
3. **Connection Pooling**: WebSocket connections reused
4. **Async Operations**: All I/O operations are async
5. **Streaming**: Large responses streamed, not buffered

## Related Files

- `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/agent/factory.py` - Agent instantiation
- `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/agent/stream_agent.py` - Streaming agent implementation
- `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/agent/tools/` - Agent tools (read, write, shell, etc.)
- `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/models.py` - Chat, Message models
- `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/template/TESSLATE.md` - Default project context template
