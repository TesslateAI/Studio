/**
 * DataPanel — the project's built-in Workspace Data Store.
 *
 * A per-project KV/document database (plain rows in the platform DB — no
 * pods, no lifecycle). Two views: Collections (browse/manage data) and API
 * Keys (anon/service keys for deployed frontends to read/write the store).
 * Available on every project, including empty workspaces.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import toast from 'react-hot-toast';
import Editor from '@monaco-editor/react';
import {
  ArrowClockwise,
  BracketsCurly,
  CaretDown,
  CaretRight,
  Copy,
  Database,
  Key,
  Plus,
  Robot,
  Trash,
} from '@phosphor-icons/react';
import {
  workspaceDataApi,
  type WorkspaceCollection,
  type WorkspaceDataKey,
  type WorkspaceDataUsage,
  type WorkspaceRecord,
} from '../../lib/api';
import type { ChatMention } from '../../types/agent';

interface DataPanelProps {
  projectSlug: string;
  /**
   * Drop a pre-canned prompt into the chat input. Called by the per-row
   * and panel-level "Ask agent" affordances. Optional — when absent, the
   * Ask-agent buttons are hidden so the panel still renders standalone.
   *
   * ``mentions`` rides alongside the prose so the backend receives a
   * structured ``{kind:'data', ref_id:<collection>}`` entry and doesn't
   * have to re-parse the slug out of the message. The host page
   * (ProjectPage) seeds both into ChatInput via its prefill channel.
   */
  onAskAgent?: (message: string, mentions?: ChatMention[]) => void;
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

// Starter schemas surfaced as a one-click dropdown in the editor. Each is a
// real, valid JSON Schema (Draft 2020-12) — additionalProperties:false on
// the form variants so spam fields are rejected at the API boundary, not
// silently accepted into the deployed app's records.
const SCHEMA_TEMPLATES: Record<string, Record<string, unknown>> = {
  'Contact form (email + message)': {
    type: 'object',
    required: ['email', 'message'],
    properties: {
      email: { type: 'string', format: 'email', maxLength: 254 },
      message: { type: 'string', minLength: 1, maxLength: 2000 },
    },
    additionalProperties: false,
  },
  'Named record (string name + optional notes)': {
    type: 'object',
    required: ['name'],
    properties: {
      name: { type: 'string', minLength: 1, maxLength: 200 },
      notes: { type: 'string', maxLength: 5000 },
    },
    additionalProperties: false,
  },
  'Todo item': {
    type: 'object',
    required: ['title'],
    properties: {
      title: { type: 'string', minLength: 1, maxLength: 200 },
      done: { type: 'boolean' },
      due: { type: 'string', format: 'date-time' },
    },
    additionalProperties: false,
  },
  'Open object (any well-formed payload)': {
    type: 'object',
    additionalProperties: true,
  },
};

interface SchemaEditorModalProps {
  projectSlug: string;
  collection: WorkspaceCollection;
  onClose: () => void;
  onSaved: (updated: WorkspaceCollection) => void;
}

/**
 * SchemaEditorModal — set / clear the per-collection JSON Schema.
 *
 * Monaco for the editor (already in the bundle). Local JSON-syntax parse
 * gates the Save button so we never POST malformed JSON; the server then
 * validates the parsed object as a Draft 2020-12 schema and returns 400
 * with the metaschema diagnostic on failure (surfaced inline).
 */
function SchemaEditorModal({ projectSlug, collection, onClose, onSaved }: SchemaEditorModalProps) {
  const initial = useMemo(
    () => (collection.schema ? JSON.stringify(collection.schema, null, 2) : '{\n  \n}'),
    [collection.schema]
  );
  const [text, setText] = useState(initial);
  const [saving, setSaving] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const hadSchema = collection.schema !== null && collection.schema !== undefined;

  // Tri-state: { ok: true } => parseable JSON object; { ok: false, msg } => bad JSON.
  const parseState = useMemo(() => {
    const trimmed = text.trim();
    if (!trimmed || trimmed === '{}') return { ok: true as const, empty: true, value: null };
    try {
      const value = JSON.parse(trimmed);
      if (value === null || typeof value !== 'object' || Array.isArray(value)) {
        return { ok: false as const, msg: 'Schema must be a JSON object.' };
      }
      return { ok: true as const, empty: false, value };
    } catch (err) {
      return { ok: false as const, msg: (err as Error).message };
    }
  }, [text]);

  const applyTemplate = (key: string) => {
    const tmpl = SCHEMA_TEMPLATES[key];
    if (tmpl) setText(JSON.stringify(tmpl, null, 2));
  };

  const handleSave = async () => {
    if (!parseState.ok) return;
    setServerError(null);
    setSaving(true);
    try {
      const body = parseState.empty
        ? { schema: null }
        : { schema: parseState.value as Record<string, unknown> };
      const updated = await workspaceDataApi.updateCollection(projectSlug, collection.id, body);
      toast.success(parseState.empty ? 'Schema cleared' : 'Schema saved');
      onSaved(updated);
      onClose();
    } catch (err) {
      setServerError(apiError(err, 'Failed to save schema'));
    } finally {
      setSaving(false);
    }
  };

  const handleClear = async () => {
    if (
      !window.confirm(
        `Clear schema for '${collection.name}'? Subsequent inserts will accept any well-formed object.`
      )
    ) {
      return;
    }
    setServerError(null);
    setSaving(true);
    try {
      const updated = await workspaceDataApi.updateCollection(projectSlug, collection.id, {
        schema: null,
      });
      toast.success('Schema cleared');
      onSaved(updated);
      onClose();
    } catch (err) {
      setServerError(apiError(err, 'Failed to clear schema'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      role="dialog"
      aria-modal="true"
      aria-label={`Edit schema for ${collection.name}`}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-full max-w-3xl rounded-xl bg-[var(--surface)] border border-[var(--border)] shadow-2xl flex flex-col max-h-[85vh]">
        <div className="flex items-center justify-between px-5 py-3 border-b border-[var(--border)]">
          <div>
            <div className="text-sm font-semibold text-[var(--text)] flex items-center gap-2">
              <BracketsCurly size={14} weight="bold" />
              Schema · <span className="font-mono">{collection.name}</span>
            </div>
            <div className="text-[11px] text-[var(--text-muted)] mt-0.5">
              {hadSchema
                ? 'Every insert/update is validated against this schema. Bad payloads return 422 with the offending field path.'
                : 'No schema set — any well-formed JSON object is accepted. Define one to enforce shape (e.g. block spam fields).'}
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-xs text-[var(--text-muted)] hover:text-[var(--text)] px-2 py-1"
          >
            Close
          </button>
        </div>

        <div className="flex items-center gap-2 px-5 py-2 border-b border-[var(--border)] text-[11px]">
          <span className="text-[var(--text-muted)]">Templates:</span>
          <select
            defaultValue=""
            onChange={(e) => {
              if (e.target.value) {
                applyTemplate(e.target.value);
                e.target.value = '';
              }
            }}
            className="bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded px-2 py-1 text-[11px] outline-none focus:border-[var(--primary)]"
          >
            <option value="">Insert template…</option>
            {Object.keys(SCHEMA_TEMPLATES).map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
          <a
            href="https://json-schema.org/learn/getting-started-step-by-step"
            target="_blank"
            rel="noreferrer"
            className="ml-auto text-[var(--text-muted)] hover:text-[var(--primary)]"
          >
            JSON Schema docs ↗
          </a>
        </div>

        <div className="h-[380px] border-b border-[var(--border)]">
          <Editor
            defaultLanguage="json"
            value={text}
            onChange={(v) => setText(v ?? '')}
            theme="vs-dark"
            options={{
              minimap: { enabled: false },
              fontSize: 12,
              lineNumbers: 'on',
              scrollBeyondLastLine: false,
              wordWrap: 'on',
              automaticLayout: true,
            }}
          />
        </div>

        {(!parseState.ok || serverError) && (
          <div className="px-5 py-2 text-[11px] text-red-400 bg-red-950/30 border-b border-red-900/40">
            {!parseState.ok ? `JSON parse error: ${parseState.msg}` : serverError}
          </div>
        )}

        <div className="flex items-center justify-between px-5 py-3 gap-2">
          <div className="text-[10px] text-[var(--text-muted)]">
            {parseState.ok &&
              !parseState.empty &&
              '✓ Valid JSON — server will validate as a Draft 2020-12 schema on save.'}
            {parseState.ok &&
              parseState.empty &&
              'Empty schema — saving will clear any existing schema.'}
          </div>
          <div className="flex items-center gap-2">
            {hadSchema && (
              <button
                onClick={handleClear}
                disabled={saving}
                className="px-3 py-1.5 text-xs text-red-400 hover:bg-red-950/30 rounded disabled:opacity-40"
              >
                Clear schema
              </button>
            )}
            <button
              onClick={onClose}
              disabled={saving}
              className="px-3 py-1.5 text-xs text-[var(--text-muted)] hover:bg-[var(--bg)] rounded disabled:opacity-40"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={!parseState.ok || saving}
              className="px-3 py-1.5 text-xs font-medium rounded-md bg-[var(--primary)] text-white disabled:opacity-40"
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export function DataPanel({ projectSlug, onAskAgent }: DataPanelProps) {
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

  // The collection whose schema is currently being edited. Null = modal closed.
  const [schemaEditing, setSchemaEditing] = useState<WorkspaceCollection | null>(null);

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
        <div className="flex items-center gap-1">
          {onAskAgent && view === 'collections' && (
            <button
              onClick={() => {
                if (collections.length === 0) {
                  onAskAgent(
                    'I want to use the workspace data store for this project. ' +
                      'Walk me through what collections we should create for the use case in this chat, ' +
                      'then create them with the workspace_data tool.'
                  );
                } else {
                  // The "*" data mention says "every collection in this project"
                  // — backend treats it as a wildcard in build_mention_data_context.
                  onAskAgent(
                    'Give me an overview of @* — what collections exist, ' +
                      'how many records each, and the dominant fields. ' +
                      'Use the workspace_data summarize action for each collection ' +
                      'and quote the bounded scope.',
                    [{ kind: 'data', ref_id: '*', display: '@*', offset: 0 }]
                  );
                }
              }}
              className="flex items-center gap-1 px-2 py-1 rounded-md text-[11px] text-[var(--text-muted)] hover:text-[var(--primary)] hover:bg-[var(--surface)]"
              title="Ask the agent about this data"
            >
              <Robot size={13} weight="bold" /> Ask agent
            </button>
          )}
          <button
            onClick={() => (view === 'collections' ? loadCollections() : loadKeys())}
            className="p-1.5 rounded-md text-[var(--text-muted)] hover:bg-[var(--surface)]"
            title="Refresh"
          >
            <ArrowClockwise size={14} weight="bold" />
          </button>
        </div>
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
                        onClick={() => setSchemaEditing(c)}
                        title={
                          c.schema
                            ? 'Edit JSON Schema (currently enforced — payloads are validated)'
                            : 'Add a JSON Schema to enforce record shape'
                        }
                        className={`p-1 rounded transition-colors ${
                          c.schema
                            ? 'text-[var(--primary)] hover:bg-[var(--bg)]'
                            : 'text-[var(--text-muted)] hover:text-[var(--primary)]'
                        }`}
                      >
                        <BracketsCurly size={13} weight={c.schema ? 'fill' : 'bold'} />
                      </button>
                      {onAskAgent && (
                        <button
                          onClick={() =>
                            onAskAgent(
                              `Summarize @${c.name} — total records, ` +
                                `inferred field types, and the most common values for the top field. ` +
                                `Use the workspace_data tool's summarize + schema actions; quote the bounded scope.`,
                              [
                                {
                                  kind: 'data',
                                  ref_id: c.name,
                                  display: `@${c.name}`,
                                  offset: 0,
                                },
                              ]
                            )
                          }
                          className="p-1 text-[var(--text-muted)] hover:text-[var(--primary)]"
                          title="Ask the agent to summarize this collection"
                        >
                          <Robot size={13} weight="bold" />
                        </button>
                      )}
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

      {schemaEditing && (
        <SchemaEditorModal
          projectSlug={projectSlug}
          collection={schemaEditing}
          onClose={() => setSchemaEditing(null)}
          onSaved={(updated) => {
            // Reflect the schema change in both the list and the open record-browse pane.
            setCollections((prev) =>
              prev.map((c) => (c.id === updated.id ? { ...c, ...updated } : c))
            );
            if (selected?.id === updated.id) setSelected({ ...selected, ...updated });
          }}
        />
      )}
    </div>
  );
}
