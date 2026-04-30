import { useEffect, useRef, useState } from 'react';
import { CaretDown } from '@phosphor-icons/react';

interface VariableGroup {
  label: string;
  variables: Array<{ token: string; help: string }>;
}

interface Props {
  /** A ref to the textarea / input the menu should insert into. */
  targetRef: React.RefObject<HTMLTextAreaElement | HTMLInputElement | null>;
  /** Called after insertion with the new full value so the parent can sync state. */
  onInsert: (newValue: string) => void;
  /** Which variable groups to show. Sensible defaults if omitted. */
  groups?: VariableGroup[];
}

const DEFAULT_GROUPS: VariableGroup[] = [
  {
    label: 'From the trigger event',
    variables: [
      { token: '{{event.payload}}', help: 'The whole event payload as JSON' },
      { token: '{{event.payload.field}}', help: 'A specific field — replace "field"' },
      { token: '{{event.received_at}}', help: 'When the trigger fired (ISO timestamp)' },
      { token: '{{event.id}}', help: 'Unique event id' },
    ],
  },
  {
    label: 'From the previous step',
    variables: [
      { token: '{{run.output}}', help: 'Whatever the previous action produced' },
      { token: '{{run.output.summary}}', help: 'A specific output field' },
      { token: '{{run.id}}', help: 'Unique run id' },
    ],
  },
];

/**
 * Tiny popover menu that inserts variable placeholders at the cursor
 * position of the linked textarea / input. Avoids dependencies — closes
 * on outside click or Escape.
 */
export function VariableMenu({ targetRef, onInsert, groups = DEFAULT_GROUPS }: Props) {
  const [open, setOpen] = useState(false);
  const popoverRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKey);
    };
  }, [open]);

  const insertAtCursor = (token: string) => {
    const el = targetRef.current;
    if (!el) {
      onInsert(
        (el as unknown as { value?: string })?.value
          ? `${(el as unknown as { value?: string }).value}${token}`
          : token
      );
      setOpen(false);
      return;
    }
    const start = el.selectionStart ?? el.value.length;
    const end = el.selectionEnd ?? el.value.length;
    const next = el.value.slice(0, start) + token + el.value.slice(end);
    onInsert(next);
    // Restore caret position immediately after the inserted token.
    requestAnimationFrame(() => {
      el.focus();
      const caret = start + token.length;
      try {
        el.setSelectionRange(caret, caret);
      } catch {
        // Some input types (e.g. number) don't support selection — ignore.
      }
    });
    setOpen(false);
  };

  return (
    <div className="relative inline-block" ref={popoverRef}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="text-[10px] text-[var(--text-subtle)] hover:text-[var(--text)] inline-flex items-center gap-0.5"
      >
        Insert variable <CaretDown className="w-2.5 h-2.5" />
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 z-20 mt-1 w-72 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] shadow-lg p-2 space-y-2"
        >
          {groups.map((group) => (
            <div key={group.label}>
              <div className="text-[10px] uppercase tracking-wider text-[var(--text-subtle)] mb-1">
                {group.label}
              </div>
              <ul className="space-y-0.5">
                {group.variables.map((v) => (
                  <li key={v.token}>
                    <button
                      type="button"
                      onClick={() => insertAtCursor(v.token)}
                      className="w-full text-left px-2 py-1 rounded-[var(--radius-small)] hover:bg-[var(--surface-hover)]"
                    >
                      <code className="text-[11px] font-mono text-[var(--text)]">{v.token}</code>
                      <div className="text-[10px] text-[var(--text-subtle)]">{v.help}</div>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
