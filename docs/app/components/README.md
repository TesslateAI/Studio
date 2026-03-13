# Tesslate Studio Components

**Location**: `app/src/components/`

The React component library that powers Tesslate Studio's user interface. These components are built with React 19, TypeScript, and modern patterns including hooks, composition, and optimized rendering.

## Component Organization

### By Feature Area

```
components/
├── chat/                 # AI chat interface (ChatContainer, ChatMessage, AgentSelector)
├── editor/              # Code editor (Monaco integration, file browser)
├── panels/              # Side panels (Git, Architecture, Assets, Settings)
├── graph/               # XYFlow graph (ContainerNode, BrowserPreviewNode, edges)
├── billing/             # Subscription & payment UI (plans, usage, deploy buttons)
├── modals/              # Dialog modals (CreateProject, Deployment, GitCommit)
├── ui/                  # Shared UI primitives (buttons, dropdowns, tooltips)
├── marketplace/         # Marketplace cards and ratings
├── git/                 # Git-specific components
└── edges/               # XYFlow custom edges (Database, HttpApi, Cache)
```

### Root Components

**Major features** (`app/src/components/`):
- **AgentMessage.tsx** - Displays AI agent execution steps and responses
- **AgentStep.tsx** - Individual agent step visualization with tool calls
- **CodeEditor.tsx** - Monaco-based code editor with file tree
- **GraphCanvas.tsx** - XYFlow canvas wrapper for architecture visualization
- **BrowserPreview.tsx** - Embedded preview iframe with navigation
- **ContainerNode.tsx** - Graph node for containers
- **BrowserPreviewNode.tsx** - Graph node with resizable browser
- **Preview.tsx** - Standalone preview component
- **ToolCallDisplay.tsx** - Visualization of agent tool invocations
- **ToolManagement.tsx** - Agent tool configuration UI
- **ServiceConfigForm.tsx** - Form for editing `.tesslate/config.json` (apps, infrastructure, env vars)
- **PreviewPortPicker.tsx** - Dropdown to switch browser preview between multiple containers
- **DashboardLayout.tsx** - Main dashboard wrapper
- **Layout.tsx** - Application shell
- **DottedSurface.tsx** - Animated background pattern
- **Walkthrough.tsx** - Onboarding tour
- **MobileWarning.tsx** - Mobile device notice

## Component Patterns

### 1. Hooks Composition

All components use React hooks for state and effects:

```typescript
// ChatContainer.tsx
const [messages, setMessages] = useState<Message[]>([]);
const [isStreaming, setIsStreaming] = useState(false);
const wsRef = useRef<WebSocket | null>(null);

useEffect(() => {
  // WebSocket connection with auto-reconnect
  const connectWebSocket = () => { /* ... */ };
  connectWebSocket();
  return () => ws?.close();
}, [projectId]);
```

### 2. Memoization for Performance

High-frequency render components use `memo` and custom comparison:

```typescript
// ContainerNode.tsx
const arePropsEqual = (prev: Props, next: Props) => {
  return (
    prev.id === next.id &&
    prev.data.name === next.data.name &&
    prev.data.status === next.data.status
  );
};

export const ContainerNode = memo(ContainerNodeComponent, arePropsEqual);
```

### 3. Event-Driven Architecture

WebSocket and SSE for real-time updates:

```typescript
// ChatContainer.tsx
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);

  if (data.type === 'stream') {
    setCurrentStream(prev => prev + data.content);
  } else if (data.type === 'agent_step') {
    // Add step as new message
  } else if (data.type === 'complete') {
    // Finalize response
  }
};
```

### 4. Controlled Inputs

Form inputs managed via state with validation:

```typescript
// ChatInput.tsx
const [message, setMessage] = useState('');
const [messageHistory, setMessageHistory] = useState<string[]>([]);

const handleKeyDown = (e: KeyboardEvent) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    sendMessage();
  } else if (e.key === 'ArrowUp') {
    // Navigate history
  }
};
```

### 5. Theme-Aware Styling

CSS variables for dynamic theming:

```typescript
// CodeEditor.tsx
<div className="bg-[var(--surface)] text-[var(--text)]">
  <Editor theme={theme === 'dark' ? 'vs-dark' : 'vs'} />
</div>
```

## Shared UI Components

### `/ui` Directory

Low-level reusable primitives:

- **button.tsx** - Base button component
- **textarea.tsx** - Auto-resizing textarea
- **Dropdown.tsx** - Generic dropdown menu
- **Tabs.tsx** - Tab navigation
- **Tooltip.tsx** - Hover tooltips
- **Toast.tsx** - Toast notifications (via react-hot-toast)
- **StatusBadge.tsx** - Colored status indicators
- **TaskProgress.tsx** - Progress bars
- **ToggleSwitch.tsx** - Toggle switches
- **Breadcrumbs.tsx** - Breadcrumb navigation
- **NavigationSidebar.tsx** - Collapsible sidebar
- **FloatingSidebar.tsx** - Overlay sidebar
- **FloatingPanel.tsx** - Draggable panels
- **GlassContainer.tsx** - Glassmorphism wrapper
- **MarkerPill.tsx** - Colored marker badges
- **MarkerEditor.tsx** - Marker color picker
- **MarkerPalette.tsx** - Predefined color palette
- **MobileMenu.tsx** - Mobile navigation
- **AgentTag.tsx** - Agent identifier badge
- **ProjectCard.tsx** - Project list card
- **MarketplaceCard.tsx** - Marketplace listing card
- **TechStackIcons.tsx** - Tech stack icons
- **HelpModal.tsx** - Help/documentation modal
- **ruixen-moon-chat.tsx** - Custom chat UI variant

## Props and Composition

### Example: ChatContainer

**Full Props Interface**:
```typescript
interface ChatContainerProps {
  projectId: number;
  containerId?: string;            // Container-scoped agents
  viewContext?: 'graph' | 'builder' | 'terminal' | 'kanban';
  agents: Agent[];
  currentAgent: Agent;
  onSelectAgent: (agent: Agent) => void;
  onFileUpdate: (filePath: string, content: string) => void;
  projectFiles?: ProjectFile[];
  projectName?: string;
  className?: string;
  sidebarExpanded?: boolean;       // Adjust positioning
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
  onFileUpdate={handleFileUpdate}
  projectFiles={files}
  projectName={project.name}
  sidebarExpanded={leftSidebarOpen}
/>
```

### Example: CodeEditor

**Props**:
```typescript
interface CodeEditorProps {
  projectId: number;
  files: FileData[];
  onFileUpdate: (filePath: string, content: string) => void;
}
```

**Features**:
- File tree rendering with nested folders
- Monaco editor with syntax highlighting
- Auto-language detection by extension
- Collapsible sidebar
- Line/character count

## Accessibility Patterns

### Keyboard Navigation

```typescript
// ChatInput.tsx - Arrow keys for history
if (e.key === 'ArrowUp') {
  setHistoryIndex(Math.max(0, historyIndex - 1));
}

// Escape to stop agent execution
if (e.key === 'Escape' && agentExecuting) {
  escPressCountRef.current += 1;
  if (escPressCountRef.current >= 2) {
    stopAgentExecution();
  }
}
```

### ARIA Labels

```typescript
<button
  aria-label="Open chat"
  title="Open chat"
  className="..."
>
  <ChatIcon />
</button>
```

### Focus Management

```typescript
<input
  autoFocus
  ref={inputRef}
  onFocus={handleInputFocus}
/>
```

## Performance Optimizations

### 1. Lazy Loading

```typescript
const AgentDebugPanel = lazy(() => import('./AgentDebugPanel'));
```

### 2. Virtualization

File trees and long lists use windowing:
```typescript
// DirectoryTree.tsx (inside AssetsPanel)
// Renders only visible nodes
```

### 3. Debounced Updates

```typescript
// CodeEditor.tsx
const handleEditorChange = debounce((value: string) => {
  if (selectedFile && value !== undefined) {
    onFileUpdate(selectedFile, value);
  }
}, 300);
```

### 4. Smart Re-rendering

```typescript
// GraphCanvas.tsx - Custom comparison prevents re-renders
const arePropsEqual = (prev: Props, next: Props): boolean => {
  return (
    prev.nodes === next.nodes &&
    prev.edges === next.edges &&
    prev.theme === next.theme
  );
};
```

## State Management

### Local State (useState)

Used for component-specific UI state:
- Form inputs
- Modal open/closed
- Dropdown expanded
- Loading states

### Context (useContext)

Used for cross-cutting concerns:
- Theme (dark/light)
- User authentication
- Subscription status

### URL State (useSearchParams)

Used for shareable state:
- Selected tab/panel
- Filter values
- Search queries

### Server State (React Query patterns)

Used for data fetching:
```typescript
const [projects, setProjects] = useState<Project[]>([]);

useEffect(() => {
  projectsApi.list().then(setProjects);
}, []);
```

## Component Testing

### Unit Tests

Test component logic in isolation:
```typescript
// ChatInput.test.tsx
test('sends message on Enter key', () => {
  const onSend = jest.fn();
  render(<ChatInput onSendMessage={onSend} />);

  fireEvent.keyDown(input, { key: 'Enter' });
  expect(onSend).toHaveBeenCalled();
});
```

### Integration Tests

Test component interactions:
```typescript
// ChatContainer.test.tsx
test('agent step updates appear in chat', async () => {
  render(<ChatContainer projectId={1} />);

  // Simulate WebSocket message
  act(() => {
    mockWs.onmessage({ data: JSON.stringify({ type: 'agent_step' }) });
  });

  expect(screen.getByText(/Tool call/)).toBeInTheDocument();
});
```

## Common Gotchas

### 1. Monaco Editor Memory Leaks

Always dispose editor on unmount:
```typescript
useEffect(() => {
  return () => {
    editorRef.current?.dispose();
  };
}, []);
```

### 2. XYFlow Performance

Disable expensive features when not needed:
```typescript
<ReactFlow
  autoPanOnNodeDrag={false}  // Major perf gain
  elevateNodesOnSelect={false}
  snapToGrid={false}
/>
```

### 3. WebSocket Reconnection

Implement exponential backoff:
```typescript
const reconnectWithBackoff = () => {
  const delay = Math.min(baseDelay * Math.pow(2, attempts), 30000);
  setTimeout(connect, delay);
};
```

### 4. Iframe Security

Use sandbox attribute:
```typescript
<iframe
  sandbox="allow-scripts allow-same-origin allow-forms"
  src={previewUrl}
/>
```

## File Structure Summary

```
app/src/components/
├── README.md (you are here)
├── CLAUDE.md (agent context)
├── chat/
│   ├── README.md
│   ├── CLAUDE.md
│   ├── ChatContainer.tsx        # Main chat UI with WebSocket
│   ├── ChatMessage.tsx          # Single message bubble
│   ├── ChatInput.tsx            # Input with agent selector
│   ├── AgentSelector.tsx        # Agent dropdown
│   ├── ApprovalRequestCard.tsx  # Tool approval UI
│   ├── EditModeStatus.tsx       # Ask/Allow/Plan mode
│   ├── TypingIndicator.tsx      # Animated dots
│   ├── ToolDropdown.tsx         # Tool selection
│   └── UsageRibbon.tsx          # Usage stats banner
├── editor/
│   ├── README.md
│   ├── CLAUDE.md
│   └── CodeEditor.tsx           # Monaco + file tree
├── panels/
│   ├── README.md
│   ├── CLAUDE.md
│   ├── ArchitecturePanel.tsx    # Mermaid/PlantUML diagrams
│   ├── GitHubPanel.tsx          # Git operations
│   ├── AssetsPanel.tsx          # File upload/management
│   ├── KanbanPanel.tsx          # Task board
│   ├── TerminalPanel.tsx        # Shell access
│   ├── NotesPanel.tsx           # Markdown notes
│   ├── DeploymentsPanel.tsx     # Deployment history
│   ├── SettingsPanel.tsx        # Project settings
│   ├── MarketplacePanel.tsx     # Agent store
│   └── assets/
│       ├── AssetComponents.tsx
│       ├── AssetUploadZone.tsx
│       └── DirectoryTree.tsx
├── graph/
│   ├── README.md
│   ├── CLAUDE.md
│   ├── GraphCanvas.tsx          # XYFlow wrapper
│   ├── ContainerNode.tsx        # Container card node
│   └── BrowserPreviewNode.tsx   # Resizable preview node
├── billing/
│   ├── README.md
│   ├── CLAUDE.md
│   ├── SubscriptionStatus.tsx   # Current plan display
│   ├── SubscriptionPlans.tsx    # Upgrade UI
│   ├── BillingDashboard.tsx     # Full billing page
│   ├── UsageDashboard.tsx       # Usage charts
│   ├── CreditsPurchaseModal.tsx # Buy credits
│   ├── TransactionHistory.tsx   # Payment history
│   ├── UpgradeModal.tsx         # Upgrade flow
│   ├── DeployButton.tsx         # Deploy with usage check
│   ├── ProjectLimitBanner.tsx   # Limit warnings
│   └── AgentPurchaseButton.tsx  # Marketplace purchase
├── modals/
│   ├── README.md
│   ├── CLAUDE.md
│   ├── CreateProjectModal.tsx   # New project dialog
│   ├── DeploymentModal.tsx      # External deploy flow
│   ├── GitCommitDialog.tsx      # Commit + push UI
│   ├── GitHubConnectModal.tsx   # OAuth connection
│   ├── GitHubImportModal.tsx    # Import from GitHub
│   ├── RepoImportModal/         # Multi-provider import
│   ├── ConfirmDialog.tsx        # Generic confirmation
│   ├── FeedbackModal.tsx        # User feedback
│   ├── CreateFeedbackModal.tsx  # Bug reports
│   └── ProviderConnectModal.tsx # Inline OAuth for deployment providers
└── edges/
    ├── DatabaseEdge.tsx         # Green edge for DB
    ├── HttpApiEdge.tsx          # Orange edge for REST
    ├── CacheEdge.tsx            # Blue edge for cache
    ├── EnvInjectionEdge.tsx     # Dotted env edge
    └── BrowserPreviewEdge.tsx   # Browser connection edge
```

---

**Next Steps:**
- Read subdirectory READMEs for detailed component documentation
- Check CLAUDE.md files for agent-specific context and patterns
- Review `app/src/types/` for TypeScript interfaces
