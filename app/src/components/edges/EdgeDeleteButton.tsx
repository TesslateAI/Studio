import { memo } from 'react';
import { EdgeLabelRenderer, useReactFlow } from '@xyflow/react';

interface EdgeDeleteButtonProps {
  id: string;
  labelX: number;
  labelY: number;
  selected?: boolean;
}

const EdgeDeleteButtonComponent = ({ id, labelX, labelY, selected }: EdgeDeleteButtonProps) => {
  const { deleteElements } = useReactFlow();

  if (!selected) return null;

  return (
    <EdgeLabelRenderer>
      <button
        className="nodrag nopan absolute flex items-center justify-center w-5 h-5 rounded-full bg-red-500/90 hover:bg-red-600 text-white text-xs leading-none cursor-pointer shadow-md border border-red-400/50 transition-colors"
        style={{
          transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
          pointerEvents: 'all',
        }}
        onClick={(e) => {
          e.stopPropagation();
          deleteElements({ edges: [{ id }] });
        }}
        title="Delete connection"
      >
        &times;
      </button>
    </EdgeLabelRenderer>
  );
};

export const EdgeDeleteButton = memo(EdgeDeleteButtonComponent);
EdgeDeleteButton.displayName = 'EdgeDeleteButton';
