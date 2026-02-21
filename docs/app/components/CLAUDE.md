# CLAUDE.md - Tesslate Studio Components

**Context for AI Agents**: This file provides patterns and context for developing, modifying, or debugging React components in Tesslate Studio.

## Component Development Guidelines

### When Creating New Components

**1. File Location**
- Feature-specific: `components/<feature>/<ComponentName>.tsx`
- Shared UI: `components/ui/<ComponentName>.tsx`
- Root-level only for major features (e.g., `GraphCanvas`, `CodeEditor`)

**2. TypeScript Patterns**

```typescript
// Always define props interface
interface ComponentProps {
  // Required props first
  projectId: number;
  onUpdate: (data: Data) => void;

  // Optional props with defaults
  className?: string;
  disabled?: boolean;
  theme?: 'light' | 'dark';
}

// Export component with explicit type
export function Component({
  projectId,
  onUpdate,
  className = '',
  disabled = false,
  theme = 'dark'
}: ComponentProps) {
  // Component logic
}
```

**3. State Management**

```typescript
// Local UI state
const [isOpen, setIsOpen] = useState(false);
const [value, setValue] = useState('');

// Refs for DOM access
const inputRef = useRef<HTMLInputElement>(null);

// Effects for side effects
useEffect(() => {
  // Setup
  const subscription = api.subscribe();

  // Cleanup
  return () => subscription.unsubscribe();
}, [dependencies]);
```

**4. Performance Optimization**

```typescript
// For high-frequency renders, use memo
export const ExpensiveComponent = memo(Component, (prev, next) => {
  return prev.id === next.id && prev.data === next.data;
});

// For expensive calculations, use useMemo
const sortedItems = useMemo(() => {
  return items.sort((a, b) => a.name.localeCompare(b.name));
}, [items]);

// For callbacks passed to children, use useCallback
const handleClick = useCallback(() => {
  onUpdate(value);
}, [value, onUpdate]);
```

### Styling Conventions

**60-30-10 Design Rule** (dominant, secondary, accent):
```tsx
// 60% - Dark background (dominant)
<div className="bg-[var(--bg-dark)]">

  {/* 30% - Surface/borders (secondary) */}
  <div className="bg-[var(--surface)] border-[var(--border-color)]">

    {/* 10% - Orange accents (highlights) */}
    <button className="bg-[var(--primary)] hover:bg-[var(--primary-hover)]">
      Action
    </button>
  </div>
</div>
```

**CSS Variables**:
```css
var(--bg-dark)         /* #0a0a0a - Main background */
var(--surface)         /* #1a1a1a - Elevated surfaces */
var(--text)            /* #e2e2e2 - Text color */
var(--primary)         /* #F89521 - Orange accent */
var(--primary-hover)   /* #ff8533 - Orange hover */
var(--border-color)    /* rgba(255,255,255,0.1) - Borders */
```

**Responsive Design**:
```tsx
// Mobile-first with md: breakpoint (768px)
<div className="
  w-full              {/* Mobile: full width */}
  md:w-64            {/* Desktop: fixed width */}
  rounded-b-none      {/* Mobile: no bottom radius */}
  md:rounded-3xl      {/* Desktop: rounded corners */}
">
```

### Component Communication

**Props Down, Events Up**:
```typescript
// Parent passes data down
<ChildComponent
  data={parentData}
  onUpdate={handleChildUpdate}  // Parent handles events
/>

// Child emits events up
function ChildComponent({ data, onUpdate }: Props) {
  const handleChange = (newValue: string) => {
    onUpdate(newValue);  // Call parent's handler
  };
}
```

**Context for Global State**:
```typescript
// Create context
const ThemeContext = createContext<Theme>('dark');

// Provide at root
<ThemeContext.Provider value={theme}>
  <App />
</ThemeContext.Provider>

// Consume in components
const theme = useContext(ThemeContext);
```

### WebSocket Integration

**Pattern for Real-Time Components**:
```typescript
useEffect(() => {
  const ws = createWebSocket(token);
  let reconnectTimer: NodeJS.Timeout | null = null;

  ws.onopen = () => {
    console.log('[WS] Connected');
  };

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);

    // Handle different message types
    switch (data.type) {
      case 'stream':
        setContent(prev => prev + data.content);
        break;
      case 'complete':
        setIsStreaming(false);
        break;
      case 'error':
        toast.error(data.content);
        break;
    }
  };

  ws.onclose = () => {
    // Reconnect with backoff
    reconnectTimer = setTimeout(connect, delay);
  };

  return () => {
    if (reconnectTimer) clearTimeout(reconnectTimer);
    ws.close();
  };
}, [projectId, token]);
```

### Monaco Editor Integration

**CodeEditor Component Pattern**:
```typescript
import Editor from '@monaco-editor/react';

const editorRef = useRef<unknown>(null);

const handleEditorDidMount = (editor: unknown) => {
  editorRef.current = editor;
};

<Editor
  height="100%"
  language={getLanguage(fileName)}
  value={content}
  onChange={handleEditorChange}
  onMount={handleEditorDidMount}
  theme={theme === 'dark' ? 'vs-dark' : 'vs'}
  options={{
    fontSize: 14,
    minimap: { enabled: true },
    automaticLayout: true,
    wordWrap: 'on',
  }}
/>
```

### XYFlow Graph Integration

**Custom Node Pattern**:
```typescript
import { memo } from 'react';
import { Handle, Position, type Node } from '@xyflow/react';

interface CustomNodeData extends Record<string, unknown> {
  name: string;
  status: 'running' | 'stopped';
}

type CustomNodeProps = Node<CustomNodeData>;

const CustomNodeComponent = ({ data, id }: CustomNodeProps) => {
  return (
    <div className="bg-[#1a1a1a] rounded-xl p-3">
      <Handle type="target" position={Position.Left} />
      <Handle type="source" position={Position.Right} />

      <h3>{data.name}</h3>
      <span>{data.status}</span>
    </div>
  );
};

export const CustomNode = memo(CustomNodeComponent);
```

**Custom Edge Pattern**:
```typescript
import { memo } from 'react';
import { BaseEdge, getSmoothStepPath, type EdgeProps } from '@xyflow/react';

const EDGE_STYLE = { stroke: '#22c55e', strokeWidth: 2 };

const CustomEdgeComponent = (props: EdgeProps) => {
  const [edgePath] = getSmoothStepPath({
    sourceX: props.sourceX,
    sourceY: props.sourceY,
    sourcePosition: props.sourcePosition,
    targetX: props.targetX,
    targetY: props.targetY,
    targetPosition: props.targetPosition,
  });

  return <BaseEdge id={props.id} path={edgePath} style={EDGE_STYLE} />;
};

export const CustomEdge = memo(CustomEdgeComponent);
```

### Form Handling

**Controlled Inputs with Validation**:
```typescript
const [formData, setFormData] = useState({ name: '', email: '' });
const [errors, setErrors] = useState<Record<string, string>>({});

const validateForm = (): boolean => {
  const newErrors: Record<string, string> = {};

  if (!formData.name.trim()) {
    newErrors.name = 'Name is required';
  }
  if (!/\S+@\S+\.\S+/.test(formData.email)) {
    newErrors.email = 'Invalid email';
  }

  setErrors(newErrors);
  return Object.keys(newErrors).length === 0;
};

const handleSubmit = async (e: FormEvent) => {
  e.preventDefault();

  if (!validateForm()) return;

  try {
    await api.submit(formData);
    toast.success('Submitted!');
  } catch (error) {
    toast.error('Failed to submit');
  }
};
```

### Modal Patterns

**Standard Modal Structure**:
```typescript
interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: (data: Data) => void;
}

export function Modal({ isOpen, onClose, onConfirm }: ModalProps) {
  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50"
      onClick={onClose}  // Close on backdrop click
    >
      <div
        className="bg-[var(--surface)] p-8 rounded-3xl max-w-md"
        onClick={(e) => e.stopPropagation()}  // Prevent backdrop click
      >
        <h2>Modal Title</h2>
        {/* Modal content */}
        <div className="flex gap-3">
          <button onClick={onClose}>Cancel</button>
          <button onClick={() => onConfirm(data)}>Confirm</button>
        </div>
      </div>
    </div>
  );
}
```

### Container Loading Overlay

**Pattern for Container Startup Feedback**:

```typescript
import { ContainerLoadingOverlay } from '../components/ContainerLoadingOverlay';
import { useContainerStartup } from '../hooks/useContainerStartup';

function BrowserPreview({ projectSlug, containerId }: Props) {
  const {
    status,
    phase,
    progress,
    message,
    logs,
    error,
    containerUrl,
    startContainer,
    retry,
    isLoading,
  } = useContainerStartup(projectSlug, containerId);

  // Show loading overlay during startup or on error
  if (isLoading || status === 'error') {
    return (
      <ContainerLoadingOverlay
        phase={phase}
        progress={progress}
        message={message}
        logs={logs}
        error={error ?? undefined}
        onRetry={retry}
      />
    );
  }

  // Show preview when ready
  if (status === 'ready' && containerUrl) {
    return <iframe src={containerUrl} className="w-full h-full" />;
  }

  return null;
}
```

**ContainerLoadingOverlay Props**:
```typescript
interface ContainerLoadingOverlayProps {
  phase: string;      // Current startup phase
  progress: number;   // 0-100 percentage
  message: string;    // User-friendly message
  logs: string[];     // Terminal-style log output
  error?: string;     // Error message (shows error state if present)
  onRetry?: () => void; // Retry callback for error state
}
```

**Features**:
- Animated pulsing grid spinner during loading
- Progress bar with percentage
- Terminal-style log viewer with auto-scroll
- Color-coded logs (red=error, yellow=warn, green=success)
- Error state with retry button and log preview

### Error Handling

**Component-Level Error Boundaries**:
```typescript
class ErrorBoundary extends React.Component<Props, State> {
  state = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Component error:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="error-fallback">
          <h2>Something went wrong</h2>
          <button onClick={() => this.setState({ hasError: false })}>
            Try again
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
```

**Async Error Handling**:
```typescript
const [loading, setLoading] = useState(false);
const [error, setError] = useState<string | null>(null);

const fetchData = async () => {
  setLoading(true);
  setError(null);

  try {
    const result = await api.getData();
    setData(result);
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    setError(message);
    toast.error(message);
  } finally {
    setLoading(false);
  }
};
```

## Common Debugging Patterns

### React DevTools

```typescript
// Add displayName for better debugging
Component.displayName = 'MyComponent';

// Use React DevTools Profiler to find slow renders
// Check "Highlight updates" to see what's re-rendering
```

### Console Logging

```typescript
// Prefix logs with component name
useEffect(() => {
  console.log('[ChatContainer] WebSocket connected');
}, []);

// Log render reasons
useEffect(() => {
  console.log('[ChatContainer] messages changed:', messages.length);
}, [messages]);
```

### Performance Debugging

```typescript
// Measure render time
const startTime = performance.now();
// ... render logic
console.log(`Render took ${performance.now() - startTime}ms`);

// Check memo effectiveness
useEffect(() => {
  console.log('[Node] Re-rendered with:', data);
}, [data]);
```

## Route Auth Protection

Routes are protected by `PrivateRoute` and `PublicOnlyRoute` guards in `app/src/components/RouteGuards.tsx`, used in `App.tsx`.

**IMPORTANT: When adding a new route to `App.tsx`**, you MUST:
1. Wrap it with the appropriate guard (`PrivateRoute`, `PublicOnlyRoute`, or none for public)
2. Add an entry to the `ROUTE_CONFIG` array in `app/src/components/RouteGuards.test.tsx`
3. Run `npm test` in `app/` to verify the route has correct auth behavior

| Guard | Behavior | Example Routes |
|-------|----------|----------------|
| `PrivateRoute` | Redirects to `/login` if not authenticated (preserves intended destination) | `/dashboard`, `/settings/*`, `/project/*` |
| `PublicOnlyRoute` | Redirects to `/dashboard` (or saved destination) if already authenticated | `/login`, `/register` |
| None (public) | Always accessible | `/`, `/marketplace/*`, `/forgot-password` |

## Testing Patterns

### Component Tests

```typescript
import { render, screen, fireEvent } from '@testing-library/react';

test('button triggers onClick handler', () => {
  const handleClick = jest.fn();
  render(<Button onClick={handleClick}>Click me</Button>);

  fireEvent.click(screen.getByText('Click me'));
  expect(handleClick).toHaveBeenCalledTimes(1);
});
```

### Async Tests

```typescript
test('loads data on mount', async () => {
  render(<DataComponent />);

  // Wait for loading to complete
  await waitFor(() => {
    expect(screen.getByText('Data loaded')).toBeInTheDocument();
  });
});
```

## Common Issues and Solutions

### Issue: Component Not Re-rendering

**Solution**: Check dependencies in useEffect, useMemo, useCallback
```typescript
// Bad: Missing dependency
useEffect(() => {
  doSomething(value);
}, []);

// Good: Include all dependencies
useEffect(() => {
  doSomething(value);
}, [value]);
```

### Issue: Memory Leak Warning

**Solution**: Clean up effects and subscriptions
```typescript
useEffect(() => {
  const timer = setInterval(fetchData, 1000);
  return () => clearInterval(timer);  // Cleanup
}, []);
```

### Issue: Stale Closure

**Solution**: Use functional setState
```typescript
// Bad: Stale value
setCount(count + 1);

// Good: Function receives latest value
setCount(prev => prev + 1);
```

### Issue: Expensive Re-renders

**Solution**: Memoize values and callbacks
```typescript
// Memoize computed values
const expensiveValue = useMemo(() => {
  return computeExpensiveValue(data);
}, [data]);

// Memoize callbacks
const handleClick = useCallback(() => {
  doSomething(value);
}, [value]);
```

---

**When in doubt**: Check existing similar components for patterns, use TypeScript's type checking, and test in both development and production builds.
