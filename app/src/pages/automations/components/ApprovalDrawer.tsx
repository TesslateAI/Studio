import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { X } from '@phosphor-icons/react';
import toast from 'react-hot-toast';
import { automationsApi } from '../../../lib/api';
import type {
  ApprovalChoice,
  ApprovalReason,
  ApprovalRequest,
  ApprovalResponse,
  AutomationRunArtifactOut,
} from '../../../types/automations';
import { ConfirmDialog } from '../../../components/modals/ConfirmDialog';
import { ArtifactPreview } from './ArtifactPreview';

interface Props {
  /** The pending request to act on. ``null`` closes the drawer. */
  approval: ApprovalRequest | null;
  onClose: () => void;
  /** Fired after a successful POST so the parent can drop the row. */
  onResolved?: (id: string) => void;
}

interface ChoiceMeta {
  label: string;
  description: string;
  /** Visual emphasis. ``destructive`` paints red. */
  tone: 'primary' | 'neutral' | 'destructive';
  /** Show a confirm-dialog before submitting. */
  confirm?: { title: string; message: string; confirmText: string };
  /** Render a notes textarea before submission. */
  requiresNotes?: boolean;
}

const CHOICE_META: Record<ApprovalChoice, ChoiceMeta> = {
  allow_once: {
    label: 'Allow Once',
    description: 'Approve this single tool call. The next call requires re-approval.',
    tone: 'primary',
  },
  allow_for_run: {
    label: 'Allow For This Run',
    description: 'Approve this and similar calls for the remainder of this run only.',
    tone: 'neutral',
  },
  allow_for_automation: {
    label: 'Allow Permanently',
    description:
      "Approve this kind of call for every future run of this automation by editing its contract.",
    tone: 'neutral',
    confirm: {
      title: 'Modify automation contract?',
      message:
        'This will modify the automation’s contract so future runs do not pause for this kind of call. You can always tighten the contract later.',
      confirmText: 'Allow Permanently',
    },
  },
  allow_for_app_or_agent: {
    label: 'Allow For App / Agent',
    description: 'Approve this call for the originating app/agent across automations.',
    tone: 'neutral',
    confirm: {
      title: 'Allow across automations?',
      message:
        'This grants the originating app or agent permission to make this kind of call without approval in future automations.',
      confirmText: 'Allow',
    },
  },
  request_changes: {
    label: 'Request Changes',
    description: 'Send the agent back with notes describing what to change.',
    tone: 'neutral',
    requiresNotes: true,
  },
  deny: {
    label: 'Deny',
    description: 'Refuse this call. The run continues and the agent decides what to do.',
    tone: 'neutral',
  },
  deny_and_disable_automation: {
    label: 'Deny + Disable Automation',
    description:
      'Refuse this call and pause the entire automation. Use when the contract feels wrong.',
    tone: 'destructive',
    confirm: {
      title: 'Disable this automation?',
      message:
        'The automation will be paused immediately. No further runs will start until you re-enable it from the automation page.',
      confirmText: 'Disable Automation',
    },
  },
};

const REASON_LABEL: Record<ApprovalReason, { label: string; tone: string }> = {
  contract_violation: {
    label: 'Contract Violation',
    tone: 'bg-amber-500/15 text-amber-400',
  },
  budget_exhausted: {
    label: 'Budget Exhausted',
    tone: 'bg-red-500/15 text-red-400',
  },
  tier_escalation: {
    label: 'Tier Escalation',
    tone: 'bg-violet-500/15 text-violet-400',
  },
  credential_missing: {
    label: 'Credential Missing',
    tone: 'bg-blue-500/15 text-blue-400',
  },
  manual: {
    label: 'Manual',
    tone: 'bg-[var(--surface-hover)] text-[var(--text-muted)]',
  },
};

/**
 * Right-side drawer for resolving a single pending approval. Mirrors
 * the AppDetailsDrawer styling (backdrop + fixed aside) so we don't
 * need to introduce a new dialog primitive.
 */
export default function ApprovalDrawer({ approval, onClose, onResolved }: Props) {
  const [submitting, setSubmitting] = useState<ApprovalChoice | null>(null);
  const [notes, setNotes] = useState('');
  const [pendingConfirm, setPendingConfirm] = useState<ApprovalChoice | null>(null);
  const [artifacts, setArtifacts] = useState<AutomationRunArtifactOut[] | null>(null);
  const [artifactsError, setArtifactsError] = useState<string | null>(null);

  const open = approval !== null;

  // Reset transient state whenever the drawer changes target.
  useEffect(() => {
    setNotes('');
    setSubmitting(null);
    setPendingConfirm(null);
    setArtifacts(null);
    setArtifactsError(null);
  }, [approval?.id]);

  // Fetch artefact metadata for the run, then narrow down to the ones
  // listed in ``context_artifacts``. We use the existing run-artifacts
  // endpoint rather than introducing a new per-id fetch.
  useEffect(() => {
    if (!approval) return;
    const refIds = approval.context_artifacts ?? [];
    if (refIds.length === 0) {
      setArtifacts([]);
      return;
    }
    let cancelled = false;
    automationsApi
      .listRunArtifacts(approval.automation_id, approval.run_id)
      .then((all) => {
        if (cancelled) return;
        const wanted = new Set(refIds);
        setArtifacts(all.filter((a) => wanted.has(a.id)));
      })
      .catch((err: Error) => {
        if (cancelled) return;
        setArtifactsError(err.message ?? 'Failed to load artifacts');
      });
    return () => {
      cancelled = true;
    };
  }, [approval]);

  const submit = useCallback(
    async (choice: ApprovalChoice, payloadNotes?: string) => {
      if (!approval) return;
      setSubmitting(choice);
      try {
        const payload: ApprovalResponse = { choice };
        if (payloadNotes && payloadNotes.trim()) payload.notes = payloadNotes.trim();
        await automationsApi.approvals.respond(
          approval.automation_id,
          approval.id,
          payload
        );
        toast.success(
          choice === 'request_changes' ? 'Sent changes back to the agent' : 'Response recorded'
        );
        onResolved?.(approval.id);
        onClose();
      } catch (err) {
        const msg =
          (err as { response?: { data?: { detail?: string } } }).response?.data?.detail ||
          (err as Error).message ||
          'Failed to submit response';
        toast.error(msg);
      } finally {
        setSubmitting(null);
      }
    },
    [approval, onClose, onResolved]
  );

  const handleChoice = useCallback(
    (choice: ApprovalChoice) => {
      const meta = CHOICE_META[choice];
      if (meta.requiresNotes && !notes.trim()) {
        toast.error('Please add a note describing the requested changes.');
        return;
      }
      if (meta.confirm) {
        setPendingConfirm(choice);
        return;
      }
      submit(choice, notes);
    },
    [notes, submit]
  );

  const reasonMeta = useMemo(() => {
    if (!approval) return null;
    return REASON_LABEL[approval.reason] ?? REASON_LABEL.manual;
  }, [approval]);

  if (!open || !approval) return null;

  const expiresLabel = formatExpiry(approval.expires_at);
  const allowedChoices = (approval.options?.length
    ? approval.options
    : (Object.keys(CHOICE_META) as ApprovalChoice[])) as ApprovalChoice[];

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/40 z-40"
        onClick={() => (submitting ? undefined : onClose())}
        data-testid="approval-drawer-backdrop"
      />

      <aside
        className="fixed right-0 top-0 bottom-0 w-full max-w-[640px] bg-[var(--surface)] border-l border-[var(--border)] z-50 flex flex-col shadow-2xl"
        data-testid="approval-drawer"
        role="dialog"
        aria-label="Approval request"
      >
        <header className="flex items-start justify-between px-5 py-4 border-b border-[var(--border)]">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 mb-1">
              <span
                className={`inline-flex items-center gap-1 rounded-[var(--radius-small)] px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider ${reasonMeta?.tone ?? ''}`}
              >
                {reasonMeta?.label ?? approval.reason}
              </span>
              <span className="text-[10px] uppercase tracking-wider text-[var(--text-subtle)]">
                {expiresLabel.text}
              </span>
            </div>
            <Link
              to={`/automations/${approval.automation_id}`}
              className="font-heading text-lg font-semibold text-[var(--text)] truncate hover:underline block"
            >
              {approval.automation_name || 'Untitled automation'}
            </Link>
            <Link
              to={`/automations/${approval.automation_id}/runs/${approval.run_id}`}
              className="text-[11px] text-[var(--text-muted)] hover:underline"
            >
              View run
            </Link>
          </div>
          <button
            onClick={onClose}
            disabled={submitting !== null}
            className="p-1.5 rounded-md hover:bg-white/5 text-[var(--text-muted)] disabled:opacity-50"
            aria-label="Close drawer"
            data-testid="approval-drawer-close"
          >
            <X className="w-4 h-4" />
          </button>
        </header>

        <div className="flex-1 min-h-0 overflow-y-auto p-5 space-y-5">
          {/* Summary */}
          <Section title="Summary">
            <p className="text-sm text-[var(--text)]">
              {approval.context.summary || '(no summary provided)'}
            </p>
          </Section>

          {/* Tool + params */}
          {approval.context.tool_name && (
            <Section title="Tool">
              <code className="text-xs text-[var(--text)] bg-[var(--surface-hover)] px-2 py-1 rounded-[var(--radius-small)] inline-block">
                {approval.context.tool_name}
              </code>
              {approval.context.tool_call_params ? (
                <pre className="mt-2 max-h-72 overflow-auto rounded-[var(--radius-small)] border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-[11px] font-mono text-[var(--text-muted)] whitespace-pre-wrap break-words">
                  {safeStringify(approval.context.tool_call_params)}
                </pre>
              ) : null}
            </Section>
          )}

          {/* Budget context */}
          {(approval.context.current_spend_usd != null ||
            approval.context.requested_extension_usd != null) && (
            <Section title="Budget">
              <dl className="text-xs grid grid-cols-[120px_1fr] gap-y-1">
                {approval.context.current_spend_usd != null && (
                  <>
                    <dt className="text-[var(--text-subtle)]">Current spend</dt>
                    <dd className="text-[var(--text)] tabular-nums">
                      ${approval.context.current_spend_usd}
                    </dd>
                  </>
                )}
                {approval.context.requested_extension_usd != null && (
                  <>
                    <dt className="text-[var(--text-subtle)]">Extension request</dt>
                    <dd className="text-[var(--text)] tabular-nums">
                      ${approval.context.requested_extension_usd}
                    </dd>
                  </>
                )}
              </dl>
            </Section>
          )}

          {/* Artefacts */}
          {(approval.context_artifacts?.length ?? 0) > 0 && (
            <Section title={`Artifacts (${approval.context_artifacts.length})`}>
              {artifactsError ? (
                <div className="text-xs text-[var(--status-error)]">{artifactsError}</div>
              ) : artifacts === null ? (
                <div className="text-xs text-[var(--text-subtle)]">Loading artifacts…</div>
              ) : artifacts.length === 0 ? (
                <div className="text-xs text-[var(--text-subtle)]">
                  Referenced artifacts could not be found.
                </div>
              ) : (
                <div className="flex flex-col gap-2">
                  {artifacts.map((a) => (
                    <ArtifactPreview
                      key={a.id}
                      automationId={approval.automation_id}
                      runId={approval.run_id}
                      artifact={a}
                    />
                  ))}
                </div>
              )}
            </Section>
          )}

          {/* Other context fields (catch-all) */}
          {hasExtraContext(approval.context) && (
            <Section title="Additional context">
              <pre className="max-h-48 overflow-auto rounded-[var(--radius-small)] border border-[var(--border)] bg-[var(--bg)] px-3 py-2 text-[11px] font-mono text-[var(--text-muted)] whitespace-pre-wrap break-words">
                {safeStringify(extraContext(approval.context))}
              </pre>
            </Section>
          )}

          {/* Notes — only relevant when one of the choices needs them. */}
          <Section title="Notes (optional)">
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Add context the agent should see (required for Request Changes)…"
              rows={3}
              className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)] placeholder-[var(--text-subtle)] resize-y"
            />
          </Section>
        </div>

        {/* Footer — choice grid */}
        <footer className="border-t border-[var(--border)] p-4 grid grid-cols-1 gap-2 bg-[var(--bg)]">
          {allowedChoices.map((choice) => {
            const meta = CHOICE_META[choice];
            if (!meta) return null;
            const busy = submitting !== null;
            const tone =
              meta.tone === 'primary'
                ? 'btn btn-filled'
                : meta.tone === 'destructive'
                  ? 'btn border-red-500/40 text-red-400 hover:bg-red-500/10'
                  : 'btn';
            return (
              <button
                key={choice}
                type="button"
                onClick={() => handleChoice(choice)}
                disabled={busy}
                className={`${tone} w-full justify-start text-left disabled:opacity-50`}
                data-testid={`approval-choice-${choice}`}
              >
                <div className="flex flex-col items-start min-w-0">
                  <span className="text-xs font-medium">
                    {submitting === choice ? 'Submitting…' : meta.label}
                  </span>
                  <span className="text-[10px] text-[var(--text-subtle)] font-normal whitespace-normal">
                    {meta.description}
                  </span>
                </div>
              </button>
            );
          })}
        </footer>
      </aside>

      {/* Confirm dialog for destructive / contract-mutating choices */}
      <ConfirmDialog
        isOpen={pendingConfirm !== null}
        onClose={() => (submitting ? undefined : setPendingConfirm(null))}
        onConfirm={() => {
          const choice = pendingConfirm;
          setPendingConfirm(null);
          if (choice) submit(choice, notes);
        }}
        title={pendingConfirm ? CHOICE_META[pendingConfirm].confirm!.title : ''}
        message={pendingConfirm ? CHOICE_META[pendingConfirm].confirm!.message : ''}
        confirmText={
          pendingConfirm ? CHOICE_META[pendingConfirm].confirm!.confirmText : 'Confirm'
        }
        variant={pendingConfirm === 'deny_and_disable_automation' ? 'danger' : 'warning'}
        isLoading={submitting !== null}
      />
    </>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="text-[10px] uppercase tracking-wider text-[var(--text-subtle)] mb-1.5">
        {title}
      </h3>
      {children}
    </section>
  );
}

function safeStringify(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

const KNOWN_KEYS = new Set([
  'summary',
  'tool_name',
  'tool_call_params',
  'current_spend_usd',
  'requested_extension_usd',
]);

function hasExtraContext(ctx: Record<string, unknown>): boolean {
  return Object.keys(ctx).some((k) => !KNOWN_KEYS.has(k));
}

function extraContext(ctx: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(ctx).filter(([k]) => !KNOWN_KEYS.has(k)));
}

function formatExpiry(iso: string | null): { text: string; expired: boolean } {
  if (!iso) return { text: 'No expiry', expired: false };
  const ts = Date.parse(iso);
  if (Number.isNaN(ts)) return { text: 'No expiry', expired: false };
  const diff = ts - Date.now();
  if (diff <= 0) return { text: 'Expired', expired: true };
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 60) return { text: `Expires in ${minutes}m`, expired: false };
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return { text: `Expires in ${hours}h`, expired: false };
  const days = Math.floor(hours / 24);
  return { text: `Expires in ${days}d`, expired: false };
}
