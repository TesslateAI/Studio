import { useState, useEffect, useCallback } from 'react';
import toast from 'react-hot-toast';
import {
  Send,
  MessageSquare,
  Hash,
  Phone,
  Shield,
  Terminal,
  Link,
  Unlink,
  Plus,
  Wifi,
  WifiOff,
} from 'lucide-react';
import { gatewayApi } from '../../lib/api';
import { LoadingSpinner } from '../../components/PulsingGridSpinner';
import { SettingsSection, SettingsGroup } from '../../components/settings';
import { ConfirmDialog } from '../../components/modals/ConfirmDialog';

interface Identity {
  id: string;
  platform: string;
  platform_user_id: string;
  platform_username: string | null;
  is_verified: boolean;
  paired_at: string | null;
  created_at: string;
}

interface GatewayStatus {
  shard: number | null;
  adapters: number | null;
  active_sessions: number | null;
  heartbeat: string | null;
  status: string;
}

interface Platform {
  name: string;
  display_name: string;
}

const PLATFORM_ICONS: Record<string, React.ReactNode> = {
  telegram: <Send size={18} />,
  discord: <MessageSquare size={18} />,
  slack: <Hash size={18} />,
  whatsapp: <Phone size={18} />,
  signal: <Shield size={18} />,
  cli: <Terminal size={18} />,
};

function getPlatformIcon(platform: string) {
  return PLATFORM_ICONS[platform.toLowerCase()] || <Link size={18} />;
}

function formatDate(dateString: string): string {
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(new Date(dateString));
}

export default function ConnectionsSettings() {
  const [identities, setIdentities] = useState<Identity[]>([]);
  const [status, setStatus] = useState<GatewayStatus | null>(null);
  const [platforms, setPlatforms] = useState<Platform[]>([]);
  const [loading, setLoading] = useState(true);

  // Link form
  const [selectedPlatform, setSelectedPlatform] = useState('');
  const [pairingCode, setPairingCode] = useState('');
  const [linking, setLinking] = useState(false);

  // Unlink
  const [unlinkingId, setUnlinkingId] = useState<string | null>(null);
  const [confirmDialog, setConfirmDialog] = useState<{
    isOpen: boolean;
    title: string;
    message: string;
    confirmText: string;
    variant: 'danger' | 'warning' | 'info';
    onConfirm: () => void;
  }>({
    isOpen: false,
    title: '',
    message: '',
    confirmText: 'Confirm',
    variant: 'info',
    onConfirm: () => {},
  });

  const loadData = useCallback(async () => {
    try {
      const [identitiesRes, statusRes, platformsRes] = await Promise.all([
        gatewayApi.listIdentities(),
        gatewayApi.getStatus(),
        gatewayApi.getPlatforms(),
      ]);
      setIdentities(identitiesRes as Identity[]);
      setStatus(statusRes as GatewayStatus);
      setPlatforms(platformsRes as unknown as Platform[]);
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to load connections');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleLink = async () => {
    if (!selectedPlatform || !pairingCode.trim()) return;
    setLinking(true);
    try {
      await gatewayApi.verifyPairing(selectedPlatform, pairingCode.trim());
      toast.success('Platform linked successfully');
      setPairingCode('');
      setSelectedPlatform('');
      loadData();
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string | unknown[] } } };
      const detail = err.response?.data?.detail;
      const msg = typeof detail === 'string' ? detail : 'Invalid or expired pairing code';
      toast.error(msg);
    } finally {
      setLinking(false);
    }
  };

  const handleUnlink = (identity: Identity) => {
    setConfirmDialog({
      isOpen: true,
      title: `Unlink ${identity.platform}`,
      message: `This will disconnect "${identity.platform_username}" on ${identity.platform}. You will need to re-pair to restore the connection.`,
      confirmText: 'Unlink',
      variant: 'danger',
      onConfirm: async () => {
        setConfirmDialog((prev) => ({ ...prev, isOpen: false }));
        setUnlinkingId(identity.id);
        try {
          await gatewayApi.unlinkIdentity(identity.id);
          toast.success('Platform unlinked');
          loadData();
        } catch (error: unknown) {
          const err = error as { response?: { data?: { detail?: string } } };
          toast.error(err.response?.data?.detail || 'Failed to unlink platform');
        } finally {
          setUnlinkingId(null);
        }
      },
    });
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--bg)]">
        <LoadingSpinner message="Loading connections..." size={60} />
      </div>
    );
  }

  return (
    <>
      <SettingsSection
        title="Connections"
        description="Link platform identities and monitor gateway status"
      >
        {/* Gateway Status */}
        <SettingsGroup title="Gateway Status">
          <div className="p-4">
            <div className="flex items-center gap-3 mb-4">
              {status?.status === 'online' ? (
                <div className="flex items-center gap-2 text-[var(--status-success)]">
                  <Wifi size={18} />
                  <span className="text-sm font-medium">Online</span>
                </div>
              ) : (
                <div className="flex items-center gap-2 text-[var(--status-error)]">
                  <WifiOff size={18} />
                  <span className="text-sm font-medium">Offline</span>
                </div>
              )}
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="p-3 bg-[var(--bg)] rounded-lg border border-[var(--border)]">
                <p className="text-[11px] text-[var(--text-muted)] mb-1">Adapters</p>
                <p className="text-lg font-semibold text-[var(--text)]">{status?.adapters ?? 0}</p>
              </div>
              <div className="p-3 bg-[var(--bg)] rounded-lg border border-[var(--border)]">
                <p className="text-[11px] text-[var(--text-muted)] mb-1">Active Sessions</p>
                <p className="text-lg font-semibold text-[var(--text)]">
                  {status?.active_sessions ?? 0}
                </p>
              </div>
            </div>
          </div>
        </SettingsGroup>

        {/* Link a Platform */}
        <SettingsGroup title="Link a Platform">
          <div className="p-4">
            <div className="space-y-4">
              <div>
                <label className="text-xs font-medium text-[var(--text)] block mb-1.5">
                  Platform
                </label>
                <select
                  value={selectedPlatform}
                  onChange={(e) => setSelectedPlatform(e.target.value)}
                  className="w-full px-3 py-2 bg-[var(--surface-hover)] border border-[var(--border)] rounded-lg text-base text-[var(--text)] placeholder-[var(--text)]/40 focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
                >
                  <option value="">Select a platform</option>
                  {platforms.map((p) => (
                    <option key={p.name} value={p.name}>
                      {p.display_name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-xs font-medium text-[var(--text)] block mb-1.5">
                  Pairing Code
                </label>
                <input
                  type="text"
                  value={pairingCode}
                  onChange={(e) => setPairingCode(e.target.value)}
                  placeholder="Enter the code from your platform"
                  className="w-full px-3 py-2 bg-[var(--surface-hover)] border border-[var(--border)] rounded-lg text-base text-[var(--text)] placeholder-[var(--text)]/40 focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
                />
              </div>
              <button
                onClick={handleLink}
                disabled={!selectedPlatform || !pairingCode.trim() || linking}
                className="btn btn-filled flex items-center gap-1.5"
              >
                {linking ? (
                  <>
                    <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none">
                      <circle
                        className="opacity-25"
                        cx="12"
                        cy="12"
                        r="10"
                        stroke="currentColor"
                        strokeWidth="4"
                      />
                      <path
                        className="opacity-75"
                        fill="currentColor"
                        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                      />
                    </svg>
                    Linking...
                  </>
                ) : (
                  <>
                    <Plus size={14} />
                    Link
                  </>
                )}
              </button>
            </div>
          </div>
        </SettingsGroup>

        {/* Linked Platforms */}
        <SettingsGroup title="Linked Platforms">
          {identities.length > 0 ? (
            <div className="divide-y divide-[var(--border)]">
              {identities.map((identity) => (
                <div
                  key={identity.id}
                  className="p-4 flex items-center justify-between hover:bg-[var(--surface-hover)] transition-colors"
                >
                  <div className="flex items-center gap-3 flex-1 min-w-0">
                    <div className="w-10 h-10 rounded-lg bg-[var(--primary)]/10 flex items-center justify-center flex-shrink-0 text-[var(--primary)]">
                      {getPlatformIcon(identity.platform)}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <h4 className="font-semibold text-sm text-[var(--text)] capitalize">
                          {identity.platform}
                        </h4>
                      </div>
                      <p className="text-xs text-[var(--text-muted)] truncate">
                        {identity.platform_username}
                      </p>
                      <p className="text-[11px] text-[var(--text-subtle)] mt-0.5">
                        {identity.paired_at
                          ? `Paired ${formatDate(identity.paired_at)}`
                          : 'Not paired'}
                      </p>
                    </div>
                  </div>
                  <button
                    onClick={() => handleUnlink(identity)}
                    disabled={unlinkingId === identity.id}
                    className="p-2 text-[var(--text-subtle)] hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors disabled:opacity-50 flex-shrink-0"
                    title="Unlink"
                  >
                    {unlinkingId === identity.id ? (
                      <svg
                        className="w-[18px] h-[18px] animate-spin"
                        viewBox="0 0 24 24"
                        fill="none"
                      >
                        <circle
                          className="opacity-25"
                          cx="12"
                          cy="12"
                          r="10"
                          stroke="currentColor"
                          strokeWidth="4"
                        />
                        <path
                          className="opacity-75"
                          fill="currentColor"
                          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                        />
                      </svg>
                    ) : (
                      <Unlink size={18} />
                    )}
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <div className="p-8 text-center">
              <div className="w-12 h-12 rounded-xl bg-[var(--surface-hover)] border border-[var(--border)] flex items-center justify-center mx-auto mb-3">
                <Link size={24} className="text-[var(--text-subtle)]" />
              </div>
              <p className="text-sm text-[var(--text-muted)] mb-1">No linked platforms</p>
              <p className="text-xs text-[var(--text-subtle)]">
                Link a platform above to get started
              </p>
            </div>
          )}
        </SettingsGroup>
      </SettingsSection>

      <ConfirmDialog
        isOpen={confirmDialog.isOpen}
        onClose={() => setConfirmDialog((prev) => ({ ...prev, isOpen: false }))}
        onConfirm={confirmDialog.onConfirm}
        title={confirmDialog.title}
        message={confirmDialog.message}
        confirmText={confirmDialog.confirmText}
        variant={confirmDialog.variant}
      />
    </>
  );
}
