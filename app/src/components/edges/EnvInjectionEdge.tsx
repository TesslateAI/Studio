import { memo } from 'react';
import {
  BaseEdge,
  EdgeLabelRenderer,
  getBezierPath,
  type EdgeProps,
} from '@xyflow/react';
import { Gear } from '@phosphor-icons/react';

/**
 * EnvInjectionEdge - Represents environment variable injection between containers
 * Visual: Orange dashed line with gear icon
 */
export const EnvInjectionEdge = memo(({
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

  // Get env var count from config if available
  const envCount = data?.config?.env_mapping
    ? Object.keys(data.config.env_mapping).length
    : 0;

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        markerEnd={markerEnd}
        style={{
          ...style,
          stroke: '#f97316', // Orange
          strokeWidth: 2,
          strokeDasharray: '5,5',
        }}
      />
      <EdgeLabelRenderer>
        <div
          style={{
            position: 'absolute',
            transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
            pointerEvents: 'all',
          }}
          className="flex items-center gap-1 px-2 py-1 bg-orange-500/20 border border-orange-500/30 rounded text-[10px] text-orange-400 font-medium"
        >
          <Gear size={12} weight="fill" />
          <span>{envCount > 0 ? `${envCount} env` : 'env'}</span>
        </div>
      </EdgeLabelRenderer>
    </>
  );
});

EnvInjectionEdge.displayName = 'EnvInjectionEdge';
