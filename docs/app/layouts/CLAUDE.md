# Page Layouts Documentation

**Purpose**: This context provides guidance for working with the page layout system in Tesslate Studio, which provides consistent structure for settings and marketplace pages.

## When to Load This Context

Load this context when:
- Creating new pages that need consistent layout structure
- Modifying the settings page navigation or layout
- Working on marketplace public/authenticated views
- Implementing responsive mobile drawer patterns
- Adding new authenticated vs. public page variants
- Debugging layout-related mobile issues

## Key Files

| File | Purpose |
|------|---------|
| `app/src/layouts/SettingsLayout.tsx` | Two-column settings layout with collapsible sidebar and mobile drawer |
| `app/src/layouts/MarketplaceLayout.tsx` | Adaptive layout that switches between public and authenticated views |
| `app/src/layouts/PublicMarketplaceHeader.tsx` | Public marketplace header with auth CTAs and navigation |
| `app/src/layouts/PublicMarketplaceFooter.tsx` | SEO-friendly footer with category links |

## Related Contexts

- **`docs/app/contexts/CLAUDE.md`**: MarketplaceAuthContext used by MarketplaceLayout
- **`docs/app/CLAUDE.md`**: Frontend overview and patterns
- **`docs/app/components/settings/CLAUDE.md`**: Settings sidebar components
- **`docs/app/components/ui/CLAUDE.md`**: NavigationSidebar used by authenticated view

## Layout Architecture

```
App Router
├── /settings/*  -> SettingsLayout
│   └── Outlet renders settings pages
│
└── /marketplace/* -> MarketplaceLayout
    ├── Authenticated View (with NavigationSidebar)
    │   └── Outlet renders marketplace pages
    │
    └── Public View (header + footer)
        └── Outlet renders marketplace pages
```

## SettingsLayout

### Purpose

Provides a consistent two-column layout for all settings pages with:
- Collapsible desktop sidebar (via `SettingsSidebar` component)
- Mobile-optimized header with back navigation
- Animated slide-in drawer for mobile navigation
- Safe area support for notched devices (iOS)

### Key Features

1. **Route-based Titles**: Automatically displays the current page title based on route
2. **Mobile Warning**: Shows a warning for unsupported mobile features
3. **Animated Transitions**: Uses Framer Motion for smooth drawer animations
4. **Touch-friendly**: Minimum 44px touch targets for mobile buttons

### Route Titles Mapping

```typescript
const routeTitles: Record<string, string> = {
  '/settings/profile': 'Profile',
  '/settings/preferences': 'Preferences',
  '/settings/security': 'Security',
  '/settings/deployment': 'Deployment',
  '/settings/api-keys': 'API Keys',
  '/settings/billing': 'Billing',
};
```

### Mobile Drawer Pattern

The mobile drawer uses a spring animation for natural feel:

```typescript
<motion.div
  initial={{ x: '-100%' }}
  animate={{ x: 0 }}
  exit={{ x: '-100%' }}
  transition={{
    type: 'spring',
    stiffness: 400,
    damping: 30
  }}
  className="w-[70vw] max-w-[240px] min-w-[180px]"
>
  <SettingsSidebarMobile onClose={handleCloseMobileMenu} />
</motion.div>
```

### Usage in Router

```typescript
// In App.tsx
<Route path="/settings" element={<SettingsLayout />}>
  <Route path="profile" element={<ProfileSettings />} />
  <Route path="preferences" element={<PreferencesSettings />} />
  <Route path="security" element={<SecuritySettings />} />
  <Route path="deployment" element={<DeploymentSettings />} />
  <Route path="api-keys" element={<ApiKeysSettings />} />
  <Route path="billing" element={<BillingSettings />} />
</Route>
```

## MarketplaceLayout

### Purpose

An adaptive layout that provides different experiences for authenticated and unauthenticated users while:
- Avoiding route duplication (single route definition)
- Maintaining non-blocking behavior (content renders immediately)
- Providing auth state via context (no duplicate checks in children)
- Supporting SEO with immediate public view rendering

### Authentication Strategy

The layout implements a non-blocking auth check pattern:

```typescript
type AuthState = 'loading' | 'authenticated' | 'unauthenticated';

// Fast path: Token in localStorage (instant)
const token = localStorage.getItem('token');
if (token) {
  setAuthState('authenticated');
  return;
}

// Slow path: Cookie-based auth check (OAuth users)
// Uses raw axios to bypass 401 redirect interceptor
const response = await axios.get(`${API_URL}/api/users/me`, {
  withCredentials: true,
});
```

### View Selection

| Auth State | View | Components |
|------------|------|------------|
| `loading` | Public | PublicMarketplaceHeader + Outlet + PublicMarketplaceFooter |
| `unauthenticated` | Public | PublicMarketplaceHeader + Outlet + PublicMarketplaceFooter |
| `authenticated` | Dashboard | NavigationSidebar + Outlet |

**Design Decision**: During loading, the public view is shown intentionally for:
1. SEO (crawlers see content immediately)
2. Performance (no blocking render)
3. UX (content appears instantly)

### MarketplaceAuthContext

The layout provides auth state to all child components via context:

```typescript
interface MarketplaceAuthContextValue {
  isAuthenticated: boolean;
  isLoading: boolean;
}

// In child components
import { useMarketplaceAuth } from '../contexts/MarketplaceAuthContext';

function MarketplaceDetail() {
  const { isAuthenticated, isLoading } = useMarketplaceAuth();

  // Show purchase button only for authenticated users
  return (
    <div>
      {isAuthenticated && <PurchaseButton />}
      {!isAuthenticated && <SignUpPrompt />}
    </div>
  );
}
```

### Active Page Detection

The layout determines the active sidebar page based on the current path:

```typescript
const activePage = useMemo((): 'dashboard' | 'marketplace' | 'library' | 'feedback' => {
  const path = location.pathname;
  if (path.includes('/marketplace')) return 'marketplace';
  if (path.includes('/library')) return 'library';
  if (path.includes('/feedback')) return 'feedback';
  return 'dashboard';
}, [location.pathname]);
```

## PublicMarketplaceHeader

### Purpose

A responsive header for public marketplace visitors featuring:
- Brand logo and navigation
- Desktop nav links (Explore, Agents, Templates)
- Theme toggle
- Auth CTAs (Sign In, Sign Up)
- Mobile hamburger menu

### Key Props

```typescript
interface PublicMarketplaceHeaderProps {
  isLoading?: boolean;  // Hides auth buttons during loading to prevent flash
}
```

### Navigation Links

| Link | Route | Purpose |
|------|-------|---------|
| Explore | `/marketplace` | Marketplace home |
| Agents | `/marketplace/browse/agent` | AI agents listing |
| Templates | `/marketplace/browse/base` | Project templates |

### Responsive Behavior

- **Desktop (md+)**: Full nav links, Sign In text button, Sign Up primary button
- **Mobile**: Hamburger menu, Sign Up button only (shortened text)

### Theme Integration

```typescript
const { theme, toggleTheme } = useTheme();

// Theme-aware styling
className={`
  ${theme === 'light'
    ? 'bg-white/90 border-black/10'
    : 'bg-[#0a0a0a]/90 border-white/10'}
`}
```

## PublicMarketplaceFooter

### Purpose

An SEO-friendly footer providing:
- Category navigation links for crawlers
- Company links
- Sign up CTA
- Copyright notice

### Link Sections

| Section | Links |
|---------|-------|
| Marketplace | AI Agents, Project Templates, Frontend, Backend |
| Categories | Builder, Fullstack, Data & ML, DevOps |
| Company | About, Sign Up, Sign In |
| Get Started | CTA with description |

### SEO Considerations

- Uses native `<a>` tags (not React Router Links) for proper crawling
- Full hrefs for each category page
- Semantic HTML structure with headings

## Usage Examples

### Adding a New Settings Page

1. Create the page component:
```typescript
// app/src/pages/settings/NewSettings.tsx
export function NewSettings() {
  return (
    <div className="p-6 max-w-2xl">
      <h1 className="text-2xl font-bold mb-6">New Settings</h1>
      {/* Content */}
    </div>
  );
}
```

2. Add route title in SettingsLayout:
```typescript
const routeTitles: Record<string, string> = {
  // ... existing
  '/settings/new': 'New Settings',
};
```

3. Add route in App.tsx:
```typescript
<Route path="/settings" element={<SettingsLayout />}>
  {/* ... existing */}
  <Route path="new" element={<NewSettings />} />
</Route>
```

4. Add link in SettingsSidebar component.

### Accessing Auth State in Marketplace Pages

```typescript
import { useMarketplaceAuth } from '../contexts/MarketplaceAuthContext';

function AgentCard({ agent }) {
  const { isAuthenticated } = useMarketplaceAuth();

  const handleAction = () => {
    if (isAuthenticated) {
      // Direct to purchase/download
      purchaseAgent(agent.id);
    } else {
      // Redirect to sign up
      navigate('/register', { state: { returnTo: `/marketplace/${agent.slug}` }});
    }
  };

  return (
    <div className="agent-card">
      <h3>{agent.name}</h3>
      <button onClick={handleAction}>
        {isAuthenticated ? 'Get Agent' : 'Sign Up to Get'}
      </button>
    </div>
  );
}
```

### Creating a New Layout

```typescript
import { Outlet, useLocation } from 'react-router-dom';
import { motion } from 'framer-motion';

export function MyNewLayout() {
  const location = useLocation();

  return (
    <motion.div
      className="h-screen flex overflow-hidden bg-[var(--bg)]"
      initial={{ opacity: 0.95 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.15 }}
    >
      {/* Sidebar or header */}
      <MySidebar />

      {/* Main content area */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <Outlet />
      </div>
    </motion.div>
  );
}
```

## Best Practices

### 1. Non-blocking Auth Checks

Never block the initial render for auth checks:
```typescript
// Good: Show public view during loading
if (authState === 'authenticated') {
  return <AuthenticatedView />;
}
return <PublicView />; // Shown during loading AND unauthenticated

// Bad: Show loading spinner
if (authState === 'loading') {
  return <Spinner />; // Blocks content, hurts SEO
}
```

### 2. Mobile Touch Targets

Always use minimum 44px touch targets:
```typescript
<button className="min-h-[44px] min-w-[44px]">
  <Icon size={18} />
</button>
```

### 3. Safe Area Support

Support notched devices with env() CSS:
```typescript
className="pt-[env(safe-area-inset-top)] h-[calc(48px+env(safe-area-inset-top))]"
```

### 4. Theme-aware Styling

Use CSS custom properties with fallbacks:
```typescript
className={`
  bg-[var(--sidebar-bg)]
  border-[var(--sidebar-border)]
  text-[var(--sidebar-text)]
`}
```

### 5. Context Provider Placement

Wrap entire layout output with context provider:
```typescript
return (
  <MyContext.Provider value={contextValue}>
    <div className="layout">
      {/* All children have access to context */}
      <Outlet />
    </div>
  </MyContext.Provider>
);
```

## Common Issues

### Issue: Auth buttons flash briefly on load

**Symptom**: Sign In/Sign Up buttons appear then disappear for authenticated users

**Solution**: Hide auth buttons during loading state:
```typescript
{!isLoading && (
  <>
    <SignInButton />
    <SignUpButton />
  </>
)}
```

### Issue: Mobile drawer not closing on navigation

**Symptom**: Drawer stays open after clicking a link

**Solution**: Pass `onClose` callback and call it in the sidebar:
```typescript
<SettingsSidebarMobile onClose={handleCloseMobileMenu} />

// In SettingsSidebarMobile
const handleNavClick = (path: string) => {
  navigate(path);
  onClose(); // Close drawer after navigation
};
```

### Issue: Layout flickers between views

**Symptom**: Visible jump between public and authenticated views

**Solution**: Use subtle opacity transition:
```typescript
<motion.div
  initial={{ opacity: 0.95 }}
  animate={{ opacity: 1 }}
  transition={{ duration: 0.15 }}
>
```

### Issue: Sidebar width inconsistent on different screens

**Symptom**: Mobile drawer too wide or narrow

**Solution**: Use responsive width constraints:
```typescript
className="w-[70vw] max-w-[240px] min-w-[180px]"
```

## File Organization

```
app/src/
├── layouts/
│   ├── SettingsLayout.tsx        # Settings two-column layout
│   ├── MarketplaceLayout.tsx     # Adaptive public/auth layout
│   ├── PublicMarketplaceHeader.tsx  # Public header component
│   └── PublicMarketplaceFooter.tsx  # Public footer component
│
├── contexts/
│   └── MarketplaceAuthContext.tsx   # Auth context for marketplace
│
├── components/
│   ├── settings/
│   │   └── SettingsSidebar.tsx   # Desktop and mobile sidebar
│   ├── ui/
│   │   └── NavigationSidebar.tsx # Main app sidebar
│   └── MobileWarning.tsx         # Mobile device warning
│
└── pages/
    ├── settings/                  # Settings pages (children of SettingsLayout)
    │   ├── ProfileSettings.tsx
    │   ├── PreferencesSettings.tsx
    │   └── ...
    │
    └── Marketplace*.tsx          # Marketplace pages (children of MarketplaceLayout)
```
