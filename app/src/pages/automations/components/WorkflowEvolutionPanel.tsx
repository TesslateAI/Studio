/**
 * Workflow Evolution Panel — G1 / G2 / G5 surfaces in one collapsible
 * section on the automation detail page.
 *
 * UX intent: an owner who opens this panel can answer four questions
 * in one glance:
 *   1. What's the live version, and how many have come before?
 *   2. Are there agent proposals waiting for me?
 *   3. Is the doctor watching this workflow?
 *   4. (Hover/click any version) What changed?
 *
 * No tabs — the panel is one scrollable column with three small
 * cards: Versions, Proposals, Doctor. Each card is independently
 * useful and the most common action (approve a proposal, enable
 * the doctor) is one click.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import toast from 'react-hot-toast';
import {
  CheckCircle,
  ClockCounterClockwise,
  Robot,
  ShieldCheck,
  Warning,
  X,
} from '@phosphor-icons/react';
import { automationsApi } from '../../../lib/api';

interface Props {
  automationId: string;
  headVersionId: string | null;
  doctorAutomationId: string | null;
  doctorEnabled: boolean;
  onDoctorChanged?: (enabled: boolean, doctorId: string | null) => void;
  onProposalApplied?: () => void;
}

interface VersionRow {
  id: string;
  generation: number;
  parent_version_id: string | null;
  payload_sha256: string;
  rationale: string | null;
  created_at: string | null;
  created_by_user_id: string | null;
  created_by_run_id: string | null;
  is_head: boolean;
  payload: Record<string, unknown>;
}

interface ProposalRow {
  id: string;
  status: string;
  risk_class: string;
  rationale: string;
  from_version_id: string | null;
  applied_version_id: string | null;
  proposer_user_id: string | null;
  proposer_run_id: string | null;
  created_at: string | null;
  decided_at: string | null;
}

interface ProposalDetail extends ProposalRow {
  automation_id: string;
  to_payload: Record<string, unknown>;
  diff_summary: Array<{
    path: string;
    op: string;
    before?: unknown;
    after?: unknown;
  }>;
  reviewer_comment: string | null;
}

const STATUS_COLOR: Record<string, string> = {
  submitted: 'text-amber-400',
  approved: 'text-emerald-400',
  applied: 'text-emerald-400',
  rejected: 'text-rose-400',
  withdrawn: 'text-[var(--text-subtle)]',
  expired: 'text-[var(--text-subtle)]',
  reverted: 'text-amber-400',
};

const RISK_COLOR: Record<string, string> = {
  low: 'text-emerald-400',
  medium: 'text-amber-400',
  high: 'text-rose-400',
};

function relativeTime(iso: string | null): string {
  if (!iso) return '—';
  const ts = new Date(iso).getTime();
  if (Number.isNaN(ts)) return '—';
  const diff = Date.now() - ts;
  const minutes = Math.round(diff / 60_000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

export default function WorkflowEvolutionPanel({
  automationId,
  headVersionId,
  doctorAutomationId,
  doctorEnabled,
  onDoctorChanged,
  onProposalApplied,
}: Props) {
  const [versions, setVersions] = useState<VersionRow[] | null>(null);
  const [proposals, setProposals] = useState<ProposalRow[] | null>(null);
  const [expandedProposal, setExpandedProposal] = useState<ProposalDetail | null>(null);
  const [deciding, setDeciding] = useState(false);
  const [togglingDoctor, setTogglingDoctor] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setError(null);
    try {
      const [v, p] = await Promise.all([
        automationsApi.listVersions(automationId),
        automationsApi.listProposals(automationId),
      ]);
      setVersions(v as VersionRow[]);
      setProposals(p as ProposalRow[]);
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail ||
        'Failed to load workflow evolution data';
      setError(msg);
      setVersions([]);
      setProposals([]);
    }
  }, [automationId]);

  useEffect(() => {
    reload();
  }, [reload]);

  const headGeneration = useMemo(() => {
    if (!versions) return null;
    const head = versions.find((v) => v.is_head);
    return head?.generation ?? null;
  }, [versions]);

  const openProposals = useMemo(
    () => (proposals ?? []).filter((p) => p.status === 'submitted'),
    [proposals]
  );

  const handleDecide = async (proposalId: string, decision: 'approve' | 'reject') => {
    setDeciding(true);
    try {
      await automationsApi.decideProposal(automationId, proposalId, { decision });
      toast.success(decision === 'approve' ? 'Applied' : 'Rejected');
      setExpandedProposal(null);
      await reload();
      if (decision === 'approve' && onProposalApplied) onProposalApplied();
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail ||
        `Failed to ${decision}`;
      toast.error(msg);
    } finally {
      setDeciding(false);
    }
  };

  const handleToggleDoctor = async () => {
    setTogglingDoctor(true);
    try {
      const result = doctorEnabled
        ? await automationsApi.disableDoctor(automationId)
        : await automationsApi.enableDoctor(automationId);
      toast.success(doctorEnabled ? 'Doctor paused' : 'Doctor watching this workflow');
      if (onDoctorChanged) {
        onDoctorChanged(
          Boolean(result?.doctor_enabled),
          (result?.doctor_automation_id as string | null) ?? null
        );
      }
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail ||
        'Failed to toggle doctor';
      toast.error(msg);
    } finally {
      setTogglingDoctor(false);
    }
  };

  const openProposalDetail = async (id: string) => {
    try {
      const detail = await automationsApi.getProposal(automationId, id);
      setExpandedProposal(detail as ProposalDetail);
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail ||
        'Failed to load proposal';
      toast.error(msg);
    }
  };

  return (
    <section className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] overflow-hidden">
      <header className="flex items-center gap-3 border-b border-[var(--border)] px-4 py-2.5">
        <ClockCounterClockwise className="w-4 h-4 text-[var(--text-muted)]" />
        <h3 className="text-xs font-semibold text-[var(--text)] flex-1">Workflow evolution</h3>
        {headGeneration !== null && (
          <span className="text-[10px] text-[var(--text-subtle)] tabular-nums">
            v{headGeneration}
          </span>
        )}
        {openProposals.length > 0 && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 tabular-nums">
            {openProposals.length} pending
          </span>
        )}
      </header>

      {error ? (
        <div className="px-4 py-3 text-xs text-[var(--status-error)]">{error}</div>
      ) : (
        <div className="grid md:grid-cols-3 divide-y md:divide-y-0 md:divide-x divide-[var(--border)]">
          {/* Versions card */}
          <div className="p-3">
            <h4 className="text-[10px] uppercase tracking-wider text-[var(--text-subtle)] mb-2">
              Versions
            </h4>
            {versions === null ? (
              <p className="text-xs text-[var(--text-muted)]">Loading…</p>
            ) : versions.length === 0 ? (
              <p className="text-xs text-[var(--text-muted)]">
                No versions yet. Edit the workflow to create one.
              </p>
            ) : (
              <ul className="space-y-1.5 max-h-48 overflow-y-auto">
                {versions.slice(0, 8).map((v) => (
                  <li
                    key={v.id}
                    className={`flex items-center gap-2 text-xs ${
                      v.is_head ? 'text-[var(--text)]' : 'text-[var(--text-muted)]'
                    }`}
                  >
                    <span className="tabular-nums w-6 text-right">v{v.generation}</span>
                    {v.is_head && (
                      <span className="text-[9px] px-1 py-px rounded bg-emerald-500/15 text-emerald-400">
                        HEAD
                      </span>
                    )}
                    <span className="flex-1 truncate" title={v.rationale ?? ''}>
                      {v.rationale ?? '—'}
                    </span>
                    <span className="text-[10px] text-[var(--text-subtle)]">
                      {relativeTime(v.created_at)}
                    </span>
                  </li>
                ))}
                {versions.length > 8 && (
                  <li className="text-[10px] text-[var(--text-subtle)] text-center pt-1">
                    +{versions.length - 8} older
                  </li>
                )}
              </ul>
            )}
          </div>

          {/* Proposals card */}
          <div className="p-3">
            <h4 className="text-[10px] uppercase tracking-wider text-[var(--text-subtle)] mb-2">
              Proposals
            </h4>
            {proposals === null ? (
              <p className="text-xs text-[var(--text-muted)]">Loading…</p>
            ) : openProposals.length === 0 ? (
              <p className="text-xs text-[var(--text-muted)]">
                No pending proposals. The doctor will appear here when it drafts a change.
              </p>
            ) : (
              <ul className="space-y-1.5 max-h-48 overflow-y-auto">
                {openProposals.map((p) => (
                  <li key={p.id}>
                    <button
                      type="button"
                      onClick={() => openProposalDetail(p.id)}
                      className="w-full text-left flex items-center gap-2 text-xs hover:bg-[var(--surface-hover)] rounded px-1.5 py-1"
                    >
                      <span
                        className={`text-[9px] uppercase tabular-nums ${
                          RISK_COLOR[p.risk_class] ?? 'text-[var(--text-subtle)]'
                        }`}
                      >
                        {p.risk_class}
                      </span>
                      <span className="flex-1 truncate text-[var(--text)]">{p.rationale}</span>
                      <span className="text-[10px] text-[var(--text-subtle)]">
                        {relativeTime(p.created_at)}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Doctor card */}
          <div className="p-3 flex flex-col gap-2">
            <h4 className="text-[10px] uppercase tracking-wider text-[var(--text-subtle)] mb-1">
              Self-healing doctor
            </h4>
            <p className="text-xs text-[var(--text-muted)] leading-relaxed">
              {doctorEnabled ? (
                <>
                  <ShieldCheck className="inline w-3.5 h-3.5 mr-1 text-emerald-400" />
                  Watching this workflow. Failed runs trigger a diagnose-then-propose loop; you
                  approve before changes apply.
                </>
              ) : (
                <>
                  When enabled, an agent watches this workflow's failures and proposes fixes for
                  your review. Disabled by default.
                </>
              )}
            </p>
            <button
              type="button"
              onClick={handleToggleDoctor}
              disabled={togglingDoctor}
              className={`btn btn-sm self-start ${doctorEnabled ? 'btn-secondary' : 'btn-primary'}`}
            >
              <Robot className="w-3.5 h-3.5" />
              {togglingDoctor ? '…' : doctorEnabled ? 'Pause doctor' : 'Enable doctor'}
            </button>
            {doctorAutomationId && (
              <p className="text-[10px] text-[var(--text-subtle)] mt-1 font-mono">
                doctor: {doctorAutomationId.slice(0, 8)}…
              </p>
            )}
          </div>
        </div>
      )}

      {/* Proposal detail / decide modal */}
      {expandedProposal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          onClick={() => setExpandedProposal(null)}
        >
          <div
            className="bg-[var(--surface)] border border-[var(--border)] rounded-[var(--radius)] max-w-2xl w-full max-h-[80vh] flex flex-col overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <header className="flex items-center gap-3 border-b border-[var(--border)] px-4 py-3">
              <span
                className={`text-[10px] uppercase tabular-nums ${
                  RISK_COLOR[expandedProposal.risk_class] ?? ''
                }`}
              >
                {expandedProposal.risk_class}
              </span>
              <h3 className="text-sm font-semibold text-[var(--text)] flex-1">
                Proposal — {expandedProposal.rationale}
              </h3>
              <span
                className={`text-[10px] tabular-nums ${
                  STATUS_COLOR[expandedProposal.status] ?? ''
                }`}
              >
                {expandedProposal.status}
              </span>
              <button
                type="button"
                onClick={() => setExpandedProposal(null)}
                className="btn btn-icon btn-sm"
                aria-label="Close"
              >
                <X className="w-4 h-4" />
              </button>
            </header>

            <div className="px-4 py-3 text-[11px] text-[var(--text-muted)] flex items-center gap-4 border-b border-[var(--border)]">
              <span>
                Proposed by{' '}
                {expandedProposal.proposer_user_id
                  ? 'user'
                  : expandedProposal.proposer_run_id
                    ? 'agent'
                    : 'system'}
              </span>
              <span>{relativeTime(expandedProposal.created_at)}</span>
              {headVersionId && expandedProposal.from_version_id && (
                <span>Base: {expandedProposal.from_version_id.slice(0, 8)}…</span>
              )}
            </div>

            <div className="flex-1 overflow-y-auto px-4 py-3">
              <h4 className="text-[10px] uppercase tracking-wider text-[var(--text-subtle)] mb-2">
                Diff ({expandedProposal.diff_summary.length} change
                {expandedProposal.diff_summary.length === 1 ? '' : 's'})
              </h4>
              {expandedProposal.diff_summary.length === 0 ? (
                <p className="text-xs text-[var(--text-muted)]">No diff.</p>
              ) : (
                <ul className="space-y-3">
                  {expandedProposal.diff_summary.map((entry, i) => (
                    <li key={i} className="text-xs border border-[var(--border)] rounded p-2">
                      <div className="flex items-center gap-2 mb-1.5">
                        <span
                          className={`text-[9px] uppercase tabular-nums ${
                            entry.op === 'add'
                              ? 'text-emerald-400'
                              : entry.op === 'remove'
                                ? 'text-rose-400'
                                : 'text-amber-400'
                          }`}
                        >
                          {entry.op}
                        </span>
                        <code className="text-[10px] text-[var(--text)] font-mono">
                          {entry.path}
                        </code>
                      </div>
                      {entry.op !== 'add' && (
                        <div className="mb-1">
                          <span className="text-[10px] text-rose-400">−</span>{' '}
                          <code className="text-[10px] text-[var(--text-muted)] font-mono break-all">
                            {JSON.stringify(entry.before)}
                          </code>
                        </div>
                      )}
                      {entry.op !== 'remove' && (
                        <div>
                          <span className="text-[10px] text-emerald-400">+</span>{' '}
                          <code className="text-[10px] text-[var(--text)] font-mono break-all">
                            {JSON.stringify(entry.after)}
                          </code>
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {expandedProposal.status === 'submitted' && (
              <footer className="flex items-center gap-2 border-t border-[var(--border)] px-4 py-3 justify-end">
                <button
                  type="button"
                  onClick={() => handleDecide(expandedProposal.id, 'reject')}
                  disabled={deciding}
                  className="btn btn-sm btn-secondary"
                >
                  <Warning className="w-3.5 h-3.5" /> Reject
                </button>
                <button
                  type="button"
                  onClick={() => handleDecide(expandedProposal.id, 'approve')}
                  disabled={deciding}
                  className="btn btn-sm btn-primary"
                >
                  <CheckCircle className="w-3.5 h-3.5" /> Approve & apply
                </button>
              </footer>
            )}
            {expandedProposal.status !== 'submitted' && expandedProposal.reviewer_comment && (
              <footer className="border-t border-[var(--border)] px-4 py-3 text-[11px] text-[var(--text-muted)]">
                {expandedProposal.reviewer_comment}
              </footer>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
