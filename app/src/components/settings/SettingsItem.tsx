import { ReactNode } from 'react';

interface SettingsItemProps {
  label: string;
  description?: string;
  control: ReactNode;
}

export function SettingsItem({ label, description, control }: SettingsItemProps) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 sm:gap-4 px-4 md:px-6 py-3 md:py-4 min-h-[48px] hover:bg-white/[0.02] transition-colors">
      {/* Label and Description */}
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium text-[var(--text)]">{label}</div>
        {description && (
          <div className="text-xs text-[var(--text)]/50 mt-0.5">{description}</div>
        )}
      </div>

      {/* Control */}
      <div className="flex-shrink-0">{control}</div>
    </div>
  );
}
