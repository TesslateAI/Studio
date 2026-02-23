import { useState, useEffect, useCallback, useRef } from 'react';
import {
  X,
  Check,
  Key,
  ShieldCheck,
  LinkSimple,
  Spinner,
  Warning
} from '@phosphor-icons/react';
import { deploymentCredentialsApi } from '../../lib/api';
import { isValidOAuthUrl } from '../../lib/url-validation';
import toast from 'react-hot-toast';

interface Provider {
  name: string;
  display_name: string;
  auth_type: 'oauth' | 'api_token';
  required_fields: string[];
  icon_color: string;
  description: string;
}

interface ProviderConnectModalProps {
  isOpen: boolean;
  onClose: () => void;
  onConnected: (provider: string) => void | Promise<void>;
  defaultProvider?: 'vercel' | 'netlify' | 'cloudflare';
  connectedProviders?: string[];
}

const PROVIDER_INFO: Record<string, { icon: string; color: string; bgColor: string }> = {
  vercel: { icon: '▲', color: 'text-black', bgColor: 'bg-white' },
  netlify: { icon: '◆', color: 'text-white', bgColor: 'bg-[#00C7B7]' },
  cloudflare: { icon: '🔥', color: 'text-white', bgColor: 'bg-[#F38020]' },
};

export function ProviderConnectModal({
  isOpen,
  onClose,
  onConnected,
  defaultProvider,
  connectedProviders = [],
}: ProviderConnectModalProps) {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedProvider, setSelectedProvider] = useState<Provider | null>(null);
  const [manualCredentials, setManualCredentials] = useState<Record<string, string>>({});
  const [isSaving, setIsSaving] = useState(false);
  const [isOAuthPending, setIsOAuthPending] = useState(false);

  // Use ref for interval to prevent race conditions and ensure proper cleanup
  const oauthCheckIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const oauthTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Cleanup intervals on unmount
  useEffect(() => {
    return () => {
      if (oauthCheckIntervalRef.current) {
        clearInterval(oauthCheckIntervalRef.current);
        oauthCheckIntervalRef.current = null;
      }
      if (oauthTimeoutRef.current) {
        clearTimeout(oauthTimeoutRef.current);
        oauthTimeoutRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (isOpen) {
      loadProviders();
    }
  }, [isOpen]);

  const loadProviders = async () => {
    try {
      setLoading(true);
      const data = await deploymentCredentialsApi.getProviders();
      setProviders(data.providers || []);

      // If defaultProvider is set, pre-select it
      if (defaultProvider) {
        const provider = (data.providers || []).find((p: Provider) => p.name === defaultProvider);
        if (provider) {
          setSelectedProvider(provider);
          initializeCredentialsForm(provider);
        }
      }
    } catch (error) {
      console.error('Failed to load providers:', error);
      toast.error('Failed to load deployment providers');
    } finally {
      setLoading(false);
    }
  };

  const initializeCredentialsForm = (provider: Provider) => {
    const form: Record<string, string> = {};
    (provider.required_fields || []).forEach(field => {
      form[field] = '';
    });
    setManualCredentials(form);
  };

  const handleSelectProvider = (provider: Provider) => {
    setSelectedProvider(provider);
    initializeCredentialsForm(provider);
  };

  const clearOAuthPolling = useCallback(() => {
    if (oauthCheckIntervalRef.current) {
      clearInterval(oauthCheckIntervalRef.current);
      oauthCheckIntervalRef.current = null;
    }
    if (oauthTimeoutRef.current) {
      clearTimeout(oauthTimeoutRef.current);
      oauthTimeoutRef.current = null;
    }
  }, []);

  const checkForNewCredential = useCallback(async (provider: string) => {
    try {
      const data = await deploymentCredentialsApi.list(provider);
      const credentials = data.credentials || [];
      if (credentials.some((c: { provider: string }) => c.provider === provider)) {
        // Credential found, OAuth was successful
        clearOAuthPolling();
        setIsOAuthPending(false);
        toast.success(`${provider.charAt(0).toUpperCase() + provider.slice(1)} connected successfully!`);
        // Await onConnected to ensure credential state is refreshed before closing
        await onConnected(provider);
        onClose();
      }
    } catch (error) {
      // Silently handle errors during polling - user may cancel or close popup
    }
  }, [clearOAuthPolling, onConnected, onClose]);

  const handleOAuthConnect = async (provider: Provider) => {
    try {
      setIsOAuthPending(true);

      // Get the OAuth URL
      const result = await deploymentCredentialsApi.startOAuth(provider.name);

      if (result.auth_url) {
        if (!isValidOAuthUrl(result.auth_url)) {
          throw new Error('Invalid OAuth URL received');
        }

        // Open OAuth in popup window instead of redirect
        const width = 600;
        const height = 700;
        const left = window.screenX + (window.outerWidth - width) / 2;
        const top = window.screenY + (window.outerHeight - height) / 2;

        const popup = window.open(
          result.auth_url,
          `Connect ${provider.display_name}`,
          `width=${width},height=${height},left=${left},top=${top},popup=1`
        );

        // Poll to check if credential was created
        oauthCheckIntervalRef.current = setInterval(() => {
          // Check if popup was closed without completing
          if (popup && popup.closed) {
            clearOAuthPolling();
            setIsOAuthPending(false);
            // Do one final check in case they completed just before closing
            checkForNewCredential(provider.name);
          } else {
            checkForNewCredential(provider.name);
          }
        }, 2000);

        // Timeout after 5 minutes
        oauthTimeoutRef.current = setTimeout(() => {
          if (oauthCheckIntervalRef.current) {
            clearOAuthPolling();
            setIsOAuthPending(false);
            toast.error('OAuth authorization timed out. Please try again.');
          }
        }, 5 * 60 * 1000);
      } else {
        throw new Error('Failed to start OAuth flow');
      }
    } catch (error) {
      setIsOAuthPending(false);
      toast.error((error as Error).message || 'Failed to start OAuth connection');
    }
  };

  const handleSaveManualCredentials = async () => {
    if (!selectedProvider) return;

    const missingFields = selectedProvider.required_fields.filter(
      field => !manualCredentials[field]?.trim()
    );

    if (missingFields.length > 0) {
      toast.error(`Please fill in all required fields`);
      return;
    }

    setIsSaving(true);
    try {
      await deploymentCredentialsApi.saveManual(selectedProvider.name, manualCredentials);
      toast.success(`${selectedProvider.display_name} connected successfully!`);
      // Await onConnected to ensure credential state is refreshed before closing
      await onConnected(selectedProvider.name);
      onClose();
    } catch (error) {
      console.error('Failed to save credentials:', error);
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to save credentials');
    } finally {
      setIsSaving(false);
    }
  };

  const formatFieldName = (fieldName: string) => {
    return fieldName
      .split('_')
      .map(word => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ');
  };

  const isProviderConnected = (providerName: string) => {
    return connectedProviders.includes(providerName);
  };

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-[60]"
      onClick={(e) => {
        if (e.target === e.currentTarget && !isSaving && !isOAuthPending) {
          onClose();
        }
      }}
    >
      <div
        className="bg-[var(--surface)] rounded-2xl w-full max-w-md shadow-2xl border border-white/10 max-h-[90vh] overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="p-4 border-b border-white/10">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-[var(--text)]">
              {selectedProvider ? `Connect ${selectedProvider.display_name}` : 'Connect Deployment Provider'}
            </h2>
            {!isSaving && !isOAuthPending && (
              <button
                onClick={onClose}
                className="p-1.5 hover:bg-[var(--sidebar-hover)] rounded-lg transition-colors"
              >
                <X size={18} className="text-[var(--text)]/60" />
              </button>
            )}
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-4">
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <Spinner size={24} className="animate-spin text-[var(--primary)]" />
            </div>
          ) : isOAuthPending ? (
            <div className="flex flex-col items-center justify-center py-8 text-center">
              <Spinner size={32} className="animate-spin text-[var(--primary)] mb-4" />
              <h3 className="text-sm font-semibold text-[var(--text)] mb-2">
                Waiting for authorization...
              </h3>
              <p className="text-xs text-[var(--text)]/60">
                Complete the authorization in the popup window
              </p>
              <button
                onClick={() => {
                  clearOAuthPolling();
                  setIsOAuthPending(false);
                }}
                className="mt-4 text-xs text-[var(--text)]/60 hover:text-[var(--text)] transition-colors"
              >
                Cancel
              </button>
            </div>
          ) : selectedProvider?.auth_type === 'api_token' ? (
            // Manual credential form
            <div className="space-y-4">
              {selectedProvider.required_fields.map((field) => (
                <div key={field}>
                  <label className="block text-xs font-medium text-[var(--text)] mb-1.5">
                    {formatFieldName(field)}
                    <span className="text-red-400 ml-0.5">*</span>
                  </label>
                  <input
                    type={field.includes('token') || field.includes('key') ? 'password' : 'text'}
                    value={manualCredentials[field] || ''}
                    onChange={(e) => setManualCredentials({
                      ...manualCredentials,
                      [field]: e.target.value
                    })}
                    placeholder={`Enter your ${formatFieldName(field).toLowerCase()}`}
                    className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm text-[var(--text)] placeholder-[var(--text)]/40 focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
                    disabled={isSaving}
                  />
                </div>
              ))}

              <div className="p-3 bg-green-500/10 border border-green-500/20 rounded-lg">
                <div className="flex items-start gap-2">
                  <ShieldCheck size={16} className="text-green-400 mt-0.5 flex-shrink-0" />
                  <div className="text-xs text-green-400">
                    <p className="font-medium">Your credentials are secure</p>
                    <p className="text-green-400/80 mt-0.5">
                      All API tokens are encrypted before being stored.
                    </p>
                  </div>
                </div>
              </div>

              <div className="flex gap-2">
                <button
                  onClick={() => setSelectedProvider(null)}
                  className="flex-1 px-4 py-2 bg-white/5 border border-white/10 text-[var(--text)] rounded-lg text-sm font-medium hover:bg-white/10 transition-colors"
                >
                  Back
                </button>
                <button
                  onClick={handleSaveManualCredentials}
                  disabled={isSaving || selectedProvider.required_fields.some(f => !manualCredentials[f]?.trim())}
                  className="flex-1 px-4 py-2 bg-[var(--primary)] hover:bg-[var(--primary-hover)] disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded-lg text-sm font-medium transition-all flex items-center justify-center gap-2"
                >
                  {isSaving ? (
                    <Spinner size={16} className="animate-spin" />
                  ) : (
                    <Check size={16} weight="bold" />
                  )}
                  Connect
                </button>
              </div>
            </div>
          ) : (
            // Provider selection
            <div className="space-y-2">
              {providers.map((provider) => {
                const info = PROVIDER_INFO[provider.name] || { icon: '🚀', color: 'text-white', bgColor: 'bg-purple-500' };
                const connected = isProviderConnected(provider.name);
                const isComingSoon = ['vercel', 'cloudflare'].includes(provider.name.toLowerCase());

                return (
                  <button
                    key={provider.name}
                    onClick={() => {
                      if (connected || isComingSoon) return;
                      if (provider.auth_type === 'oauth') {
                        handleOAuthConnect(provider);
                      } else {
                        handleSelectProvider(provider);
                      }
                    }}
                    disabled={connected || isComingSoon}
                    className={`w-full p-3 rounded-xl border transition-all flex items-center gap-3 ${
                      connected
                        ? 'bg-green-500/10 border-green-500/30 cursor-default'
                        : isComingSoon
                          ? 'bg-white/5 border-white/10 opacity-50 cursor-not-allowed'
                          : 'bg-white/5 border-white/10 hover:border-[var(--primary)] hover:bg-white/10'
                    }`}
                  >
                    <div className={`w-10 h-10 rounded-lg flex items-center justify-center text-lg font-bold ${info.bgColor} ${info.color}`}>
                      {info.icon}
                    </div>
                    <div className="flex-1 text-left">
                      <p className="text-sm font-medium text-[var(--text)]">{provider.display_name}</p>
                      <p className="text-xs text-[var(--text)]/60">{provider.description}</p>
                    </div>
                    {connected ? (
                      <span className="flex items-center gap-1 text-xs text-green-400">
                        <Check size={14} weight="bold" />
                        Connected
                      </span>
                    ) : isComingSoon ? (
                      <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 bg-yellow-500/20 text-yellow-400 rounded-full">
                        Coming Soon
                      </span>
                    ) : (
                      <span className="text-xs text-[var(--text)]/40">
                        {provider.auth_type === 'oauth' ? (
                          <span className="flex items-center gap-1">
                            <LinkSimple size={12} />
                            OAuth
                          </span>
                        ) : (
                          <span className="flex items-center gap-1">
                            <Key size={12} />
                            API Token
                          </span>
                        )}
                      </span>
                    )}
                  </button>
                );
              })}

              {providers.filter(p => !isProviderConnected(p.name)).length === 0 && (
                <div className="text-center py-6">
                  <Check size={32} className="text-green-400 mx-auto mb-2" weight="bold" />
                  <p className="text-sm text-[var(--text)]">All providers connected!</p>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer help text */}
        {!loading && !isOAuthPending && !selectedProvider && (
          <div className="p-3 border-t border-white/10 bg-white/5">
            <p className="text-xs text-[var(--text)]/50 text-center">
              Select a provider to connect your account for deployments
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
