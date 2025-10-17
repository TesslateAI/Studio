import { Settings } from 'lucide-react';

interface SettingsPanelProps {
  projectId: number;
  onLockToggle?: (locked: boolean) => void;
}

export function SettingsPanel({ projectId, onLockToggle }: SettingsPanelProps) {
  return (
    <div className="h-full flex items-center justify-center p-8">
      <div className="text-center max-w-md">
        <div className="mb-6 flex justify-center">
          <div className="w-24 h-24 rounded-2xl bg-gradient-to-br from-[var(--primary)]/20 to-purple-500/20 flex items-center justify-center backdrop-blur-sm border border-white/10">
            <Settings className="w-12 h-12 text-[var(--primary)]" />
          </div>
        </div>
        <h3 className="text-2xl font-bold text-white mb-3">
          Coming Soon
        </h3>
        <p className="text-gray-400 leading-relaxed">
          Project settings will allow you to customize your development environment,
          configure build options, and manage project preferences.
        </p>
        <div className="mt-8 pt-8 border-t border-white/10">
          <p className="text-sm text-gray-500">
            Stay tuned for updates!
          </p>
        </div>
      </div>
    </div>
  );
}
