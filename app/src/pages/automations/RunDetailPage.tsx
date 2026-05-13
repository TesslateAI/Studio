import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import toast from 'react-hot-toast';
import { ArrowLeft, ArrowsClockwise } from '@phosphor-icons/react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { automationsApi } from '../../lib/api';
import type {
  AutomationApprovalRequestOut,
  AutomationRunArtifactOut,
  AutomationRunDetail,
  RunSpendRollup,
  RunStep,
} from '../../types/automations';
import { RunStatusBadge } from './components/RunStatusBadge';
import { ArtifactPreview } from './components/ArtifactPreview';

const TERMINAL_STATES = new Set(['succeeded', 'failed', 'cancelled', 'expired']);

type TabId = 'steps' | 'artifacts' | 'approvals' | 'spend' | 'delivery';

const TABS: Array<{ id: TabId; label: string }> = [
  { id: 'steps', label: 'Steps' },
  { id: 'artifacts', label: 'Artifacts' },
  { id: 'approvals', label: 'Approvals' },
  { id: 'spend', label: 'Spend' },
  { id: 'delivery', label: 'Delivery' },
];

/**
 * /automations/:id/runs/:run_id
 *
 * Auto-polls every 5s while the run is non-terminal so the user sees
 * step / artifact updates without a manual refresh. Phase 2 will swap
 * this for an SSE subscription.
 *
 * Phase 5 — adds the tabbed body (steps/artifacts/approvals/spend/delivery)
 * sourced from the existing run-detail endpoint plus the small ``/spend``
 * + ``/steps`` rollup endpoints (both gracefully degrade when the server
 * routes aren't deployed yet).
 */
export default function RunDetailPage() {
  const { id, run_id: runId } = useParams<{ id: string; run_id: string }>();
  const navigate = useNavigate();
  const [run, setRun] = useState<AutomationRunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const [activeTab, setActiveTab] = useState<TabId>('steps');

  // Tab-specific lazy state. Each loader fires once the tab activates so we
  // never hammer the rollup endpoints on first paint.
  const [steps, setSteps] = useState<RunStep[] | null>(null);
  const [stepsError, setStepsError] = useState<string | null>(null);
  const [spend, setSpend] = useState<RunSpendRollup | null>(null);
  const [spendError, setSpendError] = useState<string | null>(null);

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

  // Load Steps when the user activates the Steps tab. Re-fetch on every
  // run poll while the run is non-terminal so steps written after first
  // load become visible without a manual refresh — the previous version
  // gated re-fetch on ``steps === null`` and could leave the panel empty
  // forever if the first fetch raced ahead of the worker (TC-04 Bug #23).
  useEffect(() => {
    if (!id || !runId || activeTab !== 'steps') return;
    if (run && TERMINAL_STATES.has(run.status) && steps !== null) return;
    let cancelled = false;
    automationsApi
      .listRunSteps(id, runId)
      .then((rows) => {
        if (!cancelled) {
          setSteps(rows);
          setStepsError(null);
        }
      })
      .catch((err: { message?: string; response?: { data?: { detail?: string } } }) => {
        if (!cancelled) {
          const detail = err.response?.data?.detail;
          setStepsError(
            (typeof detail === 'string' ? detail : err.message) ?? 'Failed to load steps'
          );
        }
      });
    return () => {
      cancelled = true;
    };
  }, [id, runId, activeTab, run, steps]);

  // Lazy-load Spend rollup when the user activates the Spend tab.
  useEffect(() => {
    if (!id || !runId || activeTab !== 'spend' || spend !== null) return;
    let cancelled = false;
    automationsApi
      .getRunSpend(id, runId)
      .then((data) => {
        if (!cancelled) setSpend(data);
      })
      .catch((err: Error) => {
        if (!cancelled) setSpendError(err.message ?? 'Failed to load spend rollup');
      });
    return () => {
      cancelled = true;
    };
  }, [id, runId, activeTab, spend]);

  // ---- Derived per-tab data ----
  const deliveryReceipts = useMemo<AutomationRunArtifactOut[]>(() => {
    if (!run) return [];
    return run.artifacts.filter((a) => a.kind === 'delivery_receipt');
  }, [run]);

  const nonDeliveryArtifacts = useMemo<AutomationRunArtifactOut[]>(() => {
    if (!run) return [];
    return run.artifacts.filter((a) => a.kind !== 'delivery_receipt');
  }, [run]);

  const resolvedApprovals = useMemo<AutomationApprovalRequestOut[]>(() => {
    if (!run) return [];
    return run.approval_requests.filter((r) => r.resolved_at !== null);
  }, [run]);

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
                <Field
                  label={
                    // The ``paused_reason`` column is used as a generic
                    // human-readable reason field; for terminal failures
                    // labelling it "Paused reason" misleads operators
                    // triaging a failed run. Use a status-aware label.
                    run.status === 'failed' || run.status === 'failed_preflight'
                      ? 'Failure reason'
                      : run.status === 'cancelled'
                        ? 'Cancellation reason'
                        : run.status === 'expired'
                          ? 'Expiration reason'
                          : 'Paused reason'
                  }
                >
                  <span className="text-[var(--status-error)]">{run.paused_reason}</span>
                </Field>
              )}
            </dl>
          </section>

          {/* Pending-approval banner — preserved from the previous layout. */}
          {run.approval_requests.some((r) => r.resolved_at === null) && (
            <section className="rounded-[var(--radius)] border border-amber-500/40 bg-amber-500/5 p-4 space-y-2">
              <h3 className="text-xs font-semibold text-amber-300">
                Approval required
              </h3>
              <p className="text-[10px] text-[var(--text-subtle)]">
                Resolve via the Approvals tab below or the originating delivery
                channel.
              </p>
            </section>
          )}

          {/* Tab bar */}
          <div
            role="tablist"
            aria-label="Run details"
            className="flex items-center gap-1 border-b border-[var(--border)]"
          >
            {TABS.map((t) => (
              <button
                key={t.id}
                role="tab"
                aria-selected={activeTab === t.id}
                data-testid={`run-tab-${t.id}`}
                onClick={() => setActiveTab(t.id)}
                className={`px-3 py-1.5 text-xs border-b-2 -mb-px transition-colors ${
                  activeTab === t.id
                    ? 'border-[var(--primary)] text-[var(--text)]'
                    : 'border-transparent text-[var(--text-muted)] hover:text-[var(--text)]'
                }`}
              >
                {t.label}
                {t.id === 'artifacts' && nonDeliveryArtifacts.length > 0 && (
                  <span className="ml-1 text-[10px] text-[var(--text-subtle)] tabular-nums">
                    ({nonDeliveryArtifacts.length})
                  </span>
                )}
                {t.id === 'approvals' && resolvedApprovals.length > 0 && (
                  <span className="ml-1 text-[10px] text-[var(--text-subtle)] tabular-nums">
                    ({resolvedApprovals.length})
                  </span>
                )}
                {t.id === 'delivery' && deliveryReceipts.length > 0 && (
                  <span className="ml-1 text-[10px] text-[var(--text-subtle)] tabular-nums">
                    ({deliveryReceipts.length})
                  </span>
                )}
              </button>
            ))}
          </div>

          {/* Tab panels */}
          {activeTab === 'steps' && (
            <StepsPanel
              run={run}
              steps={steps}
              error={stepsError}
            />
          )}

          {activeTab === 'artifacts' && (
            <ArtifactsPanel
              automationId={id}
              runId={runId}
              artifacts={nonDeliveryArtifacts}
            />
          )}

          {activeTab === 'approvals' && (
            <ApprovalsPanel approvals={resolvedApprovals} />
          )}

          {activeTab === 'spend' && (
            <SpendPanel run={run} rollup={spend} error={spendError} />
          )}

          {activeTab === 'delivery' && (
            <DeliveryPanel
              automationId={id}
              runId={runId}
              receipts={deliveryReceipts}
            />
          )}
        </div>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Tab panels — one component per tab. Each is a thin renderer over the
// run / step / spend data already loaded in the page-level state.
// ---------------------------------------------------------------------------

interface StepsPanelProps {
  run: AutomationRunDetail;
  steps: RunStep[] | null;
  error: string | null;
}

function StepsPanel({ run, steps, error }: StepsPanelProps) {
  // Distinguish app.invoke runs by ``raw_output.action_type``. The action
  // dispatcher writes a single envelope:
  //   {action_type, result: {output, artifacts, spend_usd, duration_seconds,
  //    error, rendered}, app_version_id, action_name}.
  // Agent runs progressively persist into agent_steps and surface via the
  // /steps endpoint.
  const rawOutput = run.raw_output as
    | {
        action_type?: string;
        action_name?: string;
        app_version_id?: string;
        result?: {
          output?: unknown;
          error?: string | null;
          duration_seconds?: number;
          spend_usd?: string | number;
          rendered?: string | null;
        };
      }
    | null
    | undefined;

  const isAppInvoke =
    rawOutput &&
    typeof rawOutput === 'object' &&
    !Array.isArray(rawOutput) &&
    rawOutput.action_type === 'app.invoke';

  if (isAppInvoke) {
    const result = rawOutput.result ?? {};
    return (
      <section className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-4 space-y-3">
        <header className="flex items-center justify-between gap-3 flex-wrap">
          <h3 className="text-xs font-semibold text-[var(--text)]">App invocation</h3>
          <div className="flex items-center gap-2 text-[10px] text-[var(--text-muted)]">
            {rawOutput.action_name && (
              <code className="font-mono">{rawOutput.action_name}</code>
            )}
            {rawOutput.app_version_id && (
              <span className="text-[var(--text-subtle)]">
                version {rawOutput.app_version_id.slice(0, 8)}…
              </span>
            )}
          </div>
        </header>
        {result.error ? (
          <div className="rounded border border-red-500/40 bg-red-500/10 p-2 text-[11px] text-red-300">
            <div className="font-semibold text-red-200">Action error</div>
            <div className="mt-1 whitespace-pre-wrap break-words">{result.error}</div>
          </div>
        ) : (
          <KeyJson label="Output" value={result.output} />
        )}
        {result.rendered && (
          <div>
            <div className="text-[10px] font-medium text-[var(--text-subtle)] mb-1">
              Rendered
            </div>
            <pre className="text-[11px] whitespace-pre-wrap break-words bg-[var(--bg)] border border-[var(--border)] rounded p-2">
              {result.rendered}
            </pre>
          </div>
        )}
        {(typeof result.duration_seconds === 'number' ||
          result.spend_usd !== undefined) && (
          <dl className="text-[10px] text-[var(--text-subtle)] flex flex-wrap gap-x-4 gap-y-1">
            {typeof result.duration_seconds === 'number' && (
              <div>
                <dt className="inline font-medium">Action duration:</dt>{' '}
                <dd className="inline tabular-nums">
                  {(result.duration_seconds * 1000).toFixed(0)} ms
                </dd>
              </div>
            )}
            {result.spend_usd !== undefined && (
              <div>
                <dt className="inline font-medium">Action spend:</dt>{' '}
                <dd className="inline tabular-nums">${result.spend_usd}</dd>
              </div>
            )}
          </dl>
        )}
      </section>
    );
  }

  if (error) {
    return (
      <section className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-4">
        <p className="text-xs text-[var(--status-error)]">{error}</p>
      </section>
    );
  }

  if (steps === null) {
    return (
      <section className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-4">
        <p className="text-xs text-[var(--text-muted)]">Loading steps…</p>
      </section>
    );
  }

  if (steps.length === 0) {
    return (
      <section className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-4">
        <p className="text-xs text-[var(--text-muted)]">No steps recorded.</p>
      </section>
    );
  }

  return (
    <section className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] divide-y divide-[var(--border)]">
      {steps.map((step) => (
        <div key={step.id} className="p-4 space-y-2">
          <div className="flex items-center justify-between text-xs">
            <span className="font-medium text-[var(--text)]">
              #{step.ordinal} · {step.tool_name ?? step.name ?? 'thought'}
            </span>
            <span className="text-[10px] text-[var(--text-subtle)] tabular-nums">
              {step.status} · {formatDate(step.created_at)}
            </span>
          </div>
          {step.thought && (
            <p className="text-xs text-[var(--text-muted)] whitespace-pre-wrap">
              {step.thought}
            </p>
          )}
          {step.input != null && <KeyJson label="Input" value={step.input} />}
          {step.output != null && <KeyJson label="Output" value={step.output} />}
        </div>
      ))}
    </section>
  );
}

interface ArtifactsPanelProps {
  automationId: string;
  runId: string;
  artifacts: AutomationRunArtifactOut[];
}

function ArtifactsPanel({ automationId, runId, artifacts }: ArtifactsPanelProps) {
  if (artifacts.length === 0) {
    return (
      <section className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-4">
        <p className="text-xs text-[var(--text-muted)]">No artifacts produced yet.</p>
      </section>
    );
  }

  return (
    <section className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-4 space-y-2">
      {artifacts.map((artifact) => (
        <ArtifactRow
          key={artifact.id}
          automationId={automationId}
          runId={runId}
          artifact={artifact}
        />
      ))}
    </section>
  );
}

/**
 * Renders a single artifact: markdown inline (via ReactMarkdown), images
 * inline (``<img>``), and everything else as a download link via the
 * existing ``ArtifactPreview`` component.
 */
function ArtifactRow({
  automationId,
  runId,
  artifact,
}: {
  automationId: string;
  runId: string;
  artifact: AutomationRunArtifactOut;
}) {
  const downloadUrl = automationsApi.artifactDownloadUrl(
    automationId,
    runId,
    artifact.id
  );

  // Markdown — render inline using the same renderer used by AgentMessage.
  if (
    artifact.kind === 'markdown' &&
    (artifact.storage_mode === 'inline' || artifact.storage_mode === 'cas') &&
    artifact.preview_text != null
  ) {
    return (
      <article className="rounded-[var(--radius-small)] border border-[var(--border)] bg-[var(--bg)] p-3 space-y-2">
        <header className="flex items-center justify-between text-xs">
          <span className="font-medium text-[var(--text)]">
            {artifact.name || '(unnamed)'}
          </span>
          <a
            href={downloadUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[10px] text-[var(--text-muted)] hover:underline"
          >
            Download
          </a>
        </header>
        <div className="prose prose-sm max-w-none text-[var(--text)]">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {artifact.preview_text}
          </ReactMarkdown>
        </div>
      </article>
    );
  }

  // Images — render inline as an <img> tag pointing at the artifact endpoint.
  if (artifact.kind === 'image' || artifact.kind === 'screenshot') {
    return (
      <article className="rounded-[var(--radius-small)] border border-[var(--border)] bg-[var(--bg)] p-3 space-y-2">
        <header className="flex items-center justify-between text-xs">
          <span className="font-medium text-[var(--text)]">
            {artifact.name || '(unnamed)'}
          </span>
          <a
            href={downloadUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[10px] text-[var(--text-muted)] hover:underline"
          >
            Download
          </a>
        </header>
        <img
          src={downloadUrl}
          alt={artifact.name || 'artifact image'}
          className="max-w-full rounded-[var(--radius-small)]"
        />
      </article>
    );
  }

  // Files / logs / json / text — defer to the existing preview component.
  return (
    <ArtifactPreview
      automationId={automationId}
      runId={runId}
      artifact={artifact}
    />
  );
}

interface ApprovalsPanelProps {
  approvals: AutomationApprovalRequestOut[];
}

function ApprovalsPanel({ approvals }: ApprovalsPanelProps) {
  if (approvals.length === 0) {
    return (
      <section className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-4">
        <p className="text-xs text-[var(--text-muted)]">
          No resolved approvals on this run.
        </p>
      </section>
    );
  }

  return (
    <section className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] divide-y divide-[var(--border)]">
      {approvals.map((req) => {
        const response = req.response ?? {};
        const choice = (response as { choice?: string }).choice ?? '—';
        const notes = (response as { notes?: string }).notes ?? null;
        const summary =
          (req.context as { summary?: string } | null)?.summary ?? '(no summary)';
        return (
          <div key={req.id} className="p-4 space-y-2">
            <div className="flex items-center justify-between text-xs">
              <span className="font-medium text-[var(--text)]">{req.reason}</span>
              <span className="text-[10px] text-[var(--text-subtle)]">
                {choice} · {formatDate(req.resolved_at)}
              </span>
            </div>
            <p className="text-xs text-[var(--text-muted)]">{summary}</p>
            {req.resolved_by_user_id && (
              <p className="text-[10px] text-[var(--text-subtle)]">
                Resolved by user {String(req.resolved_by_user_id).slice(0, 8)}…
              </p>
            )}
            {notes && (
              <p className="text-[11px] text-[var(--text-muted)] whitespace-pre-wrap">
                Notes: {notes}
              </p>
            )}
          </div>
        );
      })}
    </section>
  );
}

interface SpendPanelProps {
  run: AutomationRunDetail;
  rollup: RunSpendRollup | null;
  error: string | null;
}

function SpendPanel({ run, rollup, error }: SpendPanelProps) {
  if (error) {
    return (
      <section className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-4">
        <p className="text-xs text-[var(--status-error)]">{error}</p>
      </section>
    );
  }
  if (rollup === null) {
    return (
      <section className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-4">
        <p className="text-xs text-[var(--text-muted)]">Loading spend rollup…</p>
      </section>
    );
  }

  const sourceEntries = Object.entries(rollup.spend_by_source ?? {});
  const hasBreakdown = sourceEntries.length > 0 || rollup.per_app.length > 0;

  return (
    <section className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-4 space-y-4">
      <div>
        <h3 className="text-xs font-semibold text-[var(--text)] mb-2">Total</h3>
        <p className="text-base font-semibold text-[var(--text)] tabular-nums">
          ${run.spend_usd}
        </p>
      </div>

      {sourceEntries.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-[var(--text)] mb-2">By source</h3>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
            {sourceEntries.map(([source, amount]) => (
              <div key={source} className="flex justify-between">
                <dt className="text-[var(--text-subtle)]">{source}</dt>
                <dd className="text-[var(--text)] tabular-nums">${String(amount)}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      {rollup.per_app.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-[var(--text)] mb-2">By app</h3>
          <table className="w-full text-xs">
            <thead className="text-[10px] uppercase tracking-wider text-[var(--text-subtle)]">
              <tr>
                <th className="text-left font-medium">App</th>
                <th className="text-right font-medium">Spend</th>
              </tr>
            </thead>
            <tbody>
              {rollup.per_app.map((row, i) => (
                <tr
                  key={`${row.app_instance_id ?? 'none'}-${i}`}
                  className="border-t border-[var(--border)]"
                >
                  <td className="py-1 text-[var(--text)]">
                    {row.app_name ??
                      (row.app_instance_id
                        ? `${row.app_instance_id.slice(0, 8)}…`
                        : '—')}
                  </td>
                  <td className="py-1 text-right text-[var(--text)] tabular-nums">
                    ${row.amount_usd}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!hasBreakdown && (
        <p className="text-xs text-[var(--text-muted)]">
          Spend rollup not yet available — totals will surface once the run
          dispatcher finalises.
        </p>
      )}
    </section>
  );
}

interface DeliveryPanelProps {
  automationId: string;
  runId: string;
  receipts: AutomationRunArtifactOut[];
}

function DeliveryPanel({ automationId, runId, receipts }: DeliveryPanelProps) {
  if (receipts.length === 0) {
    return (
      <section className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-4">
        <p className="text-xs text-[var(--text-muted)]">No delivery receipts.</p>
      </section>
    );
  }

  return (
    <section className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-4 space-y-2">
      {receipts.map((r) => (
        <ArtifactPreview
          key={r.id}
          automationId={automationId}
          runId={runId}
          artifact={r}
        />
      ))}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Small shared helpers
// ---------------------------------------------------------------------------

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

function KeyJson({ label, value }: { label: string; value: unknown }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wider text-[var(--text-subtle)] mb-1">
        {label}
      </p>
      <pre className="max-h-48 overflow-auto rounded-[var(--radius-small)] border border-[var(--border)] bg-[var(--bg)] px-2 py-1.5 text-[11px] font-mono text-[var(--text-muted)] whitespace-pre-wrap break-words">
        {typeof value === 'string' ? value : safeStringify(value)}
      </pre>
    </div>
  );
}

function safeStringify(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
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
