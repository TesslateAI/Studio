import { useState, useEffect, useCallback } from 'react';
import toast from 'react-hot-toast';
import { Trash, Plus, Key, ShieldCheck, Check, LinkSimple, Info } from '@phosphor-icons/react';
import { deploymentCredentialsApi } from '../../lib/api';
import { COMING_SOON_PROVIDERS } from '../../lib/utils';
import { getProviderConfig } from '../../lib/deployment-providers';
import { LoadingSpinner } from '../../components/PulsingGridSpinner';
import { SettingsSection } from '../../components/settings';
import { ProviderConnectModal } from '../../components/modals/ProviderConnectModal';
import { ConfirmDialog } from '../../components/modals/ConfirmDialog';
import { useCancellableParallelRequests } from '../../hooks/useCancellableRequest';

interface Provider {
  name: string;
  display_name: string;
  auth_type: 'oauth' | 'api_token';
  required_fields: string[];
  icon_color: string;
  description: string;
}

interface DeploymentCredential {
  id: string;
  provider: string;
  metadata: Record<string, unknown>;
  created_at: string;
}

export default function DeploymentSettings() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [credentials, setCredentials] = useState<DeploymentCredential[]>([]);
  const [loading, setLoading] = useState(true);
  const [deletingCredentialId, setDeletingCredentialId] = useState<string | null>(null);

  // ProviderConnectModal state — replaces the old inline manual credential modal + OAuth handler
  const [connectModal, setConnectModal] = useState<{
    isOpen: boolean;
    defaultProvider?: string;
  }>({ isOpen: false });

  // Confirm dialog for disconnect
  const [confirmDialog, setConfirmDialog] = useState<{
    isOpen: boolean;
    title: string;
    message: string;
    confirmText: string;
    variant: 'danger' | 'warning' | 'info';
    onConfirm: () => void;
  }>({ isOpen: false, title: '', message: '', confirmText: 'Confirm', variant: 'info', onConfirm: () => {} });

  // Use cancellable parallel requests to prevent memory leaks on unmount
  const { executeAll } = useCancellableParallelRequests();

  const loadData = useCallback(() => {
    executeAll(
      [() => deploymentCredentialsApi.getProviders(), () => deploymentCredentialsApi.list()],
      {
        onAllSuccess: ([providersData, credentialsData]) => {
          setProviders((providersData as { providers?: Provider[] }).providers || []);
          setCredentials(
            (credentialsData as { credentials?: DeploymentCredential[] }).credentials || []
          );
        },
        onError: (error) => {
          console.error('Failed to load deployment data:', error);
          const err = error as { response?: { data?: { detail?: string } } };
          toast.error(err.response?.data?.detail || 'Failed to load deployment providers');
        },
        onFinally: () => setLoading(false),
      }
    );
  }, [executeAll]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleConnectProvider = (provider: Provider) => {
    setConnectModal({ isOpen: true, defaultProvider: provider.name });
  };

  const handleProviderConnected = async () => {
    await loadData();
  };

  const handleDisconnect = (credentialId: string, providerName: string) => {
    setConfirmDialog({
      isOpen: true,
      title: `Disconnect ${providerName}`,
      message: `This will remove your saved credentials for ${providerName}. You will need to reconnect before deploying to this provider again.`,
      confirmText: 'Disconnect',
      variant: 'danger',
      onConfirm: async () => {
        setConfirmDialog((prev) => ({ ...prev, isOpen: false }));
        setDeletingCredentialId(credentialId);
        try {
          await deploymentCredentialsApi.delete(credentialId);
          toast.success(`Disconnected from ${providerName}`);
          await loadData();
        } catch (error: unknown) {
          console.error('Failed to delete credential:', error);
          const err = error as { response?: { data?: { detail?: string } } };
          toast.error(err.response?.data?.detail || 'Failed to disconnect provider');
        } finally {
          setDeletingCredentialId(null);
        }
      },
    });
  };

  const getProviderIcon = (providerName: string) => {
    return getProviderConfig(providerName.toLowerCase()).icon;
  };

  const getProviderColor = (providerName: string) => {
    const config = getProviderConfig(providerName.toLowerCase());
    return `bg-[${config.color}]/20 ${config.textColor} border-[${config.color}]/30`;
  };

  const isProviderConnected = (providerName: string) => {
    return credentials.some((c) => c.provider === providerName);
  };

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--bg)]">
        <LoadingSpinner message="Loading deployment providers..." size={60} />
      </div>
    );
  }

  return (
    <>
      <SettingsSection
        title="Deployment Providers"
        description="Connect your cloud accounts to deploy projects directly from Tesslate Studio"
      >
        {/* Info Box */}
        <div className="p-4 bg-blue-500/10 border border-blue-500/20 rounded-xl">
          <div className="flex items-start gap-3">
            <Info size={20} className="text-blue-400 mt-0.5 flex-shrink-0" />
            <div className="text-sm text-blue-400">
              <p className="font-semibold mb-1">Your credentials, your control</p>
              <p className="text-xs">
                All credentials are encrypted and stored securely. Deployments happen to your own
                cloud accounts, giving you full ownership and control of your applications.
              </p>
            </div>
          </div>
        </div>

        {/* Connected Providers */}
        {credentials.length > 0 && (
          <div>
            <h3 className="text-lg font-semibold text-[var(--text)] mb-4 flex items-center gap-2">
              <Check size={20} className="text-green-400" weight="bold" />
              Connected Providers
            </h3>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {credentials.map((credential) => {
                const provider = providers.find((p) => p.name === credential.provider);
                if (!provider) return null;

                return (
                  <div
                    key={credential.id}
                    className="p-4 bg-[var(--surface)] border border-white/10 rounded-xl hover:border-white/20 transition-all"
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex items-start gap-3 flex-1">
                        <div
                          className={`w-12 h-12 rounded-lg flex items-center justify-center text-2xl ${getProviderColor(provider.name)}`}
                        >
                          {getProviderIcon(provider.name)}
                        </div>
                        <div className="flex-1 min-w-0">
                          <h4 className="font-semibold text-[var(--text)] mb-1">
                            {provider.display_name}
                          </h4>
                          <p className="text-xs text-[var(--text)]/60 mb-2">
                            {provider.description}
                          </p>
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="inline-flex items-center gap-1 px-2 py-1 bg-green-500/20 text-green-400 text-xs font-medium rounded-md">
                              <Check size={12} weight="bold" />
                              Connected
                            </span>
                            {credential.metadata?.account_name && (
                              <span className="text-xs text-[var(--text)]/40">
                                {String(credential.metadata.account_name)}
                              </span>
                            )}
                          </div>
                          <p className="text-xs text-[var(--text)]/40 mt-2">
                            Connected {formatDate(credential.created_at)}
                          </p>
                        </div>
                      </div>
                      <button
                        onClick={() => handleDisconnect(credential.id, provider.display_name)}
                        disabled={deletingCredentialId === credential.id}
                        className="p-2 text-red-400 hover:bg-red-500/10 rounded-lg transition-colors disabled:opacity-50 min-h-[44px] min-w-[44px] flex items-center justify-center"
                        title="Disconnect"
                      >
                        {deletingCredentialId === credential.id ? (
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
                        ) : (
                          <Trash size={18} />
                        )}
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Available Providers */}
        <div>
          <h3 className="text-lg font-semibold text-[var(--text)] mb-4 flex items-center gap-2">
            <Plus size={20} />
            Available Providers
          </h3>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {providers
              .filter((provider) => !isProviderConnected(provider.name))
              .map((provider) => {
                const isComingSoon = COMING_SOON_PROVIDERS.includes(provider.name.toLowerCase());
                return (
                  <div
                    key={provider.name}
                    className={`p-4 bg-[var(--surface)] border border-white/10 rounded-xl transition-all ${isComingSoon ? 'opacity-60' : 'hover:border-white/20'}`}
                  >
                    <div className="flex items-start gap-3 mb-4">
                      <div
                        className={`w-12 h-12 rounded-lg flex items-center justify-center text-2xl ${getProviderColor(provider.name)}`}
                      >
                        {getProviderIcon(provider.name)}
                      </div>
                      <div className="flex-1">
                        <h4 className="font-semibold text-[var(--text)] mb-1 flex items-center gap-2">
                          {provider.display_name}
                          {isComingSoon && (
                            <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 bg-yellow-500/20 text-yellow-400 rounded-full">
                              Coming Soon
                            </span>
                          )}
                        </h4>
                        <p className="text-xs text-[var(--text)]/60">{provider.description}</p>
                      </div>
                    </div>

                    <button
                      onClick={() => {
                        if (!isComingSoon) handleConnectProvider(provider);
                      }}
                      disabled={isComingSoon}
                      className={`w-full px-4 py-2.5 rounded-lg font-semibold transition-all flex items-center justify-center gap-2 min-h-[48px] ${
                        isComingSoon
                          ? 'bg-white/5 text-[var(--text)]/30 cursor-not-allowed'
                          : 'bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white'
                      }`}
                    >
                      {isComingSoon ? (
                        'Coming Soon'
                      ) : provider.auth_type === 'oauth' ? (
                        <>
                          <LinkSimple size={18} weight="bold" />
                          Connect with OAuth
                        </>
                      ) : (
                        <>
                          <Key size={18} weight="bold" />
                          Add API Token
                        </>
                      )}
                    </button>

                    <div className="mt-3 pt-3 border-t border-white/10">
                      <div className="flex items-center gap-2 text-xs text-[var(--text)]/40">
                        <ShieldCheck size={14} />
                        {isComingSoon
                          ? 'Provider integration in development'
                          : provider.auth_type === 'oauth'
                            ? 'Secure OAuth 2.0 authentication'
                            : 'Encrypted API token storage'}
                      </div>
                    </div>
                  </div>
                );
              })}
          </div>

          {providers.filter((p) => !isProviderConnected(p.name)).length === 0 && (
            <div className="text-center py-8">
              <p className="text-[var(--text)]/40 text-sm">
                All available providers are connected!
              </p>
            </div>
          )}
        </div>
      </SettingsSection>

      {/* Shared provider connect modal — handles OAuth + API token for all 22 providers */}
      <ProviderConnectModal
        isOpen={connectModal.isOpen}
        onClose={() => setConnectModal({ isOpen: false })}
        onConnected={handleProviderConnected}
        defaultProvider={connectModal.defaultProvider}
        connectedProviders={credentials.map((c) => c.provider)}
      />

      {/* Confirm dialog for disconnect */}
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
