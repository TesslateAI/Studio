import { memo } from 'react';
import {
  BaseEdge,
  EdgeLabelRenderer,
  getBezierPath,
  type EdgeProps,
} from '@xyflow/react';
import { Lightning } from '@phosphor-icons/react';

/**
 * CacheEdge - Represents cache/Redis connections between containers
 * Visual: Red dashed line with lightning icon
 */
export const CacheEdge = memo(({
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
          stroke: '#ef4444', // Red
          strokeWidth: 2,
          strokeDasharray: '8,4',
        }}
      />
      <EdgeLabelRenderer>
        <div
          style={{
            position: 'absolute',
            transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
            pointerEvents: 'all',
          }}
          className="flex items-center gap-1 px-2 py-1 bg-red-500/20 border border-red-500/30 rounded text-[10px] text-red-400 font-medium"
        >
          <Lightning size={12} weight="fill" />
          <span>Cache</span>
        </div>
      </EdgeLabelRenderer>
    </>
  );
});

CacheEdge.displayName = 'CacheEdge';
