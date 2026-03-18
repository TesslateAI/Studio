import { ReactNode } from 'react';

interface SettingsGroupProps {
  title: string;
  children: ReactNode;
}

export function SettingsGroup({ title, children }: SettingsGroupProps) {
  return (
    <div className="bg-[var(--surface-hover)] border border-[var(--border)] rounded-[var(--radius)] overflow-hidden">
      {/* Group Header */}
      <div className="px-4 py-2.5 border-b border-[var(--border)]">
        <h2 className="text-[11px] font-medium text-[var(--text-muted)]">{title}</h2>
      </div>

      {/* Group Items */}
      <div className="divide-y divide-[var(--border)]">{children}</div>
    </div>
  );
}
