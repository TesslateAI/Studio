import Dagre from '@dagrejs/dagre';
import { type Node, type Edge } from '@xyflow/react';

export interface LayoutOptions {
  direction: 'LR' | 'TB'; // Left-Right or Top-Bottom
  nodeWidth?: number;
  nodeHeight?: number;
  nodeSep?: number; // Horizontal separation between nodes
  rankSep?: number; // Vertical separation between ranks
}

/**
 * Apply automatic layout to nodes using the Dagre algorithm.
 * Returns new nodes with updated positions while preserving all other data.
 */
export function getLayoutedElements(
  nodes: Node[],
  edges: Edge[],
  options: LayoutOptions = { direction: 'LR' }
): { nodes: Node[]; edges: Edge[] } {
  // Skip layout if no nodes
  if (nodes.length === 0) {
    return { nodes, edges };
  }

  const g = new Dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}));

  g.setGraph({
    rankdir: options.direction,
    nodesep: options.nodeSep ?? 80,
    ranksep: options.rankSep ?? 150,
  });

  // Add all nodes to the graph
  nodes.forEach((node) => {
    // Use different sizes for different node types
    let width = options.nodeWidth ?? 180;
    let height = options.nodeHeight ?? 100;

    if (node.type === 'browserPreview') {
      // Browser preview nodes are larger
      width = 320;
      height = 280;
    }

    g.setNode(node.id, { width, height });
  });

  // Add all edges to the graph
  edges.forEach((edge) => {
    g.setEdge(edge.source, edge.target);
  });

  // Run the layout algorithm
  Dagre.layout(g);

  // Map the calculated positions back to nodes
  const layoutedNodes = nodes.map((node) => {
    const nodeWithPosition = g.node(node.id);

    // Get the dimensions used for this node type
    let width = options.nodeWidth ?? 180;
    let height = options.nodeHeight ?? 100;

    if (node.type === 'browserPreview') {
      width = 320;
      height = 280;
    }

    return {
      ...node,
      position: {
        // Dagre gives center position, convert to top-left for React Flow
        x: nodeWithPosition.x - width / 2,
        y: nodeWithPosition.y - height / 2,
      },
    };
  });

  return { nodes: layoutedNodes, edges };
}
