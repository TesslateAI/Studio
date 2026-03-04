# Chat API

The Chat API handles AI agent communication, including streaming responses via Server-Sent Events (SSE) and tool approval flows.

**File**: `app/src/lib/api.ts`

## Chat API (chatApi)

### Basic Operations

```typescript
export const chatApi = {
  // Create new chat session for project
  create: async (projectId?: string) => {
    const response = await api.post('/api/chat/', { project_id: projectId });
    return response.data;
  },

  // Get all user's chat sessions
  getAll: async () => {
    const response = await api.get('/api/chat/');
    return response.data;
  },

  // Get messages for a project
  getProjectMessages: async (projectId: string) => {
    const response = await api.get(`/api/chat/${projectId}/messages`);
    return response.data;
  },

  // Clear all messages for a project
  clearProjectMessages: async (projectId: string) => {
    const response = await api.delete(`/api/chat/${projectId}/messages`);
    return response.data;
  },
};
```

### Non-Streaming Agent Messages

For simple agent requests without streaming:

```typescript
export const chatApi = {
  sendAgentMessage: async (request: AgentChatRequest): Promise<AgentChatResponse> => {
    const response = await api.post('/api/chat/agent', request);
    return response.data;
  },
};
```

### Streaming Agent Messages (SSE)

The primary method for agent communication uses Server-Sent Events for real-time streaming:

```typescript
export const chatApi = {
  sendAgentMessageStreaming: async (
    request: AgentChatRequest,
    onEvent: (event: { type: string; data: Record<string, unknown> }) => void,
    signal?: AbortSignal
  ): Promise<void> => {
    const response = await fetch(`${API_URL}/api/chat/agent/stream`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify(request),
      credentials: 'include', // Include cookies for OAuth authentication
      signal, // Pass abort signal for cancellation
    });

    // Handle 401 by redirecting to login
    if (response.status === 401) {
      localStorage.removeItem('token');
      window.location.href = '/login';
      throw new Error('Authentication required');
    }

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error('Response body is not readable');
    }

    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();

        if (done) break;

        // Decode chunk and add to buffer
        buffer += decoder.decode(value, { stream: true });

        // Process complete lines (SSE format: "data: {JSON}\n\n")
        const lines = buffer.split('\n\n');
        buffer = lines.pop() || ''; // Keep incomplete line in buffer

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const jsonStr = line.slice(6); // Remove "data: " prefix
            try {
              const event = JSON.parse(jsonStr);
              onEvent(event);
            } catch (e) {
              console.error('Failed to parse SSE event:', e, jsonStr);
            }
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
  },
};
```

### SSE Event Format

Events follow the Server-Sent Events format:

```
data: {"type": "event_type", "data": {...}}\n\n
```

Common event types:
- `text_delta` - Streaming text content
- `tool_call` - Agent calling a tool
- `tool_result` - Tool execution result
- `approval_request` - Requires user approval
- `done` - Stream complete
- `error` - Error occurred

### Tool Approval Flow

When an agent needs approval for dangerous operations:

```typescript
export const chatApi = {
  sendApprovalResponse: async (
    approvalId: string,
    response: 'allow_once' | 'allow_all' | 'stop'
  ): Promise<void> => {
    await api.post('/api/chat/agent/approval', {
      approval_id: approvalId,
      response: response
    });
  },
};
```

Approval response options:
- `allow_once` - Allow this specific operation
- `allow_all` - Allow all similar operations (session-scoped)
- `stop` - Reject and stop the agent

## Type Definitions

From `app/src/types/agent.ts`:

```typescript
interface AgentChatRequest {
  project_id: string;
  message: string;
  agent_id?: string;      // Optional specific agent
  context?: {             // Optional context
    files?: string[];
    current_file?: string;
  };
}

interface AgentChatResponse {
  message: string;
  tool_calls?: ToolCall[];
  approval_request?: ApprovalRequest;
}
```

## Usage Examples

### Basic Streaming Chat

```typescript
const controller = new AbortController();

try {
  await chatApi.sendAgentMessageStreaming(
    {
      project_id: projectId,
      message: 'Add a dark mode toggle to the header',
    },
    (event) => {
      switch (event.type) {
        case 'text_delta':
          appendToMessage(event.data.content);
          break;
        case 'tool_call':
          showToolExecution(event.data);
          break;
        case 'approval_request':
          showApprovalDialog(event.data);
          break;
        case 'done':
          markComplete();
          break;
        case 'error':
          showError(event.data.message);
          break;
      }
    },
    controller.signal
  );
} catch (error) {
  if (error.name === 'AbortError') {
    console.log('Request cancelled');
  }
}

// To cancel the stream:
controller.abort();
```

### Handling Approvals

```typescript
// When approval_request event received
const handleApproval = async (approvalData: ApprovalRequest) => {
  const { approval_id, tool_name, description } = approvalData;

  // Show dialog to user
  const userResponse = await showApprovalDialog({
    tool: tool_name,
    description,
  });

  // Send response
  await chatApi.sendApprovalResponse(approval_id, userResponse);
};
```

### Loading Message History

```typescript
// Get previous messages
const messages = await chatApi.getProjectMessages(projectId);

// Display in UI
messages.forEach(msg => {
  renderMessage(msg);
});
```

### Clearing Chat History

```typescript
// Clear all messages for project
await chatApi.clearProjectMessages(projectId);

// Refresh UI
setMessages([]);
```

## WebSocket Alternative

For persistent connections, use the WebSocket helper:

```typescript
import { createWebSocket } from './api';

const ws = createWebSocket(token);

ws.onopen = () => {
  console.log('WebSocket connected');
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  handleMessage(data);
};

ws.onerror = (error) => {
  console.error('WebSocket error:', error);
};

ws.onclose = () => {
  console.log('WebSocket closed');
};

// Send message
ws.send(JSON.stringify({
  type: 'message',
  content: 'Hello',
  project_id: projectId,
}));
```

## Error Handling

```typescript
try {
  await chatApi.sendAgentMessageStreaming(request, onEvent, signal);
} catch (error) {
  if (error.name === 'AbortError') {
    // User cancelled - not an error
    return;
  }

  if (error.message === 'Authentication required') {
    // Already redirected to login
    return;
  }

  // Show error to user
  toast.error(`Chat error: ${error.message}`);
}
```
