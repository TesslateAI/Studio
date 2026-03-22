import { useState, useEffect } from 'react';
import { Settings, Monitor, Check, Layers, Package, Download, Lock, Cpu, Cloud, ExternalLink } from 'lucide-react';
import { ChatCentered, Spinner } from '@phosphor-icons/react';
import { projectsApi, setupApi, deploymentCredentialsApi } from '../../lib/api';
import { ServiceConfigForm } from '../ServiceConfigForm';
import type { TesslateConfig } from '../../types/tesslateConfig';
import { ToggleSwitch } from '../ui/ToggleSwitch';
import { useChatPosition, type ChatPosition } from '../../contexts/ChatPositionContext';
import { ExportTemplateModal } from '../modals/ExportTemplateModal';
import { ProviderConnectModal } from '../modals/ProviderConnectModal';
import toast from 'react-hot-toast';

interface DeploymentCredential {
  id: string;
  provider: string;
  project_id: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
  is_default: boolean;
}

interface ProviderDisplay {
  name: string;
  display_name: string;
  icon: string;
  color: string;
}

const PROVIDER_DISPLAY: Record<string, ProviderDisplay> = {
  vercel: { name: 'vercel', display_name: 'Vercel', icon: '▲', color: '#000000' },
  netlify: { name: 'netlify', display_name: 'Netlify', icon: '◆', color: '#00C7B7' },
  cloudflare: { name: 'cloudflare', display_name: 'Cloudflare', icon: '🔥', color: '#F38020' },
  railway: { name: 'railway', display_name: 'Railway', icon: '🚂', color: '#0B0D0E' },
  heroku: { name: 'heroku', display_name: 'Heroku', icon: '🟣', color: '#430098' },
  render: { name: 'render', display_name: 'Render', icon: '🔷', color: '#46E3B7' },
  koyeb: { name: 'koyeb', display_name: 'Koyeb', icon: '🟢', color: '#121212' },
  zeabur: { name: 'zeabur', display_name: 'Zeabur', icon: '⚡', color: '#6C5CE7' },
  northflank: { name: 'northflank', display_name: 'Northflank', icon: '🔶', color: '#01E277' },
  surge: { name: 'surge', display_name: 'Surge.sh', icon: '🌊', color: '#D93472' },
  'deno-deploy': { name: 'deno-deploy', display_name: 'Deno Deploy', icon: '🦕', color: '#000000' },
  firebase: { name: 'firebase', display_name: 'Firebase', icon: '🔥', color: '#FFCA28' },
  'github-pages': { name: 'github-pages', display_name: 'GitHub Pages', icon: '📄', color: '#222222' },
  digitalocean: { name: 'digitalocean', display_name: 'DigitalOcean', icon: '🌊', color: '#0080FF' },
  'aws-apprunner': { name: 'aws-apprunner', display_name: 'AWS App Runner', icon: '☁️', color: '#FF9900' },
  'gcp-cloudrun': { name: 'gcp-cloudrun', display_name: 'GCP Cloud Run', icon: '☁️', color: '#4285F4' },
  'azure-container-apps': { name: 'azure-container-apps', display_name: 'Azure Container Apps', icon: '☁️', color: '#0078D4' },
  'do-container': { name: 'do-container', display_name: 'DO Container', icon: '🌊', color: '#0080FF' },
  fly: { name: 'fly', display_name: 'Fly.io', icon: '✈️', color: '#7B3FE4' },
  dockerhub: { name: 'dockerhub', display_name: 'Docker Hub', icon: '🐳', color: '#2496ED' },
  ghcr: { name: 'ghcr', display_name: 'GHCR', icon: '📦', color: '#222222' },
  download: { name: 'download', display_name: 'Download', icon: '💾', color: '#6B7280' },
};

interface SettingsPanelProps {
  projectSlug: string;
  onLockToggle?: (locked: boolean) => void;
}

type PreviewMode = 'normal' | 'browser-tabs';

export function SettingsPanel({ projectSlug }: SettingsPanelProps) {
  const [previewMode, setPreviewMode] = useState<PreviewMode>('normal');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [savingChatPos, setSavingChatPos] = useState(false);
  const [showExportModal, setShowExportModal] = useState(false);
  const [downloadingTesslate, setDownloadingTesslate] = useState(false);
  const [agentLockEnabled, setAgentLockEnabled] = useState(true);
  const [savingAgentLock, setSavingAgentLock] = useState(false);
  const [servicesConfig, setServicesConfig] = useState<TesslateConfig | null>(null);
  const [servicesEditing, setServicesEditing] = useState(false);
  const [savingServices, setSavingServices] = useState(false);
  const { chatPosition, setChatPosition } = useChatPosition();

  // Deployment credentials state
  const [deployCredentials, setDeployCredentials] = useState<DeploymentCredential[]>([]);
  const [deployLoading, setDeployLoading] = useState(false);
  const [showConnectModal, setShowConnectModal] = useState(false);

  useEffect(() => {
    loadSettings();
    loadDeployCredentials();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectSlug]);

  const loadSettings = async () => {
    try {
      const data = await projectsApi.getSettings(projectSlug);
      const settings = data.settings || {};
      setPreviewMode(settings.preview_mode || 'normal');
      setAgentLockEnabled(settings.agent_lock_enabled !== false); // default true
      // Load services config
      try {
        const configData = await setupApi.getConfig(projectSlug);
        if (configData.exists) {
          setServicesConfig({
            apps: configData.apps,
            infrastructure: configData.infrastructure,
            primaryApp: configData.primaryApp,
          });
        }
      } catch (e) {
        console.error('Failed to load services config:', e);
      }
    } catch (error) {
      console.error('Failed to load settings:', error);
    } finally {
      setLoading(false);
    }
  };

  const loadDeployCredentials = async () => {
    setDeployLoading(true);
    try {
      const data = await deploymentCredentialsApi.list();
      setDeployCredentials(data.credentials || []);
    } catch (error) {
      console.error('Failed to load deployment credentials:', error);
    } finally {
      setDeployLoading(false);
    }
  };

  const handlePreviewModeChange = async (mode: PreviewMode) => {
    setSaving(true);
    try {
      await projectsApi.updateSettings(projectSlug, { preview_mode: mode });
      setPreviewMode(mode);
      toast.success('Preview mode updated! Refresh the page to see changes.');
    } catch (error: unknown) {
      console.error('Failed to update settings:', error);
      const axiosError = error as { response?: { data?: { detail?: string } } };
      toast.error(axiosError.response?.data?.detail || 'Failed to update settings');
    } finally {
      setSaving(false);
    }
  };

  const handleDownloadTesslate = async () => {
    setDownloadingTesslate(true);
    try {
      const blob = await projectsApi.downloadTesslateFolder(projectSlug);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${projectSlug}-tesslate.zip`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
      toast.success('Downloaded .tesslate folder');
    } catch (error: unknown) {
      const axiosError = error as { response?: { status?: number } };
      if (axiosError.response?.status === 404) {
        toast.error('No .tesslate data found yet. Run the agent first.');
      } else {
        toast.error('Failed to download .tesslate folder');
      }
    } finally {
      setDownloadingTesslate(false);
    }
  };

  const handleAgentLockToggle = async (enabled: boolean) => {
    const previous = agentLockEnabled;
    setAgentLockEnabled(enabled); // optimistic
    setSavingAgentLock(true);
    try {
      await projectsApi.updateSettings(projectSlug, { agent_lock_enabled: enabled });
      toast.success(enabled ? 'Agent locking enabled' : 'Agent locking disabled');
    } catch (error: unknown) {
      console.error('Failed to update agent lock:', error);
      setAgentLockEnabled(previous); // revert
      const axiosError = error as { response?: { data?: { detail?: string } } };
      toast.error(axiosError.response?.data?.detail || 'Failed to update settings');
    } finally {
      setSavingAgentLock(false);
    }
  };

  const handleSaveServices = async () => {
    if (!servicesConfig) return;
    setSavingServices(true);
    try {
      await setupApi.saveConfig(projectSlug, servicesConfig);
      toast.success('Services configuration saved');
      setServicesEditing(false);
    } catch (error: unknown) {
      const axiosError = error as { response?: { data?: { detail?: string } } };
      toast.error(axiosError.response?.data?.detail || 'Failed to save services config');
    } finally {
      setSavingServices(false);
    }
  };

  const handleChatPositionChange = async (position: ChatPosition) => {
    setSavingChatPos(true);
    try {
      await setChatPosition(position);
      toast.success(`Chat moved to ${position}`);
    } catch {
      toast.error('Failed to update chat position');
    } finally {
      setSavingChatPos(false);
    }
  };

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center p-8">
        <div className="text-[var(--text)]/60">Loading settings...</div>
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="panel-section p-6">
        {/* Header */}
        <div className="flex items-center gap-3 mb-6">
          <div className="p-2 bg-purple-500/20 rounded-lg">
            <Settings size={20} className="text-purple-400" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-[var(--text)]">Project Settings</h2>
            <p className="text-xs text-[var(--text)]/60">Customize your development environment</p>
          </div>
        </div>

        {/* Preview Mode Setting */}
        <div className="space-y-4">
          <div>
            <h3 className="text-sm font-medium text-[var(--text)] mb-3">Preview Mode</h3>
            <p className="text-xs text-[var(--text)]/60 mb-4">
              Choose how the preview window displays your application
            </p>

            <div className="space-y-3">
              {/* Normal Mode */}
              <button
                onClick={() => handlePreviewModeChange('normal')}
                disabled={saving}
                className={`
                  w-full p-4 rounded-lg border-2 transition-all text-left
                  ${
                    previewMode === 'normal'
                      ? 'border-orange-500 bg-orange-500/10'
                      : 'border-[var(--text)]/15 bg-white/5 hover:border-[var(--text)]/20'
                  }
                  ${saving ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
                `}
              >
                <div className="flex items-start gap-3">
                  <div
                    className={`p-2 rounded-lg ${previewMode === 'normal' ? 'bg-orange-500/20' : 'bg-white/10'}`}
                  >
                    <Monitor
                      size={20}
                      className={
                        previewMode === 'normal' ? 'text-orange-400' : 'text-[var(--text)]/60'
                      }
                    />
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="font-medium text-[var(--text)]">Normal Mode</span>
                      {previewMode === 'normal' && <Check size={16} className="text-orange-400" />}
                    </div>
                    <p className="text-xs text-[var(--text)]/60">
                      Simple preview window with basic browser controls
                    </p>
                  </div>
                </div>
              </button>

              {/* Browser Tabs Mode */}
              <button
                onClick={() => handlePreviewModeChange('browser-tabs')}
                disabled={saving}
                className={`
                  w-full p-4 rounded-lg border-2 transition-all text-left
                  ${
                    previewMode === 'browser-tabs'
                      ? 'border-orange-500 bg-orange-500/10'
                      : 'border-[var(--text)]/15 bg-white/5 hover:border-[var(--text)]/20'
                  }
                  ${saving ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
                `}
              >
                <div className="flex items-start gap-3">
                  <div
                    className={`p-2 rounded-lg ${previewMode === 'browser-tabs' ? 'bg-orange-500/20' : 'bg-white/10'}`}
                  >
                    <Layers
                      size={20}
                      className={
                        previewMode === 'browser-tabs' ? 'text-orange-400' : 'text-[var(--text)]/60'
                      }
                    />
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="font-medium text-[var(--text)]">Browser with Tabs</span>
                      {previewMode === 'browser-tabs' && (
                        <Check size={16} className="text-orange-400" />
                      )}
                    </div>
                    <p className="text-xs text-[var(--text)]/60">
                      Full browser experience with multiple tabs support
                    </p>
                  </div>
                </div>
              </button>
            </div>
          </div>

          {previewMode === 'browser-tabs' && (
            <div className="mt-4 p-4 bg-blue-500/10 border border-blue-500/20 rounded-lg">
              <p className="text-xs text-blue-400">
                💡 Browser tabs mode allows you to open multiple pages of your application
                simultaneously. Refresh the page to activate this feature.
              </p>
            </div>
          )}
        </div>

        {/* Divider */}
        <div className="border-t border-[var(--text)]/10 my-6" />

        {/* Chat Position Setting */}
        <div className="space-y-4">
          <div>
            <div className="flex items-center gap-2 mb-3">
              <ChatCentered size={18} className="text-[var(--text)]/60" />
              <h3 className="text-sm font-medium text-[var(--text)]">Chat Position</h3>
            </div>
            <p className="text-xs text-[var(--text)]/60 mb-4">
              Choose where the chat panel appears in the builder
            </p>

            <div className="grid grid-cols-3 gap-3">
              {/* Left Position */}
              <button
                onClick={() => handleChatPositionChange('left')}
                disabled={savingChatPos}
                className={`
                  p-3 rounded-lg border-2 transition-all
                  ${
                    chatPosition === 'left'
                      ? 'border-orange-500 bg-orange-500/10'
                      : 'border-[var(--text)]/15 bg-white/5 hover:border-[var(--text)]/20'
                  }
                  ${savingChatPos ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
                `}
              >
                <div className="flex flex-col items-center gap-2">
                  {/* Layout diagram - chat on left */}
                  <div className="flex w-full h-8 rounded overflow-hidden border border-[var(--text)]/20">
                    <div
                      className={`w-1/3 ${chatPosition === 'left' ? 'bg-orange-500/40' : 'bg-[var(--primary)]/20'}`}
                    />
                    <div className="flex-1 bg-[var(--surface)]" />
                  </div>
                  <span className="text-xs font-medium text-[var(--text)]">Left</span>
                </div>
              </button>

              {/* Center Position */}
              <button
                onClick={() => handleChatPositionChange('center')}
                disabled={savingChatPos}
                className={`
                  p-3 rounded-lg border-2 transition-all
                  ${
                    chatPosition === 'center'
                      ? 'border-orange-500 bg-orange-500/10'
                      : 'border-[var(--text)]/15 bg-white/5 hover:border-[var(--text)]/20'
                  }
                  ${savingChatPos ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
                `}
              >
                <div className="flex flex-col items-center gap-2">
                  {/* Layout diagram - floating chat in center */}
                  <div className="relative w-full h-8 rounded overflow-hidden border border-[var(--text)]/20 bg-[var(--surface)]">
                    <div
                      className={`absolute bottom-0 left-1/2 -translate-x-1/2 w-1/2 h-3 rounded-t ${chatPosition === 'center' ? 'bg-orange-500/40' : 'bg-[var(--primary)]/20'}`}
                    />
                  </div>
                  <span className="text-xs font-medium text-[var(--text)]">Center</span>
                </div>
              </button>

              {/* Right Position */}
              <button
                onClick={() => handleChatPositionChange('right')}
                disabled={savingChatPos}
                className={`
                  p-3 rounded-lg border-2 transition-all
                  ${
                    chatPosition === 'right'
                      ? 'border-orange-500 bg-orange-500/10'
                      : 'border-[var(--text)]/15 bg-white/5 hover:border-[var(--text)]/20'
                  }
                  ${savingChatPos ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
                `}
              >
                <div className="flex flex-col items-center gap-2">
                  {/* Layout diagram - chat on right */}
                  <div className="flex w-full h-8 rounded overflow-hidden border border-[var(--text)]/20">
                    <div className="flex-1 bg-[var(--surface)]" />
                    <div
                      className={`w-1/3 ${chatPosition === 'right' ? 'bg-orange-500/40' : 'bg-[var(--primary)]/20'}`}
                    />
                  </div>
                  <span className="text-xs font-medium text-[var(--text)]">Right</span>
                </div>
              </button>
            </div>
          </div>
        </div>

        {/* Divider */}
        <div className="border-t border-[var(--text)]/10 my-6" />

        {/* Agent Lock */}
        <div className="space-y-4">
          <div>
            <div className="flex items-center gap-2 mb-3">
              <Lock size={18} className="text-[var(--text)]/60" />
              <h3 className="text-sm font-medium text-[var(--text)]">Agent Lock</h3>
            </div>
            <p className="text-xs text-[var(--text)]/60 mb-4">
              Controls whether agents acquire a lock before modifying project files
            </p>

            <div className="flex items-center justify-between p-4 rounded-lg border-2 border-[var(--text)]/15 bg-white/5">
              <div className="flex-1">
                <span className="text-sm font-medium text-[var(--text)]">
                  {agentLockEnabled ? 'Locking' : 'Non-locking'}
                </span>
                <p className="text-xs text-[var(--text)]/40 mt-0.5">
                  {agentLockEnabled
                    ? 'Agents lock files before editing — prevents conflicts'
                    : 'Agents edit freely — faster but may conflict'}
                </p>
              </div>
              <ToggleSwitch
                active={agentLockEnabled}
                onChange={handleAgentLockToggle}
                disabled={savingAgentLock}
              />
            </div>
          </div>
        </div>

        {/* Divider */}
        <div className="border-t border-[var(--text)]/10 my-6" />

        {/* Services Configuration */}
        <div className="space-y-4">
          <div>
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <Cpu size={18} className="text-[var(--text)]/60" />
                <h3 className="text-sm font-medium text-[var(--text)]">Services</h3>
              </div>
              {servicesConfig && (
                <button
                  onClick={() => setServicesEditing(!servicesEditing)}
                  className="text-xs text-[var(--primary)] hover:text-[var(--primary)]/80 transition-colors"
                >
                  {servicesEditing ? 'Cancel' : 'Edit'}
                </button>
              )}
            </div>
            <p className="text-xs text-[var(--text)]/60 mb-4">
              Configure apps, ports, start commands, and infrastructure
            </p>

            {servicesConfig ? (
              <div>
                <ServiceConfigForm
                  config={servicesConfig}
                  onChange={setServicesConfig}
                  readOnly={!servicesEditing}
                />
                {servicesEditing && (
                  <div className="mt-4 flex gap-2 justify-end">
                    <button
                      onClick={() => setServicesEditing(false)}
                      className="px-4 py-2 text-sm text-[var(--text)]/60 hover:text-[var(--text)] transition-colors"
                    >
                      Cancel
                    </button>
                    <button
                      onClick={handleSaveServices}
                      disabled={savingServices}
                      className="px-4 py-2 bg-[var(--primary)] text-white rounded-lg text-sm font-medium hover:opacity-90 transition-opacity disabled:opacity-50"
                    >
                      {savingServices ? 'Saving...' : 'Save Changes'}
                    </button>
                  </div>
                )}
              </div>
            ) : (
              <div className="p-4 rounded-lg border-2 border-dashed border-[var(--text)]/10 text-center">
                <p className="text-xs text-[var(--text)]/40">
                  No services configured yet
                </p>
              </div>
            )}
          </div>
        </div>

        {/* Divider */}
        <div className="border-t border-[var(--text)]/10 my-6" />

        {/* Deployment Credentials */}
        <div className="space-y-4">
          <div>
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <Cloud size={18} className="text-[var(--text)]/60" />
                <h3 className="text-sm font-medium text-[var(--text)]">Deployments</h3>
              </div>
              <button
                onClick={() => setShowConnectModal(true)}
                className="text-xs text-[var(--primary)] hover:text-[var(--primary)]/80 transition-colors flex items-center gap-1"
              >
                <ExternalLink size={12} />
                Connect Provider
              </button>
            </div>
            <p className="text-xs text-[var(--text)]/60 mb-4">
              Provider credentials used for deploying this project
            </p>

            {deployLoading ? (
              <div className="flex items-center justify-center py-6">
                <Spinner size={20} className="animate-spin text-[var(--primary)]" />
              </div>
            ) : deployCredentials.length > 0 ? (
              <div className="space-y-2">
                {deployCredentials.map((cred) => {
                  const display = PROVIDER_DISPLAY[cred.provider] || {
                    name: cred.provider,
                    display_name: cred.provider,
                    icon: '🚀',
                    color: '#6B7280',
                  };
                  return (
                    <div
                      key={cred.id}
                      className="flex items-center gap-3 p-3 rounded-lg border border-[var(--text)]/10 bg-white/5"
                    >
                      <div
                        className="w-8 h-8 rounded-md flex items-center justify-center text-sm font-bold text-white"
                        style={{ backgroundColor: display.color }}
                      >
                        {display.icon}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-[var(--text)] truncate">
                          {display.display_name}
                        </p>
                        <p className="text-xs text-[var(--text)]/40">
                          {(cred.metadata as Record<string, string>)?.account_name || 'Connected'}
                        </p>
                      </div>
                      <span
                        className={`text-[10px] font-medium px-2 py-0.5 rounded-full ${
                          cred.is_default
                            ? 'bg-blue-500/15 text-blue-400'
                            : 'bg-green-500/15 text-green-400'
                        }`}
                      >
                        {cred.is_default ? 'Account Default' : 'Project-Specific'}
                      </span>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="p-4 rounded-lg border-2 border-dashed border-[var(--text)]/10 text-center">
                <p className="text-xs text-[var(--text)]/40">
                  No deployment providers connected yet
                </p>
                <button
                  onClick={() => setShowConnectModal(true)}
                  className="mt-2 text-xs text-[var(--primary)] hover:text-[var(--primary)]/80 transition-colors"
                >
                  Connect a provider
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Divider */}
        <div className="border-t border-[var(--text)]/10 my-6" />

        {/* Template Export */}
        <div className="space-y-4">
          <div>
            <div className="flex items-center gap-2 mb-3">
              <Package size={18} className="text-[var(--text)]/60" />
              <h3 className="text-sm font-medium text-[var(--text)]">Template Export</h3>
            </div>
            <p className="text-xs text-[var(--text)]/60 mb-4">
              Share this project as a reusable template on the marketplace
            </p>

            <button
              onClick={() => setShowExportModal(true)}
              className="w-full p-4 rounded-lg border-2 border-[var(--text)]/15 bg-white/5 hover:border-[var(--primary)]/50 hover:bg-[var(--primary)]/5 transition-all cursor-pointer text-left"
            >
              <div className="flex items-start gap-3">
                <div className="p-2 rounded-lg bg-white/10">
                  <Package size={20} className="text-[var(--text)]/60" />
                </div>
                <div className="flex-1">
                  <span className="font-medium text-[var(--text)]">Export as Template</span>
                  <p className="text-xs text-[var(--text)]/60 mt-1">
                    Package your project files into a shareable template archive
                  </p>
                </div>
              </div>
            </button>
          </div>
        </div>

        {/* Divider */}
        <div className="border-t border-[var(--text)]/10 my-6" />

        {/* Project Data */}
        <div className="space-y-4">
          <div>
            <div className="flex items-center gap-2 mb-3">
              <Download size={18} className="text-[var(--text)]/60" />
              <h3 className="text-sm font-medium text-[var(--text)]">Project Data</h3>
            </div>
            <p className="text-xs text-[var(--text)]/60 mb-4">
              Download agent trajectory logs and plan files
            </p>

            <button
              onClick={handleDownloadTesslate}
              disabled={downloadingTesslate}
              className={`
                w-full p-4 rounded-lg border-2 transition-all text-left
                border-[var(--text)]/15 bg-white/5 hover:border-[var(--text)]/20
                ${downloadingTesslate ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
              `}
            >
              <div className="flex items-start gap-3">
                <div className="p-2 rounded-lg bg-white/10">
                  <Download
                    size={20}
                    className={
                      downloadingTesslate
                        ? 'text-orange-400 animate-pulse'
                        : 'text-[var(--text)]/60'
                    }
                  />
                </div>
                <div className="flex-1">
                  <span className="font-medium text-[var(--text)]">
                    {downloadingTesslate ? 'Downloading...' : 'Download .tesslate Folder'}
                  </span>
                  <p className="text-xs text-[var(--text)]/60 mt-1">
                    ATIF trajectory logs, subagent sessions, and plan files
                  </p>
                </div>
              </div>
            </button>
          </div>
        </div>
      </div>

      <ExportTemplateModal
        isOpen={showExportModal}
        onClose={() => setShowExportModal(false)}
        onSuccess={() => {}}
        projectSlug={projectSlug}
      />

      <ProviderConnectModal
        isOpen={showConnectModal}
        onClose={() => setShowConnectModal(false)}
        onConnected={async () => {
          await loadDeployCredentials();
        }}
        connectedProviders={deployCredentials.map((c) => c.provider)}
      />
    </div>
  );
}
