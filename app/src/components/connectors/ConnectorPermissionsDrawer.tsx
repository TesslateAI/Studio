import { useEffect, useMemo, useState } from 'react';
import { X, Warning } from '@phosphor-icons/react';
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

  useEffect(() => {
    setDisabled(new Set(initiallyDisabled));
  }, [initiallyDisabled, open]);

  const groups = useMemo(() => {
    const g: { read: ConnectorTool[]; write: ConnectorTool[]; other: ConnectorTool[] } = {
      read: [],
      write: [],
      other: [],
    };
    for (const t of tools) g[classify(t.name)].push(t);
    return g;
  }, [tools]);

  if (!open) return null;

  const toggle = (prefixed: string) => {
    setDisabled((prev) => {
      const next = new Set(prev);
      if (next.has(prefixed)) next.delete(prefixed);
      else next.add(prefixed);
      return next;
    });
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
      <div className="mb-4">
        <div className="flex items-center gap-2 mb-2 text-xs font-semibold text-[var(--text-muted)] uppercase">
          {danger && <Warning size={12} weight="fill" color="var(--color-warning, #d97706)" />}
          {title}
        </div>
        <ul className="divide-y" style={{ borderColor: 'var(--border)' }}>
          {items.map((t) => {
            const isDisabled = disabled.has(t.prefixedName);
            return (
              <li key={t.prefixedName} className="py-2 flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-sm font-medium text-[var(--text)] truncate">{t.name}</div>
                  {t.description ? (
                    <div className="text-xs text-[var(--text-muted)] line-clamp-2">{t.description}</div>
                  ) : null}
                </div>
                <label className="relative inline-flex items-center cursor-pointer shrink-0">
                  <input
                    type="checkbox"
                    className="sr-only peer"
                    checked={!isDisabled}
                    onChange={() => toggle(t.prefixedName)}
                  />
                  <div className="w-9 h-5 bg-gray-400/40 rounded-full peer-checked:bg-[var(--accent)] peer-focus:outline-none transition" />
                  <div
                    className="absolute left-0.5 top-0.5 w-4 h-4 bg-white rounded-full shadow peer-checked:translate-x-4 transition"
                  />
                </label>
              </li>
            );
          })}
        </ul>
      </div>
    );
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-stretch justify-end"
      style={{ background: 'rgba(0,0,0,0.4)' }}
      onClick={onClose}
    >
      <aside
        className="w-full max-w-md border-l flex flex-col"
        style={{
          background: 'var(--bg)',
          borderColor: 'var(--border)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <header
          className="flex items-center justify-between px-4 py-3 border-b"
          style={{ borderColor: 'var(--border)' }}
        >
          <div>
            <h2 className="text-sm font-semibold text-[var(--text)]">{serverName} permissions</h2>
            <p className="text-xs text-[var(--text-muted)]">
              Toggle off tools you don't want this connector to expose to agents.
            </p>
          </div>
          <button onClick={onClose} aria-label="Close" className="text-[var(--text-muted)]">
            <X size={18} />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto p-4">
          {renderGroup('Read-only tools', groups.read)}
          {renderGroup('Write / destructive tools', groups.write, true)}
          {renderGroup('Other', groups.other)}
          {tools.length === 0 && (
            <p className="text-sm text-[var(--text-muted)]">No tools discovered for this connector yet.</p>
          )}
        </div>

        <footer
          className="flex items-center justify-end gap-2 px-4 py-3 border-t"
          style={{ borderColor: 'var(--border)' }}
        >
          <button
            onClick={onClose}
            className="text-sm px-3 py-1.5 rounded text-[var(--text-muted)] hover:text-[var(--text)]"
          >
            Cancel
          </button>
          <button
            onClick={save}
            disabled={saving}
            className="btn btn-primary text-sm px-3 py-1.5 rounded disabled:opacity-50"
          >
            {saving ? 'Saving...' : 'Save'}
          </button>
        </footer>
      </aside>
    </div>
  );
}
