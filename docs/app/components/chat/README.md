# Chat Components

**Location**: `app/src/components/chat/`

The chat interface provides real-time communication with AI agents. Users send natural language prompts, agents execute tools, and responses stream back with visual feedback for each step.

## Components Overview

### ChatContainer.tsx

**The Main Chat Interface**: Full-featured chat UI with WebSocket connection, message history, streaming responses, agent selection, and approval workflows.

**Key Features**:
- WebSocket connection with auto-reconnect and exponential backoff
- Message history loaded from database on mount
- Streaming responses with file creation indicators
- Agent step visualization
- Tool approval requests (Ask/Allow/Plan modes)
- Desktop/mobile responsive layout
- Floating chat button on mobile
- Collapsible panel on desktop
- Smart auto-scroll (stops when user scrolls up)
- ESC-ESC to stop agent execution
- Heartbeat ping to keep connection alive

**Props**:
```typescript
interface ChatContainerProps {
  projectId: number;
  containerId?: string;            // Container ID for scoped agents
  viewContext?: 'graph' | 'builder' | 'terminal' | 'kanban';
  agents: Agent[];
  currentAgent: Agent;
  onSelectAgent: (agent: Agent) => void;
  onFileUpdate: (filePath: string, content: string) => void;
  projectFiles?: ProjectFile[];
  projectName?: string;
  className?: string;
  sidebarExpanded?: boolean;       // Affects positioning on desktop
}
```

**Usage**:
```typescript
<ChatContainer
  projectId={project.id}
  containerId={selectedContainer?.id}
  viewContext="builder"
  agents={purchasedAgents}
  currentAgent={activeAgent}
  onSelectAgent={setActiveAgent}
  onFileUpdate={(path, content) => {
    // Update file in local state
    setFiles(prev => [...prev.filter(f => f.file_path !== path), { file_path: path, content }]);
  }}
  projectFiles={files}
  projectName={project.name}
  sidebarExpanded={leftSidebarOpen}
/>
```

**Message Types**:
```typescript
interface Message {
  id: string;
  type: 'user' | 'ai' | 'approval_request';
  content: string;
  agentData?: AgentMessageData;    // For agent steps
  agentIcon?: string;
  agentAvatarUrl?: string;
  agentType?: string;
  toolCalls?: Array<{ name: string; description: string }>;
  // Approval-specific
  approvalId?: string;
  toolName?: string;
  toolParameters?: Record<string, unknown>;
  toolDescription?: string;
}
```

**WebSocket Event Handling**:
```typescript
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);

  switch (data.type) {
    case 'stream':          // Streaming text response
    case 'agent_step':      // Agent iteration with tool calls
    case 'complete':        // Task finished
    case 'file_ready':      // File created/updated
    case 'error':           // Error occurred
    case 'approval_required': // Tool needs approval
    case 'status_update':   // Project status change (hibernating/waking)
    case 'pong':            // Heartbeat response
  }
};
```

**Positioning Logic**:
```tsx
{/* Desktop: Positioned relative to sidebar */}
<div
  style={{
    left: sidebarExpanded ? 'calc(96px + 50vw)' : 'calc(24px + 50vw)'
  }}
  className="fixed bottom-6 -translate-x-1/2"
/>

{/* Mobile: Full-width bottom sheet */}
<div className="fixed bottom-0 left-0 right-0 rounded-b-none" />
```

---

### ChatMessage.tsx

**Individual Message Bubble**: Displays a single user or AI message with markdown rendering, tool calls, and action buttons.

**Props**:
```typescript
interface ChatMessageProps {
  type: 'user' | 'ai';
  content: ReactNode;         // String or JSX
  avatar?: ReactNode;         // Custom avatar
  agentIcon?: string;         // Emoji icon
  agentAvatarUrl?: string;    // Uploaded logo
  actions?: Array<{
    label: string;
    onClick: () => void;
  }>;
  toolCalls?: Array<{
    name: string;
    description: string;
  }>;
}
```

**Visual Design**:
- **User messages**: Orange gradient background (`from-[var(--primary)] to-[#ff8533]`) with white text
- **AI messages**: Surface background (`bg-[var(--surface)]`) with border
- **Avatars**: User = gradient orange circle with icon, AI = agent logo or Tesslate favicon
- **Tool calls**: Shown below message in monospace font
- **Actions**: Buttons below message for interactive responses

**Markdown Rendering**:
Uses `react-markdown` with `remark-gfm` for:
- Paragraphs with spacing
- Lists (ordered/unordered)
- Inline code (dark background) and code blocks
- Links (open in new tab)
- Headings (H1-H3)

**Usage**:
```typescript
<ChatMessage
  type="ai"
  content="Created three new files for your React app."
  agentIcon="🤖"
  toolCalls={[
    { name: 'write_file', description: 'App.tsx' },
    { name: 'write_file', description: 'index.tsx' }
  ]}
  actions={[
    { label: 'View Files', onClick: () => setActivePanel('files') }
  ]}
/>
```

---

### ChatInput.tsx

**Message Input with Controls**: Two-row layout with growing textarea (top) and agent selector + buttons (bottom). Supports slash commands, message history navigation, and file downloads.

**Props**:
```typescript
interface ChatInputProps {
  agents: Agent[];
  currentAgent: Agent;
  onSelectAgent: (agent: Agent) => void;
  onSendMessage: (message: string) => void;
  projectFiles?: ProjectFile[];
  projectName?: string;
  placeholder?: string;
  disabled?: boolean;
  isExecuting?: boolean;
  onStop?: () => void;
  onClearHistory?: () => void;
  isExpanded?: boolean;
  editMode?: EditMode;
  onModeChange?: (mode: EditMode) => void;
  onPlanMode?: () => void;
}
```

**Features**:
1. **Auto-resizing Textarea**: Grows with content up to 200px max height
2. **Slash Commands**: Type `/` to see available commands (`/clear`, `/plan`)
3. **Message History**: Arrow up/down to navigate previous messages
4. **Keyboard Shortcuts**:
   - `Enter` = Send message
   - `Shift+Enter` = New line
   - `Ctrl/Cmd+Enter` = Send (alternative)
5. **Edit Mode Indicator**: Shows Ask/Allow/Plan mode with border color
6. **Settings Dropdown**: Download project, clear history
7. **Send/Stop Button**: Changes based on execution state

**Layout**:
```tsx
<div className="flex flex-col">
  {/* Row 1: Textarea */}
  <textarea className="resize-none overflow-hidden" />

  {/* Row 2: Controls */}
  <div className="flex items-center gap-2">
    <AgentSelector />
    <div className="flex-1" />  {/* Spacer */}
    <EditModeStatus />
    <button>Settings</button>
    <button>/</button>  {/* Slash commands */}
    <button>Send/Stop</button>
  </div>
</div>
```

**Download Project Feature**:
Uses JSZip to create a .zip file:
```typescript
const downloadProject = async () => {
  const zip = new JSZip();
  projectFiles.forEach(file => {
    zip.file(file.file_path, file.content);
  });
  const blob = await zip.generateAsync({ type: 'blob' });
  // Trigger download
};
```

---

### AgentSelector.tsx

**Agent Dropdown Menu**: Displays current agent with icon and provides dropdown to switch agents. Includes marketplace CTA.

**Props**:
```typescript
interface AgentSelectorProps {
  agents: Agent[];
  currentAgent: Agent;
  onSelectAgent: (agent: Agent) => void;
}
```

**Features**:
- Dropdown triggered by click (closes on outside click)
- Current agent shown with icon and name
- Purchased agents listed with "Active" indicator
- Marketplace CTA at bottom with gradient background
- Responsive: Shows icon only on mobile, icon + name on desktop

**Visual Design**:
```tsx
{/* Current agent button */}
<button className="bg-[var(--text)]/10 hover:bg-[var(--text)]/20 rounded-xl">
  <span>{currentAgent.icon}</span>
  <span className="hidden md:inline">{currentAgent.name}</span>
</button>

{/* Dropdown menu */}
<div className="bg-[rgba(20,20,20,0.98)] backdrop-blur-xl rounded-xl">
  {agents.map(agent => (
    <button className={agent.id === currentAgent.id && 'bg-[rgba(255,107,0,0.2)]'}>
      {agent.icon} {agent.name}
    </button>
  ))}

  {/* Marketplace CTA */}
  <div className="bg-gradient-to-r from-orange-500/20 to-orange-600/20 border border-orange-500/30">
    <button onClick={() => navigate('/marketplace')}>
      Browse Marketplace
    </button>
  </div>
</div>
```

---

### ApprovalRequestCard.tsx

**Tool Approval UI**: Yellow card prompting user to approve/deny a tool execution (for Ask mode or dangerous operations).

**Props**:
```typescript
interface ApprovalRequestCardProps {
  approvalId: string;
  toolName: string;
  toolParameters: Record<string, unknown>;
  toolDescription: string;
  onRespond: (approvalId: string, response: 'allow_once' | 'allow_all' | 'stop', toolName: string) => void;
}
```

**Visual Design**:
- Yellow background with warning icon
- Tool name in monospace
- Three action buttons: Allow Once (green), Allow All Edits (orange), Stop (red)
- Special handling for write tools: "Allow All" switches to Allow mode

**Usage**:
```typescript
<ApprovalRequestCard
  approvalId="approval-123"
  toolName="write_file"
  toolParameters={{ file_path: 'App.tsx', content: '...' }}
  toolDescription="Write file to src/App.tsx"
  onRespond={(id, response, tool) => {
    if (response === 'allow_all' && WRITE_TOOLS.has(tool)) {
      setEditMode('allow');  // Switch mode
    }
  }}
/>
```

---

### EditModeStatus.tsx

**Edit Mode Indicator**: Three-state toggle showing Ask/Allow/Plan mode. Not exported in index, used internally by ChatInput.

**Modes**:
- **Ask**: Agent asks permission before file edits (gray border)
- **Allow**: Agent can edit files freely (orange border)
- **Plan**: Agent generates plan without executing (green border)

---

### TypingIndicator.tsx

**Animated Dots**: Three bouncing dots to indicate agent is thinking.

**Usage**:
```typescript
{isThinking && <TypingIndicator />}
```

---

### ToolDropdown.tsx

**Tool Selection UI**: Allows user to enable/disable specific tools for an agent. (Exact usage context unclear from codebase.)

---

### UsageRibbon.tsx

**Usage Stats Banner**: Shows current usage stats (tokens, API calls) at top of chat. Used to warn users approaching limits.

## State Flow

### Message Lifecycle

1. **User types message** → ChatInput
2. **Send button clicked** → ChatContainer.handleSendMessage()
3. **Message sent via WebSocket** → Backend
4. **Agent processes request** → Backend executes tools
5. **Stream events received** → ChatContainer.ws.onmessage
6. **Messages updated in state** → setMessages()
7. **UI re-renders** → ChatMessage/AgentMessage components display

### Agent Step Flow

```
User: "Create a login page"
  ↓
Agent Step 1: [Thought: I'll create the components]
  Tool: write_file(LoginForm.tsx)
  Tool: write_file(styles.css)
  ↓
Agent Step 2: [Thought: Now add routing]
  Tool: patch_file(App.tsx)
  ↓
Complete: "Created login page with form and styling"
```

### Approval Flow

```
User: "Delete all files"  (Ask mode)
  ↓
Agent: approval_required { tool: delete_file, file: App.tsx }
  ↓
ApprovalRequestCard rendered
  ↓
User clicks: "Allow All Edits"
  ↓
Edit mode switches to Allow
  ↓
Agent continues execution
```

## WebSocket Protocol

### Client → Server Messages

```json
{
  "message": "Create a React app",
  "project_id": 123,
  "container_id": "container-abc",
  "agent_id": 5,
  "edit_mode": "allow",
  "view_context": "builder"
}
```

### Server → Client Messages

**Stream Event**:
```json
{
  "type": "stream",
  "content": "Creating your app..."
}
```

**Agent Step Event**:
```json
{
  "type": "agent_step",
  "data": {
    "iteration": 1,
    "thought": "I'll create the main component",
    "tool_calls": [
      {
        "name": "write_file",
        "parameters": { "file_path": "App.tsx", "content": "..." }
      }
    ],
    "tool_results": [
      { "success": true, "message": "File created" }
    ]
  }
}
```

**Complete Event**:
```json
{
  "type": "complete",
  "data": {
    "final_response": "Your React app is ready!",
    "completion_reason": "complete"
  }
}
```

**File Ready Event**:
```json
{
  "type": "file_ready",
  "file_path": "src/App.tsx",
  "content": "..."
}
```

**Approval Required Event**:
```json
{
  "type": "approval_required",
  "data": {
    "approval_id": "approval-xyz",
    "tool_name": "delete_file",
    "tool_parameters": { "file_path": "important.tsx" },
    "tool_description": "Delete file important.tsx"
  }
}
```

## Styling Patterns

### 60-30-10 Color Usage

**ChatContainer**:
- 60%: Dark background (`bg-[var(--bg-dark)]`)
- 30%: Surface borders (`border-[var(--surface)]`)
- 10%: Orange glow effects (radial gradients)

**ChatMessage**:
- User: 10% orange gradient (accent)
- AI: 30% surface background (secondary)
- Avatar: 10% orange for user, 30% surface for AI

### Responsive Behavior

**Desktop (≥768px)**:
- Floating chat container positioned relative to sidebar
- Hover to expand width slightly
- Click outside to collapse
- Auto-collapses when clicking iframe/preview

**Mobile (<768px)**:
- Bottom sheet that slides up
- Floating button in bottom-right when collapsed
- Full-width when expanded
- Manual close button in header

## Performance Considerations

### Message Rendering

- Use `animatedMessagesRef` to track which messages have animated (prevent re-animation on re-render)
- Only animate new messages (`!animatedMessagesRef.current.has(message.id)`)
- Skip animation during history load (`!isLoadingHistory`)

### Auto-Scroll Logic

```typescript
// Don't auto-scroll if user has manually scrolled up
const isUserScrollingRef = useRef(false);

// Check if near bottom
const isNearBottom = scrollHeight - scrollTop - clientHeight < 100;
isUserScrollingRef.current = !isNearBottom;

// Only auto-scroll if user hasn't scrolled up
if (!isUserScrollingRef.current || isNearBottom) {
  messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
}
```

### WebSocket Reconnection

Exponential backoff prevents connection spam:
```typescript
const delay = Math.min(baseDelay * Math.pow(2, attempts), 30000);
reconnectTimer = setTimeout(connect, delay);
```

## Common Tasks

### Adding a New Agent

1. Create agent in backend (Library page)
2. Agent appears in `agents` prop from parent
3. ChatContainer automatically includes it in AgentSelector
4. User selects it → `onSelectAgent` callback
5. Current agent stored in local state

### Adding a New Message Type

1. Extend `Message` interface in ChatContainer.tsx
2. Add WebSocket handler in `ws.onmessage`
3. Add rendering logic in ChatContainer's `messages.map()`
4. Create dedicated component if complex (like ApprovalRequestCard)

### Customizing Agent Responses

Responses are markdown strings from backend. Customize rendering in ChatMessage's `ReactMarkdown` component:
```typescript
<ReactMarkdown
  components={{
    code: ({ children }) => <code className="custom-style">{children}</code>
  }}
>
  {content}
</ReactMarkdown>
```

---

**Next**: See CLAUDE.md for agent-specific patterns and debugging tips.
