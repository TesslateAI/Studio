import { ReactNode } from 'react';

interface SettingsSectionProps {
  title: string;
  description?: string;
  children: ReactNode;
}

export function SettingsSection({ title, description, children }: SettingsSectionProps) {
  return (
    <div className="max-w-3xl mx-auto p-4 md:p-8">
      {/* Section Header */}
      <div className="mb-6 md:mb-8">
        <h1 className="text-2xl md:text-3xl font-bold text-[var(--text)]">{title}</h1>
        {description && (
          <p className="mt-2 text-sm md:text-base text-[var(--text)]/60">{description}</p>
        )}
      </div>

      {/* Section Content */}
      <div className="space-y-6">{children}</div>
    </div>
  );
}
