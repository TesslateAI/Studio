import { useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { AnimatePresence, motion } from 'framer-motion';
import { X, Warning, MagnifyingGlass } from '@phosphor-icons/react';
import toast from 'react-hot-toast';
import { marketplaceApi } from '../../lib/api';
import { apiErrorMessage } from './errorHelpers';

export interface ConnectorTool {
  /** Prefixed form, e.g. "mcp__github__list_repos" */
  prefixedName: string;
  /** Raw tool name as advertised by the server */
  name: string;
  description?: string;
}

interface Props {
  open: boolean;
  onClose: () => void;
  configId: string;
  serverName: string;
  tools: ConnectorTool[];
  initiallyDisabled: string[];
  onSaved: (disabled: string[]) => void;
}

const READ_PREFIXES = ['list_', 'get_', 'search_', 'read_', 'fetch_', 'query_'];
const WRITE_PREFIXES = ['create_', 'update_', 'delete_', 'remove_', 'write_', 'patch_', 'destroy_'];

function classify(toolName: string): 'read' | 'write' | 'other' {
  const n = toolName.toLowerCase();
  if (READ_PREFIXES.some((p) => n.startsWith(p))) return 'read';
  if (WRITE_PREFIXES.some((p) => n.startsWith(p))) return 'write';
  return 'other';
}

/**
 * Centered permissions modal.
 *
 * Swapped from the old right-side drawer to a centered sheet that grows in
 * with a framer-motion scale+fade. Portal-rendered into document.body so it
 * survives transform'd ancestors. Close on backdrop click, ESC, or the
 * explicit Cancel / close icon.
 */
export function ConnectorPermissionsDrawer({
  open,
  onClose,
  configId,
  serverName,
  tools,
  initiallyDisabled,
  onSaved,
}: Props) {
  const [disabled, setDisabled] = useState<Set<string>>(new Set(initiallyDisabled));
  const [saving, setSaving] = useState(false);
  const [query, setQuery] = useState('');

  useEffect(() => {
    setDisabled(new Set(initiallyDisabled));
    setQuery('');
  }, [initiallyDisabled, open]);

  // ESC to close.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  const filteredTools = useMemo(() => {
    if (!query.trim()) return tools;
    const q = query.toLowerCase();
    return tools.filter(
      (t) =>
        t.name.toLowerCase().includes(q) ||
        (t.description || '').toLowerCase().includes(q),
    );
  }, [tools, query]);

  const groups = useMemo(() => {
    const g: { read: ConnectorTool[]; write: ConnectorTool[]; other: ConnectorTool[] } = {
      read: [],
      write: [],
      other: [],
    };
    for (const t of filteredTools) g[classify(t.name)].push(t);
    return g;
  }, [filteredTools]);

  const enabledCount = tools.length - disabled.size;

  const toggle = (prefixed: string) => {
    setDisabled((prev) => {
      const next = new Set(prev);
      if (next.has(prefixed)) next.delete(prefixed);
      else next.add(prefixed);
      return next;
    });
  };

  const enableAll = () => setDisabled(new Set());
  const disableAll = () => setDisabled(new Set(tools.map((t) => t.prefixedName)));
  const enableReadOnly = () => {
    const writeSlugs = tools
      .filter((t) => classify(t.name) === 'write')
      .map((t) => t.prefixedName);
    setDisabled(new Set(writeSlugs));
  };

  const save = async () => {
    setSaving(true);
    try {
      await marketplaceApi.updateMcpDisabledTools(configId, Array.from(disabled).sort());
      toast.success('Permissions updated');
      onSaved(Array.from(disabled));
      onClose();
    } catch (err) {
      toast.error(apiErrorMessage(err, 'Failed to update permissions'));
    } finally {
      setSaving(false);
    }
  };

  const renderGroup = (title: string, items: ConnectorTool[], danger?: boolean) => {
    if (!items.length) return null;
    return (
      <section className="mb-5">
        <div className="flex items-center gap-2 mb-2">
          {danger && (
            <Warning
              size={12}
              weight="fill"
              className="text-[var(--color-warning,#d97706)] shrink-0"
            />
          )}
          <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-muted)]">
            {title}
          </span>
          <span className="text-[10px] text-[var(--text-subtle)]">{items.length}</span>
        </div>
        <ul className="rounded-[var(--radius-medium)] border border-[var(--border)] divide-y divide-[var(--border)] overflow-hidden">
          {items.map((t) => {
            const isDisabled = disabled.has(t.prefixedName);
            return (
              <li
                key={t.prefixedName}
                className="px-3 py-2.5 flex items-start justify-between gap-3 hover:bg-[var(--surface-hover)] transition-colors"
              >
                <div className="min-w-0 flex-1">
                  <div className="text-xs font-medium text-[var(--text)] font-mono truncate">
                    {t.name}
                  </div>
                  {t.description ? (
                    <div className="text-[11px] text-[var(--text-muted)] line-clamp-2 mt-0.5">
                      {t.description}
                    </div>
                  ) : null}
                </div>
                <label className="relative inline-flex items-center cursor-pointer shrink-0 mt-0.5">
                  <input
                    type="checkbox"
                    className="sr-only peer"
                    checked={!isDisabled}
                    onChange={() => toggle(t.prefixedName)}
                  />
                  <div className="w-9 h-5 bg-[var(--border)] rounded-full peer-checked:bg-[var(--status-success)] transition-colors" />
                  <div className="absolute left-0.5 top-0.5 w-4 h-4 bg-white rounded-full shadow peer-checked:translate-x-4 transition-transform" />
                </label>
              </li>
            );
          })}
        </ul>
      </section>
    );
  };

  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-8"
          style={{ background: 'rgba(0,0,0,0.55)', backdropFilter: 'blur(2px)' }}
          onClick={onClose}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
        >
          <motion.div
            role="dialog"
            aria-modal="true"
            aria-label={`${serverName} permissions`}
            onClick={(e) => e.stopPropagation()}
            initial={{ opacity: 0, scale: 0.96, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.98, y: 4 }}
            transition={{ duration: 0.18, ease: [0.22, 1, 0.36, 1] }}
            className="w-full max-w-2xl max-h-[85vh] flex flex-col bg-[var(--bg)] border border-[var(--border)] rounded-[var(--radius)] shadow-2xl overflow-hidden"
          >
            {/* Header */}
            <header className="flex items-start justify-between gap-4 px-5 py-4 border-b border-[var(--border)]">
              <div className="min-w-0">
                <h2 className="text-sm font-semibold text-[var(--text)] truncate">
                  {serverName} permissions
                </h2>
                <p className="text-[11px] text-[var(--text-muted)] mt-0.5">
                  {tools.length === 0
                    ? 'No tools discovered for this connector yet.'
                    : `${enabledCount} of ${tools.length} tools enabled — toggle off anything you don't want agents to call.`}
                </p>
              </div>
              <button
                onClick={onClose}
                aria-label="Close"
                className="shrink-0 p-1 rounded-[var(--radius-small)] text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-hover)] transition-colors"
              >
                <X size={16} />
              </button>
            </header>

            {/* Toolbar */}
            {tools.length > 0 && (
              <div className="flex items-center gap-2 px-5 py-2.5 border-b border-[var(--border)]">
                <div className="relative flex-1">
                  <MagnifyingGlass
                    size={12}
                    className="absolute left-2 top-1/2 -translate-y-1/2 text-[var(--text-subtle)]"
                  />
                  <input
                    type="text"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Filter tools…"
                    className="w-full pl-7 pr-2 py-1.5 text-xs bg-[var(--surface)] border border-[var(--border)] rounded-[var(--radius-small)] text-[var(--text)] placeholder:text-[var(--text-subtle)] focus:outline-none focus:border-[var(--border-hover)]"
                  />
                </div>
                <button onClick={enableAll} className="btn btn-sm">
                  Enable all
                </button>
                <button onClick={enableReadOnly} className="btn btn-sm">
                  Read only
                </button>
                <button onClick={disableAll} className="btn btn-sm">
                  Disable all
                </button>
              </div>
            )}

            {/* Body */}
            <div className="flex-1 overflow-y-auto px-5 py-4">
              {tools.length === 0 ? (
                <div className="py-12 text-center">
                  <p className="text-xs text-[var(--text-muted)]">
                    No tools discovered for this connector yet.
                  </p>
                </div>
              ) : filteredTools.length === 0 ? (
                <div className="py-12 text-center">
                  <p className="text-xs text-[var(--text-muted)]">
                    No tools match &quot;{query}&quot;.
                  </p>
                </div>
              ) : (
                <>
                  {renderGroup('Read-only tools', groups.read)}
                  {renderGroup('Write / destructive tools', groups.write, true)}
                  {renderGroup('Other', groups.other)}
                </>
              )}
            </div>

            {/* Footer */}
            <footer className="flex items-center justify-between gap-3 px-5 py-3 border-t border-[var(--border)]">
              <span className="text-[11px] text-[var(--text-subtle)]">
                {disabled.size > 0
                  ? `${disabled.size} tool${disabled.size === 1 ? '' : 's'} disabled`
                  : 'All tools enabled'}
              </span>
              <div className="flex items-center gap-2">
                <button onClick={onClose} className="btn btn-sm">
                  Cancel
                </button>
                <button
                  onClick={save}
                  disabled={saving || tools.length === 0}
                  className="btn btn-filled btn-sm disabled:opacity-50"
                >
                  {saving ? 'Saving…' : 'Save changes'}
                </button>
              </div>
            </footer>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  );
}
