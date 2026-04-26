import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import toast from 'react-hot-toast';
import { ArrowLeft, Play, Trash, PencilSimple, Check, X } from '@phosphor-icons/react';
import { automationsApi } from '../../lib/api';
import type {
  AutomationDefinitionOut,
  AutomationRunSummary,
} from '../../types/automations';
import { ConfirmDialog } from '../../components/modals/ConfirmDialog';
import { RunStatusBadge } from './components/RunStatusBadge';
import { ContractEditor } from './components/ContractEditor';
import { DestinationPicker } from './components/DestinationPicker';
import type { AutomationDeliveryTargetIn } from '../../types/automations';

const PAGE_SIZE = 25;

/**
 * /automations/:id — view + light edit + run history.
 *
 * "Edit" mode toggles a flat form for name + contract + active flag.
 * For trigger / action editing we send the user back to a fresh create
 * (Phase 1 keeps the patch surface minimal — Phase 5 builds a full
 * inline editor).
 */
export default function AutomationDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [definition, setDefinition] = useState<AutomationDefinitionOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [runs, setRuns] = useState<AutomationRunSummary[] | null>(null);
  const [runOffset, setRunOffset] = useState(0);
  const [runHasMore, setRunHasMore] = useState(false);

  const [running, setRunning] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const [editing, setEditing] = useState(false);
  const [editName, setEditName] = useState('');
  const [editContract, setEditContract] = useState('');
  const [editActive, setEditActive] = useState(true);
  /**
   * Phase 4: edit a single delivery destination via the picker. The
   * form only supports one delivery target per automation today (matches
   * the create flow). Empty string = "no delivery target".
   */
  const [editDeliveryDestinationId, setEditDeliveryDestinationId] = useState('');
  const [savingEdit, setSavingEdit] = useState(false);

  const reload = useCallback(async () => {
    if (!id) return;
    setError(null);
    try {
      const def = await automationsApi.get(id);
      setDefinition(def);
      setEditName(def.name);
      setEditContract(JSON.stringify(def.contract ?? {}, null, 2));
      setEditActive(def.is_active);
      setEditDeliveryDestinationId(def.delivery_targets[0]?.destination_id ?? '');
    } catch (err) {
      setError(
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail ||
          'Failed to load automation'
      );
    }
  }, [id]);

  const loadRuns = useCallback(
    async (offset: number) => {
      if (!id) return;
      try {
        const list = await automationsApi.listRuns(id, { limit: PAGE_SIZE, offset });
        setRuns((prev) => (offset === 0 ? list : [...(prev ?? []), ...list]));
        setRunHasMore(list.length === PAGE_SIZE);
        setRunOffset(offset + list.length);
      } catch (err) {
        toast.error(
          (err as { response?: { data?: { detail?: string } } }).response?.data?.detail ||
            'Failed to load runs'
        );
      }
    },
    [id]
  );

  useEffect(() => {
    reload();
  }, [reload]);

  useEffect(() => {
    setRuns(null);
    setRunOffset(0);
    setRunHasMore(false);
    loadRuns(0);
  }, [loadRuns]);

  const handleRunNow = async () => {
    if (!id) return;
    setRunning(true);
    try {
      const res = await automationsApi.run(id);
      toast.success('Run queued');
      navigate(`/automations/${id}/runs/${res.run_id}`);
    } catch (err) {
      toast.error(
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail ||
          'Failed to queue run'
      );
    } finally {
      setRunning(false);
    }
  };

  const handleDelete = async () => {
    if (!id) return;
    setDeleting(true);
    try {
      await automationsApi.remove(id, false);
      toast.success('Automation deleted');
      setConfirmDelete(false);
      navigate('/automations');
    } catch (err) {
      toast.error(
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail ||
          'Failed to delete'
      );
    } finally {
      setDeleting(false);
    }
  };

  const handleSaveEdit = async () => {
    if (!id) return;
    let contract: Record<string, unknown>;
    try {
      contract = JSON.parse(editContract);
      if (typeof contract !== 'object' || contract === null || Array.isArray(contract)) {
        throw new Error('Contract must be a JSON object.');
      }
    } catch (err) {
      toast.error(`Invalid contract: ${err instanceof Error ? err.message : String(err)}`);
      return;
    }
    const deliveryTargets: AutomationDeliveryTargetIn[] = editDeliveryDestinationId.trim()
      ? [
          {
            destination_id: editDeliveryDestinationId.trim(),
            ordinal: 0,
            on_failure: {},
            artifact_filter: 'all',
          },
        ]
      : [];

    setSavingEdit(true);
    try {
      const updated = await automationsApi.update(id, {
        name: editName.trim(),
        contract,
        is_active: editActive,
        delivery_targets: deliveryTargets,
      });
      setDefinition(updated);
      setEditing(false);
      toast.success('Automation updated');
    } catch (err) {
      toast.error(
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail ||
          'Failed to update'
      );
    } finally {
      setSavingEdit(false);
    }
  };

  if (error) {
    return (
      <div className="p-8">
        <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-4 text-sm text-[var(--status-error)]">
          {error}
        </div>
      </div>
    );
  }

  if (!definition) {
    return <div className="p-8 text-sm text-[var(--text-muted)]">Loading automation…</div>;
  }

  const trig = definition.triggers[0];
  const action = definition.actions[0];

  return (
    <>
      {/* Header */}
      <div className="flex-shrink-0">
        <div
          className="h-10 flex items-center gap-2"
          style={{
            paddingLeft: '11px',
            paddingRight: '11px',
            borderBottom: 'var(--border-width) solid var(--border)',
          }}
        >
          <button
            onClick={() => navigate('/automations')}
            className="btn btn-icon btn-sm"
            aria-label="Back to automations"
          >
            <ArrowLeft className="w-3 h-3" />
          </button>
          <h2 className="text-xs font-semibold text-[var(--text)] flex-1 truncate">
            {definition.name}
          </h2>
          <button
            onClick={handleRunNow}
            disabled={running || !definition.is_active}
            className="btn btn-sm btn-filled"
            title={definition.is_active ? 'Run now' : 'Automation is paused'}
          >
            <Play className="w-3 h-3" weight="fill" />
            {running ? 'Queuing…' : 'Run now'}
          </button>
          {!editing ? (
            <button
              onClick={() => setEditing(true)}
              className="btn btn-sm btn-icon"
              aria-label="Edit"
            >
              <PencilSimple className="w-3 h-3" />
            </button>
          ) : (
            <>
              <button
                onClick={handleSaveEdit}
                disabled={savingEdit}
                className="btn btn-sm btn-filled"
              >
                <Check className="w-3 h-3" />
                {savingEdit ? 'Saving…' : 'Save'}
              </button>
              <button
                onClick={() => {
                  setEditing(false);
                  setEditName(definition.name);
                  setEditContract(JSON.stringify(definition.contract ?? {}, null, 2));
                  setEditActive(definition.is_active);
                  setEditDeliveryDestinationId(
                    definition.delivery_targets[0]?.destination_id ?? ''
                  );
                }}
                disabled={savingEdit}
                className="btn btn-sm btn-icon"
                aria-label="Cancel edit"
              >
                <X className="w-3 h-3" />
              </button>
            </>
          )}
          <button
            onClick={() => setConfirmDelete(true)}
            className="btn btn-sm btn-icon"
            aria-label="Delete"
            title="Delete"
          >
            <Trash className="w-3 h-3" />
          </button>
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-6 py-6 space-y-6">
          {/* Definition summary / edit */}
          <section className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-4 space-y-3">
            <header className="flex items-center justify-between">
              <h3 className="text-xs font-semibold text-[var(--text)]">Definition</h3>
              <span className="text-[10px] uppercase tracking-wider text-[var(--text-subtle)]">
                ID {definition.id.slice(0, 8)}…
              </span>
            </header>

            {editing ? (
              <div className="space-y-3">
                <label className="block">
                  <span className="block text-xs font-medium text-[var(--text)] mb-1">Name</span>
                  <input
                    type="text"
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                    className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)]"
                  />
                </label>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={editActive}
                    onChange={(e) => setEditActive(e.target.checked)}
                  />
                  <span className="text-xs text-[var(--text)]">Active</span>
                  <span className="text-[10px] text-[var(--text-subtle)]">
                    Uncheck to pause this automation.
                  </span>
                </label>
                <ContractEditor value={editContract} onChange={setEditContract} />
                <div>
                  <span className="block text-xs font-medium text-[var(--text)] mb-1">
                    Delivery destination
                  </span>
                  <DestinationPicker
                    value={editDeliveryDestinationId}
                    onChange={setEditDeliveryDestinationId}
                    placeholder="No delivery target"
                  />
                </div>
                <p className="text-[10px] text-[var(--text-subtle)]">
                  Edits cover name + contract + active flag + delivery destination.
                  To change the trigger or action, recreate the automation.
                </p>
              </div>
            ) : (
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
                <div>
                  <dt className="text-[10px] uppercase tracking-wider text-[var(--text-subtle)]">
                    Status
                  </dt>
                  <dd>
                    <span
                      className={`inline-flex items-center rounded-[var(--radius-small)] px-1.5 py-0.5 text-[10px] uppercase tracking-wider ${
                        definition.is_active
                          ? 'bg-emerald-500/15 text-emerald-400'
                          : 'bg-[var(--surface-hover)] text-[var(--text-subtle)]'
                      }`}
                    >
                      {definition.is_active ? 'Active' : 'Paused'}
                    </span>
                    {definition.paused_reason && (
                      <span className="ml-2 text-[10px] text-[var(--text-subtle)]">
                        {definition.paused_reason}
                      </span>
                    )}
                  </dd>
                </div>
                <div>
                  <dt className="text-[10px] uppercase tracking-wider text-[var(--text-subtle)]">
                    Workspace scope
                  </dt>
                  <dd className="text-[var(--text)]">{definition.workspace_scope}</dd>
                </div>
                <div>
                  <dt className="text-[10px] uppercase tracking-wider text-[var(--text-subtle)]">
                    Trigger
                  </dt>
                  <dd className="text-[var(--text)]">
                    {trig
                      ? `${trig.kind}${
                          trig.kind === 'cron' && trig.config.expression
                            ? ` · ${String(trig.config.expression)}`
                            : ''
                        }`
                      : '—'}
                  </dd>
                </div>
                <div>
                  <dt className="text-[10px] uppercase tracking-wider text-[var(--text-subtle)]">
                    Action
                  </dt>
                  <dd className="text-[var(--text)]">{action ? action.action_type : '—'}</dd>
                </div>
                <div>
                  <dt className="text-[10px] uppercase tracking-wider text-[var(--text-subtle)]">
                    Compute tier
                  </dt>
                  <dd className="text-[var(--text)] tabular-nums">
                    {definition.max_compute_tier}
                  </dd>
                </div>
                <div>
                  <dt className="text-[10px] uppercase tracking-wider text-[var(--text-subtle)]">
                    Spend caps
                  </dt>
                  <dd className="text-[var(--text)] tabular-nums">
                    {fmtCap(definition.max_spend_per_run_usd)} / run ·{' '}
                    {fmtCap(definition.max_spend_per_day_usd)} / day
                  </dd>
                </div>
                <div className="col-span-2">
                  <dt className="text-[10px] uppercase tracking-wider text-[var(--text-subtle)]">
                    Delivery targets
                  </dt>
                  <dd className="text-[var(--text-muted)] text-[11px]">
                    {definition.delivery_targets.length === 0
                      ? '— (none configured)'
                      : definition.delivery_targets
                          .map((t) => t.destination_id.slice(0, 8) + '…')
                          .join(', ')}
                  </dd>
                </div>
                <div className="col-span-2">
                  <dt className="text-[10px] uppercase tracking-wider text-[var(--text-subtle)]">
                    Contract
                  </dt>
                  <dd>
                    <pre className="mt-1 max-h-48 overflow-auto rounded-[var(--radius-small)] border border-[var(--border)] bg-[var(--bg)] px-2 py-1.5 text-[11px] font-mono text-[var(--text-muted)]">
                      {JSON.stringify(definition.contract, null, 2)}
                    </pre>
                  </dd>
                </div>
              </dl>
            )}
          </section>

          {/* Run history */}
          <section className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] overflow-hidden">
            <header className="flex items-center justify-between px-4 py-3 border-b border-[var(--border)]">
              <h3 className="text-xs font-semibold text-[var(--text)]">Run history</h3>
              <span className="text-[10px] text-[var(--text-subtle)] tabular-nums">
                {runs?.length ?? 0} loaded
              </span>
            </header>
            {runs === null ? (
              <div className="px-4 py-6 text-xs text-[var(--text-muted)]">
                Loading runs…
              </div>
            ) : runs.length === 0 ? (
              <div className="px-4 py-6 text-xs text-[var(--text-muted)]">
                No runs yet. Click "Run now" to trigger one manually.
              </div>
            ) : (
              <table className="w-full text-xs">
                <thead className="bg-[var(--surface-hover)] text-[10px] uppercase tracking-wider text-[var(--text-subtle)]">
                  <tr>
                    <th className="text-left px-3 py-2 font-medium">Status</th>
                    <th className="text-left px-3 py-2 font-medium">Started</th>
                    <th className="text-left px-3 py-2 font-medium">Ended</th>
                    <th className="text-left px-3 py-2 font-medium">Duration</th>
                    <th className="text-left px-3 py-2 font-medium">Spend</th>
                    <th className="text-left px-3 py-2 font-medium">Breaches</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((run) => (
                    <tr
                      key={run.id}
                      className="border-t border-[var(--border)] hover:bg-[var(--surface-hover)] cursor-pointer"
                      onClick={() => navigate(`/automations/${id}/runs/${run.id}`)}
                    >
                      <td className="px-3 py-2">
                        <RunStatusBadge status={run.status} />
                      </td>
                      <td className="px-3 py-2 text-[var(--text-muted)] tabular-nums">
                        {formatDate(run.started_at)}
                      </td>
                      <td className="px-3 py-2 text-[var(--text-muted)] tabular-nums">
                        {formatDate(run.ended_at)}
                      </td>
                      <td className="px-3 py-2 text-[var(--text-muted)] tabular-nums">
                        {formatDuration(run.started_at, run.ended_at)}
                      </td>
                      <td className="px-3 py-2 text-[var(--text-muted)] tabular-nums">
                        ${run.spend_usd}
                      </td>
                      <td className="px-3 py-2 text-[var(--text-muted)] tabular-nums">
                        {run.contract_breaches}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {runHasMore && (
              <div className="border-t border-[var(--border)] px-4 py-2 text-center">
                <button
                  onClick={() => loadRuns(runOffset)}
                  className="btn btn-sm"
                  disabled={runs === null}
                >
                  Load more
                </button>
              </div>
            )}
          </section>
        </div>
      </div>

      <ConfirmDialog
        isOpen={confirmDelete}
        onClose={() => (!deleting ? setConfirmDelete(false) : undefined)}
        onConfirm={handleDelete}
        title="Delete automation?"
        message={
          <span>
            Soft-delete <strong>{definition.name}</strong>? The definition will be
            paused and hidden from new runs. Existing run history is preserved.
          </span>
        }
        confirmText="Delete"
        variant="danger"
        isLoading={deleting}
      />
    </>
  );
}

function fmtCap(value: string | null): string {
  if (value === null || value === undefined || value === '') return '—';
  return `$${value}`;
}

function formatDate(value: string | null): string {
  if (!value) return '—';
  try {
    return new Intl.DateTimeFormat(undefined, {
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    }).format(new Date(value));
  } catch {
    return value;
  }
}

function formatDuration(started: string | null, ended: string | null): string {
  if (!started) return '—';
  const start = Date.parse(started);
  const end = ended ? Date.parse(ended) : Date.now();
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return '—';
  const ms = end - start;
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const m = Math.floor(ms / 60_000);
  const s = Math.floor((ms % 60_000) / 1000);
  return `${m}m ${s}s`;
}
