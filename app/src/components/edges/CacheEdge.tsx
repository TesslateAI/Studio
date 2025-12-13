import { memo } from 'react';
import { BaseEdge, getSmoothStepPath, type EdgeProps } from '@xyflow/react';

// Static style object - defined once at module scope to prevent re-renders
const EDGE_STYLE = { stroke: '#ef4444', strokeWidth: 2, strokeDasharray: '6,3' };

/**
 * CacheEdge - Lightweight edge for cache/Redis connections
 * Performance optimized: No labels, minimal rendering, static style
 */
const CacheEdgeComponent = ({
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

export const CacheEdge = memo(CacheEdgeComponent);
CacheEdge.displayName = 'CacheEdge';
