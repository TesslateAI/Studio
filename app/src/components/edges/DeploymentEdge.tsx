import { memo } from 'react';
import { BaseEdge, getSmoothStepPath, type EdgeProps } from '@xyflow/react';

// Static style object - defined once at module scope to prevent re-renders
// Orange dashed line for deployment connections
const EDGE_STYLE = {
  stroke: '#F38020',
  strokeWidth: 2,
  strokeDasharray: '6,4',
};

/**
 * DeploymentEdge - Edge connecting containers to deployment targets
 * Performance optimized: No labels, minimal rendering, static style
 * Uses orange color to match deployment provider branding
 */
const DeploymentEdgeComponent = ({
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
      markerEnd="url(#deployment-arrow)"
    />
  );
};

export const DeploymentEdge = memo(DeploymentEdgeComponent);
DeploymentEdge.displayName = 'DeploymentEdge';
