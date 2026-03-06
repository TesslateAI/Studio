# Settings UI Components

This document provides comprehensive documentation for the settings UI component system used in Tesslate Studio. These components create a consistent, responsive settings experience across all settings pages.

## Component Hierarchy Overview

The settings components follow a hierarchical structure that separates layout concerns from content:

```
SettingsLayout (Layout wrapper)
├── SettingsSidebar / SettingsSidebarMobile (Navigation)
└── SettingsSection (Page container)
    └── SettingsGroup (Card grouping)
        └── SettingsItem (Individual setting row)
```

**Data Flow:**
1. `SettingsLayout` provides the overall page structure with sidebar navigation
2. `SettingsSection` wraps page content with title and description
3. `SettingsGroup` creates visual card groupings for related settings
4. `SettingsItem` displays individual settings with labels and controls

## Source Files

| Component | Path |
|-----------|------|
| SettingsSection | `app/src/components/settings/SettingsSection.tsx` |
| SettingsSidebar | `app/src/components/settings/SettingsSidebar.tsx` |
| SettingsSidebarMobile | `app/src/components/settings/SettingsSidebar.tsx` |
| SettingsGroup | `app/src/components/settings/SettingsGroup.tsx` |
| SettingsItem | `app/src/components/settings/SettingsItem.tsx` |
| Index (exports) | `app/src/components/settings/index.ts` |
| SettingsLayout | `app/src/layouts/SettingsLayout.tsx` |

---

## SettingsSection

The top-level wrapper for settings page content. Provides consistent page headers and spacing.

### Props

```typescript
interface SettingsSectionProps {
  title: string;        // Main heading for the settings page
  description?: string; // Optional subtitle/description text
  children: ReactNode;  // Content (typically SettingsGroup components)
}
```

### Features

- Centered content with `max-w-3xl` constraint
- Responsive padding (`p-4` on mobile, `p-8` on desktop)
- Consistent heading styles with `text-2xl`/`text-3xl`
- Vertical spacing between child elements via `space-y-6`

### Usage Example

```tsx
import { SettingsSection, SettingsGroup, SettingsItem } from '../../components/settings';

export default function ProfileSettings() {
  return (
    <SettingsSection
      title="Profile"
      description="Manage your profile information and how you appear to others"
    >
      <SettingsGroup title="Basic Information">
        {/* SettingsItem components here */}
      </SettingsGroup>
    </SettingsSection>
  );
}
```

### Styling

| Element | Classes |
|---------|---------|
| Container | `max-w-3xl mx-auto p-4 md:p-8` |
| Title | `text-2xl md:text-3xl font-bold text-[var(--text)]` |
| Description | `text-sm md:text-base text-[var(--text)]/60` |
| Content wrapper | `space-y-6` |

---

## SettingsSidebar

The desktop navigation sidebar for settings pages. Supports collapsible state with smooth animations.

### Props

```typescript
interface SettingsSidebarProps {
  onClose?: () => void;       // Optional callback when navigating away
  showContent?: boolean;      // Controls content visibility (default: true)
}
```

### Features

- **Collapsible:** Toggles between expanded (192px) and collapsed (48px) states
- **Persistent state:** Remembers collapse state via localStorage (`settingsSidebarExpanded`)
- **Animated transitions:** Uses Framer Motion with spring physics
- **Tooltips:** Shows tooltips on hover when collapsed
- **Active route highlighting:** Indicates current page with distinct background
- **Back navigation:** Quick link to dashboard

### Navigation Structure

The sidebar organizes navigation into sections:

```typescript
const navSections: NavSection[] = [
  {
    title: 'ACCOUNT',
    items: [
      { label: 'Profile', path: '/settings/profile', icon: User },
      { label: 'Preferences', path: '/settings/preferences', icon: Settings },
      { label: 'Security', path: '/settings/security', icon: Shield },
    ],
  },
  {
    title: 'INTEGRATIONS',
    items: [
      { label: 'Deployment', path: '/settings/deployment', icon: Cloud },
      { label: 'API Keys', path: '/settings/api-keys', icon: Key },
    ],
  },
  {
    title: 'BILLING',
    items: [
      { label: 'Subscription', path: '/settings/billing', icon: CreditCard },
    ],
  },
];
```

### Usage Example

```tsx
import { SettingsSidebar } from '../components/settings/SettingsSidebar';

function SettingsLayout() {
  return (
    <div className="h-screen flex">
      <div className="flex-shrink-0 h-full">
        <SettingsSidebar />
      </div>
      <main className="flex-1">
        <Outlet />
      </main>
    </div>
  );
}
```

### Styling

| State | Width | Layout |
|-------|-------|--------|
| Expanded | 192px | Icons + labels, section titles visible |
| Collapsed | 48px | Icons only, tooltips on hover |

**Animation configuration:**
```typescript
{
  type: 'spring',
  stiffness: 700,
  damping: 28,
  mass: 0.4,
}
```

### CSS Variables Used

- `--sidebar-bg`: Background color
- `--sidebar-border`: Border color
- `--sidebar-text`: Text color
- `--sidebar-active`: Active item background
- `--sidebar-hover`: Hover state background

---

## SettingsSidebarMobile

A mobile-optimized version of the sidebar, always expanded and designed for drawer presentation.

### Props

```typescript
interface SettingsSidebarMobileProps {
  onClose: () => void;  // Required callback to close the drawer
}
```

### Features

- Always-expanded layout (no collapse toggle)
- Larger touch targets (`h-11` vs `h-9` for nav items, `min-h-[44px]` for buttons)
- Same navigation structure as desktop sidebar
- Calls `onClose()` after navigation to dismiss drawer

### Usage Example

```tsx
import { SettingsSidebarMobile } from '../components/settings/SettingsSidebar';

function MobileDrawer({ isOpen, onClose }) {
  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div className="fixed inset-y-0 left-0 w-[70vw] max-w-[240px]">
          <SettingsSidebarMobile onClose={onClose} />
        </motion.div>
      )}
    </AnimatePresence>
  );
}
```

---

## SettingsGroup

Groups related settings together in a card-like container with a header.

### Props

```typescript
interface SettingsGroupProps {
  title: string;        // Group header text
  children: ReactNode;  // Content (typically SettingsItem components)
}
```

### Features

- Card styling with rounded corners and border
- Distinct header section with bottom border
- Dividers between child items
- Responsive padding

### Usage Example

```tsx
<SettingsGroup title="Basic Information">
  <SettingsItem
    label="Display Name"
    description="Your name as shown to other users"
    control={<input type="text" />}
  />
  <SettingsItem
    label="Bio"
    description="A short description about yourself"
    control={<textarea />}
  />
</SettingsGroup>
```

### Styling

| Element | Classes |
|---------|---------|
| Container | `bg-[var(--surface)] border border-white/10 rounded-xl overflow-hidden` |
| Header | `px-4 md:px-6 py-3 md:py-4 border-b border-white/10` |
| Title | `text-sm font-semibold text-[var(--text)]` |
| Items wrapper | `divide-y divide-white/10` |

---

## SettingsItem

Individual setting row with label, optional description, and control element.

### Props

```typescript
interface SettingsItemProps {
  label: string;         // Primary label text
  description?: string;  // Optional secondary description
  control: ReactNode;    // Form control (input, select, toggle, etc.)
}
```

### Features

- Responsive layout: stacked on mobile, horizontal on desktop
- Hover state with subtle background change
- Flexible control slot for any form element
- Minimum height for consistent spacing

### Usage Example

```tsx
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

### Layout Behavior

| Breakpoint | Layout |
|------------|--------|
| Mobile (`< sm`) | Stacked: label/description above control |
| Desktop (`>= sm`) | Horizontal: label/description left, control right |

### Styling

| Element | Classes |
|---------|---------|
| Container | `flex flex-col sm:flex-row sm:items-center justify-between gap-3 sm:gap-4 px-4 md:px-6 py-3 md:py-4 min-h-[48px] hover:bg-white/[0.02]` |
| Label | `text-sm font-medium text-[var(--text)]` |
| Description | `text-xs text-[var(--text)]/50 mt-0.5` |
| Control wrapper | `flex-shrink-0` |

---

## Responsive Behavior

### Desktop (md and above)

- Sidebar is visible and collapsible
- Settings content has larger padding
- SettingsItem displays horizontally
- Controls have fixed widths (e.g., `sm:w-64`)

### Mobile (below md)

- Sidebar is hidden; navigation via slide-out drawer
- Fixed header with back button and hamburger menu
- Settings content has tighter padding
- SettingsItem stacks vertically
- Controls expand to full width
- Larger touch targets (44px minimum)
- Safe area insets for notched devices

### Mobile Header (in SettingsLayout)

The layout provides a mobile header with:
- Back button (navigates to `/dashboard`)
- Current page title
- Menu button (opens drawer)

```tsx
<div className="md:hidden fixed top-0 left-0 right-0 z-40 bg-[var(--sidebar-bg)]">
  <button onClick={() => navigate('/dashboard')}>
    <ArrowLeft /> Back
  </button>
  <h1>{currentTitle}</h1>
  <button onClick={() => setIsMobileMenuOpen(true)}>
    <Menu />
  </button>
</div>
```

### Mobile Drawer Animation

```typescript
// Backdrop
initial={{ opacity: 0 }}
animate={{ opacity: 1 }}
exit={{ opacity: 0 }}

// Drawer
initial={{ x: '-100%' }}
animate={{ x: 0 }}
exit={{ x: '-100%' }}
transition={{
  type: 'spring',
  stiffness: 400,
  damping: 30
}}
```

---

## Theming and Styling

### CSS Variables

The settings components use theme-aware CSS variables:

| Variable | Usage |
|----------|-------|
| `--bg` | Main background color |
| `--text` | Primary text color |
| `--surface` | Card/group background |
| `--primary` | Focus rings, active states |
| `--sidebar-bg` | Sidebar background |
| `--sidebar-border` | Sidebar borders |
| `--sidebar-text` | Sidebar text |
| `--sidebar-active` | Active nav item background |
| `--sidebar-hover` | Hover state background |

### Common Control Styling

For consistency, form controls should follow this pattern:

```tsx
// Input
<input
  className="w-full sm:w-64 px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-base text-[var(--text)] placeholder-[var(--text)]/40 focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
/>

// Select
<select
  className="w-full sm:w-48 px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-base text-[var(--text)] focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
/>

// Textarea
<textarea
  className="w-full sm:w-64 px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-base text-[var(--text)] placeholder-[var(--text)]/40 focus:outline-none focus:ring-2 focus:ring-[var(--primary)] resize-none"
/>
```

---

## Complete Usage Example

Here is a complete example of a settings page using all components:

```tsx
import { useState, useEffect } from 'react';
import toast from 'react-hot-toast';
import { Check } from 'lucide-react';
import { SettingsSection, SettingsGroup, SettingsItem } from '../../components/settings';
import { ToggleSwitch } from '../../components/ui/ToggleSwitch';
import { LoadingSpinner } from '../../components/PulsingGridSpinner';

export default function ExampleSettings() {
  const [loading, setLoading] = useState(true);
  const [formData, setFormData] = useState({
    name: '',
    emailNotifications: true,
    selectedOption: 'option1',
  });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    // Load settings from API
    loadSettings().then((data) => {
      setFormData(data);
      setLoading(false);
    });
  }, []);

  const handleSave = async () => {
    setSaving(true);
    try {
      await saveSettings(formData);
      toast.success('Settings saved successfully');
    } catch (error) {
      toast.error('Failed to save settings');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--bg)]">
        <LoadingSpinner message="Loading settings..." size={60} />
      </div>
    );
  }

  return (
    <SettingsSection
      title="Example Settings"
      description="Configure your example settings here"
    >
      {/* Text Input Group */}
      <SettingsGroup title="General">
        <SettingsItem
          label="Display Name"
          description="Your name as shown to other users"
          control={
            <input
              type="text"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              placeholder="Enter your name"
              className="w-full sm:w-64 px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-base text-[var(--text)] placeholder-[var(--text)]/40 focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
            />
          }
        />
      </SettingsGroup>

      {/* Toggle Group */}
      <SettingsGroup title="Notifications">
        <SettingsItem
          label="Email notifications"
          description="Receive email updates about your projects"
          control={
            <ToggleSwitch
              active={formData.emailNotifications}
              onChange={(active) => setFormData({ ...formData, emailNotifications: active })}
            />
          }
        />
      </SettingsGroup>

      {/* Select Group */}
      <SettingsGroup title="Preferences">
        <SettingsItem
          label="Default option"
          description="Select your preferred option"
          control={
            <select
              value={formData.selectedOption}
              onChange={(e) => setFormData({ ...formData, selectedOption: e.target.value })}
              className="w-full sm:w-48 px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-base text-[var(--text)] focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
            >
              <option value="option1">Option 1</option>
              <option value="option2">Option 2</option>
              <option value="option3">Option 3</option>
            </select>
          }
        />
      </SettingsGroup>

      {/* Save Button */}
      <div className="flex justify-end">
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-6 py-3 bg-[var(--primary)] hover:bg-[var(--primary-hover)] disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded-lg font-semibold transition-all flex items-center gap-2 min-h-[48px]"
        >
          {saving ? (
            <>
              <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
              </svg>
              Saving...
            </>
          ) : (
            <>
              <Check size={18} />
              Save Changes
            </>
          )}
        </button>
      </div>
    </SettingsSection>
  );
}
```

---

## Adding New Settings Pages

To add a new settings page:

1. **Create the page component** in `app/src/pages/settings/`:

```tsx
// app/src/pages/settings/NewSettings.tsx
import { SettingsSection, SettingsGroup, SettingsItem } from '../../components/settings';

export default function NewSettings() {
  return (
    <SettingsSection title="New Settings" description="Description here">
      <SettingsGroup title="Group Name">
        <SettingsItem label="Setting" control={<input />} />
      </SettingsGroup>
    </SettingsSection>
  );
}
```

2. **Add the route** in your router configuration:

```tsx
{
  path: 'settings',
  element: <SettingsLayout />,
  children: [
    // ... existing routes
    { path: 'new-page', element: <NewSettings /> },
  ],
}
```

3. **Add navigation item** in `SettingsSidebar.tsx`:

```typescript
const navSections: NavSection[] = [
  {
    title: 'SECTION_NAME',
    items: [
      // ... existing items
      { label: 'New Page', path: '/settings/new-page', icon: SomeIcon },
    ],
  },
];
```

4. **Add route title** in `SettingsLayout.tsx`:

```typescript
const routeTitles: Record<string, string> = {
  // ... existing titles
  '/settings/new-page': 'New Page',
};
```

---

## Related Documentation

- [Theme System](../state/theme.md) - How theming works with CSS variables
- [UI Components](../../components/ui/index.md) - Reusable UI components like ToggleSwitch
- [Layout Components](../layouts.md) - Application layout patterns
