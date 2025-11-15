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
  WarningCircle
} from '@phosphor-icons/react';
import { deploymentCredentialsApi } from '../lib/api';
import toast from 'react-hot-toast';
import { DashboardLayout } from '../components/DashboardLayout';

interface Provider {
  name: string;
  display_name: string;
  auth_type: string;
  required_fields: string[];
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
  const [showAddModal, setShowAddModal] = useState(false);
  const [selectedProvider, setSelectedProvider] = useState<string | null>(null);
  const [formData, setFormData] = useState<Record<string, string>>({});
  const [showSecret, setShowSecret] = useState<Record<string, boolean>>({});
  const [isAdding, setIsAdding] = useState(false);
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

  const handleAddCredential = () => {
    setShowAddModal(true);
    setFormData({});
    setShowSecret({});
  };

  const handleProviderSelect = (providerName: string) => {
    setSelectedProvider(providerName);
    const provider = providers.find(p => p.name === providerName);
    if (provider) {
      // Initialize form data with empty values for required fields
      const initialData: Record<string, string> = {};
      provider.required_fields.forEach(field => {
        initialData[field] = '';
      });
      setFormData(initialData);
    }
  };

  const handleFormChange = (field: string, value: string) => {
    setFormData({ ...formData, [field]: value });
  };

  const handleSubmit = async () => {
    if (!selectedProvider) {
      toast.error('Please select a provider');
      return;
    }

    const provider = providers.find(p => p.name === selectedProvider);
    if (!provider) return;

    // Validate required fields
    for (const field of provider.required_fields) {
      if (!formData[field] || !formData[field].trim()) {
        toast.error(`${field} is required`);
        return;
      }
    }

    setIsAdding(true);
    try {
      // Separate access_token from metadata
      const { access_token, api_token, token, ...metadata } = formData;
      const tokenValue = access_token || api_token || token;

      if (!tokenValue) {
        toast.error('API token is required');
        return;
      }

      await deploymentCredentialsApi.create({
        provider: selectedProvider,
        access_token: tokenValue,
        metadata,
      });

      toast.success(`Successfully connected to ${provider.display_name}`);
      setShowAddModal(false);
      await loadData();
    } catch (error: any) {
      console.error('Failed to add credential:', error);
      toast.error(error.response?.data?.detail || 'Failed to add credential');
    } finally {
      setIsAdding(false);
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

  const connectedProviderNames = credentials.map(c => c.provider);
  const availableProviders = providers.filter(p => !connectedProviderNames.includes(p.name));

  return (
    <DashboardLayout>
      <div className="min-h-screen bg-gradient-to-br from-[var(--background)] to-[var(--background-dark)]">
        <div className="max-w-5xl mx-auto px-6 py-12">
          {/* Header */}
          <div className="mb-8">
            <button
              onClick={() => navigate('/dashboard')}
              className="flex items-center gap-2 text-[var(--text)]/60 hover:text-[var(--text)] transition-colors mb-6"
            >
              <ArrowLeft size={20} />
              Back to Dashboard
            </button>
            <div className="flex items-center justify-between">
              <div>
                <h1 className="text-3xl font-bold text-[var(--text)] mb-2">Account Settings</h1>
                <p className="text-[var(--text)]/60">
                  Manage your deployment provider connections
                </p>
              </div>
              <button
                onClick={handleAddCredential}
                disabled={availableProviders.length === 0}
                className="flex items-center gap-2 bg-orange-500 hover:bg-orange-600 disabled:bg-gray-600 disabled:cursor-not-allowed text-white px-6 py-3 rounded-lg font-semibold transition-all"
                title={availableProviders.length === 0 ? 'All providers are already connected' : 'Add deployment provider'}
              >
                <Plus size={20} weight="bold" />
                Add Provider
              </button>
            </div>
          </div>

          {/* Connected Providers */}
          {loading ? (
            <div className="flex items-center justify-center py-20">
              <Spinner size={40} className="text-purple-400 animate-spin" />
            </div>
          ) : credentials.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 text-center">
              <div className="p-6 bg-purple-500/10 rounded-full mb-6">
                <CloudArrowUp size={60} className="text-purple-400" />
              </div>
              <h2 className="text-2xl font-bold text-[var(--text)] mb-2">
                No providers connected
              </h2>
              <p className="text-[var(--text)]/60 mb-8 max-w-md">
                Connect deployment providers like Cloudflare, Vercel, or Netlify to deploy your projects with one click
              </p>
              <button
                onClick={handleAddCredential}
                className="flex items-center gap-2 bg-orange-500 hover:bg-orange-600 text-white px-8 py-4 rounded-lg font-semibold transition-all"
              >
                <Plus size={20} weight="bold" />
                Connect Your First Provider
              </button>
            </div>
          ) : (
            <div className="grid gap-6">
              {credentials.map((credential) => (
                <div
                  key={credential.id}
                  className="bg-[var(--surface)] border border-white/10 rounded-2xl p-6 hover:border-white/20 transition-all"
                >
                  <div className="flex items-start justify-between">
                    <div className="flex items-center gap-4">
                      <div className={`p-4 rounded-xl ${getProviderColor(credential.provider)}`}>
                        <CloudArrowUp size={32} />
                      </div>
                      <div>
                        <h3 className="text-lg font-semibold text-[var(--text)]">
                          {getProviderDisplay(credential.provider)}
                        </h3>
                        <p className="text-sm text-[var(--text)]/60 mt-1">
                          Connected on {formatDate(credential.created_at)}
                        </p>
                        {credential.metadata && Object.keys(credential.metadata).length > 0 && (
                          <div className="mt-2 flex flex-wrap gap-2">
                            {Object.entries(credential.metadata).map(([key, value]) => (
                              <span
                                key={key}
                                className="text-xs px-2 py-1 bg-white/5 rounded-md text-[var(--text)]/60"
                              >
                                {key}: {String(value)}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => handleTest(credential.id)}
                        disabled={testingId === credential.id}
                        className="px-4 py-2 bg-blue-500/20 text-blue-400 hover:bg-blue-500/30 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg font-semibold transition-all flex items-center gap-2 text-sm"
                      >
                        {testingId === credential.id ? (
                          <>
                            <Spinner size={16} className="animate-spin" />
                            Testing...
                          </>
                        ) : (
                          <>
                            <CheckCircle size={16} />
                            Test
                          </>
                        )}
                      </button>
                      <button
                        onClick={() => handleDelete(credential.id, getProviderDisplay(credential.provider))}
                        disabled={deletingId === credential.id}
                        className="px-4 py-2 bg-red-500/20 text-red-400 hover:bg-red-500/30 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg font-semibold transition-all flex items-center gap-2 text-sm"
                      >
                        {deletingId === credential.id ? (
                          <>
                            <Spinner size={16} className="animate-spin" />
                            Removing...
                          </>
                        ) : (
                          <>
                            <Trash size={16} />
                            Remove
                          </>
                        )}
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Help Text */}
          {credentials.length > 0 && (
            <div className="mt-8 p-6 bg-blue-500/10 border border-blue-500/20 rounded-xl">
              <div className="flex items-start gap-3">
                <WarningCircle size={24} className="text-blue-400 mt-0.5 flex-shrink-0" />
                <div className="text-sm text-blue-400">
                  <p className="font-semibold mb-2">About deployment credentials:</p>
                  <ul className="list-disc list-inside space-y-1 text-xs">
                    <li>Your credentials are encrypted and stored securely</li>
                    <li>They are never exposed in logs or error messages</li>
                    <li>You can remove them at any time</li>
                    <li>Use "Test" to verify your connection is working</li>
                  </ul>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Add Provider Modal */}
      {showAddModal && (
        <div
          className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50"
          onClick={() => !isAdding && setShowAddModal(false)}
        >
          <div
            className="bg-[var(--surface)] rounded-3xl w-full max-w-2xl shadow-2xl border border-white/10 max-h-[90vh] overflow-hidden flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div className="p-6 border-b border-white/10">
              <h2 className="text-xl font-bold text-[var(--text)]">Add Deployment Provider</h2>
              <p className="text-sm text-[var(--text)]/60 mt-1">
                Connect your account to deploy projects
              </p>
            </div>

            {/* Modal Content */}
            <div className="flex-1 overflow-y-auto p-6 space-y-6">
              {!selectedProvider ? (
                <>
                  <p className="text-sm text-[var(--text)]/60">
                    Select a deployment provider to connect:
                  </p>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    {availableProviders.map((provider) => (
                      <button
                        key={provider.name}
                        onClick={() => handleProviderSelect(provider.name)}
                        className={`p-6 rounded-xl border-2 transition-all text-left hover:border-orange-500/50 ${getProviderColor(provider.name)}`}
                      >
                        <div className="flex items-center gap-3 mb-2">
                          <CloudArrowUp size={32} />
                          <h3 className="font-semibold text-lg">{provider.display_name}</h3>
                        </div>
                        <p className="text-xs opacity-80">
                          {provider.auth_type === 'oauth' ? 'OAuth 2.0 (Recommended)' : 'API Token'}
                        </p>
                      </button>
                    ))}
                  </div>
                </>
              ) : (
                <>
                  <div className="flex items-center gap-3 mb-4">
                    <button
                      onClick={() => setSelectedProvider(null)}
                      disabled={isAdding}
                      className="p-2 hover:bg-white/5 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      <ArrowLeft size={20} className="text-[var(--text)]/60" />
                    </button>
                    <div>
                      <h3 className="text-lg font-semibold text-[var(--text)]">
                        {getProviderDisplay(selectedProvider)}
                      </h3>
                      <p className="text-xs text-[var(--text)]/60">
                        Enter your credentials below
                      </p>
                    </div>
                  </div>

                  {providers.find(p => p.name === selectedProvider)?.required_fields.map((field) => (
                    <div key={field}>
                      <label className="block text-sm font-semibold text-[var(--text)] mb-2">
                        {field.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')}
                      </label>
                      <div className="relative">
                        <input
                          type={field.includes('token') || field.includes('secret') ? (showSecret[field] ? 'text' : 'password') : 'text'}
                          value={formData[field] || ''}
                          onChange={(e) => handleFormChange(field, e.target.value)}
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
                      <p className="text-xs text-[var(--text)]/60 mt-1">
                        {field.includes('token') ? 'This will be encrypted and stored securely' : ''}
                      </p>
                    </div>
                  ))}
                </>
              )}
            </div>

            {/* Modal Footer */}
            {selectedProvider && (
              <div className="p-6 border-t border-white/10 flex justify-end gap-3">
                <button
                  onClick={() => setShowAddModal(false)}
                  disabled={isAdding}
                  className="px-6 py-3 bg-white/5 border border-white/10 text-[var(--text)] rounded-lg font-semibold hover:bg-white/10 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Cancel
                </button>
                <button
                  onClick={handleSubmit}
                  disabled={isAdding}
                  className="px-6 py-3 bg-orange-500 hover:bg-orange-600 disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded-lg font-semibold transition-all flex items-center gap-2"
                >
                  {isAdding ? (
                    <>
                      <Spinner size={18} className="animate-spin" />
                      Connecting...
                    </>
                  ) : (
                    <>
                      <Plus size={18} weight="bold" />
                      Connect
                    </>
                  )}
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </DashboardLayout>
  );
}
