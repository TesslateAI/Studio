import React, { useState, useMemo, useEffect, useRef } from 'react';
import { MagnifyingGlass, X } from '@phosphor-icons/react';
import { useTheme } from '../theme/ThemeContext';
import { shortcutGroups, type ShortcutGroup } from '../lib/keyboard-registry';

interface KeyboardShortcutsModalProps {
  open: boolean;
  onClose: () => void;
}

export function KeyboardShortcutsModal({ open, onClose }: KeyboardShortcutsModalProps) {
  const [search, setSearch] = useState('');
  const { theme } = useTheme();
  const searchInputRef = useRef<HTMLInputElement>(null);
  const modalRef = useRef<HTMLDivElement>(null);

  // Filter shortcuts based on search
  const filteredGroups = useMemo<ShortcutGroup[]>(() => {
    if (!search) return shortcutGroups;

    const searchLower = search.toLowerCase();
    return shortcutGroups
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

  // Focus search input when modal opens
  useEffect(() => {
    if (open) {
      setTimeout(() => searchInputRef.current?.focus(), 100);
    } else {
      setSearch('');
    }
  }, [open]);

  // Handle escape key
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

  // Trap focus within modal
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

  const isDark = theme === 'dark';

  return (
    <div className="fixed inset-0 z-[100] flex items-start justify-center pt-[10vh]">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Modal */}
      <div
        ref={modalRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="shortcuts-title"
        className={`
          relative w-full max-w-lg mx-4 rounded-xl shadow-2xl overflow-hidden
          ${isDark ? 'bg-[#1a1a1c] border border-white/10' : 'bg-white border border-black/10'}
        `}
      >
        {/* Header */}
        <div
          className={`flex items-center justify-between px-6 py-4 border-b ${isDark ? 'border-white/10' : 'border-black/10'}`}
        >
          <h2
            id="shortcuts-title"
            className={`text-lg font-semibold ${isDark ? 'text-white' : 'text-black'}`}
          >
            Keyboard Shortcuts
          </h2>
          <div className="flex items-center gap-2">
            <div
              className={`p-2 rounded-lg ${isDark ? 'bg-white/10 text-white/60' : 'bg-black/5 text-black/60'}`}
            >
              <span className="font-mono text-sm">?</span>
            </div>
            <button
              onClick={onClose}
              className={`p-2 rounded-lg transition-colors ${isDark ? 'hover:bg-white/10 text-white/60' : 'hover:bg-black/5 text-black/60'}`}
              aria-label="Close"
            >
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Search */}
        <div className={`px-6 py-3 border-b ${isDark ? 'border-white/10' : 'border-black/10'}`}>
          <div
            className={`
              flex items-center gap-3 px-4 py-2.5 rounded-lg border transition-colors
              ${
                isDark
                  ? 'bg-white/5 border-white/10'
                  : 'bg-black/5 border-black/10'
              }
            `}
          >
            <MagnifyingGlass size={18} className={isDark ? 'text-white/40' : 'text-black/40'} />
            <input
              ref={searchInputRef}
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search shortcuts..."
              className={`
                flex-1 bg-transparent outline-none focus-visible:outline-none text-sm
                ${isDark ? 'text-white placeholder-white/40' : 'text-black placeholder-black/40'}
              `}
            />
            {search && (
              <button
                onClick={() => {
                  setSearch('');
                  searchInputRef.current?.focus();
                }}
                className={`p-1 rounded transition-colors ${isDark ? 'hover:bg-white/10' : 'hover:bg-black/10'}`}
                aria-label="Clear search"
              >
                <X size={14} className={isDark ? 'text-white/40' : 'text-black/40'} />
              </button>
            )}
          </div>
        </div>

        {/* Shortcuts List */}
        <div className="max-h-[60vh] overflow-y-auto px-6 py-4 space-y-6">
          {filteredGroups.length === 0 ? (
            <p className={`text-center py-8 ${isDark ? 'text-white/40' : 'text-black/40'}`}>
              No shortcuts found matching "{search}"
            </p>
          ) : (
            filteredGroups.map((group) => (
              <div key={group.title}>
                <h3
                  className={`text-xs font-medium uppercase tracking-wider mb-3 ${isDark ? 'text-white/50' : 'text-black/50'}`}
                >
                  {group.title}
                </h3>
                <div className="space-y-1">
                  {group.shortcuts.map((shortcut) => (
                    <div
                      key={shortcut.id}
                      className={`
                        flex items-center justify-between py-2.5 px-3 rounded-lg transition-colors
                        ${isDark ? 'hover:bg-white/5' : 'hover:bg-black/5'}
                      `}
                    >
                      <span className={isDark ? 'text-white/80' : 'text-black/80'}>
                        {shortcut.label}
                      </span>
                      <div className="flex items-center gap-1">
                        {shortcut.keys.map((key, i) => (
                          <kbd
                            key={i}
                            className={`
                              px-2 py-1 rounded text-xs font-mono min-w-[24px] text-center
                              ${isDark ? 'bg-white/10 text-white/70' : 'bg-black/10 text-black/70'}
                            `}
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
        <div
          className={`px-6 py-3 border-t text-xs ${isDark ? 'border-white/10 text-white/40' : 'border-black/10 text-black/40'}`}
        >
          <span>
            Press{' '}
            <kbd
              className={`px-1.5 py-0.5 rounded font-mono ${isDark ? 'bg-white/10' : 'bg-black/10'}`}
            >
              ?
            </kbd>{' '}
            anywhere to open this panel
          </span>
        </div>
      </div>
    </div>
  );
}

export default KeyboardShortcutsModal;
