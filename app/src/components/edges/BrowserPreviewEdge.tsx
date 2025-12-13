import { memo } from 'react';
import { BaseEdge, getSmoothStepPath, type EdgeProps } from '@xyflow/react';

// Static style object - defined once at module scope to prevent re-renders
const EDGE_STYLE = { stroke: '#8b5cf6', strokeWidth: 2, strokeDasharray: '8,4' };

/**
 * BrowserPreviewEdge - Edge connecting containers to browser preview nodes
 * Performance optimized: No labels, minimal rendering, static style
 */
const BrowserPreviewEdgeComponent = ({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
}: EdgeProps) => {
  const [edgePath] = getSmoothStepPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });

  return (
    <BaseEdge
      id={id}
      path={edgePath}
      style={EDGE_STYLE}
    />
  );
};

export const BrowserPreviewEdge = memo(BrowserPreviewEdgeComponent);
BrowserPreviewEdge.displayName = 'BrowserPreviewEdge';
