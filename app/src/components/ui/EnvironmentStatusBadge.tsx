import { ArrowsClockwise } from '@phosphor-icons/react';
import { Tooltip } from './Tooltip';
import { STATUS_MAP, type EnvironmentStatus } from './environmentStatus';

interface EnvironmentStatusBadgeProps {
  status: EnvironmentStatus;
  showTooltip?: boolean;
  size?: 'sm' | 'md';
}

export function EnvironmentStatusBadge({
  status,
  showTooltip = false,
  size = 'md',
}: EnvironmentStatusBadgeProps) {
  const cfg = STATUS_MAP[status];
  if (!cfg) return null;

  const sizeClasses = size === 'sm' ? 'px-2 py-0.5 text-[10px]' : 'px-2.5 py-1 text-[11px]';
  const dotSize = size === 'sm' ? 'w-2 h-2' : 'w-[7px] h-[7px]';
  const iconSize = size === 'sm' ? 10 : 12;

  const badge = (
    <div
      className={`flex items-center gap-1.5 ${sizeClasses} rounded-lg border font-semibold cursor-default ${cfg.className}`}
    >
      {cfg.spin ? (
        <ArrowsClockwise size={iconSize} className={`${cfg.textColor} animate-spin`} />
      ) : (
        <span className={`${dotSize} rounded-full ${cfg.dotColor}`} />
      )}
      <span className={cfg.textColor}>{cfg.label}</span>
    </div>
  );

  if (showTooltip) {
    return (
      <Tooltip content={cfg.tooltip} side="bottom" delay={100}>
        {badge}
      </Tooltip>
    );
  }
  return badge;
}
