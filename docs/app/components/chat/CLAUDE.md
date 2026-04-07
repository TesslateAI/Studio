# Chat Components - AI Agent Context

## Quick Reference

**When modifying chat components**, remember:
- WebSocket connection is managed in ChatContainer useEffect
- Messages are stored in local state and loaded from DB on mount
- Agent steps are rendered separately from final responses
- Approval requests are separate message types
- Mobile/desktop have different UI patterns
- **Multi-session chat**: Users can have multiple chat sessions per project, managed via ChatSessionPopover
- **Real-time agent visibility**: Agent execution events stream via Redis → WebSocket, not just SSE
- **Progressive step loading**: Steps may come from AgentStep table (metadata flag `steps_table: True`)

## Common Modifications

### Adding a New WebSocket Event Type

1. **Define the event structure** (coordinate with backend):
```typescript
// Server sends:
{
  "type": "new_event_type",
  "data": { /* event data */ }
}
```

2. **Add handler in ChatContainer.tsx**:
```typescript
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);

  // Add new case
  if (data.type === 'new_event_type') {
    // Handle the event
    handleNewEvent(data.data);
  }
};
```

3. **Update UI accordingly** (add message, show notification, update state)

### Customizing Message Appearance

**To change user/AI message colors**:
```typescript
// ChatMessage.tsx
const isUser = type === 'user';

<div className={`
  ${isUser
    ? 'bg-gradient-to-br from-[var(--primary)] to-[#ff8533]'  // Orange gradient
    : 'bg-[var(--surface)]'                                    // Dark surface
  }
`} />
```

**To add custom message types**:
```typescript
// 1. Extend Message interface in ChatContainer
interface Message {
  type: 'user' | 'ai' | 'approval_request' | 'system';  // Add 'system'
  // ...
}

// 2. Handle in render
{message.type === 'system' && (
  <div className="system-message">{message.content}</div>
)}
```

### Built-in Slash Commands

| Command | Description | Behavior |
|---------|-------------|----------|
| `/clear` | Clear chat history | Deletes all messages in the session |
| `/undo` | Undo last exchange | Removes the last user+assistant message pair via `POST /api/chat/{chat_id}/undo` |
| `/retry` | Retry last message | Performs `/undo` then re-sends the removed user message |

`/undo` and `/retry` are handled in ChatContainer (`handleUndo`, `handleRetry`) and use `chatApi.undoLastExchange(chatId)`. The endpoint returns `last_user_message` so `/retry` can re-send it. Both are disabled while the agent is executing or the chat status is `running`/`waiting_approval`.

Installed skills also appear as slash commands (e.g., `/docker-dev`).

### Command Palette UX

ChatInput renders a dropdown when the user types `/`. The dropdown supports:

- **Keyboard navigation**: ArrowUp/ArrowDown to move, Tab to autocomplete, Enter to execute, Escape to dismiss
- **Categorized sections**: "Commands" (built-in) and "Skills" (installed marketplace skills)
- **Command icons**: Each command/skill displays an icon
- **Chip mode**: When the typed text exactly matches a command (e.g., `/clear`), the input shows a chip badge and Enter executes it immediately

### Adding Slash Commands

1. **Add command definition** in ChatInput.tsx:
```typescript
const slashCommands = [
  { command: '/clear', description: 'Clear chat history' },
  { command: '/help', description: 'Show help' },  // New command
];
```

2. **Add execution handler**:
```typescript
const executeCommand = (cmd: string) => {
  if (cmd === '/help') {
    // Show help modal or add help message to chat
    setMessages(prev => [...prev, {
      id: `cmd-${Date.now()}`,
      type: 'system',
      content: 'Available commands: /clear, /help, /plan'
    }]);
  }
};
```

### Debugging WebSocket Issues

**Check connection state**:
```typescript
console.log('[WS] State:', ws.readyState);
// 0 = CONNECTING, 1 = OPEN, 2 = CLOSING, 3 = CLOSED
```

**Log all messages**:
```typescript
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('[WS] Received:', data.type, data);
  // ... existing handlers
};
```

**Test reconnection**:
```typescript
// Manually close to trigger reconnect
ws.close();
```

### Fixing Auto-Scroll Issues

**Problem**: Chat keeps scrolling even when user scrolls up

**Solution**: Check `isUserScrollingRef` logic:
```typescript
const handleScroll = () => {
  const { scrollTop, scrollHeight, clientHeight } = container;
  const isNearBottom = scrollHeight - scrollTop - clientHeight < 100;
  isUserScrollingRef.current = !isNearBottom;
};

// Only auto-scroll if user hasn't scrolled up
if (!isUserScrollingRef.current || isNearBottom || isNewUserMessage) {
  messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
}
```

### Adding Message Actions

**Example: Add "Copy" button to AI messages**:
```typescript
// ChatContainer.tsx
const messages = [
  {
    id: 'msg-1',
    type: 'ai',
    content: 'Here is your code...',
    actions: [
      {
        label: 'Copy',
        onClick: () => {
          navigator.clipboard.writeText(message.content);
          toast.success('Copied!');
        }
      }
    ]
  }
];

// ChatMessage.tsx already renders actions, no changes needed
```

## Multi-Session Chat

### Components

| Component | File | Purpose |
|-----------|------|---------|
| `ChatSessionPopover` | `components/chat/ChatSessionPopover.tsx` | Dropdown to switch between chat sessions |
| `ChatSessionModal` | `components/chat/ChatSessionModal.tsx` | Full modal for session management (create, rename, delete) |

### Session Model

Each chat session is a `Chat` record with:
- `title`: User-editable session name
- `origin`: Where it was created ("browser", "api", "slack", "cli")
- `status`: Lifecycle state ("active", "running", "completed")
- `updated_at`: Auto-refreshed on new messages

### Switching Sessions

```typescript
// ChatContainer manages active session
const [activeChatId, setActiveChatId] = useState<string | null>(null);

// ChatSessionPopover shows session list
<ChatSessionPopover
  projectId={projectId}
  activeChatId={activeChatId}
  onSessionChange={setActiveChatId}
/>
```

### API Endpoints (lib/api.ts)

```typescript
// List sessions for a project
chatApi.getSessions(projectId): Promise<ChatSession[]>

// List standalone sessions (paginated)
chatApi.getUserSessions({ limit: 30, offset: 0 }): Promise<{ sessions: ChatSession[], has_more: boolean }>

// Create new session
chatApi.createSession(projectId, title?): Promise<ChatSession>

// Delete session
chatApi.deleteSession(sessionId): Promise<void>
```

### Standalone Chat Page Hooks

| Hook | File | Purpose |
|------|------|---------|
| `useAgentChat` | `hooks/useAgentChat.ts` | Agent message streaming with `overrideChatId` for race-free session creation |
| `useChatSessions` | `hooks/useChatSessions.ts` | Session CRUD with optimistic temp-ID creation, pagination (limit=30) |

**Key patterns:**
- `sendMessage(message, overrideChatId?)` — pass explicit chatId to avoid stale-closure race conditions
- `createSession()` — optimistic: inserts temp-ID session immediately, swaps for server ID on resolve, rolls back on error
- No search — removed to eliminate N+1 backend query; re-add with debounce if needed later
- Always loads messages via `GET /session/{chatId}/messages` (no standalone/project branching)

## Real-Time Agent Visibility

Agent execution events now flow through Redis Streams → WebSocket instead of only SSE:

### Event Flow
```
Worker Pod → Redis Stream → API Pod (pubsub subscriber) → WebSocket → Frontend
```

### WebSocket Event Types (New)
```typescript
// Agent execution started (from another source like API)
{ type: "agent_task_started", task_id: string, chat_id: string }

// Agent step completed
{ type: "agent_step", step: AgentStepData }

// Agent execution completed
{ type: "agent_task_completed", task_id: string, response: string }

// Agent execution failed
{ type: "agent_task_error", task_id: string, error: string }
```

### Progressive Step Loading
When loading chat history, messages from worker execution have `metadata.steps_table: true`. The frontend should load steps from the AgentStep API instead of inline metadata:

```typescript
// Check if steps are in separate table
if (message.metadata?.steps_table) {
  const steps = await chatApi.getMessageSteps(messageId);
  // Render steps from API response
} else {
  // Render steps from inline metadata (legacy)
}
```

## Approval Flow Deep Dive

### How Approval Works

1. **Agent requests approval** (Ask mode or dangerous tool):
```json
{
  "type": "approval_required",
  "data": {
    "approval_id": "approval-abc",
    "tool_name": "delete_file",
    "tool_parameters": { "file_path": "src/App.tsx" }
  }
}
```

2. **UI shows approval card**:
```typescript
const approvalMessage: Message = {
  id: `approval-${Date.now()}`,
  type: 'approval_request',
  approvalId: data.data.approval_id,
  toolName: data.data.tool_name,
  // ...
};
setMessages(prev => [...prev, approvalMessage]);
```

3. **User responds** (Allow Once / Allow All / Stop):
```typescript
const handleApprovalResponse = async (approvalId, response, toolName) => {
  // Send response via WebSocket or HTTP
  ws.send(JSON.stringify({
    type: 'approval_response',
    approval_id: approvalId,
    response: response  // 'allow_once' | 'allow_all' | 'stop'
  }));

  // Remove approval message from chat
  setMessages(prev => prev.filter(msg => msg.approvalId !== approvalId));

  // If "Allow All Edits" for write tools, switch mode
  if (response === 'allow_all' && WRITE_TOOLS.has(toolName)) {
    setEditMode('allow');
  }
};
```

4. **Agent continues** (if approved) or stops (if denied)

### Testing Approval Flow

Manually trigger approval:
```typescript
// In development, add test button:
<button onClick={() => {
  setMessages(prev => [...prev, {
    id: 'test-approval',
    type: 'approval_request',
    approvalId: 'test-123',
    toolName: 'write_file',
    toolParameters: { file_path: 'test.txt' },
    toolDescription: 'Test approval request'
  }]);
}}>Test Approval</button>
```

## Edit Modes Explained

### Ask Mode (default)
- Agent asks before file writes
- Shows ApprovalRequestCard for each file operation
- Safe for beginners

### Allow Mode
- Agent can write files freely
- No approval requests for file operations
- Faster iteration

### Plan Mode
- Agent generates plan without executing
- Returns list of steps as markdown
- User can review before execution

**Switching modes**:
```typescript
// ChatInput has EditModeStatus component
<EditModeStatus
  mode={editMode}
  onModeChange={setEditMode}
/>
```

## Unmount Protection (isMountedRef)

ChatContainer uses an `isMountedRef` to guard against React state updates from orphaned SSE and WebSocket callbacks after the component unmounts (e.g., when the user navigates away mid-stream).

### Pattern

```typescript
const isMountedRef = useRef(true);

useEffect(() => {
  isMountedRef.current = true;
  return () => {
    isMountedRef.current = false;
  };
}, []);
```

### Where Guards Are Applied

1. **SSE event callback** (in `sendAgentMessage`): The streaming response handler checks `isMountedRef.current` before updating messages, agent steps, or execution state.

2. **WebSocket onmessage handler**: Checks `isMountedRef.current` alongside the `isCleaningUp` flag before processing incoming messages.

```typescript
// SSE callback guard
(event) => {
  if (!isMountedRef.current) return;
  // ... process event, update state
};

// WebSocket guard
ws.onmessage = (event) => {
  if (isCleaningUp || !isMountedRef.current) return;
  // ... process message
};
```

### Why This Is Needed

When a user navigates away from the builder while an agent is streaming:
- The SSE fetch is NOT aborted (only ESC key triggers abort)
- The backend continues executing and saves results to DB
- SSE callbacks still fire, trying to call `setMessages()`, `setAgentExecuting()`, etc.
- Without the guard, React logs warnings about state updates on unmounted components
- On return, `loadChatHistory` reloads completed messages from DB

## Performance Optimization Tips

### Reduce Message Re-renders

**Problem**: Every new message re-renders all previous messages

**Solution**: Use `React.memo` on ChatMessage:
```typescript
export const ChatMessage = memo(({ type, content, ... }: Props) => {
  // Component logic
}, (prevProps, nextProps) => {
  // Only re-render if content changed
  return prevProps.content === nextProps.content &&
         prevProps.type === nextProps.type;
});
```

### Virtualize Long Chat History

If chat has 1000+ messages, use react-window:
```typescript
import { FixedSizeList } from 'react-window';

<FixedSizeList
  height={600}
  itemCount={messages.length}
  itemSize={100}
>
  {({ index, style }) => (
    <div style={style}>
      <ChatMessage {...messages[index]} />
    </div>
  )}
</FixedSizeList>
```

### Debounce WebSocket Messages

If receiving many rapid updates:
```typescript
const debouncedUpdate = debounce((content: string) => {
  setCurrentStream(content);
}, 50);

ws.onmessage = (event) => {
  if (data.type === 'stream') {
    debouncedUpdate(currentStream + data.content);
  }
};
```

## Mobile Considerations

### Touch vs Click Events

Mobile users may see double-trigger on buttons:
```typescript
// Use onTouchEnd instead of onClick for mobile
<button
  onClick={handleClick}
  onTouchEnd={(e) => {
    e.preventDefault();
    handleClick();
  }}
/>
```

### Keyboard Handling on Mobile

Mobile keyboards may not fire `keydown` events correctly:
```typescript
// Fallback: Add explicit send button for mobile
const isMobile = window.innerWidth < 768;

<button
  type="button"
  onClick={sendMessage}
  className={isMobile ? 'visible' : 'hidden md:visible'}
>
  Send
</button>
```

### Viewport Height Issues

Mobile browsers have dynamic viewport due to address bar:
```typescript
// Use 100dvh (dynamic viewport height) instead of 100vh
className="max-md:max-h-[90dvh]"
```

## Testing Scenarios

### Test WebSocket Reconnection

1. Open chat
2. Open DevTools → Network
3. Find WebSocket connection
4. Right-click → Close connection
5. Verify: Chat shows reconnecting message
6. Verify: After delay, connection restored
7. Verify: Messages still work

### Test Message History Persistence

1. Send several messages
2. Refresh page
3. Verify: Messages reload from database
4. Verify: Scroll position resets to bottom
5. Verify: No duplicate messages

### Test Agent Switching

1. Select Agent A
2. Send message "Hello"
3. Verify: Response uses Agent A
4. Switch to Agent B
5. Send message "Hi"
6. Verify: Response uses Agent B
7. Verify: Chat history preserved

### Test Approval Flow

1. Enable Ask mode
2. Send message "Create a file"
3. Verify: Approval card appears
4. Click "Allow Once"
5. Verify: File created, approval card removed
6. Send another file creation request
7. Verify: Another approval card (not auto-approved)

### Test Mobile Layout

1. Open DevTools → Device toolbar (Cmd/Ctrl+Shift+M)
2. Select iPhone 12 Pro
3. Verify: Chat button in bottom-right
4. Click chat button
5. Verify: Bottom sheet slides up
6. Verify: Header shows close button
7. Tap backdrop
8. Verify: Chat closes

## Troubleshooting

### Chat Not Receiving Messages

**Check**:
1. WebSocket connection state: `ws.readyState === 1` (OPEN)
2. Token valid: `localStorage.getItem('token')`
3. Project ID correct: `projectId` prop matches URL
4. Backend WebSocket URL: `createWebSocket()` uses correct endpoint

**Debug**:
```typescript
ws.onopen = () => console.log('[WS] Connected');
ws.onerror = (err) => console.error('[WS] Error:', err);
ws.onclose = () => console.log('[WS] Closed');
ws.onmessage = (evt) => console.log('[WS] Message:', evt.data);
```

### Messages Not Persisting

**Check**:
1. `chatApi.getProjectMessages()` called on mount
2. Database has messages: Run SQL query `SELECT * FROM messages WHERE project_id = ?`
3. Message metadata stored correctly

**Debug**:
```typescript
useEffect(() => {
  console.log('[CHAT] Loading history...');
  chatApi.getProjectMessages(projectId.toString()).then(msgs => {
    console.log('[CHAT] Loaded messages:', msgs.length);
    setMessages(expandedMessages);
  });
}, [projectId]);
```

### Agent Not Responding

**Check**:
1. Agent selected: `currentAgent.backendId` defined
2. Agent active: `currentAgent.active === true`
3. Backend receives request: Check backend logs
4. WebSocket still open: `ws.readyState === 1`

**Debug**:
```typescript
const sendMessage = () => {
  console.log('[CHAT] Sending:', {
    message,
    project_id: projectId,
    agent_id: currentAgent.backendId,
    edit_mode: editMode
  });
  ws.send(JSON.stringify({ /* ... */ }));
};
```

---

**Remember**: Chat components are the main user interaction point. Changes here affect the entire user experience. Test thoroughly on both desktop and mobile.
