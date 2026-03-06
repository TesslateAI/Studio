import { memo } from 'react';
import { BaseEdge, getSmoothStepPath, type EdgeProps } from '@xyflow/react';
import { EdgeDeleteButton } from './EdgeDeleteButton';

const EDGE_STYLE = { stroke: '#ef4444', strokeWidth: 2, strokeDasharray: '6,3' };
const SELECTED_EDGE_STYLE = { stroke: '#ef4444', strokeWidth: 3, strokeDasharray: '6,3' };

const CacheEdgeComponent = ({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  selected,
}: EdgeProps) => {
  const [edgePath, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        style={selected ? SELECTED_EDGE_STYLE : EDGE_STYLE}
        interactionWidth={20}
      />
      <EdgeDeleteButton id={id} labelX={labelX} labelY={labelY} selected={selected} />
    </>
  );
};

export const CacheEdge = memo(CacheEdgeComponent);
CacheEdge.displayName = 'CacheEdge';
