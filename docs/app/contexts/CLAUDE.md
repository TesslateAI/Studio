# React Contexts Documentation

**Purpose**: This context provides guidance for working with the centralized React context system in Tesslate Studio.

## When to Load This Context

Load this context when:
- Adding new application-wide state
- Working with authentication
- Implementing command/keyboard shortcut features
- Debugging context-related issues
- Understanding the app's state architecture

## Key Files

| File | Purpose |
|------|---------|
| `app/src/contexts/AuthContext.tsx` | Centralized authentication state |
| `app/src/contexts/CommandContext.tsx` | Command palette & keyboard shortcut system |
| `app/src/contexts/MarketplaceAuthContext.tsx` | Marketplace optional auth state |
| `app/src/contexts/auth/types.ts` | Auth error types and utilities |
| `app/src/theme/ThemeContext.tsx` | Theme state and preset management |

## Related Contexts

- **`docs/app/state/CLAUDE.md`**: General state management patterns
- **`docs/app/CLAUDE.md`**: Frontend overview
- **`docs/app/hooks/CLAUDE.md`**: Custom hooks that complement contexts

## Context Architecture

```
App.tsx
├── ThemeProvider (outermost - CSS variables)
│   └── AuthProvider (authentication state)
│       └── CommandProvider (command dispatch)
│           └── Router & Pages
```

## AuthContext

### Purpose

Centralized authentication state management that handles:
- Bearer token authentication (localStorage)
- OAuth cookie-based authentication
- Cross-tab synchronization
- Non-blocking initialization
- Proper error classification

### Key Types

```typescript
interface AuthContextValue {
  status: 'initializing' | 'authenticated' | 'unauthenticated';
  user: AuthUser | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  error: AuthError | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  checkAuth: (options?: { force?: boolean }) => Promise<boolean>;
  clearError: () => void;
}

interface AuthUser {
  id: string;
  email: string;
  name?: string;
  username?: string;
  subscription_tier?: string;
  credits_balance?: number;
}
```

### Usage

```typescript
import { useAuth } from '../contexts/AuthContext';

function MyComponent() {
  const { isAuthenticated, user, isLoading, login, logout } = useAuth();

  if (isLoading) return <Spinner />;

  if (!isAuthenticated) {
    return <LoginPrompt onLogin={login} />;
  }

  return (
    <div>
      Welcome, {user?.name}!
      <button onClick={logout}>Logout</button>
    </div>
  );
}
```

### Error Handling

```typescript
import { AuthenticationError, type AuthErrorCode } from '../contexts/auth/types';

// Error codes
type AuthErrorCode =
  | 'NETWORK_ERROR'      // Network connectivity issues
  | 'INVALID_CREDENTIALS' // Wrong email/password
  | 'SESSION_EXPIRED'     // Token expired
  | 'TOKEN_INVALID'       // Malformed token
  | 'UNAUTHORIZED'        // 401 response
  | 'FORBIDDEN'           // 403 response
  | 'SERVER_ERROR'        // 5xx response
  | 'UNKNOWN';            // Unexpected error

// Check error type
const { error } = useAuth();
if (error?.code === 'SESSION_EXPIRED') {
  // Prompt re-login
}
```

## CommandContext

### Purpose

Replaces fragile CustomEvent dispatching with a context-based command system that:
- Guarantees command delivery
- Provides type safety
- Allows components to register handlers
- Prevents commands from failing silently

### Key Types

```typescript
interface CommandHandlers {
  // Project view commands
  switchView: (view: ViewType) => void;
  togglePanel: (panel: PanelType) => void;
  refreshPreview: () => void;

  // Dashboard commands
  openCreateProject: () => void;

  // Chat commands
  focusChatInput: () => void;
  clearChat: () => void;

  // Editor commands
  saveFile: () => void;
  formatFile: () => void;
}

type ViewType = 'preview' | 'code' | 'kanban' | 'assets' | 'terminal';
type PanelType = 'github' | 'architecture' | 'notes' | 'settings' | 'marketplace' | null;
```

### Registering Handlers

Components that own state register their handlers:

```typescript
import { useCommandHandlers } from '../contexts/CommandContext';

function ProjectPage() {
  const [activeView, setActiveView] = useState<ViewType>('preview');
  const [activePanel, setActivePanel] = useState<PanelType>(null);
  const iframeRef = useRef<HTMLIFrameElement>(null);

  // Register handlers - automatically cleaned up on unmount
  useCommandHandlers({
    switchView: setActiveView,
    togglePanel: (panel) => {
      setActivePanel(prev => prev === panel ? null : panel);
    },
    refreshPreview: () => {
      if (iframeRef.current) {
        iframeRef.current.src = iframeRef.current.src;
      }
    },
  });

  return (/* ... */);
}
```

### Executing Commands

From CommandPalette or other components:

```typescript
import { useCommands } from '../contexts/CommandContext';

function CommandPalette() {
  const { executeCommand, isCommandAvailable } = useCommands();

  const handleSelect = (commandId: string) => {
    switch (commandId) {
      case 'view-code':
        executeCommand('switchView', 'code');
        break;
      case 'toggle-git':
        executeCommand('togglePanel', 'github');
        break;
    }
  };

  // Optionally hide unavailable commands
  const showGitCommand = isCommandAvailable('togglePanel');
}
```

### Type-Safe Command Actions

```typescript
import { useCommandAction } from '../contexts/CommandContext';

function QuickActions() {
  // Returns a type-safe function
  const switchToCode = useCommandAction('switchView');
  const toggleNotes = useCommandAction('togglePanel');

  return (
    <>
      <button onClick={() => switchToCode('code')}>Code</button>
      <button onClick={() => toggleNotes('notes')}>Notes</button>
    </>
  );
}
```

## MarketplaceAuthContext

### Purpose

Lightweight auth context specifically for marketplace pages that:
- Provides optional authentication state
- Avoids duplicate auth checks across marketplace components
- Allows marketplace to be publicly accessible (no auth required)

### Key Types

```typescript
interface MarketplaceAuthContextValue {
  isAuthenticated: boolean;
  isLoading: boolean;
}
```

### Usage

The context is provided by `MarketplaceLayout` and consumed by marketplace pages:

```typescript
import { useMarketplaceAuth } from '../contexts/MarketplaceAuthContext';

function MarketplaceBrowse() {
  const { isAuthenticated, isLoading } = useMarketplaceAuth();

  if (isLoading) return <Spinner />;

  return (
    <div>
      {/* Show install button for authenticated users, sign up for others */}
      {isAuthenticated ? (
        <button>Install Agent</button>
      ) : (
        <Link to="/register">Sign Up to Install</Link>
      )}

      {/* Show credits only if authenticated */}
      {isAuthenticated && <CreditsDisplay />}

      <AgentGrid />
    </div>
  );
}
```

### When to Use

- **Use MarketplaceAuthContext**: For marketplace pages/components that need to conditionally show auth-dependent UI
- **Use AuthContext**: For protected routes that require authentication

---

## Best Practices

### 1. Provider Order Matters

```typescript
// Correct order in App.tsx
<ThemeProvider>      {/* Outermost - CSS must be ready */}
  <AuthProvider>     {/* Auth state */}
    <CommandProvider> {/* Commands need auth context */}
      <Router />
    </CommandProvider>
  </AuthProvider>
</ThemeProvider>
```

### 2. Don't Duplicate State

Use context for app-wide state, not component-local state:
- **Good**: Auth status, theme, global commands
- **Bad**: Form input values, modal open state

### 3. Handle Loading States

```typescript
function ProtectedContent() {
  const { isAuthenticated, isLoading } = useAuth();

  // Don't flash unauthorized content
  if (isLoading) return null;
  if (!isAuthenticated) return <Navigate to="/login" />;

  return <PrivateContent />;
}
```

### 4. Clean Up Handlers

`useCommandHandlers` auto-cleans on unmount, but for manual registration:

```typescript
useEffect(() => {
  const cleanup = registerHandlers({ myCommand: handler });
  return cleanup; // Important!
}, []);
```

## Common Issues

### Issue: Commands Not Executing

**Symptom**: `executeCommand` returns `false`, console shows "No handler registered"

**Solution**: Ensure the component with `useCommandHandlers` is mounted:
```typescript
// Handler component must be rendered
{showProject && <ProjectPage />} // handlers only available when mounted
```

### Issue: Auth State Not Syncing Across Tabs

**Symptom**: Login in one tab doesn't update another

**Solution**: AuthContext listens to `storage` events automatically. Ensure you're using `localStorage`, not `sessionStorage`.

### Issue: Context Undefined Error

**Symptom**: "useAuth must be used within AuthProvider"

**Solution**: Check provider hierarchy in App.tsx:
```typescript
// Component must be inside provider tree
<AuthProvider>
  <MyComponent /> {/* Can use useAuth here */}
</AuthProvider>
```

## Adding New Commands

1. Add to `CommandHandlers` interface in `CommandContext.tsx`:
```typescript
interface CommandHandlers {
  // ... existing
  myNewCommand: (arg: MyType) => void;
}
```

2. Register handler in owning component:
```typescript
useCommandHandlers({
  myNewCommand: (arg) => { /* handle */ },
});
```

3. Add to CommandPalette commands array:
```typescript
{
  id: 'my-new-command',
  label: 'Do My Thing',
  action: () => executeCommand('myNewCommand', myArg),
}
```

## File Organization

```
app/src/
├── contexts/
│   ├── AuthContext.tsx      # Auth state provider
│   ├── CommandContext.tsx   # Command dispatch system
│   └── auth/
│       └── types.ts         # Auth types and error classes
├── theme/
│   └── ThemeContext.tsx     # Theme state (separate dir for CSS)
```
