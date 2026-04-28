import { useState, useMemo, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { MagnifyingGlass, X } from '@phosphor-icons/react';
import { shortcutGroups, modKey, type ShortcutGroup } from '../lib/keyboard-registry';

interface KeyboardShortcutsModalProps {
  open: boolean;
  onClose: () => void;
}

// Treatment-aligned shortcuts panel.
// All colors flow through CSS custom properties set by the active theme
// preset (themePresets.ts), so the panel adapts to every light/dark theme
// without per-mode branching. The previous implementation hardcoded
// white/* and black/* opacity colors and gated them on `theme === 'dark'`,
// which broke for any non-default preset.
export function KeyboardShortcutsModal({ open, onClose }: KeyboardShortcutsModalProps) {
  const [search, setSearch] = useState('');
  const searchInputRef = useRef<HTMLInputElement>(null);
  const modalRef = useRef<HTMLDivElement>(null);

  const filteredGroups = useMemo<ShortcutGroup[]>(() => {
    // Hide paletteOnly entries — they have no keybinding and live in the
    // command palette only.
    const visibleGroups = shortcutGroups
      .map((group) => ({
        ...group,
        shortcuts: group.shortcuts.filter((s) => !s.paletteOnly),
      }))
      .filter((group) => group.shortcuts.length > 0);

    if (!search) return visibleGroups;

    const searchLower = search.toLowerCase();
    return visibleGroups
      .map((group) => ({
        ...group,
        shortcuts: group.shortcuts.filter(
          (s) =>
            s.label.toLowerCase().includes(searchLower) ||
            s.category.toLowerCase().includes(searchLower) ||
            s.keys.some((k) => k.toLowerCase().includes(searchLower))
        ),
      }))
      .filter((group) => group.shortcuts.length > 0);
  }, [search]);

  useEffect(() => {
    if (open) {
      setTimeout(() => searchInputRef.current?.focus(), 100);
    } else {
      setSearch('');
    }
  }, [open]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && open) {
        e.preventDefault();
        e.stopPropagation();
        onClose();
      }
    };

    if (open) {
      document.addEventListener('keydown', handleKeyDown, true);
      return () => document.removeEventListener('keydown', handleKeyDown, true);
    }
  }, [open, onClose]);

  useEffect(() => {
    if (!open) return;

    const handleTab = (e: KeyboardEvent) => {
      if (e.key !== 'Tab' || !modalRef.current) return;

      const focusableElements = modalRef.current.querySelectorAll(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      );
      const firstElement = focusableElements[0] as HTMLElement;
      const lastElement = focusableElements[focusableElements.length - 1] as HTMLElement;

      if (e.shiftKey && document.activeElement === firstElement) {
        e.preventDefault();
        lastElement.focus();
      } else if (!e.shiftKey && document.activeElement === lastElement) {
        e.preventDefault();
        firstElement.focus();
      }
    };

    document.addEventListener('keydown', handleTab);
    return () => document.removeEventListener('keydown', handleTab);
  }, [open]);

  if (!open) return null;

  return createPortal(
    <div className="fixed inset-0 z-[100] flex items-start justify-center pt-[10vh]">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Modal — floating panel, hairline border, no shadow */}
      <div
        ref={modalRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="shortcuts-title"
        className="relative w-full max-w-lg mx-4 rounded-[var(--radius)] overflow-hidden bg-[var(--surface)] border border-[var(--border)]"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border)]">
          <h2 id="shortcuts-title" className="text-lg font-semibold text-[var(--text)]">
            Keyboard Shortcuts
          </h2>
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1 px-2 py-1 rounded-[var(--radius-small)] bg-[var(--surface-hover)] text-[var(--text-muted)]">
              <span className="font-mono text-sm">{modKey}+/</span>
            </div>
            <button
              onClick={onClose}
              className="p-2 rounded-[var(--radius-small)] transition-colors text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]"
              aria-label="Close"
            >
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Search — flat fill, no border on the wrapper or the input so
            focusing the textbox never paints a highlight ring. */}
        <div className="px-6 py-3 border-b border-[var(--border)]">
          <div className="flex items-center gap-3 px-4 py-2.5 rounded-[var(--radius-small)] bg-[var(--surface-hover)]">
            <MagnifyingGlass size={18} className="text-[var(--text-subtle)]" />
            <input
              ref={searchInputRef}
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search shortcuts..."
              className="flex-1 bg-transparent text-sm text-[var(--text)] placeholder:text-[var(--text-subtle)] border-none outline-none focus:outline-none focus:ring-0 focus:border-transparent shadow-none"
              style={{ outline: 'none', boxShadow: 'none' }}
            />
            {search && (
              <button
                onClick={() => {
                  setSearch('');
                  searchInputRef.current?.focus();
                }}
                className="p-1 rounded-[var(--radius-small)] hover:bg-[var(--surface)] transition-colors"
                aria-label="Clear search"
              >
                <X size={14} className="text-[var(--text-subtle)]" />
              </button>
            )}
          </div>
        </div>

        {/* Shortcuts List */}
        <div className="max-h-[60vh] overflow-y-auto px-6 py-4 space-y-6">
          {filteredGroups.length === 0 ? (
            <p className="text-center py-8 text-[var(--text-subtle)]">
              No shortcuts found matching "{search}"
            </p>
          ) : (
            filteredGroups.map((group) => (
              <div key={group.title}>
                <h3 className="text-xs font-medium uppercase tracking-wider mb-3 text-[var(--text-muted)]">
                  {group.title}
                </h3>
                <div className="space-y-1">
                  {group.shortcuts.map((shortcut) => (
                    <div
                      key={shortcut.id}
                      className="flex items-center justify-between py-2.5 px-3 rounded-[var(--radius-small)] transition-colors hover:bg-[var(--surface-hover)]"
                    >
                      <span className="text-[var(--text)]">{shortcut.label}</span>
                      <div className="flex items-center gap-1">
                        {shortcut.keys.map((key, i) => (
                          <kbd
                            key={i}
                            className="px-2 py-1 rounded-[var(--radius-small)] text-xs font-mono min-w-[24px] text-center bg-[var(--surface-hover)] text-[var(--text-muted)]"
                          >
                            {key}
                          </kbd>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-[var(--border)] text-xs text-[var(--text-subtle)]">
          <span>
            Press{' '}
            <kbd className="px-1.5 py-0.5 rounded-[var(--radius-small)] font-mono bg-[var(--surface-hover)] text-[var(--text-muted)]">
              {modKey}+/
            </kbd>{' '}
            or{' '}
            <kbd className="px-1.5 py-0.5 rounded-[var(--radius-small)] font-mono bg-[var(--surface-hover)] text-[var(--text-muted)]">
              ?
            </kbd>{' '}
            anywhere to open this panel
          </span>
        </div>
      </div>
    </div>,
    document.body
  );
}

export default KeyboardShortcutsModal;
