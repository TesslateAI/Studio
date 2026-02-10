import { memo } from 'react';
import { BaseEdge, getSmoothStepPath, type EdgeProps } from '@xyflow/react';
import { EdgeDeleteButton } from './EdgeDeleteButton';

const EDGE_STYLE = { stroke: '#3b82f6', strokeWidth: 2 };
const SELECTED_EDGE_STYLE = { stroke: '#3b82f6', strokeWidth: 3 };

const HttpApiEdgeComponent = ({
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

export const HttpApiEdge = memo(HttpApiEdgeComponent);
HttpApiEdge.displayName = 'HttpApiEdge';
