import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import toast from 'react-hot-toast';
import { ArrowLeft, ArrowsClockwise } from '@phosphor-icons/react';
import { automationsApi } from '../../lib/api';
import type { AutomationRunDetail } from '../../types/automations';
import { RunStatusBadge } from './components/RunStatusBadge';
import { ArtifactPreview } from './components/ArtifactPreview';

const TERMINAL_STATES = new Set(['succeeded', 'failed', 'cancelled', 'expired']);

/**
 * /automations/:id/runs/:run_id
 *
 * Auto-polls every 5s while the run is non-terminal so the user sees
 * step / artifact updates without a manual refresh. Phase 2 will swap
 * this for an SSE subscription.
 */
export default function RunDetailPage() {
  const { id, run_id: runId } = useParams<{ id: string; run_id: string }>();
  const navigate = useNavigate();
  const [run, setRun] = useState<AutomationRunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const reload = useCallback(
    async (silent = false) => {
      if (!id || !runId) return;
      if (!silent) setError(null);
      if (silent) setRefreshing(true);
      try {
        const data = await automationsApi.getRun(id, runId);
        setRun(data);
      } catch (err) {
        const msg =
          (err as { response?: { data?: { detail?: string } } }).response?.data?.detail ||
          'Failed to load run';
        if (!silent) setError(msg);
        else toast.error(msg);
      } finally {
        setRefreshing(false);
      }
    },
    [id, runId]
  );

  useEffect(() => {
    reload(false);
  }, [reload]);

  // Auto-poll until terminal.
  useEffect(() => {
    if (!run || TERMINAL_STATES.has(run.status)) return;
    const handle = window.setInterval(() => reload(true), 5000);
    return () => window.clearInterval(handle);
  }, [run, reload]);

  if (error) {
    return (
      <div className="p-8">
        <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-4 text-sm text-[var(--status-error)]">
          {error}
        </div>
      </div>
    );
  }

  if (!run || !id || !runId) {
    return <div className="p-8 text-sm text-[var(--text-muted)]">Loading run…</div>;
  }

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
            onClick={() => navigate(`/automations/${id}`)}
            className="btn btn-icon btn-sm"
            aria-label="Back to automation"
          >
            <ArrowLeft className="w-3 h-3" />
          </button>
          <h2 className="text-xs font-semibold text-[var(--text)] flex-1 truncate">
            Run {runId.slice(0, 8)}…
          </h2>
          <RunStatusBadge status={run.status} />
          <button
            onClick={() => reload(true)}
            disabled={refreshing}
            className="btn btn-icon btn-sm"
            aria-label="Refresh"
            title="Refresh"
          >
            <ArrowsClockwise className={`w-3 h-3 ${refreshing ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-6 py-6 space-y-6">
          {/* Header card */}
          <section className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-4">
            <dl className="grid grid-cols-2 md:grid-cols-3 gap-x-4 gap-y-2 text-xs">
              <Field label="Status">
                <RunStatusBadge status={run.status} />
              </Field>
              <Field label="Started">{formatDate(run.started_at)}</Field>
              <Field label="Ended">{formatDate(run.ended_at)}</Field>
              <Field label="Duration">
                {formatDuration(run.started_at, run.ended_at)}
              </Field>
              <Field label="Spend">${run.spend_usd}</Field>
              <Field label="Retries">{run.retry_count}</Field>
              <Field label="Contract breaches">{run.contract_breaches}</Field>
              <Field label="Event ID">{run.event_id?.slice(0, 8) ?? '—'}…</Field>
              {run.paused_reason && (
                <Field label="Paused reason">
                  <span className="text-[var(--status-error)]">{run.paused_reason}</span>
                </Field>
              )}
            </dl>
          </section>

          {/* Approval requests */}
          {run.approval_requests.length > 0 && (
            <section className="rounded-[var(--radius)] border border-amber-500/40 bg-amber-500/5 p-4 space-y-2">
              <h3 className="text-xs font-semibold text-amber-300">
                Approval required ({run.approval_requests.length})
              </h3>
              {run.approval_requests.map((req) => (
                <div
                  key={req.id}
                  className="rounded-[var(--radius-small)] border border-[var(--border)] bg-[var(--surface)] p-3 space-y-1"
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="text-xs text-[var(--text)] font-medium">
                      {req.reason}
                    </span>
                    <span className="text-[10px] text-[var(--text-subtle)]">
                      Requested {formatDate(req.requested_at)}
                    </span>
                  </div>
                  {req.expires_at && (
                    <p className="text-[10px] text-[var(--text-subtle)]">
                      Expires {formatDate(req.expires_at)}
                    </p>
                  )}
                  <p className="text-[10px] text-[var(--text-subtle)]">
                    Approval resolution UI lands in Phase 2 — for now, resolve via the
                    delivery channel where the approval was sent.
                  </p>
                </div>
              ))}
            </section>
          )}

          {/* Raw output (Phase 1: dump as JSON; Phase 2 wires StepRenderer for agent.run) */}
          {run.raw_output != null && (
            <section className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-4">
              <h3 className="text-xs font-semibold text-[var(--text)] mb-2">Output</h3>
              <pre className="max-h-72 overflow-auto rounded-[var(--radius-small)] border border-[var(--border)] bg-[var(--bg)] px-2 py-1.5 text-[11px] font-mono text-[var(--text-muted)] whitespace-pre-wrap break-words">
                {typeof run.raw_output === 'string'
                  ? run.raw_output
                  : JSON.stringify(run.raw_output, null, 2)}
              </pre>
            </section>
          )}

          {/* Artifacts */}
          <section className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-4 space-y-2">
            <header className="flex items-center justify-between">
              <h3 className="text-xs font-semibold text-[var(--text)]">
                Artifacts ({run.artifacts.length})
              </h3>
            </header>
            {run.artifacts.length === 0 ? (
              <p className="text-xs text-[var(--text-muted)]">
                No artifacts produced yet.
              </p>
            ) : (
              <div className="space-y-2">
                {run.artifacts.map((artifact) => (
                  <ArtifactPreview
                    key={artifact.id}
                    automationId={id}
                    runId={runId}
                    artifact={artifact}
                  />
                ))}
              </div>
            )}
          </section>
        </div>
      </div>
    </>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-wider text-[var(--text-subtle)]">
        {label}
      </dt>
      <dd className="text-[var(--text)] tabular-nums">{children}</dd>
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
      second: '2-digit',
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
