import { memo } from 'react';
import { BaseEdge, getSmoothStepPath, type EdgeProps } from '@xyflow/react';

// Static style object - defined once at module scope to prevent re-renders
const EDGE_STYLE = { stroke: '#22c55e', strokeWidth: 2 };

/**
 * DatabaseEdge - Lightweight edge for database connections
 * Performance optimized: No labels, minimal rendering, static style
 */
const DatabaseEdgeComponent = ({
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

export const DatabaseEdge = memo(DatabaseEdgeComponent);
DatabaseEdge.displayName = 'DatabaseEdge';
