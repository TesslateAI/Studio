import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import toast from 'react-hot-toast';
import {
  ArrowLeft,
  Play,
  Trash,
  PencilSimple,
  Check,
  X,
  Info,
  MagnifyingGlass,
} from '@phosphor-icons/react';
import { automationsApi, communicationDestinationsApi, marketplaceApi } from '../../lib/api';
import type {
  AutomationDefinitionOut,
  AutomationRunStatus,
  AutomationRunSummary,
  CommunicationDestination,
} from '../../types/automations';
import { ConfirmDialog } from '../../components/modals/ConfirmDialog';
import { RunStatusBadge } from './components/RunStatusBadge';
import { ContractEditor } from './components/ContractEditor';
import { DestinationPicker } from './components/DestinationPicker';
import type { AutomationDeliveryTargetIn } from '../../types/automations';
import {
  humanizeActionType,
  humanizeCron,
  humanizeDestinationKind,
  humanizeRunStatus,
  humanizeTriggerKind,
  humanizeWorkspaceScope,
} from './utils/humanize';

const PAGE_SIZE = 25;

/** Status filter options surfaced in the run-history dropdown. */
const STATUS_FILTERS: Array<{ value: 'all' | AutomationRunStatus; label: string }> = [
  { value: 'all', label: 'All statuses' },
  { value: 'queued', label: humanizeRunStatus('queued') },
  { value: 'running', label: humanizeRunStatus('running') },
  { value: 'succeeded', label: humanizeRunStatus('succeeded') },
  { value: 'failed', label: humanizeRunStatus('failed') },
  { value: 'expired', label: humanizeRunStatus('expired') },
  { value: 'awaiting_approval', label: humanizeRunStatus('awaiting_approval') },
  { value: 'cancelled', label: humanizeRunStatus('cancelled') },
];

/** Date range presets for cost rollups + filter bar. */
type DateRange = '24h' | '7d' | '30d' | 'custom';

const RANGE_LABEL: Record<DateRange, string> = {
  '24h': 'Last 24h',
  '7d': 'Last 7d',
  '30d': 'Last 30d',
  custom: 'Custom',
};

/** Window expressed as inclusive [from, to] timestamps in ms. */
interface DateWindow {
  from: number;
  to: number;
}

function rangeToWindow(range: DateRange, customFrom: string, customTo: string): DateWindow | null {
  const now = Date.now();
  if (range === '24h') return { from: now - 24 * 60 * 60 * 1000, to: now };
  if (range === '7d') return { from: now - 7 * 24 * 60 * 60 * 1000, to: now };
  if (range === '30d') return { from: now - 30 * 24 * 60 * 60 * 1000, to: now };
  // Custom — empty inputs collapse to "no bound" rather than NaN.
  const from = customFrom ? Date.parse(customFrom) : -Infinity;
  const to = customTo ? Date.parse(customTo) : Infinity;
  if (Number.isNaN(from) || Number.isNaN(to)) return null;
  return { from, to };
}

/** Sum spend_usd for runs whose created_at falls inside ``window``. */
function sumSpendInWindow(runs: AutomationRunSummary[], window: DateWindow): number {
  let total = 0;
  for (const r of runs) {
    const ts = Date.parse(r.created_at);
    if (!Number.isFinite(ts)) continue;
    if (ts < window.from || ts > window.to) continue;
    const v = parseFloat(r.spend_usd);
    if (Number.isFinite(v)) total += v;
  }
  return total;
}

/**
 * /automations/:id — view + light edit + run history.
 *
 * "Edit" mode toggles a flat form for name + contract + active flag.
 * Trigger / action edits go through a fresh create until the inline
 * editor lands.
 */
export default function AutomationDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [definition, setDefinition] = useState<AutomationDefinitionOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [runs, setRuns] = useState<AutomationRunSummary[] | null>(null);
  const [runOffset, setRunOffset] = useState(0);
  const [runHasMore, setRunHasMore] = useState(false);

  // ---- Filter state (status + date range + search) ----
  const [statusFilter, setStatusFilter] = useState<'all' | AutomationRunStatus>('all');
  const [dateRange, setDateRange] = useState<DateRange>('7d');
  const [customFrom, setCustomFrom] = useState('');
  const [customTo, setCustomTo] = useState('');
  const [searchQuery, setSearchQuery] = useState('');

  const [running, setRunning] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const [editing, setEditing] = useState(false);
  const [editName, setEditName] = useState('');
  const [editContract, setEditContract] = useState('');
  const [editActive, setEditActive] = useState(true);
  /**
   * The form only supports one delivery target per automation today
   * (matches the create flow). Empty string = "no delivery target".
   */
  const [editDeliveryDestinationId, setEditDeliveryDestinationId] = useState('');
  const [savingEdit, setSavingEdit] = useState(false);

  // Resolve agent_id and destination_id to human names so the read view
  // can render "Run 'News Brief' agent · Send to #standup" instead of UUIDs.
  const [agentNames, setAgentNames] = useState<Record<string, string>>({});
  const [destinations, setDestinations] = useState<CommunicationDestination[]>([]);
  const [showRawContract, setShowRawContract] = useState(false);

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
        const params: { limit: number; offset: number; status?: string } = {
          limit: PAGE_SIZE,
          offset,
        };
        if (statusFilter !== 'all') params.status = statusFilter;
        const list = await automationsApi.listRuns(id, params);
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
    [id, statusFilter]
  );

  useEffect(() => {
    reload();
  }, [reload]);

  // Fetch agent + destination directories once so the read view can show
  // names instead of UUIDs. Failures degrade silently to the generic label.
  useEffect(() => {
    let cancelled = false;
    marketplaceApi
      .getMyAgents()
      .then((data) => {
        if (cancelled) return;
        const list = (data?.agents ?? data?.items ?? data ?? []) as Array<{
          id: string;
          name?: string;
          slug?: string;
        }>;
        const map: Record<string, string> = {};
        for (const a of list) map[String(a.id)] = a.name ?? a.slug ?? String(a.id);
        setAgentNames(map);
      })
      .catch(() => {});
    communicationDestinationsApi
      .list()
      .then((data) => {
        if (!cancelled) setDestinations(data);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  // Refetch from offset 0 whenever the server-side filter (status) changes
  // OR the automation id changes. Date-range and search are applied
  // client-side below — they don't trigger a refetch.
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

  // ---- Cost rollups (always client-side; sums what's currently loaded) ----
  // We compute the three rollup windows from whatever runs have been loaded;
  // a tooltip on the card surfaces the "from loaded runs" caveat when the
  // server still has more rows to paginate through.
  const rollups = useMemo(() => {
    const list = runs ?? [];
    const now = Date.now();
    return {
      h24: sumSpendInWindow(list, { from: now - 24 * 60 * 60 * 1000, to: now }),
      d7: sumSpendInWindow(list, { from: now - 7 * 24 * 60 * 60 * 1000, to: now }),
      d30: sumSpendInWindow(list, { from: now - 30 * 24 * 60 * 60 * 1000, to: now }),
    };
  }, [runs]);

  // Apply client-side date + search filters on top of the server-fetched
  // status-filtered list. Search matches the run id prefix or the parent
  // automation name (case-insensitive).
  const filteredRuns = useMemo(() => {
    if (runs === null) return null;
    const window = rangeToWindow(dateRange, customFrom, customTo);
    const q = searchQuery.trim().toLowerCase();
    const nameMatch = q && definition?.name?.toLowerCase().includes(q);
    return runs.filter((r) => {
      if (window) {
        const ts = Date.parse(r.created_at);
        if (Number.isFinite(ts) && (ts < window.from || ts > window.to)) return false;
      }
      if (q && !nameMatch) {
        if (!r.id.toLowerCase().startsWith(q)) return false;
      }
      return true;
    });
  }, [runs, dateRange, customFrom, customTo, searchQuery, definition?.name]);

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
              <h3 className="text-xs font-semibold text-[var(--text)]">How this works</h3>
              <span
                className="text-[10px] uppercase tracking-wider text-[var(--text-subtle)] font-mono"
                title={definition.id}
              >
                {definition.id.slice(0, 8)}
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
                  You can change the name, permissions, active flag, and where results are sent. To
                  change the schedule or what it does, build a new automation.
                </p>
              </div>
            ) : (
              <div className="space-y-3 text-xs">
                {/* Plain-English story line */}
                <p
                  className="text-[var(--text-muted)] leading-relaxed"
                  data-testid="automation-story"
                >
                  <span className="text-[var(--text)] font-medium">
                    {trig ? describeTrigger(trig.kind, trig.config) : 'No schedule set'}
                  </span>{' '}
                  <span className="text-[var(--text-subtle)]">→</span>{' '}
                  <span className="text-[var(--text)] font-medium">
                    {action
                      ? describeAction(action.action_type, action.config, agentNames)
                      : 'No action configured'}
                  </span>
                  {definition.delivery_targets.length > 0 && (
                    <>
                      {' '}
                      <span className="text-[var(--text-subtle)]">→</span>{' '}
                      <span className="text-[var(--text)] font-medium">
                        {describeDeliveryTargets(definition.delivery_targets, destinations)}
                      </span>
                    </>
                  )}
                </p>

                <dl className="grid grid-cols-2 gap-x-4 gap-y-2">
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
                      Where it runs
                    </dt>
                    <dd className="text-[var(--text)]">
                      {humanizeWorkspaceScope(definition.workspace_scope)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[10px] uppercase tracking-wider text-[var(--text-subtle)]">
                      Power level
                    </dt>
                    <dd className="text-[var(--text)] tabular-nums">
                      {describePowerLevel(definition.max_compute_tier)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[10px] uppercase tracking-wider text-[var(--text-subtle)]">
                      Spend caps
                    </dt>
                    <dd className="text-[var(--text)] tabular-nums">
                      {fmtCap(definition.max_spend_per_run_usd)} per run ·{' '}
                      {fmtCap(definition.max_spend_per_day_usd)} per day
                    </dd>
                  </div>
                  <div className="col-span-2">
                    <dt className="text-[10px] uppercase tracking-wider text-[var(--text-subtle)]">
                      Permissions
                    </dt>
                    <dd className="text-[var(--text)]">
                      {summarizeContract(definition.contract)}
                      <button
                        type="button"
                        onClick={() => setShowRawContract((v) => !v)}
                        className="ml-2 text-[10px] text-[var(--text-subtle)] hover:text-[var(--text)] underline"
                      >
                        {showRawContract ? 'Hide raw JSON' : 'Show raw JSON'}
                      </button>
                    </dd>
                    {showRawContract && (
                      <pre className="mt-2 max-h-48 overflow-auto rounded-[var(--radius-small)] border border-[var(--border)] bg-[var(--bg)] px-2 py-1.5 text-[11px] font-mono text-[var(--text-muted)]">
                        {JSON.stringify(definition.contract, null, 2)}
                      </pre>
                    )}
                  </div>
                </dl>
              </div>
            )}
          </section>

          {/* Cost rollups — three inline windows summed from loaded runs */}
          <section
            data-testid="cost-rollup-card"
            className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-4"
          >
            <header className="flex items-center justify-between mb-3">
              <h3 className="text-xs font-semibold text-[var(--text)]">Spend rollup</h3>
              {runHasMore && (
                <span
                  className="inline-flex items-center gap-1 text-[10px] text-[var(--text-subtle)]"
                  title="from loaded runs — paginate to include older history"
                >
                  <Info className="w-3 h-3" weight="regular" />
                  from loaded runs
                </span>
              )}
            </header>
            <div className="grid grid-cols-3 gap-3">
              <RollupStat label="24h" value={rollups.h24} testId="rollup-24h" />
              <RollupStat label="7d" value={rollups.d7} testId="rollup-7d" />
              <RollupStat label="30d" value={rollups.d30} testId="rollup-30d" />
            </div>
          </section>

          {/* Filter bar — status (server) + date range + search (client) */}
          <section className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-3">
            <div className="flex flex-wrap items-center gap-2">
              {/* Status — round-trips to the server */}
              <label className="flex items-center gap-1.5">
                <span className="text-[10px] uppercase tracking-wider text-[var(--text-subtle)]">
                  Status
                </span>
                <select
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value as 'all' | AutomationRunStatus)}
                  data-testid="status-filter"
                  className="px-2 py-1 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)]"
                >
                  {STATUS_FILTERS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </label>

              {/* Date range — purely client-side */}
              <label className="flex items-center gap-1.5">
                <span className="text-[10px] uppercase tracking-wider text-[var(--text-subtle)]">
                  Range
                </span>
                <select
                  value={dateRange}
                  onChange={(e) => setDateRange(e.target.value as DateRange)}
                  data-testid="range-filter"
                  className="px-2 py-1 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)]"
                >
                  {(Object.keys(RANGE_LABEL) as DateRange[]).map((r) => (
                    <option key={r} value={r}>
                      {RANGE_LABEL[r]}
                    </option>
                  ))}
                </select>
              </label>

              {dateRange === 'custom' && (
                <>
                  <input
                    type="date"
                    value={customFrom}
                    onChange={(e) => setCustomFrom(e.target.value)}
                    aria-label="From date"
                    className="px-2 py-1 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)]"
                  />
                  <span className="text-[10px] text-[var(--text-subtle)]">to</span>
                  <input
                    type="date"
                    value={customTo}
                    onChange={(e) => setCustomTo(e.target.value)}
                    aria-label="To date"
                    className="px-2 py-1 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)]"
                  />
                </>
              )}

              {/* Search — name (client) or run id prefix */}
              <div className="flex-1 flex items-center gap-1.5 min-w-[160px]">
                <MagnifyingGlass className="w-3 h-3 text-[var(--text-subtle)]" />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search name or run id prefix…"
                  data-testid="search-filter"
                  className="flex-1 px-2 py-1 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)] placeholder-[var(--text-subtle)]"
                />
              </div>
            </div>
          </section>

          {/* Run history */}
          <section className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] overflow-hidden">
            <header className="flex items-center justify-between px-4 py-3 border-b border-[var(--border)]">
              <h3 className="text-xs font-semibold text-[var(--text)]">Run history</h3>
              <span className="text-[10px] text-[var(--text-subtle)] tabular-nums">
                {filteredRuns?.length ?? 0} shown · {runs?.length ?? 0} loaded
              </span>
            </header>
            {filteredRuns === null ? (
              <div className="px-4 py-6 text-xs text-[var(--text-muted)]">Loading runs…</div>
            ) : filteredRuns.length === 0 ? (
              <div className="px-4 py-6 text-xs text-[var(--text-muted)]">
                {runs && runs.length > 0
                  ? 'No runs match the current filters.'
                  : 'No runs yet. Click "Run now" to trigger one manually.'}
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
                  {filteredRuns.map((run) => (
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
            Pause and archive <strong>{definition.name}</strong>? It will stop running, but its run
            history stays so you can review past results.
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
  if (value === null || value === undefined || value === '') return 'No cap';
  return `$${value}`;
}

function describeTrigger(kind: string, config: Record<string, unknown>): string {
  if (kind === 'cron') {
    const expression = String(config.expression ?? '');
    const tz = config.timezone ? String(config.timezone) : null;
    if (!expression) return humanizeTriggerKind(kind);
    return humanizeCron(expression, tz);
  }
  return humanizeTriggerKind(kind);
}

function describeAction(
  type: string,
  config: Record<string, unknown>,
  agentNames: Record<string, string>
): string {
  if (type === 'agent.run') {
    const agentId = String(config.agent_id ?? '');
    const name = agentId ? agentNames[agentId] : null;
    if (name) return `Run "${name}" agent`;
    return humanizeActionType(type);
  }
  return humanizeActionType(type);
}

function describeDeliveryTargets(
  targets: Array<{ destination_id: string }>,
  destinations: CommunicationDestination[]
): string {
  const byId = new Map(destinations.map((d) => [d.id, d]));
  const names = targets.map((t) => {
    const d = byId.get(t.destination_id);
    if (!d) return 'a saved destination';
    return `${d.name} (${humanizeDestinationKind(d.kind)})`;
  });
  if (names.length === 0) return '';
  if (names.length === 1) return `Send to ${names[0]}`;
  return `Send to ${names.join(', ')}`;
}

const POWER_LEVELS: Record<number, string> = {
  0: 'Light (no sandbox)',
  1: 'Standard',
  2: 'Heavy',
};

function describePowerLevel(tier: number): string {
  return POWER_LEVELS[tier] ?? `Tier ${tier}`;
}

function summarizeContract(contract: Record<string, unknown> | null | undefined): string {
  if (!contract || typeof contract !== 'object') return '—';
  const parts: string[] = [];
  const allowedTools = (contract as { allowed_tools?: unknown }).allowed_tools;
  if (Array.isArray(allowedTools) && allowedTools.length > 0) {
    parts.push(`Allowed: ${allowedTools.map(String).join(', ')}`);
  }
  const maxIters = (contract as { max_iterations?: unknown }).max_iterations;
  if (typeof maxIters === 'number') {
    parts.push(`up to ${maxIters} steps per run`);
  }
  if (parts.length === 0) return 'Custom permissions set';
  return parts.join(' · ');
}

function fmtUsd(n: number): string {
  if (!Number.isFinite(n)) return '$0.00';
  // Cap at 4 decimals for tiny token-cost rollups; trim trailing zeros below 2.
  if (n >= 1) return `$${n.toFixed(2)}`;
  return `$${n.toFixed(4).replace(/0+$/, '').replace(/\.$/, '.00')}`;
}

function RollupStat({ label, value, testId }: { label: string; value: number; testId?: string }) {
  return (
    <div data-testid={testId} className="flex flex-col">
      <span className="text-[10px] uppercase tracking-wider text-[var(--text-subtle)]">
        {label}
      </span>
      <span className="text-base font-semibold text-[var(--text)] tabular-nums">
        {fmtUsd(value)}
      </span>
    </div>
  );
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
