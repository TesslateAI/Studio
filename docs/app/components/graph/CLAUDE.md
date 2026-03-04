# Graph Components - AI Agent Context

## Adding a Custom Node Type

1. **Create node component**:
```typescript
// MyCustomNode.tsx
import { memo } from 'react';
import { Handle, Position, type Node } from '@xyflow/react';

interface CustomNodeData {
  title: string;
  description?: string;
}

type CustomNodeProps = Node<CustomNodeData>;

const CustomNodeComponent = ({ data, id }: CustomNodeProps) => {
  return (
    <div className="bg-[#1a1a1a] rounded-xl p-4">
      <Handle type="target" position={Position.Left} />
      <Handle type="source" position={Position.Right} />

      <h3 className="font-bold text-white">{data.title}</h3>
      {data.description && <p className="text-gray-400 text-sm">{data.description}</p>}
    </div>
  );
};

export const CustomNode = memo(CustomNodeComponent);
```

2. **Register node type**:
```typescript
// Project.tsx
const nodeTypes = useMemo(() => ({
  container: ContainerNode,
  browserPreview: BrowserPreviewNode,
  custom: CustomNode,  // Add new type
}), []);
```

3. **Create nodes with type**:
```typescript
const newNode: Node = {
  id: 'node-1',
  type: 'custom',
  position: { x: 100, y: 100 },
  data: {
    title: 'My Custom Node',
    description: 'Description here'
  }
};
```

## Adding a Custom Edge Type

```typescript
// CustomEdge.tsx
import { memo } from 'react';
import { BaseEdge, getSmoothStepPath, EdgeLabelRenderer, type EdgeProps } from '@xyflow/react';

const EDGE_STYLE = { stroke: '#ff00ff', strokeWidth: 3 };

const CustomEdgeComponent = (props: EdgeProps) => {
  const [edgePath, labelX, labelY] = getSmoothStepPath({
    sourceX: props.sourceX,
    sourceY: props.sourceY,
    sourcePosition: props.sourcePosition,
    targetX: props.targetX,
    targetY: props.targetY,
    targetPosition: props.targetPosition,
  });

  return (
    <>
      <BaseEdge id={props.id} path={edgePath} style={EDGE_STYLE} />

      {/* Optional: Add label */}
      <EdgeLabelRenderer>
        <div
          style={{
            position: 'absolute',
            transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
            pointerEvents: 'all',
          }}
          className="nodrag nopan bg-black px-2 py-1 rounded text-xs"
        >
          {props.label}
        </div>
      </EdgeLabelRenderer>
    </>
  );
};

export const CustomEdge = memo(CustomEdgeComponent);

// Register
const edgeTypes = useMemo(() => ({
  custom: CustomEdge,
}), []);
```

## Handling Node Interactions

### Click, Double-Click, Drag

```typescript
<GraphCanvas
  onNodeClick={(event, node) => {
    console.log('[Graph] Node clicked:', node.id);
    setSelectedNode(node);
  }}
  onNodeDoubleClick={(event, node) => {
    console.log('[Graph] Node double-clicked:', node.id);
    if (node.type === 'container') {
      openBuilder(node.id);
    }
  }}
  onNodeDragStop={(event, node) => {
    console.log('[Graph] Node dragged to:', node.position);
    // Position automatically updated by XYFlow
  }}
/>
```

### Adding Context Menu

```typescript
const [contextMenu, setContextMenu] = useState<{ x: number; y: number; node: Node } | null>(null);

<GraphCanvas
  onNodeClick={(event, node) => {
    if (event.button === 2) {  // Right-click
      event.preventDefault();
      setContextMenu({
        x: event.clientX,
        y: event.clientY,
        node
      });
    }
  }}
/>

{contextMenu && (
  <div
    style={{ position: 'fixed', top: contextMenu.y, left: contextMenu.x }}
    className="bg-[var(--surface)] border rounded-lg shadow-lg"
  >
    <button onClick={() => deleteNode(contextMenu.node.id)}>Delete</button>
    <button onClick={() => duplicateNode(contextMenu.node)}>Duplicate</button>
  </div>
)}
```

## Connecting Nodes

### Creating Connections

```typescript
const onConnect: OnConnect = useCallback((connection) => {
  // connection: { source, target, sourceHandle, targetHandle }

  const newEdge: Edge = {
    id: `edge-${connection.source}-${connection.target}`,
    source: connection.source,
    target: connection.target,
    type: 'database',  // or determine dynamically
    animated: true,    // optional: animated edge
  };

  setEdges((eds) => addEdge(newEdge, eds));
}, []);

<GraphCanvas onConnect={onConnect} />
```

### Validating Connections

Prevent invalid connections:
```typescript
const isValidConnection = useCallback((connection: Connection) => {
  const sourceNode = nodes.find(n => n.id === connection.source);
  const targetNode = nodes.find(n => n.id === connection.target);

  // Example: Only allow container → database connections
  if (sourceNode?.type === 'container' && targetNode?.type !== 'database') {
    return false;
  }

  // Prevent self-connections
  if (connection.source === connection.target) {
    return false;
  }

  return true;
}, [nodes]);

<ReactFlow
  isValidConnection={isValidConnection}
  // ...
/>
```

## Drag-and-Drop New Nodes

```typescript
const onDragOver = useCallback((event: React.DragEvent) => {
  event.preventDefault();
  event.dataTransfer.dropEffect = 'move';
}, []);

const onDrop = useCallback((event: React.DragEvent) => {
  event.preventDefault();

  const type = event.dataTransfer.getData('application/reactflow');
  const position = reactFlowInstance.screenToFlowPosition({
    x: event.clientX,
    y: event.clientY,
  });

  const newNode = {
    id: `${type}-${Date.now()}`,
    type,
    position,
    data: { /* default data */ },
  };

  setNodes((nds) => nds.concat(newNode));
}, [reactFlowInstance]);

// Draggable element
<div
  draggable
  onDragStart={(event) => {
    event.dataTransfer.setData('application/reactflow', 'container');
    event.dataTransfer.effectAllowed = 'move';
  }}
>
  Drag me to canvas
</div>
```

## Debugging Graph Issues

### Nodes Not Rendering

Check:
1. Node type registered in `nodeTypes`
2. Node has `position` property
3. Node data matches interface

Debug:
```typescript
useEffect(() => {
  console.log('[Graph] Nodes:', nodes.map(n => ({ id: n.id, type: n.type, position: n.position })));
  console.log('[Graph] Node types:', Object.keys(nodeTypes));
}, [nodes, nodeTypes]);
```

### Edges Not Appearing

Check:
1. Edge type registered in `edgeTypes`
2. Source/target IDs exist in nodes
3. Handles on nodes (source/target)

Debug:
```typescript
useEffect(() => {
  edges.forEach(edge => {
    const sourceExists = nodes.find(n => n.id === edge.source);
    const targetExists = nodes.find(n => n.id === edge.target);

    if (!sourceExists) console.error(`[Graph] Source not found for edge ${edge.id}: ${edge.source}`);
    if (!targetExists) console.error(`[Graph] Target not found for edge ${edge.id}: ${edge.target}`);
  });
}, [nodes, edges]);
```

### Performance Issues

Check:
1. `nodeTypes` and `edgeTypes` memoized
2. Custom nodes memoized
3. `autoPanOnNodeDrag={false}`
4. No expensive calculations in render

Profile:
```typescript
import { Profiler } from 'react';

<Profiler
  id="GraphCanvas"
  onRender={(id, phase, actualDuration) => {
    console.log(`[${id}] ${phase} took ${actualDuration}ms`);
  }}
>
  <GraphCanvas {...props} />
</Profiler>
```

## Browser Preview Integration

### Connecting Container to Browser

```typescript
// When user drags from container to browser preview
const onConnect = useCallback((connection) => {
  if (connection.target.startsWith('browser-')) {
    // Update browser preview node data
    setNodes(nds => nds.map(node => {
      if (node.id === connection.target) {
        const sourceContainer = nds.find(n => n.id === connection.source);

        return {
          ...node,
          data: {
            ...node.data,
            connectedContainerId: connection.source,
            connectedContainerName: sourceContainer?.data.name,
            connectedPort: sourceContainer?.data.port,
            baseUrl: `http://localhost:${sourceContainer?.data.port}`
          }
        };
      }
      return node;
    }));

    // Create edge
    const newEdge = {
      id: `preview-${connection.source}`,
      source: connection.source,
      target: connection.target,
      type: 'browserPreview',
    };

    setEdges(eds => addEdge(newEdge, eds));
  }
}, []);
```

## Auto-Layout with Dagre

**File**: `app/src/utils/autoLayout.ts`

Apply automatic layout to graph nodes using the Dagre algorithm.

### Basic Usage

```typescript
import { getLayoutedElements } from '../utils/autoLayout';

// Apply layout when loading nodes
const loadContainers = async () => {
  const containers = await projectsApi.getContainers(slug);
  const connections = await projectsApi.getConnections(slug);

  // Convert to XYFlow format
  const nodes = containers.map(c => ({
    id: c.id,
    type: 'containerNode',
    position: { x: 0, y: 0 }, // Will be replaced by layout
    data: { name: c.name, status: c.status },
  }));

  const edges = connections.map(conn => ({
    id: conn.id,
    source: conn.source_container_id,
    target: conn.target_container_id,
  }));

  // Apply Dagre layout
  const { nodes: layoutedNodes, edges: layoutedEdges } = getLayoutedElements(
    nodes,
    edges,
    { direction: 'LR' }
  );

  setNodes(layoutedNodes);
  setEdges(layoutedEdges);
};
```

### Layout Options

```typescript
interface LayoutOptions {
  direction: 'LR' | 'TB';  // Left-Right or Top-Bottom
  nodeWidth?: number;       // Default: 180
  nodeHeight?: number;      // Default: 100
  nodeSep?: number;         // Horizontal spacing between nodes (default: 80)
  rankSep?: number;         // Spacing between ranks/levels (default: 150)
}
```

### Auto-Layout on Button Click

```typescript
const handleAutoLayout = () => {
  const { nodes: layoutedNodes, edges: layoutedEdges } = getLayoutedElements(
    nodes,
    edges,
    { direction: 'LR', nodeSep: 100, rankSep: 200 }
  );

  setNodes(layoutedNodes);
  setEdges(layoutedEdges);
  toast.success('Layout applied');
};

// In JSX
<button onClick={handleAutoLayout}>
  <GridFour /> Auto Layout
</button>
```

### Different Node Sizes

The layout automatically handles different node types:

```typescript
// In getLayoutedElements, nodes are sized by type:
if (node.type === 'browserPreview') {
  width = 320;
  height = 280;
} else {
  // Default container node size
  width = 180;
  height = 100;
}
```

### Position Conversion

Dagre returns center positions, but React Flow uses top-left. The utility handles conversion:

```typescript
// Dagre gives center position
const nodeWithPosition = g.node(node.id);

// Convert to top-left for React Flow
position: {
  x: nodeWithPosition.x - width / 2,
  y: nodeWithPosition.y - height / 2,
}
```

---

**Remember**: XYFlow is highly optimized. Don't fight its performance model. Use memo, memoize types, and avoid expensive render logic.
