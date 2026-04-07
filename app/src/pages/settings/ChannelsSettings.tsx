import { useState, useEffect, useCallback, useMemo } from 'react';
import toast from 'react-hot-toast';
import {
  Send,
  MessageSquare,
  Hash,
  Phone,
  Shield,
  Terminal,
  Plus,
  ChevronDown,
  ChevronUp,
  Zap,
  XCircle,
  Radio,
} from 'lucide-react';
import { channelsApi, projectsApi, gatewayApi } from '../../lib/api';
import { LoadingSpinner } from '../../components/PulsingGridSpinner';
import { SettingsSection, SettingsGroup } from '../../components/settings';
import { ConfirmDialog } from '../../components/modals/ConfirmDialog';

interface Channel {
  id: string;
  channel_type: string;
  name: string;
  webhook_url?: string;
  is_active: boolean;
  project_id: string | null;
  created_at: string;
  updated_at: string;
}

interface Project {
  id: string;
  name: string;
  slug: string;
}

interface Platform {
  platform: string;
  display_name: string;
  supports_gateway: boolean;
  setup_notes: string;
}

interface CredentialField {
  key: string;
  label: string;
  placeholder?: string;
}

const PLATFORM_ICONS: Record<string, React.ReactNode> = {
  telegram: <Send size={18} />,
  discord: <MessageSquare size={18} />,
  slack: <Hash size={18} />,
  whatsapp: <Phone size={18} />,
  signal: <Shield size={18} />,
  cli: <Terminal size={18} />,
};

const CREDENTIAL_FIELDS: Record<string, CredentialField[]> = {
  telegram: [{ key: 'bot_token', label: 'Bot Token', placeholder: '123456:ABC-DEF...' }],
  discord: [
    { key: 'bot_token', label: 'Bot Token' },
    { key: 'application_id', label: 'Application ID' },
    { key: 'public_key', label: 'Public Key' },
  ],
  slack: [
    { key: 'bot_token', label: 'Bot Token (xoxb-...)' },
    { key: 'signing_secret', label: 'Signing Secret' },
    { key: 'app_token', label: 'App Token (xapp-..., for Socket Mode)' },
  ],
  whatsapp: [
    { key: 'access_token', label: 'Access Token' },
    { key: 'phone_number_id', label: 'Phone Number ID' },
  ],
  signal: [
    { key: 'signal_cli_url', label: 'signal-cli REST URL' },
    { key: 'phone_number', label: 'Phone Number (+...)' },
  ],
};

function getPlatformIcon(platform: string) {
  return PLATFORM_ICONS[platform.toLowerCase()] || <Radio size={18} />;
}

export default function ChannelsSettings() {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [platforms, setPlatforms] = useState<Platform[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedProjectId, setSelectedProjectId] = useState('');

  // Create form
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [formPlatform, setFormPlatform] = useState('');
  const [formName, setFormName] = useState('');
  const [formProjectId, setFormProjectId] = useState('');
  const [formCredentials, setFormCredentials] = useState<Record<string, string>>({});
  const [creating, setCreating] = useState(false);

  // Test
  const [testingId, setTestingId] = useState<string | null>(null);

  // Deactivate
  const [deactivatingId, setDeactivatingId] = useState<string | null>(null);
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
      const [channelsRes, projectsRes, platformsRes] = await Promise.all([
        channelsApi.list(),
        projectsApi.getAll(),
        gatewayApi.getPlatforms(),
      ]);
      setChannels(channelsRes as Channel[]);
      setProjects(projectsRes as Project[]);
      setPlatforms(platformsRes as Platform[]);
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to load channels');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const filteredChannels = useMemo(() => {
    if (!selectedProjectId) return channels;
    return channels.filter((ch) => ch.project_id === selectedProjectId);
  }, [channels, selectedProjectId]);

  const currentFields = useMemo(() => {
    return CREDENTIAL_FIELDS[formPlatform] || [];
  }, [formPlatform]);

  const handlePlatformChange = (platform: string) => {
    setFormPlatform(platform);
    setFormCredentials({});
  };

  const handleCredentialChange = (key: string, value: string) => {
    setFormCredentials((prev) => ({ ...prev, [key]: value }));
  };

  const resetForm = () => {
    setFormPlatform('');
    setFormName('');
    setFormProjectId('');
    setFormCredentials({});
  };

  const handleCreate = async () => {
    if (!formPlatform || !formName.trim() || !formProjectId) return;
    setCreating(true);
    try {
      await channelsApi.create({
        channel_type: formPlatform,
        name: formName.trim(),
        project_id: formProjectId,
        credentials: formCredentials,
      });
      toast.success('Channel created');
      setShowCreateForm(false);
      resetForm();
      loadData();
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string | unknown[] } } };
      const detail = err.response?.data?.detail;
      const msg = typeof detail === 'string' ? detail : 'Failed to create channel';
      toast.error(msg);
    } finally {
      setCreating(false);
    }
  };

  const handleTest = async (channelId: string) => {
    setTestingId(channelId);
    try {
      await channelsApi.test(channelId, 'self');
      toast.success('Test message sent');
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Test failed');
    } finally {
      setTestingId(null);
    }
  };

  const handleDeactivate = (channel: Channel) => {
    setConfirmDialog({
      isOpen: true,
      title: `Deactivate "${channel.name}"`,
      message: `This will deactivate the ${channel.channel_type} channel. The bot will stop responding until reactivated.`,
      confirmText: 'Deactivate',
      variant: 'danger',
      onConfirm: async () => {
        setConfirmDialog((prev) => ({ ...prev, isOpen: false }));
        setDeactivatingId(channel.id);
        try {
          await channelsApi.deactivate(channel.id);
          toast.success('Channel deactivated');
          loadData();
        } catch (error: unknown) {
          const err = error as { response?: { data?: { detail?: string } } };
          toast.error(err.response?.data?.detail || 'Failed to deactivate channel');
        } finally {
          setDeactivatingId(null);
        }
      },
    });
  };

  const projectName = (id: string | null) =>
    id ? projects.find((p) => p.id === id)?.name || id : 'No project';

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--bg)]">
        <LoadingSpinner message="Loading channels..." size={60} />
      </div>
    );
  }

  return (
    <>
      <SettingsSection title="Channels" description="Manage bot channels for your projects">
        {/* Project picker */}
        <div>
          <label className="text-xs font-medium text-[var(--text)] block mb-1.5">
            Filter by Project
          </label>
          <select
            value={selectedProjectId}
            onChange={(e) => setSelectedProjectId(e.target.value)}
            className="w-full px-3 py-2 bg-[var(--surface-hover)] border border-[var(--border)] rounded-lg text-base text-[var(--text)] placeholder-[var(--text)]/40 focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
          >
            <option value="">All projects</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>

        {/* Active Channels */}
        <SettingsGroup title="Active Channels">
          {filteredChannels.length > 0 ? (
            <div className="divide-y divide-[var(--border)]">
              {filteredChannels.map((channel) => (
                <div
                  key={channel.id}
                  className="p-4 flex items-center justify-between hover:bg-[var(--surface-hover)] transition-colors"
                >
                  <div className="flex items-center gap-3 flex-1 min-w-0">
                    <div className="w-10 h-10 rounded-lg bg-[var(--primary)]/10 flex items-center justify-center flex-shrink-0 text-[var(--primary)]">
                      {getPlatformIcon(channel.channel_type)}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <h4 className="font-semibold text-sm text-[var(--text)]">{channel.name}</h4>
                        <span
                          className={`px-2 py-0.5 rounded text-[10px] ${
                            channel.is_active
                              ? 'bg-green-500/10 text-green-400'
                              : 'bg-yellow-500/10 text-yellow-400'
                          }`}
                        >
                          {channel.is_active ? 'active' : 'inactive'}
                        </span>
                      </div>
                      <p className="text-xs text-[var(--text-muted)] capitalize">
                        {channel.channel_type}
                      </p>
                      <p className="text-[11px] text-[var(--text-subtle)] mt-0.5 truncate">
                        {projectName(channel.project_id)}
                        {channel.webhook_url && (
                          <span className="ml-2 font-mono">{channel.webhook_url}</span>
                        )}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <button
                      onClick={() => handleTest(channel.id)}
                      disabled={testingId === channel.id}
                      className="btn btn-sm flex items-center gap-1"
                      title="Send test message"
                    >
                      {testingId === channel.id ? (
                        <svg className="w-3.5 h-3.5 animate-spin" viewBox="0 0 24 24" fill="none">
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
                        <Zap size={14} />
                      )}
                      Test
                    </button>
                    <button
                      onClick={() => handleDeactivate(channel)}
                      disabled={deactivatingId === channel.id}
                      className="p-2 text-[var(--text-subtle)] hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors disabled:opacity-50"
                      title="Deactivate channel"
                    >
                      {deactivatingId === channel.id ? (
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
                        <XCircle size={18} />
                      )}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="p-8 text-center">
              <div className="w-12 h-12 rounded-xl bg-[var(--surface-hover)] border border-[var(--border)] flex items-center justify-center mx-auto mb-3">
                <Radio size={24} className="text-[var(--text-subtle)]" />
              </div>
              <p className="text-sm text-[var(--text-muted)] mb-1">No channels configured</p>
              <p className="text-xs text-[var(--text-subtle)]">
                Add a channel below to connect a bot to your project
              </p>
            </div>
          )}
        </SettingsGroup>

        {/* Add Channel */}
        <div>
          <button
            onClick={() => setShowCreateForm((prev) => !prev)}
            className="btn flex items-center gap-1.5 w-full justify-between"
          >
            <span className="flex items-center gap-1.5">
              <Plus size={14} />
              Add Channel
            </span>
            {showCreateForm ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>

          {showCreateForm && (
            <div className="mt-3 p-4 bg-[var(--surface-hover)] border border-[var(--border)] rounded-xl">
              <h4 className="font-semibold text-sm text-[var(--text)] mb-4">
                New channel configuration
              </h4>
              <div className="space-y-4">
                {/* Platform */}
                <div>
                  <label className="text-xs font-medium text-[var(--text)] block mb-1.5">
                    Platform <span className="text-red-400">*</span>
                  </label>
                  <select
                    value={formPlatform}
                    onChange={(e) => handlePlatformChange(e.target.value)}
                    className="w-full px-3 py-2 bg-[var(--surface-hover)] border border-[var(--border)] rounded-lg text-base text-[var(--text)] placeholder-[var(--text)]/40 focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
                  >
                    <option value="">Select a platform</option>
                    {platforms.map((p) => (
                      <option key={p.platform} value={p.platform}>
                        {p.display_name}
                      </option>
                    ))}
                  </select>
                </div>

                {/* Name */}
                <div>
                  <label className="text-xs font-medium text-[var(--text)] block mb-1.5">
                    Channel Name <span className="text-red-400">*</span>
                  </label>
                  <input
                    type="text"
                    value={formName}
                    onChange={(e) => setFormName(e.target.value)}
                    placeholder="e.g., Support Bot, Notifications"
                    className="w-full px-3 py-2 bg-[var(--surface-hover)] border border-[var(--border)] rounded-lg text-base text-[var(--text)] placeholder-[var(--text)]/40 focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
                    maxLength={100}
                  />
                </div>

                {/* Credential fields */}
                {currentFields.length > 0 && (
                  <div className="space-y-3">
                    <p className="text-[11px] text-[var(--text-muted)] font-medium uppercase tracking-wider">
                      Credentials
                    </p>
                    {currentFields.map((field) => (
                      <div key={field.key}>
                        <label className="text-xs font-medium text-[var(--text)] block mb-1.5">
                          {field.label}
                        </label>
                        <input
                          type="password"
                          value={formCredentials[field.key] || ''}
                          onChange={(e) => handleCredentialChange(field.key, e.target.value)}
                          placeholder={field.placeholder || ''}
                          className="w-full px-3 py-2 bg-[var(--surface-hover)] border border-[var(--border)] rounded-lg text-base text-[var(--text)] placeholder-[var(--text)]/40 focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
                        />
                      </div>
                    ))}
                  </div>
                )}

                {/* Project */}
                <div>
                  <label className="text-xs font-medium text-[var(--text)] block mb-1.5">
                    Project <span className="text-red-400">*</span>
                  </label>
                  <select
                    value={formProjectId}
                    onChange={(e) => setFormProjectId(e.target.value)}
                    className="w-full px-3 py-2 bg-[var(--surface-hover)] border border-[var(--border)] rounded-lg text-base text-[var(--text)] placeholder-[var(--text)]/40 focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
                  >
                    <option value="">Select a project</option>
                    {projects.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                </div>

                {/* Actions */}
                <div className="flex items-center gap-2 pt-2">
                  <button
                    onClick={handleCreate}
                    disabled={!formPlatform || !formName.trim() || !formProjectId || creating}
                    className="btn btn-filled flex items-center gap-1.5"
                  >
                    {creating ? 'Creating...' : 'Create Channel'}
                  </button>
                  <button
                    onClick={() => {
                      setShowCreateForm(false);
                      resetForm();
                    }}
                    className="btn"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
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
