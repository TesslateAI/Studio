import { ReactNode } from 'react';

interface SettingsGroupProps {
  title: string;
  children: ReactNode;
}

export function SettingsGroup({ title, children }: SettingsGroupProps) {
  return (
    <div className="bg-[var(--surface)] border border-white/10 rounded-xl overflow-hidden">
      {/* Group Header */}
      <div className="px-4 md:px-6 py-3 md:py-4 border-b border-white/10">
        <h2 className="text-sm font-semibold text-[var(--text)]">{title}</h2>
      </div>

      {/* Group Items */}
      <div className="divide-y divide-white/10">{children}</div>
    </div>
  );
}
