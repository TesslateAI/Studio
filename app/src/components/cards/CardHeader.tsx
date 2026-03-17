import type { ReactNode } from 'react';
import { clsx } from 'clsx';

const iconSizes = {
  sm: 'w-10 h-10',
  md: 'w-11 h-11 sm:w-12 sm:h-12',
  lg: 'w-20 h-20 md:w-24 md:h-24',
} as const;

export interface CardHeaderProps {
  icon?: ReactNode;
  iconSize?: keyof typeof iconSizes;
  title: string;
  subtitle?: string;
  onSubtitleClick?: (e: React.MouseEvent) => void;
  /** Extra content to the right of the title area (e.g. status dot) */
  trailing?: ReactNode;
  className?: string;
}

export function CardHeader({
  icon,
  iconSize = 'md',
  title,
  subtitle,
  onSubtitleClick,
  trailing,
  className,
}: CardHeaderProps) {
  return (
    <div className={clsx('flex items-start gap-3 mb-3', trailing && 'pr-16', className)}>
      {icon && (
        <div
          className={clsx(
            iconSizes[iconSize],
            'rounded-xl bg-[var(--bg)] border border-[var(--border)] flex items-center justify-center overflow-hidden shrink-0 transition-colors group-hover:border-[rgba(var(--primary-rgb),0.3)]'
          )}
        >
          {icon}
        </div>
      )}
      <div className="flex-1 min-w-0">
        <h4 className="font-heading text-sm font-semibold text-[var(--text)] line-clamp-1 group-hover:text-[var(--primary)] transition-colors">
          {title}
        </h4>
        {subtitle &&
          (onSubtitleClick ? (
            <button
              onClick={onSubtitleClick}
              className="text-xs text-[var(--text-muted)] hover:text-[var(--primary)] transition-colors mt-0.5"
            >
              {subtitle}
            </button>
          ) : (
            <span className="text-xs text-[var(--text-muted)] mt-0.5 block">{subtitle}</span>
          ))}
      </div>
      {trailing}
    </div>
  );
}
