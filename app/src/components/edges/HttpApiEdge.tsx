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
 * Visual: Blue curved line with API label
 */
const HttpApiEdgeComponent = ({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  markerEnd,
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
        style={{ stroke: '#3b82f6', strokeWidth: 2 }}
      />
      <EdgeLabelRenderer>
        <div
          style={{
            position: 'absolute',
            transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
            pointerEvents: 'none',
          }}
          className="flex items-center gap-1 px-2 py-1 bg-blue-500/20 border border-blue-500/30 rounded text-[10px] text-blue-400 font-medium"
        >
          <ArrowsLeftRight size={12} weight="bold" />
          <span>API</span>
        </div>
      </EdgeLabelRenderer>
    </>
  );
};

export const HttpApiEdge = memo(HttpApiEdgeComponent);
HttpApiEdge.displayName = 'HttpApiEdge';
