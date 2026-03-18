import type { ReactNode } from 'react';
import { clsx } from 'clsx';

export interface CardActionsProps {
  children: ReactNode;
  className?: string;
}

export function CardActions({ children, className }: CardActionsProps) {
  return (
    <div
      className={clsx(
        'mt-auto pt-3 border-t border-[var(--border)] flex flex-wrap items-center gap-2',
        className
      )}
    >
      {children}
    </div>
  );
}
