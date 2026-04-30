import { useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import { Plus, Play, Trash, Robot } from '@phosphor-icons/react';
import { automationsApi, marketplaceApi } from '../../lib/api';
import type {
  AutomationDefinitionSummary,
  AutomationDefinitionOut,
  AutomationActionType,
  AutomationTriggerKind,
} from '../../types/automations';
import { ConfirmDialog } from '../../components/modals/ConfirmDialog';
import { humanizeActionType, humanizeCron, humanizeTriggerKind } from './utils/humanize';

/**
 * /automations — list view. Lightweight summary list + lazy detail
 * fetches for the trigger/action summaries.
 */
export default function AutomationsListPage() {
  const navigate = useNavigate();
  const [rows, setRows] = useState<AutomationDefinitionSummary[] | null>(null);
  const [details, setDetails] = useState<Record<string, AutomationDefinitionOut>>({});
  const [agentNames, setAgentNames] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [actioningId, setActioningId] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<AutomationDefinitionSummary | null>(null);
  const [deleting, setDeleting] = useState(false);

  const loadList = useCallback(async () => {
    setError(null);
    try {
      const data = await automationsApi.list();
      setRows(data);
      // Fan out detail fetches non-blockingly so the table can show trigger
      // / action summaries. Individual failures are swallowed — the row
      // simply renders with "—" placeholders.
      data.forEach((row) => {
        automationsApi
          .get(row.id)
          .then((detail) => setDetails((prev) => ({ ...prev, [row.id]: detail })))
          .catch(() => {});
      });
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail ||
        (err as Error).message ||
        'Failed to load automations';
      setError(msg);
      setRows([]);
    }
  }, []);

  useEffect(() => {
    loadList();
  }, [loadList]);

  // One-shot fetch of the caller's agents so we can resolve agent_id →
  // human name in the action column. Falls back silently to "Run an AI
  // agent" if the API errors or the row is missing.
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
        for (const a of list) {
          map[String(a.id)] = a.name ?? a.slug ?? String(a.id);
        }
        setAgentNames(map);
      })
      .catch(() => {
        // Silent — the action column gracefully renders the generic label.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleRunNow = async (id: string) => {
    setActioningId(id);
    try {
      const res = await automationsApi.run(id);
      toast.success('Run queued');
      navigate(`/automations/${id}/runs/${res.run_id}`);
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail ||
        'Failed to queue run';
      toast.error(msg);
    } finally {
      setActioningId(null);
    }
  };

  const handleDelete = async () => {
    if (!confirmDelete) return;
    setDeleting(true);
    try {
      await automationsApi.remove(confirmDelete.id, false);
      toast.success(`Deleted "${confirmDelete.name}"`);
      setConfirmDelete(null);
      await loadList();
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail ||
        'Failed to delete automation';
      toast.error(msg);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <>
      {/* Header bar */}
      <div className="flex-shrink-0">
        <div
          className="h-10 flex items-center justify-between gap-[6px]"
          style={{
            paddingLeft: '18px',
            paddingRight: '4px',
            borderBottom: 'var(--border-width) solid var(--border)',
          }}
        >
          <h2 className="text-xs font-semibold text-[var(--text)] flex-1">Automations</h2>
          <button
            onClick={() => navigate('/automations/new')}
            className="btn btn-icon"
            aria-label="Create automation"
          >
            <Plus className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto">
        {rows === null ? (
          <div className="p-8 text-sm text-[var(--text-muted)]">Loading automations…</div>
        ) : error ? (
          <div className="p-8">
            <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-4 text-sm text-[var(--status-error)]">
              {error}
            </div>
          </div>
        ) : rows.length === 0 ? (
          <EmptyState onCreate={() => navigate('/automations/new')} />
        ) : (
          <div className="px-6 py-6">
            <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] overflow-hidden">
              <table className="w-full text-xs">
                <thead className="bg-[var(--surface-hover)] text-[10px] uppercase tracking-wider text-[var(--text-subtle)]">
                  <tr>
                    <th className="text-left px-3 py-2 font-medium">Name</th>
                    <th className="text-left px-3 py-2 font-medium">Trigger</th>
                    <th className="text-left px-3 py-2 font-medium">Action</th>
                    <th className="text-left px-3 py-2 font-medium">Status</th>
                    <th className="text-left px-3 py-2 font-medium">Last run</th>
                    <th className="text-left px-3 py-2 font-medium">Next run</th>
                    <th className="text-right px-3 py-2 font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => {
                    const detail = details[row.id];
                    const trig = detail?.triggers[0];
                    const action = detail?.actions[0];
                    const lastRun = trig?.last_run_at;
                    const nextRun = trig?.next_run_at;
                    return (
                      <tr
                        key={row.id}
                        className="border-t border-[var(--border)] hover:bg-[var(--surface-hover)] cursor-pointer"
                        onClick={() => navigate(`/automations/${row.id}`)}
                      >
                        <td className="px-3 py-2 text-[var(--text)] font-medium">{row.name}</td>
                        <td className="px-3 py-2 text-[var(--text-muted)]">
                          {trig ? summarizeTrigger(trig.kind, trig.config) : '—'}
                        </td>
                        <td className="px-3 py-2 text-[var(--text-muted)]">
                          {action
                            ? summarizeAction(action.action_type, action.config, agentNames)
                            : '—'}
                        </td>
                        <td className="px-3 py-2">
                          <StatusChip isActive={row.is_active} pausedReason={row.paused_reason} />
                        </td>
                        <td className="px-3 py-2 text-[var(--text-subtle)] tabular-nums">
                          {formatDate(lastRun ?? null)}
                        </td>
                        <td className="px-3 py-2 text-[var(--text-subtle)] tabular-nums">
                          {formatDate(nextRun ?? null)}
                        </td>
                        <td className="px-3 py-2">
                          <div className="flex items-center justify-end gap-1">
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                handleRunNow(row.id);
                              }}
                              disabled={actioningId === row.id || !row.is_active}
                              className="btn btn-sm btn-icon"
                              aria-label="Run now"
                              title={row.is_active ? 'Run now' : 'Automation is paused'}
                            >
                              <Play className="w-3 h-3" weight="fill" />
                            </button>
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                setConfirmDelete(row);
                              }}
                              className="btn btn-sm btn-icon"
                              aria-label="Delete"
                              title="Delete"
                            >
                              <Trash className="w-3 h-3" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      <ConfirmDialog
        isOpen={confirmDelete !== null}
        onClose={() => (!deleting ? setConfirmDelete(null) : undefined)}
        onConfirm={handleDelete}
        title="Delete automation?"
        message={
          <span>
            Pause and archive <strong>{confirmDelete?.name}</strong>? It will stop running, but its
            run history stays so you can review past results.
          </span>
        }
        confirmText="Delete"
        variant="danger"
        isLoading={deleting}
      />
    </>
  );
}

function EmptyState({ onCreate }: { onCreate: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] px-6 text-center">
      <div className="h-16 w-16 rounded-[var(--radius)] bg-[var(--surface-hover)] border border-[var(--border)] flex items-center justify-center mb-4">
        <Robot className="w-8 h-8 text-[var(--text-subtle)]" />
      </div>
      <h1 className="text-sm font-semibold text-[var(--text)] mb-2">No automations yet</h1>
      <p className="text-xs text-[var(--text-muted)] max-w-md mb-6">
        Automations do work for you on a schedule or when something happens — like running an AI
        agent every morning, or posting to Slack when a webhook fires.
      </p>
      <button onClick={onCreate} className="btn btn-filled">
        <Plus className="w-3 h-3" />
        Build your first automation
      </button>
      <p className="text-[10px] text-[var(--text-subtle)] mt-3">Templates coming soon.</p>
    </div>
  );
}

function StatusChip({
  isActive,
  pausedReason,
}: {
  isActive: boolean;
  pausedReason: string | null;
}) {
  if (isActive) {
    return (
      <span className="inline-flex items-center gap-1 rounded-[var(--radius-small)] px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider bg-emerald-500/15 text-emerald-400">
        Active
      </span>
    );
  }
  return (
    <span
      className="inline-flex items-center gap-1 rounded-[var(--radius-small)] px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider bg-[var(--surface-hover)] text-[var(--text-subtle)]"
      title={pausedReason || 'Paused'}
    >
      Paused
    </span>
  );
}

function summarizeTrigger(kind: AutomationTriggerKind, config: Record<string, unknown>): string {
  if (kind === 'cron') {
    const expression = String(config.expression ?? '');
    const tz = config.timezone ? String(config.timezone) : null;
    if (!expression) return humanizeTriggerKind(kind);
    return humanizeCron(expression, tz);
  }
  return humanizeTriggerKind(kind);
}

function summarizeAction(
  type: AutomationActionType,
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
