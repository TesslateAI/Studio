/**
 * DataPanel — the project's built-in Workspace Data Store.
 *
 * A per-project KV/document database (plain rows in the platform DB — no
 * pods, no lifecycle). Two views: Collections (browse/manage data) and API
 * Keys (anon/service keys for deployed frontends to read/write the store).
 * Available on every project, including empty workspaces.
 */
import { useCallback, useEffect, useState } from 'react';
import toast from 'react-hot-toast';
import {
  ArrowClockwise,
  CaretDown,
  CaretRight,
  Copy,
  Database,
  Key,
  Plus,
  Trash,
} from '@phosphor-icons/react';
import {
  workspaceDataApi,
  type WorkspaceCollection,
  type WorkspaceDataKey,
  type WorkspaceDataUsage,
  type WorkspaceRecord,
} from '../../lib/api';

interface DataPanelProps {
  projectSlug: string;
}

type View = 'collections' | 'keys';

const RECORDS_PAGE_SIZE = 25;

const FLAG_FIELDS = [
  { key: 'public_insert', label: 'Insert' },
  { key: 'public_read', label: 'Read' },
  { key: 'public_update', label: 'Update' },
  { key: 'public_delete', label: 'Delete' },
] as const;

function apiError(err: unknown, fallback: string): string {
  const e = err as { response?: { data?: { detail?: string } } };
  return e?.response?.data?.detail || fallback;
}

export function DataPanel({ projectSlug }: DataPanelProps) {
  const [view, setView] = useState<View>('collections');
  const [collections, setCollections] = useState<WorkspaceCollection[]>([]);
  const [usage, setUsage] = useState<WorkspaceDataUsage | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<WorkspaceCollection | null>(null);

  const [records, setRecords] = useState<WorkspaceRecord[]>([]);
  const [recordTotal, setRecordTotal] = useState(0);
  const [recordOffset, setRecordOffset] = useState(0);
  const [recordsLoading, setRecordsLoading] = useState(false);
  const [expandedRecord, setExpandedRecord] = useState<string | null>(null);

  const [showNewCollection, setShowNewCollection] = useState(false);
  const [newCollectionName, setNewCollectionName] = useState('');

  const [keys, setKeys] = useState<WorkspaceDataKey[]>([]);
  const [showNewKey, setShowNewKey] = useState(false);
  const [newKeyName, setNewKeyName] = useState('');
  const [newKeyKind, setNewKeyKind] = useState('anon');
  const [createdKey, setCreatedKey] = useState<string | null>(null);

  const loadCollections = useCallback(async () => {
    setLoading(true);
    try {
      const [cols, use] = await Promise.all([
        workspaceDataApi.listCollections(projectSlug),
        workspaceDataApi.getUsage(projectSlug),
      ]);
      setCollections(cols);
      setUsage(use);
    } catch (err) {
      toast.error(apiError(err, 'Failed to load data collections'));
    } finally {
      setLoading(false);
    }
  }, [projectSlug]);

  const loadKeys = useCallback(async () => {
    try {
      setKeys(await workspaceDataApi.listKeys(projectSlug));
    } catch (err) {
      toast.error(apiError(err, 'Failed to load API keys'));
    }
  }, [projectSlug]);

  useEffect(() => {
    loadCollections();
  }, [loadCollections]);

  useEffect(() => {
    if (view === 'keys') loadKeys();
  }, [view, loadKeys]);

  const loadRecords = useCallback(
    async (collection: WorkspaceCollection, offset: number) => {
      setRecordsLoading(true);
      try {
        const page = await workspaceDataApi.listRecords(
          projectSlug,
          collection.id,
          RECORDS_PAGE_SIZE,
          offset
        );
        setRecords(page.records);
        setRecordTotal(page.total);
        setRecordOffset(offset);
      } catch (err) {
        toast.error(apiError(err, 'Failed to load records'));
      } finally {
        setRecordsLoading(false);
      }
    },
    [projectSlug]
  );

  const selectCollection = (collection: WorkspaceCollection) => {
    setSelected(collection);
    setExpandedRecord(null);
    loadRecords(collection, 0);
  };

  const handleCreateCollection = async () => {
    const name = newCollectionName.trim();
    if (!name) return;
    try {
      await workspaceDataApi.createCollection(projectSlug, { name });
      toast.success(`Collection '${name}' created`);
      setNewCollectionName('');
      setShowNewCollection(false);
      await loadCollections();
    } catch (err) {
      toast.error(apiError(err, 'Failed to create collection'));
    }
  };

  const handleToggleFlag = async (
    collection: WorkspaceCollection,
    field: (typeof FLAG_FIELDS)[number]['key']
  ) => {
    try {
      const updated = await workspaceDataApi.updateCollection(projectSlug, collection.id, {
        [field]: !collection[field],
      });
      setCollections((prev) => prev.map((c) => (c.id === updated.id ? { ...c, ...updated } : c)));
      if (selected?.id === updated.id) setSelected({ ...selected, ...updated });
    } catch (err) {
      toast.error(apiError(err, 'Failed to update collection'));
    }
  };

  const handleDeleteCollection = async (collection: WorkspaceCollection) => {
    if (!window.confirm(`Delete collection '${collection.name}' and all its records?`)) return;
    try {
      await workspaceDataApi.deleteCollection(projectSlug, collection.id);
      toast.success(`Collection '${collection.name}' deleted`);
      if (selected?.id === collection.id) setSelected(null);
      await loadCollections();
    } catch (err) {
      toast.error(apiError(err, 'Failed to delete collection'));
    }
  };

  const handleDeleteRecord = async (recordId: string) => {
    if (!selected) return;
    try {
      await workspaceDataApi.deleteRecord(projectSlug, selected.id, recordId);
      await loadRecords(selected, recordOffset);
      loadCollections();
    } catch (err) {
      toast.error(apiError(err, 'Failed to delete record'));
    }
  };

  const handleCreateKey = async () => {
    const name = newKeyName.trim();
    if (!name) return;
    try {
      const key = await workspaceDataApi.createKey(projectSlug, {
        name,
        kind: newKeyKind,
      });
      setCreatedKey(key.key ?? null);
      setNewKeyName('');
      setShowNewKey(false);
      await loadKeys();
    } catch (err) {
      toast.error(apiError(err, 'Failed to create key'));
    }
  };

  const handleRevokeKey = async (key: WorkspaceDataKey) => {
    if (!window.confirm(`Revoke key '${key.name}'? Apps using it will stop working.`)) return;
    try {
      await workspaceDataApi.revokeKey(projectSlug, key.id);
      toast.success('Key revoked');
      await loadKeys();
    } catch (err) {
      toast.error(apiError(err, 'Failed to revoke key'));
    }
  };

  const copy = (text: string) => {
    navigator.clipboard?.writeText(text);
    toast.success('Copied');
  };

  const tabBtn = (id: View, label: string, icon: React.ReactNode) => (
    <button
      onClick={() => setView(id)}
      className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
        view === id
          ? 'bg-[var(--primary)] text-white'
          : 'text-[var(--text-muted)] hover:bg-[var(--surface)]'
      }`}
    >
      {icon}
      {label}
    </button>
  );

  return (
    <div className="w-full h-full flex flex-col bg-[var(--bg)] overflow-hidden">
      {/* Header */}
      <div className="flex-shrink-0 flex items-center justify-between px-3 py-2 border-b border-[var(--border)]">
        <div className="flex items-center gap-1.5">
          {tabBtn('collections', 'Collections', <Database size={14} weight="bold" />)}
          {tabBtn('keys', 'API Keys', <Key size={14} weight="bold" />)}
        </div>
        <button
          onClick={() => (view === 'collections' ? loadCollections() : loadKeys())}
          className="p-1.5 rounded-md text-[var(--text-muted)] hover:bg-[var(--surface)]"
          title="Refresh"
        >
          <ArrowClockwise size={14} weight="bold" />
        </button>
      </div>

      {view === 'collections' ? (
        <div className="flex-1 overflow-auto p-3 space-y-3">
          {usage && (
            <div className="text-[11px] text-[var(--text-muted)]">
              {usage.collection_count}/{usage.max_collections} collections · {usage.record_count}/
              {usage.max_records} records
            </div>
          )}

          {/* New collection */}
          {showNewCollection ? (
            <div className="flex items-center gap-2">
              <input
                autoFocus
                value={newCollectionName}
                onChange={(e) => setNewCollectionName(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleCreateCollection()}
                placeholder="collection-name"
                className="flex-1 px-2 py-1.5 text-xs rounded-md bg-[var(--surface)] border border-[var(--border)] text-[var(--text)] outline-none focus:border-[var(--primary)]"
              />
              <button
                onClick={handleCreateCollection}
                className="px-3 py-1.5 text-xs font-medium rounded-md bg-[var(--primary)] text-white"
              >
                Create
              </button>
              <button
                onClick={() => setShowNewCollection(false)}
                className="px-2 py-1.5 text-xs text-[var(--text-muted)]"
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              onClick={() => setShowNewCollection(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md border border-dashed border-[var(--border)] text-[var(--text-muted)] hover:border-[var(--primary)] hover:text-[var(--primary)]"
            >
              <Plus size={14} weight="bold" /> New collection
            </button>
          )}

          {loading ? (
            <div className="text-xs text-[var(--text-muted)]">Loading…</div>
          ) : collections.length === 0 ? (
            <div className="text-xs text-[var(--text-muted)] py-6 text-center">
              No collections yet. Create one to start storing data — or ask the agent to do it with
              the <code>workspace_data</code> tool.
            </div>
          ) : (
            <div className="space-y-2">
              {collections.map((c) => (
                <div
                  key={c.id}
                  className="rounded-lg border border-[var(--border)] bg-[var(--surface)]"
                >
                  <div className="flex items-center justify-between px-3 py-2">
                    <button
                      onClick={() => selectCollection(c)}
                      className="flex items-center gap-2 text-left flex-1 min-w-0"
                    >
                      {selected?.id === c.id ? (
                        <CaretDown size={12} weight="bold" />
                      ) : (
                        <CaretRight size={12} weight="bold" />
                      )}
                      <span className="text-sm font-medium text-[var(--text)] truncate">
                        {c.name}
                      </span>
                      <span className="text-[10px] text-[var(--text-muted)]">
                        {c.record_count} rec
                      </span>
                    </button>
                    <div className="flex items-center gap-1">
                      {FLAG_FIELDS.map((f) => (
                        <button
                          key={f.key}
                          onClick={() => handleToggleFlag(c, f.key)}
                          title={`Public ${f.label.toLowerCase()} from deployed apps`}
                          className={`px-1.5 py-0.5 text-[9px] font-semibold rounded ${
                            c[f.key]
                              ? 'bg-[var(--primary)] text-white'
                              : 'bg-[var(--bg)] text-[var(--text-muted)] border border-[var(--border)]'
                          }`}
                        >
                          {f.label}
                        </button>
                      ))}
                      <button
                        onClick={() => handleDeleteCollection(c)}
                        className="p-1 text-[var(--text-muted)] hover:text-red-400"
                        title="Delete collection"
                      >
                        <Trash size={13} />
                      </button>
                    </div>
                  </div>

                  {/* Records */}
                  {selected?.id === c.id && (
                    <div className="border-t border-[var(--border)] p-2">
                      {recordsLoading ? (
                        <div className="text-xs text-[var(--text-muted)] p-2">Loading…</div>
                      ) : records.length === 0 ? (
                        <div className="text-xs text-[var(--text-muted)] p-2">No records.</div>
                      ) : (
                        <div className="space-y-1">
                          {records.map((r) => (
                            <div key={r.id} className="rounded bg-[var(--bg)] text-xs">
                              <div className="flex items-center gap-2 px-2 py-1.5">
                                <button
                                  onClick={() =>
                                    setExpandedRecord(expandedRecord === r.id ? null : r.id)
                                  }
                                  className="flex-1 min-w-0 text-left font-mono text-[var(--text-muted)] truncate"
                                >
                                  {JSON.stringify(r.data)}
                                </button>
                                <span className="text-[9px] text-[var(--text-muted)] flex-shrink-0">
                                  {r.created_at?.slice(0, 19).replace('T', ' ')}
                                </span>
                                <button
                                  onClick={() => handleDeleteRecord(r.id)}
                                  className="p-0.5 text-[var(--text-muted)] hover:text-red-400 flex-shrink-0"
                                  title="Delete record"
                                >
                                  <Trash size={12} />
                                </button>
                              </div>
                              {expandedRecord === r.id && (
                                <pre className="px-2 pb-2 text-[10px] text-[var(--text)] overflow-auto whitespace-pre-wrap break-all">
                                  {JSON.stringify(r.data, null, 2)}
                                </pre>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                      {recordTotal > RECORDS_PAGE_SIZE && (
                        <div className="flex items-center justify-between mt-2 text-[11px] text-[var(--text-muted)]">
                          <button
                            disabled={recordOffset === 0}
                            onClick={() => loadRecords(c, recordOffset - RECORDS_PAGE_SIZE)}
                            className="px-2 py-0.5 rounded disabled:opacity-40 hover:bg-[var(--surface)]"
                          >
                            Prev
                          </button>
                          <span>
                            {recordOffset + 1}–
                            {Math.min(recordOffset + RECORDS_PAGE_SIZE, recordTotal)} of{' '}
                            {recordTotal}
                          </span>
                          <button
                            disabled={recordOffset + RECORDS_PAGE_SIZE >= recordTotal}
                            onClick={() => loadRecords(c, recordOffset + RECORDS_PAGE_SIZE)}
                            className="px-2 py-0.5 rounded disabled:opacity-40 hover:bg-[var(--surface)]"
                          >
                            Next
                          </button>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      ) : (
        <div className="flex-1 overflow-auto p-3 space-y-3">
          {/* Endpoint hint */}
          <div className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-3 text-[11px] text-[var(--text-muted)] space-y-1">
            <div className="font-medium text-[var(--text)]">Data API endpoint</div>
            <code className="block break-all text-[var(--text)]">
              {window.location.origin}/api/data/v1/&#123;collection&#125;
            </code>
            <div>
              Send <code>Authorization: Bearer &lt;key&gt;</code>. <b>anon</b> keys obey each
              collection's public flags; <b>service</b> keys have full access (server-side only).
            </div>
            <div>
              On deploy, a fresh anon key is auto-injected into your app as{' '}
              <code>OPENSAIL_DATA_KEY</code> + <code>OPENSAIL_DATA_API_URL</code> (also under{' '}
              <code>VITE_</code> and <code>NEXT_PUBLIC_</code> prefixes).
            </div>
          </div>

          {/* Newly created key */}
          {createdKey && (
            <div className="rounded-lg border border-[var(--primary)] bg-[var(--surface)] p-3 space-y-2">
              <div className="text-xs font-medium text-[var(--text)]">
                Key created — copy it now, it won't be shown again.
              </div>
              <div className="flex items-center gap-2">
                <code className="flex-1 min-w-0 break-all text-[11px] text-[var(--primary)]">
                  {createdKey}
                </code>
                <button
                  onClick={() => copy(createdKey)}
                  className="p-1.5 rounded-md bg-[var(--primary)] text-white flex-shrink-0"
                >
                  <Copy size={13} />
                </button>
              </div>
              <button
                onClick={() => setCreatedKey(null)}
                className="text-[11px] text-[var(--text-muted)]"
              >
                Dismiss
              </button>
            </div>
          )}

          {/* New key */}
          {showNewKey ? (
            <div className="flex items-center gap-2">
              <input
                autoFocus
                value={newKeyName}
                onChange={(e) => setNewKeyName(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleCreateKey()}
                placeholder="Key name"
                className="flex-1 px-2 py-1.5 text-xs rounded-md bg-[var(--surface)] border border-[var(--border)] text-[var(--text)] outline-none focus:border-[var(--primary)]"
              />
              <select
                value={newKeyKind}
                onChange={(e) => setNewKeyKind(e.target.value)}
                className="px-2 py-1.5 text-xs rounded-md bg-[var(--surface)] border border-[var(--border)] text-[var(--text)]"
              >
                <option value="anon">anon</option>
                <option value="service">service</option>
              </select>
              <button
                onClick={handleCreateKey}
                className="px-3 py-1.5 text-xs font-medium rounded-md bg-[var(--primary)] text-white"
              >
                Create
              </button>
              <button
                onClick={() => setShowNewKey(false)}
                className="px-2 py-1.5 text-xs text-[var(--text-muted)]"
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              onClick={() => setShowNewKey(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md border border-dashed border-[var(--border)] text-[var(--text-muted)] hover:border-[var(--primary)] hover:text-[var(--primary)]"
            >
              <Plus size={14} weight="bold" /> New API key
            </button>
          )}

          {keys.length === 0 ? (
            <div className="text-xs text-[var(--text-muted)] py-6 text-center">
              No API keys yet.
            </div>
          ) : (
            <div className="space-y-2">
              {keys.map((k) => (
                <div
                  key={k.id}
                  className="flex items-center justify-between rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2"
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-[var(--text)] truncate">
                        {k.name}
                      </span>
                      <span
                        className={`px-1.5 py-0.5 text-[9px] font-semibold rounded ${
                          k.kind === 'service'
                            ? 'bg-amber-500/20 text-amber-500'
                            : 'bg-[var(--primary)]/20 text-[var(--primary)]'
                        }`}
                      >
                        {k.kind}
                      </span>
                    </div>
                    <code className="text-[10px] text-[var(--text-muted)]">{k.key_prefix}…</code>
                  </div>
                  <button
                    onClick={() => handleRevokeKey(k)}
                    className="p-1 text-[var(--text-muted)] hover:text-red-400"
                    title="Revoke key"
                  >
                    <Trash size={13} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
