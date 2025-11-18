import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  CloudArrowUp,
  Plus,
  Trash,
  CheckCircle,
  XCircle,
  Spinner,
  Eye,
  EyeSlash,
  Info
} from '@phosphor-icons/react';
import { deploymentCredentialsApi } from '../lib/api';
import toast from 'react-hot-toast';

interface Provider {
  name: string;
  display_name: string;
  description: string;
  auth_type: string;
  required_credentials: string[];
  optional_credentials?: string[];
}

interface DeploymentCredential {
  id: string;
  provider: string;
  metadata: Record<string, any>;
  created_at: string;
}

export default function AccountSettings() {
  const navigate = useNavigate();
  const [providers, setProviders] = useState<Provider[]>([]);
  const [credentials, setCredentials] = useState<DeploymentCredential[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedProvider, setExpandedProvider] = useState<string | null>(null);
  const [formData, setFormData] = useState<Record<string, Record<string, string>>>({});
  const [showSecret, setShowSecret] = useState<Record<string, boolean>>({});
  const [savingProvider, setSavingProvider] = useState<string | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

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
      console.error('Failed to load data:', error);
      toast.error(error.response?.data?.detail || 'Failed to load deployment providers');
    } finally {
      setLoading(false);
    }
  };

  const toggleProvider = (providerName: string) => {
    if (expandedProvider === providerName) {
      setExpandedProvider(null);
    } else {
      setExpandedProvider(providerName);
      // Initialize form data for this provider if not already done
      if (!formData[providerName]) {
        const provider = providers.find(p => p.name === providerName);
        if (provider) {
          const initialData: Record<string, string> = {};
          provider.required_credentials.forEach(field => {
            initialData[field] = '';
          });
          setFormData({ ...formData, [providerName]: initialData });
        }
      }
    }
  };

  const handleFormChange = (providerName: string, field: string, value: string) => {
    setFormData({
      ...formData,
      [providerName]: {
        ...formData[providerName],
        [field]: value
      }
    });
  };

  const handleConnect = async (providerName: string) => {
    const provider = providers.find(p => p.name === providerName);
    if (!provider) return;

    // For OAuth providers, start OAuth flow
    if (provider.auth_type === 'oauth') {
      try {
        await deploymentCredentialsApi.startOAuth(providerName);
      } catch (error: any) {
        console.error('Failed to start OAuth:', error);
        toast.error(error.response?.data?.detail || 'Failed to start OAuth flow');
      }
      return;
    }

    // Validate required credentials
    const providerFormData = formData[providerName] || {};
    for (const field of provider.required_credentials) {
      if (!providerFormData[field] || !providerFormData[field].trim()) {
        toast.error(`${field} is required`);
        return;
      }
    }

    setSavingProvider(providerName);
    try {
      // Separate access_token from metadata
      const { access_token, api_token, token, ...metadata } = providerFormData;
      const tokenValue = access_token || api_token || token;

      if (!tokenValue) {
        toast.error('API token is required');
        return;
      }

      await deploymentCredentialsApi.create({
        provider: providerName,
        access_token: tokenValue,
        metadata,
      });

      toast.success(`Successfully connected to ${provider.display_name}`);
      setExpandedProvider(null);
      await loadData();
    } catch (error: any) {
      console.error('Failed to add credential:', error);
      toast.error(error.response?.data?.detail || 'Failed to add credential');
    } finally {
      setSavingProvider(null);
    }
  };

  const handleTest = async (credentialId: string) => {
    setTestingId(credentialId);
    try {
      const result = await deploymentCredentialsApi.test(credentialId);
      if (result.valid) {
        toast.success('Connection test successful!');
      } else {
        toast.error(result.error || 'Connection test failed');
      }
    } catch (error: any) {
      console.error('Test failed:', error);
      toast.error(error.response?.data?.detail || 'Failed to test connection');
    } finally {
      setTestingId(null);
    }
  };

  const handleDelete = async (credentialId: string, providerName: string) => {
    if (!confirm(`Are you sure you want to disconnect ${providerName}?`)) {
      return;
    }

    setDeletingId(credentialId);
    try {
      await deploymentCredentialsApi.delete(credentialId);
      toast.success('Credential removed successfully');
      await loadData();
    } catch (error: any) {
      console.error('Failed to delete credential:', error);
      toast.error(error.response?.data?.detail || 'Failed to remove credential');
    } finally {
      setDeletingId(null);
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

  const getProviderDisplay = (providerName: string) => {
    const provider = providers.find(p => p.name === providerName);
    return provider?.display_name || providerName.charAt(0).toUpperCase() + providerName.slice(1);
  };

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric'
    });
  };

  const getCredentialForProvider = (providerName: string) => {
    return credentials.find(c => c.provider === providerName);
  };

  const isProviderConnected = (providerName: string) => {
    return credentials.some(c => c.provider === providerName);
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-[var(--background)] to-[var(--background-dark)]">
      <div className="max-w-4xl mx-auto px-6 py-12">
        {/* Header */}
        <div className="mb-12">
          <button
            onClick={() => navigate('/dashboard')}
            className="flex items-center gap-2 text-[var(--text)]/60 hover:text-[var(--text)] transition-colors mb-6"
          >
            <ArrowLeft size={20} />
            Back to Dashboard
          </button>
          <h1 className="text-3xl font-bold text-[var(--text)] mb-2">Settings</h1>
          <p className="text-[var(--text)]/60">
            Manage your account and application settings
          </p>
        </div>

        {/* Deployment Providers Section */}
        <div className="mb-12">
          <div className="mb-6">
            <div className="flex items-center gap-2 mb-2">
              <h2 className="text-xl font-bold text-[var(--text)]">Deployment Providers</h2>
              <div className="group relative">
                <Info
                  size={20}
                  className="text-[var(--text)]/40 hover:text-[var(--text)]/60 transition-colors cursor-help"
                  weight="fill"
                />
                <div className="absolute left-1/2 -translate-x-1/2 bottom-full mb-2 w-80 p-4 bg-[var(--surface)] border border-white/20 rounded-lg shadow-xl opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-200 z-50">
                  <div className="text-xs text-[var(--text)]/80 space-y-2">
                    <p className="font-semibold text-[var(--text)]">About deployment credentials</p>
                    <ul className="space-y-1.5 list-disc list-inside">
                      <li>Your credentials are encrypted and stored securely</li>
                      <li>They are never exposed in logs or error messages</li>
                      <li>You can test and remove connections at any time</li>
                      <li>OAuth providers offer the most secure authentication method</li>
                    </ul>
                  </div>
                  <div className="absolute left-1/2 -translate-x-1/2 top-full w-0 h-0 border-l-8 border-r-8 border-t-8 border-l-transparent border-r-transparent border-t-white/20"></div>
                </div>
              </div>
            </div>
            <p className="text-sm text-[var(--text)]/60">
              Connect deployment providers to deploy your projects
            </p>
          </div>

          {/* Loading State */}
          {loading ? (
            <div className="flex items-center justify-center py-20">
              <Spinner size={40} className="text-purple-400 animate-spin" />
            </div>
          ) : (
            <div className="space-y-4">
              {/* Provider List */}
              {providers.map((provider) => {
              const credential = getCredentialForProvider(provider.name);
              const isConnected = isProviderConnected(provider.name);
              const isExpanded = expandedProvider === provider.name;
              const isSaving = savingProvider === provider.name;
              const isTesting = testingId === credential?.id;
              const isDeleting = deletingId === credential?.id;

              return (
                <div
                  key={provider.name}
                  className="bg-[var(--surface)] border border-white/10 rounded-xl overflow-hidden hover:border-white/20 transition-all"
                >
                  {/* Provider Header */}
                  <div className="p-6">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-4">
                        <div className={`p-3 rounded-lg ${getProviderColor(provider.name)}`}>
                          <CloudArrowUp size={28} />
                        </div>
                        <div>
                          <div className="flex items-center gap-3">
                            <h3 className="text-lg font-semibold text-[var(--text)]">
                              {provider.display_name}
                            </h3>
                            {isConnected && (
                              <span className="flex items-center gap-1.5 px-2.5 py-1 bg-green-500/20 text-green-400 text-xs font-semibold rounded-full">
                                <CheckCircle size={14} weight="fill" />
                                Connected
                              </span>
                            )}
                          </div>
                          <p className="text-sm text-[var(--text)]/60 mt-1">
                            {provider.description || (provider.auth_type === 'oauth' ? 'OAuth 2.0' : 'API Token')}
                          </p>
                          {credential && (
                            <p className="text-xs text-[var(--text)]/50 mt-1">
                              Connected on {formatDate(credential.created_at)}
                            </p>
                          )}
                        </div>
                      </div>

                      {/* Action Buttons */}
                      <div className="flex items-center gap-2">
                        {isConnected ? (
                          <>
                            <button
                              onClick={() => handleTest(credential!.id)}
                              disabled={isTesting}
                              className="px-4 py-2 bg-blue-500/20 text-blue-400 hover:bg-blue-500/30 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg font-semibold transition-all flex items-center gap-2 text-sm"
                            >
                              {isTesting ? (
                                <>
                                  <Spinner size={16} className="animate-spin" />
                                  Testing
                                </>
                              ) : (
                                <>
                                  <CheckCircle size={16} />
                                  Test
                                </>
                              )}
                            </button>
                            <button
                              onClick={() => handleDelete(credential!.id, provider.display_name)}
                              disabled={isDeleting}
                              className="px-4 py-2 bg-red-500/20 text-red-400 hover:bg-red-500/30 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg font-semibold transition-all flex items-center gap-2 text-sm"
                            >
                              {isDeleting ? (
                                <>
                                  <Spinner size={16} className="animate-spin" />
                                  Removing
                                </>
                              ) : (
                                <>
                                  <Trash size={16} />
                                  Remove
                                </>
                              )}
                            </button>
                          </>
                        ) : (
                          <button
                            onClick={() => toggleProvider(provider.name)}
                            className="px-6 py-2 bg-orange-500/20 text-orange-400 hover:bg-orange-500/30 rounded-lg font-semibold transition-all text-sm"
                          >
                            {isExpanded ? 'Cancel' : 'Connect'}
                          </button>
                        )}
                      </div>
                    </div>

                    {/* Metadata Display for Connected Providers */}
                    {credential?.metadata && Object.keys(credential.metadata).length > 0 && (
                      <div className="mt-4 pt-4 border-t border-white/10">
                        <div className="flex flex-wrap gap-2">
                          {Object.entries(credential.metadata).map(([key, value]) => (
                            <span
                              key={key}
                              className="text-xs px-3 py-1.5 bg-white/5 rounded-lg text-[var(--text)]/60 border border-white/10"
                            >
                              <span className="font-semibold">{key}:</span> {String(value)}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Expandable Form for Non-Connected Providers */}
                  {!isConnected && isExpanded && (
                    <div className="px-6 pb-6 pt-2 border-t border-white/10 bg-white/5">
                      <div className="space-y-4">
                        {provider.auth_type === 'oauth' ? (
                          <div className="py-4 text-center">
                            <p className="text-sm text-[var(--text)]/60 mb-4">
                              You'll be redirected to authorize {provider.display_name}
                            </p>
                            <button
                              onClick={() => handleConnect(provider.name)}
                              disabled={isSaving}
                              className="px-6 py-3 bg-orange-500 hover:bg-orange-600 disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded-lg font-semibold transition-all flex items-center gap-2 mx-auto"
                            >
                              {isSaving ? (
                                <>
                                  <Spinner size={18} className="animate-spin" />
                                  Redirecting...
                                </>
                              ) : (
                                <>
                                  <CloudArrowUp size={18} />
                                  Authorize with {provider.display_name}
                                </>
                              )}
                            </button>
                          </div>
                        ) : (
                          <>
                            {provider.required_credentials.map((field) => (
                              <div key={field}>
                                <label className="block text-sm font-semibold text-[var(--text)] mb-2">
                                  {field.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')}
                                </label>
                                <div className="relative">
                                  <input
                                    type={field.includes('token') || field.includes('secret') ? (showSecret[field] ? 'text' : 'password') : 'text'}
                                    value={formData[provider.name]?.[field] || ''}
                                    onChange={(e) => handleFormChange(provider.name, field, e.target.value)}
                                    placeholder={`Enter ${field}`}
                                    className="w-full px-4 py-3 bg-white/5 border border-white/10 rounded-lg text-[var(--text)] placeholder-[var(--text)]/40 focus:outline-none focus:ring-2 focus:ring-orange-500 pr-12"
                                  />
                                  {(field.includes('token') || field.includes('secret')) && (
                                    <button
                                      type="button"
                                      onClick={() => setShowSecret({ ...showSecret, [field]: !showSecret[field] })}
                                      className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--text)]/60 hover:text-[var(--text)] transition-colors"
                                    >
                                      {showSecret[field] ? <EyeSlash size={20} /> : <Eye size={20} />}
                                    </button>
                                  )}
                                </div>
                                <p className="text-xs text-[var(--text)]/50 mt-1.5">
                                  {field.includes('token') ? 'Encrypted and stored securely' : ''}
                                </p>
                              </div>
                            ))}

                            <button
                              onClick={() => handleConnect(provider.name)}
                              disabled={isSaving}
                              className="w-full mt-4 px-6 py-3 bg-orange-500 hover:bg-orange-600 disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded-lg font-semibold transition-all flex items-center justify-center gap-2"
                            >
                              {isSaving ? (
                                <>
                                  <Spinner size={18} className="animate-spin" />
                                  Connecting...
                                </>
                              ) : (
                                <>
                                  <CloudArrowUp size={18} />
                                  Connect {provider.display_name}
                                </>
                              )}
                            </button>
                          </>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              );
              })}
            </div>
          )}
        </div>

        {/* Future sections can be added here */}
        {/* Example: Profile Settings, Notification Preferences, etc. */}
      </div>
    </div>
  );
}
