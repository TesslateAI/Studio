import React, { useState, useRef, useCallback, useMemo } from 'react';
import { X, Plus, Palette } from 'lucide-react';
import {
  type ClassInfo,
  categorizeTailwindClass,
  getActiveCategories,
} from '../../../utils/classDetection';

// ── Common Tailwind class suggestions for autocomplete ──────────────
const COMMON_TAILWIND_CLASSES = [
  // Layout
  'flex', 'inline-flex', 'grid', 'block', 'inline-block', 'hidden', 'relative', 'absolute', 'fixed', 'sticky',
  // Flex
  'flex-col', 'flex-row', 'flex-wrap', 'items-center', 'items-start', 'items-end', 'justify-center', 'justify-between', 'justify-start', 'justify-end',
  // Spacing
  'p-0', 'p-1', 'p-2', 'p-3', 'p-4', 'p-5', 'p-6', 'p-8', 'px-2', 'px-4', 'px-6', 'py-2', 'py-4', 'py-6',
  'm-0', 'm-1', 'm-2', 'm-3', 'm-4', 'mx-auto', 'mt-2', 'mt-4', 'mb-2', 'mb-4',
  'gap-1', 'gap-2', 'gap-3', 'gap-4', 'gap-6', 'gap-8',
  // Sizing
  'w-full', 'w-auto', 'w-screen', 'w-fit', 'h-full', 'h-auto', 'h-screen', 'h-fit',
  'min-h-0', 'min-w-0', 'max-w-sm', 'max-w-md', 'max-w-lg', 'max-w-xl', 'max-w-2xl',
  // Typography
  'text-xs', 'text-sm', 'text-base', 'text-lg', 'text-xl', 'text-2xl', 'text-3xl',
  'font-light', 'font-normal', 'font-medium', 'font-semibold', 'font-bold',
  'text-left', 'text-center', 'text-right', 'truncate', 'uppercase', 'lowercase',
  // Colors
  'text-white', 'text-black', 'text-gray-500', 'text-gray-700', 'text-gray-900',
  'bg-white', 'bg-black', 'bg-gray-50', 'bg-gray-100', 'bg-gray-200', 'bg-gray-900',
  'bg-blue-500', 'bg-green-500', 'bg-red-500', 'bg-yellow-500', 'bg-purple-500',
  // Border
  'border', 'border-0', 'border-2', 'border-t', 'border-b', 'border-l', 'border-r',
  'rounded', 'rounded-sm', 'rounded-md', 'rounded-lg', 'rounded-xl', 'rounded-2xl', 'rounded-full',
  'border-gray-200', 'border-gray-300', 'border-transparent',
  // Effects
  'shadow', 'shadow-sm', 'shadow-md', 'shadow-lg', 'shadow-xl', 'shadow-none',
  'opacity-0', 'opacity-50', 'opacity-100',
  // Transition
  'transition', 'transition-all', 'transition-colors', 'duration-150', 'duration-200', 'duration-300',
  'ease-in', 'ease-out', 'ease-in-out',
  // Overflow
  'overflow-hidden', 'overflow-auto', 'overflow-scroll', 'overflow-visible',
];

interface VisualTabProps {
  cursorClasses: ClassInfo | null;
  editorRef: unknown;
  selectedElement?: import('./DesignBridge').ElementData | null;
  onClassUpdate?: (designId: string, classes: string[]) => void;
}

export default function VisualTab({ cursorClasses, editorRef, selectedElement, onClassUpdate }: VisualTabProps) {
  const [addingClass, setAddingClass] = useState(false);
  const [inputValue, setInputValue] = useState('');
  const [categoryFilter, setCategoryFilter] = useState<string | null>(null);
  const [recentClasses, setRecentClasses] = useState<string[]>(() => {
    try {
      return JSON.parse(localStorage.getItem('tesslate-recent-classes') || '[]');
    } catch { return []; }
  });
  const inputRef = useRef<HTMLInputElement>(null);

  // ── Determine active class source: selectedElement > cursorClasses ──
  const elementClasses = selectedElement && selectedElement.classList.length > 0
    ? selectedElement.classList
    : null;
  const activeClasses = elementClasses ?? cursorClasses?.classes ?? null;
  const sourceIsElement = !!elementClasses;

  // Filtered suggestions for autocomplete
  const suggestions = useMemo(() => {
    if (!inputValue.trim()) return [];
    const lower = inputValue.toLowerCase();
    return COMMON_TAILWIND_CLASSES
      .filter(c => c.toLowerCase().includes(lower) && !(activeClasses?.includes(c)))
      .slice(0, 12);
  }, [inputValue, activeClasses]);

  const updateClasses = useCallback((newClasses: string[]) => {
    // If editing from the selected preview element, update via bridge
    if (sourceIsElement && selectedElement?.designId && onClassUpdate) {
      onClassUpdate(selectedElement.designId, newClasses);
      return;
    }

    // Otherwise edit via Monaco (cursor classes)
    if (!cursorClasses || !editorRef) return;
    const editor = editorRef as {
      executeEdits: (source: string, edits: Array<{ range: unknown; text: string }>) => void;
      getModel: () => { getLineContent: (line: number) => string } | null;
    };

    // Use Monaco's IRange format
    const monacoRange = {
      startLineNumber: cursorClasses.range.lineNumber,
      startColumn: cursorClasses.range.startColumn,
      endLineNumber: cursorClasses.range.lineNumber,
      endColumn: cursorClasses.range.endColumn,
    };

    editor.executeEdits('design-visual', [{
      range: monacoRange,
      text: newClasses.join(' '),
    }]);

    // Also send to bridge for instant live preview (before HMR catches up)
    if (selectedElement?.designId && onClassUpdate) {
      onClassUpdate(selectedElement.designId, newClasses);
    }
  }, [cursorClasses, editorRef, selectedElement, onClassUpdate, sourceIsElement]);

  const removeClass = useCallback((cls: string) => {
    if (!activeClasses) return;
    const newClasses = activeClasses.filter(c => c !== cls);
    updateClasses(newClasses);
  }, [activeClasses, updateClasses]);

  const addClass = useCallback((cls: string) => {
    if (!activeClasses || !cls.trim()) return;
    const trimmed = cls.trim();
    if (activeClasses.includes(trimmed)) return;
    const newClasses = [...activeClasses, trimmed];
    updateClasses(newClasses);

    // Track recently used
    setRecentClasses(prev => {
      const updated = [trimmed, ...prev.filter(c => c !== trimmed)].slice(0, 20);
      localStorage.setItem('tesslate-recent-classes', JSON.stringify(updated));
      return updated;
    });

    setInputValue('');
    setAddingClass(false);
  }, [activeClasses, updateClasses]);

  const activeCategories = activeClasses
    ? getActiveCategories(activeClasses)
    : [];

  const filteredClasses = activeClasses
    ? categoryFilter
      ? activeClasses.filter(c => categorizeTailwindClass(c).name === categoryFilter)
      : activeClasses
    : [];

  // ── Empty state ────────────────────────────────────────────────────
  if (!activeClasses) {
    return (
      <div className="h-full flex flex-col">
        <div className="flex-1 flex items-center justify-center px-6">
          <div className="text-center">
            <Palette size={24} className="mx-auto mb-3 text-[var(--text-subtle)]" />
            <p className="text-xs text-[var(--text-muted)] mb-1">
              Click an element in the preview or place the cursor on a class declaration in code.
            </p>
            <p className="text-[10px] text-[var(--text-subtle)]">
              Supports className, cn(), clsx(), twMerge()
            </p>
          </div>
        </div>

        {/* Recently used classes */}
        {recentClasses.length > 0 && (
          <div className="border-t border-[var(--border)] px-3 py-3">
            <p className="text-[10px] font-medium text-[var(--text-subtle)] uppercase tracking-wider mb-2">
              Recently Used
            </p>
            <div className="flex flex-wrap gap-1">
              {recentClasses.slice(0, 12).map(cls => {
                const cat = categorizeTailwindClass(cls);
                return (
                  <span
                    key={cls}
                    className={`text-[10px] font-mono px-1.5 py-0.5 rounded border-l-2 ${cat.color} bg-[var(--surface)] border border-[var(--border)] text-[var(--text-subtle)]`}
                  >
                    {cls}
                  </span>
                );
              })}
            </div>
          </div>
        )}
      </div>
    );
  }

  // ── Active class editor ────────────────────────────────────────────
  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Header */}
      <div className="px-3 py-2.5 border-b border-[var(--border)] shrink-0">
        {sourceIsElement && selectedElement ? (
          <>
            <div className="flex items-center gap-1.5 mb-1">
              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-[var(--surface-hover)] text-[var(--text-muted)]">
                &lt;{selectedElement.tagName.toLowerCase()}&gt;
              </span>
              {selectedElement.reactComponent?.name && (
                <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-purple-500/10 text-purple-400">
                  {selectedElement.reactComponent.name}
                </span>
              )}
            </div>
            <p className="text-[10px] text-[var(--text-subtle)] font-mono truncate">
              Preview selection · {activeClasses?.length ?? 0} classes
            </p>
          </>
        ) : (
          <>
            <p className="text-[11px] font-medium text-[var(--text-muted)] mb-1">
              Editing classes
            </p>
            <p className="text-[10px] text-[var(--text-subtle)] font-mono truncate">
              Line {cursorClasses?.range.lineNumber} · {cursorClasses?.classes.length ?? 0} classes
            </p>
          </>
        )}
      </div>

      {/* Category filters */}
      {activeCategories.length > 1 && (
        <div className="px-3 py-2 border-b border-[var(--border)] shrink-0">
          <div className="flex flex-wrap gap-1">
            <button
              onClick={() => setCategoryFilter(null)}
              className={`text-[10px] px-1.5 py-0.5 rounded-full transition-colors ${
                categoryFilter === null
                  ? 'bg-[var(--surface-hover)] text-[var(--text)]'
                  : 'text-[var(--text-subtle)] hover:text-[var(--text-muted)]'
              }`}
            >
              All ({activeClasses.length})
            </button>
            {activeCategories.map(cat => (
              <button
                key={cat.name}
                onClick={() => setCategoryFilter(cat.name === categoryFilter ? null : cat.name)}
                className={`text-[10px] px-1.5 py-0.5 rounded-full transition-colors border-l-2 ${cat.color} ${
                  categoryFilter === cat.name
                    ? 'bg-[var(--surface-hover)] text-[var(--text)]'
                    : 'text-[var(--text-subtle)] hover:text-[var(--text-muted)]'
                }`}
              >
                {cat.name}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Class pills */}
      <div className="flex-1 overflow-y-auto px-3 py-2">
        <div className="flex flex-wrap gap-1.5">
          {filteredClasses.map((cls) => {
            const cat = categorizeTailwindClass(cls);
            return (
              <div
                key={cls}
                className={`group flex items-center gap-1 text-[11px] font-mono px-2 py-1 rounded-md border-l-2 ${cat.color} bg-[var(--surface)] border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--text)] hover:border-[var(--border-hover)] transition-colors`}
              >
                <span>{cls}</span>
                <button
                  onClick={() => removeClass(cls)}
                  className="opacity-0 group-hover:opacity-100 transition-opacity p-0.5 rounded hover:bg-[var(--surface-hover)]"
                >
                  <X size={10} />
                </button>
              </div>
            );
          })}
        </div>
      </div>

      {/* Add class input */}
      <div className="px-3 py-2.5 border-t border-[var(--border)] shrink-0">
        {addingClass ? (
          <div className="relative">
            <input
              ref={inputRef}
              value={inputValue}
              onChange={e => setInputValue(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter' && inputValue.trim()) {
                  addClass(inputValue);
                } else if (e.key === 'Escape') {
                  setAddingClass(false);
                  setInputValue('');
                }
              }}
              placeholder="Type a class name..."
              className="w-full px-2 py-1.5 bg-[var(--surface)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs font-mono focus:outline-none focus:border-[var(--primary)]"
              autoFocus
            />

            {/* Autocomplete suggestions */}
            {suggestions.length > 0 && (
              <div className="absolute bottom-full left-0 right-0 mb-1 bg-[var(--surface)] border border-[var(--border)] rounded-[var(--radius-small)] shadow-lg max-h-48 overflow-y-auto z-10">
                {suggestions.map(cls => {
                  const cat = categorizeTailwindClass(cls);
                  return (
                    <button
                      key={cls}
                      onClick={() => addClass(cls)}
                      className={`w-full px-2 py-1 text-left text-[11px] font-mono text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)] flex items-center gap-2 border-l-2 ${cat.color}`}
                    >
                      <span>{cls}</span>
                      <span className="text-[9px] text-[var(--text-subtle)] ml-auto">{cat.name}</span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        ) : (
          <button
            onClick={() => {
              setAddingClass(true);
              setTimeout(() => inputRef.current?.focus(), 0);
            }}
            className="w-full flex items-center justify-center gap-1.5 px-2 py-1.5 text-xs text-[var(--text-muted)] hover:text-[var(--text)] bg-[var(--surface)] hover:bg-[var(--surface-hover)] border border-dashed border-[var(--border)] rounded-[var(--radius-small)] transition-colors"
          >
            <Plus size={12} />
            Add class
          </button>
        )}
      </div>
    </div>
  );
}
