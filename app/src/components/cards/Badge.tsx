import { cva, type VariantProps } from 'class-variance-authority';
import { clsx } from 'clsx';
import type { ReactNode } from 'react';

const badgeVariants = cva(
  'inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium whitespace-nowrap',
  {
    variants: {
      intent: {
        success: 'bg-[var(--status-success)]/10 text-[var(--status-success)]',
        info: 'bg-[var(--status-info)]/10 text-[var(--status-info)]',
        warning: 'bg-[var(--status-warning)]/10 text-[var(--status-warning)]',
        primary: 'bg-[var(--primary)]/10 text-[var(--primary)]',
        accent: 'bg-[var(--accent)]/10 text-[var(--accent)]',
        muted: 'bg-[var(--surface-hover)] text-[var(--text-muted)]',
        purple: 'bg-[var(--status-purple)]/10 text-[var(--status-purple)]',
      },
    },
    defaultVariants: {
      intent: 'muted',
    },
  }
);

export interface BadgeProps extends VariantProps<typeof badgeVariants> {
  icon?: ReactNode;
  children: ReactNode;
  className?: string;
}

export function Badge({ intent, icon, children, className }: BadgeProps) {
  return (
    <span className={clsx(badgeVariants({ intent }), className)}>
      {icon}
      {children}
    </span>
  );
}
