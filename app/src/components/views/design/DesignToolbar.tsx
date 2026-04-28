import React, { useRef, useState, useCallback } from 'react';
import {
  Crosshair,
  Plus,
  Type,
  Move,
  Undo2,
  Redo2,
  Loader2,
  Maximize2,
  PanelLeft,
  PanelRight,
} from 'lucide-react';
import { ArrowsClockwise, DeviceMobile } from '@phosphor-icons/react';
import { InsertPalette } from './InsertPalette';
import { RECENTER_CANVAS_EVENT } from './CanvasViewport';
import type { FileTreeEntry } from '../../../utils/buildFileTree';

export type Breakpoint = 'fit' | 'sm' | 'md' | 'lg' | 'xl' | '2xl' | 'mobile';

// eslint-disable-next-line react-refresh/only-export-components
export const BREAKPOINT_WIDTHS: Record<Breakpoint, number | 'fit'> = {
  fit: 'fit',
  mobile: 375,
  sm: 640,
  md: 768,
  lg: 1024,
  xl: 1280,
  '2xl': 1536,
};

const BREAKPOINT_LABELS: Record<Breakpoint, React.ReactNode> = {
  fit: 'Fit',
  sm: 'Sm',
  md: 'Md',
  lg: 'Lg',
  xl: 'Xl',
  '2xl': '2xl',
  mobile: <DeviceMobile size={12} />,
};

const BREAKPOINT_ORDER: Breakpoint[] = ['fit', 'sm', 'md', 'lg', 'xl', '2xl', 'mobile'];

interface DesignToolbarProps {
  designMode: 'select' | 'text' | 'move';
  onDesignModeChange: (mode: 'select' | 'text' | 'move') => void;
  viewportBreakpoint: Breakpoint;
  onViewportChange: (bp: Breakpoint) => void;
  onRefresh: () => void;
  onInsert: (snippet: string) => void;
  fileTree: FileTreeEntry[];
  canUndo?: boolean;
  canRedo?: boolean;
  flushing?: boolean;
  persistError?: string | null;
  indexLoaded?: boolean;
  indexLoading?: boolean;
  onUndo?: () => void;
  onRedo?: () => void;
  /** Mobile slide-over toggles. Optional — when omitted (desktop), the
   *  toolbar hides the panel-toggle buttons. */
  onToggleFileTree?: () => void;
  onToggleInspector?: () => void;
  showPanelToggles?: boolean;
}

export function DesignToolbar({
  designMode,
  onDesignModeChange,
  viewportBreakpoint,
  onViewportChange,
  onRefresh,
  onInsert,
  fileTree,
  canUndo = false,
  canRedo = false,
  flushing = false,
  persistError = null,
  indexLoaded = false,
  indexLoading = false,
  onUndo,
  onRedo,
  onToggleFileTree,
  onToggleInspector,
  showPanelToggles = false,
}: DesignToolbarProps) {
  const [insertOpen, setInsertOpen] = useState(false);
  const insertBtnRef = useRef<HTMLButtonElement>(null);

  const handleInsertToggle = useCallback(() => {
    setInsertOpen((prev) => !prev);
  }, []);

  const handleInsert = useCallback(
    (snippet: string) => {
      onInsert(snippet);
      setInsertOpen(false);
    },
    [onInsert],
  );

  const handleRecenter = useCallback(() => {
    window.dispatchEvent(new CustomEvent(RECENTER_CANVAS_EVENT));
  }, []);

  return (
    <div className="flex-shrink-0 border-b border-[var(--border)] bg-[var(--bg)]">
      {/* Single responsive row — wraps under sm so nothing pushes the canvas off-screen. */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-3 py-1.5">
        {/* Mobile: panel toggles */}
        {showPanelToggles && (
          <div className="flex items-center gap-0.5 sm:hidden">
            {onToggleFileTree && (
              <button
                type="button"
                onClick={onToggleFileTree}
                title="Files"
                className="p-1 rounded text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-hover)]"
              >
                <PanelLeft size={14} />
              </button>
            )}
            {onToggleInspector && (
              <button
                type="button"
                onClick={onToggleInspector}
                title="Inspector"
                className="p-1 rounded text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-hover)]"
              >
                <PanelRight size={14} />
              </button>
            )}
            <div className="w-px h-4 bg-[var(--border)] mx-1" />
          </div>
        )}

        {/* Place button — arms placement mode (click target on canvas). */}
        <div className="relative">
          <button
            ref={insertBtnRef}
            onClick={handleInsertToggle}
            className="bg-emerald-500 hover:bg-emerald-600 text-white rounded-md px-2.5 py-1 text-xs font-medium flex items-center gap-1 transition-colors"
            title="Pick a snippet, then click an element to drop it there"
          >
            <Plus size={12} />
            Place
          </button>
          <InsertPalette
            isOpen={insertOpen}
            onClose={() => setInsertOpen(false)}
            onInsert={handleInsert}
            onAIAssist={() => {}}
            fileTree={fileTree}
          />
        </div>

        {/* Mode group — hidden on the smallest screens. */}
        <div className="hidden sm:flex items-center gap-0.5 bg-[var(--surface)] rounded-[var(--radius-small)] p-0.5">
          <button
            onClick={() => onDesignModeChange('select')}
            title="Select elements"
            className={`p-1 rounded transition-colors ${
              designMode === 'select'
                ? 'bg-[var(--primary)]/20 text-[var(--primary)]'
                : 'text-[var(--text-subtle)] hover:text-[var(--text-muted)]'
            }`}
          >
            <Crosshair size={14} />
          </button>
          <button
            onClick={() => onDesignModeChange('text')}
            title="Edit text content"
            className={`p-1 rounded transition-colors ${
              designMode === 'text'
                ? 'bg-[var(--primary)]/20 text-[var(--primary)]'
                : 'text-[var(--text-subtle)] hover:text-[var(--text-muted)]'
            }`}
          >
            <Type size={14} />
          </button>
          <button
            onClick={() => onDesignModeChange('move')}
            title="Drag to reposition"
            className={`p-1 rounded transition-colors ${
              designMode === 'move'
                ? 'bg-[var(--primary)]/20 text-[var(--primary)]'
                : 'text-[var(--text-subtle)] hover:text-[var(--text-muted)]'
            }`}
          >
            <Move size={14} />
          </button>
        </div>

        {/* Breakpoint chips — collapse to a select on small screens. */}
        <div className="hidden md:flex items-center gap-0.5 ml-auto">
          {BREAKPOINT_ORDER.map((bp) => {
            const isActive = bp === viewportBreakpoint;
            const width = BREAKPOINT_WIDTHS[bp];
            return (
              <button
                key={bp}
                onClick={() => onViewportChange(bp)}
                title={`${bp}${typeof width === 'number' ? ` (${width}px)` : ''}`}
                className={`text-[10px] px-1.5 py-0.5 rounded-[var(--radius-small)] transition-colors flex items-center gap-0.5 ${
                  isActive
                    ? 'bg-[var(--surface-hover)] text-[var(--text)]'
                    : 'text-[var(--text-subtle)] hover:text-[var(--text-muted)]'
                }`}
              >
                {BREAKPOINT_LABELS[bp]}
                {isActive && typeof width === 'number' && (
                  <span className="text-[9px] text-[var(--text-muted)]">{width}px</span>
                )}
              </button>
            );
          })}
        </div>

        <select
          value={viewportBreakpoint}
          onChange={(e) => onViewportChange(e.target.value as Breakpoint)}
          className="md:hidden ml-auto text-[10px] bg-[var(--surface)] border border-[var(--border)] rounded-[var(--radius-small)] px-1.5 py-0.5 text-[var(--text-muted)]"
          title="Viewport size"
        >
          {BREAKPOINT_ORDER.map((bp) => {
            const w = BREAKPOINT_WIDTHS[bp];
            return (
              <option key={bp} value={bp}>
                {bp}{typeof w === 'number' ? ` · ${w}px` : ''}
              </option>
            );
          })}
        </select>

        {/* Right cluster — status, recenter, undo/redo, refresh. */}
        <div className="flex items-center gap-1">
          {persistError ? (
            <span
              className="text-[10px] px-1.5 py-0.5 rounded text-red-400 border border-red-500/30"
              title={persistError}
            >
              Save failed
            </span>
          ) : indexLoading && !indexLoaded ? (
            <span
              className="text-[10px] text-[var(--text-subtle)] flex items-center gap-1"
              title="Injecting data-oid attributes into source files"
            >
              <Loader2 size={10} className="animate-spin" />
              Indexing
            </span>
          ) : flushing ? (
            <Loader2 size={12} className="text-[var(--text-subtle)] animate-spin" />
          ) : indexLoaded ? (
            <span
              className="hidden sm:inline text-[10px] text-[var(--text-subtle)]"
              title="Edits persist to source"
            >
              Saved
            </span>
          ) : null}

          <button
            onClick={handleRecenter}
            title="Recenter canvas (0)"
            className="p-1 text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-hover)] transition-colors rounded"
          >
            <Maximize2 size={14} />
          </button>

          <button
            onClick={onUndo}
            disabled={!canUndo}
            title="Undo (⌘Z)"
            className={`p-1 rounded transition-colors ${
              canUndo
                ? 'text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-hover)]'
                : 'text-[var(--text-subtle)]/40 cursor-not-allowed'
            }`}
          >
            <Undo2 size={14} />
          </button>
          <button
            onClick={onRedo}
            disabled={!canRedo}
            title="Redo (⌘⇧Z)"
            className={`p-1 rounded transition-colors ${
              canRedo
                ? 'text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-hover)]'
                : 'text-[var(--text-subtle)]/40 cursor-not-allowed'
            }`}
          >
            <Redo2 size={14} />
          </button>

          <button
            onClick={onRefresh}
            title="Refresh preview"
            className="p-1 text-[var(--text-subtle)] hover:text-[var(--text-muted)] hover:bg-[var(--surface-hover)] transition-colors rounded"
          >
            <ArrowsClockwise size={14} />
          </button>
        </div>
      </div>
    </div>
  );
}
