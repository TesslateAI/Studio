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
  onNodeDragStop: (event: any, node: Node) => void;
  onNodeClick: (event: React.MouseEvent, node: Node) => void;
  onNodeDoubleClick: (event: React.MouseEvent, node: Node) => void;
  nodeTypes: NodeTypes;
  edgeTypes: EdgeTypes;
  theme: 'dark' | 'light';
}

// Memoized ReactFlow wrapper to prevent re-renders from parent state changes
const GraphCanvasComponent = ({
  nodes,
  edges,
  onNodesChange,
  onEdgesChange,
  onConnect,
  onDrop,
  onDragOver,
  onNodeDragStop,
  onNodeClick,
  onNodeDoubleClick,
  nodeTypes,
  edgeTypes,
  theme,
}: GraphCanvasProps) => {
  const bgColor = useMemo(
    () => (theme === 'dark' ? '#374151' : '#e5e7eb'),
    [theme]
  );

  const connectionLineStyle = useMemo(() => ({
    stroke: 'var(--primary)',
    strokeWidth: 2,
  }), []);

  const fitViewOptions = useMemo(() => ({
    padding: 0.3,
    minZoom: 0.3,
    maxZoom: 1.5,
  }), []);

  const defaultViewport = useMemo(() => ({
    x: 0,
    y: 0,
    zoom: 0.5,
  }), []);

  const nodeOrigin = useMemo((): [number, number] => [0.5, 0.5], []);

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onConnect={onConnect}
      onDrop={onDrop}
      onDragOver={onDragOver}
      onNodeDragStop={onNodeDragStop}
      onNodeClick={onNodeClick}
      onNodeDoubleClick={onNodeDoubleClick}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      defaultViewport={defaultViewport}
      fitView
      fitViewOptions={fitViewOptions}
      minZoom={0.1}
      maxZoom={2}
      panOnScroll
      panOnDrag
      zoomOnPinch
      zoomOnScroll
      selectNodesOnDrag={false}
      // Performance optimizations
      nodeOrigin={nodeOrigin}
      elevateNodesOnSelect={false}
      // Edge performance optimizations
      connectionLineStyle={connectionLineStyle}
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
      className="bg-[var(--bg)] touch-none"
    >
      <Background
        variant={BackgroundVariant.Dots}
        gap={16}
        size={1}
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
          Pinch to zoom • Drag to pan
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
