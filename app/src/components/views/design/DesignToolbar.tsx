import React, { useRef, useState, useCallback } from 'react';
import { Crosshair, Plus, Type, Move, Undo2, Redo2, Loader2 } from 'lucide-react';
import { ArrowsClockwise, DeviceMobile } from '@phosphor-icons/react';
import { InsertPalette } from './InsertPalette';
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
  openFiles: { path: string; name: string }[];
  activeFile: string | null;
  onFileSelect: (path: string) => void;
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
}

export function DesignToolbar({
  openFiles,
  activeFile,
  onFileSelect,
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

  const _activeWidth = BREAKPOINT_WIDTHS[viewportBreakpoint];

  return (
    <div className="flex-shrink-0">
      {/* Row 1 — Component selector */}
      <div className="h-10 flex items-center gap-2 px-3 border-b border-[var(--border)] bg-[var(--bg)]">
        {/* +Insert button */}
        <div className="relative">
          <button
            ref={insertBtnRef}
            onClick={handleInsertToggle}
            className="bg-emerald-500 hover:bg-emerald-600 text-white rounded-md px-3 py-1.5 text-xs font-medium flex items-center gap-1 transition-colors"
          >
            <Plus size={12} />
            Insert
          </button>
          <InsertPalette
            isOpen={insertOpen}
            onClose={() => setInsertOpen(false)}
            onInsert={handleInsert}
            onAIAssist={() => {}}
            fileTree={fileTree}
          />
        </div>

        {/* Component pills */}
        <div className="flex items-center gap-1.5 overflow-x-auto flex-1 min-w-0">
          {openFiles.map((file) => {
            const isActive = file.path === activeFile;
            return (
              <button
                key={file.path}
                onClick={() => onFileSelect(file.path)}
                title={file.path}
                className={
                  isActive
                    ? 'bg-amber-500/90 text-white rounded-full px-3 py-1 text-xs font-medium flex-shrink-0 transition-colors'
                    : 'bg-[var(--surface)] text-[var(--text-muted)] hover:text-[var(--text)] rounded-full px-3 py-1 text-xs border border-[var(--border)] flex-shrink-0 transition-colors'
                }
              >
                <span className="truncate max-w-[120px] block">{file.name}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Row 2 — Preview controls */}
      <div className="h-8 flex items-center px-3 border-b border-[var(--border)] bg-[var(--bg)]">
        {/* Left section */}
        <div className="flex items-center gap-1">
          <span className="text-[10px] font-medium text-[var(--text-subtle)] uppercase tracking-wider">
            PREVIEW
          </span>
          <div className="w-px h-3.5 bg-[var(--border)] mx-2" />
          <div className="flex items-center gap-0.5 bg-[var(--surface)] rounded-[var(--radius-small)] p-0.5">
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
        </div>

        {/* Center section — Viewport breakpoints */}
        <div className="flex items-center gap-0.5 mx-auto">
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

        {/* Right section */}
        <div className="flex items-center gap-1">
          {/* Persistence status */}
          {persistError ? (
            <span
              className="text-[10px] px-1.5 py-0.5 rounded text-red-400 border border-red-500/30 mr-1"
              title={persistError}
            >
              Save failed
            </span>
          ) : indexLoading && !indexLoaded ? (
            <span
              className="text-[10px] text-[var(--text-subtle)] mr-1 flex items-center gap-1"
              title="Injecting data-oid attributes into source files"
            >
              <Loader2 size={10} className="animate-spin" />
              Indexing
            </span>
          ) : flushing ? (
            <Loader2 size={12} className="text-[var(--text-subtle)] animate-spin mr-1" />
          ) : indexLoaded ? (
            <span
              className="text-[10px] text-[var(--text-subtle)] mr-1"
              title="Edits persist to source"
            >
              Saved
            </span>
          ) : null}

          {/* Undo / Redo */}
          <button
            onClick={onUndo}
            disabled={!canUndo}
            title="Undo (⌘Z)"
            className={`p-1 rounded transition-colors ${
              canUndo
                ? 'text-[var(--text-muted)] hover:text-[var(--text)]'
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
                ? 'text-[var(--text-muted)] hover:text-[var(--text)]'
                : 'text-[var(--text-subtle)]/40 cursor-not-allowed'
            }`}
          >
            <Redo2 size={14} />
          </button>

          <button
            onClick={onRefresh}
            title="Refresh preview"
            className="p-1 text-[var(--text-subtle)] hover:text-[var(--text-muted)] transition-colors rounded"
          >
            <ArrowsClockwise size={14} />
          </button>
        </div>
      </div>
    </div>
  );
}
