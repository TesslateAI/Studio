import { useEffect, useRef, useState } from 'react';
import { Plus, ImageSquare, Plug, GithubLogo, SlackLogo, FigmaLogo } from '@phosphor-icons/react';

interface PlusMenuProps {
  /** Called with the picked image File(s). One picker invocation may pick many. */
  onAddImages: (files: File[]) => void;
  /** Disabled state — e.g., when the input is locked for viewers. */
  disabled?: boolean;
}

interface ConnectorEntry {
  key: string;
  label: string;
  icon: typeof GithubLogo;
  description: string;
  enabled: boolean;
}

// Placeholder connector list — each entry will eventually wire into a real
// integration. Disabled entries render with a "Coming soon" affordance so
// users can see what's planned without us pretending it works.
const CONNECTORS: ConnectorEntry[] = [
  {
    key: 'github',
    label: 'GitHub',
    icon: GithubLogo,
    description: 'Import a repo or sync changes.',
    enabled: false,
  },
  {
    key: 'figma',
    label: 'Figma',
    icon: FigmaLogo,
    description: 'Pull designs into the chat.',
    enabled: false,
  },
  {
    key: 'slack',
    label: 'Slack',
    icon: SlackLogo,
    description: 'Forward agent results to a channel.',
    enabled: false,
  },
];

export function PlusMenu({ onAddImages, disabled = false }: PlusMenuProps) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    const handle = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', handle);
    document.addEventListener('keydown', onEsc);
    return () => {
      document.removeEventListener('mousedown', handle);
      document.removeEventListener('keydown', onEsc);
    };
  }, [open]);

  const handlePick = () => {
    fileInputRef.current?.click();
  };

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={disabled}
        className={`btn btn-icon btn-sm ${open ? 'btn-active' : ''}`}
        title="Add"
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <Plus size={14} weight="bold" />
      </button>

      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        multiple
        className="hidden"
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          if (files.length > 0) onAddImages(files);
          // Reset so picking the same file twice still fires onChange.
          e.target.value = '';
          setOpen(false);
        }}
      />

      {open && (
        <div
          role="menu"
          className="absolute bottom-full left-0 mb-1.5 w-64 bg-[var(--surface)] border border-[var(--border-hover)] rounded-[var(--radius-medium)] p-1.5 z-50 shadow-lg"
        >
          {/* Section 1 — Add */}
          <button
            type="button"
            onClick={handlePick}
            title="Attach images from your computer."
            className="w-full flex items-center gap-2.5 px-2.5 py-2 rounded-[var(--radius-small)] hover:bg-[var(--surface-hover)] transition-colors text-left"
            role="menuitem"
          >
            <ImageSquare size={14} className="text-[var(--text-muted)] flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="text-xs font-medium text-[var(--text)]">Add photos &amp; files</div>
              <div className="text-[10px] text-[var(--text-subtle)] mt-0.5">
                Attach images to the next message.
              </div>
            </div>
          </button>

          {/* Section 2 — Connectors */}
          <div className="border-t border-[var(--border)] mt-1 pt-1">
            <div className="flex items-center gap-1.5 px-2.5 pt-1 pb-1.5 text-[10px] font-medium uppercase tracking-wider text-[var(--text-subtle)]">
              <Plug size={10} weight="bold" />
              <span>Connectors</span>
            </div>
            {CONNECTORS.map((c) => {
              const Icon = c.icon;
              return (
                <button
                  key={c.key}
                  type="button"
                  disabled={!c.enabled}
                  title={c.enabled ? c.description : `${c.description} (Coming soon)`}
                  className={`w-full flex items-center gap-2.5 px-2.5 py-2 rounded-[var(--radius-small)] text-left transition-colors ${
                    c.enabled
                      ? 'hover:bg-[var(--surface-hover)]'
                      : 'opacity-50 cursor-not-allowed'
                  }`}
                  role="menuitem"
                >
                  <Icon size={14} className="text-[var(--text-muted)] flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="text-xs font-medium text-[var(--text)] truncate">
                      {c.label}
                    </div>
                  </div>
                  {!c.enabled && (
                    <span className="text-[9px] uppercase tracking-wider text-[var(--text-subtle)]">
                      Soon
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
