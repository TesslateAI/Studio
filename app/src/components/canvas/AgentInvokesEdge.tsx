/**
 * AgentInvokesEdge — XYFlow custom edge representing an agent -> target
 * invocation link. Visually distinct from http_api (solid) edges: dashed
 * purple line with an "invokes" label.
 */
import { memo } from 'react';
import { BaseEdge, EdgeLabelRenderer, getSmoothStepPath, type EdgeProps } from '@xyflow/react';

const STYLE = {
  stroke: '#a855f7',
  strokeWidth: 2,
  strokeDasharray: '6 4',
};
const SELECTED = { ...STYLE, strokeWidth: 3 };

function AgentInvokesEdgeComponent({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  selected,
}: EdgeProps) {
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
      <BaseEdge id={id} path={edgePath} style={selected ? SELECTED : STYLE} />
      <EdgeLabelRenderer>
        <div
          data-testid="agent-invokes-label"
          style={{
            position: 'absolute',
            transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
            pointerEvents: 'none',
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            padding: '1px 6px',
            borderRadius: 4,
            fontSize: 10,
            color: 'var(--text-muted)',
          }}
        >
          invokes
        </div>
      </EdgeLabelRenderer>
    </>
  );
}

export const AgentInvokesEdge = memo(AgentInvokesEdgeComponent);
AgentInvokesEdge.displayName = 'AgentInvokesEdge';
