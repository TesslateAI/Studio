import { useState, useRef, useEffect } from 'react';
import { CaretDown, Check, FolderSimple, Plus } from '@phosphor-icons/react';

export const PROJECT_ROOT_ID = 'root';

interface Container {
  id: string;
  name: string;
  status: string;
  base?: {
    slug: string;
    name: string;
  };
}

interface ContainerSelectorProps {
  containers: Container[];
  currentContainerId?: string | null;
  onChange: (containerId: string) => void;
  onOpenArchitecture?: () => void;
}

// Map base slugs to icons
const getContainerIcon = (slug?: string) => {
  const icons: Record<string, string> = {
    nextjs: '▲',
    vite: '⚡',
    react: '⚛',
    fastapi: '🚀',
    express: 'E',
    django: '🐍',
    flask: '🧪',
    postgres: '🐘',
    mongodb: '🍃',
    redis: '◉',
  };
  return icons[slug?.toLowerCase() || ''] || '📦';
};

// Status dot color
const getStatusColor = (status: string) => {
  switch (status) {
    case 'running':
      return 'bg-emerald-500';
    case 'starting':
      return 'bg-yellow-500 animate-pulse';
    case 'failed':
      return 'bg-red-500';
    default:
      return 'bg-gray-500';
  }
};

export function ContainerSelector({
  containers,
  currentContainerId,
  onChange,
  onOpenArchitecture,
}: ContainerSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Find current container
  const isProjectRoot = currentContainerId === PROJECT_ROOT_ID;
  const currentContainer = isProjectRoot
    ? null
    : containers.find((c) => c.id === currentContainerId) || containers[0];

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Don't render if no containers at all
  if (!isProjectRoot && !currentContainer) {
    return null;
  }

  const hasDropdown = containers.length > 0;

  return (
    <div className="relative" ref={dropdownRef}>
      {/* Current selection button */}
      <button
        onClick={() => hasDropdown && setIsOpen(!isOpen)}
        className={`
          flex items-center gap-2 px-3 py-2 rounded-lg transition-colors
          ${hasDropdown ? 'hover:bg-white/5 cursor-pointer' : 'cursor-default'}
        `}
      >
        {isProjectRoot ? (
          <>
            <FolderSimple size={18} className="text-[var(--text)]/70" />
            <span className="font-medium text-[var(--text)]">Project Root</span>
          </>
        ) : currentContainer ? (
          <>
            <span className="text-lg">{getContainerIcon(currentContainer.base?.slug)}</span>
            <span className="font-medium text-[var(--text)]">{currentContainer.name}</span>
            <span className={`w-2 h-2 rounded-full ${getStatusColor(currentContainer.status)}`} />
          </>
        ) : null}

        {hasDropdown && (
          <CaretDown
            size={14}
            className={`text-[var(--text)]/50 transition-transform ${isOpen ? 'rotate-180' : ''}`}
          />
        )}
      </button>

      {/* Dropdown panel */}
      {isOpen && hasDropdown && (
        <div className="absolute top-full left-0 mt-1 w-64 bg-[#1a1a1a] border border-white/10 rounded-xl shadow-xl z-50 overflow-hidden animate-in fade-in slide-in-from-top-2 duration-150">
          {/* Project Root option */}
          <button
            onClick={() => {
              onChange(PROJECT_ROOT_ID);
              setIsOpen(false);
            }}
            className={`
              w-full flex items-center gap-3 px-3 py-2.5 hover:bg-white/5 transition-colors text-left
              ${isProjectRoot ? 'bg-white/5' : ''}
            `}
          >
            <FolderSimple size={18} className="w-6 text-center text-white/70" />
            <div className="flex-1 min-w-0">
              <div className="font-medium text-white truncate">Project Root</div>
              <div className="text-xs text-white/50 truncate">All files</div>
            </div>
            {isProjectRoot && (
              <Check size={16} className="text-[var(--primary)] flex-shrink-0" weight="bold" />
            )}
          </button>

          {/* Containers header */}
          <div className="px-3 py-2 border-t border-white/10 text-xs text-white/50 uppercase tracking-wide font-medium">
            Containers
          </div>

          {/* Container list */}
          <div className="max-h-64 overflow-y-auto">
            {containers.map((container) => (
              <button
                key={container.id}
                onClick={() => {
                  onChange(container.id);
                  setIsOpen(false);
                }}
                className={`
                  w-full flex items-center gap-3 px-3 py-2.5 hover:bg-white/5 transition-colors text-left
                  ${container.id === currentContainerId ? 'bg-white/5' : ''}
                `}
              >
                {/* Icon */}
                <span className="text-lg w-6 text-center">
                  {getContainerIcon(container.base?.slug)}
                </span>

                {/* Name and type */}
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-white truncate">{container.name}</div>
                  <div className="text-xs text-white/50 truncate">
                    {container.base?.name || 'Custom'}
                  </div>
                </div>

                {/* Status dot */}
                <span
                  className={`w-2 h-2 rounded-full flex-shrink-0 ${getStatusColor(container.status)}`}
                />

                {/* Selected checkmark */}
                {container.id === currentContainerId && (
                  <Check size={16} className="text-[var(--primary)] flex-shrink-0" weight="bold" />
                )}
              </button>
            ))}
          </div>

          {/* Add container link */}
          {onOpenArchitecture && (
            <button
              onClick={() => {
                onOpenArchitecture();
                setIsOpen(false);
              }}
              className="w-full flex items-center gap-3 px-3 py-2.5 border-t border-white/10 text-white/50 hover:text-white hover:bg-white/5 transition-colors"
            >
              <Plus size={18} className="w-6 text-center" />
              <span className="text-sm">Add container...</span>
            </button>
          )}
        </div>
      )}
    </div>
  );
}
