import { Shield, CheckCircle } from 'lucide-react';
import { SettingsSection, SettingsGroup, SettingsItem } from '../../components/settings';
import toast from 'react-hot-toast';

export default function SecuritySettings() {
  return (
    <SettingsSection title="Security" description="Manage your account security settings">
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
          label="Email verification is active"
          description="A 6-digit verification code is sent to your email on every email/password login"
          control={
            <span className="flex items-center gap-1.5 text-green-400 text-sm font-medium">
              <CheckCircle size={16} />
              Active
            </span>
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
            <p className="font-medium mb-1">Your account is protected</p>
            <p className="text-xs">
              A verification code is sent to your email each time you sign in with email and
              password. OAuth logins (Google, GitHub) are not affected.
            </p>
          </div>
        </div>
      </div>
    </SettingsSection>
  );
}
