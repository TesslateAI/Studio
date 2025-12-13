import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTheme } from '../theme/ThemeContext';
import { deploymentCredentialsApi } from '../lib/api';
import toast from 'react-hot-toast';
import {
  X,
  CloudArrowUp,
  Trash,
  Plus,
  Key,
  ShieldCheck,
  Warning,
  ArrowLeft,
  Check,
  LinkSimple,
  Info
} from '@phosphor-icons/react';
import { LoadingSpinner } from '../components/PulsingGridSpinner';

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
  metadata: Record<string, any>;
  created_at: string;
}

interface ManualCredentialsForm {
  [key: string]: string;
}

export default function Settings() {
  const navigate = useNavigate();
  const { theme } = useTheme();
  const [activeTab, setActiveTab] = useState('deployment');
  const [providers, setProviders] = useState<Provider[]>([]);
  const [credentials, setCredentials] = useState<DeploymentCredential[]>([]);
  const [loading, setLoading] = useState(true);
  const [showManualCredentialModal, setShowManualCredentialModal] = useState(false);
  const [selectedProvider, setSelectedProvider] = useState<Provider | null>(null);
  const [manualCredentials, setManualCredentials] = useState<ManualCredentialsForm>({});
  const [isSaving, setIsSaving] = useState(false);
  const [deletingCredentialId, setDeletingCredentialId] = useState<string | null>(null);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      const [providersData, credentialsData] = await Promise.all([
        deploymentCredentialsApi.getProviders(),
        deploymentCredentialsApi.list(),
      ]);
      setProviders(providersData.providers || []);
      setCredentials(credentialsData.credentials || []);
    } catch (error: any) {
      console.error('Failed to load deployment data:', error);
      toast.error(error.response?.data?.detail || 'Failed to load deployment providers');
    } finally {
      setLoading(false);
    }
  };

  const handleOAuthConnect = async (provider: Provider) => {
    try {
      // Start OAuth flow
      const result = await deploymentCredentialsApi.startOAuth(provider.name);

      if (result.auth_url) {
        // Redirect to provider's OAuth page
        window.location.href = result.auth_url;
      } else {
        toast.error('Failed to start OAuth flow');
      }
    } catch (error: any) {
      console.error('OAuth flow error:', error);
      toast.error(error.response?.data?.detail || 'Failed to start OAuth connection');
    }
  };

  const handleManualConnect = (provider: Provider) => {
    setSelectedProvider(provider);
    const initialForm: ManualCredentialsForm = {};
    provider.required_fields.forEach(field => {
      initialForm[field] = '';
    });
    setManualCredentials(initialForm);
    setShowManualCredentialModal(true);
  };

  const handleSaveManualCredentials = async () => {
    if (!selectedProvider) return;

    // Validate all required fields
    const missingFields = selectedProvider.required_fields.filter(
      field => !manualCredentials[field]?.trim()
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
    } catch (error: any) {
      console.error('Failed to save credentials:', error);
      toast.error(error.response?.data?.detail || 'Failed to save credentials');
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
    } catch (error: any) {
      console.error('Failed to delete credential:', error);
      toast.error(error.response?.data?.detail || 'Failed to disconnect provider');
    } finally {
      setDeletingCredentialId(null);
    }
  };

  const getProviderIcon = (providerName: string) => {
    switch (providerName.toLowerCase()) {
      case 'cloudflare':
        return '☁️';
      case 'vercel':
        return '▲';
      case 'netlify':
        return '◆';
      default:
        return '🚀';
    }
  };

  const getProviderColor = (providerName: string) => {
    switch (providerName.toLowerCase()) {
      case 'cloudflare':
        return 'bg-orange-500/20 text-orange-400 border-orange-500/30';
      case 'vercel':
        return 'bg-white/20 text-white border-white/30';
      case 'netlify':
        return 'bg-teal-500/20 text-teal-400 border-teal-500/30';
      default:
        return 'bg-purple-500/20 text-purple-400 border-purple-500/30';
    }
  };

  const isProviderConnected = (providerName: string) => {
    return credentials.some(c => c.provider === providerName);
  };

  const getCredentialForProvider = (providerName: string) => {
    return credentials.find(c => c.provider === providerName);
  };

  const formatFieldName = (fieldName: string) => {
    return fieldName
      .split('_')
      .map(word => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ');
  };

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--bg)]">
        <LoadingSpinner message="Loading settings..." size={80} />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[var(--bg)]">
      {/* Header */}
      <div className="h-12 bg-[var(--surface)] border-b border-[var(--sidebar-border)] flex items-center px-4 md:px-6 justify-between">
        <div className="flex items-center gap-4">
          <button
            onClick={() => navigate('/dashboard')}
            className="flex items-center gap-2 text-[var(--text)]/60 hover:text-[var(--text)] transition-colors"
          >
            <ArrowLeft size={18} />
            <span className="text-sm font-medium">Back to Dashboard</span>
          </button>
        </div>
        <h1 className="font-heading text-sm font-semibold text-[var(--text)]">Settings</h1>
      </div>

      <div className="max-w-6xl mx-auto p-4 md:p-8">
        {/* Tabs */}
        <div className="flex gap-2 mb-8 border-b border-white/10 pb-2">
          <button
            onClick={() => setActiveTab('deployment')}
            className={`px-4 py-2 rounded-lg font-medium transition-all ${
              activeTab === 'deployment'
                ? 'bg-[var(--primary)]/20 text-[var(--primary)]'
                : 'text-[var(--text)]/60 hover:text-[var(--text)] hover:bg-white/5'
            }`}
          >
            <div className="flex items-center gap-2">
              <CloudArrowUp size={18} />
              Deployment Providers
            </div>
          </button>
          <button
            onClick={() => setActiveTab('api-keys')}
            className={`px-4 py-2 rounded-lg font-medium transition-all ${
              activeTab === 'api-keys'
                ? 'bg-[var(--primary)]/20 text-[var(--primary)]'
                : 'text-[var(--text)]/60 hover:text-[var(--text)] hover:bg-white/5'
            }`}
          >
            <div className="flex items-center gap-2">
              <Key size={18} />
              API Keys
            </div>
          </button>
        </div>

        {/* Deployment Providers Tab */}
        {activeTab === 'deployment' && (
          <div className="space-y-6">
            {/* Header */}
            <div>
              <h2 className="text-2xl font-bold text-[var(--text)] mb-2">Deployment Providers</h2>
              <p className="text-[var(--text)]/60">
                Connect your cloud accounts to deploy projects directly from Tesslate Studio
              </p>
            </div>

            {/* Info Box */}
            <div className="p-4 bg-blue-500/10 border border-blue-500/20 rounded-xl">
              <div className="flex items-start gap-3">
                <Info size={20} className="text-blue-400 mt-0.5 flex-shrink-0" />
                <div className="text-sm text-blue-400">
                  <p className="font-semibold mb-1">Your credentials, your control</p>
                  <p className="text-xs">
                    All credentials are encrypted and stored securely. Deployments happen to your own cloud accounts,
                    giving you full ownership and control of your applications.
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
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {credentials.map((credential) => {
                    const provider = providers.find(p => p.name === credential.provider);
                    if (!provider) return null;

                    return (
                      <div
                        key={credential.id}
                        className="p-4 bg-[var(--surface)] border border-white/10 rounded-xl hover:border-white/20 transition-all"
                      >
                        <div className="flex items-start justify-between">
                          <div className="flex items-start gap-3 flex-1">
                            <div className={`w-12 h-12 rounded-lg flex items-center justify-center text-2xl ${getProviderColor(provider.name)}`}>
                              {getProviderIcon(provider.name)}
                            </div>
                            <div className="flex-1 min-w-0">
                              <h4 className="font-semibold text-[var(--text)] mb-1">
                                {provider.display_name}
                              </h4>
                              <p className="text-xs text-[var(--text)]/60 mb-2">
                                {provider.description}
                              </p>
                              <div className="flex items-center gap-2">
                                <span className="inline-flex items-center gap-1 px-2 py-1 bg-green-500/20 text-green-400 text-xs font-medium rounded-md">
                                  <Check size={12} weight="bold" />
                                  Connected
                                </span>
                                {credential.metadata?.account_name && (
                                  <span className="text-xs text-[var(--text)]/40">
                                    {credential.metadata.account_name}
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
                            className="p-2 text-red-400 hover:bg-red-500/10 rounded-lg transition-colors disabled:opacity-50"
                            title="Disconnect"
                          >
                            {deletingCredentialId === credential.id ? (
                              <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none">
                                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
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
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {providers
                  .filter(provider => !isProviderConnected(provider.name))
                  .map((provider) => (
                    <div
                      key={provider.name}
                      className="p-4 bg-[var(--surface)] border border-white/10 rounded-xl hover:border-white/20 transition-all"
                    >
                      <div className="flex items-start gap-3 mb-4">
                        <div className={`w-12 h-12 rounded-lg flex items-center justify-center text-2xl ${getProviderColor(provider.name)}`}>
                          {getProviderIcon(provider.name)}
                        </div>
                        <div className="flex-1">
                          <h4 className="font-semibold text-[var(--text)] mb-1">
                            {provider.display_name}
                          </h4>
                          <p className="text-xs text-[var(--text)]/60">
                            {provider.description}
                          </p>
                        </div>
                      </div>

                      <button
                        onClick={() => {
                          if (provider.auth_type === 'oauth') {
                            handleOAuthConnect(provider);
                          } else {
                            handleManualConnect(provider);
                          }
                        }}
                        className="w-full px-4 py-2.5 bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white rounded-lg font-semibold transition-all flex items-center justify-center gap-2"
                      >
                        {provider.auth_type === 'oauth' ? (
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
                          {provider.auth_type === 'oauth'
                            ? 'Secure OAuth 2.0 authentication'
                            : 'Encrypted API token storage'}
                        </div>
                      </div>
                    </div>
                  ))}
              </div>

              {providers.filter(p => !isProviderConnected(p.name)).length === 0 && (
                <div className="text-center py-8">
                  <p className="text-[var(--text)]/40 text-sm">
                    All available providers are connected!
                  </p>
                </div>
              )}
            </div>
          </div>
        )}

        {/* API Keys Tab */}
        {activeTab === 'api-keys' && (
          <div className="space-y-6">
            <div>
              <h2 className="text-2xl font-bold text-[var(--text)] mb-2">API Keys</h2>
              <p className="text-[var(--text)]/60">
                Manage your LLM provider API keys (OpenRouter, Anthropic, OpenAI, etc.)
              </p>
            </div>

            <div className="p-8 bg-[var(--surface)] border border-white/10 rounded-xl text-center">
              <Warning size={48} className="text-yellow-400 mx-auto mb-4" />
              <p className="text-[var(--text)]/60">API key management coming soon!</p>
            </div>
          </div>
        )}
      </div>

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
            <div className="p-6 border-b border-white/10">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className={`p-2 rounded-lg ${getProviderColor(selectedProvider.name)}`}>
                    <span className="text-2xl">{getProviderIcon(selectedProvider.name)}</span>
                  </div>
                  <div>
                    <h2 className="text-xl font-bold text-[var(--text)]">
                      Connect {selectedProvider.display_name}
                    </h2>
                    <p className="text-sm text-[var(--text)]/60 mt-1">
                      Enter your API credentials
                    </p>
                  </div>
                </div>
                {!isSaving && (
                  <button
                    onClick={() => setShowManualCredentialModal(false)}
                    className="text-[var(--text)]/60 hover:text-[var(--text)] transition-colors"
                  >
                    <X size={24} />
                  </button>
                )}
              </div>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto p-6 space-y-4">
              {selectedProvider.required_fields.map((field) => (
                <div key={field}>
                  <label htmlFor={field} className="block text-sm font-semibold text-[var(--text)] mb-2">
                    {formatFieldName(field)}
                    <span className="text-red-400 ml-1">*</span>
                  </label>
                  <input
                    id={field}
                    type={field.includes('token') || field.includes('key') ? 'password' : 'text'}
                    value={manualCredentials[field] || ''}
                    onChange={(e) => setManualCredentials({
                      ...manualCredentials,
                      [field]: e.target.value
                    })}
                    placeholder={`Enter your ${formatFieldName(field).toLowerCase()}`}
                    className="w-full px-4 py-3 bg-white/5 border border-white/10 rounded-lg text-[var(--text)] placeholder-[var(--text)]/40 focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
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
                      All API tokens are encrypted using Fernet encryption before being stored.
                      We never log or display your credentials in plain text.
                    </p>
                  </div>
                </div>
              </div>
            </div>

            {/* Footer */}
            <div className="p-6 border-t border-white/10 flex justify-end gap-3">
              <button
                onClick={() => setShowManualCredentialModal(false)}
                disabled={isSaving}
                className="px-6 py-3 bg-white/5 border border-white/10 text-[var(--text)] rounded-lg font-semibold hover:bg-white/10 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Cancel
              </button>
              <button
                onClick={handleSaveManualCredentials}
                disabled={isSaving || selectedProvider.required_fields.some(f => !manualCredentials[f]?.trim())}
                className="px-6 py-3 bg-[var(--primary)] hover:bg-[var(--primary-hover)] disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded-lg font-semibold transition-all flex items-center gap-2"
              >
                {isSaving ? (
                  <>
                    <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
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
    </div>
  );
}
