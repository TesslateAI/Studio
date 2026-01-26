# Frontend Development Context

**Purpose**: This context provides guidance for developing and modifying the Tesslate Studio React frontend.

## When to Load This Context

Load this context when:
- Modifying UI components or pages
- Adding new routes or navigation
- Implementing new chat features or agent interactions
- Working on WebSocket streaming or real-time updates
- Debugging frontend issues
- Adding new API integrations
- Implementing new marketplace features
- Working on billing/subscription UI

## Key Files

### Entry Points
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/main.tsx`**: App bootstrap, PostHog provider
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/App.tsx`**: Router, auth guards, toast configuration

### Core API Layer
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/lib/api.ts`**: Axios instance, auth interceptors, all API methods
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/lib/git-api.ts`**: Git operations API
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/lib/github-api.ts`**: GitHub-specific API
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/lib/git-providers-api.ts`**: Unified git provider API (GH/GL/BB)

### Type Definitions
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/types/agent.ts`**: Agent, message, and chat types
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/types/billing.ts`**: Subscription and payment types
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/types/git.ts`**: Git operation types
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/types/assets.ts`**: File and asset types
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/types/theme.ts`**: Theme types + runtime validation

### Contexts
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/contexts/AuthContext.tsx`**: Centralized auth state
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/contexts/CommandContext.tsx`**: Command palette dispatch

### Hooks
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/hooks/useCancellableRequest.ts`**: AbortController-based request hook
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/hooks/useAuth.ts`**: Auth status and user info

### SEO
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/lib/seo-manager.ts`**: SEO tag registry singleton
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/components/SEO.tsx`**: Declarative SEO component

### Command System & Keyboard Shortcuts
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/components/CommandPalette.tsx`**: Cmd+K command menu
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/components/KeyboardShortcutsModal.tsx`**: Shortcuts help (? key)
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/lib/keyboard-registry.ts`**: Shortcut definitions (50+ shortcuts)

### UI Components
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/components/ui/HelpButton.tsx`**: Help button with "?" key trigger
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/components/ui/HelpMenu.tsx`**: Comprehensive help menu with submenus
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/components/ui/UserDropdown.tsx`**: User account dropdown menu
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/components/ui/Tooltip.tsx`**: Accessible tooltip component

### Analytics
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/lib/posthog.ts`**: PostHog analytics with DNT respect, singleton pattern

### Layouts
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/layouts/SettingsLayout.tsx`**: Two-column settings layout
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/layouts/MarketplaceLayout.tsx`**: Marketplace page wrapper
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/layouts/PublicMarketplaceHeader.tsx`**: Marketplace header
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/layouts/PublicMarketplaceFooter.tsx`**: Marketplace footer

### Settings Pages
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/pages/settings/ProfileSettings.tsx`**: User profile, avatar, bio
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/pages/settings/PreferencesSettings.tsx`**: Theme, diagram model
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/pages/settings/SecuritySettings.tsx`**: Password, 2FA, sessions
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/pages/settings/DeploymentSettings.tsx`**: Provider credentials
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/pages/settings/ApiKeysSettings.tsx`**: API key management
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/pages/settings/BillingSettings.tsx`**: Subscription, invoices

### Marketplace Pages
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/pages/MarketplaceBrowse.tsx`**: Browse with filtering
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/pages/MarketplaceCategory.tsx`**: Category-specific browse

### Settings Components
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/components/settings/SettingsSection.tsx`**: Container with title
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/components/settings/SettingsGroup.tsx`**: Related items group
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/components/settings/SettingsItem.tsx`**: Single setting row
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/components/settings/SettingsSidebar.tsx`**: Navigation links

### Utilities
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/utils/fileEvents.ts`**: Event system for file changes
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/utils/autoLayout.ts`**: Graph auto-layout with Dagre algorithm
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/lib/utils.ts`**: Utility functions (classNames, etc.)
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/theme/ThemeContext.tsx`**: Theme state management

## Related Contexts

When working on specific features, also load:

### Core Systems (NEW)
- **`docs/app/contexts/CLAUDE.md`**: AuthContext, CommandContext, MarketplaceAuthContext documentation
- **`docs/app/hooks/CLAUDE.md`**: Custom hooks (useCancellableRequest, useAuth, useTask, useReferralTracking)
- **`docs/app/seo/CLAUDE.md`**: SEOManager and SEO component patterns
- **`docs/app/types/CLAUDE.md`**: Theme types and runtime validation
- **`docs/app/state/CLAUDE.md`**: Theme context and state management
- **`docs/app/keyboard-shortcuts/CLAUDE.md`**: Command palette and keyboard shortcuts system
- **`docs/app/layouts/CLAUDE.md`**: SettingsLayout and MarketplaceLayout patterns

### Pages
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/docs/app/pages/`**: Detailed page documentation
  - `dashboard.md`: Project list and creation
  - `project-builder.md`: Main editor interface
  - `project-graph.md`: Architecture visualization
  - `marketplace.md`: Agent/base browsing and purchase
  - `marketplace-browse.md`: Browse and category pages with filtering
  - `settings.md`: Modular settings architecture (6 pages)
  - `billing.md`: Subscription management
  - `auth.md`: Login/register/OAuth

### Components
For specific UI work, reference the actual component files:
- **Chat**: `app/src/components/chat/`
- **Panels**: `app/src/components/panels/`
- **Modals**: `app/src/components/modals/`
- **Billing**: `app/src/components/billing/`
- **Marketplace**: `app/src/components/marketplace/` (includes `SkeletonCard` for loading states)
- **Settings**: `app/src/components/settings/` (see `docs/app/components/settings.md`)
- **Command**: `app/src/components/CommandPalette.tsx`, `KeyboardShortcutsModal.tsx`
- **UI**: `app/src/components/ui/` (HelpButton, HelpMenu, UserDropdown, Tooltip)
- **SEO**: `app/src/components/SEO.tsx`

### Backend Integration
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/docs/orchestrator/routers/`**: API endpoint documentation
- **`c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/schemas.py`**: Request/response schemas

## Common Patterns

### 1. API Calls

**Pattern**: All API calls go through typed methods in `lib/api.ts`

```typescript
import { projectsApi, chatApi, marketplaceApi } from '../lib/api';

// Projects
const projects = await projectsApi.getAll();
const project = await projectsApi.getBySlug('my-app-k3x8n2');
await projectsApi.create({ name: 'New App', base_id: null });
await projectsApi.update(projectSlug, { name: 'Updated Name' });
await projectsApi.delete(projectSlug);

// Chat
const messages = await chatApi.getHistory(projectId);
const response = await chatApi.sendMessage(projectId, {
  content: 'Create a login page',
  agent_id: agentId,
});

// Marketplace
const agents = await marketplaceApi.getAgents();
const agent = await marketplaceApi.getAgentBySlug('advanced-fullstack');
await marketplaceApi.purchaseAgent(agentSlug);
```

**Authentication**: The axios instance automatically adds:
- JWT Bearer token from `localStorage.getItem('token')` for regular auth
- CSRF token for cookie-based OAuth auth
- Redirects to `/login` on 401 (except task polling)

### 2. WebSocket Streaming

**Pattern**: Use `createWebSocket()` for agent streaming

```typescript
import { createWebSocket } from '../lib/api';

const ws = useRef<WebSocket | null>(null);

useEffect(() => {
  ws.current = createWebSocket();

  ws.current.addEventListener('message', (event) => {
    const data = JSON.parse(event.data);

    switch (data.type) {
      case 'agent_response':
        // Streaming text token
        setCurrentStream(prev => prev + data.content);
        break;

      case 'agent_tool_start':
        // Tool execution starting
        console.log('Tool:', data.tool_name);
        break;

      case 'agent_tool_result':
        // Tool completed
        console.log('Result:', data.result);
        break;

      case 'agent_stream_end':
        // Stream complete
        setIsStreaming(false);
        break;

      case 'agent_error':
        // Error occurred
        toast.error(data.error);
        break;
    }
  });

  return () => ws.current?.close();
}, []);

// Send message
const sendMessage = (message: string) => {
  ws.current?.send(JSON.stringify({
    type: 'chat_message',
    project_id: projectId,
    content: message,
    agent_id: currentAgent.backendId,
    container_id: containerId, // Optional: for container-scoped agents
    view_context: 'builder',    // Optional: for view-scoped tools
  }));
};
```

### 3. File Events

**Pattern**: Use custom event system for file changes

```typescript
import { fileEvents } from '../utils/fileEvents';

// Emit file change (e.g., after saving in editor)
fileEvents.emit('fileUpdated', {
  filePath: 'src/App.tsx',
  content: newContent
});

// Listen for file changes (e.g., in file tree)
useEffect(() => {
  const handler = (detail: { filePath: string, content: string }) => {
    // Update UI to reflect change
    refreshFileTree();
  };

  fileEvents.on('fileUpdated', handler);
  return () => fileEvents.off('fileUpdated', handler);
}, []);
```

### 4. Theme Management

**Pattern**: Use `useTheme` hook for dark/light mode

```typescript
import { useTheme } from '../theme/ThemeContext';
import { Sun, Moon } from '@phosphor-icons/react';

function MyComponent() {
  const { theme, toggleTheme } = useTheme();

  return (
    <div className={theme === 'dark' ? 'dark-mode' : 'light-mode'}>
      <button onClick={toggleTheme}>
        {theme === 'dark' ? <Sun size={20} /> : <Moon size={20} />}
      </button>
    </div>
  );
}
```

Theme is persisted to localStorage and applies CSS custom properties defined in `theme/variables.css`.

### 5. Route Protection

**Pattern**: Use `PrivateRoute` wrapper for authenticated routes

```typescript
// Already implemented in App.tsx
<Route
  path="/dashboard"
  element={
    <PrivateRoute>
      <Dashboard />
    </PrivateRoute>
  }
/>
```

`PrivateRoute` checks both:
1. JWT token in localStorage (regular login)
2. Cookie-based authentication (OAuth login)

### 6. Task Polling

**Pattern**: Use `useTask` hook for long-running operations

```typescript
import { useTask } from '../hooks/useTask';

function MyComponent() {
  const { task, isPolling, startPolling, stopPolling } = useTask();

  const createProject = async () => {
    const response = await projectsApi.create({ name: 'New App' });

    // Start polling for project setup task
    startPolling(response.task_id);
  };

  useEffect(() => {
    if (task?.status === 'completed') {
      toast.success('Project created!');
      navigate(`/project/${task.result.slug}`);
    } else if (task?.status === 'failed') {
      toast.error(`Failed: ${task.error}`);
    }
  }, [task]);

  return (
    <button onClick={createProject} disabled={isPolling}>
      {isPolling ? 'Creating...' : 'Create Project'}
    </button>
  );
}
```

### 7. Toast Notifications

**Pattern**: Use `react-hot-toast` for user feedback

```typescript
import toast from 'react-hot-toast';

// Success
toast.success('Project created successfully!');

// Error
toast.error('Failed to save file');

// Loading (returns ID for dismissal)
const toastId = toast.loading('Deploying...');

// Update loading toast
toast.success('Deployed!', { id: toastId });

// Custom duration
toast.success('Done!', { duration: 5000 });

// With action
toast.success(
  <div>
    File saved! <button onClick={openFile}>View</button>
  </div>,
  { duration: 10000 }
);
```

### 8. Modal Management

**Pattern**: Use state to control modal visibility

```typescript
const [showModal, setShowModal] = useState(false);
const [modalData, setModalData] = useState<SomeType | null>(null);

// Open modal with data
const openModal = (data: SomeType) => {
  setModalData(data);
  setShowModal(true);
};

// Close modal
const closeModal = () => {
  setShowModal(false);
  setModalData(null);
};

return (
  <>
    <button onClick={() => openModal(someData)}>Open</button>
    {showModal && (
      <MyModal
        data={modalData}
        onClose={closeModal}
        onSave={(updatedData) => {
          // Handle save
          closeModal();
        }}
      />
    )}
  </>
);
```

### 9. Monaco Editor Integration

**Pattern**: Use `CodeEditor` component wrapper

```typescript
import CodeEditor from '../components/CodeEditor';

function MyEditor() {
  const [content, setContent] = useState('');
  const [filePath, setFilePath] = useState('src/App.tsx');

  const handleSave = async (updatedContent: string) => {
    // Save to backend
    await projectsApi.updateFile(projectSlug, filePath, updatedContent);

    // Emit file event
    fileEvents.emit('fileUpdated', { filePath, content: updatedContent });

    toast.success('File saved!');
  };

  return (
    <CodeEditor
      filePath={filePath}
      content={content}
      onChange={setContent}
      onSave={handleSave}
      readOnly={false}
    />
  );
}
```

### 10. XYFlow Graph Integration

**Pattern**: Use `GraphCanvas` with custom node types

```typescript
import { GraphCanvas } from '../components/GraphCanvas';
import { ContainerNode } from '../components/ContainerNode';
import { BrowserPreviewNode } from '../components/BrowserPreviewNode';
import { useNodesState, useEdgesState } from '@xyflow/react';

const nodeTypes = {
  containerNode: ContainerNode,
  browserPreview: BrowserPreviewNode,
};

function MyGraph() {
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  // Load containers and connections from backend
  useEffect(() => {
    loadContainers();
  }, []);

  const loadContainers = async () => {
    const containers = await projectsApi.getContainers(projectSlug);

    // Convert to XYFlow nodes
    const newNodes = containers.map(c => ({
      id: c.id,
      type: 'containerNode',
      position: { x: c.position_x, y: c.position_y },
      data: {
        name: c.name,
        status: c.status,
        port: c.port,
      },
    }));

    setNodes(newNodes);
  };

  return (
    <GraphCanvas
      nodes={nodes}
      edges={edges}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      nodeTypes={nodeTypes}
    />
  );
}
```

### 11. Cancellable API Requests

**Pattern**: Use `useCancellableRequest` to prevent memory leaks

```typescript
import { useCancellableRequest } from '../hooks/useCancellableRequest';

function MySettings() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const { execute } = useCancellableRequest<MyDataType>();

  useEffect(() => {
    execute(
      () => api.getData(),
      {
        onSuccess: setData,
        onError: (err) => toast.error(err.message),
        onFinally: () => setLoading(false),
      }
    );
  }, [execute]);

  // Cleanup happens automatically on unmount
  // No more "Can't perform state update on unmounted component"
}
```

### 12. Auth Context

**Pattern**: Use `useAuth` for consistent authentication state

```typescript
import { useAuth } from '../contexts/AuthContext';

function MyComponent() {
  const { isAuthenticated, isLoading, user, login, logout, checkAuth } = useAuth();

  if (isLoading) return <Spinner />;
  if (!isAuthenticated) return <Navigate to="/login" />;

  return <div>Hello, {user?.name}</div>;
}
```

### 13. Command Palette Integration

**Pattern**: Use `useCommandHandlers` to register page commands

```typescript
import { useCommandHandlers, useCommandContext } from '../contexts/CommandContext';

// In page component
function ProjectPage() {
  const [view, setView] = useState('builder');

  useCommandHandlers({
    switchView: setView,
    togglePanel: (panel) => setActivePanel(prev => prev === panel ? null : panel),
    refreshPreview: () => iframeRef.current?.contentWindow?.location.reload(),
  });

  // Commands from Cmd+K palette will now work
}

// In CommandPalette
function CommandPalette() {
  const { executeCommand, isCommandAvailable } = useCommandContext();

  const handleSelect = (command) => {
    if (!executeCommand(command.id, command.args)) {
      toast.error(`Command "${command.id}" not available on this page`);
    }
  };
}
```

### 14. SEO for Dynamic Pages

**Pattern**: Use `<SEO>` component with proper cleanup

```typescript
import { SEO, generateProductStructuredData } from '../components/SEO';

function AgentDetailPage({ agent }) {
  if (!agent) return <Spinner />;

  return (
    <>
      <SEO
        title={agent.name}
        description={agent.description}
        url={`https://tesslate.com/marketplace/${agent.slug}`}
        image={agent.og_image_url}
        structuredData={generateProductStructuredData({
          name: agent.name,
          description: agent.description,
          slug: agent.slug,
          price: agent.price,
          rating: agent.average_rating,
        })}
      />
      <AgentContent agent={agent} />
    </>
  );
}
```

### 15. Theme Validation

**Pattern**: Validate themes before applying to prevent crashes

```typescript
import { isValidTheme, DEFAULT_FALLBACK_THEME } from '../types/theme';

async function loadTheme(themeId: string) {
  try {
    const theme = await themesApi.get(themeId);

    if (!isValidTheme(theme)) {
      console.warn(`Theme ${themeId} failed validation`);
      return DEFAULT_FALLBACK_THEME;
    }

    return theme;
  } catch {
    return DEFAULT_FALLBACK_THEME;
  }
}
```

### 16. Keyboard Shortcuts Registry

**Pattern**: Use centralized keyboard registry for platform-aware shortcuts

```typescript
import { getShortcutsForContext, getAllShortcuts } from '../lib/keyboard-registry';

// Get shortcuts for current context (dashboard, project, marketplace, etc.)
const context = getContextFromPath(location.pathname);
const shortcuts = getShortcutsForContext(context);

// Shortcut structure
interface Shortcut {
  id: string;           // Unique identifier
  label: string;        // Display name
  keys: string[];       // Visual keys ['⌘', 'K'] (Mac) or ['Ctrl', 'K'] (Win)
  hotkey: string;       // Hotkeys-js format 'mod+k'
  context: string[];    // Where it's active: ['global', 'project']
  category: string;     // Grouping: 'Navigation', 'Actions', etc.
}

// In CommandPalette
function CommandPalette() {
  const [isOpen, setIsOpen] = useState(false);

  // Open with Cmd+K
  useHotkeys('mod+k', (e) => {
    e.preventDefault();
    setIsOpen(true);
  });

  const commands = useMemo(() =>
    getAllShortcuts()
      .filter(s => s.context.includes(currentContext) || s.context.includes('global'))
      .map(s => ({
        id: s.id,
        label: s.label,
        keys: s.keys,
        action: () => executeCommand(s.id),
      })),
    [currentContext]
  );
}
```

### 17. Settings Layout & Components

**Pattern**: Use modular settings pages with shared layout and components

```typescript
// SettingsLayout provides two-column layout
import { Outlet } from 'react-router-dom';

function SettingsLayout() {
  return (
    <div className="settings-layout">
      <SettingsSidebar />
      <main className="settings-content">
        <Outlet /> {/* Page content renders here */}
      </main>
    </div>
  );
}

// Settings component hierarchy
function ProfileSettings() {
  return (
    <SettingsSection title="Profile">
      <SettingsGroup label="Personal Information">
        <SettingsItem
          label="Display Name"
          description="Your public name"
        >
          <Input value={name} onChange={setName} />
        </SettingsItem>
        <SettingsItem label="Email">
          <Input value={email} disabled />
        </SettingsItem>
      </SettingsGroup>

      <SettingsGroup label="Avatar">
        <SettingsItem label="Profile Picture">
          <AvatarUploader />
        </SettingsItem>
      </SettingsGroup>
    </SettingsSection>
  );
}

// Route configuration
<Route path="/settings" element={<SettingsLayout />}>
  <Route index element={<Navigate to="/settings/profile" replace />} />
  <Route path="profile" element={<ProfileSettings />} />
  <Route path="preferences" element={<PreferencesSettings />} />
  <Route path="security" element={<SecuritySettings />} />
  <Route path="deployment" element={<DeploymentSettings />} />
  <Route path="api-keys" element={<ApiKeysSettings />} />
  <Route path="billing" element={<BillingSettings />} />
</Route>
```

### 18. Marketplace Filtering

**Pattern**: Server-side filtering for agents, client-side for bases

```typescript
// Server-side filtering (agents) - preferred for large datasets
function MarketplaceBrowse() {
  const [filters, setFilters] = useState({
    category: 'all',
    pricing_type: 'all',
    search: '',
    sort: 'popular',
  });
  const [page, setPage] = useState(1);
  const { execute } = useCancellableRequest();

  // Fetch with server-side filtering
  useEffect(() => {
    execute(
      () => marketplaceApi.getAllAgents({
        category: filters.category !== 'all' ? filters.category : undefined,
        pricing_type: filters.pricing_type !== 'all' ? filters.pricing_type : undefined,
        search: filters.search || undefined,
        sort: filters.sort,
        page,
        limit: 20,
      }),
      { onSuccess: (data) => setAgents(data.agents) }
    );
  }, [filters, page, execute]);

  // Filter controls update state, triggering new API call
  return (
    <div>
      <FilterBar
        filters={filters}
        onChange={setFilters}
      />
      <AgentGrid agents={agents} />
      <InfiniteScrollTrigger onVisible={() => setPage(p => p + 1)} />
    </div>
  );
}

// Client-side filtering (bases) - used when dataset is small
function BasesBrowse() {
  const [allBases, setAllBases] = useState([]);
  const [filters, setFilters] = useState({ category: 'all' });

  // Fetch all once
  useEffect(() => {
    marketplaceApi.getAllBases().then(setAllBases);
  }, []);

  // Filter in memory
  const filteredBases = useMemo(() =>
    allBases.filter(base =>
      filters.category === 'all' || base.category === filters.category
    ),
    [allBases, filters]
  );

  return <BaseGrid bases={filteredBases} />;
}
```

### 19. Analytics Integration

**Pattern**: Use PostHog with privacy-respecting initialization

```typescript
import { initPostHog, capture, getPostHog } from '../lib/posthog';

// Initialize once in main.tsx (non-blocking)
initPostHog();

// Safe event capture (never throws)
capture('project_created', {
  project_type: 'react',
  from_template: true,
});

// Check if analytics available
const ph = getPostHog();
if (ph) {
  ph.identify(user.id, { email: user.email });
}
```

Features:
- Respects Do Not Track (DNT) browser setting
- Singleton pattern prevents multiple initializations
- Non-blocking: initialization errors don't crash the app
- `capture()` helper silently fails if PostHog unavailable

### 20. Skeleton Loading States

**Pattern**: Use SkeletonCard for loading placeholders in grids

```typescript
import { SkeletonCard } from '../components/marketplace/SkeletonCard';

function AgentGrid({ loading, agents }) {
  if (loading) {
    return (
      <div className="grid grid-cols-3 gap-4">
        {/* Show 6 skeleton cards while loading */}
        {Array.from({ length: 6 }).map((_, i) => (
          <SkeletonCard key={i} variant="card" />
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-3 gap-4">
      {agents.map(agent => <AgentCard key={agent.id} agent={agent} />)}
    </div>
  );
}

// Featured variant for hero sections
<SkeletonCard variant="featured" />
```

### 21. Help Menu System

**Pattern**: Use HelpButton and HelpMenu for contextual help

```typescript
import { HelpButton } from '../components/ui/HelpButton';
import { HelpMenu } from '../components/ui/HelpMenu';

// Simple: Just the help button (opens shortcuts modal)
function NavigationBar() {
  return (
    <nav>
      {/* Shows "?" button, opens KeyboardShortcutsModal */}
      <HelpButton />
    </nav>
  );
}

// Advanced: Full help menu with nested submenus
function Sidebar() {
  const [showHelp, setShowHelp] = useState(false);
  const [showShortcuts, setShowShortcuts] = useState(false);
  const helpButtonRef = useRef<HTMLButtonElement>(null);

  return (
    <>
      <button ref={helpButtonRef} onClick={() => setShowHelp(!showHelp)}>
        Help
      </button>
      <HelpMenu
        isOpen={showHelp}
        onClose={() => setShowHelp(false)}
        onOpenShortcuts={() => setShowShortcuts(true)}
        anchorRef={helpButtonRef}
      />
      <KeyboardShortcutsModal
        open={showShortcuts}
        onClose={() => setShowShortcuts(false)}
      />
    </>
  );
}
```

### 22. User Dropdown Menu

**Pattern**: Use UserDropdown for account actions

```typescript
import { UserDropdown } from '../components/ui/UserDropdown';

function Header({ user }) {
  return (
    <header>
      <UserDropdown
        userName={user.name}
        userCredits={user.credits_balance}
        userTier={user.subscription_tier}
      />
    </header>
  );
}
```

Includes: Credits display, Subscriptions, Settings, Logout

## Best Practices

### 1. Component Structure
- Keep components focused (single responsibility)
- Extract reusable logic into custom hooks
- Use TypeScript interfaces for props
- Document complex props with JSDoc comments

### 2. State Management
- Use React hooks (useState, useEffect, useCallback, useMemo)
- Lift state up only when necessary
- Use refs for values that don't trigger re-renders
- Consider context for deeply nested prop drilling

### 3. Performance
- Memoize expensive calculations with `useMemo`
- Memoize callbacks with `useCallback`
- Use React.memo for expensive component renders
- Debounce/throttle frequent operations (file saves, API calls)
- Lazy load heavy components with React.lazy

### 4. Error Handling
- Always wrap async calls in try/catch
- Show user-friendly error messages via toast
- Log errors to console for debugging
- Handle loading and error states in UI

### 5. Accessibility
- Use semantic HTML elements
- Add ARIA labels for interactive elements
- Ensure keyboard navigation works
- Test with screen readers

### 6. Styling
- Use Tailwind utility classes for consistency
- Follow existing color scheme (CSS custom properties)
- Maintain responsive design (mobile-first)
- Use Framer Motion for animations

### 7. Testing
- Write tests for critical user flows
- Mock API calls in tests
- Use React Testing Library for component tests
- Test error states and edge cases

## Common Issues and Solutions

### Issue: API calls failing with 401
**Solution**: Check authentication:
```typescript
// Check localStorage token
const token = localStorage.getItem('token');
console.log('Token:', token);

// Check cookie-based auth
const user = await authApi.getCurrentUser();
console.log('User:', user);

// If both fail, redirect to login
if (!token && !user) {
  navigate('/login');
}
```

### Issue: WebSocket not connecting
**Solution**: Verify WebSocket URL and protocol:
```typescript
// Dev: ws://localhost:8000/ws
// Prod: wss://api.tesslate.com/ws
const ws = createWebSocket(); // Uses correct URL from env

// Check connection status
ws.addEventListener('open', () => console.log('Connected'));
ws.addEventListener('error', (e) => console.error('WS Error:', e));
ws.addEventListener('close', (e) => console.log('Disconnected:', e.code));
```

### Issue: File events not propagating
**Solution**: Ensure cleanup and event names match:
```typescript
// Emitter
fileEvents.emit('fileUpdated', { filePath, content });

// Listener (with cleanup)
useEffect(() => {
  const handler = (detail) => console.log('File updated:', detail);
  fileEvents.on('fileUpdated', handler);
  return () => fileEvents.off('fileUpdated', handler); // Important!
}, []);
```

### Issue: Monaco editor not loading
**Solution**: Check imports and worker configuration:
```typescript
// Ensure CSS is imported in main.tsx or component
import '@monaco-editor/react';

// Vite should auto-configure workers
// If issues persist, check vite.config.ts
```

### Issue: XYFlow nodes not rendering
**Solution**: Verify node structure and types:
```typescript
// Ensure node has required properties
const node = {
  id: 'unique-id',          // Required
  type: 'containerNode',     // Must match nodeTypes key
  position: { x: 0, y: 0 },  // Required
  data: { /* custom data */ } // Required
};

// Register node type
const nodeTypes = {
  containerNode: ContainerNode, // Component, not JSX
};

// Pass to ReactFlow
<ReactFlow nodes={nodes} nodeTypes={nodeTypes} />
```

### Issue: Infinite re-renders
**Solution**: Memoize callbacks and check dependencies:
```typescript
// Bad: Creates new function on every render
<ChildComponent onClick={() => doSomething()} />

// Good: Memoized callback
const handleClick = useCallback(() => {
  doSomething();
}, [/* dependencies */]);

<ChildComponent onClick={handleClick} />
```

### Issue: State not updating
**Solution**: Check for stale closures and refs:
```typescript
// Bad: Stale closure
useEffect(() => {
  const interval = setInterval(() => {
    console.log(count); // Always logs initial value
  }, 1000);
  return () => clearInterval(interval);
}, []); // Empty deps = stale closure

// Good: Use ref for latest value
const countRef = useRef(count);
useEffect(() => { countRef.current = count; }, [count]);

useEffect(() => {
  const interval = setInterval(() => {
    console.log(countRef.current); // Always logs latest value
  }, 1000);
  return () => clearInterval(interval);
}, []);
```

## Development Workflow

### 1. Starting the Dev Server
```bash
cd c:/Users/Smirk/Downloads/Tesslate-Studio/app
npm run dev
```
Frontend runs on `http://localhost:5173` and proxies API calls to backend.

### 2. Making Changes
1. Edit files in `app/src/`
2. Vite hot-reloads changes automatically
3. Check browser console for errors
4. Test in Chrome DevTools (F12)

### 3. Adding New Routes
1. Create page component in `app/src/pages/`
2. Add route in `app/src/App.tsx`:
```typescript
<Route path="/my-new-page" element={<MyNewPage />} />
```
3. Add navigation link where appropriate

### 4. Adding New Components
1. Create component file in appropriate directory
2. Export from directory's `index.ts` if needed
3. Import and use in parent component
4. Add TypeScript types for props

### 5. Adding New API Calls
1. Add method to appropriate API object in `lib/api.ts`:
```typescript
export const myNewApi = {
  getData: async () => {
    const response = await api.get('/api/my-endpoint');
    return response.data;
  },
  postData: async (data: MyType) => {
    const response = await api.post('/api/my-endpoint', data);
    return response.data;
  },
};
```
2. Import and use in components:
```typescript
import { myNewApi } from '../lib/api';
const data = await myNewApi.getData();
```

### 6. Testing Changes
```bash
# Run all tests
npm run test

# Run specific test file
npm run test MyComponent.test.tsx

# Run tests in watch mode
npm run test -- --watch

# Run tests with UI
npm run test:ui
```

### 7. Building for Production
```bash
# Build optimized bundle
npm run build

# Preview production build locally
npm run preview
```

## File Naming Conventions

- **Pages**: PascalCase (e.g., `Dashboard.tsx`, `ProjectGraphCanvas.tsx`)
- **Components**: PascalCase (e.g., `ChatContainer.tsx`, `CodeEditor.tsx`)
- **Utilities**: camelCase (e.g., `api.ts`, `fileEvents.ts`)
- **Types**: camelCase (e.g., `agent.ts`, `billing.ts`)
- **CSS**: kebab-case (e.g., `variables.css`)

## Code Style

Follow the existing ESLint and Prettier configuration:
```bash
# Format all files
npm run format

# Check formatting
npm run format:check

# Lint and auto-fix
npm run lint:fix
```

## Getting Help

- Check console errors first
- Review related page/component docs
- Check backend API docs for endpoint details
- Look at similar existing components for patterns
- Test in isolation (create minimal reproduction)
