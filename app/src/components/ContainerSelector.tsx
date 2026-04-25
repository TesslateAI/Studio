import { useState, useRef, useEffect } from 'react';
import { CaretDown, Check, Cube, FolderSimple, Plus } from '@phosphor-icons/react';
import { STATUS_MAP, type EnvironmentStatus } from './ui/environmentStatus';

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
  /** Top-level environment status — drives the dot on the trigger and the
   * status row inside the dropdown header. */
  environmentStatus?: EnvironmentStatus | null;
}

const containerStatusVar = (status: string): string => {
  switch (status) {
    case 'running':
      return 'var(--status-success)';
    case 'starting':
      return 'var(--status-warning)';
    case 'failed':
      return 'var(--status-error)';
    default:
      return 'var(--text-subtle)';
  }
};

const envStatusVar = (status: EnvironmentStatus | null | undefined): string => {
  if (!status) return 'var(--text-subtle)';
  switch (status) {
    case 'running':
      return 'var(--status-success)';
    case 'files_ready':
      return 'var(--text-muted)';
    case 'agent_active':
    case 'starting':
    case 'provisioning':
      return 'var(--status-warning)';
    case 'stopping':
      return 'var(--status-warning)';
    default:
      return 'var(--text-subtle)';
  }
};

export function ContainerSelector({
  containers,
  currentContainerId,
  onChange,
  onOpenArchitecture,
  environmentStatus,
}: ContainerSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const isProjectRoot = currentContainerId === PROJECT_ROOT_ID;
  const currentContainer = isProjectRoot
    ? null
    : containers.find((c) => c.id === currentContainerId) || containers[0];

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  if (!isProjectRoot && !currentContainer) {
    return null;
  }

  const hasDropdown = containers.length > 0;
  const triggerDotColor = envStatusVar(environmentStatus ?? null);
  const envCfg = environmentStatus ? STATUS_MAP[environmentStatus] : null;

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => hasDropdown && setIsOpen(!isOpen)}
        className={`flex items-center gap-2 px-2.5 h-7 rounded-[var(--radius-small)] text-xs transition-colors ${
          hasDropdown
            ? 'hover:bg-[var(--surface-hover)] cursor-pointer'
            : 'cursor-default'
        }`}
      >
        {isProjectRoot ? (
          <>
            <FolderSimple size={14} className="text-[var(--text-muted)]" />
            <span className="font-medium text-[var(--text)]">Project Root</span>
          </>
        ) : currentContainer ? (
          <>
            <Cube size={14} className="text-[var(--text-muted)]" />
            <span className="font-medium text-[var(--text)] truncate max-w-[160px]">
              {currentContainer.name}
            </span>
            <span
              className="w-2 h-2 rounded-full flex-shrink-0"
              style={{ backgroundColor: triggerDotColor }}
              aria-hidden
            />
          </>
        ) : null}

        {hasDropdown && (
          <CaretDown
            size={12}
            className={`text-[var(--text-subtle)] transition-transform ${isOpen ? 'rotate-180' : ''}`}
          />
        )}
      </button>

      {isOpen && hasDropdown && (
        <div className="absolute top-full left-0 mt-1 w-64 bg-[var(--surface)] border border-[var(--border-hover)] rounded-[var(--radius-medium)] z-50 overflow-hidden p-1.5">
          {envCfg && (
            <div className="flex items-center gap-2 px-2.5 py-2 border-b border-[var(--border)] mb-1">
              <span
                className="w-2 h-2 rounded-full flex-shrink-0"
                style={{ backgroundColor: triggerDotColor }}
                aria-hidden
              />
              <span className="text-[11px] font-medium text-[var(--text)]">{envCfg.label}</span>
              <span className="ml-auto text-[10px] text-[var(--text-subtle)] truncate">
                {envCfg.tooltip}
              </span>
            </div>
          )}

          <button
            onClick={() => {
              onChange(PROJECT_ROOT_ID);
              setIsOpen(false);
            }}
            className={`w-full flex items-center gap-3 px-2.5 py-2 rounded-[var(--radius-small)] hover:bg-[var(--surface-hover)] transition-colors text-left ${
              isProjectRoot ? 'bg-[var(--surface-hover)]' : ''
            }`}
          >
            <FolderSimple size={14} className="text-[var(--text-muted)] flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="text-xs font-medium text-[var(--text)] truncate">Project Root</div>
              <div className="text-[10px] text-[var(--text-subtle)] truncate">All files</div>
            </div>
            {isProjectRoot && (
              <Check size={14} className="text-[var(--text-muted)] flex-shrink-0" weight="bold" />
            )}
          </button>

          <div className="px-2.5 pt-2 pb-1 text-[10px] text-[var(--text-subtle)] uppercase tracking-wide font-medium">
            Containers
          </div>

          <div className="max-h-64 overflow-y-auto">
            {containers.map((container) => (
              <button
                key={container.id}
                onClick={() => {
                  onChange(container.id);
                  setIsOpen(false);
                }}
                className={`w-full flex items-center gap-3 px-2.5 py-2 rounded-[var(--radius-small)] hover:bg-[var(--surface-hover)] transition-colors text-left ${
                  container.id === currentContainerId ? 'bg-[var(--surface-hover)]' : ''
                }`}
              >
                <Cube size={14} className="text-[var(--text-muted)] flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-medium text-[var(--text)] truncate">
                    {container.name}
                  </div>
                  <div className="text-[10px] text-[var(--text-subtle)] truncate">
                    {container.base?.name || 'Custom'}
                  </div>
                </div>
                <span
                  className="w-2 h-2 rounded-full flex-shrink-0"
                  style={{ backgroundColor: containerStatusVar(container.status) }}
                  aria-hidden
                />
                {container.id === currentContainerId && (
                  <Check size={14} className="text-[var(--text-muted)] flex-shrink-0" weight="bold" />
                )}
              </button>
            ))}
          </div>

          {onOpenArchitecture && (
            <button
              onClick={() => {
                onOpenArchitecture();
                setIsOpen(false);
              }}
              className="mt-1 w-full flex items-center gap-3 px-2.5 py-2 border-t border-[var(--border)] rounded-[var(--radius-small)] text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-hover)] transition-colors"
            >
              <Plus size={14} className="flex-shrink-0" />
              <span className="text-xs">Add container…</span>
            </button>
          )}
        </div>
      )}
    </div>
  );
}
