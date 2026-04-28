import { useCallback, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowClockwise, BellRinging, Robot } from '@phosphor-icons/react';
import { usePendingApprovals } from '../../hooks/usePendingApprovals';
import type {
  ApprovalReason,
  ApprovalRequest,
} from '../../types/automations';
import ApprovalDrawer from './components/ApprovalDrawer';

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
 * /automations/approvals — cross-automation pending-approvals list.
 *
 * Polls every 30s via :func:`usePendingApprovals` (the same hook that
 * feeds the sidebar badge, so they stay in lockstep without extra
 * coordination). Optimistic-removes a row when the drawer reports a
 * successful resolution; the next poll cycle reconciles.
 */
export default function ApprovalsPage() {
  const navigate = useNavigate();
  const { approvals, loading, error, refresh } = usePendingApprovals({ pollMs: 30_000 });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  /** Optimistic suppression list — items resolved this session. */
  const [suppressed, setSuppressed] = useState<Set<string>>(() => new Set());

  const visible = useMemo(
    () => approvals.filter((a) => !suppressed.has(a.id)),
    [approvals, suppressed]
  );
  const selected = useMemo(
    () => approvals.find((a) => a.id === selectedId) ?? null,
    [approvals, selectedId]
  );

  const handleResolved = useCallback(
    (id: string) => {
      setSuppressed((prev) => {
        const next = new Set(prev);
        next.add(id);
        return next;
      });
      setSelectedId(null);
      // Trigger a fresh server fetch so we don't rely on the optimistic
      // hide forever.
      refresh();
    },
    [refresh]
  );

  return (
    <>
      {/* Header bar — mirrors AutomationsListPage */}
      <div className="flex-shrink-0">
        <div
          className="h-10 flex items-center justify-between gap-[6px]"
          style={{
            paddingLeft: '18px',
            paddingRight: '4px',
            borderBottom: 'var(--border-width) solid var(--border)',
          }}
        >
          <div className="flex items-center gap-2 flex-1 min-w-0">
            <button
              onClick={() => navigate('/automations')}
              className="text-[10px] uppercase tracking-wider text-[var(--text-subtle)] hover:text-[var(--text)] transition-colors"
            >
              Automations
            </button>
            <span className="text-[10px] text-[var(--text-subtle)]">/</span>
            <h2 className="text-xs font-semibold text-[var(--text)] truncate">
              Approvals
              {visible.length > 0 && (
                <span className="ml-1.5 text-[var(--text-muted)] font-normal">
                  ({visible.length})
                </span>
              )}
            </h2>
          </div>
          <button
            onClick={() => refresh()}
            className="btn btn-icon"
            aria-label="Refresh approvals"
            title="Refresh"
            disabled={loading}
          >
            <ArrowClockwise className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {error && (
          <div className="px-6 pt-4">
            <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-3 text-xs text-[var(--status-error)]">
              {error}
            </div>
          </div>
        )}

        {loading && approvals.length === 0 ? (
          <div className="p-8 text-sm text-[var(--text-muted)]">Loading approvals…</div>
        ) : visible.length === 0 ? (
          <EmptyState />
        ) : (
          <div className="px-6 py-6 flex flex-col gap-3">
            {visible.map((approval) => (
              <ApprovalCard
                key={approval.id}
                approval={approval}
                onReview={() => setSelectedId(approval.id)}
              />
            ))}
          </div>
        )}
      </div>

      <ApprovalDrawer
        approval={selected}
        onClose={() => setSelectedId(null)}
        onResolved={handleResolved}
      />
    </>
  );
}

function ApprovalCard({
  approval,
  onReview,
}: {
  approval: ApprovalRequest;
  onReview: () => void;
}) {
  const reason = REASON_LABEL[approval.reason] ?? REASON_LABEL.manual;
  const expiry = formatExpiry(approval.expires_at);
  const requested = formatRelative(approval.requested_at);
  const tool = approval.context.tool_name ?? null;
  const paramSummary = abbreviateParams(approval.context.tool_call_params);

  return (
    <article
      className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-4 hover:border-[var(--border-hover)] transition-colors"
      data-testid={`approval-card-${approval.id}`}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 mb-1">
            <span
              className={`inline-flex items-center gap-1 rounded-[var(--radius-small)] px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider ${reason.tone}`}
            >
              {reason.label}
            </span>
            <span
              className={`text-[10px] uppercase tracking-wider ${
                expiry.expired ? 'text-red-400 font-semibold' : 'text-[var(--text-subtle)]'
              }`}
              title={approval.expires_at ?? undefined}
            >
              {expiry.text}
            </span>
          </div>

          <Link
            to={`/automations/${approval.automation_id}`}
            className="text-sm font-semibold text-[var(--text)] hover:underline block truncate"
            onClick={(e) => e.stopPropagation()}
          >
            {approval.automation_name || 'Untitled automation'}
          </Link>

          <p className="text-xs text-[var(--text-muted)] mt-1 line-clamp-2">
            {approval.context.summary || '(no summary provided)'}
          </p>

          {(tool || paramSummary) && (
            <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-[var(--text-subtle)]">
              {tool && (
                <code className="bg-[var(--surface-hover)] px-1.5 py-0.5 rounded-[var(--radius-small)] text-[var(--text-muted)]">
                  {tool}
                </code>
              )}
              {paramSummary && (
                <span className="font-mono truncate max-w-[60ch]">{paramSummary}</span>
              )}
            </div>
          )}

          <div className="mt-2 text-[11px] text-[var(--text-subtle)]">
            Requested {requested}
          </div>
        </div>

        <button onClick={onReview} className="btn btn-filled flex-shrink-0">
          Review
        </button>
      </div>
    </article>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] px-6 text-center">
      <div className="h-16 w-16 rounded-[var(--radius)] bg-[var(--surface-hover)] border border-[var(--border)] flex items-center justify-center mb-4 relative">
        <Robot className="w-8 h-8 text-[var(--text-subtle)]" />
        <BellRinging
          weight="fill"
          className="w-4 h-4 text-[var(--text-subtle)] absolute -bottom-1 -right-1 bg-[var(--surface)] rounded-full p-0.5"
        />
      </div>
      <h1 className="text-sm font-semibold text-[var(--text)] mb-2">No approvals pending</h1>
      <p className="text-xs text-[var(--text-muted)] max-w-md">
        When an automation needs your input — to extend a budget, escalate compute, or
        confirm a sensitive action — it will appear here.
      </p>
    </div>
  );
}

function abbreviateParams(params: Record<string, unknown> | undefined): string | null {
  if (!params || typeof params !== 'object') return null;
  const entries = Object.entries(params);
  if (entries.length === 0) return null;
  const parts: string[] = [];
  for (const [k, v] of entries.slice(0, 3)) {
    let valStr: string;
    if (v === null || v === undefined) {
      valStr = String(v);
    } else if (typeof v === 'string') {
      valStr = v.length > 40 ? `"${v.slice(0, 40)}…"` : `"${v}"`;
    } else if (typeof v === 'number' || typeof v === 'boolean') {
      valStr = String(v);
    } else {
      valStr = '{…}';
    }
    parts.push(`${k}=${valStr}`);
  }
  if (entries.length > 3) parts.push(`+${entries.length - 3} more`);
  return parts.join(', ');
}

function formatRelative(iso: string): string {
  const ts = Date.parse(iso);
  if (Number.isNaN(ts)) return iso;
  const diff = Date.now() - ts;
  if (diff < 60_000) return 'just now';
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
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
