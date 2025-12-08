import { memo } from 'react';
import { BaseEdge, getSmoothStepPath, type EdgeProps } from '@xyflow/react';

// Static style object - defined once at module scope to prevent re-renders
const EDGE_STYLE = { stroke: '#f97316', strokeWidth: 2, strokeDasharray: '4,4' };

/**
 * EnvInjectionEdge - Lightweight edge for environment variable injection
 * Performance optimized: No labels, minimal rendering, static style
 */
const EnvInjectionEdgeComponent = ({
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

export const EnvInjectionEdge = memo(EnvInjectionEdgeComponent);
EnvInjectionEdge.displayName = 'EnvInjectionEdge';
