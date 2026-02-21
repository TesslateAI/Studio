import { memo } from 'react';
import { BaseEdge, getSmoothStepPath, type EdgeProps } from '@xyflow/react';
import { EdgeDeleteButton } from './EdgeDeleteButton';

const EDGE_STYLE = { stroke: '#22c55e', strokeWidth: 2 };
const SELECTED_EDGE_STYLE = { stroke: '#22c55e', strokeWidth: 3 };

const DatabaseEdgeComponent = ({
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

export const DatabaseEdge = memo(DatabaseEdgeComponent);
DatabaseEdge.displayName = 'DatabaseEdge';
