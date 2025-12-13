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
  onNodeDragStop: (event: any, node: Node) => void;
  onNodeClick: (event: React.MouseEvent, node: Node) => void;
  onNodeDoubleClick: (event: React.MouseEvent, node: Node) => void;
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
  nodeTypes,
  edgeTypes,
  theme,
}: GraphCanvasProps) => {
  const bgColor = useMemo(
    () => (theme === 'dark' ? '#2a2a2a' : '#e5e7eb'),
    [theme]
  );

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
      // Edge performance optimizations
      connectionLineStyle={CONNECTION_LINE_STYLE}
      edgesFocusable={false}
      edgesReconnectable={false}
      // Disable auto-pan during drag (major performance gain)
      autoPanOnNodeDrag={false}
      autoPanOnConnect={false}
      // Disable keyboard shortcuts during drag
      deleteKeyCode={null}
      selectionKeyCode={null}
      multiSelectionKeyCode={null}
      // Disable snapping for smoother drag
      snapToGrid={false}
      // Disable selection box
      selectionOnDrag={false}
      className="bg-[#0a0a0a] touch-none"
    >
      <Background
        variant={BackgroundVariant.Dots}
        gap={20}
        size={0.8}
        color={bgColor}
      />
      <Controls className="!bg-[var(--surface)] !border-[var(--sidebar-border)] !shadow-lg [&>button]:!bg-[var(--surface)] [&>button]:!border-[var(--sidebar-border)] [&>button]:!fill-[var(--text)] [&>button:hover]:!bg-[var(--sidebar-hover)]" />

      {/* Desktop hint */}
      <Panel position="top-right" className="hidden md:block bg-[var(--surface)] px-4 py-2 rounded-lg shadow-lg border border-[var(--sidebar-border)]">
        <p className="text-xs text-[var(--text)]/60">
          Double-click a container to open the builder
        </p>
      </Panel>

      {/* Mobile hint */}
      <Panel position="top-center" className="md:hidden bg-[var(--surface)] px-3 py-1.5 rounded-lg shadow-lg border border-[var(--sidebar-border)]">
        <p className="text-[10px] text-[var(--text)]/60 flex items-center gap-1.5">
          <Hand size={12} className="text-[var(--primary)]" />
          Pinch to zoom - Drag to pan
        </p>
      </Panel>
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
    prev.edgeTypes === next.edgeTypes
  );
};

export const GraphCanvas = memo(GraphCanvasComponent, arePropsEqual);
