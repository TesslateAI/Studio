# State Management Context for Claude

## Key Files

| File | Purpose |
|------|---------|
| `app/src/services/taskService.ts` | Background task WebSocket singleton |
| `app/src/theme/ThemeContext.tsx` | Theme state and provider |
| `app/src/theme/themePresets.ts` | Theme preset loading and caching |
| `app/src/theme/variables.css` | CSS custom properties |
| `app/src/hooks/useTask.ts` | Task tracking hooks |
| `app/src/hooks/useTaskNotifications.ts` | Toast notifications for tasks |
| `app/src/hooks/useReferralTracking.ts` | Affiliate tracking |
| `app/src/hooks/useContainerStartup.ts` | Container startup lifecycle with health checks |
| `app/src/hooks/useCancellableRequest.ts` | AbortController-based API request hook |
| `app/src/hooks/useAuth.ts` | Auth status and user info |
| `app/src/contexts/AuthContext.tsx` | Centralized auth state (single source of truth) |
| `app/src/contexts/CommandContext.tsx` | Command palette dispatch system |
| `app/src/types/theme.ts` | Theme types + runtime validation |

## Related Documentation

- **`docs/app/contexts/CLAUDE.md`**: AuthContext and CommandContext details
- **`docs/app/hooks/CLAUDE.md`**: Custom hooks documentation
- **`docs/app/types/CLAUDE.md`**: Theme types and validation

## Quick Reference

### Adding New Theme Variables

1. Add variable in `variables.css`:
```css
:root {
  --new-color: #value;
}

body.light-mode {
  --new-color: #light-value;
}

body.dark-mode {
  --new-color: #dark-value;
}
```

2. Use in components:
```tsx
<div style={{ color: 'var(--new-color)' }} />
```

### Using Theme in Components

```typescript
import { useTheme } from '../theme';

function MyComponent() {
  const { theme, toggleTheme } = useTheme();

  return (
    <button onClick={toggleTheme}>
      Current: {theme}
    </button>
  );
}
```

### Theme Loading States

The theme system has explicit loading states to handle async theme fetching:

```typescript
import { useTheme } from '../theme';

function PreferencesSettings() {
  const {
    themePreset,           // Current theme object
    availablePresets,      // All available themes
    setThemePreset,        // Change theme by ID
    loadingState,          // 'idle' | 'loading' | 'success' | 'error'
    isReady,               // true when themes loaded OR fallback available
    error,                 // Error message if loading failed
  } = useTheme();

  // Wait for themes to be ready before rendering picker
  if (!isReady) {
    return <SkeletonLoader />;
  }

  return (
    <ThemePicker
      themes={availablePresets}
      selected={themePreset?.id}
      onChange={setThemePreset}
    />
  );
}
```

### Theme State Flow

```
App Mount
    ↓
loadingState: 'idle'
    ↓
Theme API called
    ↓
loadingState: 'loading'
    ↓
┌─────────────────┬──────────────────┐
│ Success         │ Error            │
│ loadingState:   │ loadingState:    │
│ 'success'       │ 'error'          │
│ isReady: true   │ isReady: true    │
│ themes loaded   │ fallback used    │
└─────────────────┴──────────────────┘
```

The `isReady` flag is true in both cases - either themes loaded successfully, or the fallback theme is available. This ensures the UI never blocks waiting for themes.

### Using useThemeWhenReady

For components that must wait for themes:

```typescript
import { useThemeWhenReady } from '../theme';

function ThemeSettings() {
  // Automatically uses fallback if themes not loaded
  const { availablePresets, isReady } = useThemeWhenReady();

  // Always has at least one theme (the fallback)
  return <ThemeGrid themes={availablePresets} />;
}
```

### Subscribing to Tasks

```typescript
import { useTask, useActiveTasks, useTaskPolling } from '../hooks/useTask';

// Track specific task
const { task, loading, error } = useTask(taskId);

// Track all active tasks
const { tasks, loading } = useActiveTasks();

// Poll task until completion
const { task, loading, error } = useTaskPolling(taskId);
```

### Using Cancellable Requests

```typescript
import { useCancellableRequest } from '../hooks/useCancellableRequest';

function MySettings() {
  const [data, setData] = useState(null);
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
    // Cleanup happens automatically on unmount
  }, [execute]);
}
```

### Using Auth Context

```typescript
import { useAuth } from '../contexts/AuthContext';

function MyComponent() {
  const { isAuthenticated, isLoading, user, login, logout } = useAuth();

  if (isLoading) return <Spinner />;
  if (!isAuthenticated) return <Navigate to="/login" />;

  return <div>Hello, {user?.name}</div>;
}
```

### Using Command Context

```typescript
import { useCommandHandlers, useCommandContext } from '../contexts/CommandContext';

// Register handlers in page component
function ProjectPage() {
  useCommandHandlers({
    switchView: setView,
    togglePanel: (panel) => setActivePanel(p => p === panel ? null : panel),
  });
}

// Execute commands from CommandPalette
function CommandPalette() {
  const { executeCommand } = useCommandContext();

  const handleSelect = (cmd) => executeCommand(cmd.id, cmd.args);
}
```

### Using Theme Validation

```typescript
import { isValidTheme, DEFAULT_FALLBACK_THEME } from '../types/theme';

async function loadTheme(themeId: string) {
  const theme = await themesApi.get(themeId);

  if (!isValidTheme(theme)) {
    console.warn('Invalid theme, using fallback');
    return DEFAULT_FALLBACK_THEME;
  }

  return theme;
}
```

### Using Task Service Directly

```typescript
import { taskService } from '../services/taskService';

// Connect WebSocket
taskService.connect(token);

// Subscribe to task updates
const unsubscribe = taskService.subscribeToTask(taskId, (task) => {
  console.log('Task updated:', task.status);
});

// Cleanup
unsubscribe();
taskService.disconnect();
```

## State Patterns

### Context Pattern Template

```typescript
import { createContext, useContext, useState, type ReactNode } from 'react';

interface MyContextType {
  value: string;
  setValue: (v: string) => void;
}

const MyContext = createContext<MyContextType | undefined>(undefined);

export function MyProvider({ children }: { children: ReactNode }) {
  const [value, setValue] = useState('default');

  return (
    <MyContext.Provider value={{ value, setValue }}>
      {children}
    </MyContext.Provider>
  );
}

export function useMyContext() {
  const context = useContext(MyContext);
  if (!context) {
    throw new Error('useMyContext must be used within MyProvider');
  }
  return context;
}
```

### Service Singleton Template

```typescript
type Callback<T> = (data: T) => void;

class MyService {
  private callbacks: Callback<MyData>[] = [];

  subscribe(callback: Callback<MyData>): () => void {
    this.callbacks.push(callback);
    return () => {
      const index = this.callbacks.indexOf(callback);
      if (index > -1) {
        this.callbacks.splice(index, 1);
      }
    };
  }

  private notify(data: MyData): void {
    this.callbacks.forEach(cb => cb(data));
  }
}

export const myService = new MyService();
```

### Custom Hook with Subscription

```typescript
export function useMyData(id: string) {
  const [data, setData] = useState<MyData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);

    // Initial fetch
    myService.getData(id)
      .then(setData)
      .finally(() => setLoading(false));

    // Subscribe to updates
    const unsubscribe = myService.subscribe((updated) => {
      if (updated.id === id) {
        setData(updated);
      }
    });

    return unsubscribe;
  }, [id]);

  return { data, loading };
}
```

## Common Operations

### Enable Task Notifications

```typescript
// In App.tsx or layout component
import { useTaskNotifications } from '../hooks/useTaskNotifications';

function App() {
  useTaskNotifications(); // Enables WebSocket and toast notifications
  return <RouterProvider router={router} />;
}
```

### Track Background Task

```typescript
const { task_id } = await projectsApi.create(name);

// Option 1: Use hook
const { task, loading, error } = useTaskPolling(task_id);

// Option 2: Use service directly
const completedTask = await taskService.pollTaskUntilComplete(task_id);
```

### Persist Preference

```typescript
// Save
localStorage.setItem('preference-key', JSON.stringify(value));

// Load with fallback
const value = JSON.parse(localStorage.getItem('preference-key') || 'null') ?? defaultValue;
```

## CSS Variable Reference

| Variable | Purpose |
|----------|---------|
| `--primary` | Brand orange (#F89521) |
| `--primary-hover` | Hover state |
| `--accent` | Accent blue (#00D9FF) |
| `--bg-dark` | Background color |
| `--surface` | Card/surface color |
| `--text` | Text color |
| `--border-color` | Border color |
| `--status-*` | Status indicator colors |
| `--radius` | Border radius (22px) |
| `--ease` | Animation easing |

## Task Status Types

```typescript
type TaskStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
```

## File Organization

```
app/src/
├── services/           # Singleton services
│   └── taskService.ts
├── theme/              # Theme system
│   ├── ThemeContext.tsx    # Theme provider with loading states
│   ├── themePresets.ts     # Theme loading/caching
│   ├── variables.css
│   ├── fonts.ts
│   └── index.ts
└── hooks/              # Custom hooks
    ├── useTask.ts
    ├── useTaskNotifications.ts
    ├── useReferralTracking.ts
    └── useContainerStartup.ts  # Container startup lifecycle
```
