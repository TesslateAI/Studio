import { clsx } from 'clsx';

export interface StatusDotProps {
  active: boolean;
  className?: string;
}

export function StatusDot({ active, className }: StatusDotProps) {
  return (
    <div className={clsx('absolute top-3 right-3 sm:top-4 sm:right-4', className)}>
      {active ? (
        <div className="w-4 h-4 rounded-full border-2 border-[var(--status-success)] flex items-center justify-center">
          <div className="w-2 h-2 rounded-full bg-[var(--status-success)]" />
        </div>
      ) : (
        <div className="w-4 h-4 rounded-full border-2 border-[var(--text)]/20" />
      )}
    </div>
  );
}
