# Settings Pages Architecture

This document describes the modular settings architecture used in Tesslate Studio's frontend application.

## Overview

The settings system is organized as a **modular tab-based architecture** with 6 independent settings pages. Each page is a standalone component that handles its own state and API calls, rendered within a shared layout that provides consistent navigation.

### Architecture Diagram

```
/settings
├── SettingsLayout (shared layout with sidebar)
│   ├── SettingsSidebar (desktop, collapsible)
│   ├── SettingsSidebarMobile (mobile drawer)
│   └── <Outlet /> (renders child routes)
│
├── /profile      → ProfileSettings
├── /preferences  → PreferencesSettings
├── /security     → SecuritySettings
├── /deployment   → DeploymentSettings
├── /api-keys     → ApiKeysSettings
└── /billing      → BillingSettings
```

## Route Structure

Settings routes are defined in `app/src/App.tsx` as nested routes under `/settings`:

```tsx
<Route
  path="/settings"
  element={
    <PrivateRoute>
      <SettingsLayout />
    </PrivateRoute>
  }
>
  <Route index element={<Navigate to="/settings/profile" replace />} />
  <Route path="profile" element={<ProfileSettings />} />
  <Route path="preferences" element={<PreferencesSettings />} />
  <Route path="security" element={<SecuritySettings />} />
  <Route path="deployment" element={<DeploymentSettings />} />
  <Route path="api-keys" element={<ApiKeysSettings />} />
  <Route path="billing" element={<BillingSettings />} />
</Route>
```

**Key Points:**
- All settings routes require authentication (`PrivateRoute` wrapper)
- The index route (`/settings`) redirects to `/settings/profile`
- Each tab is a separate component file in `app/src/pages/settings/`

### Route-to-Tab Mapping

| Route | Component | Purpose |
|-------|-----------|---------|
| `/settings/profile` | `ProfileSettings` | User profile information |
| `/settings/preferences` | `PreferencesSettings` | Theme, AI settings, notifications |
| `/settings/security` | `SecuritySettings` | Password, 2FA, sessions |
| `/settings/deployment` | `DeploymentSettings` | Cloud provider connections |
| `/settings/api-keys` | `ApiKeysSettings` | LLM API key management |
| `/settings/billing` | `BillingSettings` | Subscription management |

## SettingsLayout Pattern

**File:** `app/src/layouts/SettingsLayout.tsx`

The `SettingsLayout` component provides the shell for all settings pages:

### Features

1. **Desktop Sidebar** - Collapsible navigation with section groupings (ACCOUNT, INTEGRATIONS, BILLING)
2. **Mobile Navigation** - Slide-out drawer with hamburger menu
3. **Back Navigation** - Quick return to dashboard
4. **Dynamic Title** - Header displays current page title based on route

### Structure

```tsx
export function SettingsLayout() {
  return (
    <motion.div className="h-screen flex overflow-hidden bg-[var(--bg)]">
      {/* Mobile Warning */}
      <MobileWarning />

      {/* Desktop Sidebar - collapsible */}
      <div className="flex-shrink-0 h-full">
        <SettingsSidebar />
      </div>

      {/* Mobile Header (hidden on desktop) */}
      <div className="md:hidden fixed ...">
        {/* Back button, title, hamburger menu */}
      </div>

      {/* Mobile Drawer (AnimatePresence for transitions) */}
      <AnimatePresence>
        {isMobileMenuOpen && <SettingsSidebarMobile onClose={handleClose} />}
      </AnimatePresence>

      {/* Main Content Area */}
      <motion.div className="flex-1 flex flex-col overflow-hidden">
        <main className="flex-1 overflow-y-auto">
          <Outlet />  {/* Child routes render here */}
        </main>
      </motion.div>
    </motion.div>
  );
}
```

### Route Title Mapping

The layout maintains a mapping of routes to display titles for the mobile header:

```tsx
const routeTitles: Record<string, string> = {
  '/settings/profile': 'Profile',
  '/settings/preferences': 'Preferences',
  '/settings/security': 'Security',
  '/settings/deployment': 'Deployment',
  '/settings/api-keys': 'API Keys',
  '/settings/billing': 'Billing',
};
```

## Settings Pages

### 1. ProfileSettings

**File:** `app/src/pages/settings/ProfileSettings.tsx`

Manages user profile information including:
- **Profile Picture** - Image upload with size limits (200KB max)
- **Basic Information** - Display name, bio
- **Social Links** - Twitter, GitHub, website URL
- **Email Display** - Read-only email with support contact note

**API Calls:**
- `usersApi.getProfile()` - Load current profile
- `usersApi.updateProfile(data)` - Save profile changes

**State Management:**
```tsx
const [profile, setProfile] = useState<UserProfile | null>(null);
const [profileForm, setProfileForm] = useState<UserProfileUpdate>({});
const [savingProfile, setSavingProfile] = useState(false);
```

### 2. PreferencesSettings

**File:** `app/src/pages/settings/PreferencesSettings.tsx`

Controls user experience preferences:
- **Theme Selection** - Dark and light theme presets with live preview cards
- **AI Settings** - Architecture diagram model selection (Claude, GPT-4)
- **Notifications** - Email and marketing preferences (placeholder for future)

**Key Features:**
- `ThemeCard` component renders color swatches and border radius previews
- Theme changes are immediately applied via `useTheme()` hook
- Themes persist via `ThemeContext` (syncs with backend)

**API Calls:**
- `usersApi.getPreferences()` - Load user preferences
- `usersApi.updatePreferences({ diagram_model })` - Save AI model preference

### 3. SecuritySettings

**File:** `app/src/pages/settings/SecuritySettings.tsx`

Security-related settings (currently placeholders):
- **Password Change** - Coming soon
- **Two-Factor Authentication** - Coming soon
- **Session Management** - Coming soon

**Note:** This page displays placeholder buttons with toast notifications indicating features are coming soon.

### 4. DeploymentSettings

**File:** `app/src/pages/settings/DeploymentSettings.tsx`

Manages cloud deployment provider connections:
- **Connected Providers** - Shows currently linked accounts with metadata
- **Available Providers** - OAuth or API token connection options
- **Provider Types** - Cloudflare, Vercel, Netlify

**Features:**
- OAuth flow initiation for supported providers
- Manual API token entry via modal
- Secure credential storage with encryption notice
- Disconnect functionality with confirmation

**API Calls:**
- `deploymentCredentialsApi.getProviders()` - List available providers
- `deploymentCredentialsApi.list()` - Get connected credentials
- `deploymentCredentialsApi.startOAuth(provider)` - Start OAuth flow
- `deploymentCredentialsApi.saveManual(provider, credentials)` - Save API token
- `deploymentCredentialsApi.delete(credentialId)` - Remove connection

**Uses Parallel Loading:**
```tsx
const { executeAll } = useCancellableParallelRequests();

executeAll(
  [
    () => deploymentCredentialsApi.getProviders(),
    () => deploymentCredentialsApi.list(),
  ],
  {
    onAllSuccess: ([providers, credentials]) => { ... },
    onError: (error) => { ... },
    onFinally: () => setLoading(false),
  }
);
```

### 5. ApiKeysSettings

**File:** `app/src/pages/settings/ApiKeysSettings.tsx`

LLM provider API key management (placeholder):
- Displays "Coming Soon" notice
- Will support OpenRouter, Anthropic, OpenAI keys

### 6. BillingSettings

**File:** `app/src/pages/settings/BillingSettings.tsx`

Quick access to billing features (navigates to dedicated billing pages):
- **Current Plan** - Link to `/billing`
- **Upgrade Plan** - Link to `/billing/plans`
- **Usage Dashboard** - Link to `/billing/usage`
- **Transaction History** - Link to `/billing/transactions`

## Common Patterns

### useCancellableRequest Hook

**File:** `app/src/hooks/useCancellableRequest.ts`

All settings pages use `useCancellableRequest` to prevent memory leaks on unmount:

```tsx
const { execute: executeLoad } = useCancellableRequest<UserProfile>();

const loadProfile = useCallback(() => {
  executeLoad(
    (signal) => usersApi.getProfile(),
    {
      onSuccess: (data) => {
        setProfile(data);
        setProfileForm({ ...data });
      },
      onError: (error) => {
        toast.error(error.message || 'Failed to load profile');
      },
      onFinally: () => setLoading(false),
    }
  );
}, [executeLoad]);

useEffect(() => {
  loadProfile();
}, [loadProfile]);
```

**Benefits:**
- Automatically aborts in-flight requests on unmount
- Prevents state updates on unmounted components
- Silently ignores abort errors
- Handles axios cancel errors

For parallel requests, use `useCancellableParallelRequests`:

```tsx
const { executeAll } = useCancellableParallelRequests();
```

### Form Handling Pattern

Settings pages follow a consistent form handling pattern:

1. **Load initial data** into form state
2. **Track changes** in form state (not modifying original)
3. **Show loading state** during API calls
4. **Display success/error toasts** on completion

```tsx
// 1. State for original data and form
const [profile, setProfile] = useState<UserProfile | null>(null);
const [profileForm, setProfileForm] = useState<UserProfileUpdate>({});
const [savingProfile, setSavingProfile] = useState(false);

// 2. Load and populate form
executeLoad(
  () => usersApi.getProfile(),
  {
    onSuccess: (data) => {
      setProfile(data);
      setProfileForm({
        name: data.name || '',
        bio: data.bio || '',
        // ...other fields
      });
    },
  }
);

// 3. Save handler
const handleSave = async () => {
  setSavingProfile(true);
  try {
    const updated = await usersApi.updateProfile(profileForm);
    setProfile(updated);
    toast.success('Profile updated successfully');
  } catch (error) {
    toast.error('Failed to update profile');
  } finally {
    setSavingProfile(false);
  }
};
```

### Loading States

Each settings page handles loading independently:

```tsx
if (loading) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--bg)]">
      <LoadingSpinner message="Loading profile..." size={60} />
    </div>
  );
}
```

## Settings UI Components

**Directory:** `app/src/components/settings/`

Three composable components provide consistent settings UI:

### SettingsSection

Top-level container for a settings page. Provides max-width, padding, and header.

```tsx
interface SettingsSectionProps {
  title: string;
  description?: string;
  children: ReactNode;
}

<SettingsSection
  title="Profile"
  description="Manage your profile information and how you appear to others"
>
  {/* SettingsGroups go here */}
</SettingsSection>
```

**Styling:**
- Max width: `max-w-3xl`
- Centered with `mx-auto`
- Responsive padding: `p-4 md:p-8`
- Vertical spacing: `space-y-6`

### SettingsGroup

Groups related settings items with a header. Creates a card-like appearance.

```tsx
interface SettingsGroupProps {
  title: string;
  children: ReactNode;
}

<SettingsGroup title="Basic Information">
  <SettingsItem label="Display Name" control={...} />
  <SettingsItem label="Bio" control={...} />
</SettingsGroup>
```

**Styling:**
- Background: `bg-[var(--surface)]`
- Border: `border border-white/10`
- Rounded corners: `rounded-xl`
- Items separated with: `divide-y divide-white/10`

### SettingsItem

Individual setting with label, optional description, and control.

```tsx
interface SettingsItemProps {
  label: string;
  description?: string;
  control: ReactNode;
}

<SettingsItem
  label="Display Name"
  description="Your name as shown to other users"
  control={
    <input
      type="text"
      value={name}
      onChange={(e) => setName(e.target.value)}
      className="w-full sm:w-64 px-3 py-2 bg-white/5 border border-white/10 rounded-lg"
    />
  }
/>
```

**Styling:**
- Responsive layout: column on mobile, row on desktop (`flex-col sm:flex-row`)
- Hover effect: `hover:bg-white/[0.02]`
- Minimum height for touch targets: `min-h-[48px]`

### Usage Example

```tsx
<SettingsSection
  title="Profile"
  description="Manage your profile information"
>
  <SettingsGroup title="Basic Information">
    <SettingsItem
      label="Display Name"
      description="Your name as shown to other users"
      control={<input type="text" ... />}
    />
    <SettingsItem
      label="Bio"
      description="A short description about yourself"
      control={<textarea ... />}
    />
  </SettingsGroup>

  <SettingsGroup title="Social Links">
    <SettingsItem label="Twitter" control={...} />
    <SettingsItem label="GitHub" control={...} />
  </SettingsGroup>
</SettingsSection>
```

## Adding a New Settings Tab

Follow these steps to add a new settings tab:

### 1. Create the Page Component

Create a new file in `app/src/pages/settings/`:

```tsx
// app/src/pages/settings/NotificationsSettings.tsx
import { useState, useEffect, useCallback } from 'react';
import toast from 'react-hot-toast';
import { SettingsSection, SettingsGroup, SettingsItem } from '../../components/settings';
import { LoadingSpinner } from '../../components/PulsingGridSpinner';
import { useCancellableRequest } from '../../hooks/useCancellableRequest';
import { usersApi } from '../../lib/api';

export default function NotificationsSettings() {
  const [loading, setLoading] = useState(true);
  // ... state and logic

  const { execute } = useCancellableRequest();

  // Load data on mount
  useEffect(() => {
    execute(
      () => usersApi.getNotificationSettings(),
      {
        onSuccess: (data) => { /* populate state */ },
        onError: (error) => toast.error('Failed to load settings'),
        onFinally: () => setLoading(false),
      }
    );
  }, [execute]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--bg)]">
        <LoadingSpinner message="Loading notification settings..." size={60} />
      </div>
    );
  }

  return (
    <SettingsSection
      title="Notifications"
      description="Control how you receive notifications"
    >
      <SettingsGroup title="Email Notifications">
        <SettingsItem
          label="Project updates"
          description="Receive emails when projects are deployed"
          control={<ToggleSwitch ... />}
        />
      </SettingsGroup>
    </SettingsSection>
  );
}
```

### 2. Add the Route

In `app/src/App.tsx`, import and add the route:

```tsx
import NotificationsSettings from './pages/settings/NotificationsSettings';

// Inside the /settings route:
<Route path="notifications" element={<NotificationsSettings />} />
```

### 3. Update the Sidebar Navigation

In `app/src/components/settings/SettingsSidebar.tsx`:

1. Add the icon import:
```tsx
import { Bell } from 'lucide-react';
```

2. Add to the appropriate section in `navSections`:
```tsx
const navSections: NavSection[] = [
  {
    title: 'ACCOUNT',
    items: [
      { label: 'Profile', path: '/settings/profile', icon: User },
      { label: 'Preferences', path: '/settings/preferences', icon: Settings },
      { label: 'Notifications', path: '/settings/notifications', icon: Bell },  // NEW
      { label: 'Security', path: '/settings/security', icon: Shield },
    ],
  },
  // ...
];
```

### 4. Update the Layout Title Mapping

In `app/src/layouts/SettingsLayout.tsx`:

```tsx
const routeTitles: Record<string, string> = {
  '/settings/profile': 'Profile',
  '/settings/preferences': 'Preferences',
  '/settings/notifications': 'Notifications',  // NEW
  '/settings/security': 'Security',
  // ...
};
```

### Checklist for New Settings Tab

- [ ] Create page component in `app/src/pages/settings/`
- [ ] Use `SettingsSection`, `SettingsGroup`, `SettingsItem` components
- [ ] Implement `useCancellableRequest` for API calls
- [ ] Handle loading state with `LoadingSpinner`
- [ ] Add route to `App.tsx` under `/settings`
- [ ] Add navigation item to `SettingsSidebar.tsx`
- [ ] Add route title to `SettingsLayout.tsx`
- [ ] Add any required API functions to `app/src/lib/api.ts`
- [ ] Test responsive behavior on mobile and desktop

## File References

| File | Purpose |
|------|---------|
| `app/src/layouts/SettingsLayout.tsx` | Shared layout with sidebar |
| `app/src/components/settings/SettingsSidebar.tsx` | Navigation sidebar (desktop + mobile) |
| `app/src/components/settings/SettingsSection.tsx` | Page-level container component |
| `app/src/components/settings/SettingsGroup.tsx` | Grouped settings card component |
| `app/src/components/settings/SettingsItem.tsx` | Individual setting row component |
| `app/src/components/settings/index.ts` | Exports for settings components |
| `app/src/pages/settings/ProfileSettings.tsx` | Profile management page |
| `app/src/pages/settings/PreferencesSettings.tsx` | Theme and preferences page |
| `app/src/pages/settings/SecuritySettings.tsx` | Security settings page |
| `app/src/pages/settings/DeploymentSettings.tsx` | Cloud provider connections page |
| `app/src/pages/settings/ApiKeysSettings.tsx` | API key management page |
| `app/src/pages/settings/BillingSettings.tsx` | Billing quick links page |
| `app/src/hooks/useCancellableRequest.ts` | Hook for safe API requests |
