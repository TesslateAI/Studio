import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Package,
  Pencil,
  Power,
  Cpu,
  GitFork,
  LockSimpleOpen,
  LockKey,
  Sparkle,
  ArrowLeft,
  Check,
  XCircle,
  Rocket,
  Key,
  ChartLine,
  Plus,
  Trash,
  Eye,
  EyeSlash,
  CurrencyDollar,
  Circle,
  CheckCircle
} from '@phosphor-icons/react';
import { LoadingSpinner } from '../components/PulsingGridSpinner';
import { marketplaceApi, secretsApi } from '../lib/api';
import toast from 'react-hot-toast';

interface LibraryAgent {
  id: number;
  name: string;
  slug: string;
  description: string;
  category: string;
  mode: string;
  agent_type: string;
  model: string;
  selected_model?: string | null;
  source_type: 'open' | 'closed';
  is_forkable: boolean;
  icon: string;
  pricing_type: string;
  features: string[];
  purchase_date: string;
  purchase_type: string;
  expires_at: string | null;
  is_custom: boolean;
  parent_agent_id: number | null;
  system_prompt?: string;
  is_enabled?: boolean;
  is_published?: boolean;
  usage_count?: number;
}

interface Model {
  id: string;
  name: string;
  source: string;
  provider: string;
  pricing: {
    input: number;
    output: number;
  };
  available: boolean;
  custom_id?: number;
}

interface ExternalProvider {
  provider: string;
  name: string;
  description: string;
  has_key: boolean;
  setup_required: boolean;
  models_count: string;
}

interface ApiKey {
  id: number;
  provider: string;
  auth_type: string;
  key_name: string | null;
  key_preview: string;
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
}

type TabType = 'agents' | 'models' | 'api-keys';

export default function Library() {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<TabType>('agents');
  const [agents, setAgents] = useState<LibraryAgent[]>([]);
  const [models, setModels] = useState<Model[]>([]);
  const [externalProviders, setExternalProviders] = useState<ExternalProvider[]>([]);
  const [apiKeys, setApiKeys] = useState<ApiKey[]>([]);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(true);
  const [editingAgent, setEditingAgent] = useState<LibraryAgent | null>(null);

  useEffect(() => {
    loadData();
  }, [activeTab]);

  const loadData = async () => {
    setLoading(true);
    try {
      if (activeTab === 'agents') {
        await loadLibraryAgents();
      } else if (activeTab === 'models') {
        await loadModels();
      } else if (activeTab === 'api-keys') {
        await loadApiKeys();
        await loadProviders();
      }
    } finally {
      setLoading(false);
    }
  };

  const loadLibraryAgents = async () => {
    try {
      const data = await marketplaceApi.getMyAgents();
      setAgents(data.agents || []);
    } catch (error) {
      console.error('Failed to load library:', error);
      toast.error('Failed to load library');
    }
  };

  const loadModels = async () => {
    try {
      const data = await marketplaceApi.getAvailableModels();
      setModels(data.models || []);
      setExternalProviders(data.external_providers || []);
    } catch (error) {
      console.error('Failed to load models:', error);
      toast.error('Failed to load models');
    }
  };

  const loadApiKeys = async () => {
    try {
      const data = await secretsApi.listApiKeys();
      setApiKeys(data.api_keys || []);
    } catch (error) {
      console.error('Failed to load API keys:', error);
      toast.error('Failed to load API keys');
    }
  };

  const loadProviders = async () => {
    try {
      const data = await secretsApi.getProviders();
      setProviders(data.providers || []);
    } catch (error) {
      console.error('Failed to load providers:', error);
    }
  };

  const handleToggleEnable = async (agent: LibraryAgent) => {
    try {
      const newState = !agent.is_enabled;
      await marketplaceApi.toggleAgent(agent.id, newState);
      toast.success(`Agent ${newState ? 'enabled' : 'disabled'}`);
      loadLibraryAgents();
    } catch (error) {
      console.error('Toggle failed:', error);
      toast.error('Failed to toggle agent');
    }
  };

  const handleTogglePublish = async (agent: LibraryAgent) => {
    try {
      if (agent.is_published) {
        await marketplaceApi.unpublishAgent(agent.id);
        toast.success('Agent unpublished from marketplace');
      } else {
        await marketplaceApi.publishAgent(agent.id);
        toast.success('Agent published to community marketplace! 🎉');
      }
      loadLibraryAgents();
    } catch (error: any) {
      console.error('Publish toggle failed:', error);
      toast.error(error.response?.data?.detail || 'Failed to toggle publish status');
    }
  };

  const handleModelChange = async (agent: LibraryAgent, model: string) => {
    try {
      await marketplaceApi.selectAgentModel(agent.id, model);
      toast.success('Model updated successfully');
      loadLibraryAgents();
    } catch (error: any) {
      console.error('Model change failed:', error);
      toast.error(error.response?.data?.detail || 'Failed to change model');
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-[var(--background)] flex items-center justify-center">
        <LoadingSpinner message="Loading..." size={80} />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[var(--background)]">
      {/* Header */}
      <div className="border-b border-white/10 bg-[var(--surface)]">
        <div className="max-w-7xl mx-auto px-6 py-8">
          <div className="flex items-center justify-between mb-6">
            <div>
              <h1 className="text-3xl font-bold text-[var(--text)] mb-2">My Library</h1>
              <p className="text-[var(--text)]/60">Manage agents, models, and API keys</p>
            </div>
            <div className="flex items-center gap-3">
              <button
                onClick={() => navigate('/marketplace')}
                className="px-4 py-2 bg-orange-500 hover:bg-orange-600 rounded-lg text-white transition-colors flex items-center gap-2"
              >
                <Sparkle size={18} />
                Browse Marketplace
              </button>
              <button
                onClick={() => navigate('/dashboard')}
                className="px-4 py-2 bg-white/5 hover:bg-white/10 rounded-lg text-[var(--text)]/80 transition-colors flex items-center gap-2"
              >
                <ArrowLeft size={18} />
                Back to Dashboard
              </button>
            </div>
          </div>

          {/* Tabs */}
          <div className="flex items-center gap-2 border-b border-white/10">
            <button
              onClick={() => setActiveTab('agents')}
              className={`px-4 py-3 font-medium transition-colors border-b-2 flex items-center gap-2 ${
                activeTab === 'agents'
                  ? 'border-orange-500 text-orange-400'
                  : 'border-transparent text-[var(--text)]/60 hover:text-[var(--text)]/80'
              }`}
            >
              <Package size={18} />
              Agents ({agents.length})
            </button>
            <button
              onClick={() => setActiveTab('models')}
              className={`px-4 py-3 font-medium transition-colors border-b-2 flex items-center gap-2 ${
                activeTab === 'models'
                  ? 'border-orange-500 text-orange-400'
                  : 'border-transparent text-[var(--text)]/60 hover:text-[var(--text)]/80'
              }`}
            >
              <Cpu size={18} />
              Model Management
            </button>
            <button
              onClick={() => setActiveTab('api-keys')}
              className={`px-4 py-3 font-medium transition-colors border-b-2 flex items-center gap-2 ${
                activeTab === 'api-keys'
                  ? 'border-orange-500 text-orange-400'
                  : 'border-transparent text-[var(--text)]/60 hover:text-[var(--text)]/80'
              }`}
            >
              <Key size={18} />
              API Keys ({apiKeys.length})
            </button>
          </div>
        </div>
      </div>

      {/* Tab Content */}
      <div className="max-w-7xl mx-auto px-6 py-8">
        {activeTab === 'agents' && (
          <AgentsTab
            agents={agents}
            models={models}
            onToggleEnable={handleToggleEnable}
            onEdit={setEditingAgent}
            onTogglePublish={handleTogglePublish}
            onModelChange={handleModelChange}
            onReload={loadLibraryAgents}
          />
        )}

        {activeTab === 'models' && (
          <ModelsTab
            models={models}
            externalProviders={externalProviders}
            onSetupProvider={(provider) => setActiveTab('api-keys')}
          />
        )}

        {activeTab === 'api-keys' && (
          <ApiKeysTab
            apiKeys={apiKeys}
            providers={providers}
            onReload={loadApiKeys}
          />
        )}
      </div>

      {/* Edit Agent Modal */}
      {editingAgent && (
        <EditAgentModal
          agent={editingAgent}
          availableModels={models.map(m => m.id)}
          onClose={() => setEditingAgent(null)}
          onSave={async (updatedData) => {
            try {
              const response = await marketplaceApi.updateAgent(editingAgent.id, updatedData);
              if (response.forked) {
                toast.success('Created a custom fork with your changes!');
              } else {
                toast.success('Agent updated successfully');
              }
              setEditingAgent(null);
              loadLibraryAgents();
            } catch (error: any) {
              console.error('Update failed:', error);
              toast.error(error.response?.data?.detail || 'Failed to update agent');
            }
          }}
        />
      )}
    </div>
  );
}

// Agents Tab Component
function AgentsTab({
  agents,
  models,
  onToggleEnable,
  onEdit,
  onTogglePublish,
  onModelChange,
  onReload
}: {
  agents: LibraryAgent[];
  models: Model[];
  onToggleEnable: (agent: LibraryAgent) => void;
  onEdit: (agent: LibraryAgent) => void;
  onTogglePublish: (agent: LibraryAgent) => void;
  onModelChange: (agent: LibraryAgent, model: string) => void;
  onReload: () => void;
}) {
  const navigate = useNavigate();

  if (agents.length === 0) {
    return (
      <div className="text-center py-16">
        <Package size={48} className="mx-auto mb-4 text-[var(--text)]/20" />
        <p className="text-[var(--text)]/60 mb-4">Your library is empty</p>
        <button
          onClick={() => navigate('/marketplace')}
          className="px-6 py-3 bg-orange-500 hover:bg-orange-600 rounded-lg text-white transition-colors"
        >
          Browse Marketplace
        </button>
      </div>
    );
  }

  return (
    <>
      {/* Stats */}
      <div className="grid grid-cols-3 gap-4 mb-6">
        <div className="p-4 bg-white/5 border border-white/10 rounded-lg">
          <div className="text-2xl font-bold text-[var(--text)] mb-1">{agents.length}</div>
          <div className="text-sm text-[var(--text)]/60">Total Agents</div>
        </div>
        <div className="p-4 bg-white/5 border border-white/10 rounded-lg">
          <div className="text-2xl font-bold text-green-400 mb-1">
            {agents.filter(a => a.is_enabled).length}
          </div>
          <div className="text-sm text-[var(--text)]/60">Enabled</div>
        </div>
        <div className="p-4 bg-white/5 border border-white/10 rounded-lg">
          <div className="text-2xl font-bold text-orange-400 mb-1">
            {agents.filter(a => a.is_custom).length}
          </div>
          <div className="text-sm text-[var(--text)]/60">Custom Agents</div>
        </div>
      </div>

      {/* Agents Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {agents.map(agent => (
          <AgentCard
            key={agent.id}
            agent={agent}
            availableModels={models.map(m => m.id)}
            onToggleEnable={() => onToggleEnable(agent)}
            onEdit={() => onEdit(agent)}
            onTogglePublish={() => onTogglePublish(agent)}
            onModelChange={(model) => onModelChange(agent, model)}
          />
        ))}
      </div>
    </>
  );
}

// Models Tab Component
function ModelsTab({
  models,
  externalProviders,
  onSetupProvider
}: {
  models: Model[];
  externalProviders: ExternalProvider[];
  onSetupProvider: (provider: string) => void;
}) {
  const [showAddCustomModel, setShowAddCustomModel] = useState(false);
  const [customModels, setCustomModels] = useState<Model[]>([]);
  const [systemModels, setSystemModels] = useState<Model[]>([]);

  useEffect(() => {
    // Separate custom and system models
    setCustomModels(models.filter(m => m.source === 'custom'));
    setSystemModels(models.filter(m => m.source !== 'custom'));
  }, [models]);

  const handleDeleteCustomModel = async (modelId: number) => {
    try {
      await marketplaceApi.deleteCustomModel(modelId);
      toast.success('Custom model deleted');
      // Reload models
      window.location.reload();
    } catch (error) {
      console.error('Delete custom model failed:', error);
      toast.error('Failed to delete custom model');
    }
  };

  return (
    <div className="space-y-8">
      {/* Custom Models */}
      {customModels.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-2xl font-bold text-[var(--text)] mb-1">Your Custom Models</h2>
              <p className="text-[var(--text)]/60">OpenRouter models you've added</p>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {customModels.map((model) => (
              <div
                key={model.id}
                className="bg-[var(--surface)] border border-orange-500/20 rounded-lg p-4 hover:border-orange-500/40 transition-all"
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center gap-3 flex-1">
                    <div className="p-2 bg-orange-500/10 rounded-lg">
                      <Cpu size={24} className="text-orange-400" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <h3 className="font-semibold text-[var(--text)] truncate">{model.name}</h3>
                        <span className="px-2 py-0.5 bg-orange-500/20 text-orange-400 text-xs rounded shrink-0">
                          Custom
                        </span>
                      </div>
                      <div className="flex items-center gap-2 mt-1">
                        <span className="text-xs text-[var(--text)]/40 capitalize">{model.provider}</span>
                      </div>
                    </div>
                  </div>
                  <button
                    onClick={() => model.custom_id && handleDeleteCustomModel(model.custom_id)}
                    className="p-2 hover:bg-red-500/10 rounded-lg text-red-400 transition-colors shrink-0"
                  >
                    <Trash size={18} />
                  </button>
                </div>

                {/* Pricing */}
                <div className="grid grid-cols-2 gap-3 pt-3 border-t border-white/10">
                  <div className="flex items-center gap-2">
                    <div className="text-xs text-[var(--text)]/60">Input:</div>
                    <div className="text-sm font-semibold text-[var(--text)]">
                      ${model.pricing.input.toFixed(2)}/1M
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="text-xs text-[var(--text)]/60">Output:</div>
                    <div className="text-sm font-semibold text-[var(--text)]">
                      ${model.pricing.output.toFixed(2)}/1M
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Available Models */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-2xl font-bold text-[var(--text)] mb-1">Available Models</h2>
            <p className="text-[var(--text)]/60">Models you can use right now</p>
          </div>
          <div className="text-sm text-[var(--text)]/40">
            {systemModels.length} models available
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {systemModels.map((model) => (
            <div
              key={model.id}
              className="bg-[var(--surface)] border border-white/10 rounded-lg p-4 hover:border-orange-500/30 transition-all"
            >
              <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-3">
                  <div className="p-2 bg-blue-500/10 rounded-lg">
                    <Cpu size={24} className="text-blue-400" />
                  </div>
                  <div>
                    <h3 className="font-semibold text-[var(--text)]">{model.name}</h3>
                    <div className="flex items-center gap-2 mt-1">
                      <span className="text-xs text-[var(--text)]/40 capitalize">{model.provider}</span>
                      {model.pricing.input === 0 && model.pricing.output === 0 && (
                        <span className="px-2 py-0.5 bg-green-500/20 text-green-400 text-xs rounded">
                          Free
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </div>

              {/* Pricing */}
              <div className="grid grid-cols-2 gap-3 mt-3 pt-3 border-t border-white/10">
                <div className="flex items-center gap-2">
                  <div className="text-xs text-[var(--text)]/60">Input:</div>
                  <div className="text-sm font-semibold text-[var(--text)]">
                    ${model.pricing.input.toFixed(2)}/1M
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <div className="text-xs text-[var(--text)]/60">Output:</div>
                  <div className="text-sm font-semibold text-[var(--text)]">
                    ${model.pricing.output.toFixed(2)}/1M
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* External Providers */}
      {externalProviders.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-2xl font-bold text-[var(--text)] mb-1">External Providers</h2>
              <p className="text-[var(--text)]/60">Add API keys to unlock more models</p>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {externalProviders.map((provider) => (
              <div
                key={provider.provider}
                className="bg-[var(--surface)] border border-white/10 rounded-lg p-4"
              >
                <div className="flex items-start justify-between mb-3">
                  <div>
                    <h3 className="font-semibold text-[var(--text)] mb-1">{provider.name}</h3>
                    <p className="text-xs text-[var(--text)]/60 mb-2">{provider.description}</p>
                    <div className="text-xs text-orange-400">{provider.models_count} models</div>
                  </div>
                  {provider.has_key ? (
                    <CheckCircle size={20} className="text-green-400" weight="fill" />
                  ) : (
                    <Circle size={20} className="text-[var(--text)]/20" />
                  )}
                </div>

                {provider.setup_required && (
                  <button
                    onClick={() => onSetupProvider(provider.provider)}
                    className="w-full mt-3 px-4 py-2 bg-orange-500/10 hover:bg-orange-500/20 border border-orange-500/20 text-orange-400 rounded-lg transition-colors flex items-center justify-center gap-2"
                  >
                    <Key size={16} />
                    Add API Key
                  </button>
                )}

                {provider.has_key && (
                  <>
                    <div className="mt-3 px-3 py-2 bg-green-500/10 border border-green-500/20 rounded-lg flex items-center justify-center gap-2">
                      <CheckCircle size={16} className="text-green-400" weight="fill" />
                      <span className="text-xs text-green-400">Configured</span>
                    </div>
                    {provider.provider === 'openrouter' && (
                      <button
                        onClick={() => setShowAddCustomModel(true)}
                        className="w-full mt-2 px-4 py-2 bg-blue-500/10 hover:bg-blue-500/20 border border-blue-500/20 text-blue-400 rounded-lg transition-colors flex items-center justify-center gap-2"
                      >
                        <Plus size={16} />
                        Add Custom Model
                      </button>
                    )}
                  </>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Add Custom Model Modal */}
      {showAddCustomModel && (
        <AddCustomModelModal
          onClose={() => setShowAddCustomModel(false)}
          onSuccess={() => {
            setShowAddCustomModel(false);
            toast.success('Custom model added successfully');
            window.location.reload();
          }}
        />
      )}
    </div>
  );
}

// API Keys Tab Component
function ApiKeysTab({
  apiKeys,
  providers,
  onReload
}: {
  apiKeys: ApiKey[];
  providers: Provider[];
  onReload: () => void;
}) {
  const [showAddModal, setShowAddModal] = useState(false);

  return (
    <div className="space-y-6">
      {/* Header with Add Button */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-[var(--text)] mb-1">API Keys</h2>
          <p className="text-[var(--text)]/60">Manage your provider API keys</p>
        </div>
        <button
          onClick={() => setShowAddModal(true)}
          className="px-4 py-2 bg-orange-500 hover:bg-orange-600 rounded-lg text-white transition-colors flex items-center gap-2"
        >
          <Plus size={18} />
          Add API Key
        </button>
      </div>

      {/* API Keys List */}
      {apiKeys.length === 0 ? (
        <div className="text-center py-16 bg-[var(--surface)] border border-white/10 rounded-lg">
          <Key size={48} className="mx-auto mb-4 text-[var(--text)]/20" />
          <p className="text-[var(--text)]/60 mb-4">No API keys configured</p>
          <button
            onClick={() => setShowAddModal(true)}
            className="px-6 py-3 bg-orange-500 hover:bg-orange-600 rounded-lg text-white transition-colors"
          >
            Add Your First API Key
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {apiKeys.map((key) => (
            <ApiKeyCard key={key.id} apiKey={key} onReload={onReload} />
          ))}
        </div>
      )}

      {/* Supported Providers Info */}
      <div className="mt-8">
        <h3 className="text-lg font-semibold text-[var(--text)] mb-4">Supported Providers</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {providers.map((provider) => (
            <div
              key={provider.id}
              className="bg-[var(--surface)] border border-white/10 rounded-lg p-4"
            >
              <h4 className="font-semibold text-[var(--text)] mb-1">{provider.name}</h4>
              <p className="text-xs text-[var(--text)]/60 mb-2">{provider.description}</p>
              <div className="flex items-center gap-2 text-xs text-[var(--text)]/40">
                <span className="capitalize">{provider.auth_type.replace('_', ' ')}</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Add API Key Modal */}
      {showAddModal && (
        <AddApiKeyModal
          providers={providers}
          onClose={() => setShowAddModal(false)}
          onSuccess={() => {
            setShowAddModal(false);
            onReload();
          }}
        />
      )}
    </div>
  );
}

// API Key Card Component
function ApiKeyCard({ apiKey, onReload }: { apiKey: ApiKey; onReload: () => void }) {
  const [showDelete, setShowDelete] = useState(false);

  const handleDelete = async () => {
    try {
      await secretsApi.deleteApiKey(apiKey.id);
      toast.success('API key deleted');
      onReload();
    } catch (error) {
      console.error('Delete failed:', error);
      toast.error('Failed to delete API key');
    }
  };

  return (
    <div className="bg-[var(--surface)] border border-white/10 rounded-lg p-4 flex items-center justify-between">
      <div className="flex items-center gap-4">
        <div className="p-3 bg-purple-500/10 rounded-lg">
          <Key size={20} className="text-purple-400" />
        </div>
        <div>
          <div className="font-semibold text-[var(--text)] capitalize">{apiKey.provider}</div>
          {apiKey.key_name && (
            <div className="text-sm text-[var(--text)]/60">{apiKey.key_name}</div>
          )}
          <div className="text-xs text-[var(--text)]/40 font-mono mt-1">{apiKey.key_preview}</div>
          <div className="text-xs text-[var(--text)]/40 mt-1">
            Added {new Date(apiKey.created_at).toLocaleDateString()}
          </div>
        </div>
      </div>

      <button
        onClick={() => setShowDelete(true)}
        className="p-2 hover:bg-red-500/10 rounded-lg text-red-400 transition-colors"
      >
        <Trash size={18} />
      </button>

      {/* Delete Confirmation */}
      {showDelete && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50">
          <div className="bg-[var(--surface)] border border-white/10 rounded-lg p-6 max-w-md">
            <h3 className="text-lg font-semibold text-[var(--text)] mb-4">Delete API Key?</h3>
            <p className="text-[var(--text)]/60 mb-6">
              Are you sure you want to delete this {apiKey.provider} API key? This action cannot be undone.
            </p>
            <div className="flex items-center gap-3 justify-end">
              <button
                onClick={() => setShowDelete(false)}
                className="px-4 py-2 bg-white/5 hover:bg-white/10 rounded-lg text-[var(--text)]/80 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleDelete}
                className="px-4 py-2 bg-red-500 hover:bg-red-600 rounded-lg text-white transition-colors"
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// Add API Key Modal Component
function AddApiKeyModal({
  providers,
  onClose,
  onSuccess
}: {
  providers: Provider[];
  onClose: () => void;
  onSuccess: () => void;
}) {
  const [provider, setProvider] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [keyName, setKeyName] = useState('');
  const [showKey, setShowKey] = useState(false);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);

    try {
      await secretsApi.addApiKey({
        provider,
        api_key: apiKey,
        key_name: keyName || undefined,
      });
      toast.success('API key added successfully');
      onSuccess();
    } catch (error: any) {
      console.error('Add API key failed:', error);
      toast.error(error.response?.data?.detail || 'Failed to add API key');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-[var(--surface)] border border-white/10 rounded-xl max-w-md w-full p-6">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-2xl font-bold text-[var(--text)]">Add API Key</h2>
          <button
            onClick={onClose}
            className="p-2 hover:bg-white/5 rounded-lg transition-colors text-[var(--text)]/60"
          >
            ✕
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-[var(--text)] mb-2">
              Provider
            </label>
            <select
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-[var(--text)] focus:outline-none focus:border-orange-500/50"
              required
            >
              <option value="">Select a provider...</option>
              {providers.filter(p => p.requires_key).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-[var(--text)] mb-2">
              API Key
            </label>
            <div className="relative">
              <input
                type={showKey ? 'text' : 'password'}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                className="w-full px-4 py-2 pr-12 bg-white/5 border border-white/10 rounded-lg text-[var(--text)] focus:outline-none focus:border-orange-500/50 font-mono text-sm"
                placeholder="sk-..."
                required
              />
              <button
                type="button"
                onClick={() => setShowKey(!showKey)}
                className="absolute right-3 top-1/2 -translate-y-1/2 p-1 hover:bg-white/5 rounded transition-colors text-[var(--text)]/60"
              >
                {showKey ? <EyeSlash size={18} /> : <Eye size={18} />}
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
              className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-[var(--text)] focus:outline-none focus:border-orange-500/50"
              placeholder="My API Key"
            />
            <p className="mt-1 text-xs text-[var(--text)]/40">
              Useful if you have multiple keys for the same provider
            </p>
          </div>

          <div className="flex items-center gap-3 justify-end pt-4 border-t border-white/10">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 bg-white/5 hover:bg-white/10 rounded-lg text-[var(--text)]/80 transition-colors"
              disabled={loading}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-6 py-2 bg-orange-500 hover:bg-orange-600 rounded-lg text-white transition-colors flex items-center gap-2 disabled:opacity-50"
              disabled={loading}
            >
              {loading ? (
                <>Adding...</>
              ) : (
                <>
                  <Plus size={18} />
                  Add Key
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// Agent Card Component (keeping original)
function AgentCard({
  agent,
  availableModels,
  onToggleEnable,
  onEdit,
  onTogglePublish,
  onModelChange
}: {
  agent: LibraryAgent;
  availableModels: string[];
  onToggleEnable: () => void;
  onEdit: () => void;
  onTogglePublish: () => void;
  onModelChange: (model: string) => void;
}) {
  const canEdit = agent.source_type === 'open' || agent.is_custom;
  const canChangeModel = agent.source_type === 'open' || agent.is_custom;
  const currentModel = agent.selected_model || agent.model;

  return (
    <div className="bg-[var(--surface)] border border-white/10 rounded-xl p-6 hover:border-orange-500/30 transition-all">
      {/* Header */}
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="text-3xl">{agent.icon}</div>
          <div>
            <h3 className="font-semibold text-[var(--text)] text-lg">{agent.name}</h3>
            <div className="flex items-center gap-2 mt-1">
              {agent.source_type === 'open' ? (
                <span className="flex items-center gap-1 px-2 py-0.5 bg-green-500/20 text-green-400 text-xs rounded">
                  <LockSimpleOpen size={10} />
                  Open
                </span>
              ) : (
                <span className="flex items-center gap-1 px-2 py-0.5 bg-purple-500/20 text-purple-400 text-xs rounded">
                  <LockKey size={10} />
                  Pro
                </span>
              )}
              {agent.is_custom && (
                <span className="flex items-center gap-1 px-2 py-0.5 bg-orange-500/20 text-orange-400 text-xs rounded">
                  <GitFork size={10} />
                  Custom
                </span>
              )}
              {agent.parent_agent_id && (
                <span className="flex items-center gap-1 px-2 py-0.5 bg-blue-500/20 text-blue-400 text-xs rounded">
                  <GitFork size={10} />
                  Forked
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Enable/Disable Toggle */}
        <button
          onClick={onToggleEnable}
          className={`p-2 rounded-lg transition-colors ${
            agent.is_enabled
              ? 'bg-green-500/20 text-green-400 hover:bg-green-500/30'
              : 'bg-white/5 text-[var(--text)]/40 hover:bg-white/10'
          }`}
          title={agent.is_enabled ? 'Disable agent' : 'Enable agent'}
        >
          {agent.is_enabled ? <Power size={20} weight="fill" /> : <Power size={20} />}
        </button>
      </div>

      {/* Description */}
      <p className="text-[var(--text)]/60 text-sm mb-4 line-clamp-2">{agent.description}</p>

      {/* Model Badge */}
      <div className="mb-4">
        <div className="flex items-center gap-2 px-3 py-1.5 bg-blue-500/10 border border-blue-500/20 rounded-lg w-fit">
          <Cpu size={14} className="text-blue-400" />
          <span className="text-xs text-blue-400 font-medium">{currentModel}</span>
        </div>
      </div>

      {/* Features */}
      <div className="flex flex-wrap gap-2 mb-4">
        {agent.features.slice(0, 3).map((feature, idx) => (
          <span
            key={idx}
            className="px-2 py-1 bg-white/5 text-[var(--text)]/60 text-xs rounded"
          >
            {feature}
          </span>
        ))}
      </div>

      {/* Actions */}
      <div className="flex items-center gap-2 pt-4 border-t border-white/10">
        {canEdit && (
          <button
            onClick={onEdit}
            className="flex-1 py-2 px-3 bg-orange-500/10 hover:bg-orange-500/20 border border-orange-500/20 text-orange-400 rounded-lg transition-colors flex items-center justify-center gap-2"
          >
            <Pencil size={16} />
            Edit
          </button>
        )}
        {agent.is_custom && (
          <button
            onClick={onTogglePublish}
            className={`flex-1 py-2 px-3 rounded-lg transition-colors flex items-center justify-center gap-2 ${
              agent.is_published
                ? 'bg-blue-500/10 hover:bg-blue-500/20 border border-blue-500/20 text-blue-400'
                : 'bg-purple-500/10 hover:bg-purple-500/20 border border-purple-500/20 text-purple-400'
            }`}
          >
            {agent.is_published ? (
              <>
                <Check size={16} />
                Published
              </>
            ) : (
              <>
                <Rocket size={16} />
                Publish
              </>
            )}
          </button>
        )}
        <button
          onClick={onToggleEnable}
          className={`flex-1 py-2 px-3 rounded-lg transition-colors flex items-center justify-center gap-2 ${
            agent.is_enabled
              ? 'bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 text-red-400'
              : 'bg-green-500/10 hover:bg-green-500/20 border border-green-500/20 text-green-400'
          }`}
        >
          {agent.is_enabled ? (
            <>
              <XCircle size={16} />
              Disable
            </>
          ) : (
            <>
              <Power size={16} />
              Enable
            </>
          )}
        </button>
      </div>

      {/* Purchase Date */}
      <div className="mt-4 text-xs text-[var(--text)]/40">
        Added {new Date(agent.purchase_date).toLocaleDateString()}
      </div>
    </div>
  );
}

// Edit Agent Modal Component (keeping original)
function EditAgentModal({
  agent,
  availableModels,
  onClose,
  onSave
}: {
  agent: LibraryAgent;
  availableModels: string[];
  onClose: () => void;
  onSave: (data: { name?: string; description?: string; system_prompt?: string; model?: string }) => void;
}) {
  const [name, setName] = useState(agent.name);
  const [description, setDescription] = useState(agent.description);
  const [systemPrompt, setSystemPrompt] = useState(agent.system_prompt || '');
  const currentModel = agent.selected_model || agent.model;
  const [model, setModel] = useState(currentModel);
  const [originalPrompt] = useState(agent.system_prompt || '');

  const handleReset = () => {
    setSystemPrompt(originalPrompt);
    toast.success('Reset to original system prompt');
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSave({
      name,
      description,
      system_prompt: systemPrompt,
      model
    });
  };

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-[var(--surface)] border border-white/10 rounded-xl max-w-3xl w-full p-6 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-2xl font-bold text-[var(--text)] flex items-center gap-2">
            <Pencil size={24} />
            Edit Agent
          </h2>
          <button
            onClick={onClose}
            className="p-2 hover:bg-white/5 rounded-lg transition-colors text-[var(--text)]/60"
          >
            ✕
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-[var(--text)] mb-2">
              Agent Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-[var(--text)] focus:outline-none focus:border-orange-500/50"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-[var(--text)] mb-2">
              Description
            </label>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-[var(--text)] focus:outline-none focus:border-orange-500/50"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-[var(--text)] mb-2">
              Model
            </label>
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-[var(--text)] focus:outline-none focus:border-orange-500/50"
              disabled={agent.source_type !== 'open' && !agent.is_custom}
            >
              {availableModels.length > 0 ? (
                availableModels.map((modelName) => (
                  <option key={modelName} value={modelName}>
                    {modelName}
                  </option>
                ))
              ) : (
                <option value={model}>{model}</option>
              )}
            </select>
            {agent.source_type !== 'open' && !agent.is_custom && (
              <p className="mt-1 text-xs text-[var(--text)]/40">
                Model can only be changed for open source agents
              </p>
            )}
          </div>

          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="block text-sm font-medium text-[var(--text)]">
                System Prompt
              </label>
              {systemPrompt !== originalPrompt && (
                <button
                  type="button"
                  onClick={handleReset}
                  className="px-3 py-1 bg-blue-500/10 hover:bg-blue-500/20 border border-blue-500/20 text-blue-400 text-xs rounded transition-colors"
                >
                  Reset to Default
                </button>
              )}
            </div>
            <textarea
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              rows={10}
              className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-[var(--text)] focus:outline-none focus:border-orange-500/50 font-mono text-sm resize-y"
              required
            />
            <p className="mt-1 text-xs text-[var(--text)]/40">
              {systemPrompt.length} characters
            </p>
          </div>

          <div className="flex items-center gap-3 justify-end pt-4 border-t border-white/10">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 bg-white/5 hover:bg-white/10 rounded-lg text-[var(--text)]/80 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-6 py-2 bg-orange-500 hover:bg-orange-600 rounded-lg text-white transition-colors flex items-center gap-2"
            >
              <Check size={18} />
              Save Changes
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// Add Custom Model Modal Component
function AddCustomModelModal({
  onClose,
  onSuccess
}: {
  onClose: () => void;
  onSuccess: () => void;
}) {
  const [modelId, setModelId] = useState('');
  const [modelName, setModelName] = useState('');
  const [pricingInput, setPricingInput] = useState('');
  const [pricingOutput, setPricingOutput] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);

    try {
      await marketplaceApi.addCustomModel({
        model_id: modelId,
        model_name: modelName,
        pricing_input: pricingInput ? parseFloat(pricingInput) : undefined,
        pricing_output: pricingOutput ? parseFloat(pricingOutput) : undefined
      });
      onSuccess();
    } catch (error: any) {
      console.error('Add custom model failed:', error);
      toast.error(error.response?.data?.detail || 'Failed to add custom model');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-[var(--surface)] border border-white/10 rounded-xl max-w-md w-full p-6">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-2xl font-bold text-[var(--text)] flex items-center gap-2">
            <Plus size={24} />
            Add Custom OpenRouter Model
          </h2>
          <button
            onClick={onClose}
            className="p-2 hover:bg-white/5 rounded-lg transition-colors text-[var(--text)]/60"
          >
            ✕
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-[var(--text)] mb-2">
              Model ID
            </label>
            <input
              type="text"
              value={modelId}
              onChange={(e) => setModelId(e.target.value)}
              className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-[var(--text)] focus:outline-none focus:border-orange-500/50 font-mono text-sm"
              placeholder="openrouter/model-name"
              required
            />
            <p className="mt-1 text-xs text-[var(--text)]/40">
              Find model IDs at openrouter.ai
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-[var(--text)] mb-2">
              Display Name
            </label>
            <input
              type="text"
              value={modelName}
              onChange={(e) => setModelName(e.target.value)}
              className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-[var(--text)] focus:outline-none focus:border-orange-500/50"
              placeholder="My Custom Model"
              required
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-[var(--text)] mb-2">
                Input Price ($/1M tokens)
              </label>
              <input
                type="number"
                step="0.01"
                value={pricingInput}
                onChange={(e) => setPricingInput(e.target.value)}
                className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-[var(--text)] focus:outline-none focus:border-orange-500/50"
                placeholder="0.00"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-[var(--text)] mb-2">
                Output Price ($/1M tokens)
              </label>
              <input
                type="number"
                step="0.01"
                value={pricingOutput}
                onChange={(e) => setPricingOutput(e.target.value)}
                className="w-full px-4 py-2 bg-white/5 border border-white/10 rounded-lg text-[var(--text)] focus:outline-none focus:border-orange-500/50"
                placeholder="0.00"
              />
            </div>
          </div>

          <div className="flex items-center gap-3 justify-end pt-4 border-t border-white/10">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 bg-white/5 hover:bg-white/10 rounded-lg text-[var(--text)]/80 transition-colors"
              disabled={loading}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-6 py-2 bg-orange-500 hover:bg-orange-600 rounded-lg text-white transition-colors flex items-center gap-2 disabled:opacity-50"
              disabled={loading}
            >
              {loading ? (
                <>Adding...</>
              ) : (
                <>
                  <Plus size={18} />
                  Add Model
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
