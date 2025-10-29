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
  CheckCircle,
  File,
  FileText,
  FilePlus,
  Terminal,
  Globe,
  ListChecks,
  Wrench,
  Desktop,
  Microchip,
  ArrowsClockwise,
  X
} from '@phosphor-icons/react';
import { LoadingSpinner } from '../components/PulsingGridSpinner';
import { DiscordSupport } from '../components/DiscordSupport';
import { ConfirmDialog } from '../components/modals';
import { marketplaceApi, secretsApi, usersApi } from '../lib/api';
import toast from 'react-hot-toast';

interface LibraryAgent {
  id: string;
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
  tools?: string[] | null;
  purchase_date: string;
  purchase_type: string;
  expires_at: string | null;
  is_custom: boolean;
  parent_agent_id: string | null;
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
  id: string;
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

// All available tools in the system
const ALL_TOOLS = [
  'read_file',
  'write_file',
  'patch_file',
  'multi_edit',
  'bash_exec',
  'shell_open',
  'shell_exec',
  'shell_close',
  'get_project_info',
  'todo_read',
  'todo_write',
  'web_fetch'
];

// Tool icon mapping helper
const getToolIcon = (toolName: string): { icon: React.ReactNode; label: string } | null => {
  const toolIcons: Record<string, { icon: React.ReactNode; label: string }> = {
    read_file: { icon: <File size={12} weight="fill" />, label: 'Read' },
    write_file: { icon: <FilePlus size={12} weight="fill" />, label: 'Write' },
    patch_file: { icon: <Pencil size={12} weight="fill" />, label: 'Patch' },
    multi_edit: { icon: <FileText size={12} weight="fill" />, label: 'Multi-Edit' },
    bash_exec: { icon: <Terminal size={12} weight="fill" />, label: 'Bash' },
    shell_open: { icon: <Terminal size={12} weight="fill" />, label: 'Shell Open' },
    shell_exec: { icon: <Terminal size={12} weight="fill" />, label: 'Shell' },
    shell_close: { icon: <Terminal size={12} weight="fill" />, label: 'Shell Close' },
    get_project_info: { icon: <Package size={12} weight="fill" />, label: 'Project Info' },
    todo_read: { icon: <ListChecks size={12} weight="fill" />, label: 'Todo Read' },
    todo_write: { icon: <ListChecks size={12} weight="fill" />, label: 'Todo Write' },
    web_fetch: { icon: <Globe size={12} weight="fill" />, label: 'Web Fetch' },
  };
  return toolIcons[toolName] || null;
};

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
        await Promise.all([loadLibraryAgents(), loadModels()]); // Load models for agent tab
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
      // Optimistically update the UI
      setAgents(prevAgents =>
        prevAgents.map(a =>
          a.id === agent.id ? { ...a, selected_model: model } : a
        )
      );

      await marketplaceApi.selectAgentModel(agent.id, model);
      toast.success('Model updated successfully');

      // Reload to ensure consistency with backend
      await loadLibraryAgents();
    } catch (error: any) {
      console.error('Model change failed:', error);
      toast.error(error.response?.data?.detail || 'Failed to change model');
      // Revert on error
      await loadLibraryAgents();
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
    <div className="min-h-screen px-4 sm:px-8 md:px-20 lg:px-32 py-6 sm:py-12 md:py-20 lg:py-24">
      {/* Header */}
      <div className="mb-10">
        <div className="flex items-center justify-between mb-8">
          {/* Back Button */}
          <button
            onClick={() => navigate('/dashboard')}
            data-tour="dashboard-link"
            className="flex items-center gap-2 text-[var(--text)]/60 hover:text-[var(--text)] transition-colors"
          >
            <ArrowLeft size={20} weight="bold" />
            <span className="font-medium">Back</span>
          </button>

          {/* Action Buttons */}
          <div className="flex items-center gap-3">
            <button
              onClick={() => navigate('/marketplace')}
              className="px-6 py-2.5 bg-gradient-to-r from-orange-500 to-pink-500 hover:from-orange-600 hover:to-pink-600 rounded-xl text-white font-semibold transition-all flex items-center gap-2 shadow-lg hover:shadow-xl hover:scale-105"
            >
              <Sparkle size={20} weight="fill" />
              Browse Marketplace
            </button>
          </div>
        </div>

        {/* Main Title */}
        <div className="mb-8">
          <h1 className="font-heading text-4xl md:text-5xl font-bold text-[var(--text)] mb-3">
            My Library
          </h1>
          <p className="text-[var(--text)]/60 text-lg">Manage your agents, models, and API keys</p>
        </div>

        {/* Tabs */}
        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={() => setActiveTab('agents')}
            className={`px-5 py-2.5 font-semibold transition-all rounded-xl flex items-center gap-2 ${
              activeTab === 'agents'
                ? 'bg-[var(--primary)] text-white shadow-lg'
                : 'bg-white/5 text-[var(--text)]/60 hover:bg-white/10 hover:text-[var(--text)]'
            }`}
          >
            <Package size={20} weight={activeTab === 'agents' ? 'fill' : 'regular'} />
            Agents ({agents.length})
          </button>
          <button
            onClick={() => setActiveTab('models')}
            className={`px-5 py-2.5 font-semibold transition-all rounded-xl flex items-center gap-2 ${
              activeTab === 'models'
                ? 'bg-[var(--primary)] text-white shadow-lg'
                : 'bg-white/5 text-[var(--text)]/60 hover:bg-white/10 hover:text-[var(--text)]'
            }`}
          >
            <Cpu size={20} weight={activeTab === 'models' ? 'fill' : 'regular'} />
            Model Management
          </button>
          <button
            onClick={() => setActiveTab('api-keys')}
            className={`px-5 py-2.5 font-semibold transition-all rounded-xl flex items-center gap-2 ${
              activeTab === 'api-keys'
                ? 'bg-[var(--primary)] text-white shadow-lg'
                : 'bg-white/5 text-[var(--text)]/60 hover:bg-white/10 hover:text-[var(--text)]'
            }`}
          >
            <Key size={20} weight={activeTab === 'api-keys' ? 'fill' : 'regular'} />
            API Keys ({apiKeys.length})
          </button>
        </div>
      </div>

      {/* Tab Content */}
      <div>
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

      {/* Discord Support */}
      <DiscordSupport />
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
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [agentToDelete, setAgentToDelete] = useState<LibraryAgent | null>(null);

  const handleRemove = (agent: LibraryAgent) => {
    setAgentToDelete(agent);
    setShowDeleteDialog(true);
  };

  const confirmRemoveAgent = async () => {
    if (!agentToDelete) return;

    setShowDeleteDialog(false);
    const removingToast = toast.loading(`Removing ${agentToDelete.name}...`);

    try {
      await marketplaceApi.removeFromLibrary(agentToDelete.id);
      toast.success(`${agentToDelete.name} removed from library`, { id: removingToast });
      onReload();
    } catch (error) {
      console.error('Remove failed:', error);
      toast.error('Failed to remove agent from library', { id: removingToast });
    } finally {
      setAgentToDelete(null);
    }
  };

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
        <div className="p-4 bg-white/5 border border-[var(--text)]/15 rounded-lg">
          <div className="text-2xl font-bold text-[var(--text)] mb-1">{agents.length}</div>
          <div className="text-sm text-[var(--text)]/60">Total Agents</div>
        </div>
        <div className="p-4 bg-white/5 border border-[var(--text)]/15 rounded-lg">
          <div className="text-2xl font-bold text-[var(--text)] mb-1">
            {agents.filter(a => a.is_enabled).length}
          </div>
          <div className="text-sm text-[var(--text)]/60">Active</div>
        </div>
        <div className="p-4 bg-white/5 border border-[var(--text)]/15 rounded-lg">
          <div className="text-2xl font-bold text-[var(--text)] mb-1">
            {agents.filter(a => a.is_custom).length}
          </div>
          <div className="text-sm text-[var(--text)]/60">Custom</div>
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
            onRemove={() => handleRemove(agent)}
          />
        ))}
      </div>

      {/* Delete Confirmation Dialog */}
      <ConfirmDialog
        isOpen={showDeleteDialog}
        onClose={() => {
          setShowDeleteDialog(false);
          setAgentToDelete(null);
        }}
        onConfirm={confirmRemoveAgent}
        title="Remove Agent"
        message={`Remove "${agentToDelete?.name}" from your library? This cannot be undone.`}
        confirmText="Remove"
        cancelText="Cancel"
        variant="danger"
      />
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
  const [addModelProvider, setAddModelProvider] = useState<string>('openrouter');
  const [showAddApiKey, setShowAddApiKey] = useState(false);
  const [customModels, setCustomModels] = useState<Model[]>([]);
  const [systemModels, setSystemModels] = useState<Model[]>([]);
  const [diagramModel, setDiagramModel] = useState<string>('');
  const [loadingPreferences, setLoadingPreferences] = useState(true);
  const [openRouterKeys, setOpenRouterKeys] = useState<ApiKey[]>([]);
  const [loadingKeys, setLoadingKeys] = useState(true);
  const [providers, setProviders] = useState<Provider[]>([]);

  // State for 4 new providers
  const [ollamaConfig, setOllamaConfig] = useState<ApiKey | null>(null);
  const [lmstudioConfig, setLmstudioConfig] = useState<ApiKey | null>(null);
  const [llamacppConfig, setLlamacppConfig] = useState<ApiKey | null>(null);
  const [customConfigs, setCustomConfigs] = useState<ApiKey[]>([]);

  // Modal states for provider configuration
  const [showOllamaConfig, setShowOllamaConfig] = useState(false);
  const [showLMStudioConfig, setShowLMStudioConfig] = useState(false);
  const [showLlamaCppConfig, setShowLlamaCppConfig] = useState(false);
  const [showCustomConfig, setShowCustomConfig] = useState(false);

  // Modal state for fetching models
  const [showFetchModels, setShowFetchModels] = useState(false);
  const [fetchingProvider, setFetchingProvider] = useState<string | null>(null);
  const [fetchedModels, setFetchedModels] = useState<any[]>([]);
  const [fetchingModels, setFetchingModels] = useState(false);

  useEffect(() => {
    // Separate custom and system models
    setCustomModels(models.filter(m => m.source === 'custom'));
    setSystemModels(models.filter(m => m.source !== 'custom'));
  }, [models]);

  useEffect(() => {
    // Load user preferences
    loadUserPreferences();
    loadOpenRouterKeys();
    loadProviders();
    loadProviderConfigs();
  }, []);

  const loadUserPreferences = async () => {
    try {
      const prefs = await usersApi.getPreferences();
      setDiagramModel(prefs.diagram_model || '');
    } catch (error) {
      console.error('Failed to load preferences:', error);
    } finally {
      setLoadingPreferences(false);
    }
  };

  const loadOpenRouterKeys = async () => {
    try {
      const data = await secretsApi.listApiKeys('openrouter');
      setOpenRouterKeys(data.api_keys || []);
    } catch (error) {
      console.error('Failed to load OpenRouter keys:', error);
    } finally {
      setLoadingKeys(false);
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

  const loadProviderConfigs = async () => {
    try {
      const [ollama, lmstudio, llamacpp, custom] = await Promise.all([
        secretsApi.listApiKeys('ollama'),
        secretsApi.listApiKeys('lmstudio'),
        secretsApi.listApiKeys('llamacpp'),
        secretsApi.listApiKeys('custom'),
      ]);

      setOllamaConfig(ollama.api_keys[0] || null);
      setLmstudioConfig(lmstudio.api_keys[0] || null);
      setLlamacppConfig(llamacpp.api_keys[0] || null);
      setCustomConfigs(custom.api_keys || []);
    } catch (error) {
      console.error('Failed to load provider configs:', error);
    }
  };

  const handleFetchProviderModels = async (provider: string) => {
    setFetchingProvider(provider);
    setFetchingModels(true);
    setShowFetchModels(true);
    setFetchedModels([]);

    try {
      const response = await marketplaceApi.fetchModels(provider);
      setFetchedModels(response.models || []);

      if (response.count === 0) {
        toast.info(`No models found on ${provider}`);
      } else {
        toast.success(`Found ${response.count} models from ${provider}`);
      }
    } catch (error: any) {
      console.error(`Failed to fetch ${provider} models:`, error);
      toast.error(error.response?.data?.detail || `Failed to fetch models from ${provider}`);
      setShowFetchModels(false);
    } finally {
      setFetchingModels(false);
    }
  };

  const handleImportModels = async (provider: string, selectedModels: any[]) => {
    try {
      const response = await marketplaceApi.importBatchModels({
        provider,
        models: selectedModels
      });

      toast.success(`Imported ${response.imported} models from ${provider}`);

      if (response.skipped > 0) {
        toast.info(`Skipped ${response.skipped} duplicate models`);
      }

      // Reload models
      await loadModels();
      setShowFetchModels(false);
    } catch (error: any) {
      console.error('Failed to import models:', error);
      toast.error(error.response?.data?.detail || 'Failed to import models');
    }
  };

  const handleDiagramModelChange = async (modelId: string) => {
    try {
      await usersApi.updatePreferences({ diagram_model: modelId });
      setDiagramModel(modelId);
      toast.success('Diagram generation model updated');
    } catch (error: any) {
      console.error('Failed to update diagram model:', error);
      toast.error(error.response?.data?.detail || 'Failed to update diagram model');
    }
  };

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

  const openRouterProvider = externalProviders.find(p => p.provider === 'openrouter');
  const hasOpenRouterKey = openRouterProvider?.has_key || openRouterKeys.length > 0;

  return (
    <div className="space-y-8">
      {/* OpenRouter Integration Section */}
      <div className="bg-gradient-to-r from-blue-500/10 to-purple-500/10 border border-blue-500/20 rounded-xl p-6">
        <div className="flex items-start gap-4 mb-4">
          <div className="p-3 bg-blue-500/20 rounded-lg">
            <Key size={24} className="text-blue-400" />
          </div>
          <div className="flex-1">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-xl font-bold text-[var(--text)]">OpenRouter Integration</h2>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setShowAddApiKey(true)}
                  className="px-4 py-2 bg-blue-500/10 hover:bg-blue-500/20 border border-blue-500/20 text-blue-400 rounded-lg transition-colors flex items-center gap-2"
                >
                  <Plus size={16} />
                  Add API Key
                </button>
                {hasOpenRouterKey && (
                  <button
                    onClick={() => setShowAddCustomModel(true)}
                    className="px-4 py-2 bg-orange-500/10 hover:bg-orange-500/20 border border-orange-500/20 text-orange-400 rounded-lg transition-colors flex items-center gap-2"
                  >
                    <Plus size={16} />
                    Add Custom Model
                  </button>
                )}
              </div>
            </div>
            <p className="text-[var(--text)]/60 text-sm mb-4">
              Access 200+ AI models through OpenRouter. Add your API key to unlock access to models from Anthropic, OpenAI, Google, Meta, and more.
            </p>

            {/* API Keys List */}
            {loadingKeys ? (
              <div className="px-4 py-3 bg-white/5 border border-[var(--text)]/15 rounded-lg text-[var(--text)]/40">
                Loading keys...
              </div>
            ) : openRouterKeys.length > 0 ? (
              <div className="space-y-2">
                {openRouterKeys.map((key) => (
                  <div
                    key={key.id}
                    className="bg-[var(--surface)] border border-[var(--text)]/15 rounded-lg p-3 flex items-center justify-between"
                  >
                    <div className="flex items-center gap-3">
                      <div className="p-2 bg-green-500/10 rounded-lg">
                        <CheckCircle size={16} className="text-green-400" weight="fill" />
                      </div>
                      <div>
                        {key.key_name && (
                          <div className="text-sm font-medium text-[var(--text)]">{key.key_name}</div>
                        )}
                        <div className="text-xs text-[var(--text)]/40 font-mono">{key.key_preview}</div>
                        <div className="text-xs text-[var(--text)]/40 mt-0.5">
                          Added {new Date(key.created_at).toLocaleDateString()}
                        </div>
                      </div>
                    </div>
                    <button
                      onClick={async () => {
                        try {
                          await secretsApi.deleteApiKey(key.id);
                          toast.success('API key removed');
                          loadOpenRouterKeys();
                        } catch (error) {
                          console.error('Delete failed:', error);
                          toast.error('Failed to delete API key');
                        }
                      }}
                      className="p-2 hover:bg-red-500/10 rounded-lg text-red-400 transition-colors"
                    >
                      <Trash size={16} />
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <div className="px-4 py-3 bg-orange-500/10 border border-orange-500/20 rounded-lg flex items-center gap-2">
                <Circle size={16} className="text-orange-400" />
                <span className="text-sm text-orange-400">No API key configured. Add one to get started.</span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Ollama Integration Section */}
      <div className="bg-gradient-to-r from-green-500/10 to-emerald-500/10 border border-green-500/20 rounded-xl p-6">
        <div className="flex items-start gap-4 mb-4">
          <div className="p-3 bg-green-500/20 rounded-lg">
            <Terminal size={24} className="text-green-400" />
          </div>
          <div className="flex-1">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-xl font-bold text-[var(--text)]">Ollama Integration</h2>
              <div className="flex items-center gap-2">
                {!ollamaConfig && (
                  <button
                    onClick={() => setShowOllamaConfig(true)}
                    className="px-4 py-2 bg-green-500/10 hover:bg-green-500/20 border border-green-500/20 text-green-400 rounded-lg transition-colors flex items-center gap-2"
                  >
                    <Plus size={16} />
                    Connect Ollama
                  </button>
                )}
                {ollamaConfig && (
                  <>
                    <button
                      onClick={() => handleFetchProviderModels('ollama')}
                      className="px-4 py-2 bg-blue-500/10 hover:bg-blue-500/20 border border-blue-500/20 text-blue-400 rounded-lg transition-colors flex items-center gap-2"
                    >
                      <ArrowsClockwise size={16} />
                      Fetch All Models
                    </button>
                    <button
                      onClick={() => {
                        setAddModelProvider('ollama');
                        setShowAddCustomModel(true);
                      }}
                      className="px-4 py-2 bg-orange-500/10 hover:bg-orange-500/20 border border-orange-500/20 text-orange-400 rounded-lg transition-colors flex items-center gap-2"
                    >
                      <Plus size={16} />
                      Add Model Manually
                    </button>
                  </>
                )}
              </div>
            </div>
            <p className="text-[var(--text)]/60 text-sm mb-4">
              Run large language models locally with Ollama. Configure your Ollama server URL and fetch available models.
            </p>

            {/* Configuration Status */}
            {ollamaConfig ? (
              <div className="bg-[var(--surface)] border border-[var(--text)]/15 rounded-lg p-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="p-2 bg-green-500/10 rounded-lg">
                      <CheckCircle size={16} className="text-green-400" weight="fill" />
                    </div>
                    <div>
                      <div className="text-sm font-medium text-[var(--text)]">Connected</div>
                      <div className="text-xs text-[var(--text)]/40">{ollamaConfig.provider_metadata?.base_url || 'http://localhost:11434'}</div>
                    </div>
                  </div>
                  <button
                    onClick={async () => {
                      try {
                        await secretsApi.deleteApiKey(ollamaConfig.id);
                        toast.success('Ollama configuration removed');
                        await loadProviderConfigs();
                      } catch (error) {
                        console.error('Delete failed:', error);
                        toast.error('Failed to remove configuration');
                      }
                    }}
                    className="p-2 hover:bg-red-500/10 rounded-lg text-red-400 transition-colors"
                  >
                    <Trash size={16} />
                  </button>
                </div>
              </div>
            ) : (
              <div className="px-4 py-3 bg-orange-500/10 border border-orange-500/20 rounded-lg flex items-center gap-2">
                <Circle size={16} className="text-orange-400" />
                <span className="text-sm text-orange-400">Not configured. Connect to get started.</span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* LM Studio Integration Section */}
      <div className="bg-gradient-to-r from-purple-500/10 to-pink-500/10 border border-purple-500/20 rounded-xl p-6">
        <div className="flex items-start gap-4 mb-4">
          <div className="p-3 bg-purple-500/20 rounded-lg">
            <Desktop size={24} className="text-purple-400" />
          </div>
          <div className="flex-1">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-xl font-bold text-[var(--text)]">LM Studio Integration</h2>
              <div className="flex items-center gap-2">
                {!lmstudioConfig && (
                  <button
                    onClick={() => setShowLMStudioConfig(true)}
                    className="px-4 py-2 bg-purple-500/10 hover:bg-purple-500/20 border border-purple-500/20 text-purple-400 rounded-lg transition-colors flex items-center gap-2"
                  >
                    <Plus size={16} />
                    Connect LM Studio
                  </button>
                )}
                {lmstudioConfig && (
                  <>
                    <button
                      onClick={() => handleFetchProviderModels('lmstudio')}
                      className="px-4 py-2 bg-blue-500/10 hover:bg-blue-500/20 border border-blue-500/20 text-blue-400 rounded-lg transition-colors flex items-center gap-2"
                    >
                      <ArrowsClockwise size={16} />
                      Fetch All Models
                    </button>
                    <button
                      onClick={() => {
                        setAddModelProvider('lmstudio');
                        setShowAddCustomModel(true);
                      }}
                      className="px-4 py-2 bg-orange-500/10 hover:bg-orange-500/20 border border-orange-500/20 text-orange-400 rounded-lg transition-colors flex items-center gap-2"
                    >
                      <Plus size={16} />
                      Add Model Manually
                    </button>
                  </>
                )}
              </div>
            </div>
            <p className="text-[var(--text)]/60 text-sm mb-4">
              Local LLM inference with LM Studio. Connect to your LM Studio server and access loaded models.
            </p>

            {/* Configuration Status */}
            {lmstudioConfig ? (
              <div className="bg-[var(--surface)] border border-[var(--text)]/15 rounded-lg p-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="p-2 bg-purple-500/10 rounded-lg">
                      <CheckCircle size={16} className="text-purple-400" weight="fill" />
                    </div>
                    <div>
                      <div className="text-sm font-medium text-[var(--text)]">Connected</div>
                      <div className="text-xs text-[var(--text)]/40">{lmstudioConfig.provider_metadata?.base_url || 'http://localhost:1234'}</div>
                    </div>
                  </div>
                  <button
                    onClick={async () => {
                      try {
                        await secretsApi.deleteApiKey(lmstudioConfig.id);
                        toast.success('LM Studio configuration removed');
                        await loadProviderConfigs();
                      } catch (error) {
                        console.error('Delete failed:', error);
                        toast.error('Failed to remove configuration');
                      }
                    }}
                    className="p-2 hover:bg-red-500/10 rounded-lg text-red-400 transition-colors"
                  >
                    <Trash size={16} />
                  </button>
                </div>
              </div>
            ) : (
              <div className="px-4 py-3 bg-orange-500/10 border border-orange-500/20 rounded-lg flex items-center gap-2">
                <Circle size={16} className="text-orange-400" />
                <span className="text-sm text-orange-400">Not configured. Connect to get started.</span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* llama.cpp Integration Section */}
      <div className="bg-gradient-to-r from-yellow-500/10 to-orange-500/10 border border-yellow-500/20 rounded-xl p-6">
        <div className="flex items-start gap-4 mb-4">
          <div className="p-3 bg-yellow-500/20 rounded-lg">
            <Microchip size={24} className="text-yellow-400" />
          </div>
          <div className="flex-1">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-xl font-bold text-[var(--text)]">llama.cpp Integration</h2>
              <div className="flex items-center gap-2">
                {!llamacppConfig && (
                  <button
                    onClick={() => setShowLlamaCppConfig(true)}
                    className="px-4 py-2 bg-yellow-500/10 hover:bg-yellow-500/20 border border-yellow-500/20 text-yellow-400 rounded-lg transition-colors flex items-center gap-2"
                  >
                    <Plus size={16} />
                    Connect llama.cpp
                  </button>
                )}
                {llamacppConfig && (
                  <>
                    <button
                      onClick={() => handleFetchProviderModels('llamacpp')}
                      className="px-4 py-2 bg-blue-500/10 hover:bg-blue-500/20 border border-blue-500/20 text-blue-400 rounded-lg transition-colors flex items-center gap-2"
                    >
                      <ArrowsClockwise size={16} />
                      Fetch All Models
                    </button>
                    <button
                      onClick={() => {
                        setAddModelProvider('llamacpp');
                        setShowAddCustomModel(true);
                      }}
                      className="px-4 py-2 bg-orange-500/10 hover:bg-orange-500/20 border border-orange-500/20 text-orange-400 rounded-lg transition-colors flex items-center gap-2"
                    >
                      <Plus size={16} />
                      Add Model Manually
                    </button>
                  </>
                )}
              </div>
            </div>
            <p className="text-[var(--text)]/60 text-sm mb-4">
              Efficient local inference with llama.cpp server. Connect to your llama.cpp server instance.
            </p>

            {/* Configuration Status */}
            {llamacppConfig ? (
              <div className="bg-[var(--surface)] border border-[var(--text)]/15 rounded-lg p-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="p-2 bg-yellow-500/10 rounded-lg">
                      <CheckCircle size={16} className="text-yellow-400" weight="fill" />
                    </div>
                    <div>
                      <div className="text-sm font-medium text-[var(--text)]">Connected</div>
                      <div className="text-xs text-[var(--text)]/40">{llamacppConfig.provider_metadata?.base_url || 'http://localhost:8080'}</div>
                    </div>
                  </div>
                  <button
                    onClick={async () => {
                      try {
                        await secretsApi.deleteApiKey(llamacppConfig.id);
                        toast.success('llama.cpp configuration removed');
                        await loadProviderConfigs();
                      } catch (error) {
                        console.error('Delete failed:', error);
                        toast.error('Failed to remove configuration');
                      }
                    }}
                    className="p-2 hover:bg-red-500/10 rounded-lg text-red-400 transition-colors"
                  >
                    <Trash size={16} />
                  </button>
                </div>
              </div>
            ) : (
              <div className="px-4 py-3 bg-orange-500/10 border border-orange-500/20 rounded-lg flex items-center gap-2">
                <Circle size={16} className="text-orange-400" />
                <span className="text-sm text-orange-400">Not configured. Connect to get started.</span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Custom Endpoint Integration Section */}
      <div className="bg-gradient-to-r from-gray-500/10 to-slate-500/10 border border-gray-500/20 rounded-xl p-6">
        <div className="flex items-start gap-4 mb-4">
          <div className="p-3 bg-gray-500/20 rounded-lg">
            <Wrench size={24} className="text-gray-400" />
          </div>
          <div className="flex-1">
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-xl font-bold text-[var(--text)]">Custom API Endpoint</h2>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setShowCustomConfig(true)}
                  className="px-4 py-2 bg-gray-500/10 hover:bg-gray-500/20 border border-gray-500/20 text-gray-400 rounded-lg transition-colors flex items-center gap-2"
                >
                  <Plus size={16} />
                  Add Custom Endpoint
                </button>
                {customConfigs.length > 0 && (
                  <>
                    <button
                      onClick={() => handleFetchProviderModels('custom')}
                      className="px-4 py-2 bg-blue-500/10 hover:bg-blue-500/20 border border-blue-500/20 text-blue-400 rounded-lg transition-colors flex items-center gap-2"
                    >
                      <ArrowsClockwise size={16} />
                      Fetch All Models
                    </button>
                    <button
                      onClick={() => {
                        setAddModelProvider('custom');
                        setShowAddCustomModel(true);
                      }}
                      className="px-4 py-2 bg-orange-500/10 hover:bg-orange-500/20 border border-orange-500/20 text-orange-400 rounded-lg transition-colors flex items-center gap-2"
                    >
                      <Plus size={16} />
                      Add Model Manually
                    </button>
                  </>
                )}
              </div>
            </div>
            <p className="text-[var(--text)]/60 text-sm mb-4">
              Connect to any OpenAI-compatible API endpoint. Configure your custom server URL and API key.
            </p>

            {/* Configuration Status */}
            {customConfigs.length > 0 ? (
              <div className="space-y-2">
                {customConfigs.map((config) => (
                  <div
                    key={config.id}
                    className="bg-[var(--surface)] border border-[var(--text)]/15 rounded-lg p-3 flex items-center justify-between"
                  >
                    <div className="flex items-center gap-3">
                      <div className="p-2 bg-gray-500/10 rounded-lg">
                        <CheckCircle size={16} className="text-gray-400" weight="fill" />
                      </div>
                      <div>
                        {config.key_name && (
                          <div className="text-sm font-medium text-[var(--text)]">{config.key_name}</div>
                        )}
                        <div className="text-xs text-[var(--text)]/40">{config.provider_metadata?.base_url || 'Custom endpoint'}</div>
                      </div>
                    </div>
                    <button
                      onClick={async () => {
                        try {
                          await secretsApi.deleteApiKey(config.id);
                          toast.success('Custom endpoint removed');
                          await loadProviderConfigs();
                        } catch (error) {
                          console.error('Delete failed:', error);
                          toast.error('Failed to remove configuration');
                        }
                      }}
                      className="p-2 hover:bg-red-500/10 rounded-lg text-red-400 transition-colors"
                    >
                      <Trash size={16} />
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <div className="px-4 py-3 bg-orange-500/10 border border-orange-500/20 rounded-lg flex items-center gap-2">
                <Circle size={16} className="text-orange-400" />
                <span className="text-sm text-orange-400">No custom endpoints configured.</span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Diagram Model Selection */}
      <div className="bg-gradient-to-r from-orange-500/10 to-purple-500/10 border border-orange-500/20 rounded-xl p-6">
        <div className="flex items-start gap-4 mb-4">
          <div className="p-3 bg-orange-500/20 rounded-lg">
            <ChartLine size={24} className="text-orange-400" />
          </div>
          <div className="flex-1">
            <h2 className="text-xl font-bold text-[var(--text)] mb-2">Architecture Diagram Generation</h2>
            <p className="text-[var(--text)]/60 text-sm mb-4">
              Select which AI model to use for generating architecture diagrams of your projects.
              This model will analyze your code and create Mermaid diagrams showing component relationships.
            </p>
          </div>
        </div>

        <div className="mt-4">
          <label className="block text-sm font-medium text-[var(--text)] mb-2">
            Diagram Generation Model
          </label>
          {loadingPreferences ? (
            <div className="px-4 py-3 bg-white/5 border border-[var(--text)]/15 rounded-lg text-[var(--text)]/40">
              Loading preferences...
            </div>
          ) : (
            <select
              value={diagramModel}
              onChange={(e) => handleDiagramModelChange(e.target.value)}
              className="w-full px-4 py-3 bg-[var(--surface)] border border-[var(--text)]/15 rounded-lg text-[var(--text)] focus:outline-none focus:border-orange-500/50 transition-colors [&>option]:bg-[var(--surface)] [&>option]:text-[var(--text)]"
            >
              <option value="">Select a model...</option>
              {[...systemModels, ...customModels].map((model) => (
                <option key={model.id} value={model.id}>
                  {model.name} ({model.provider})
                </option>
              ))}
            </select>
          )}
          {diagramModel && (
            <div className="mt-3 px-3 py-2 bg-green-500/10 border border-green-500/20 rounded-lg flex items-center gap-2">
              <CheckCircle size={16} className="text-green-400" weight="fill" />
              <span className="text-xs text-green-400">
                Diagram generation configured with {models.find(m => m.id === diagramModel)?.name || diagramModel}
              </span>
            </div>
          )}
          {!diagramModel && !loadingPreferences && (
            <p className="mt-2 text-xs text-[var(--text)]/40">
              You must select a model before you can generate architecture diagrams
            </p>
          )}
        </div>
      </div>

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
                <div className="grid grid-cols-2 gap-3 pt-3 border-t border-[var(--text)]/15">
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
              className="bg-[var(--surface)] border border-[var(--text)]/15 rounded-lg p-4 hover:border-orange-500/30 transition-all"
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
              <div className="grid grid-cols-2 gap-3 mt-3 pt-3 border-t border-[var(--text)]/15">
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
                className="bg-[var(--surface)] border border-[var(--text)]/15 rounded-lg p-4"
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
                  <div className="mt-3 px-3 py-2 bg-green-500/10 border border-green-500/20 rounded-lg flex items-center justify-center gap-2">
                    <CheckCircle size={16} className="text-green-400" weight="fill" />
                    <span className="text-xs text-green-400">Configured</span>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Add OpenRouter API Key Modal */}
      {showAddApiKey && (
        <AddApiKeyModal
          providers={providers.filter(p => p.id === 'openrouter')}
          onClose={() => setShowAddApiKey(false)}
          onSuccess={() => {
            setShowAddApiKey(false);
            loadOpenRouterKeys();
          }}
        />
      )}

      {/* Add Custom Model Modal */}
      {showAddCustomModel && (
        <AddCustomModelModal
          provider={addModelProvider}
          onClose={() => setShowAddCustomModel(false)}
          onSuccess={() => {
            setShowAddCustomModel(false);
            toast.success('Custom model added successfully');
            window.location.reload();
          }}
        />
      )}

      {/* Ollama Configuration Modal */}
      {showOllamaConfig && (
        <OllamaConfigModal
          onClose={() => setShowOllamaConfig(false)}
          onSuccess={() => {
            setShowOllamaConfig(false);
            loadProviderConfigs();
          }}
        />
      )}

      {/* LM Studio Configuration Modal */}
      {showLMStudioConfig && (
        <LMStudioConfigModal
          onClose={() => setShowLMStudioConfig(false)}
          onSuccess={() => {
            setShowLMStudioConfig(false);
            loadProviderConfigs();
          }}
        />
      )}

      {/* llama.cpp Configuration Modal */}
      {showLlamaCppConfig && (
        <LlamaCppConfigModal
          onClose={() => setShowLlamaCppConfig(false)}
          onSuccess={() => {
            setShowLlamaCppConfig(false);
            loadProviderConfigs();
          }}
        />
      )}

      {/* Custom Endpoint Configuration Modal */}
      {showCustomConfig && (
        <CustomEndpointConfigModal
          onClose={() => setShowCustomConfig(false)}
          onSuccess={() => {
            setShowCustomConfig(false);
            loadProviderConfigs();
          }}
        />
      )}

      {/* Fetch Models Result Modal */}
      {showFetchModels && fetchingProvider && (
        <FetchModelsResultModal
          provider={fetchingProvider}
          models={fetchedModels}
          loading={fetchingModels}
          onClose={() => {
            setShowFetchModels(false);
            setFetchingProvider(null);
            setFetchedModels([]);
          }}
          onImport={(selectedModels) => handleImportModels(fetchingProvider, selectedModels)}
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
        <div className="text-center py-16 bg-[var(--surface)] border border-[var(--text)]/15 rounded-lg">
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
              className="bg-[var(--surface)] border border-[var(--text)]/15 rounded-lg p-4"
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
    <div className="bg-[var(--surface)] border border-[var(--text)]/15 rounded-lg p-4 flex items-center justify-between">
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
          <div className="bg-[var(--surface)] border border-[var(--text)]/15 rounded-lg p-6 max-w-md">
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
      <div className="bg-[var(--surface)] border border-[var(--text)]/15 rounded-xl max-w-md w-full p-6">
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
              className="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--text)]/15 rounded-lg text-[var(--text)] focus:outline-none focus:border-orange-500/50 [&>option]:bg-[var(--surface)] [&>option]:text-[var(--text)]"
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
                className="w-full px-4 py-2 pr-12 bg-white/5 border border-[var(--text)]/15 rounded-lg text-[var(--text)] focus:outline-none focus:border-orange-500/50 font-mono text-sm"
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
              className="w-full px-4 py-2 bg-white/5 border border-[var(--text)]/15 rounded-lg text-[var(--text)] focus:outline-none focus:border-orange-500/50"
              placeholder="My API Key"
            />
            <p className="mt-1 text-xs text-[var(--text)]/40">
              Useful if you have multiple keys for the same provider
            </p>
          </div>

          <div className="flex items-center gap-3 justify-end pt-4 border-t border-[var(--text)]/15">
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
  onModelChange,
  onRemove
}: {
  agent: LibraryAgent;
  availableModels: string[];
  onToggleEnable: () => void;
  onEdit: () => void;
  onTogglePublish: () => void;
  onModelChange: (model: string) => void;
  onRemove: () => void;
}) {
  const canEdit = agent.source_type === 'open' || agent.is_custom;
  const canChangeModel = agent.source_type === 'open' || agent.is_custom;
  const currentModel = agent.selected_model || agent.model;

  return (
    <div className={`relative bg-[var(--surface)] border rounded-2xl p-6 transition-all ${
      agent.is_enabled
        ? 'border-[var(--text)]/15 hover:border-orange-500/30'
        : 'border-white/5 opacity-60'
    }`}>
      {/* Status Badge - Top Right */}
      <div className="absolute top-4 right-4">
        {agent.is_enabled ? (
          <span className="px-2.5 py-1 bg-green-500/20 text-green-400 text-xs rounded-md font-medium">
            Active
          </span>
        ) : (
          <span className="px-2.5 py-1 bg-white/10 text-white/40 text-xs rounded-md font-medium">
            Disabled
          </span>
        )}
      </div>

      {/* Header */}
      <div className="flex items-start gap-4 mb-4 pr-20">
        <div className="text-4xl">{agent.icon}</div>
        <div className="flex-1">
          <h3 className="font-heading font-bold text-[var(--text)] text-xl mb-2">{agent.name}</h3>
          <div className="flex flex-wrap items-center gap-2">
            {agent.source_type === 'open' ? (
              <span className="flex items-center gap-1 px-2 py-0.5 bg-green-500/20 text-green-400 text-xs rounded">
                <LockSimpleOpen size={10} />
                Open Source
              </span>
            ) : (
              <span className="flex items-center gap-1 px-2 py-0.5 bg-purple-500/20 text-purple-400 text-xs rounded">
                <LockKey size={10} />
                Closed Source
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

      {/* Description */}
      <p className="text-[var(--text)]/60 text-sm mb-4 line-clamp-2">{agent.description}</p>

      {/* Model Selection */}
      <div className="mb-4">
        {canChangeModel ? (
          <div className="relative">
            <select
              value={currentModel}
              onChange={(e) => onModelChange(e.target.value)}
              className="w-full px-3 py-2 pl-8 bg-blue-500/10 border border-blue-500/20 rounded-lg text-blue-400 text-xs font-medium focus:outline-none focus:border-blue-500/40 hover:bg-blue-500/15 transition-colors cursor-pointer appearance-none pr-8 [&>option]:bg-[var(--surface)] [&>option]:text-[var(--text)]"
            >
              {availableModels.length > 0 ? (
                availableModels.map((modelName) => (
                  <option key={modelName} value={modelName}>
                    {modelName}
                  </option>
                ))
              ) : (
                <option value={currentModel}>{currentModel}</option>
              )}
            </select>
            <Cpu size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-blue-400 pointer-events-none" />
            <div className="absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none text-blue-400">
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                <path d="M3 4.5L6 7.5L9 4.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </div>
          </div>
        ) : (
          <div className="flex items-center gap-2 px-3 py-1.5 bg-blue-500/10 border border-blue-500/20 rounded-lg w-fit">
            <Cpu size={14} className="text-blue-400" />
            <span className="text-xs text-blue-400 font-medium">{currentModel}</span>
          </div>
        )}
      </div>

      {/* Tools */}
      <div className="mb-4">
        <div className="flex flex-wrap gap-1.5">
          {(agent.tools && agent.tools.length > 0 ? agent.tools : ALL_TOOLS).map((toolName, idx) => {
            const tool = getToolIcon(toolName);
            if (!tool) return null;
            return (
              <div
                key={idx}
                className="flex items-center gap-1 px-2 py-1 bg-orange-500/10 border border-orange-500/20 text-orange-400 text-xs rounded-md font-medium"
                title={tool.label}
              >
                {tool.icon}
                <span>{tool.label}</span>
              </div>
            );
          })}
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
      <div className="flex items-center gap-2 pt-4 border-t border-[var(--text)]/15">
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

      {/* Remove Button */}
      <div className="mt-3">
        <button
          onClick={onRemove}
          className="w-full py-2 px-3 bg-white/5 hover:bg-red-500/10 border border-[var(--text)]/15 hover:border-red-500/20 text-[var(--text)]/60 hover:text-red-400 rounded-lg transition-colors flex items-center justify-center gap-2"
        >
          <Trash size={16} />
          Remove from Library
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
      <div className="bg-[var(--surface)] border border-[var(--text)]/15 rounded-xl max-w-3xl w-full p-6 max-h-[90vh] overflow-y-auto">
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
              className="w-full px-4 py-2 bg-white/5 border border-[var(--text)]/15 rounded-lg text-[var(--text)] focus:outline-none focus:border-orange-500/50"
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
              className="w-full px-4 py-2 bg-white/5 border border-[var(--text)]/15 rounded-lg text-[var(--text)] focus:outline-none focus:border-orange-500/50"
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
              className="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--text)]/15 rounded-lg text-[var(--text)] focus:outline-none focus:border-orange-500/50 [&>option]:bg-[var(--surface)] [&>option]:text-[var(--text)]"
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
              className="w-full px-4 py-2 bg-white/5 border border-[var(--text)]/15 rounded-lg text-[var(--text)] focus:outline-none focus:border-orange-500/50 font-mono text-sm resize-y"
              required
            />
            <p className="mt-1 text-xs text-[var(--text)]/40">
              {systemPrompt.length} characters
            </p>
          </div>

          <div className="flex items-center gap-3 justify-end pt-4 border-t border-[var(--text)]/15">
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
  provider = 'openrouter',
  onClose,
  onSuccess
}: {
  provider?: string;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const [modelId, setModelId] = useState('');
  const [modelName, setModelName] = useState('');
  const [pricingInput, setPricingInput] = useState('');
  const [pricingOutput, setPricingOutput] = useState('');
  const [loading, setLoading] = useState(false);

  const providerLabels: Record<string, string> = {
    openrouter: 'OpenRouter',
    ollama: 'Ollama',
    lmstudio: 'LM Studio',
    llamacpp: 'llama.cpp',
    custom: 'Custom Endpoint'
  };

  const providerPlaceholders: Record<string, string> = {
    openrouter: 'openrouter/model-name',
    ollama: 'llama2:latest',
    lmstudio: 'local-model',
    llamacpp: 'model-name',
    custom: 'custom/model-name'
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);

    try {
      await marketplaceApi.addCustomModel({
        model_id: modelId,
        model_name: modelName,
        provider: provider, // Pass provider to API
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
      <div className="bg-[var(--surface)] border border-[var(--text)]/15 rounded-xl max-w-md w-full p-6">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-2xl font-bold text-[var(--text)] flex items-center gap-2">
            <Plus size={24} />
            Add {providerLabels[provider] || provider} Model
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
              className="w-full px-4 py-2 bg-white/5 border border-[var(--text)]/15 rounded-lg text-[var(--text)] focus:outline-none focus:border-orange-500/50 font-mono text-sm"
              placeholder={providerPlaceholders[provider] || 'model-name'}
              required
            />
            <p className="mt-1 text-xs text-[var(--text)]/40">
              {provider === 'openrouter' ? 'Find model IDs at openrouter.ai' : `Enter the model ID from your ${providerLabels[provider] || provider} instance`}
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
              className="w-full px-4 py-2 bg-white/5 border border-[var(--text)]/15 rounded-lg text-[var(--text)] focus:outline-none focus:border-orange-500/50"
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
                className="w-full px-4 py-2 bg-white/5 border border-[var(--text)]/15 rounded-lg text-[var(--text)] focus:outline-none focus:border-orange-500/50"
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
                className="w-full px-4 py-2 bg-white/5 border border-[var(--text)]/15 rounded-lg text-[var(--text)] focus:outline-none focus:border-orange-500/50"
                placeholder="0.00"
              />
            </div>
          </div>

          <div className="flex items-center gap-3 justify-end pt-4 border-t border-[var(--text)]/15">
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

// Ollama Configuration Modal Component
function OllamaConfigModal({
  onClose,
  onSuccess
}: {
  onClose: () => void;
  onSuccess: () => void;
}) {
  const [baseUrl, setBaseUrl] = useState('http://localhost:11434');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);

    try {
      await secretsApi.addApiKey({
        provider: 'ollama',
        api_key: 'ollama', // Ollama doesn't require authentication
        auth_type: 'none',
        provider_metadata: {
          base_url: baseUrl.trim()
        }
      });
      toast.success('Ollama connected successfully');
      onSuccess();
    } catch (error: any) {
      console.error('Ollama connection failed:', error);
      toast.error(error.response?.data?.detail || 'Failed to connect to Ollama');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-[var(--surface)] border border-[var(--text)]/15 rounded-xl max-w-md w-full p-6">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-2xl font-bold text-[var(--text)] flex items-center gap-2">
            <Terminal size={24} className="text-green-400" />
            Connect to Ollama
          </h2>
          <button
            onClick={onClose}
            className="p-2 hover:bg-white/5 rounded-lg transition-colors text-[var(--text)]/60"
          >
            <X size={20} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-[var(--text)] mb-2">
              Ollama API URL
            </label>
            <input
              type="url"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              className="w-full px-4 py-2 bg-white/5 border border-[var(--text)]/15 rounded-lg text-[var(--text)] focus:outline-none focus:border-green-500/50 font-mono text-sm"
              placeholder="http://localhost:11434"
              required
            />
            <p className="mt-1 text-xs text-[var(--text)]/40">
              Default Ollama server URL. Modify if running on a different host or port.
            </p>
          </div>

          <div className="flex items-center gap-3 justify-end pt-4 border-t border-[var(--text)]/15">
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
              className="px-6 py-2 bg-green-500 hover:bg-green-600 rounded-lg text-white transition-colors flex items-center gap-2 disabled:opacity-50"
              disabled={loading}
            >
              {loading ? (
                <>Connecting...</>
              ) : (
                <>
                  <Link size={18} />
                  Connect
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// LM Studio Configuration Modal Component
function LMStudioConfigModal({
  onClose,
  onSuccess
}: {
  onClose: () => void;
  onSuccess: () => void;
}) {
  const [baseUrl, setBaseUrl] = useState('http://localhost:1234');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);

    try {
      await secretsApi.addApiKey({
        provider: 'lmstudio',
        api_key: 'lmstudio', // LM Studio doesn't require authentication
        auth_type: 'none',
        provider_metadata: {
          base_url: baseUrl.trim()
        }
      });
      toast.success('LM Studio connected successfully');
      onSuccess();
    } catch (error: any) {
      console.error('LM Studio connection failed:', error);
      toast.error(error.response?.data?.detail || 'Failed to connect to LM Studio');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-[var(--surface)] border border-[var(--text)]/15 rounded-xl max-w-md w-full p-6">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-2xl font-bold text-[var(--text)] flex items-center gap-2">
            <Desktop size={24} className="text-purple-400" />
            Connect to LM Studio
          </h2>
          <button
            onClick={onClose}
            className="p-2 hover:bg-white/5 rounded-lg transition-colors text-[var(--text)]/60"
          >
            <X size={20} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-[var(--text)] mb-2">
              LM Studio API URL
            </label>
            <input
              type="url"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              className="w-full px-4 py-2 bg-white/5 border border-[var(--text)]/15 rounded-lg text-[var(--text)] focus:outline-none focus:border-purple-500/50 font-mono text-sm"
              placeholder="http://localhost:1234"
              required
            />
            <p className="mt-1 text-xs text-[var(--text)]/40">
              Default LM Studio server URL. Modify if using a different configuration.
            </p>
          </div>

          <div className="flex items-center gap-3 justify-end pt-4 border-t border-[var(--text)]/15">
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
              className="px-6 py-2 bg-purple-500 hover:bg-purple-600 rounded-lg text-white transition-colors flex items-center gap-2 disabled:opacity-50"
              disabled={loading}
            >
              {loading ? (
                <>Connecting...</>
              ) : (
                <>
                  <Link size={18} />
                  Connect
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// llama.cpp Configuration Modal Component
function LlamaCppConfigModal({
  onClose,
  onSuccess
}: {
  onClose: () => void;
  onSuccess: () => void;
}) {
  const [baseUrl, setBaseUrl] = useState('http://localhost:8080');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);

    try {
      await secretsApi.addApiKey({
        provider: 'llamacpp',
        api_key: 'llamacpp', // llama.cpp doesn't require authentication
        auth_type: 'none',
        provider_metadata: {
          base_url: baseUrl.trim()
        }
      });
      toast.success('llama.cpp connected successfully');
      onSuccess();
    } catch (error: any) {
      console.error('llama.cpp connection failed:', error);
      toast.error(error.response?.data?.detail || 'Failed to connect to llama.cpp');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-[var(--surface)] border border-[var(--text)]/15 rounded-xl max-w-md w-full p-6">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-2xl font-bold text-[var(--text)] flex items-center gap-2">
            <Microchip size={24} className="text-yellow-400" />
            Connect to llama.cpp
          </h2>
          <button
            onClick={onClose}
            className="p-2 hover:bg-white/5 rounded-lg transition-colors text-[var(--text)]/60"
          >
            <X size={20} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-[var(--text)] mb-2">
              llama.cpp Server URL
            </label>
            <input
              type="url"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              className="w-full px-4 py-2 bg-white/5 border border-[var(--text)]/15 rounded-lg text-[var(--text)] focus:outline-none focus:border-yellow-500/50 font-mono text-sm"
              placeholder="http://localhost:8080"
              required
            />
            <p className="mt-1 text-xs text-[var(--text)]/40">
              Default llama.cpp server URL. Adjust if running on a custom port.
            </p>
          </div>

          <div className="flex items-center gap-3 justify-end pt-4 border-t border-[var(--text)]/15">
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
              className="px-6 py-2 bg-yellow-500 hover:bg-yellow-600 rounded-lg text-white transition-colors flex items-center gap-2 disabled:opacity-50"
              disabled={loading}
            >
              {loading ? (
                <>Connecting...</>
              ) : (
                <>
                  <Link size={18} />
                  Connect
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// Custom Endpoint Configuration Modal Component
function CustomEndpointConfigModal({
  onClose,
  onSuccess
}: {
  onClose: () => void;
  onSuccess: () => void;
}) {
  const [displayName, setDisplayName] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);

    try {
      await secretsApi.addApiKey({
        provider: 'custom',
        api_key: apiKey.trim(),
        auth_type: 'api_key',
        key_name: displayName.trim(),
        provider_metadata: {
          base_url: baseUrl.trim()
        }
      });
      toast.success('Custom endpoint connected successfully');
      onSuccess();
    } catch (error: any) {
      console.error('Custom endpoint connection failed:', error);
      toast.error(error.response?.data?.detail || 'Failed to connect to custom endpoint');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-[var(--surface)] border border-[var(--text)]/15 rounded-xl max-w-md w-full p-6">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-2xl font-bold text-[var(--text)] flex items-center gap-2">
            <Wrench size={24} className="text-gray-400" />
            Add Custom Endpoint
          </h2>
          <button
            onClick={onClose}
            className="p-2 hover:bg-white/5 rounded-lg transition-colors text-[var(--text)]/60"
          >
            <X size={20} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-[var(--text)] mb-2">
              Display Name
            </label>
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              className="w-full px-4 py-2 bg-white/5 border border-[var(--text)]/15 rounded-lg text-[var(--text)] focus:outline-none focus:border-gray-500/50"
              placeholder="My Custom API"
              required
            />
            <p className="mt-1 text-xs text-[var(--text)]/40">
              A friendly name to identify this endpoint
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-[var(--text)] mb-2">
              API Base URL
            </label>
            <input
              type="url"
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              className="w-full px-4 py-2 bg-white/5 border border-[var(--text)]/15 rounded-lg text-[var(--text)] focus:outline-none focus:border-gray-500/50 font-mono text-sm"
              placeholder="https://api.example.com/v1"
              required
            />
            <p className="mt-1 text-xs text-[var(--text)]/40">
              The base URL for your OpenAI-compatible API endpoint
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-[var(--text)] mb-2">
              API Key
            </label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              className="w-full px-4 py-2 bg-white/5 border border-[var(--text)]/15 rounded-lg text-[var(--text)] focus:outline-none focus:border-gray-500/50 font-mono text-sm"
              placeholder="sk-..."
              required
            />
            <p className="mt-1 text-xs text-[var(--text)]/40">
              Your API key for authentication (stored encrypted)
            </p>
          </div>

          <div className="flex items-center gap-3 justify-end pt-4 border-t border-[var(--text)]/15">
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
              className="px-6 py-2 bg-gray-500 hover:bg-gray-600 rounded-lg text-white transition-colors flex items-center gap-2 disabled:opacity-50"
              disabled={loading}
            >
              {loading ? (
                <>Connecting...</>
              ) : (
                <>
                  <Link size={18} />
                  Connect
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// Fetch Models Result Modal Component
function FetchModelsResultModal({
  provider,
  models,
  loading,
  onClose,
  onImport
}: {
  provider: string;
  models: any[];
  loading: boolean;
  onClose: () => void;
  onImport: (selectedModels: any[]) => void;
}) {
  const [selectedModels, setSelectedModels] = useState<Set<string>>(new Set());
  const [selectAll, setSelectAll] = useState(true);

  // Initialize with all models selected
  React.useEffect(() => {
    if (models.length > 0 && selectedModels.size === 0) {
      setSelectedModels(new Set(models.map(m => m.id || m.model_id)));
      setSelectAll(true);
    }
  }, [models]);

  const toggleModel = (modelId: string) => {
    const newSelected = new Set(selectedModels);
    if (newSelected.has(modelId)) {
      newSelected.delete(modelId);
    } else {
      newSelected.add(modelId);
    }
    setSelectedModels(newSelected);
    setSelectAll(newSelected.size === models.length);
  };

  const toggleSelectAll = () => {
    if (selectAll) {
      setSelectedModels(new Set());
      setSelectAll(false);
    } else {
      setSelectedModels(new Set(models.map(m => m.id || m.model_id)));
      setSelectAll(true);
    }
  };

  const handleImport = () => {
    const modelsToImport = models.filter(m =>
      selectedModels.has(m.id || m.model_id)
    );
    onImport(modelsToImport);
  };

  const providerColors = {
    ollama: 'green',
    lmstudio: 'purple',
    llamacpp: 'yellow',
    custom: 'gray',
    openrouter: 'orange'
  };

  const color = providerColors[provider as keyof typeof providerColors] || 'gray';

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-[var(--surface)] border border-[var(--text)]/15 rounded-xl max-w-2xl w-full max-h-[80vh] flex flex-col">
        <div className="p-6 border-b border-[var(--text)]/15">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-2xl font-bold text-[var(--text)] flex items-center gap-2">
                <ArrowsClockwise size={24} className={`text-${color}-400`} />
                Models from {provider}
              </h2>
              <p className="text-sm text-[var(--text)]/60 mt-1">
                {loading ? 'Fetching models...' : `Found ${models.length} models`}
              </p>
            </div>
            <button
              onClick={onClose}
              className="p-2 hover:bg-white/5 rounded-lg transition-colors text-[var(--text)]/60"
            >
              <X size={20} />
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-6">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-orange-500"></div>
            </div>
          ) : models.length === 0 ? (
            <div className="text-center py-12">
              <p className="text-[var(--text)]/60">No models found</p>
            </div>
          ) : (
            <div className="space-y-2">
              <div className="flex items-center justify-between mb-4 pb-3 border-b border-[var(--text)]/15">
                <button
                  onClick={toggleSelectAll}
                  className="flex items-center gap-2 text-sm font-medium text-[var(--text)] hover:text-orange-400 transition-colors"
                >
                  <input
                    type="checkbox"
                    checked={selectAll}
                    onChange={toggleSelectAll}
                    className="w-4 h-4 rounded border-[var(--text)]/30 bg-white/5"
                  />
                  {selectAll ? 'Deselect All' : 'Select All'}
                </button>
                <span className="text-sm text-[var(--text)]/60">
                  {selectedModels.size} of {models.length} selected
                </span>
              </div>

              {models.map((model) => {
                const modelId = model.id || model.model_id;
                const modelName = model.name || model.model_name || modelId;
                const isSelected = selectedModels.has(modelId);

                return (
                  <label
                    key={modelId}
                    className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-all ${
                      isSelected
                        ? `border-${color}-500/50 bg-${color}-500/10`
                        : 'border-[var(--text)]/15 hover:border-[var(--text)]/30 bg-white/5'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => toggleModel(modelId)}
                      className="mt-1 w-4 h-4 rounded border-[var(--text)]/30 bg-white/5"
                    />
                    <div className="flex-1 min-w-0">
                      <div className="font-medium text-[var(--text)]">{modelName}</div>
                      <div className="text-sm font-mono text-[var(--text)]/60 truncate">
                        {modelId}
                      </div>
                      {model.description && (
                        <div className="text-xs text-[var(--text)]/40 mt-1 line-clamp-2">
                          {model.description}
                        </div>
                      )}
                    </div>
                  </label>
                );
              })}
            </div>
          )}
        </div>

        <div className="p-6 border-t border-[var(--text)]/15">
          <div className="flex items-center gap-3 justify-end">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 bg-white/5 hover:bg-white/10 rounded-lg text-[var(--text)]/80 transition-colors"
              disabled={loading}
            >
              Cancel
            </button>
            <button
              onClick={handleImport}
              className={`px-6 py-2 bg-${color}-500 hover:bg-${color}-600 rounded-lg text-white transition-colors flex items-center gap-2 disabled:opacity-50`}
              disabled={loading || selectedModels.size === 0}
            >
              <Plus size={18} />
              Import {selectedModels.size > 0 ? `${selectedModels.size} ` : ''}Models
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
