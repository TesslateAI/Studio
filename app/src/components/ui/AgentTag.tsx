import { type ReactNode } from 'react';

interface AgentTagProps {
  icon: ReactNode;
  name: string;
  onClick?: () => void;
  removable?: boolean;
  onRemove?: () => void;
}

export function AgentTag({ icon, name, onClick, removable = false, onRemove }: AgentTagProps) {
  return (
    <div
      className={`
        agent-tag inline-flex items-center gap-1.5
        px-3 py-1 rounded-2xl
        text-xs font-medium
        bg-white/5 border border-white/10
        text-gray-400
        transition-all duration-200
        ${onClick && 'cursor-pointer hover:bg-white/8 hover:text-white hover:border-white/20'}
      `}
      onClick={onClick}
    >
      <span className="text-[10px]">{icon}</span>
      <span>{name}</span>
      {removable && onRemove && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          className="ml-0.5 hover:text-red-400 transition-colors"
        >
          <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 256 256">
            <path d="M205.66,194.34a8,8,0,0,1-11.32,11.32L128,139.31,61.66,205.66a8,8,0,0,1-11.32-11.32L116.69,128,50.34,61.66A8,8,0,0,1,61.66,50.34L128,116.69l66.34-66.35a8,8,0,0,1,11.32,11.32L139.31,128Z" />
          </svg>
        </button>
      )}
    </div>
  );
}
