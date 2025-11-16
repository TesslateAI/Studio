import { X } from 'lucide-react';

interface MarkerPillProps {
  marker: string;
  label: string;
  category: 'system' | 'project' | 'tool';
  onRemove?: () => void;
  onClick?: () => void;
  removable?: boolean;
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
  onRemove,
  onClick,
  removable = false
}: MarkerPillProps) {
  const colors = categoryColors[category];

  return (
    <div
      className={`
        inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border
        text-xs font-medium transition-all
        ${colors.bg} ${colors.border} ${colors.text}
        ${onClick ? `cursor-pointer ${colors.hoverBg}` : ''}
      `}
      onClick={onClick}
      title={`Click to insert {${marker}}`}
    >
      <span className="font-mono">{`{${marker}}`}</span>
      <span className="opacity-70">·</span>
      <span>{label}</span>
      {removable && onRemove && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          className={`ml-1 ${colors.text} hover:opacity-70 transition-opacity`}
        >
          <X className="w-3 h-3" />
        </button>
      )}
    </div>
  );
}
