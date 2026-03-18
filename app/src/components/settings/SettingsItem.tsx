import { ReactNode } from 'react';

interface SettingsItemProps {
  label: string;
  description?: string;
  control: ReactNode;
}

export function SettingsItem({ label, description, control }: SettingsItemProps) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 sm:gap-4 px-4 py-3 hover:bg-[var(--surface)] transition-colors">
      {/* Label and Description */}
      <div className="flex-1 min-w-0">
        <div className="text-xs font-medium text-[var(--text)]">{label}</div>
        {description && (
          <div className="text-[11px] text-[var(--text-subtle)] mt-0.5">{description}</div>
        )}
      </div>

      {/* Control */}
      <div className="flex-shrink-0">{control}</div>
    </div>
  );
}
