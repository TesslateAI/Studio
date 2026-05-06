import type { AutomationRunStatus } from '../../../types/automations';
import { humanizeRunStatus } from '../utils/humanize';

/**
 * Small coloured chip for an :class:`AutomationRun.status` value.
 */
export function RunStatusBadge({ status }: { status: AutomationRunStatus }) {
  const className = STATUS_STYLES[status] ?? 'bg-[var(--surface-hover)] text-[var(--text-subtle)]';
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-[var(--radius-small)] px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider ${className}`}
    >
      {humanizeRunStatus(status)}
    </span>
  );
}

const STATUS_STYLES: Record<AutomationRunStatus, string> = {
  queued: 'bg-[var(--surface-hover)] text-[var(--text-muted)]',
  running: 'bg-blue-500/15 text-blue-400',
  awaiting_approval: 'bg-amber-500/15 text-amber-400',
  paused: 'bg-[var(--surface-hover)] text-[var(--text-muted)]',
  succeeded: 'bg-emerald-500/15 text-emerald-400',
  failed: 'bg-red-500/15 text-red-400',
  cancelled: 'bg-[var(--surface-hover)] text-[var(--text-subtle)]',
  expired: 'bg-red-500/10 text-red-300',
};
