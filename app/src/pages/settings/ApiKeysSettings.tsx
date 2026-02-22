import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Key, Lock, TrendingUp, Plus, Trash2, Eye, EyeOff, Server, Info } from 'lucide-react';
import {
  SettingsSection,
  SettingsGroup,
  CustomProviderCard,
  CustomProviderModal,
} from '../../components/settings';
import type { CustomProvider } from '../../components/settings';
import { billingApi, secretsApi } from '../../lib/api';
import type { SubscriptionTier } from '../../types/billing';
import toast from 'react-hot-toast';

interface ApiKey {
  id: string;
  provider: string;
  auth_type: string;
  key_name: string | null;
  key_preview: string;
  base_url: string | null;
  created_at: string;
  last_used_at: string | null;
}

interface Provider {
  id: string;
  name: string;
  description: string;
  auth_type: string;
  website: string;
  requires_key: boolean;
  base_url?: string;
  api_type?: string;
}

export default function ApiKeysSettings() {
  const [tier, setTier] = useState<SubscriptionTier>('free');
  const [loading, setLoading] = useState(true);
  const [apiKeys, setApiKeys] = useState<ApiKey[]>([]);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [customProviders, setCustomProviders] = useState<CustomProvider[]>([]);
  const [showAddModal, setShowAddModal] = useState(false);
  const [showAddProviderModal, setShowAddProviderModal] = useState(false);
  const [editingProvider, setEditingProvider] = useState<CustomProvider | null>(null);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      const [subscription, keysData, providersData, customProvidersData] = await Promise.all([
        billingApi.getSubscription(),
        secretsApi.listApiKeys().catch(() => ({ api_keys: [] })),
        secretsApi.getProviders().catch(() => ({ providers: [] })),
        secretsApi.listCustomProviders().catch(() => ({ providers: [] })),
      ]);
      setTier(subscription.tier as SubscriptionTier);
      setApiKeys(keysData.api_keys || []);
      setProviders(providersData.providers || []);
      setCustomProviders(customProvidersData.providers || []);
    } catch (err) {
      console.error('Failed to load data:', err);
    } finally {
      setLoading(false);
    }
  };

  const loadApiKeys = async () => {
    try {
      const data = await secretsApi.listApiKeys();
      setApiKeys(data.api_keys || []);
    } catch (err) {
      console.error('Failed to load API keys:', err);
    }
  };

  const loadCustomProviders = async () => {
    try {
      const data = await secretsApi.listCustomProviders();
      setCustomProviders(data.providers || []);
    } catch (err) {
      console.error('Failed to load custom providers:', err);
    }
  };

  const handleDeleteKey = async (keyId: string) => {
    try {
      await secretsApi.deleteApiKey(keyId);
      toast.success('API key deleted');
      await loadApiKeys();
    } catch {
      toast.error('Failed to delete API key');
    }
  };

  const handleDeleteProvider = async (providerId: string) => {
    try {
      await secretsApi.deleteCustomProvider(providerId);
      toast.success('Custom provider deleted');
      await loadCustomProviders();
    } catch {
      toast.error('Failed to delete provider');
    }
  };

  const byokEnabled = tier === 'pro' || tier === 'ultra';

  if (loading) {
    return (
      <SettingsSection
        title="API Keys"
        description="Manage your LLM provider API keys and custom providers"
      >
        <div className="p-8 bg-[var(--surface)] border border-white/10 rounded-xl">
          <div className="animate-pulse flex flex-col items-center gap-4">
            <div className="w-12 h-12 bg-white/10 rounded-full" />
            <div className="h-4 w-48 bg-white/10 rounded" />
            <div className="h-3 w-64 bg-white/10 rounded" />
          </div>
        </div>
      </SettingsSection>
    );
  }

  if (!byokEnabled) {
    return (
      <SettingsSection
        title="API Keys"
        description="Manage your LLM provider API keys and custom providers"
      >
        <div className="p-8 bg-[var(--surface)] border border-white/10 rounded-xl">
          <div className="flex flex-col items-center text-center">
            <div className="w-16 h-16 bg-[var(--primary)]/20 rounded-full flex items-center justify-center mb-4">
              <Lock className="w-8 h-8 text-[var(--primary)]" />
            </div>
            <h3 className="text-lg font-semibold text-[var(--text)] mb-2">
              Bring Your Own Key (BYOK)
            </h3>
            <p className="text-[var(--text)]/60 text-sm max-w-md mb-6">
              Use your own API keys from OpenRouter, Anthropic, OpenAI, and other providers. This
              feature is available on Pro and Ultra plans.
            </p>
            <div className="w-full max-w-sm mb-6">
              <div className="space-y-3">
                <div className="flex items-center gap-3 text-left">
                  <div className="w-8 h-8 bg-white/5 rounded-lg flex items-center justify-center flex-shrink-0">
                    <Key className="w-4 h-4 text-[var(--text)]/60" />
                  </div>
                  <div>
                    <div className="text-sm font-medium text-[var(--text)]">
                      Use your own API keys
                    </div>
                    <div className="text-xs text-[var(--text)]/50">
                      OpenRouter, Anthropic, OpenAI, etc.
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-3 text-left">
                  <div className="w-8 h-8 bg-white/5 rounded-lg flex items-center justify-center flex-shrink-0">
                    <TrendingUp className="w-4 h-4 text-[var(--text)]/60" />
                  </div>
                  <div>
                    <div className="text-sm font-medium text-[var(--text)]">No credit limits</div>
                    <div className="text-xs text-[var(--text)]/50">
                      Pay directly to your provider
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <Link
              to="/settings/billing"
              className="px-6 py-3 bg-[var(--primary)] text-white font-medium rounded-xl hover:bg-[var(--primary-hover)] transition-colors flex items-center gap-2"
            >
              <TrendingUp className="w-4 h-4" />
              Upgrade to Pro
            </Link>
            <p className="text-xs text-[var(--text)]/40 mt-3">Starting at $20/month</p>
          </div>
        </div>
      </SettingsSection>
    );
  }

  const llmProviders = providers.filter(
    (p) => p.requires_key && (p.api_type === 'openai' || p.api_type === 'anthropic')
  );

  return (
    <SettingsSection
      title="API Keys"
      description="Manage your LLM provider API keys and custom providers"
    >
      {/* API Keys */}
      <SettingsGroup title="Your Keys">
        <div className="p-4 space-y-3">
          {apiKeys.length === 0 ? (
            <div className="text-center py-8">
              <Key className="w-10 h-10 mx-auto mb-3 text-[var(--text)]/20" />
              <p className="text-sm text-[var(--text)]/60 mb-4">No API keys configured yet</p>
              <button
                onClick={() => setShowAddModal(true)}
                className="px-4 py-2 bg-[var(--primary)] hover:bg-[var(--primary)]/90 rounded-lg text-white text-sm transition-colors inline-flex items-center gap-2"
              >
                <Plus className="w-4 h-4" />
                Add Your First Key
              </button>
            </div>
          ) : (
            <>
              {apiKeys.map((key) => (
                <ApiKeyRow key={key.id} apiKey={key} onDelete={handleDeleteKey} />
              ))}
              <button
                onClick={() => setShowAddModal(true)}
                className="w-full px-4 py-2.5 border border-dashed border-[var(--text)]/15 hover:border-[var(--primary)]/40 rounded-lg text-sm text-[var(--text)]/60 hover:text-[var(--primary)] transition-colors flex items-center justify-center gap-2"
              >
                <Plus className="w-4 h-4" />
                Add API Key
              </button>
            </>
          )}
        </div>
      </SettingsGroup>

      {/* Custom Providers */}
      <SettingsGroup title="Custom Providers">
        <div className="p-4 space-y-3">
          {customProviders.length === 0 ? (
            <div className="text-center py-6">
              <Server className="w-8 h-8 mx-auto mb-2 text-[var(--text)]/20" />
              <p className="text-sm text-[var(--text)]/60 mb-1">No custom providers</p>
              <p className="text-xs text-[var(--text)]/40 mb-4">
                Connect Ollama, vLLM, or any OpenAI-compatible API
              </p>
              <button
                onClick={() => {
                  setEditingProvider(null);
                  setShowAddProviderModal(true);
                }}
                className="px-4 py-2 bg-[var(--primary)] hover:bg-[var(--primary)]/90 rounded-lg text-white text-sm transition-colors inline-flex items-center gap-2"
              >
                <Plus className="w-4 h-4" />
                Add Provider
              </button>
            </div>
          ) : (
            <>
              {customProviders.map((cp) => (
                <CustomProviderCard
                  key={cp.id}
                  provider={cp}
                  onEdit={() => {
                    setEditingProvider(cp);
                    setShowAddProviderModal(true);
                  }}
                  onDelete={handleDeleteProvider}
                />
              ))}
              <button
                onClick={() => {
                  setEditingProvider(null);
                  setShowAddProviderModal(true);
                }}
                className="w-full px-4 py-2.5 border border-dashed border-[var(--text)]/15 hover:border-[var(--primary)]/40 rounded-lg text-sm text-[var(--text)]/60 hover:text-[var(--primary)] transition-colors flex items-center justify-center gap-2"
              >
                <Plus className="w-4 h-4" />
                Add Custom Provider
              </button>
            </>
          )}
        </div>
      </SettingsGroup>

      {/* Tip */}
      <div className="flex gap-3 p-4 bg-[var(--primary)]/5 border border-[var(--primary)]/15 rounded-xl">
        <Info className="w-5 h-5 text-[var(--primary)] flex-shrink-0 mt-0.5" />
        <div className="text-sm text-[var(--text)]/70 leading-relaxed">
          <span className="font-medium text-[var(--text)]/90">
            Want to use different models with a built-in provider?
          </span>{' '}
          Create a custom provider using the same base URL and API type. You can find the base URL
          and available model IDs in your provider's API documentation. This lets you configure
          exactly which models appear in the selector.
        </div>
      </div>

      {/* Built-in Providers */}
      <SettingsGroup title="Supported Providers">
        <div className="p-4 grid grid-cols-1 sm:grid-cols-2 gap-3">
          {llmProviders.map((provider) => {
            const hasKey = apiKeys.some((k) => k.provider === provider.id);
            return (
              <div
                key={provider.id}
                className="flex items-center gap-3 p-3 bg-white/[0.02] rounded-lg border border-[var(--text)]/10"
              >
                <div
                  className={`w-2 h-2 rounded-full flex-shrink-0 ${hasKey ? 'bg-green-500' : 'bg-[var(--text)]/20'}`}
                />
                <div className="min-w-0">
                  <div className="text-sm font-medium text-[var(--text)]">{provider.name}</div>
                  <div className="text-xs text-[var(--text)]/50 truncate">
                    {provider.description}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </SettingsGroup>

      {showAddModal && (
        <AddApiKeyModal
          providers={providers}
          customProviders={customProviders}
          onClose={() => setShowAddModal(false)}
          onSuccess={() => {
            setShowAddModal(false);
            loadApiKeys();
          }}
        />
      )}

      {showAddProviderModal && (
        <CustomProviderModal
          existing={editingProvider}
          onClose={() => {
            setShowAddProviderModal(false);
            setEditingProvider(null);
          }}
          onSuccess={() => {
            setShowAddProviderModal(false);
            setEditingProvider(null);
            loadCustomProviders();
          }}
        />
      )}
    </SettingsSection>
  );
}

// ─── API Key Row ─────────────────────────────────────────────────────────────

function ApiKeyRow({ apiKey, onDelete }: { apiKey: ApiKey; onDelete: (id: string) => void }) {
  const [confirmDelete, setConfirmDelete] = useState(false);

  return (
    <div className="flex items-center justify-between p-3 bg-white/[0.02] rounded-lg border border-[var(--text)]/10">
      <div className="flex items-center gap-3 min-w-0">
        <div className="p-2 bg-[var(--primary)]/10 rounded-lg flex-shrink-0">
          <Key className="w-4 h-4 text-[var(--primary)]" />
        </div>
        <div className="min-w-0">
          <div className="text-sm font-medium text-[var(--text)] capitalize">{apiKey.provider}</div>
          {apiKey.key_name && (
            <div className="text-xs text-[var(--text)]/60">{apiKey.key_name}</div>
          )}
          <div className="text-xs text-[var(--text)]/40 font-mono mt-0.5">{apiKey.key_preview}</div>
          {apiKey.base_url && (
            <div className="text-xs text-[var(--text)]/40 font-mono truncate mt-0.5">
              {apiKey.base_url}
            </div>
          )}
        </div>
      </div>
      <div className="flex items-center gap-2 flex-shrink-0">
        <span className="text-xs text-[var(--text)]/30">
          {new Date(apiKey.created_at).toLocaleDateString()}
        </span>
        {confirmDelete ? (
          <div className="flex items-center gap-1">
            <button
              onClick={() => onDelete(apiKey.id)}
              className="px-2 py-1 text-xs bg-red-500/20 text-red-400 rounded hover:bg-red-500/30 transition-colors"
            >
              Confirm
            </button>
            <button
              onClick={() => setConfirmDelete(false)}
              className="px-2 py-1 text-xs bg-white/5 text-[var(--text)]/60 rounded hover:bg-white/10 transition-colors"
            >
              Cancel
            </button>
          </div>
        ) : (
          <button
            onClick={() => setConfirmDelete(true)}
            className="p-1.5 hover:bg-red-500/10 rounded-lg text-[var(--text)]/40 hover:text-red-400 transition-colors"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        )}
      </div>
    </div>
  );
}

// ─── Add API Key Modal ───────────────────────────────────────────────────────

function AddApiKeyModal({
  providers,
  customProviders = [],
  onClose,
  onSuccess,
}: {
  providers: Provider[];
  customProviders?: CustomProvider[];
  onClose: () => void;
  onSuccess: () => void;
}) {
  const [provider, setProvider] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [keyName, setKeyName] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [showKey, setShowKey] = useState(false);
  const [loading, setLoading] = useState(false);

  const selectedCustomProvider = customProviders.find((cp) => cp.slug === provider);
  const isCustomProvider = !!selectedCustomProvider;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      await secretsApi.addApiKey({
        provider,
        api_key: apiKey,
        key_name: keyName || undefined,
        base_url: baseUrl || undefined,
      });
      toast.success('API key added successfully');
      onSuccess();
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to add API key');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-[var(--surface)] border border-[var(--text)]/15 rounded-xl max-w-md w-full p-6">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-lg font-semibold text-[var(--text)]">Add API Key</h2>
          <button
            onClick={onClose}
            className="p-2 hover:bg-white/5 rounded-lg transition-colors text-[var(--text)]/60 text-sm"
          >
            Cancel
          </button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-[var(--text)] mb-2">Provider</label>
            <select
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              className="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--text)]/15 rounded-lg text-[var(--text)] focus:outline-none focus:border-[var(--primary)]/50 [&>option]:bg-[var(--surface)] [&>option]:text-[var(--text)]"
              required
            >
              <option value="">Select a provider...</option>
              {providers
                .filter((p) => p.requires_key)
                .map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              {customProviders.length > 0 && (
                <optgroup label="Custom Providers">
                  {customProviders.map((cp) => (
                    <option key={cp.slug} value={cp.slug}>
                      {cp.name}
                    </option>
                  ))}
                </optgroup>
              )}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-[var(--text)] mb-2">API Key</label>
            <div className="relative">
              <input
                type={showKey ? 'text' : 'password'}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                className="w-full px-4 py-2 pr-12 bg-white/5 border border-[var(--text)]/15 rounded-lg text-[var(--text)] focus:outline-none focus:border-[var(--primary)]/50 font-mono text-sm"
                placeholder="sk-..."
                required
              />
              <button
                type="button"
                onClick={() => setShowKey(!showKey)}
                className="absolute right-3 top-1/2 -translate-y-1/2 p-1 hover:bg-white/5 rounded transition-colors text-[var(--text)]/60"
              >
                {showKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-[var(--text)] mb-2">
              Key Name (Optional)
            </label>
            <input
              type="text"
              value={keyName}
              onChange={(e) => setKeyName(e.target.value)}
              className="w-full px-4 py-2 bg-white/5 border border-[var(--text)]/15 rounded-lg text-[var(--text)] focus:outline-none focus:border-[var(--primary)]/50 text-sm"
              placeholder="My API Key"
            />
            <p className="mt-1 text-xs text-[var(--text)]/40">
              Defaults to provider name if left empty
            </p>
          </div>
          {isCustomProvider && (
            <div>
              <label className="block text-sm font-medium text-[var(--text)] mb-2">
                Base URL (Optional)
              </label>
              <input
                type="url"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                className="w-full px-4 py-2 bg-white/5 border border-[var(--text)]/15 rounded-lg text-[var(--text)] focus:outline-none focus:border-[var(--primary)]/50 font-mono text-sm"
                placeholder={selectedCustomProvider?.base_url || 'https://api.example.com/v1'}
              />
              <p className="mt-1 text-xs text-[var(--text)]/40">
                Override the provider's default base URL for this key
              </p>
            </div>
          )}
          <div className="flex items-center gap-3 justify-end pt-4 border-t border-[var(--text)]/10">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 bg-white/5 hover:bg-white/10 rounded-lg text-[var(--text)]/80 text-sm transition-colors"
              disabled={loading}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-5 py-2 bg-[var(--primary)] hover:bg-[var(--primary)]/90 rounded-lg text-white text-sm transition-colors flex items-center gap-2 disabled:opacity-50"
              disabled={loading || !provider || !apiKey}
            >
              {loading ? 'Adding...' : 'Add Key'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
