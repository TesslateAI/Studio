# Project Graph Canvas Page

**File**: `c:/Users/Smirk/Downloads/Tesslate-Studio/app/src/pages/ProjectGraphCanvas.tsx`
**Route**: `/project/:slug`
**Layout**: Standalone (full-screen with XYFlow canvas)

## Purpose

The Project Graph Canvas provides a visual architecture view of the project using XYFlow. Users can see containers as nodes, their connections as edges, add browser preview nodes, drag to reposition, and manage the entire system topology from this interface.

## Key Features

### 1. Interactive Graph Canvas
- Drag nodes to reposition
- Zoom and pan
- Minimap navigation
- **Auto-layout using Dagre algorithm**
- Snap to grid

### Auto-Layout with Dagre

The graph canvas uses the Dagre algorithm for intelligent automatic layout of nodes.

**Usage**:
```typescript
import { getLayoutedElements } from '../utils/autoLayout';

// Apply auto-layout to nodes and edges
const { nodes: layoutedNodes, edges: layoutedEdges } = getLayoutedElements(
  nodes,
  edges,
  { direction: 'LR', nodeSep: 80, rankSep: 150 }
);

setNodes(layoutedNodes);
setEdges(layoutedEdges);
```

**Layout Options**:
```typescript
interface LayoutOptions {
  direction: 'LR' | 'TB';  // Left-Right or Top-Bottom
  nodeWidth?: number;       // Default node width (default: 180)
  nodeHeight?: number;      // Default node height (default: 100)
  nodeSep?: number;         // Horizontal separation (default: 80)
  rankSep?: number;         // Vertical/rank separation (default: 150)
}
```

**Node Size Handling**:
- Container nodes: 180x100 (default)
- Browser preview nodes: 320x280 (automatically detected by node type)

The layout algorithm:
1. Creates a Dagre graph with all nodes and edges
2. Calculates optimal positions based on connections
3. Converts Dagre's center positions to React Flow's top-left positioning
4. Returns new nodes with updated positions (edges unchanged)

### 2. Container Nodes
- Visual representation of each container (frontend, backend, database, etc.)
- Status indicator (stopped, starting, running, failed)
- Port display
- Click to view properties
- Start/stop individual containers

### 3. Connection Edges
Semantic edge types showing relationships:
- **HTTP API**: REST API calls between services
- **Database**: Database connections
- **Cache**: Redis/memcached connections
- **Env Injection**: Environment variable sharing
- **Browser Preview**: Preview connections

### 4. Browser Preview Nodes
- Special nodes that display live preview of a container
- Resizable iframe
- URL navigation within node
- Multiple preview nodes supported

### 5. Start/Stop All
- Start all containers with single button
- Stop all containers
- Status polling during startup

### 6. Deploy All
- **Deploy All Button**: One-click deployment of all containers with assigned deployment targets
- Shows count badge with number of deployable containers
- Parallel deployment execution (non-blocking)
- Toast notifications for success/failure per container

### 7. Deployment Targets (Drag-and-Drop)
- Drag deployment target items (Vercel, Netlify, Cloudflare) from Marketplace sidebar
- Drop onto base container nodes to assign deployment provider
- Visual feedback: purple drop zone overlay when dragging over valid containers
- Deployment provider badge shows on assigned containers (bottom-right corner)
- Only base containers can receive deployment targets (services are excluded)

### 8. Container Properties Panel
- Edit container configuration
- View environment variables
- Manage connections
- **Deployment Target section** (base containers only):
  - View/change assigned deployment provider
  - Shows credential connection status
  - Quick link to connect accounts in Settings
- Delete container

### 9. AI Chat Integration
- Same chat interface as builder
- Graph-scoped tools (add_container, create_connection, etc.)
- View context: 'graph'

## Navigation

The Architecture canvas provides intuitive navigation between views:

- **Back to Projects**: Left sidebar button navigates to `/dashboard` (project list)
- **Builder Button**: Top bar button navigates to `/project/:slug/builder` (builder view with first container)
- **Double-click Container**: Opens that container in builder view

This mirrors the builder view which has a reciprocal "Architecture" button, allowing users to seamlessly switch between views like different perspectives of the same project (similar to ClickUp's view system).

## Component Structure

```
ProjectGraphCanvas
├── Header
│   ├── Breadcrumbs
│   ├── Builder button (→ /project/:slug/builder)
│   ├── Start/Stop all button
│   ├── Deploy All button (with deployable count badge)
│   └── View switcher (graph/code/kanban)
│
├── Left Sidebar (collapsible)
│   ├── Back to Projects button (→ /dashboard)
│   ├── Panel toggles
│   │   ├── GitHub
│   │   ├── Notes
│   │   └── Settings
│   └── Marketplace browser
│       └── Deploy Targets category (Vercel, Netlify, Cloudflare)
│
├── Main Canvas
│   └── GraphCanvas (XYFlow)
│       ├── Container Nodes (with deployment badges)
│       ├── Browser Preview Nodes
│       └── Connection Edges
│
├── Coming Soon Banner (architecture chat placeholder)
│
├── Floating Panels
│   ├── GitHubPanel
│   ├── NotesPanel
│   └── SettingsPanel
│
└── Container Properties Panel
    ├── (shows when container selected)
    └── Deployment Target section (base containers)
```

## State Management

```typescript
// XYFlow nodes and edges
const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

// Project data
const [project, setProject] = useState<Record<string, unknown> | null>(null);
const [files, setFiles] = useState<Array<Record<string, unknown>>>([]);
const [agents, setAgents] = useState<UIAgent[]>([]);

// Container status
const [isRunning, setIsRunning] = useState(false);

// UI state
const [activeView, setActiveView] = useState<'graph' | 'code' | 'kanban'>('graph');
const [activePanel, setActivePanel] = useState<PanelType>(null);
const [isLeftSidebarExpanded, setIsLeftSidebarExpanded] = useState(true);
const [selectedContainer, setSelectedContainer] = useState<{
  id: string;
  name: string;
  status: string;
  port?: number;
  containerType?: 'base' | 'service';
  deploymentProvider?: 'vercel' | 'netlify' | 'cloudflare' | null;
} | null>(null);

// Drag state (pauses polling during drag for performance)
const [isDragging, setIsDragging] = useState(false);

// Deployment metrics (computed)
const deployableCount = useMemo(() => {
  return nodes.filter(n => n.type === 'containerNode' && n.data?.deploymentProvider).length;
}, [nodes]);
```

## Data Flow

### Loading Graph Data

```typescript
useEffect(() => {
  if (slug) {
    loadProject();
    loadContainers();
    loadConnections();
    loadAppDomain();
  }
}, [slug]);

const loadContainers = async () => {
  try {
    const containers = await projectsApi.getContainers(slug);

    // Convert to XYFlow nodes
    const containerNodes = containers.map(c => ({
      id: c.id,
      type: 'containerNode',
      position: { x: c.position_x || 0, y: c.position_y || 0 },
      data: {
        id: c.id,
        name: c.name,
        status: c.status,
        port: c.port,
        base_id: c.base_id,
        onStartStop: handleStartStopContainer,
        onDelete: handleDeleteContainer,
        onSelect: handleSelectContainer,
      },
    }));

    setNodes(containerNodes);
  } catch (error) {
    toast.error('Failed to load containers');
  }
};

const loadConnections = async () => {
  try {
    const connections = await projectsApi.getConnections(slug);

    // Convert to XYFlow edges
    const edgeList = connections.map(conn => ({
      id: conn.id,
      source: conn.source_container_id,
      target: conn.target_container_id,
      type: getEdgeType(conn.connection_type),
      label: conn.label,
      data: {
        connection_type: conn.connection_type,
      },
    }));

    setEdges(edgeList);
  } catch (error) {
    toast.error('Failed to load connections');
  }
};
```

### Node Position Updates

When a user drags a node, save the new position to the backend:

```typescript
// Debounced save to reduce API calls
const saveNodePosition = useCallback(
  debounce(async (nodeId: string, x: number, y: number) => {
    try {
      await projectsApi.updateContainerPosition(slug, nodeId, x, y);
    } catch (error) {
      console.error('Failed to save position:', error);
    }
  }, 500),
  [slug]
);

// Handle node drag end
const onNodeDragStop = useCallback((event: unknown, node: Node) => {
  setIsDragging(false);
  saveNodePosition(node.id, node.position.x, node.position.y);
}, [saveNodePosition]);

const onNodeDragStart = useCallback(() => {
  setIsDragging(true); // Pause status polling
}, []);
```

### Adding Containers

```typescript
const handleAddContainer = async (containerData: ContainerCreate) => {
  try {
    const newContainer = await projectsApi.createContainer(slug, containerData);

    // Add to graph
    const newNode = {
      id: newContainer.id,
      type: 'containerNode',
      position: { x: 100, y: 100 }, // Default position
      data: {
        id: newContainer.id,
        name: newContainer.name,
        status: 'stopped',
        onStartStop: handleStartStopContainer,
        onDelete: handleDeleteContainer,
        onSelect: handleSelectContainer,
      },
    };

    setNodes(nodes => [...nodes, newNode]);
    toast.success('Container added');
  } catch (error) {
    toast.error('Failed to add container');
  }
};
```

### Creating Connections

```typescript
// Handle edge creation (drag from one node to another)
const onConnect: OnConnect = useCallback(async (connection) => {
  try {
    const newConnection = await projectsApi.createConnection(slug, {
      source_container_id: connection.source,
      target_container_id: connection.target,
      connection_type: 'http_api', // Default, can be changed in properties
    });

    // Add edge to graph
    const newEdge = {
      id: newConnection.id,
      source: connection.source,
      target: connection.target,
      type: 'http_api',
      data: { connection_type: 'http_api' },
    };

    setEdges(edges => addEdge(newEdge, edges));
    toast.success('Connection created');
  } catch (error) {
    toast.error('Failed to create connection');
  }
}, [slug, setEdges]);
```

### Starting/Stopping Containers

```typescript
const handleStartStopContainer = async (containerId: string, currentStatus: string) => {
  try {
    if (currentStatus === 'running') {
      await projectsApi.stopContainer(slug, containerId);
      toast.success('Container stopped');
    } else {
      await projectsApi.startContainer(slug, containerId);
      toast.success('Container starting...');
    }

    // Update node status
    setNodes(nodes =>
      nodes.map(n =>
        n.id === containerId
          ? { ...n, data: { ...n.data, status: currentStatus === 'running' ? 'stopped' : 'starting' } }
          : n
      )
    );

    // Poll for status updates
    pollContainerStatus(containerId);
  } catch (error) {
    toast.error('Failed to update container');
  }
};

const handleStartAll = async () => {
  try {
    await projectsApi.startProject(slug);
    setIsRunning(true);
    toast.success('Starting all containers...');

    // Poll for status
    pollAllStatus();
  } catch (error) {
    toast.error('Failed to start project');
  }
};

const handleStopAll = async () => {
  try {
    await projectsApi.stopProject(slug);
    setIsRunning(false);
    toast.success('Stopping all containers...');

    // Update all node statuses
    setNodes(nodes =>
      nodes.map(n => ({ ...n, data: { ...n.data, status: 'stopped' } }))
    );
  } catch (error) {
    toast.error('Failed to stop project');
  }
};
```

### Status Polling

Poll for container status updates, but pause during drag operations for performance:

```typescript
useEffect(() => {
  if (!isDragging && project) {
    const interval = setInterval(() => {
      refreshContainerStatus();
    }, 5000); // Every 5 seconds

    return () => clearInterval(interval);
  }
}, [isDragging, project]);

const refreshContainerStatus = async () => {
  try {
    const containers = await projectsApi.getContainers(slug);

    // Update node statuses
    setNodes(nodes =>
      nodes.map(node => {
        const container = containers.find(c => c.id === node.id);
        if (container) {
          return {
            ...node,
            data: { ...node.data, status: container.status },
          };
        }
        return node;
      })
    );
  } catch (error) {
    console.error('Failed to refresh status:', error);
  }
};
```

### Deployment Target Drag-and-Drop

Handle dropping deployment targets from marketplace onto containers:

```typescript
// In onDrop handler
const onDrop = useCallback(async (event: React.DragEvent) => {
  const nodeType = event.dataTransfer.getData('application/reactflow');
  const baseData = event.dataTransfer.getData('base');
  const item = JSON.parse(baseData);

  // Handle deployment target drops - must be dropped on existing container
  if (nodeType === 'deploymentTarget') {
    // Convert screen coords to flow coords
    const flowPosition = reactFlowInstance.screenToFlowPosition({
      x: event.clientX,
      y: event.clientY,
    });

    // Find container node at drop position
    const targetNode = nodes.find(n => {
      if (n.type !== 'containerNode') return false;
      // Check if drop position is within node bounds
      return isPositionInsideNode(flowPosition, n);
    });

    if (targetNode && targetNode.data.containerType === 'base') {
      // Extract provider from slug (e.g., 'vercel-deploy' -> 'vercel')
      const provider = item.slug.replace('-deploy', '');
      await projectsApi.assignDeploymentTarget(slug, targetNode.id, provider);

      // Update node locally
      setNodes(nds => nds.map(node =>
        node.id === targetNode.id
          ? { ...node, data: { ...node.data, deploymentProvider: provider } }
          : node
      ));
      toast.success(`${item.name} assigned to ${targetNode.data.name}`);
    } else {
      toast.error('Drop deployment target onto a base container');
    }
    return;
  }

  // ... handle other node types
}, [nodes, slug, reactFlowInstance]);
```

### Deploy All Handler

Deploy all containers with assigned deployment targets:

```typescript
const handleDeployAll = async () => {
  if (!slug || deployableCount === 0) return;

  toast.loading(`Deploying ${deployableCount} container(s)...`, { id: 'deploy-all' });
  const result = await deploymentsApi.deployAll(slug);

  if (result.failed === 0) {
    toast.success(`Successfully deployed ${result.deployed} container(s)!`, { id: 'deploy-all' });
  } else {
    toast.error(`${result.deployed} deployed, ${result.failed} failed`, { id: 'deploy-all' });
  }
};
```

### Browser Preview Nodes

Add live preview nodes to the graph:

```typescript
const handleAddPreviewNode = (containerId: string) => {
  const container = nodes.find(n => n.id === containerId);
  if (!container) return;

  const previewNode = {
    id: `preview-${containerId}`,
    type: 'browserPreview',
    position: {
      x: container.position.x + 300,
      y: container.position.y,
    },
    data: {
      containerId: containerId,
      url: `http://${container.data.name}.${appDomain}`,
      onClose: () => {
        // Remove preview node
        setNodes(nodes => nodes.filter(n => n.id !== `preview-${containerId}`));
        setEdges(edges => edges.filter(e => e.target !== `preview-${containerId}`));
      },
    },
  };

  // Add preview edge
  const previewEdge = {
    id: `preview-edge-${containerId}`,
    source: containerId,
    target: `preview-${containerId}`,
    type: 'browser_preview',
  };

  setNodes(nodes => [...nodes, previewNode]);
  setEdges(edges => [...edges, previewEdge]);
};
```

## Custom Node Types

### Container Node

```typescript
// components/ContainerNode.tsx
export function ContainerNode({ data }: NodeProps) {
  return (
    <div className="container-node" data-status={data.status}>
      <div className="node-header">
        <h3>{data.name}</h3>
        <StatusBadge status={data.status} />
      </div>

      <div className="node-body">
        {data.port && <span>Port: {data.port}</span>}
      </div>

      <div className="node-actions">
        <button onClick={() => data.onStartStop(data.id, data.status)}>
          {data.status === 'running' ? <Stop /> : <Play />}
        </button>
        <button onClick={() => data.onSelect(data)}>
          <Gear />
        </button>
      </div>

      {/* XYFlow handles */}
      <Handle type="source" position={Position.Right} />
      <Handle type="target" position={Position.Left} />
    </div>
  );
}
```

### Browser Preview Node

```typescript
// components/BrowserPreviewNode.tsx
export function BrowserPreviewNode({ data }: NodeProps) {
  const [currentUrl, setCurrentUrl] = useState(data.url);

  return (
    <div className="browser-preview-node">
      <div className="preview-header">
        <input
          type="text"
          value={currentUrl}
          onChange={(e) => setCurrentUrl(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              // Navigate to URL
            }
          }}
        />
        <button onClick={data.onClose}>
          <X />
        </button>
      </div>

      <iframe
        src={data.url}
        className="preview-frame"
        sandbox="allow-same-origin allow-scripts"
      />

      {/* XYFlow handle */}
      <Handle type="target" position={Position.Left} />
    </div>
  );
}
```

## Custom Edge Types

```typescript
// components/edges/HttpApiEdge.tsx
export function HttpApiEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  label,
}: EdgeProps) {
  const [edgePath] = getBezierPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
  });

  return (
    <>
      <path
        id={id}
        className="http-api-edge"
        d={edgePath}
        strokeWidth={2}
        stroke="#10b981"
        fill="none"
      />
      {label && (
        <EdgeLabelRenderer>
          <div className="edge-label">{label}</div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

// Similar for DatabaseEdge, CacheEdge, etc.
```

## AI Chat (Coming Soon)

The architecture canvas chat is currently disabled and shows a "Coming Soon" banner. AI-powered architecture editing via chat is planned for a future release. Users should use the Builder view (`/project/:slug/builder`) for chat-based interactions.

## Container Properties Panel

When a container is selected, show a properties panel:

```typescript
{selectedContainer && (
  <ContainerPropertiesPanel
    container={selectedContainer}
    onUpdate={async (updates) => {
      try {
        await projectsApi.updateContainer(slug, selectedContainer.id, updates);
        toast.success('Container updated');
        loadContainers(); // Refresh
      } catch (error) {
        toast.error('Failed to update container');
      }
    }}
    onClose={() => setSelectedContainer(null)}
  />
)}
```

## View Switching

Users can switch between graph, code, and kanban views:

```typescript
<Tabs value={activeView} onChange={setActiveView}>
  <Tab value="graph">
    <FlowArrow /> Graph
  </Tab>
  <Tab value="code">
    <Code /> Code
  </Tab>
  <Tab value="kanban">
    <Kanban /> Kanban
  </Tab>
</Tabs>

{/* Render appropriate view */}
{activeView === 'graph' && <GraphCanvas ... />}
{activeView === 'code' && <CodeEditor ... />}
{activeView === 'kanban' && <KanbanPanel ... />}
```

## API Endpoints Used

```typescript
// Get containers
GET /api/projects/{slug}/containers

// Create container
POST /api/projects/{slug}/containers
{ name, base_id, port, env_vars }

// Update container
PUT /api/projects/{slug}/containers/{id}
{ name, port, env_vars }

// Update container position
PUT /api/projects/{slug}/containers/{id}/position
{ x, y }

// Delete container
DELETE /api/projects/{slug}/containers/{id}

// Get connections
GET /api/projects/{slug}/connections

// Create connection
POST /api/projects/{slug}/connections
{ source_container_id, target_container_id, connection_type, label }

// Delete connection
DELETE /api/projects/{slug}/connections/{id}

// Start container
POST /api/projects/{slug}/containers/{id}/start

// Stop container
POST /api/projects/{slug}/containers/{id}/stop

// Start all
POST /api/projects/{slug}/start

// Stop all
POST /api/projects/{slug}/stop

// Assign/remove deployment target for a container
PATCH /api/projects/{slug}/containers/{id}/deployment-target
{ provider: 'vercel' | 'netlify' | 'cloudflare' | null }

// Deploy all containers with assigned deployment targets
POST /api/deployments/{slug}/deploy-all
// Returns: { total, deployed, failed, skipped, results: [...] }
```

## Best Practices

### 1. Pause Polling During Drag
```typescript
const [isDragging, setIsDragging] = useState(false);

useEffect(() => {
  if (!isDragging) {
    const interval = setInterval(pollStatus, 5000);
    return () => clearInterval(interval);
  }
}, [isDragging]);
```

### 2. Debounce Position Saves
```typescript
const savePosition = useCallback(
  debounce((id, x, y) => {
    api.updatePosition(id, x, y);
  }, 500),
  []
);
```

### 3. Use Refs for Stable Callbacks
```typescript
const nodesRef = useRef(nodes);
useEffect(() => { nodesRef.current = nodes; }, [nodes]);

// Use nodesRef.current in callbacks to avoid re-creating
```

## Troubleshooting

**Issue**: Nodes not draggable
- Check `nodesDraggable` prop on ReactFlow
- Verify no event handlers blocking drag

**Issue**: Edges not connecting
- Check `onConnect` callback is set
- Verify handles are present on nodes

**Issue**: Status not updating
- Check polling interval is active
- Verify API returns correct status
- Ensure isDragging doesn't block polling
