import { useState } from 'react';
import { Shield, CheckCircle } from 'lucide-react';
import { SettingsSection, SettingsGroup, SettingsItem } from '../../components/settings';
import { PulsingGridSpinner } from '../../components/PulsingGridSpinner';
import { useAuth } from '../../contexts/AuthContext';
import { authApi } from '../../lib/api';
import toast from 'react-hot-toast';

export default function SecuritySettings() {
  const { user } = useAuth();
  const [loading, setLoading] = useState(false);

  const handleChangePassword = async () => {
    if (!user?.email) return;

    setLoading(true);
    try {
      await authApi.forgotPassword(user.email);
      toast.success('Password reset link sent to your email');
    } catch {
      // Show success anyway to avoid leaking info
      toast.success('Password reset link sent to your email');
    } finally {
      setLoading(false);
    }
  };

  return (
    <SettingsSection title="Security" description="Manage your account security settings">
      <SettingsGroup title="Password">
        <SettingsItem
          label="Change password"
          description="We'll send a password reset link to your email"
          control={
            <button
              onClick={handleChangePassword}
              disabled={loading}
              className="px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-sm font-medium text-[var(--text)] hover:bg-white/10 disabled:opacity-50 disabled:cursor-not-allowed transition-colors min-h-[44px]"
            >
              {loading ? (
                <div className="flex items-center gap-2">
                  <PulsingGridSpinner size={14} />
                  <span>Sending...</span>
                </div>
              ) : (
                'Change'
              )}
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
