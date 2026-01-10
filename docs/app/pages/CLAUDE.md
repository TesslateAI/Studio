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
| Project Builder | `Project.tsx` | `/project/:slug/builder` | Editor, chat, preview, panels |
| Graph Canvas | `ProjectGraphCanvas.tsx` | `/project/:slug` | XYFlow architecture visualization |
| Marketplace | `Marketplace.tsx` | `/marketplace` | Browse agents/bases with filtering |
| Library | `Library.tsx` | `/library` | User's purchased items and API keys |
| Billing | `BillingDashboard.tsx` | `/billing` | Subscription management |
| Account Settings | `AccountSettings.tsx` | `/settings` | Profile and preferences |
| Login | `Login.tsx` | `/login` | JWT and OAuth authentication |
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
const [activeView, setActiveView] = useState<'preview' | 'code' | 'kanban' | 'assets' | 'terminal'>('preview');
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
**Purpose**: Browse and purchase agents/bases

**Key Features**:
- Filter by type (agents, bases, tools, integrations)
- Search by name, description, tags
- Sort by featured, popular, newest, name
- Featured items carousel
- Install/purchase flow
- Navigate to detail page

**State Management**:
```typescript
const [items, setItems] = useState<MarketplaceItem[]>([]);
const [filteredItems, setFilteredItems] = useState<MarketplaceItem[]>([]);
const [selectedItemType, setSelectedItemType] = useState<'agent' | 'base' | 'tool' | 'integration'>('agent');
const [searchQuery, setSearchQuery] = useState('');
const [sortBy, setSortBy] = useState<'featured' | 'popular' | 'newest' | 'name'>('featured');
```

**API Calls**:
```typescript
// Load items
const agents = await marketplaceApi.getAllAgents();
const bases = await marketplaceApi.getAllBases();

// Purchase
await marketplaceApi.purchaseAgent(slug);
```

See: `marketplace.md`

### Library (`Library.tsx`)
**Purpose**: User's purchased items and API keys

**Tabs**:
1. **Agents**: Purchased and custom agents with enable/disable
2. **Models**: Available LLM models with pricing
3. **API Keys**: Manage external provider keys (OpenAI, Anthropic, etc.)
4. **Subscriptions**: Current plan and usage
5. **Credits**: Credit balance and purchase history

**State Management**:
```typescript
const [activeTab, setActiveTab] = useState<TabType>('agents');
const [agents, setAgents] = useState<LibraryAgent[]>([]);
const [models, setModels] = useState<Model[]>([]);
const [apiKeys, setApiKeys] = useState<ApiKey[]>([]);
```

**URL State**:
```typescript
const [searchParams, setSearchParams] = useSearchParams();
const tab = searchParams.get('tab') || 'agents';

// Change tab
setSearchParams({ tab: 'models' });
```

### Billing Dashboard (`BillingDashboard.tsx`)
**Purpose**: Subscription and payment management

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

### Account Settings (`AccountSettings.tsx`)
**Purpose**: User profile and preferences

**Sections**:
1. **Profile**: Name, email, avatar
2. **Security**: Password change
3. **API Keys**: Personal API keys for Tesslate API
4. **Preferences**: Theme, notifications, etc.
5. **Danger Zone**: Delete account

**State Management**:
```typescript
const [user, setUser] = useState<User | null>(null);
const [editMode, setEditMode] = useState(false);
const [formData, setFormData] = useState({ name: '', email: '' });
```

### Login (`Login.tsx`)
**Purpose**: User authentication

**Features**:
- Email/password login (JWT)
- OAuth login (Google, GitHub)
- Remember me checkbox
- Forgot password link
- Register link

**Authentication Flow**:
```typescript
// JWT login
const response = await authApi.login(email, password);
localStorage.setItem('token', response.access_token);
navigate('/dashboard');

// OAuth login
window.location.href = `${API_URL}/api/auth/google/authorize`;
// OAuth provider redirects to /oauth/callback
// Callback page checks cookie auth and redirects to /dashboard
```

See: `auth.md`

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

- **Component Docs**: See `c:/Users/Smirk/Downloads/Tesslate-Studio/docs/app/components/` (to be created)
- **API Docs**: See `c:/Users/Smirk/Downloads/Tesslate-Studio/docs/orchestrator/routers/`
- **Frontend Context**: See `c:/Users/Smirk/Downloads/Tesslate-Studio/docs/app/CLAUDE.md`
