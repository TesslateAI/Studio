import type { AutomationRunStatus } from '../../../types/automations';

/**
 * Small coloured chip for an :class:`AutomationRun.status` value.
 * Phase 1: text + colour-coding only — no animation.
 */
export function RunStatusBadge({ status }: { status: AutomationRunStatus }) {
  const { label, className } = mapStatus(status);
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-[var(--radius-small)] px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider ${className}`}
    >
      {label}
    </span>
  );
}

function mapStatus(status: AutomationRunStatus): { label: string; className: string } {
  switch (status) {
    case 'queued':
      return { label: 'Queued', className: 'bg-[var(--surface-hover)] text-[var(--text-muted)]' };
    case 'running':
      return { label: 'Running', className: 'bg-blue-500/15 text-blue-400' };
    case 'awaiting_approval':
      return { label: 'Awaiting', className: 'bg-amber-500/15 text-amber-400' };
    case 'paused':
      return { label: 'Paused', className: 'bg-[var(--surface-hover)] text-[var(--text-muted)]' };
    case 'succeeded':
      return { label: 'Succeeded', className: 'bg-emerald-500/15 text-emerald-400' };
    case 'failed':
      return { label: 'Failed', className: 'bg-red-500/15 text-red-400' };
    case 'cancelled':
      return { label: 'Cancelled', className: 'bg-[var(--surface-hover)] text-[var(--text-subtle)]' };
    case 'expired':
      return { label: 'Expired', className: 'bg-red-500/10 text-red-300' };
    default:
      return {
        label: String(status || 'unknown'),
        className: 'bg-[var(--surface-hover)] text-[var(--text-subtle)]',
      };
  }
}
