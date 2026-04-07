# Page Development Context

**Purpose**: This context provides guidance for developing and modifying individual pages in the Tesslate Studio frontend.

## When to Load This Context

Load this context when:
- Creating a new page component
- Modifying existing page layouts or navigation
- Adding new routes to the application
- Working on page-specific features
- Debugging page-level issues
- Understanding page workflow and data flow

## Quick Reference

### All Pages at a Glance

| Page | File | Route | Key Features |
|------|------|-------|--------------|
| Dashboard | `Dashboard.tsx` | `/dashboard` | Project list, creation, task polling |
| Project Setup | `ProjectSetup.tsx` | `/project/:slug/setup` | Setup wizard with agent/manual tabs |
| Project Builder | `ProjectPage.tsx` | `/project/:slug/builder` | Editor, chat, preview, design, panels |
| Graph Canvas | `ProjectGraphCanvas.tsx` | `/project/:slug` | XYFlow architecture visualization |
| Marketplace | `Marketplace.tsx` | `/marketplace` | Browse agents/bases/skills/MCP servers |
| Library | `Library.tsx` | `/library` | User's purchased items, skills, MCP servers |
| Billing | `BillingSettings.tsx` | `/settings/billing` | Subscription, credits, usage |
| Profile | `ProfileSettings.tsx` | `/settings/profile` | Name, email, avatar, bio, socials |
| Preferences | `PreferencesSettings.tsx` | `/settings/preferences` | Theme preset, chat position |
| Security | `SecuritySettings.tsx` | `/settings/security` | Password, 2FA, sessions |
| Deployment | `DeploymentSettings.tsx` | `/settings/deployment` | Provider credentials, API keys |
| Connections | `ConnectionsSettings.tsx` | `/settings/connections` | Gateway connections (messaging platforms) |
| Channels | `ChannelsSettings.tsx` | `/settings/channels` | Per-channel agent routing and config |
| Schedules | `SchedulesSettings.tsx` | `/settings/schedules` | Cron-scheduled agent tasks |
| Login | `Login.tsx` | `/login` | JWT + email 2FA and OAuth authentication |
| Forgot Password | `ForgotPassword.tsx` | `/forgot-password` | Request password reset email |
| Reset Password | `ResetPassword.tsx` | `/reset-password` | Set new password via token |
| Admin | `AdminDashboard.tsx` | `/admin` | Platform administration |

## Common Page Patterns

### 1. Page Structure Template

```typescript
import { useState, useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { LoadingSpinner } from '../components/PulsingGridSpinner';
import { api } from '../lib/api';
import toast from 'react-hot-toast';

export default function MyPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<DataType[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      const result = await api.getData(id);
      setData(result);
    } catch (error) {
      toast.error('Failed to load data');
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return <LoadingSpinner />;
  }

  return (
    <div className="min-h-screen bg-background">
      <header>
        {/* Page header */}
      </header>
      <main>
        {/* Page content */}
      </main>
    </div>
  );
}
```

### 2. Layout Patterns

**Dashboard Layout** (with sidebar):
```typescript
// Automatically wraps pages in App.tsx using DashboardLayout
<Route
  element={
    <PrivateRoute>
      <DashboardLayout />
    </PrivateRoute>
  }
>
  <Route path="/dashboard" element={<Dashboard />} />
  <Route path="/marketplace" element={<Marketplace />} />
  <Route path="/library" element={<Library />} />
</Route>
```

**Full-Screen Layout** (no sidebar):
```typescript
// Standalone route for full-screen pages
<Route
  path="/project/:slug/builder"
  element={
    <PrivateRoute>
      <Project />
    </PrivateRoute>
  }
/>
```

### 3. Data Loading Pattern

```typescript
// Load data on mount
useEffect(() => {
  loadData();
}, []);

// Reload on specific changes
useEffect(() => {
  if (projectId) {
    loadProjectDetails();
  }
}, [projectId]);

// Polling for updates
useEffect(() => {
  const interval = setInterval(() => {
    refreshData();
  }, 60000); // Every minute

  return () => clearInterval(interval);
}, []);
```

### 4. State Management

```typescript
// Local component state
const [items, setItems] = useState<Item[]>([]);
const [selectedItem, setSelectedItem] = useState<Item | null>(null);
const [isModalOpen, setIsModalOpen] = useState(false);

// URL params
const { slug } = useParams<{ slug: string }>();
const [searchParams, setSearchParams] = useSearchParams();
const tab = searchParams.get('tab') || 'overview';

// Local storage
const [preference, setPreference] = useState(() => {
  const saved = localStorage.getItem('myPreference');
  return saved ? JSON.parse(saved) : defaultValue;
});

useEffect(() => {
  localStorage.setItem('myPreference', JSON.stringify(preference));
}, [preference]);
```

### 5. Navigation

```typescript
const navigate = useNavigate();

// Simple navigation
navigate('/dashboard');

// With state
navigate('/project/my-app', { state: { from: 'dashboard' } });

// Back navigation
navigate(-1);

// Replace (no history entry)
navigate('/login', { replace: true });

// With query params
const params = new URLSearchParams({ tab: 'settings', filter: 'active' });
navigate(`/project/my-app?${params}`);
```

## Page-Specific Details

### Dashboard (`Dashboard.tsx`)
**Purpose**: Project list and creation hub

**Key Features**:
- Displays all user's projects as cards
- Create new projects with modal
- Import from GitHub/GitLab/Bitbucket
- Delete projects with confirmation
- Task polling for project setup status
- User profile dropdown with credits and tier

**State Management**:
```typescript
const [projects, setProjects] = useState<Project[]>([]);
const [deletingProjectIds, setDeletingProjectIds] = useState<Set<string>>(new Set());
const [showCreateDialog, setShowCreateDialog] = useState(false);
const [showImportDialog, setShowImportDialog] = useState(false);
```

**API Calls**:
```typescript
// Load projects
const projects = await projectsApi.getAll();

// Create project
const newProject = await projectsApi.create({ name, base_id });

// Delete project
await projectsApi.delete(slug);

// Poll task status
const task = await tasksApi.get(taskId);
```

See: `dashboard.md`

### Project Setup (`ProjectSetup.tsx`)
**Purpose**: Setup wizard for configuring `.tesslate/config.json`

**Key Features**:
- Agent tab: AI-powered project analysis detects frameworks, ports, start commands
- Manual tab: Hand-configure apps and infrastructure via `ServiceConfigForm`
- Existing config detection and pre-population
- Skip option for workspace-only setup
- Saves config and creates containers, then navigates to builder

**State Management**:
```typescript
type Tab = 'agent' | 'manual';
const [activeTab, setActiveTab] = useState<Tab>('agent');
const [config, setConfig] = useState<TesslateConfig>(DEFAULT_CONFIG);
const [isAnalyzing, setIsAnalyzing] = useState(false);
const [analysisDone, setAnalysisDone] = useState(false);
const [isSaving, setIsSaving] = useState(false);
```

**API Calls**:
```typescript
const config = await setupApi.getConfig(slug);
const analysis = await setupApi.analyzeProject(slug);
const result = await setupApi.saveConfig(slug, config);
```

See: `project-setup.md`

### Project Builder (`Project.tsx`)
**Purpose**: Main code editor with AI chat

**Key Features**:
- Monaco code editor with file tree
- Live iframe preview of running container
- AI chat interface with streaming
- Multiple view modes (preview, code, kanban, assets, terminal)
- Floating panels (GitHub, architecture, notes, settings)
- Breadcrumb navigation
- Theme toggle

**State Management**:
```typescript
const [activeView, setActiveView] = useState<'architecture' | 'preview' | 'code' | 'design' | 'kanban' | 'assets' | 'terminal'>('preview');
const [activePanel, setActivePanel] = useState<PanelType>(null);
const [files, setFiles] = useState<Array<Record<string, unknown>>>([]);
const [container, setContainer] = useState<Record<string, unknown> | null>(null);
const [agents, setAgents] = useState<UIAgent[]>([]);
```

**URL Params**:
```typescript
const { slug } = useParams<{ slug: string }>();
const containerId = searchParams.get('container');
```

See: `project-builder.md`

### Graph Canvas (`ProjectGraphCanvas.tsx`)
**Purpose**: Visual architecture editor

**Key Features**:
- XYFlow interactive graph canvas
- Container nodes with status indicators
- Connection edges with semantic types (HTTP, database, cache, etc.)
- Browser preview nodes
- Drag-and-drop container positioning
- **Auto-layout using Dagre algorithm** (`getLayoutedElements` from `utils/autoLayout.ts`)
- Start/stop all containers
- Container properties panel
- AI chat with view-scoped tools

**State Management**:
```typescript
const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
const [isRunning, setIsRunning] = useState(false);
const [selectedContainer, setSelectedContainer] = useState<Container | null>(null);
const [isDragging, setIsDragging] = useState(false);
```

**Node Types**:
```typescript
const nodeTypes = {
  containerNode: ContainerNode,
  browserPreview: BrowserPreviewNode,
};
```

See: `project-graph.md`

### Marketplace (`Marketplace.tsx`)
**Purpose**: Browse and purchase agents/bases/skills/MCP servers

**Key Features**:
- Filter by type (agents, bases, tools, integrations, skills, MCP servers)
- Search by name, description, tags
- Sort by featured, popular, newest, name
- Featured items carousel
- Install/purchase flow
- Navigate to detail page

**State Management**:
```typescript
const [items, setItems] = useState<MarketplaceItem[]>([]);
const [filteredItems, setFilteredItems] = useState<MarketplaceItem[]>([]);
const [selectedItemType, setSelectedItemType] = useState<ItemType>('agent');
const [searchQuery, setSearchQuery] = useState('');
const [sortBy, setSortBy] = useState<SortOption>('featured');
```

**Item Types**:
```typescript
type ItemType = 'agent' | 'base' | 'theme' | 'tool' | 'integration' | 'skill' | 'mcp_server';
```

**API Calls**:
```typescript
// Load items by type
const agents = await marketplaceApi.getAllAgents();
const bases = await marketplaceApi.getAllBases();
const skills = await marketplaceApi.getAllSkills();
const mcpServers = await marketplaceApi.getAllMcpServers();

// Purchase / install
await marketplaceApi.purchaseAgent(slug);
await marketplaceApi.purchaseSkill(skillId);
await marketplaceApi.installMcpServer(marketplaceAgentId);
```

See: `marketplace.md`

### Library (`Library.tsx`)
**Purpose**: User's purchased items, skills, MCP servers, submitted bases, and API keys

**Tabs**:
1. **Agents**: Purchased and custom agents with enable/disable
2. **Bases**: User-submitted project templates with visibility toggle, edit, and delete
3. **Skills**: Purchased skills from the marketplace
4. **MCP Servers**: Installed MCP server configurations with uninstall
5. **Themes**: User's theme presets
6. **Models**: Available LLM models with pricing

**Bases Tab Features**:
- "Submit Base" button opens `SubmitBaseModal` (create/edit modes)
- Card grid showing user's created bases with visibility badge (lock/globe icon)
- Toggle visibility (Make Private / Make Public)
- Edit base details
- Delete base (soft delete with confirmation dialog)
- Download count display

**Skills Tab Features**:
- Displays purchased skills filtered from `marketplaceApi.getAllSkills()`
- Card grid with skill name, description, and category

**MCP Servers Tab Features**:
- Displays installed MCP servers via `marketplaceApi.getInstalledMcpServers()`
- Shows server name, URL, and status
- Uninstall button with confirmation

**State Management**:
```typescript
type TabType = 'agents' | 'bases' | 'skills' | 'mcp_servers' | 'themes' | 'models';

const [activeTab, setActiveTab] = useState<TabType>('agents');
const [agents, setAgents] = useState<LibraryAgent[]>([]);
const [bases, setBases] = useState<LibraryBase[]>([]);
const [skills, setSkills] = useState<LibrarySkill[]>([]);
const [mcpServers, setMcpServers] = useState<InstalledMcpServer[]>([]);
const [models, setModels] = useState<Model[]>([]);
const [showSubmitBaseModal, setShowSubmitBaseModal] = useState(false);
const [editingBase, setEditingBase] = useState<LibraryBase | null>(null);
```

**URL State**:
```typescript
const [searchParams, setSearchParams] = useSearchParams();
const tab = searchParams.get('tab') || 'agents';

// Change tab
setSearchParams({ tab: 'bases' });
```

**Agent Edit Modal (Advanced Settings)**:
The Agents tab edit modal includes advanced configuration fields for TesslateAgent:
- **Compaction Model**: Optional model selector for the auxiliary compaction/summary model (stored in `config.compaction_model`)
- **Context Window Override**: Numeric input to override the default 128K context window (stored in `config.context_window`)
- **Thinking Effort**: Selector for extended thinking intensity — `""` (off), `"low"`, `"medium"`, `"high"`, `"xhigh"` (stored in `config.thinking_effort`)

### Billing Settings (`BillingSettings.tsx`)
**Purpose**: Subscription management, credit balance, and usage

**Route**: `/settings/billing`

**Key Features**:
- Current subscription overview
- Credit balance display
- Recent transactions
- Credit purchase history
- Cancel subscription
- Manage subscription (Stripe portal)
- Upgrade/downgrade links

**State Management**:
```typescript
const [subscription, setSubscription] = useState<SubscriptionResponse | null>(null);
const [credits, setCredits] = useState<CreditBalanceResponse | null>(null);
const [transactions, setTransactions] = useState<Transaction[]>([]);
const [creditHistory, setCreditHistory] = useState<CreditPurchase[]>([]);
```

See: `billing.md`

### Settings Pages (Modular Architecture)
**Purpose**: User account management split across dedicated pages under `/settings/*`

**Pages**:
1. **ProfileSettings.tsx** (`/settings/profile`): Name, email, avatar upload, bio, social links (Twitter, GitHub, website)
2. **PreferencesSettings.tsx** (`/settings/preferences`): Theme preset selection, chat position, diagram model
3. **SecuritySettings.tsx** (`/settings/security`): Password change, 2FA status, active sessions
4. **DeploymentSettings.tsx** (`/settings/deployment`): Provider credentials, external API keys (merged from old ApiKeysSettings)
5. **BillingSettings.tsx** (`/settings/billing`): Subscription tiers, credit balance, usage, transactions
6. **ConnectionsSettings.tsx** (`/settings/connections`): Gateway connections management (connect/disconnect messaging platforms like Telegram, Slack, Discord, WhatsApp)
7. **ChannelsSettings.tsx** (`/settings/channels`): Per-channel configuration for connected messaging platforms (agent routing, project binding, credential management)
8. **SchedulesSettings.tsx** (`/settings/schedules`): Cron-scheduled agent tasks management (create, pause, resume, trigger, delete scheduled agent runs)

**Layout**: Uses `SettingsLayout.tsx` with a sidebar (`SettingsSidebar.tsx`) for navigation between pages.

### Login (`Login.tsx`)
**Purpose**: User authentication with mandatory email 2FA

**Features**:
- Email/password login with mandatory 2FA (6-digit email code)
- OAuth login (Google, GitHub) - bypasses 2FA
- Forgot password link
- Register link

**Authentication Flow**:
```typescript
// Step 1: Submit credentials → get temp token
const response = await authApi.login(email, password);
// response = { requires_2fa: true, temp_token: "...", method: "email" }

// Step 2: Verify 2FA code → get JWT
const jwt = await authApi.verify2fa(tempToken, code);
localStorage.setItem('token', jwt.access_token);
await checkAuth({ force: true });
navigate('/dashboard');

// OAuth login (bypasses 2FA)
window.location.href = `${API_URL}/api/auth/google/authorize`;
```

See: `auth.md`

### Forgot Password (`ForgotPassword.tsx`)
**Purpose**: Start password reset flow

**Features**:
- Email input form
- Always shows success (prevents user enumeration)
- Email with reset link sent asynchronously

### Reset Password (`ResetPassword.tsx`)
**Purpose**: Complete password reset with token from email

**Features**:
- Token read from `?token=` URL query param
- New password + confirmation inputs
- Validates token signature and expiry
- Redirects to `/login` on success

### Admin Dashboard (`AdminDashboard.tsx`)
**Purpose**: Platform administration

**Features**:
- User management
- Marketplace agent approval
- System analytics
- Platform settings

**Protected Route**:
```typescript
// Only accessible to admin users
// Backend checks user.is_admin
```

## Adding a New Page

### Step 1: Create Page Component
```typescript
// app/src/pages/MyNewPage.tsx
import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { LoadingSpinner } from '../components/PulsingGridSpinner';
import { api } from '../lib/api';
import toast from 'react-hot-toast';

export default function MyNewPage() {
  const navigate = useNavigate();
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const loadData = async () => {
      try {
        const result = await api.getMyData();
        setData(result);
      } catch (error) {
        toast.error('Failed to load data');
      } finally {
        setLoading(false);
      }
    };
    loadData();
  }, []);

  if (loading) return <LoadingSpinner />;

  return (
    <div className="min-h-screen bg-background">
      <h1>My New Page</h1>
      {/* Content */}
    </div>
  );
}
```

### Step 2: Add Route to App.tsx
```typescript
// app/src/App.tsx
import MyNewPage from './pages/MyNewPage';

// Add to routes
<Route
  path="/my-new-page"
  element={
    <PrivateRoute>
      <MyNewPage />
    </PrivateRoute>
  }
/>
```

### Step 3: Add Navigation Link
```typescript
// In NavigationSidebar or appropriate component
<Link to="/my-new-page">
  <MyIcon /> My New Page
</Link>
```

### Step 4: Add API Methods (if needed)
```typescript
// app/src/lib/api.ts
export const myNewApi = {
  getMyData: async () => {
    const response = await api.get('/api/my-endpoint');
    return response.data;
  },
};
```

### Step 5: Add Types (if needed)
```typescript
// app/src/types/myNewFeature.ts
export interface MyData {
  id: string;
  name: string;
  // ...
}
```

## Testing Pages

### Unit Test Example
```typescript
// app/src/pages/MyNewPage.test.tsx
import { render, screen, waitFor } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import MyNewPage from './MyNewPage';

test('renders page title', async () => {
  render(
    <BrowserRouter>
      <MyNewPage />
    </BrowserRouter>
  );

  await waitFor(() => {
    expect(screen.getByText('My New Page')).toBeInTheDocument();
  });
});
```

### Integration Test Example
```typescript
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import MyNewPage from './MyNewPage';

test('clicking button navigates', async () => {
  const user = userEvent.setup();
  render(<MyNewPage />);

  await user.click(screen.getByText('Go to Dashboard'));

  expect(window.location.pathname).toBe('/dashboard');
});
```

## Best Practices

### 1. Loading States
Always show loading state while fetching data:
```typescript
if (loading) {
  return <LoadingSpinner />;
}
```

### 2. Error Handling
Handle errors gracefully with toast notifications:
```typescript
try {
  await api.performAction();
  toast.success('Success!');
} catch (error) {
  toast.error(error.response?.data?.detail || 'Action failed');
}
```

### 3. Cleanup
Clean up side effects in useEffect:
```typescript
useEffect(() => {
  const interval = setInterval(loadData, 60000);
  return () => clearInterval(interval); // Cleanup
}, []);
```

### 4. Memoization
Memoize expensive computations:
```typescript
const filteredData = useMemo(() => {
  return data.filter(item => item.name.includes(searchQuery));
}, [data, searchQuery]);
```

### 5. Accessibility
Use semantic HTML and ARIA labels:
```typescript
<button aria-label="Close modal" onClick={onClose}>
  <X />
</button>
```

## Related Documentation

- **`dashboard.md`**: Dashboard page details
- **`project-setup.md`**: Project setup wizard details
- **`project-builder.md`**: Project builder page details
- **`project-graph.md`**: Graph canvas page details
- **`marketplace.md`**: Marketplace pages details
- **`marketplace-browse.md`**: Marketplace browse page details (skills, MCP servers)
- **`billing.md`**: Billing pages details
- **`auth.md`**: Authentication pages details
- **Component Docs**: See `docs/app/components/`
- **API Docs**: See `docs/orchestrator/routers/`
- **Frontend Context**: See `docs/app/CLAUDE.md`
