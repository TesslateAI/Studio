# Custom Hooks

Tesslate Studio provides custom React hooks for task management, notifications, and referral tracking.

## Files

| File | Purpose |
|------|---------|
| `app/src/hooks/useTask.ts` | Task tracking hooks |
| `app/src/hooks/useTaskNotifications.ts` | Toast notifications |
| `app/src/hooks/useReferralTracking.ts` | Affiliate tracking |

## Task Hooks

**File**: `app/src/hooks/useTask.ts`

### useTask

Track a specific task by ID with real-time updates:

```typescript
export function useTask(taskId: string | null) {
  const [task, setTask] = useState<Task | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!taskId) {
      setTask(null);
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);

    // Fetch initial task status
    taskService
      .getTaskStatus(taskId)
      .then((task) => {
        setTask(task);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });

    // Subscribe to real-time updates
    const unsubscribe = taskService.subscribeToTask(taskId, (updatedTask) => {
      setTask(updatedTask);
      setLoading(false);
    });

    return unsubscribe;
  }, [taskId]);

  return { task, loading, error };
}
```

**Usage:**

```typescript
function TaskStatus({ taskId }: { taskId: string }) {
  const { task, loading, error } = useTask(taskId);

  if (loading) return <Spinner />;
  if (error) return <Error message={error} />;
  if (!task) return null;

  return (
    <div>
      <p>Status: {task.status}</p>
      <p>Progress: {task.progress.percentage}%</p>
      <p>{task.progress.message}</p>
    </div>
  );
}
```

### useActiveTasks

Track all active tasks for the current user:

```typescript
export function useActiveTasks() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Fetch initial active tasks
    taskService.getActiveTasks().then((tasks) => {
      setTasks(tasks);
      setLoading(false);
    });

    // Subscribe to all task updates
    const unsubscribe = taskService.subscribeToAllTasks((task) => {
      setTasks((prevTasks) => {
        const index = prevTasks.findIndex((t) => t.id === task.id);

        if (index >= 0) {
          // Update existing task
          const newTasks = [...prevTasks];
          newTasks[index] = task;

          // Remove completed/failed tasks after 3 seconds
          if (['completed', 'failed', 'cancelled'].includes(task.status)) {
            setTimeout(() => {
              setTasks((current) => current.filter((t) => t.id !== task.id));
            }, 3000);
          }

          return newTasks;
        } else if (['queued', 'running'].includes(task.status)) {
          // Add new active task
          return [...prevTasks, task];
        }

        return prevTasks;
      });
    });

    return unsubscribe;
  }, []);

  return { tasks, loading };
}
```

**Usage:**

```typescript
function ActiveTasksList() {
  const { tasks, loading } = useActiveTasks();

  if (loading) return <Spinner />;

  return (
    <div>
      {tasks.map(task => (
        <TaskItem key={task.id} task={task} />
      ))}
    </div>
  );
}
```

### useTaskPolling

Poll a task until completion (fallback when WebSocket unavailable):

```typescript
export function useTaskPolling(taskId: string | null, enabled = true) {
  const [task, setTask] = useState<Task | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollingRef = useRef<boolean>(false);

  useEffect(() => {
    if (!taskId || !enabled || pollingRef.current) {
      return;
    }

    pollingRef.current = true;
    setLoading(true);
    setError(null);

    taskService
      .pollTaskUntilComplete(taskId, (updatedTask) => {
        setTask(updatedTask);
      })
      .then((completedTask) => {
        setTask(completedTask);
        setLoading(false);
        pollingRef.current = false;
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
        pollingRef.current = false;
      });

    return () => {
      pollingRef.current = false;
    };
  }, [taskId, enabled]);

  return { task, loading, error };
}
```

**Usage:**

```typescript
function ProjectCreation({ taskId }: { taskId: string }) {
  const { task, loading, error } = useTaskPolling(taskId);

  if (loading) {
    return (
      <div>
        <p>Creating project...</p>
        {task && <ProgressBar value={task.progress.percentage} />}
      </div>
    );
  }

  if (error) {
    return <Error message={error} />;
  }

  if (task?.status === 'completed') {
    return <Success>Project created!</Success>;
  }

  return null;
}
```

### useTaskWebSocket

Connect to task WebSocket on mount:

```typescript
export function useTaskWebSocket() {
  useEffect(() => {
    const token = localStorage.getItem('token');
    if (token) {
      taskService.connect(token);
    }

    return () => {
      taskService.disconnect();
    };
  }, []);
}
```

**Usage:**

```typescript
// In App.tsx or root layout
function App() {
  useTaskWebSocket();
  return <RouterProvider router={router} />;
}
```

## Task Notifications Hook

**File**: `app/src/hooks/useTaskNotifications.ts`

Connects to WebSocket and shows toast notifications for task updates:

```typescript
export function useTaskNotifications() {
  // Connect to WebSocket
  useTaskWebSocket();

  useEffect(() => {
    // Subscribe to all task updates
    const unsubscribe = taskService.subscribeToAllTasks((task: Task) => {
      if (task.status === 'completed') {
        const taskName = getTaskDisplayName(task);
        toast.success(`${taskName} completed successfully`, {
          duration: 4000,
        });
      } else if (task.status === 'failed') {
        const taskName = getTaskDisplayName(task);
        toast.error(`${taskName} failed: ${task.error || 'Unknown error'}`, {
          duration: 6000,
        });
      }
    });

    // Subscribe to backend notifications
    const unsubscribeNotifications = taskService.subscribeToNotifications(
      (notification) => {
        switch (notification.type) {
          case 'success':
            toast.success(notification.message, { duration: 4000 });
            break;
          case 'error':
            toast.error(notification.message, { duration: 6000 });
            break;
          case 'warning':
            toast(notification.message, { duration: 5000, icon: 'Warning' });
            break;
          default:
            toast(notification.message, { duration: 4000 });
        }
      }
    );

    return () => {
      unsubscribe();
      unsubscribeNotifications();
    };
  }, []);
}

function getTaskDisplayName(task: Task): string {
  switch (task.type) {
    case 'project_creation':
      return `Project "${task.metadata.project_name || 'creation'}"`;
    case 'project_deletion':
      return `Project "${task.metadata.project_name || 'deletion'}"`;
    case 'container_startup':
      return `Container for "${task.metadata.project_name || task.metadata.project_slug}"`;
    default:
      return task.type.replace(/_/g, ' ');
  }
}
```

**Usage:**

```typescript
// In root layout - enables global task notifications
function RootLayout() {
  useTaskNotifications();

  return (
    <>
      <Toaster />
      <Outlet />
    </>
  );
}
```

## Referral Tracking Hook

**File**: `app/src/hooks/useReferralTracking.ts`

Tracks referral links for affiliate program:

```typescript
export function useReferralTracking() {
  const location = useLocation();

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const ref = params.get('ref');

    if (ref && !sessionStorage.getItem('referral_tracked')) {
      // Track the landing
      axios.post(`${API_URL}/api/track-landing?ref=${ref}`)
        .then(() => {
          // Store in sessionStorage so we don't track multiple times
          sessionStorage.setItem('referral_tracked', 'true');
          // Store the referrer for use during signup
          sessionStorage.setItem('referrer', ref);
        })
        .catch((error) => {
          console.error('Failed to track referral:', error);
        });
    }
  }, [location]);
}
```

**Usage:**

```typescript
// In landing page or root layout
function LandingPage() {
  useReferralTracking();

  return (
    <div>
      <Hero />
      <Features />
      <SignUpButton />
    </div>
  );
}
```

The stored referrer is used during registration:

```typescript
// In authApi.register (api.ts)
register: async (name: string, email: string, password: string) => {
  const referred_by = sessionStorage.getItem('referrer');

  const response = await api.post('/api/auth/register', {
    name,
    email,
    password,
    referral_code: referred_by || undefined,
  });
  return response.data;
}
```

## Hook Summary

| Hook | Purpose | Dependencies |
|------|---------|--------------|
| `useTask` | Track single task | taskService |
| `useActiveTasks` | Track all active tasks | taskService |
| `useTaskPolling` | Poll task to completion | taskService |
| `useTaskWebSocket` | Connect WebSocket | taskService |
| `useTaskNotifications` | Show toast notifications | useTaskWebSocket, react-hot-toast |
| `useReferralTracking` | Track affiliate referrals | react-router-dom, axios |

## Best Practices

### 1. Use useTaskNotifications at Root Level

```typescript
function App() {
  useTaskNotifications(); // Only call once at root

  return <RouterProvider router={router} />;
}
```

### 2. Prefer useTask for Real-Time Updates

```typescript
// Good - real-time updates via WebSocket
const { task } = useTask(taskId);

// Only use polling as fallback
const { task } = useTaskPolling(taskId);
```

### 3. Clean Up Subscriptions

All hooks automatically clean up subscriptions on unmount via the returned cleanup function from useEffect.

### 4. Handle Loading and Error States

```typescript
const { task, loading, error } = useTask(taskId);

if (loading) return <Loading />;
if (error) return <Error message={error} />;
if (!task) return null;

return <TaskDisplay task={task} />;
```
