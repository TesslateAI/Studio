import { memo } from 'react';
import {
  BaseEdge,
  EdgeLabelRenderer,
  getBezierPath,
  type EdgeProps,
} from '@xyflow/react';
import { Database } from '@phosphor-icons/react';

/**
 * DatabaseEdge - Represents database connections between containers
 * Visual: Green solid line with database icon
 */
export const DatabaseEdge = memo(({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  style = {},
  markerEnd,
  data,
}: EdgeProps) => {
  const [edgePath, labelX, labelY] = getBezierPath({
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
        markerEnd={markerEnd}
        style={{
          ...style,
          stroke: '#22c55e', // Green
          strokeWidth: 3,
        }}
      />
      <EdgeLabelRenderer>
        <div
          style={{
            position: 'absolute',
            transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
            pointerEvents: 'all',
          }}
          className="flex items-center gap-1 px-2 py-1 bg-green-500/20 border border-green-500/30 rounded text-[10px] text-green-400 font-medium"
        >
          <Database size={12} weight="fill" />
          <span>DB</span>
        </div>
      </EdgeLabelRenderer>
    </>
  );
});

DatabaseEdge.displayName = 'DatabaseEdge';
