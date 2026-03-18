import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Cpu,
  Plus,
  Key,
  Trash,
  LockKey,
  Rocket,
  Plugs,
  Eye,
  EyeSlash,
  X,
  MagnifyingGlass,
  ToggleLeft,
  ToggleRight,
} from '@phosphor-icons/react';
import { LoadingSpinner } from '../../components/PulsingGridSpinner';
import {
  CustomProviderCard,
  CustomProviderModal,
  type CustomProvider,
} from '../../components/settings/CustomProviderComponents';
import { marketplaceApi, secretsApi } from '../../lib/api';
import toast from 'react-hot-toast';

// ─── Types ──────────────────────────────────────────────────────────

export interface ModelInfo {
  id: string;
  name: string;
  source: 'system' | 'provider' | 'custom';
  provider: string;
  provider_name?: string;
  pricing: { input: number; output: number } | null;
  available: boolean;
  health?: string | null;
  custom_id?: string;
  disabled?: boolean;
}

export interface ApiKey {
  id: string;
  provider: string;
  auth_type: string;
  key_name: string | null;
  key_preview: string;
  base_url: string | null;
  created_at: string;
  last_used_at: string | null;
}

export interface Provider {
  id: string;
  name: string;
  description: string;
  auth_type: string;
  website: string;
  requires_key: boolean;
  base_url?: string;
  api_type?: string;
}

// ─── Helpers ────────────────────────────────────────────────────────

function formatCreditsPerMillion(usdPer1M: number): string {
  const credits = usdPer1M * 100;
  if (credits === 0) return '0';
  if (Number.isInteger(credits)) return credits.toLocaleString();
  return credits.toFixed(1);
}

function getProviderLabel(provider: string, providerName?: string): string {
  if (providerName) return providerName;
  const labels: Record<string, string> = {
    internal: 'Tesslate',
    openai: 'OpenAI',
    anthropic: 'Anthropic',
    groq: 'Groq',
    together: 'Together AI',
    deepseek: 'DeepSeek',
    fireworks: 'Fireworks',
    openrouter: 'OpenRouter',
    'nano-gpt': 'NanoGPT',
  };
  return labels[provider] || provider.charAt(0).toUpperCase() + provider.slice(1);
}

// ─── ModelCard ──────────────────────────────────────────────────────

function ModelCard({
  model,
  onToggle,
  onDelete,
}: {
  model: ModelInfo;
  onToggle: (id: string, enabled: boolean) => void;
  onDelete?: (customId: string) => void;
}) {
  const isDisabled = model.disabled;
  const displayName = model.name.includes('/') ? model.name.split('/').pop() : model.name;

  return (
    <div
      className={`bg-[var(--surface-hover)] border rounded-[var(--radius)] p-3 transition-all ${
        isDisabled
          ? 'border-[var(--border)] opacity-50'
          : 'border-[var(--border)] hover:border-[var(--border-hover)]'
      }`}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2.5 min-w-0">
          <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
            model.health === 'operational' ? 'bg-[var(--status-success)]'
            : model.health === 'unhealthy' ? 'bg-[var(--status-error)]'
            : isDisabled ? 'bg-[var(--text-subtle)]'
            : 'bg-[var(--text-muted)]'
          }`} />
          <div className="min-w-0">
            <div className="text-xs font-medium text-[var(--text)] truncate">{displayName}</div>
            {model.pricing && (model.pricing.input > 0 || model.pricing.output > 0) && (
              <div className="text-[10px] text-[var(--text-subtle)] font-mono mt-0.5">
                {formatCreditsPerMillion(model.pricing.input)}/{formatCreditsPerMillion(model.pricing.output)} per 1M
              </div>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1.5 flex-shrink-0">
          {model.custom_id && onDelete && (
            <button
              onClick={() => onDelete(model.custom_id!)}
              className="btn btn-icon btn-sm btn-danger"
              title="Remove"
            >
              <X size={12} />
            </button>
          )}
          <button
            onClick={() => onToggle(model.id, !!isDisabled)}
            className="text-[var(--text-muted)] hover:text-[var(--text)] transition-colors"
            title={isDisabled ? 'Enable model' : 'Disable model'}
          >
            {isDisabled ? (
              <ToggleLeft size={18} />
            ) : (
              <ToggleRight size={18} className="text-[var(--primary)]" />
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── ApiKeyCard ─────────────────────────────────────────────────────

function ApiKeyCard({ apiKey, onReload }: { apiKey: ApiKey; onReload: () => void }) {
  const [showDelete, setShowDelete] = useState(false);

  const handleDelete = async () => {
    try {
      await secretsApi.deleteApiKey(apiKey.id);
      toast.success('API key deleted');
      onReload();
    } catch {
      toast.error('Failed to delete API key');
    }
  };

  return (
    <div className="bg-[var(--surface-hover)] border border-[var(--border)] rounded-[var(--radius)] p-3 flex items-center justify-between">
      <div className="flex items-center gap-3 min-w-0">
        <span className="w-1.5 h-1.5 rounded-full bg-[var(--status-success)] flex-shrink-0" />
        <div className="min-w-0">
          <div className="text-xs font-medium text-[var(--text)] capitalize">{apiKey.provider}</div>
          {apiKey.key_name && (
            <div className="text-[11px] text-[var(--text-muted)]">{apiKey.key_name}</div>
          )}
          <div className="text-[10px] text-[var(--text-subtle)] font-mono mt-0.5">
            {apiKey.key_preview}
          </div>
        </div>
      </div>

      <button onClick={() => setShowDelete(true)} className="btn btn-icon btn-sm btn-danger">
        <Trash size={12} />
      </button>

      {showDelete && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-[var(--surface)] border border-[var(--border)] rounded-[var(--radius)] p-5 max-w-sm">
            <h3 className="text-xs font-semibold text-[var(--text)] mb-2">Delete API Key?</h3>
            <p className="text-xs text-[var(--text-muted)] mb-4">
              Delete this {apiKey.provider} key? This cannot be undone.
            </p>
            <div className="flex items-center gap-2 justify-end">
              <button onClick={() => setShowDelete(false)} className="btn">Cancel</button>
              <button onClick={handleDelete} className="btn btn-danger">Delete</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── AddApiKeyModal ─────────────────────────────────────────────────

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

  const selectedCustomProvider = customProviders.find((p) => p.slug === provider);
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
      toast.success('API key added');
      onSuccess();
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to add API key');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded-[var(--radius)] max-w-md w-full p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xs font-semibold text-[var(--text)]">Add API Key</h2>
          <button onClick={onClose} className="btn btn-icon btn-sm"><X size={14} /></button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="block text-[11px] font-medium text-[var(--text-muted)] mb-1">Provider</label>
            <select
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] rounded-[var(--radius-small)] text-xs text-[var(--text)] focus:outline-none focus:border-[var(--border-hover)]"
              required
            >
              <option value="">Select a provider...</option>
              <optgroup label="Built-in Providers">
                {providers.filter((p) => p.requires_key).map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </optgroup>
              {customProviders.length > 0 && (
                <optgroup label="Custom Providers">
                  {customProviders.map((p) => (
                    <option key={p.slug} value={p.slug}>{p.name}</option>
                  ))}
                </optgroup>
              )}
            </select>
          </div>

          <div>
            <label className="block text-[11px] font-medium text-[var(--text-muted)] mb-1">API Key</label>
            <div className="relative">
              <input
                type={showKey ? 'text' : 'password'}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                className="w-full px-2 py-1.5 pr-8 bg-[var(--bg)] border border-[var(--border)] rounded-[var(--radius-small)] text-xs text-[var(--text)] font-mono focus:outline-none focus:border-[var(--border-hover)]"
                placeholder="sk-..."
                required
              />
              <button
                type="button"
                onClick={() => setShowKey(!showKey)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-subtle)] hover:text-[var(--text-muted)]"
              >
                {showKey ? <EyeSlash size={14} /> : <Eye size={14} />}
              </button>
            </div>
          </div>

          <div>
            <label className="block text-[11px] font-medium text-[var(--text-muted)] mb-1">Name (optional)</label>
            <input
              type="text"
              value={keyName}
              onChange={(e) => setKeyName(e.target.value)}
              className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] rounded-[var(--radius-small)] text-xs text-[var(--text)] focus:outline-none focus:border-[var(--border-hover)]"
              placeholder="My API Key"
            />
          </div>

          {isCustomProvider && (
            <div>
              <label className="block text-[11px] font-medium text-[var(--text-muted)] mb-1">Base URL (optional)</label>
              <input
                type="url"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                className="w-full px-2 py-1.5 bg-[var(--bg)] border border-[var(--border)] rounded-[var(--radius-small)] text-xs text-[var(--text)] font-mono focus:outline-none focus:border-[var(--border-hover)]"
                placeholder={selectedCustomProvider?.base_url || 'https://api.example.com/v1'}
              />
            </div>
          )}

          <div className="flex items-center gap-2 justify-end pt-3 border-t border-[var(--border)]">
            <button type="button" onClick={onClose} disabled={loading} className="btn">Cancel</button>
            <button type="submit" disabled={loading} className="btn btn-filled">
              {loading ? 'Adding...' : <><Plus size={14} /> Add Key</>}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ─── Main ModelsPage ────────────────────────────────────────────────

export default function ModelsPage({
  models,
  apiKeys,
  providers,
  customProviders,
  byokEnabled,
  onToggleModel,
  onReload,
  onReloadProviders,
  onReloadModels,
}: {
  models: ModelInfo[];
  apiKeys: ApiKey[];
  providers: Provider[];
  customProviders: CustomProvider[];
  byokEnabled: boolean | null;
  onToggleModel: (modelId: string, enable: boolean) => void;
  onReload: () => void;
  onReloadProviders: () => void;
  onReloadModels: () => void;
}) {
  const navigate = useNavigate();
  const [showAddModal, setShowAddModal] = useState(false);
  const [showProviderModal, setShowProviderModal] = useState(false);
  const [editingProvider, setEditingProvider] = useState<CustomProvider | null>(null);
  const [modelSearch, setModelSearch] = useState('');
  const [showSearch, setShowSearch] = useState(false);
  const [addingModelProvider, setAddingModelProvider] = useState<string | null>(null);
  const [newModelId, setNewModelId] = useState('');
  const [addingModelLoading, setAddingModelLoading] = useState(false);
  const [subTab, setSubTab] = useState<'models' | 'keys' | 'providers'>('models');
  const searchInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { if (showSearch) searchInputRef.current?.focus(); }, [showSearch]);

  const handleAddModel = async (provider: string) => {
    if (!newModelId.trim()) return;
    setAddingModelLoading(true);
    try {
      await marketplaceApi.addCustomModel({ model_id: newModelId.trim(), model_name: newModelId.trim(), provider });
      toast.success('Model added');
      setNewModelId('');
      setAddingModelProvider(null);
      onReloadModels();
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { detail?: string } } };
      toast.error(axiosErr.response?.data?.detail || 'Failed to add model');
    } finally {
      setAddingModelLoading(false);
    }
  };

  const handleDeleteModel = async (customId: string) => {
    try { await marketplaceApi.deleteCustomModel(customId); toast.success('Model removed'); onReloadModels(); }
    catch { toast.error('Failed to remove model'); }
  };

  const handleDeleteProvider = async (providerId: string) => {
    try { await secretsApi.deleteCustomProvider(providerId); toast.success('Provider deleted'); onReloadProviders(); }
    catch { toast.error('Failed to delete provider'); }
  };

  // Filter + group models
  const filteredModels = models.filter((m) =>
    !modelSearch || m.name.toLowerCase().includes(modelSearch.toLowerCase()) || m.id.toLowerCase().includes(modelSearch.toLowerCase())
  );
  const systemModels = filteredModels.filter((m) => m.source === 'system');
  const providerModels = filteredModels.filter((m) => m.source === 'provider');
  const customModels = filteredModels.filter((m) => m.source === 'custom');

  const providerGroups: Record<string, { label: string; models: ModelInfo[] }> = {};
  for (const m of providerModels) {
    if (!providerGroups[m.provider]) providerGroups[m.provider] = { label: getProviderLabel(m.provider, m.provider_name), models: [] };
    providerGroups[m.provider].models.push(m);
  }
  for (const k of apiKeys) {
    if (!providerGroups[k.provider] && k.provider !== 'internal') providerGroups[k.provider] = { label: getProviderLabel(k.provider), models: [] };
  }

  if (byokEnabled === null) return <div className="flex-1 flex items-center justify-center"><LoadingSpinner /></div>;

  return (
    <div className="flex-1 overflow-hidden flex flex-col">
      {/* Toolbar */}
      <div className="h-10 flex items-center justify-between flex-shrink-0" style={{ paddingLeft: '7px', paddingRight: '10px' }}>
        <div className="flex items-center gap-1 flex-1 min-w-0 overflow-x-auto scrollbar-none" style={{ maskImage: 'linear-gradient(to right, black calc(100% - 24px), transparent)', WebkitMaskImage: 'linear-gradient(to right, black calc(100% - 24px), transparent)' }}>
          <button onClick={() => setSubTab('models')} className={`btn shrink-0 ${subTab === 'models' ? 'btn-tab-active' : 'btn-tab'}`}>
            Models <span className="text-[10px] opacity-50 ml-0.5">{models.length}</span>
          </button>
          <button onClick={() => setSubTab('keys')} className={`btn shrink-0 ${subTab === 'keys' ? 'btn-tab-active' : 'btn-tab'}`}>
            API Keys <span className="text-[10px] opacity-50 ml-0.5">{apiKeys.length}</span>
          </button>
          {byokEnabled !== false && (
            <button onClick={() => setSubTab('providers')} className={`btn shrink-0 ${subTab === 'providers' ? 'btn-tab-active' : 'btn-tab'}`}>
              Providers <span className="text-[10px] opacity-50 ml-0.5">{customProviders.length + providers.length}</span>
            </button>
          )}
        </div>

        <div className="flex items-center gap-[2px]">
          {subTab === 'models' && (
            showSearch ? (
              <div className="flex items-center gap-1.5 bg-[var(--surface)] border border-[var(--border)] rounded-full px-2.5 h-[29px]">
                <MagnifyingGlass size={16} className="text-[var(--text-subtle)]" />
                <input ref={searchInputRef} type="text" value={modelSearch} onChange={(e) => setModelSearch(e.target.value)} onKeyDown={(e) => { if (e.key === 'Escape') { setModelSearch(''); setShowSearch(false); } }} placeholder="Search..." className="bg-transparent border-none outline-none text-xs w-24 sm:w-32 text-[var(--text)]" />
                <button type="button" onClick={() => { setModelSearch(''); setShowSearch(false); }}><X size={12} className="text-[var(--text-subtle)]" /></button>
              </div>
            ) : (
              <button onClick={() => setShowSearch(true)} className={`btn btn-icon ${modelSearch ? 'btn-active' : ''}`}><MagnifyingGlass size={16} /></button>
            )
          )}
          {subTab === 'keys' && byokEnabled !== false && (
            <button onClick={() => setShowAddModal(true)} className="btn btn-filled"><Plus size={14} /> Add Key</button>
          )}
          {subTab === 'providers' && byokEnabled !== false && (
            <button onClick={() => { setEditingProvider(null); setShowProviderModal(true); }} className="btn"><Plus size={14} /> Add Provider</button>
          )}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-5 py-4">
        {/* Models */}
        {subTab === 'models' && (
          models.length === 0 ? (
            <div className="text-center py-12">
              <Cpu size={28} className="mx-auto mb-3 text-[var(--text-subtle)]" />
              <p className="text-xs text-[var(--text-muted)]">No models available</p>
            </div>
          ) : (
            <div className="space-y-5">
              {systemModels.length > 0 && (
                <div>
                  <h4 className="text-[10px] font-semibold text-[var(--text-subtle)] uppercase tracking-wider mb-2">Tesslate (System)</h4>
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-2">
                    {systemModels.map((m) => <ModelCard key={m.id} model={m} onToggle={onToggleModel} />)}
                  </div>
                </div>
              )}

              {Object.entries(providerGroups).map(([key, group]) => (
                <div key={key}>
                  <div className="flex items-center justify-between mb-2">
                    <h4 className="text-[10px] font-semibold text-[var(--text-subtle)] uppercase tracking-wider">{group.label}</h4>
                    <button onClick={() => { setAddingModelProvider(addingModelProvider === key ? null : key); setNewModelId(''); }} className="btn btn-sm"><Plus size={12} /> Add Model</button>
                  </div>
                  {addingModelProvider === key && (
                    <div className="flex items-center gap-2 mb-3">
                      <input value={newModelId} onChange={(e) => setNewModelId(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') handleAddModel(key); if (e.key === 'Escape') { setAddingModelProvider(null); setNewModelId(''); } }} placeholder="e.g. gpt-4o-audio-preview" autoFocus className="flex-1 px-2 py-1 bg-[var(--bg)] border border-[var(--border)] rounded-[var(--radius-small)] text-xs text-[var(--text)] placeholder:text-[var(--text-subtle)] focus:outline-none focus:border-[var(--border-hover)]" />
                      <button onClick={() => handleAddModel(key)} disabled={!newModelId.trim() || addingModelLoading} className="btn btn-filled btn-sm">{addingModelLoading ? '...' : 'Add'}</button>
                      <button onClick={() => { setAddingModelProvider(null); setNewModelId(''); }} className="btn btn-sm">Cancel</button>
                    </div>
                  )}
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-2">
                    {group.models.map((m) => <ModelCard key={m.id} model={m} onToggle={onToggleModel} onDelete={handleDeleteModel} />)}
                  </div>
                </div>
              ))}

              {customModels.length > 0 && (
                <div>
                  <h4 className="text-[10px] font-semibold text-[var(--text-subtle)] uppercase tracking-wider mb-2">Custom Models</h4>
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-2">
                    {customModels.map((m) => <ModelCard key={m.id} model={m} onToggle={onToggleModel} onDelete={handleDeleteModel} />)}
                  </div>
                </div>
              )}

              {filteredModels.length === 0 && modelSearch && (
                <p className="text-xs text-[var(--text-muted)] text-center py-4">No models matching &ldquo;{modelSearch}&rdquo;</p>
              )}
            </div>
          )
        )}

        {/* API Keys */}
        {subTab === 'keys' && (
          byokEnabled === false ? (
            <div className="text-center py-12">
              <LockKey size={28} className="mx-auto mb-3 text-[var(--text-subtle)]" />
              <p className="text-xs font-medium text-[var(--text)] mb-1">Bring Your Own Key</p>
              <p className="text-xs text-[var(--text-muted)] max-w-sm mx-auto mb-4">Use your own API keys for OpenAI, Anthropic, and more. Available on paid plans.</p>
              <button onClick={() => navigate('/settings/billing')} className="btn btn-filled"><Rocket size={14} /> Upgrade Plan</button>
            </div>
          ) : apiKeys.length === 0 ? (
            <div className="text-center py-12">
              <Key size={28} className="mx-auto mb-3 text-[var(--text-subtle)]" />
              <p className="text-xs text-[var(--text-muted)] mb-3">No API keys configured</p>
              <button onClick={() => setShowAddModal(true)} className="btn btn-filled">Add Your First API Key</button>
            </div>
          ) : (
            <div className="space-y-2">
              {apiKeys.map((key) => <ApiKeyCard key={key.id} apiKey={key} onReload={onReload} />)}
            </div>
          )
        )}

        {/* Providers */}
        {subTab === 'providers' && byokEnabled !== false && (
          <div className="space-y-5">
            {customProviders.length > 0 ? (
              <div>
                <h4 className="text-[10px] font-semibold text-[var(--text-subtle)] uppercase tracking-wider mb-2">Custom Providers</h4>
                <div className="space-y-2">
                  {customProviders.map((cp) => (
                    <CustomProviderCard key={cp.id} provider={cp} onEdit={() => { setEditingProvider(cp); setShowProviderModal(true); }} onDelete={handleDeleteProvider} />
                  ))}
                </div>
              </div>
            ) : (
              <div className="text-center py-8">
                <Plugs size={24} className="mx-auto mb-2 text-[var(--text-subtle)]" />
                <p className="text-xs text-[var(--text-muted)] mb-1">No custom providers</p>
                <p className="text-[11px] text-[var(--text-subtle)]">Connect Ollama, vLLM, or any OpenAI-compatible API</p>
              </div>
            )}

            <div>
              <h4 className="text-[10px] font-semibold text-[var(--text-subtle)] uppercase tracking-wider mb-2">Supported Providers</h4>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                {providers.map((p) => {
                  const hasKey = apiKeys.some((k) => k.provider === p.id);
                  return (
                    <div key={p.id} className="bg-[var(--surface-hover)] border border-[var(--border)] rounded-[var(--radius-medium)] p-3">
                      <div className="flex items-center gap-2 mb-1">
                        <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${hasKey ? 'bg-[var(--status-success)]' : 'bg-[var(--text-subtle)]'}`} />
                        <span className="text-xs font-medium text-[var(--text)]">{p.name}</span>
                        {hasKey && <span className="text-[10px] text-[var(--text-subtle)] ml-auto">Connected</span>}
                      </div>
                      <p className="text-[11px] text-[var(--text-muted)]">{p.description}</p>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        )}
      </div>

      {showAddModal && <AddApiKeyModal providers={providers} customProviders={customProviders} onClose={() => setShowAddModal(false)} onSuccess={() => { setShowAddModal(false); onReload(); onReloadModels(); }} />}
      {showProviderModal && <CustomProviderModal existing={editingProvider} onClose={() => { setShowProviderModal(false); setEditingProvider(null); }} onSuccess={() => { setShowProviderModal(false); setEditingProvider(null); onReloadProviders(); onReloadModels(); }} />}
    </div>
  );
}
