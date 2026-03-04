import { memo, useMemo } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  BackgroundVariant,
  Panel,
  type Node,
  type Edge,
  type NodeTypes,
  type EdgeTypes,
  type OnNodesChange,
  type OnEdgesChange,
  type OnConnect,
  type OnBeforeDelete,
  type ReactFlowInstance,
} from '@xyflow/react';
import { Hand } from '@phosphor-icons/react';

interface GraphCanvasProps {
  nodes: Node[];
  edges: Edge[];
  onNodesChange: OnNodesChange;
  onEdgesChange: OnEdgesChange;
  onConnect: OnConnect;
  onDrop: (event: React.DragEvent) => void;
  onDragOver: (event: React.DragEvent) => void;
  onNodeDragStart?: () => void;
  onNodeDragStop: (
    event: React.MouseEvent | React.TouchEvent | MouseEvent | TouchEvent,
    node: Node
  ) => void;
  onNodeClick: (event: React.MouseEvent, node: Node) => void;
  onNodeDoubleClick: (event: React.MouseEvent, node: Node) => void;
  onEdgeClick?: (event: React.MouseEvent, edge: Edge) => void;
  onEdgesDelete?: (edges: Edge[]) => void;
  onBeforeDelete?: OnBeforeDelete;
  onInit?: (instance: ReactFlowInstance) => void;
  onPaneClick?: (event: React.MouseEvent) => void;
  nodeTypes: NodeTypes;
  edgeTypes: EdgeTypes;
  theme: 'dark' | 'light';
}

// Static styles - defined once, never recreated
const CONNECTION_LINE_STYLE = { stroke: '#F89521', strokeWidth: 2 };
const FIT_VIEW_OPTIONS = { padding: 0.3, minZoom: 0.3, maxZoom: 1.5 };
const DEFAULT_VIEWPORT = { x: 0, y: 0, zoom: 0.5 };
const NODE_ORIGIN: [number, number] = [0.5, 0.5];

// Memoized ReactFlow wrapper to prevent re-renders from parent state changes
const GraphCanvasComponent = ({
  nodes,
  edges,
  onNodesChange,
  onEdgesChange,
  onConnect,
  onDrop,
  onDragOver,
  onNodeDragStart,
  onNodeDragStop,
  onNodeClick,
  onNodeDoubleClick,
  onEdgeClick,
  onEdgesDelete,
  onBeforeDelete,
  onInit,
  onPaneClick,
  nodeTypes,
  edgeTypes,
  theme,
}: GraphCanvasProps) => {
  const bgColor = useMemo(() => (theme === 'dark' ? '#2a2a2a' : '#e5e7eb'), [theme]);

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onConnect={onConnect}
      onDrop={onDrop}
      onDragOver={onDragOver}
      onNodeDragStart={onNodeDragStart}
      onNodeDragStop={onNodeDragStop}
      onNodeClick={onNodeClick}
      onNodeDoubleClick={onNodeDoubleClick}
      onEdgeClick={onEdgeClick}
      onEdgesDelete={onEdgesDelete}
      onBeforeDelete={onBeforeDelete}
      onInit={onInit}
      onPaneClick={onPaneClick}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      defaultViewport={DEFAULT_VIEWPORT}
      fitView
      fitViewOptions={FIT_VIEW_OPTIONS}
      minZoom={0.1}
      maxZoom={2}
      panOnScroll
      panOnDrag
      zoomOnPinch
      zoomOnScroll
      selectNodesOnDrag={false}
      // Performance optimizations
      nodeOrigin={NODE_ORIGIN}
      elevateNodesOnSelect={false}
      nodesDraggable
      nodesConnectable
      // Edge configuration - enable selection for deletion
      connectionLineStyle={CONNECTION_LINE_STYLE}
      edgesFocusable
      edgesReconnectable={false}
      // Disable auto-pan during drag (major performance gain)
      autoPanOnNodeDrag={false}
      autoPanOnConnect={false}
      // Enable Delete key for edge deletion
      deleteKeyCode={['Delete', 'Backspace']}
      selectionKeyCode={null}
      multiSelectionKeyCode={null}
      // Disable snapping for smoother drag
      snapToGrid={false}
      // Disable selection box
      selectionOnDrag={false}
      className="bg-[#0a0a0a] touch-none"
    >
      <Background variant={BackgroundVariant.Dots} gap={20} size={0.8} color={bgColor} />
      <Controls className="!bg-[var(--surface)] !border-[var(--sidebar-border)] !shadow-lg [&>button]:!bg-[var(--surface)] [&>button]:!border-[var(--sidebar-border)] [&>button]:!fill-[var(--text)] [&>button:hover]:!bg-[var(--sidebar-hover)]" />

      {/* Desktop hint */}
      <Panel
        position="top-right"
        className="hidden md:block bg-[var(--surface)] px-4 py-2 rounded-lg shadow-lg border border-[var(--sidebar-border)]"
      >
        <p className="text-xs text-[var(--text)]/60">
          Double-click a container to open the builder
        </p>
      </Panel>

      {/* Mobile hint - positioned below floating buttons */}
      <Panel
        position="top-center"
        className="md:hidden !top-16 bg-[var(--surface)] px-3 py-1.5 rounded-lg shadow-lg border border-[var(--sidebar-border)]"
      >
        <p className="text-[10px] text-[var(--text)]/60 flex items-center gap-1.5">
          <Hand size={12} className="text-[var(--primary)]" />
          Pinch to zoom - Drag to pan
        </p>
      </Panel>

      {/* SVG marker definitions for custom edge arrows */}
      <svg style={{ position: 'absolute', top: 0, left: 0, width: 0, height: 0 }}>
        <defs>
          {/* Deployment edge arrow marker - orange to match deployment theme */}
          <marker
            id="deployment-arrow"
            viewBox="0 0 10 10"
            refX="8"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#F38020" />
          </marker>
        </defs>
      </svg>
    </ReactFlow>
  );
};

// Custom comparison - only re-render when nodes/edges actually change
const arePropsEqual = (prev: GraphCanvasProps, next: GraphCanvasProps): boolean => {
  return (
    prev.nodes === next.nodes &&
    prev.edges === next.edges &&
    prev.theme === next.theme &&
    prev.nodeTypes === next.nodeTypes &&
    prev.edgeTypes === next.edgeTypes &&
    prev.onEdgeClick === next.onEdgeClick &&
    prev.onEdgesDelete === next.onEdgesDelete &&
    prev.onBeforeDelete === next.onBeforeDelete &&
    prev.onInit === next.onInit &&
    prev.onPaneClick === next.onPaneClick
  );
};

export const GraphCanvas = memo(GraphCanvasComponent, arePropsEqual);
