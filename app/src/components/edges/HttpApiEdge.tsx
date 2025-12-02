import { memo } from 'react';
import {
  BaseEdge,
  EdgeLabelRenderer,
  getBezierPath,
  type EdgeProps,
} from '@xyflow/react';
import { ArrowsLeftRight } from '@phosphor-icons/react';

/**
 * HttpApiEdge - Represents HTTP/REST API calls between containers
 * Visual: Blue animated line with arrows icon
 */
export const HttpApiEdge = memo(({
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
          stroke: '#3b82f6', // Blue
          strokeWidth: 2,
        }}
      />
      {/* Animated dot traveling along the edge */}
      <circle r="4" fill="#3b82f6">
        <animateMotion dur="2s" repeatCount="indefinite" path={edgePath} />
      </circle>
      <EdgeLabelRenderer>
        <div
          style={{
            position: 'absolute',
            transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
            pointerEvents: 'all',
          }}
          className="flex items-center gap-1 px-2 py-1 bg-blue-500/20 border border-blue-500/30 rounded text-[10px] text-blue-400 font-medium"
        >
          <ArrowsLeftRight size={12} weight="bold" />
          <span>API</span>
        </div>
      </EdgeLabelRenderer>
    </>
  );
});

HttpApiEdge.displayName = 'HttpApiEdge';
