import { useState, useEffect, useCallback, useRef } from 'react';
import toast from 'react-hot-toast';
import { X, Trash, Plus, Key, ShieldCheck, Check, LinkSimple, Info } from '@phosphor-icons/react';
import { deploymentCredentialsApi } from '../../lib/api';
import { COMING_SOON_PROVIDERS } from '../../lib/utils';
import { isValidOAuthUrl } from '../../lib/url-validation';
import { getProviderConfig } from '../../lib/deployment-providers';
import { LoadingSpinner } from '../../components/PulsingGridSpinner';
import { SettingsSection } from '../../components/settings';
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

interface ManualCredentialsForm {
  [key: string]: string;
}

export default function DeploymentSettings() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [credentials, setCredentials] = useState<DeploymentCredential[]>([]);
  const [loading, setLoading] = useState(true);
  const [showManualCredentialModal, setShowManualCredentialModal] = useState(false);
  const [selectedProvider, setSelectedProvider] = useState<Provider | null>(null);
  const [manualCredentials, setManualCredentials] = useState<ManualCredentialsForm>({});
  const [isSaving, setIsSaving] = useState(false);
  const [deletingCredentialId, setDeletingCredentialId] = useState<string | null>(null);

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

  // Use refs for OAuth popup polling to prevent race conditions
  const oauthCheckIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const oauthTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Cleanup OAuth polling on unmount
  useEffect(() => {
    return () => {
      if (oauthCheckIntervalRef.current) clearInterval(oauthCheckIntervalRef.current);
      if (oauthTimeoutRef.current) clearTimeout(oauthTimeoutRef.current);
    };
  }, []);

  const handleOAuthConnect = async (provider: Provider) => {
    try {
      const result = await deploymentCredentialsApi.startOAuth(provider.name);
      if (!result.auth_url) {
        toast.error('Failed to start OAuth flow');
        return;
      }

      if (!isValidOAuthUrl(result.auth_url)) {
        toast.error('Invalid OAuth URL received');
        return;
      }

      // Open OAuth in popup window instead of full-page redirect
      const width = 600;
      const height = 700;
      const left = window.screenX + (window.outerWidth - width) / 2;
      const top = window.screenY + (window.outerHeight - height) / 2;
      const popup = window.open(
        result.auth_url,
        `Connect ${provider.display_name}`,
        `width=${width},height=${height},left=${left},top=${top},popup=1`
      );

      // Poll to check if credential was created after OAuth completes
      if (oauthCheckIntervalRef.current) clearInterval(oauthCheckIntervalRef.current);
      if (oauthTimeoutRef.current) clearTimeout(oauthTimeoutRef.current);

      oauthCheckIntervalRef.current = setInterval(async () => {
        if (popup && popup.closed) {
          if (oauthCheckIntervalRef.current) clearInterval(oauthCheckIntervalRef.current);
          if (oauthTimeoutRef.current) clearTimeout(oauthTimeoutRef.current);
          // Final check and refresh data
          loadData();
          return;
        }
        try {
          const data = await deploymentCredentialsApi.list(provider.name);
          const creds = data.credentials || [];
          if (creds.some((c: { provider: string }) => c.provider === provider.name)) {
            if (oauthCheckIntervalRef.current) clearInterval(oauthCheckIntervalRef.current);
            if (oauthTimeoutRef.current) clearTimeout(oauthTimeoutRef.current);
            toast.success(`${provider.display_name} connected successfully!`);
            loadData();
          }
        } catch {
          // Silently handle polling errors
        }
      }, 2000);

      // Timeout after 5 minutes
      oauthTimeoutRef.current = setTimeout(
        () => {
          if (oauthCheckIntervalRef.current) {
            clearInterval(oauthCheckIntervalRef.current);
            oauthCheckIntervalRef.current = null;
          }
        },
        5 * 60 * 1000
      );
    } catch (error: unknown) {
      console.error('OAuth flow error:', error);
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to start OAuth connection');
    }
  };

  const handleManualConnect = (provider: Provider) => {
    setSelectedProvider(provider);
    const initialForm: ManualCredentialsForm = {};
    provider.required_fields.forEach((field) => {
      initialForm[field] = '';
    });
    setManualCredentials(initialForm);
    setShowManualCredentialModal(true);
  };

  const handleSaveManualCredentials = async () => {
    if (!selectedProvider) return;

    const missingFields = selectedProvider.required_fields.filter(
      (field) => !manualCredentials[field]?.trim()
    );

    if (missingFields.length > 0) {
      toast.error(`Please fill in all required fields: ${missingFields.join(', ')}`);
      return;
    }

    setIsSaving(true);
    try {
      await deploymentCredentialsApi.saveManual(selectedProvider.name, manualCredentials);
      toast.success(`${selectedProvider.display_name} connected successfully!`);
      setShowManualCredentialModal(false);
      setSelectedProvider(null);
      setManualCredentials({});
      await loadData();
    } catch (error: unknown) {
      console.error('Failed to save credentials:', error);
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to save credentials');
    } finally {
      setIsSaving(false);
    }
  };

  const handleDisconnect = async (credentialId: string, providerName: string) => {
    if (!confirm(`Are you sure you want to disconnect from ${providerName}?`)) {
      return;
    }

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

  const formatFieldName = (fieldName: string) => {
    return fieldName
      .split('_')
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ');
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
                        if (isComingSoon) return;
                        if (provider.auth_type === 'oauth') {
                          handleOAuthConnect(provider);
                        } else {
                          handleManualConnect(provider);
                        }
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

      {/* Manual Credentials Modal */}
      {showManualCredentialModal && selectedProvider && (
        <div
          className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50"
          onClick={() => !isSaving && setShowManualCredentialModal(false)}
        >
          <div
            className="bg-[var(--surface)] rounded-3xl w-full max-w-lg shadow-2xl border border-white/10 max-h-[90vh] overflow-hidden flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="p-4 md:p-6 border-b border-white/10">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className={`p-2 rounded-lg ${getProviderColor(selectedProvider.name)}`}>
                    <span className="text-2xl">{getProviderIcon(selectedProvider.name)}</span>
                  </div>
                  <div>
                    <h2 className="text-lg md:text-xl font-bold text-[var(--text)]">
                      Connect {selectedProvider.display_name}
                    </h2>
                    <p className="text-sm text-[var(--text)]/60 mt-1">Enter your API credentials</p>
                  </div>
                </div>
                {!isSaving && (
                  <button
                    onClick={() => setShowManualCredentialModal(false)}
                    className="text-[var(--text)]/60 hover:text-[var(--text)] transition-colors p-2 min-h-[44px] min-w-[44px] flex items-center justify-center"
                  >
                    <X size={24} />
                  </button>
                )}
              </div>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto p-4 md:p-6 space-y-4">
              {selectedProvider.required_fields.map((field) => (
                <div key={field}>
                  <label
                    htmlFor={field}
                    className="block text-sm font-semibold text-[var(--text)] mb-2"
                  >
                    {formatFieldName(field)}
                    <span className="text-red-400 ml-1">*</span>
                  </label>
                  <input
                    id={field}
                    type={field.includes('token') || field.includes('key') ? 'password' : 'text'}
                    value={manualCredentials[field] || ''}
                    onChange={(e) =>
                      setManualCredentials({
                        ...manualCredentials,
                        [field]: e.target.value,
                      })
                    }
                    placeholder={`Enter your ${formatFieldName(field).toLowerCase()}`}
                    className="w-full px-4 py-3 bg-white/5 border border-white/10 rounded-lg text-base text-[var(--text)] placeholder-[var(--text)]/40 focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
                    disabled={isSaving}
                  />
                  {field === 'api_token' && (
                    <p className="text-xs text-[var(--text)]/60 mt-2">
                      Find this in your {selectedProvider.display_name} dashboard
                    </p>
                  )}
                </div>
              ))}

              {/* Security Notice */}
              <div className="p-4 bg-green-500/10 border border-green-500/20 rounded-lg">
                <div className="flex items-start gap-3">
                  <ShieldCheck size={20} className="text-green-400 mt-0.5 flex-shrink-0" />
                  <div className="text-sm text-green-400">
                    <p className="font-semibold mb-1">Your credentials are secure</p>
                    <p className="text-xs">
                      All API tokens are encrypted using Fernet encryption before being stored. We
                      never log or display your credentials in plain text.
                    </p>
                  </div>
                </div>
              </div>
            </div>

            {/* Footer */}
            <div className="p-4 md:p-6 border-t border-white/10 flex flex-col sm:flex-row justify-end gap-3">
              <button
                onClick={() => setShowManualCredentialModal(false)}
                disabled={isSaving}
                className="px-6 py-3 bg-white/5 border border-white/10 text-[var(--text)] rounded-lg font-semibold hover:bg-white/10 transition-all disabled:opacity-50 disabled:cursor-not-allowed min-h-[48px]"
              >
                Cancel
              </button>
              <button
                onClick={handleSaveManualCredentials}
                disabled={
                  isSaving ||
                  selectedProvider.required_fields.some((f) => !manualCredentials[f]?.trim())
                }
                className="px-6 py-3 bg-[var(--primary)] hover:bg-[var(--primary-hover)] disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded-lg font-semibold transition-all flex items-center justify-center gap-2 min-h-[48px]"
              >
                {isSaving ? (
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
                    Saving...
                  </>
                ) : (
                  <>
                    <Check size={18} weight="bold" />
                    Save Credentials
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
