# Graph Components

**Location**: `app/src/components/`

The graph visualization system uses XYFlow (React Flow) to render interactive architecture diagrams showing containers, services, and their connections.

## Components Overview

### GraphCanvas.tsx

**XYFlow Wrapper**: Memoized ReactFlow component with performance optimizations and custom configuration.

**Features**:
- Memoized with custom comparison (prevents unnecessary re-renders)
- Dotted background pattern
- Zoom controls (0.1x - 2x range)
- Pan on drag/scroll
- Custom node/edge types
- Mobile-friendly hints
- No auto-pan (performance optimization)
- Delete key to remove edges

**Props**:
```typescript
interface GraphCanvasProps {
  nodes: Node[];
  edges: Edge[];
  onNodesChange: OnNodesChange;
  onEdgesChange: OnEdgesChange;
  onConnect: OnConnect;
  onDrop: (event: React.DragEvent) => void;
  onDragOver: (event: React.DragEvent) => void;
  onNodeDragStart?: () => void;
  onNodeDragStop: (event, node: Node) => void;
  onNodeClick: (event: React.MouseEvent, node: Node) => void;
  onNodeDoubleClick: (event: React.MouseEvent, node: Node) => void;
  onEdgeClick?: (event: React.MouseEvent, edge: Edge) => void;
  onEdgesDelete?: (edges: Edge[]) => void;
  nodeTypes: NodeTypes;
  edgeTypes: EdgeTypes;
  theme: 'dark' | 'light';
}
```

**Performance Optimizations**:
```typescript
// Custom comparison - only re-render when nodes/edges change
const arePropsEqual = (prev: Props, next: Props): boolean => {
  return (
    prev.nodes === next.nodes &&
    prev.edges === next.edges &&
    prev.theme === next.theme
  );
};

export const GraphCanvas = memo(GraphCanvasComponent, arePropsEqual);

// Disable expensive features
<ReactFlow
  autoPanOnNodeDrag={false}    // Major performance gain
  elevateNodesOnSelect={false}
  snapToGrid={false}
  nodeOrigin={[0.5, 0.5]}      // Center nodes on handle
/>
```

---

### ContainerNode.tsx

**Container Card Node**: Displays a service/container with icon, status, port, and tech stack.

**Features**:
- Color-coded by type (external=purple, hybrid=cyan, service=blue, base=green)
- Status indicator (stopped/starting/running/failed)
- Port display
- Tech stack badges (show first 3, +N for more)
- Delete button (hover to show)
- Double-click to open builder (base containers only)
- Memoized with custom comparison

**Props (via node data)**:
```typescript
interface ContainerNodeData {
  name: string;
  baseIcon?: string;           // Emoji icon
  status: 'stopped' | 'starting' | 'running' | 'failed' | 'connected';
  port?: number;
  techStack?: string[];
  containerType?: 'base' | 'service';
  serviceType?: 'container' | 'external' | 'hybrid';
  onDelete?: (id: string) => void;
  onClick?: (id: string) => void;
  onDoubleClick?: (id: string) => void;
}
```

**Visual Design**:
```tsx
<div className="bg-[#1a1a1a] rounded-xl">
  {/* Handles for connections */}
  <Handle type="target" position={Position.Left} />
  <Handle type="source" position={Position.Right} />

  {/* Header */}
  <div className="flex items-center gap-3 p-3">
    {/* Color-coded icon */}
    <div className={`w-9 h-9 rounded-lg ${typeColor}`}>
      {baseIcon || <Cube />}
    </div>

    {/* Name and status */}
    <div className="flex-1">
      <h3>{name}</h3>
      <span className="text-xs">{status}</span>
    </div>

    {/* Delete button (hover) */}
    <button className="opacity-0 group-hover:opacity-100">
      <X />
    </button>
  </div>

  {/* Body (if has port or tech stack) */}
  {(port || techStack?.length > 0) && (
    <div className="px-3 pb-3">
      {port && <div>Port: {port}</div>}
      {techStack && (
        <div className="flex gap-1">
          {techStack.slice(0, 3).map(tech => (
            <span className="px-1.5 py-0.5 text-[10px] bg-white/5">{tech}</span>
          ))}
          {techStack.length > 3 && <span>+{techStack.length - 3}</span>}
        </div>
      )}
    </div>
  )}
</div>
```

---

### BrowserPreviewNode.tsx

**Resizable Browser Preview**: Embedded iframe with browser chrome, navigation controls, and resize handles.

**Features**:
- Resizable with 8 handles (corners + edges)
- Browser-like UI (address bar, back/forward/refresh/home)
- Navigation history
- Window controls (close, reset size, expand)
- Connection status indicator
- Empty state when not connected
- Min/max size constraints (280x200 to 1200x900)

**Props (via node data)**:
```typescript
interface BrowserPreviewNodeData {
  connectedContainerId?: string;
  connectedContainerName?: string;
  connectedPort?: number;
  baseUrl?: string;              // e.g., "http://localhost:3000"
  onDelete?: (id: string) => void;
  onDisconnect?: (id: string) => void;
}
```

**Resize Logic**:
```typescript
const [size, setSize] = useState({ width: 320, height: 240 });
const [isResizing, setIsResizing] = useState(false);

const handleMouseMove = (e: MouseEvent) => {
  const { startX, startY, startWidth, startHeight, handle } = resizeRef.current;
  const deltaX = e.clientX - startX;
  const deltaY = e.clientY - startY;

  let newWidth = startWidth;
  let newHeight = startHeight;

  if (handle.includes('e')) newWidth = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, startWidth + deltaX));
  if (handle.includes('w')) newWidth = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, startWidth - deltaX));
  if (handle.includes('s')) newHeight = Math.min(MAX_HEIGHT, Math.max(MIN_HEIGHT, startHeight + deltaY));
  if (handle.includes('n')) newHeight = Math.min(MAX_HEIGHT, Math.max(MIN_HEIGHT, startHeight - deltaY));

  setSize({ width: newWidth, height: newHeight });
};
```

**Browser Chrome**:
```tsx
<div className="bg-[#252525] px-2 py-1.5">
  {/* Window controls */}
  <div className="flex gap-1.5">
    <button className="w-3 h-3 rounded-full bg-red-500" onClick={onDelete} />
    <button className="w-3 h-3 rounded-full bg-yellow-500" onClick={resetSize} />
    <button className="w-3 h-3 rounded-full bg-green-500" onClick={expand} />
  </div>

  {/* Navigation bar */}
  <div className="flex items-center gap-1 mt-1.5">
    <button onClick={goBack} disabled={historyIndex <= 0}><ArrowLeft /></button>
    <button onClick={goForward} disabled={historyIndex >= history.length - 1}><ArrowRight /></button>
    <button onClick={refresh}><ArrowClockwise /></button>
    <button onClick={goHome}><House /></button>

    {/* URL input */}
    <form onSubmit={handleUrlSubmit} className="flex-1">
      <input
        value={inputUrl}
        onChange={(e) => setInputUrl(e.target.value)}
        placeholder="/"
        className="bg-[#1a1a1a] px-2 py-0.5 rounded"
      />
    </form>
  </div>
</div>

{/* Viewport */}
<iframe
  src={getFullUrl(currentPath)}
  sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
  onLoad={() => setIsLoading(false)}
/>
```

## Edge Types

**Location**: `app/src/components/edges/`

Custom edge components for different connection types:

### DatabaseEdge.tsx
- **Color**: Green (`#22c55e`)
- **Type**: Smooth step
- **Use**: Container → Database connections

### HttpApiEdge.tsx
- **Color**: Orange (`#F89521`)
- **Type**: Smooth step
- **Use**: REST API connections

### CacheEdge.tsx
- **Color**: Blue (`#3b82f6`)
- **Type**: Smooth step
- **Use**: Cache layer connections

### EnvInjectionEdge.tsx
- **Color**: Gray (dotted)
- **Type**: Dashed line
- **Use**: Environment variable injection

### BrowserPreviewEdge.tsx
- **Color**: Blue (`#3b82f6`)
- **Type**: Smooth step
- **Use**: Container → Browser preview connections

**Edge Pattern**:
```typescript
import { memo } from 'react';
import { BaseEdge, getSmoothStepPath, type EdgeProps } from '@xyflow/react';

const EDGE_STYLE = { stroke: '#22c55e', strokeWidth: 2 };

const EdgeComponent = (props: EdgeProps) => {
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

export const CustomEdge = memo(EdgeComponent);
```

## Usage Example

```typescript
// Project.tsx
const nodeTypes = useMemo(() => ({
  container: ContainerNode,
  browserPreview: BrowserPreviewNode,
}), []);

const edgeTypes = useMemo(() => ({
  database: DatabaseEdge,
  http: HttpApiEdge,
  cache: CacheEdge,
  envInjection: EnvInjectionEdge,
  browserPreview: BrowserPreviewEdge,
}), []);

<GraphCanvas
  nodes={nodes}
  edges={edges}
  onNodesChange={onNodesChange}
  onEdgesChange={onEdgesChange}
  onConnect={handleConnect}
  onNodeClick={handleNodeClick}
  onNodeDoubleClick={openBuilder}
  nodeTypes={nodeTypes}
  edgeTypes={edgeTypes}
  theme={theme}
/>
```

## Performance Best Practices

1. **Memoize node/edge types**: Prevents re-creation on every render
2. **Use memo on custom components**: Only re-render when data changes
3. **Disable auto-pan**: Major performance gain for large graphs
4. **Static styles**: Define style objects at module level
5. **Custom comparison**: Implement arePropsEqual for precise control

---

**See CLAUDE.md for implementation patterns and debugging tips.**
