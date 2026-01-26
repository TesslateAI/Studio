import { Shield } from 'lucide-react';
import { SettingsSection, SettingsGroup, SettingsItem } from '../../components/settings';
import toast from 'react-hot-toast';

export default function SecuritySettings() {
  return (
    <SettingsSection
      title="Security"
      description="Manage your account security settings"
    >
      <SettingsGroup title="Password">
        <SettingsItem
          label="Change password"
          description="Update your account password"
          control={
            <button
              onClick={() => toast('Password change coming soon!')}
              className="px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-sm font-medium text-[var(--text)] hover:bg-white/10 transition-colors min-h-[44px]"
            >
              Change
            </button>
          }
        />
      </SettingsGroup>

      <SettingsGroup title="Two-factor authentication">
        <SettingsItem
          label="Enable 2FA"
          description="Add an extra layer of security to your account"
          control={
            <button
              onClick={() => toast('Two-factor authentication coming soon!')}
              className="px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-sm font-medium text-[var(--text)] hover:bg-white/10 transition-colors min-h-[44px]"
            >
              Set up
            </button>
          }
        />
      </SettingsGroup>

      <SettingsGroup title="Sessions">
        <SettingsItem
          label="Active sessions"
          description="View and manage your active sessions"
          control={
            <button
              onClick={() => toast('Session management coming soon!')}
              className="px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-sm font-medium text-[var(--text)] hover:bg-white/10 transition-colors min-h-[44px]"
            >
              View
            </button>
          }
        />
      </SettingsGroup>

      {/* Info */}
      <div className="p-4 bg-[var(--surface)] border border-white/10 rounded-xl">
        <div className="flex items-start gap-3">
          <Shield size={20} className="text-[var(--text)]/60 mt-0.5 flex-shrink-0" />
          <div className="text-sm text-[var(--text)]/60">
            <p className="font-medium mb-1">Security features are coming soon</p>
            <p className="text-xs">
              We're working on additional security features including password management,
              two-factor authentication, and session management.
            </p>
          </div>
        </div>
      </div>
    </SettingsSection>
  );
}
