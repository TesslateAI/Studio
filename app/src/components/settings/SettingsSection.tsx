import { type ReactNode } from 'react';

interface SettingsSectionProps {
  title: string;
  description?: string;
  children: ReactNode;
}

export function SettingsSection({ title, description, children }: SettingsSectionProps) {
  return (
    <div className="max-w-3xl mx-auto p-4 md:p-5">
      {/* Section Header */}
      <div className="mb-5">
        <h1 className="text-sm font-semibold text-[var(--text)]">{title}</h1>
        {description && <p className="mt-1 text-[11px] text-[var(--text-muted)]">{description}</p>}
      </div>

      {/* Section Content */}
      <div className="space-y-4">{children}</div>
    </div>
  );
}
