# State Management Context for Claude

## Key Files

| File | Purpose |
|------|---------|
| `app/src/services/taskService.ts` | Background task WebSocket singleton |
| `app/src/theme/ThemeContext.tsx` | Theme state and provider |
| `app/src/theme/variables.css` | CSS custom properties |
| `app/src/hooks/useTask.ts` | Task tracking hooks |
| `app/src/hooks/useTaskNotifications.ts` | Toast notifications for tasks |
| `app/src/hooks/useReferralTracking.ts` | Affiliate tracking |
| `app/src/hooks/useContainerStartup.ts` | Container startup lifecycle with health checks |

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
│   ├── ThemeContext.tsx
│   ├── variables.css
│   ├── fonts.ts
│   └── index.ts
└── hooks/              # Custom hooks
    ├── useTask.ts
    ├── useTaskNotifications.ts
    ├── useReferralTracking.ts
    └── useContainerStartup.ts  # Container startup lifecycle
```
