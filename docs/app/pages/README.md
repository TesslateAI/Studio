# Tesslate Studio Pages

**Location**: `c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/pages/`

This directory contains all top-level route components that make up the Tesslate Studio application. Each page represents a distinct feature or user workflow.

## Route Map

| Route | Component | Purpose | Auth Required |
|-------|-----------|---------|---------------|
| `/` | `NewLandingPage.tsx` | Marketing landing page with animations | No |
| `/landing-old` | `Landing.tsx` | Old landing page (deprecated) | No |
| `/login` | `Login.tsx` | JWT and OAuth login | No |
| `/register` | `Register.tsx` | User registration | No |
| `/logout` | `Logout.tsx` | Logout handler | No |
| `/oauth/callback` | `OAuthLoginCallback.tsx` | OAuth login callback | No |
| `/referral` | `Referrals.tsx` | Referral program | No |
| `/dashboard` | `Dashboard.tsx` | Project list and creation | Yes |
| `/project/:slug` | `ProjectGraphCanvas.tsx` | Architecture visualization | Yes |
| `/project/:slug/setup` | `ProjectSetup.tsx` | Project setup wizard | Yes |
| `/project/:slug/builder` | `Project.tsx` | Main code editor and preview | Yes |
| `/marketplace` | `Marketplace.tsx` | Browse agents and bases | Yes |
| `/marketplace/success` | `MarketplaceSuccess.tsx` | Purchase confirmation | Yes |
| `/marketplace/:slug` | `MarketplaceDetail.tsx` | Agent/base details | Yes |
| `/marketplace/creator/:userId` | `MarketplaceAuthor.tsx` | Creator profile | Yes |
| `/library` | `Library.tsx` | User's purchased items | Yes |
| `/feedback` | `Feedback.tsx` | Submit feedback | Yes |
| `/settings` | — | Redirects to `/settings/profile` | Yes |
| `/settings/profile` | `ProfileSettings.tsx` | User profile, avatar, bio, socials | Yes |
| `/settings/preferences` | `PreferencesSettings.tsx` | Theme preset, chat position | Yes |
| `/settings/security` | `SecuritySettings.tsx` | Password, 2FA, sessions | Yes |
| `/settings/deployment` | `DeploymentSettings.tsx` | Provider credentials, API keys | Yes |
| `/settings/billing` | `BillingSettings.tsx` | Subscription, credits, usage, transactions | Yes |
| `/admin` | `AdminDashboard.tsx` | Platform administration | Yes (Admin) |
| `/auth/github/callback` | `AuthCallback.tsx` | GitHub OAuth for git | Yes |

## Layout Hierarchy

### Dashboard Layout (Shared Sidebar)
These routes use `DashboardLayout` component which provides the navigation sidebar:

```
┌────────────────────────────────────────┐
│  NavigationSidebar  │  Page Content   │
│  (Logo, Nav Links)  │  (Dynamic)      │
│                     │                 │
│  • Dashboard        │  <Dashboard />  │
│  • Marketplace      │  or             │
│  • Library          │  <Marketplace />│
│  • Feedback         │  or             │
│  • Settings         │  <Library />    │
└────────────────────────────────────────┘
```

Routes using this layout:
- `/dashboard`
- `/marketplace`
- `/marketplace/:slug`
- `/marketplace/creator/:userId`
- `/library`
- `/feedback`
- `/settings/*` (profile, preferences, security, deployment, billing)

### Standalone Routes
These routes have their own layouts:

- **Project Setup** (`/project/:slug/setup`): Full-screen setup wizard with agent/manual tabs
- **Project Builder** (`/project/:slug/builder`): Full-screen editor with chat sidebar
- **Graph Canvas** (`/project/:slug`): Full-screen XYFlow canvas with floating panels
- **Admin Dashboard** (`/admin`): Custom admin layout
- **Auth Pages**: Minimal centered layouts

## Page Categories

### 1. Authentication & Onboarding
- **Login**: JWT email/password + OAuth (Google, GitHub)
- **Register**: Email/password signup with validation
- **Logout**: Clear token and redirect
- **OAuthLoginCallback**: Handle OAuth provider redirects
- **Referrals**: Referral program landing

See: `auth.md`

### 2. Project Management
- **Dashboard**: Project list, creation, deletion, filtering
- **ProjectSetup**: Setup wizard with agent/manual tabs for configuring `.tesslate/config.json`
- **ProjectGraphCanvas**: Visual architecture editor with XYFlow
- **Project**: Code editor, chat, preview, panels (main builder)
- **Library**: User's purchased agents, skills, MCP servers, and project bases

See: `dashboard.md`, `project-setup.md`, `project-graph.md`, `project-builder.md`

### 3. Marketplace
- **Marketplace**: Browse and search agents/bases
- **MarketplaceDetail**: View details, reviews, purchase
- **MarketplaceAuthor**: Creator profile and items
- **MarketplaceSuccess**: Purchase confirmation

See: `marketplace.md`

### 4. Billing & Subscription
- **BillingSettings** (`/settings/billing`): Consolidated billing page with subscription overview, credit balance, usage, and transaction history

See: `billing.md`

### 5. User Account (Settings)
- **ProfileSettings** (`/settings/profile`): Name, email, avatar, bio, socials
- **PreferencesSettings** (`/settings/preferences`): Theme preset, chat position
- **SecuritySettings** (`/settings/security`): Password, 2FA, sessions
- **DeploymentSettings** (`/settings/deployment`): Provider credentials, API keys
- **Feedback**: Submit feature requests and bug reports

See: `settings.md`

### 6. Admin
- **AdminDashboard**: User management, marketplace approval, analytics

## Common Patterns Across Pages

### 1. Loading States
Most pages show a loading spinner while fetching data:

```typescript
const [loading, setLoading] = useState(true);

useEffect(() => {
  const loadData = async () => {
    try {
      const data = await api.getData();
      setData(data);
    } catch (error) {
      toast.error('Failed to load data');
    } finally {
      setLoading(false);
    }
  };
  loadData();
}, []);

if (loading) {
  return <LoadingSpinner />;
}
```

### 2. Error Handling
Errors are displayed via toast notifications:

```typescript
try {
  await api.performAction();
  toast.success('Action completed!');
} catch (error) {
  toast.error(error.response?.data?.detail || 'Action failed');
}
```

### 3. Polling for Updates
Pages poll for status changes at regular intervals:

```typescript
useEffect(() => {
  const pollInterval = setInterval(() => {
    loadProjects(); // Refresh data
  }, 60000); // Every 60 seconds

  return () => clearInterval(pollInterval);
}, []);
```

### 4. Mobile Responsiveness
Most pages show a warning on mobile devices:

```typescript
const [isDesktop, setIsDesktop] = useState(window.innerWidth >= 768);

useEffect(() => {
  const handleResize = () => setIsDesktop(window.innerWidth >= 768);
  window.addEventListener('resize', handleResize);
  return () => window.removeEventListener('resize', handleResize);
}, []);

if (!isDesktop) {
  return <MobileWarning />;
}
```

### 5. Theme Support
Pages respect dark/light mode:

```typescript
import { useTheme } from '../theme/ThemeContext';

const { theme, toggleTheme } = useTheme();

return (
  <div className={theme === 'dark' ? 'dark-mode-class' : 'light-mode-class'}>
    {/* Content */}
  </div>
);
```

### 6. Navigation
Pages use React Router for navigation:

```typescript
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';

const navigate = useNavigate();
const { slug } = useParams<{ slug: string }>();
const [searchParams] = useSearchParams();

// Navigate programmatically
navigate('/dashboard');

// Navigate with state
navigate('/project/my-app', { state: { fromDashboard: true } });

// Get URL params
const projectSlug = slug;
const tab = searchParams.get('tab');
```

## State Management Patterns

### 1. Local State
Most pages use `useState` for component-level state:

```typescript
const [data, setData] = useState<DataType[]>([]);
const [loading, setLoading] = useState(true);
const [selectedItem, setSelectedItem] = useState<DataType | null>(null);
```

### 2. URL State
Some pages store state in URL for shareability:

```typescript
const [searchParams, setSearchParams] = useSearchParams();

// Read from URL
const tab = searchParams.get('tab') || 'overview';
const filter = searchParams.get('filter') || 'all';

// Write to URL
setSearchParams({ tab: 'settings', filter: 'active' });
```

### 3. Local Storage
Preferences are persisted to localStorage:

```typescript
const [sidebarExpanded, setSidebarExpanded] = useState(() => {
  const saved = localStorage.getItem('sidebarExpanded');
  return saved !== null ? JSON.parse(saved) : true;
});

useEffect(() => {
  localStorage.setItem('sidebarExpanded', JSON.stringify(sidebarExpanded));
}, [sidebarExpanded]);
```

### 4. Context
Theme and auth state use React Context:

```typescript
import { useTheme } from '../theme/ThemeContext';

const { theme, toggleTheme } = useTheme();
```

## Performance Optimization

### 1. Debounced Search
Search inputs are debounced to reduce API calls:

```typescript
import { debounce } from 'lodash';

const debouncedSearch = useCallback(
  debounce(async (query: string) => {
    const results = await api.search(query);
    setSearchResults(results);
  }, 300),
  []
);

<input onChange={(e) => debouncedSearch(e.target.value)} />
```

### 2. Lazy Loading
Heavy components are loaded on demand:

```typescript
const ProjectGraphCanvas = React.lazy(() => import('./ProjectGraphCanvas'));

<Suspense fallback={<LoadingSpinner />}>
  <ProjectGraphCanvas />
</Suspense>
```

### 3. Memoization
Expensive calculations are memoized:

```typescript
const filteredProjects = useMemo(() => {
  return projects.filter(p => p.name.includes(searchQuery));
}, [projects, searchQuery]);
```

## Accessibility

### 1. Keyboard Navigation
All interactive elements support keyboard:

```typescript
<button
  onClick={handleClick}
  onKeyDown={(e) => e.key === 'Enter' && handleClick()}
  tabIndex={0}
>
  Click Me
</button>
```

### 2. ARIA Labels
Screen reader support via ARIA:

```typescript
<button aria-label="Close modal" onClick={onClose}>
  <X />
</button>

<input
  type="text"
  aria-describedby="email-error"
  aria-invalid={hasError}
/>
{hasError && <span id="email-error">{errorMessage}</span>}
```

### 3. Focus Management
Focus is managed in modals and navigation:

```typescript
useEffect(() => {
  if (showModal) {
    // Focus first input when modal opens
    modalRef.current?.querySelector('input')?.focus();
  }
}, [showModal]);
```

## Testing Pages

### 1. Unit Tests
Test individual page components:

```typescript
// Dashboard.test.tsx
import { render, screen, waitFor } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import Dashboard from './Dashboard';

test('renders project list', async () => {
  render(
    <BrowserRouter>
      <Dashboard />
    </BrowserRouter>
  );

  await waitFor(() => {
    expect(screen.getByText('My Project')).toBeInTheDocument();
  });
});
```

### 2. Integration Tests
Test page workflows:

```typescript
test('creates new project', async () => {
  const user = userEvent.setup();
  render(<Dashboard />);

  // Open modal
  await user.click(screen.getByText('New Project'));

  // Fill form
  await user.type(screen.getByLabelText('Project Name'), 'Test App');

  // Submit
  await user.click(screen.getByText('Create'));

  // Verify navigation
  await waitFor(() => {
    expect(window.location.pathname).toContain('/project/');
  });
});
```

## Related Documentation

- **`dashboard.md`**: Dashboard page details
- **`project-builder.md`**: Project builder page details
- **`project-graph.md`**: Graph canvas page details
- **`marketplace.md`**: Marketplace pages details
- **`billing.md`**: Billing pages details
- **`auth.md`**: Authentication pages details
- **`../CLAUDE.md`**: General frontend development context
