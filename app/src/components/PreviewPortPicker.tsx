import { useState, useRef, useEffect } from 'react';
import { CaretDown, Check, Globe } from '@phosphor-icons/react';

export interface PreviewableContainer {
  id: string;
  name: string;
  port: number;
  url: string;
  isPrimary: boolean;
}

interface PreviewPortPickerProps {
  containers: PreviewableContainer[];
  selectedContainerId: string | null;
  onSelect: (container: PreviewableContainer) => void;
}

export function PreviewPortPicker({
  containers,
  selectedContainerId,
  onSelect,
}: PreviewPortPickerProps) {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const selected = containers.find((c) => c.id === selectedContainerId) || containers[0];

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

  // Don't render if fewer than 2 previewable containers
  if (containers.length < 2) {
    return null;
  }

  if (!selected) {
    return null;
  }

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-[var(--text)]/5 hover:bg-[var(--text)]/10 border border-[var(--border-color)] transition-colors text-sm"
        title="Switch preview container"
      >
        <Globe size={14} className="text-emerald-400 flex-shrink-0" />
        <span className="text-[var(--text)]/80 font-mono text-xs truncate max-w-[140px]">
          {selected.name}:{selected.port}
        </span>
        <CaretDown
          size={12}
          className={`text-[var(--text)]/50 transition-transform flex-shrink-0 ${isOpen ? 'rotate-180' : ''}`}
        />
      </button>

      {isOpen && (
        <div className="absolute top-full left-0 mt-1 w-56 bg-[var(--surface)] border border-[var(--border-color)] rounded-xl shadow-xl z-50 overflow-hidden animate-in fade-in slide-in-from-top-2 duration-150">
          <div className="px-3 py-2 border-b border-[var(--border-color)] text-xs text-[var(--text)]/50 uppercase tracking-wide font-medium">
            Preview Target
          </div>
          <div className="max-h-48 overflow-y-auto">
            {containers.map((container) => (
              <button
                key={container.id}
                onClick={() => {
                  onSelect(container);
                  setIsOpen(false);
                }}
                className={`
                  w-full flex items-center gap-3 px-3 py-2.5 hover:bg-[var(--text)]/5 transition-colors text-left
                  ${container.id === selected.id ? 'bg-[var(--text)]/5' : ''}
                `}
              >
                <Globe
                  size={14}
                  className={`flex-shrink-0 ${container.id === selected.id ? 'text-emerald-400' : 'text-[var(--text)]/40'}`}
                />
                <div className="flex-1 min-w-0">
                  <div className="font-mono text-xs text-[var(--text)] truncate">
                    {container.name}:{container.port}
                  </div>
                  {container.isPrimary && (
                    <div className="text-[10px] text-[var(--primary)]/70">primary</div>
                  )}
                </div>
                {container.id === selected.id && (
                  <Check size={14} className="text-[var(--primary)] flex-shrink-0" weight="bold" />
                )}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
