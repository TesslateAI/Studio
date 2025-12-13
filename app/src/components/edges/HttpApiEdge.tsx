import { memo } from 'react';
import { BaseEdge, getSmoothStepPath, type EdgeProps } from '@xyflow/react';

// Static style object - defined once at module scope to prevent re-renders
const EDGE_STYLE = { stroke: '#3b82f6', strokeWidth: 2 };

/**
 * HttpApiEdge - Lightweight edge for HTTP/REST API calls
 * Performance optimized: No labels, minimal rendering, static style
 */
const HttpApiEdgeComponent = ({
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

export const HttpApiEdge = memo(HttpApiEdgeComponent);
HttpApiEdge.displayName = 'HttpApiEdge';
