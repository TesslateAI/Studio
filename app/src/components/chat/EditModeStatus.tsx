import { useEffect, useRef, useState } from 'react';
import { Check, AlertTriangle, Eye } from 'lucide-react';

export type EditMode = 'allow' | 'ask' | 'plan';

interface EditModeStatusProps {
  mode: EditMode;
  onModeChange: (mode: EditMode) => void;
  className?: string;
  /** When true, only show icon (no text label) on the trigger button. */
  compact?: boolean;
}

interface ModeConfig {
  label: string;
  icon: typeof AlertTriangle;
  description: string;
}

const MODE_CONFIG: Record<EditMode, ModeConfig> = {
  ask: {
    label: 'Ask before edit',
    icon: AlertTriangle,
    description: 'Agent pauses for approval before editing files.',
  },
  allow: {
    label: 'Allow all edits',
    icon: Check,
    description: 'Agent edits files freely without confirmation.',
  },
  plan: {
    label: 'Plan mode',
    icon: Eye,
    description: 'Agent proposes a plan without making any edits.',
  },
};

const MODE_ORDER: EditMode[] = ['ask', 'allow', 'plan'];

export function EditModeStatus({
  mode,
  onModeChange,
  className = '',
  compact = false,
}: EditModeStatusProps) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const config = MODE_CONFIG[mode];
  const Icon = config.icon;

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

  return (
    <div ref={containerRef} className={`relative ${className}`}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={`btn btn-sm flex items-center gap-1.5 ${open ? 'btn-active' : ''}`}
        title={compact ? config.label : 'Change edit mode'}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <Icon size={13} className="text-[var(--text-muted)]" />
        {!compact && (
          <span className="text-[var(--text)] text-xs font-medium">{config.label}</span>
        )}
      </button>

      {open && (
        <div
          role="menu"
          className="absolute bottom-full left-0 mb-1.5 w-56 bg-[var(--surface)] border border-[var(--border-hover)] rounded-[var(--radius-medium)] p-1 z-50 shadow-lg"
        >
          {MODE_ORDER.map((m) => {
            const cfg = MODE_CONFIG[m];
            const ModeIcon = cfg.icon;
            const isSelected = m === mode;
            return (
              <button
                key={m}
                type="button"
                onClick={() => {
                  onModeChange(m);
                  setOpen(false);
                }}
                title={cfg.description}
                className={`w-full grid grid-cols-[16px_1fr_16px] items-center gap-2 px-2.5 py-2 rounded-[var(--radius-small)] transition-colors text-left ${
                  isSelected
                    ? 'bg-[var(--surface-hover)]'
                    : 'hover:bg-[var(--surface-hover)]'
                }`}
                role="menuitemradio"
                aria-checked={isSelected}
              >
                <ModeIcon size={13} className="text-[var(--text-muted)] justify-self-center" />
                <span className="text-xs font-medium text-[var(--text)] truncate">
                  {cfg.label}
                </span>
                <Check
                  size={13}
                  className={`justify-self-center ${
                    isSelected ? 'text-[var(--primary)]' : 'text-transparent'
                  }`}
                />
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
