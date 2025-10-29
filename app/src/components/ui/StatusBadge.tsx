import { useState, useRef, useEffect } from 'react';

export type Status = 'idea' | 'build' | 'launch';

interface StatusBadgeProps {
  status: Status;
  onChange?: (status: Status) => void;
  readonly?: boolean;
}

const statusConfig = {
  idea: {
    label: 'Idea',
    icon: (
      <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 256 256">
        <path d="M176,232a8,8,0,0,1-8,8H88a8,8,0,0,1,0-16h80A8,8,0,0,1,176,232Zm40-128a87.55,87.55,0,0,1-33.64,69.21A16.24,16.24,0,0,0,176,186v6a16,16,0,0,1-16,16H96a16,16,0,0,1-16-16v-6a16,16,0,0,0-6.23-12.66A87.59,87.59,0,0,1,40,104.49C39.74,56.83,78.26,17.14,125.88,16A88,88,0,0,1,216,104Z" />
      </svg>
    ),
    className: 'bg-[rgba(139,92,246,0.2)] text-purple-400 border-[rgba(139,92,246,0.3)]'
  },
  build: {
    label: 'Build',
    icon: (
      <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 256 256">
        <path d="M192,104a8,8,0,0,1-8,8H72a8,8,0,0,1,0-16H184A8,8,0,0,1,192,104Zm-8,24H72a8,8,0,0,0,0,16H184a8,8,0,0,0,0-16Zm40-80V208a16,16,0,0,1-16,16H48a16,16,0,0,1-16-16V48A16,16,0,0,1,48,32H208A16,16,0,0,1,224,48ZM208,208V48H48V208H208Z" />
      </svg>
    ),
    className: 'bg-[rgba(255,107,0,0.2)] text-[var(--primary)] border-[rgba(255,107,0,0.3)]'
  },
  launch: {
    label: 'Launch',
    icon: (
      <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 256 256">
        <path d="M152,224a8,8,0,0,1-8,8H112a8,8,0,0,1,0-16h32A8,8,0,0,1,152,224ZM128,112a12,12,0,1,0-12-12A12,12,0,0,0,128,112Zm95.62,43.83-12.36,55.63a16,16,0,0,1-25.51,9.11L158.51,200h-61L70.25,220.57a16,16,0,0,1-25.51-9.11L32.38,155.83a15.95,15.95,0,0,1,1.93-12.78L64,96.28V48a16,16,0,0,1,16-16h96a16,16,0,0,1,16,16V96.28l29.69,46.77A15.95,15.95,0,0,1,223.62,155.83Z" />
      </svg>
    ),
    className: 'bg-[rgba(34,197,94,0.2)] text-green-400 border-[rgba(34,197,94,0.3)]'
  }
};

export function StatusBadge({ status, onChange, readonly = false }: StatusBadgeProps) {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const config = statusConfig[status];

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleStatusChange = (newStatus: Status) => {
    if (onChange) {
      onChange(newStatus);
    }
    setIsOpen(false);
  };

  return (
    <div className="relative inline-block" ref={dropdownRef}>
      <button
        onClick={(e) => {
          e.stopPropagation();
          if (!readonly) setIsOpen(!isOpen);
        }}
        className={`
          status-badge inline-flex items-center gap-1.5
          px-4 py-1.5 rounded-full
          text-xs font-semibold uppercase tracking-wider
          border transition-all
          ${config.className}
          ${!readonly && 'hover:opacity-80 cursor-pointer'}
        `}
        disabled={readonly}
      >
        {config.icon}
        <span>{config.label}</span>
        {!readonly && (
          <svg className="w-3 h-3 ml-0.5" fill="currentColor" viewBox="0 0 256 256">
            <path d="M213.66,101.66l-80,80a8,8,0,0,1-11.32,0l-80-80A8,8,0,0,1,53.66,90.34L128,164.69l74.34-74.35a8,8,0,0,1,11.32,11.32Z" />
          </svg>
        )}
      </button>

      {isOpen && !readonly && (
        <div className="dropdown-menu absolute top-full right-0 mt-2 bg-[rgba(20,20,20,0.98)] backdrop-blur-xl border border-white/10 rounded-xl min-w-[160px] z-50 shadow-lg overflow-hidden">
          {(Object.keys(statusConfig) as Status[]).map((statusKey) => (
            <button
              key={statusKey}
              onClick={(e) => {
                e.stopPropagation();
                handleStatusChange(statusKey);
              }}
              className={`
                dropdown-item w-full px-4 py-2.5 flex items-center gap-3
                text-sm text-white transition-colors
                hover:bg-white/8
                ${statusKey === status && 'bg-[rgba(255,107,0,0.2)] text-[var(--primary)]'}
              `}
            >
              {statusConfig[statusKey].icon}
              <span>{statusConfig[statusKey].label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
