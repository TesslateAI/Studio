# Custom Hooks Documentation

**Purpose**: This context documents the custom React hooks in Tesslate Studio, focusing on request management, authentication, and component lifecycle patterns.

## When to Load This Context

Load this context when:
- Making API calls from components
- Handling authentication state in components
- Preventing memory leaks from async operations
- Implementing cancellable requests
- Working with component unmount cleanup

## Key Files

| File | Purpose |
|------|---------|
| `app/src/hooks/useCancellableRequest.ts` | AbortController-based request management |
| `app/src/hooks/useAuth.ts` | Authentication hook (uses AuthContext) |
| `app/src/hooks/useTask.ts` | Background task polling |
| `app/src/hooks/useTaskNotifications.ts` | Task toast notifications |
| `app/src/hooks/useContainerStartup.ts` | Container startup lifecycle |
| `app/src/hooks/useReferralTracking.ts` | Affiliate/referral code tracking |

## Related Contexts

- **`docs/app/contexts/CLAUDE.md`**: Context providers that hooks consume
- **`docs/app/state/CLAUDE.md`**: State management patterns
- **`docs/app/CLAUDE.md`**: Frontend overview

## useCancellableRequest

### Purpose

Prevents memory leaks and race conditions by:
- Tracking component mount state
- Aborting in-flight requests on unmount
- Only calling callbacks if component is still mounted
- Silently ignoring AbortError and Axios CanceledError exceptions

**Note**: For manual AbortController patterns (like in Marketplace pages), use `isCanceledError()` from `lib/utils.ts` to check for cancelled requests, as it handles both native AbortError and Axios CanceledError.

### Basic Usage

```typescript
import { useCancellableRequest } from '../hooks/useCancellableRequest';

function ProfileSettings() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loading, setLoading] = useState(true);

  const { execute } = useCancellableRequest<Profile>();

  const loadProfile = useCallback(() => {
    execute(
      // Request function (receives AbortSignal if API supports it)
      (signal) => api.get('/profile', { signal }).then(r => r.data),
      {
        onSuccess: (data) => setProfile(data),
        onError: (error) => toast.error('Failed to load profile'),
        onFinally: () => setLoading(false),
      }
    );
  }, [execute]);

  useEffect(() => {
    loadProfile();
  }, [loadProfile]);

  // ... component JSX
}
```

### Without Signal Support

If your API doesn't support AbortSignal, the hook still prevents state updates on unmounted components:

```typescript
const { execute } = useCancellableRequest<UserProfile>();

execute(
  // No signal parameter - hook still checks mount state
  () => usersApi.getProfile(),
  {
    onSuccess: setProfile,  // Only called if mounted
    onError: handleError,   // Only called if mounted
    onFinally: () => setLoading(false),
  }
);
```

### Manual Abort

```typescript
const { execute, abort } = useCancellableRequest<Data>();

// Abort current request (e.g., on search input change)
const handleSearchChange = (query: string) => {
  abort(); // Cancel previous search
  execute(
    (signal) => searchApi.search(query, { signal }),
    { onSuccess: setResults }
  );
};
```

## useCancellableParallelRequests

### Purpose

Execute multiple requests in parallel with a shared abort controller:

```typescript
import { useCancellableParallelRequests } from '../hooks/useCancellableRequest';

function DeploymentSettings() {
  const { executeAll } = useCancellableParallelRequests();

  const loadData = useCallback(() => {
    executeAll(
      [
        () => deploymentApi.getProviders(),
        () => deploymentApi.getCredentials(),
      ],
      {
        onAllSuccess: ([providers, credentials]) => {
          setProviders(providers.data);
          setCredentials(credentials.data);
        },
        onError: (error) => toast.error('Failed to load data'),
        onFinally: () => setLoading(false),
      }
    );
  }, [executeAll]);

  useEffect(() => {
    loadData();
  }, [loadData]);
}
```

## useAuth

### Purpose

Provides authentication state from AuthContext:

```typescript
import { useAuth } from '../hooks/useAuth';

function Header() {
  const { isAuthenticated, user, logout } = useAuth();

  return (
    <header>
      {isAuthenticated ? (
        <>
          <span>{user?.name}</span>
          <button onClick={logout}>Logout</button>
        </>
      ) : (
        <Link to="/login">Login</Link>
      )}
    </header>
  );
}
```

### Full API

```typescript
const {
  status,           // 'initializing' | 'authenticated' | 'unauthenticated'
  user,             // AuthUser | null
  isAuthenticated,  // boolean
  isLoading,        // boolean (true during initialization)
  error,            // AuthError | null
  login,            // (email, password) => Promise<void>
  logout,           // () => Promise<void>
  checkAuth,        // (options?) => Promise<boolean>
  clearError,       // () => void
} = useAuth();
```

## useTask

### Purpose

Track and poll background task status:

```typescript
import { useTask, useTaskPolling } from '../hooks/useTask';

function CreateProject() {
  const { task, isPolling, startPolling } = useTaskPolling();

  const handleCreate = async () => {
    const { task_id } = await projectsApi.create({ name: 'New App' });
    startPolling(task_id);
  };

  useEffect(() => {
    if (task?.status === 'completed') {
      navigate(`/project/${task.result.slug}`);
    } else if (task?.status === 'failed') {
      toast.error(`Failed: ${task.error}`);
    }
  }, [task]);

  return (
    <button onClick={handleCreate} disabled={isPolling}>
      {isPolling ? 'Creating...' : 'Create Project'}
    </button>
  );
}
```

## useContainerStartup

### Purpose

Manages container startup lifecycle with real-time progress:

```typescript
import { useContainerStartup } from '../hooks/useContainerStartup';

function ProjectView() {
  const containerStartup = useContainerStartup(
    projectSlug,
    containerId,
    {
      onReady: (url) => {
        setDevServerUrl(url);
        toast.success('Development server ready!');
      },
      onError: (error) => {
        toast.error(`Container failed: ${error}`);
      }
    }
  );

  return (
    <div>
      {containerStartup.isLoading && (
        <LoadingOverlay
          phase={containerStartup.phase}
          progress={containerStartup.progress}
          message={containerStartup.message}
          logs={containerStartup.logs}
        />
      )}
    </div>
  );
}
```

## useReferralTracking

### Purpose

Tracks affiliate/referral codes from URL parameters for attribution:
- Captures `?ref=CODE` query parameter on first visit
- Stores referrer in sessionStorage to prevent duplicate tracking
- Sends tracking event to backend API
- Preserves referrer for use during signup

### Basic Usage

```typescript
import { useReferralTracking } from '../hooks/useReferralTracking';

function App() {
  // Call in root component - tracks referral once per session
  useReferralTracking();

  return <Router />;
}
```

### How It Works

1. User visits with referral link: `https://tesslate.com/?ref=PARTNER123`
2. Hook detects `ref` query parameter
3. Sends POST to `/api/track-landing?ref=PARTNER123`
4. Stores `referrer` in sessionStorage for signup attribution
5. Sets `referral_tracked` flag to prevent duplicate tracking

### Backend Integration

The referrer stored in sessionStorage can be retrieved during signup:

```typescript
const referrer = sessionStorage.getItem('referrer');
await registerUser({ email, password, referrer });
```

---

## Hook Patterns

### Pattern: Cancellable Effect

```typescript
function SearchResults({ query }: { query: string }) {
  const [results, setResults] = useState([]);
  const { execute } = useCancellableRequest<SearchResult[]>();

  useEffect(() => {
    if (!query) return;

    execute(
      (signal) => searchApi.search(query, { signal }),
      {
        onSuccess: setResults,
        onError: () => setResults([]),
      }
    );
  }, [query, execute]);

  return (/* render results */);
}
```

### Pattern: Debounced Request

```typescript
function AutoSave({ content }: { content: string }) {
  const { execute } = useCancellableRequest<void>();
  const timeoutRef = useRef<NodeJS.Timeout>();

  useEffect(() => {
    // Clear previous timeout
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }

    // Debounce save
    timeoutRef.current = setTimeout(() => {
      execute(
        () => api.save(content),
        { onSuccess: () => console.log('Saved') }
      );
    }, 1000);

    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, [content, execute]);

  return null;
}
```

### Pattern: Retry Logic

```typescript
function DataFetcher() {
  const { execute } = useCancellableRequest<Data>();
  const [retryCount, setRetryCount] = useState(0);

  const fetchWithRetry = useCallback(() => {
    execute(
      () => api.getData(),
      {
        onSuccess: setData,
        onError: (error) => {
          if (retryCount < 3) {
            setTimeout(() => {
              setRetryCount(c => c + 1);
            }, 1000 * (retryCount + 1)); // Exponential backoff
          } else {
            toast.error('Failed after 3 retries');
          }
        },
      }
    );
  }, [execute, retryCount]);

  useEffect(() => {
    fetchWithRetry();
  }, [fetchWithRetry]);
}
```

## Best Practices

### 1. Always Use Cancellable Requests for API Calls

```typescript
// Bad: Can cause memory leaks
useEffect(() => {
  api.getData().then(setData);
}, []);

// Good: Automatically handles unmount
const { execute } = useCancellableRequest();
useEffect(() => {
  execute(() => api.getData(), { onSuccess: setData });
}, [execute]);
```

### 2. Memoize Callbacks

```typescript
// Good: Stable callback reference
const loadData = useCallback(() => {
  execute(() => api.getData(), { onSuccess: setData });
}, [execute]);

useEffect(() => {
  loadData();
}, [loadData]);
```

### 3. Handle All States

```typescript
const { execute } = useCancellableRequest<Data>();
const [data, setData] = useState<Data | null>(null);
const [loading, setLoading] = useState(true);
const [error, setError] = useState<Error | null>(null);

execute(() => api.getData(), {
  onSuccess: (d) => {
    setData(d);
    setError(null);
  },
  onError: (e) => {
    setError(e);
    setData(null);
  },
  onFinally: () => setLoading(false),
});
```

### 4. Don't Await Execute in Effects

```typescript
// Bad: Can cause issues
useEffect(() => {
  const load = async () => {
    await execute(() => api.getData(), opts);
  };
  load();
}, []);

// Good: Let callbacks handle results
useEffect(() => {
  execute(() => api.getData(), opts);
}, [execute]);
```

## Common Issues

### Issue: Callbacks Not Firing

**Symptom**: onSuccess/onError never called

**Cause**: Component unmounted before request completed (expected behavior!)

**Solution**: This is correct behavior. If you need to persist data regardless of mount state, use a service or store outside the component.

### Issue: "Cannot update a component while rendering"

**Symptom**: React error during render

**Solution**: Ensure you're not calling execute during render:
```typescript
// Bad
function MyComponent() {
  const { execute } = useCancellableRequest();
  execute(() => api.getData()); // Called during render!
  return <div />;
}

// Good
function MyComponent() {
  const { execute } = useCancellableRequest();
  useEffect(() => {
    execute(() => api.getData());
  }, [execute]);
  return <div />;
}
```

### Issue: Stale Closure in Callbacks

**Symptom**: Callbacks use old state values

**Solution**: Use refs for values needed in callbacks:
```typescript
const countRef = useRef(count);
useEffect(() => { countRef.current = count; }, [count]);

execute(() => api.getData(), {
  onSuccess: () => {
    console.log(countRef.current); // Always latest
  },
});
```

## File Organization

```
app/src/hooks/
├── useCancellableRequest.ts  # Request lifecycle management
├── useAuth.ts                # Auth context consumer
├── useTask.ts                # Task polling
├── useTaskNotifications.ts   # Task toast notifications
├── useContainerStartup.ts    # Container startup lifecycle
└── useReferralTracking.ts    # Affiliate tracking
```
