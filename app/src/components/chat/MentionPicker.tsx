/**
 * MentionPicker — `@`-trigger autocomplete dropup for the chat input.
 *
 * Four sections, each with a theme-aware accent color:
 *
 *   Agents     -> --primary       (orange)        kind=agent
 *   Apps       -> --status-purple (purple)        kind=app
 *   Connectors -> --accent        (cyan)          kind=mcp
 *   Files      -> --status-info   (blue)          kind=file (project files)
 *
 * Disabled rows render with `opacity-50` but stay keyboard-selectable so
 * users can self-discover what they could turn on. Selecting a disabled
 * row does not insert the mention; instead it surfaces a small inline
 * note (handled by the parent via `onDisabledSelect`) so we never silently
 * drop a click.
 *
 * Positioning: this component is unconcerned with where it sits — the
 * parent (`ChatInput`) anchors it via absolute/fixed positioning above
 * the textarea. We just render the visual shell.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import {
  Robot as AgentIcon,
  Plug as McpIcon,
  AppWindow as AppIcon,
  File as FileIcon,
  WarningCircle,
} from '@phosphor-icons/react';

import type { ChatMention, ChatMentionKind } from '../../types/agent';
import type { MentionItem } from '../../lib/api';

export type MentionPickerKind = ChatMentionKind | 'file';

export interface MentionPickerFile {
  kind: 'file';
  path: string; // e.g. "src/components/Foo.tsx"
  display: string; // e.g. "Foo.tsx"
}

/**
 * One concrete row the picker can show. Mentions ride through the
 * structured `mentions[]` array on the chat request; files keep the
 * existing inline `@filename` behaviour and never go into `mentions[]`.
 */
export type MentionPickerRow =
  | (MentionItem & { rowKind: 'mention' })
  | (MentionPickerFile & { rowKind: 'file'; enabled: true });

const KIND_LABEL: Record<MentionPickerKind, string> = {
  agent: 'Agents',
  app: 'Apps',
  mcp: 'Connectors',
  file: 'Files',
};

// Phosphor icons accept className + arbitrary props; widen the
// component type so `<Icon className=…>` typechecks.
const KIND_ICON: Record<
  MentionPickerKind,
  React.ComponentType<{
    size?: number;
    weight?: 'regular' | 'fill' | 'bold';
    className?: string;
  }>
> = {
  agent: AgentIcon,
  app: AppIcon,
  mcp: McpIcon,
  file: FileIcon,
};

// Theme-token mapping — works in light + dark mode automatically because
// every token is defined per-theme in `themePresets.ts`.
const KIND_TOKENS: Record<MentionPickerKind, { dot: string; chip: string; iconText: string }> = {
  agent: {
    dot: 'bg-[var(--primary)]',
    chip: 'bg-[var(--primary)]/10 text-[var(--primary)] border-[var(--primary)]/20',
    iconText: 'text-[var(--primary)]',
  },
  app: {
    dot: 'bg-[var(--status-purple)]',
    chip: 'bg-[var(--status-purple)]/10 text-[var(--status-purple)] border-[var(--status-purple)]/20',
    iconText: 'text-[var(--status-purple)]',
  },
  mcp: {
    dot: 'bg-[var(--accent)]',
    chip: 'bg-[var(--accent)]/10 text-[var(--accent)] border-[var(--accent)]/20',
    iconText: 'text-[var(--accent)]',
  },
  file: {
    dot: 'bg-[var(--status-info)]',
    chip: 'bg-[var(--status-info)]/10 text-[var(--status-info)] border-[var(--status-info)]/20',
    iconText: 'text-[var(--status-info)]',
  },
};

export interface MentionPickerProps {
  isOpen: boolean;
  query: string; // text after the `@` trigger, lowercased by parent
  agents: MentionItem[];
  mcps: MentionItem[];
  apps: MentionItem[];
  files: MentionPickerFile[];
  loading?: boolean;
  /**
   * Called when the user picks an enabled @-mention (agent / mcp / app).
   * The parent inserts the structured ChatMention into its mentions[]
   * state and replaces the `@<query>` token in the textarea.
   */
  onSelectMention: (mention: ChatMention, item: MentionItem) => void;
  /** Called when the user picks a project file. */
  onSelectFile: (file: MentionPickerFile) => void;
  /**
   * Called when the user picks a *disabled* @-mention. Default behaviour
   * is to flash a small inline tooltip; the parent gets to decide.
   */
  onDisabledSelect?: (item: MentionItem) => void;
  onClose: () => void;
}

interface FlatRow {
  section: MentionPickerKind;
  row: MentionPickerRow;
}

export function MentionPicker({
  isOpen,
  query,
  agents,
  mcps,
  apps,
  files,
  loading,
  onSelectMention,
  onSelectFile,
  onDisabledSelect,
  onClose,
}: MentionPickerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [activeIndex, setActiveIndex] = useState(0);

  // Filter each section by query, then build a flat list of rows for
  // keyboard navigation. Order: Agents, Apps, Connectors, Files —
  // matches the visual stacking the user requested.
  const flatRows: FlatRow[] = useMemo(() => {
    const q = (query || '').toLowerCase().trim();
    const matches = (text: string | null | undefined) =>
      !q || (text ?? '').toLowerCase().includes(q);

    const filteredAgents = agents.filter((a) => matches(a.name) || matches(a.slug));
    const filteredApps = apps.filter((a) => matches(a.name) || matches(a.slug));
    const filteredMcps = mcps.filter((m) => matches(m.name) || matches(m.slug));
    const filteredFiles = files.filter((f) => matches(f.display) || matches(f.path));

    const rows: FlatRow[] = [];
    for (const a of filteredAgents) rows.push({ section: 'agent', row: { ...a, rowKind: 'mention' } });
    for (const a of filteredApps) rows.push({ section: 'app', row: { ...a, rowKind: 'mention' } });
    for (const m of filteredMcps) rows.push({ section: 'mcp', row: { ...m, rowKind: 'mention' } });
    for (const f of filteredFiles)
      rows.push({ section: 'file', row: { ...f, rowKind: 'file', enabled: true } });
    return rows;
  }, [agents, apps, mcps, files, query]);

  // Reset active index when the row set changes so we never end up on a
  // stale row (e.g. user typed deeper, the previously active row vanished).
  useEffect(() => {
    setActiveIndex((prev) => (prev >= flatRows.length ? 0 : prev));
  }, [flatRows.length]);

  // Keyboard navigation — arrow up/down cycle, Enter commits, Escape closes.
  // We bind on `keydown` at the window level only while open; the parent
  // textarea still receives the event but we stopPropagation on the keys
  // we consume so the textarea doesn't also process them (e.g. arrow-up
  // would otherwise trigger ChatInput's history navigation).
  useEffect(() => {
    if (!isOpen) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        e.stopPropagation();
        setActiveIndex((i) => (flatRows.length === 0 ? 0 : (i + 1) % flatRows.length));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        e.stopPropagation();
        setActiveIndex((i) =>
          flatRows.length === 0 ? 0 : (i - 1 + flatRows.length) % flatRows.length
        );
      } else if (e.key === 'Enter' || e.key === 'Tab') {
        if (flatRows.length === 0) return;
        e.preventDefault();
        e.stopPropagation();
        commit(flatRows[activeIndex]);
      } else if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        onClose();
      }
    };
    // Capture phase so we beat the textarea handler.
    window.addEventListener('keydown', handler, { capture: true });
    return () => window.removeEventListener('keydown', handler, { capture: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, flatRows, activeIndex]);

  // Click-outside dismissal. We don't need to track an anchor here —
  // any click that misses the popover closes it.
  useEffect(() => {
    if (!isOpen) return;
    const handler = (e: MouseEvent) => {
      const t = e.target as Node;
      if (containerRef.current && !containerRef.current.contains(t)) {
        onClose();
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [isOpen, onClose]);

  function commit(flat: FlatRow) {
    if (flat.row.rowKind === 'file') {
      onSelectFile(flat.row);
      return;
    }
    const item = flat.row;
    if (!item.enabled) {
      onDisabledSelect?.(item);
      return;
    }
    const display = '@' + (item.slug || item.name || 'mention').replace(/\s+/g, '-');
    const mention: ChatMention = {
      kind: item.kind,
      ref_id: item.ref_id,
      display,
      offset: 0, // ChatInput re-computes this when it splices the textarea
    };
    onSelectMention(mention, item);
  }

  // Build sectioned render structure once for the JSX below.
  const sections: { kind: MentionPickerKind; rows: FlatRow[] }[] = [
    { kind: 'agent', rows: flatRows.filter((r) => r.section === 'agent') },
    { kind: 'app', rows: flatRows.filter((r) => r.section === 'app') },
    { kind: 'mcp', rows: flatRows.filter((r) => r.section === 'mcp') },
    { kind: 'file', rows: flatRows.filter((r) => r.section === 'file') },
  ];

  // Map flat-index per row so we can highlight the keyboard-active one.
  const rowIndex = (flat: FlatRow) => flatRows.indexOf(flat);

  if (!isOpen) return null;

  return (
    <AnimatePresence>
      <motion.div
        ref={containerRef}
        initial={{ opacity: 0, y: 4 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: 4 }}
        transition={{ duration: 0.12 }}
        className="z-50 w-[420px] max-w-[calc(100vw-2rem)] overflow-hidden rounded-[var(--radius-medium)] border bg-[var(--surface)] shadow-lg"
        style={{
          borderWidth: 'var(--border-width)',
          borderColor: 'var(--border-hover)',
          maxHeight: '380px',
          display: 'flex',
          flexDirection: 'column',
        }}
        role="listbox"
        aria-label="Mention picker"
      >
        <div
          className="flex items-center justify-between px-3 py-2 border-b text-[11px] uppercase tracking-wide text-[var(--text-muted)]"
          style={{ borderColor: 'var(--border)' }}
        >
          <span>{query ? `Matching “${query}”` : 'Type to search · ↑↓ to navigate · ↵ to insert'}</span>
          {loading ? <span>loading…</span> : null}
        </div>

        <div className="overflow-y-auto py-1 flex-1">
          {flatRows.length === 0 ? (
            <div className="px-3 py-6 text-center text-sm text-[var(--text-muted)]">
              No matches.
            </div>
          ) : (
            sections.map(({ kind, rows }) => {
              if (rows.length === 0) return null;
              const Icon = KIND_ICON[kind];
              const tokens = KIND_TOKENS[kind];
              return (
                <div key={kind} className="pb-1">
                  <div
                    className="flex items-center gap-2 px-3 pt-2 pb-1 text-[10px] uppercase tracking-wide text-[var(--text-muted)] border-t first:border-t-0"
                    style={{ borderColor: 'var(--border)' }}
                  >
                    <span className={`inline-block h-1.5 w-1.5 rounded-full ${tokens.dot}`} />
                    <span>{KIND_LABEL[kind]}</span>
                  </div>

                  {rows.map((flat) => {
                    const isActive = rowIndex(flat) === activeIndex;
                    if (flat.row.rowKind === 'file') {
                      return (
                        <button
                          type="button"
                          key={`file-${flat.row.path}`}
                          onMouseEnter={() => setActiveIndex(rowIndex(flat))}
                          onClick={() => commit(flat)}
                          className={`w-full text-left px-3 py-1.5 text-sm flex items-center gap-2 ${
                            isActive ? 'bg-[var(--surface-hover)]' : 'hover:bg-[var(--surface-hover)]'
                          }`}
                        >
                          <Icon size={14} weight="regular" className={tokens.iconText} />
                          <span className="text-[var(--text)] truncate">{flat.row.display}</span>
                          <span className="text-[var(--text-muted)] text-xs truncate">
                            {flat.row.path}
                          </span>
                        </button>
                      );
                    }
                    const item = flat.row;
                    return (
                      <button
                        type="button"
                        key={`${kind}-${item.ref_id}`}
                        onMouseEnter={() => setActiveIndex(rowIndex(flat))}
                        onClick={() => commit(flat)}
                        className={`w-full text-left px-3 py-1.5 text-sm flex items-center gap-2 ${
                          isActive ? 'bg-[var(--surface-hover)]' : 'hover:bg-[var(--surface-hover)]'
                        } ${item.enabled ? '' : 'opacity-50'}`}
                      >
                        {item.icon_url ? (
                          // eslint-disable-next-line @next/next/no-img-element, jsx-a11y/alt-text
                          <img
                            src={item.icon_url}
                            alt=""
                            className="h-4 w-4 rounded-sm flex-shrink-0"
                          />
                        ) : (
                          <Icon size={14} weight="regular" className={`${tokens.iconText} flex-shrink-0`} />
                        )}
                        <span className="text-[var(--text)] truncate flex-1">{item.name}</span>
                        {item.slug ? (
                          <span
                            className={`rounded-md px-1.5 py-0.5 text-[10px] font-mono truncate border ${tokens.chip}`}
                          >
                            @{item.slug}
                          </span>
                        ) : null}
                        {item.state_label ? (
                          <span
                            className={`ml-1 inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] ${tokens.chip}`}
                          >
                            {item.state_label === 'needs reauth' ? (
                              <WarningCircle size={10} weight="fill" />
                            ) : null}
                            {item.state_label}
                          </span>
                        ) : null}
                      </button>
                    );
                  })}
                </div>
              );
            })
          )}
        </div>
      </motion.div>
    </AnimatePresence>
  );
}
