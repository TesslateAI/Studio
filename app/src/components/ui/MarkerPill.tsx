import { X } from 'lucide-react';
import { Tooltip } from './Tooltip';

interface MarkerPillProps {
  marker: string;
  label: string;
  category: 'system' | 'project' | 'tool';
  description?: string;
  onRemove?: () => void;
  onClick?: () => void;
  removable?: boolean;
  inline?: boolean;
}

const categoryColors = {
  system: {
    bg: 'bg-blue-500/10',
    border: 'border-blue-500/30',
    text: 'text-blue-500',
    hoverBg: 'hover:bg-blue-500/20',
  },
  project: {
    bg: 'bg-green-500/10',
    border: 'border-green-500/30',
    text: 'text-green-500',
    hoverBg: 'hover:bg-green-500/20',
  },
  tool: {
    bg: 'bg-purple-500/10',
    border: 'border-purple-500/30',
    text: 'text-purple-500',
    hoverBg: 'hover:bg-purple-500/20',
  },
};

export function MarkerPill({
  marker,
  label,
  category,
  description,
  onRemove,
  onClick,
  removable = false,
  inline = false
}: MarkerPillProps) {
  const colors = categoryColors[category];

  const pillContent = (
    <span
      className={`
        inline-flex items-center gap-1 px-2 py-0.5 rounded-full border
        text-xs font-medium transition-all select-none
        ${colors.bg} ${colors.border} ${colors.text}
        ${onClick ? `cursor-pointer ${colors.hoverBg}` : ''}
        ${inline ? 'mx-0.5 align-baseline' : ''}
      `}
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick(); } } : undefined}
    >
      <span className="font-mono text-[10px]">{`{${marker}}`}</span>
      {!inline && (
        <>
          <span className="opacity-70">·</span>
          <span>{label}</span>
        </>
      )}
      {removable && onRemove && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          className={`ml-0.5 ${colors.text} hover:opacity-70 transition-opacity`}
          aria-label={`Remove ${marker} marker`}
        >
          <X className="w-3 h-3" />
        </button>
      )}
    </span>
  );

  // If we have a description, wrap in tooltip
  if (description) {
    return (
      <Tooltip content={`${label}: ${description}`} side="top" delay={200}>
        {pillContent}
      </Tooltip>
    );
  }

  return pillContent;
}
