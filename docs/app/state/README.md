# Tesslate Studio State Management

Tesslate Studio uses a lightweight state management approach without Redux. State is managed through React Context, service singletons, and localStorage persistence.

## Architecture Overview

```
app/src/
├── services/
│   └── taskService.ts        # Background task tracking singleton
├── theme/
│   ├── ThemeContext.tsx      # Theme state and toggle
│   ├── variables.css         # CSS custom properties
│   ├── fonts.ts              # Font configuration
│   └── index.ts              # Public exports
└── hooks/
    ├── useTask.ts            # Task tracking hooks
    ├── useTaskNotifications.ts # Toast notifications
    └── useReferralTracking.ts  # Affiliate tracking
```

## State Management Patterns

### 1. React Context Pattern

Used for global state that needs to be accessed by many components:

```typescript
// Create context
const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

// Provider component
export function ThemeProvider({ children }: ThemeProviderProps) {
  const [theme, setTheme] = useState<'light' | 'dark'>('dark');
  // ...
  return (
    <ThemeContext.Provider value={{ theme, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

// Consumer hook
export function useTheme() {
  const context = useContext(ThemeContext);
  if (context === undefined) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
}
```

### 2. Service Singleton Pattern

Used for services that need to maintain state across the app lifecycle:

```typescript
class TaskService {
  private ws: WebSocket | null = null;
  private taskCallbacks: Map<string, TaskCallback[]> = new Map();

  connect(token: string): void { /* ... */ }
  disconnect(): void { /* ... */ }
  subscribeToTask(taskId: string, callback: TaskCallback): () => void { /* ... */ }
}

// Singleton instance
export const taskService = new TaskService();
```

### 3. LocalStorage Persistence

Used for user preferences that should persist across sessions:

```typescript
// Save to localStorage
localStorage.setItem('theme', theme);

// Load from localStorage with fallback
const saved = localStorage.getItem('theme');
return (saved as 'light' | 'dark') || 'dark';
```

### 4. SessionStorage for Transient Data

Used for data that should persist only during the session:

```typescript
// Referral tracking
sessionStorage.setItem('referrer', ref);
sessionStorage.setItem('referral_tracked', 'true');
```

## State Categories

| Category | Storage | Pattern | Documentation |
|----------|---------|---------|---------------|
| Theme | localStorage | Context | [theme.md](./theme.md) |
| Tasks | Memory + API | Singleton | [task-service.md](./task-service.md) |
| Auth Token | localStorage | API interceptor | [../api/core-api.md](../api/core-api.md) |
| CSRF Token | Memory | Module variable | [../api/core-api.md](../api/core-api.md) |
| Referrals | sessionStorage | Hook | [hooks.md](./hooks.md) |
| App Config | Memory (cached) | API | [../api/core-api.md](../api/core-api.md) |

## Why No Redux?

Tesslate Studio avoids Redux for several reasons:

1. **Component-local state** - Most state is local to components
2. **API-driven** - Data comes from the API, not stored globally
3. **Simplicity** - Context + hooks covers all use cases
4. **Bundle size** - No additional dependencies
5. **WebSocket integration** - Task service handles real-time updates

## State Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                     Application State                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────┐  │
│  │  Theme      │    │  Task       │    │  Auth               │  │
│  │  Context    │    │  Service    │    │  (localStorage)     │  │
│  │             │    │             │    │                     │  │
│  │ - theme     │    │ - ws conn   │    │ - token             │  │
│  │ - toggle    │    │ - callbacks │    │ - csrfToken (mem)   │  │
│  └──────┬──────┘    └──────┬──────┘    └──────────┬──────────┘  │
│         │                  │                       │             │
│         ▼                  ▼                       ▼             │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                    React Components                          ││
│  │                                                              ││
│  │  useTheme()     useTask()      API interceptors              ││
│  │  useActiveTasks()              getAuthHeaders()              ││
│  │  useTaskNotifications()                                      ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Best Practices

### 1. Prefer Local State

```typescript
// Good - local state for component-specific data
const [isOpen, setIsOpen] = useState(false);

// Avoid - global state for component-specific data
const { isModalOpen } = useGlobalState(); // overkill
```

### 2. Use Context for Shared UI State

```typescript
// Good - theme affects many components
<ThemeProvider>
  <App />
</ThemeProvider>
```

### 3. Use Services for Background Operations

```typescript
// Good - singleton service for WebSocket
taskService.connect(token);
taskService.subscribeToTask(taskId, callback);
```

### 4. Persist User Preferences

```typescript
// Good - remember user's theme choice
useEffect(() => {
  localStorage.setItem('theme', theme);
}, [theme]);
```

## Related Documentation

- [Theme System](./theme.md) - Theme context and CSS variables
- [Task Service](./task-service.md) - Background task tracking
- [Custom Hooks](./hooks.md) - Task and referral hooks
