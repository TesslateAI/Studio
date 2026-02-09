import { useState, useEffect, useRef } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Package,
  Pencil,
  Power,
  Cpu,
  GitFork,
  LockSimpleOpen,
  LockKey,
  Sparkle,
  Check,
  XCircle,
  Rocket,
  Key,
  ChartLine,
  Plus,
  Trash,
  Eye,
  EyeSlash,
  Circle,
  CheckCircle,
  File,
  FileText,
  FilePlus,
  Terminal,
  Globe,
  ListChecks,
  Wrench,
  Folder,
  Storefront,
  Books,
  Sun,
  Moon,
  Gear,
  SignOut,
  Repeat,
} from '@phosphor-icons/react';
import { LoadingSpinner } from '../components/PulsingGridSpinner';
import {
  MobileMenu,
  MarkerEditor,
  MarkerPalette,
  UserDropdown,
  type MarkerEditorHandle,
} from '../components/ui';
import { ConfirmDialog, SubmitBaseModal } from '../components/modals';
import { ToolManagement } from '../components/ToolManagement';
import { ImageUpload } from '../components/ImageUpload';
import { marketplaceApi, secretsApi, usersApi, billingApi, authApi } from '../lib/api';
import toast from 'react-hot-toast';
import { useTheme } from '../theme/ThemeContext';

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
  avatar_url?: string | null;
  pricing_type: string;
  features: string[];
  tools?: string[] | null;
  tool_configs?: Record<
    string,
    { description?: string; examples?: string[]; system_prompt?: string }
  > | null;
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

type TabType = 'agents' | 'bases' | 'models' | 'api-keys' | 'subscriptions';

interface LibraryBase {
  id: string;
  name: string;
  slug: string;
  description: string;
  long_description?: string;
  git_repo_url: string;
  default_branch: string;
  category: string;
  icon: string;
  visibility: 'private' | 'public';
  tags?: string[];
  features?: string[];
  tech_stack?: string[];
  downloads: number;
  rating: number;
  created_at: string;
}

// All available tools in the system
const _ALL_TOOLS = [
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
  'web_fetch',
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
  const { theme, toggleTheme } = useTheme();
  const [searchParams] = useSearchParams();
  const tabParam = searchParams.get('tab') as TabType | null;
  const [activeTab, setActiveTab] = useState<TabType>(tabParam || 'agents');
  const [agents, setAgents] = useState<LibraryAgent[]>([]);
  const [bases, setBases] = useState<LibraryBase[]>([]);
  const [models, setModels] = useState<Model[]>([]);
  const [externalProviders, setExternalProviders] = useState<ExternalProvider[]>([]);
  const [apiKeys, setApiKeys] = useState<ApiKey[]>([]);
  const [showSubmitBaseModal, setShowSubmitBaseModal] = useState(false);
  const [editingBase, setEditingBase] = useState<LibraryBase | null>(null);

  // User state for dropdown
  const [userName, setUserName] = useState<string>('');
  const [userCredits, setUserCredits] = useState<number>(0);
  const [userTier, setUserTier] = useState<string>('free');

  const logout = () => {
    localStorage.removeItem('token');
    navigate('/login');
  };

  // Sidebar items for mobile menu
  const mobileMenuItems = {
    left: [
      {
        icon: <Folder className="w-5 h-5" weight="fill" />,
        title: 'Projects',
        onClick: () => navigate('/dashboard'),
      },
      {
        icon: <Storefront className="w-5 h-5" weight="fill" />,
        title: 'Marketplace',
        onClick: () => navigate('/marketplace'),
      },
      {
        icon: <Books className="w-5 h-5" weight="fill" />,
        title: 'Library',
        onClick: () => {},
        active: true,
      },
      {
        icon: <Package className="w-5 h-5" weight="fill" />,
        title: 'Components',
        onClick: () => toast('Components library coming soon!'),
      },
    ],
    right: [
      {
        icon:
          theme === 'dark' ? (
            <Sun className="w-5 h-5" weight="fill" />
          ) : (
            <Moon className="w-5 h-5" weight="fill" />
          ),
        title: theme === 'dark' ? 'Light Mode' : 'Dark Mode',
        onClick: toggleTheme,
      },
      {
        icon: <Gear className="w-5 h-5" weight="fill" />,
        title: 'Settings',
        onClick: () => navigate('/settings'),
      },
      {
        icon: <SignOut className="w-5 h-5" weight="fill" />,
        title: 'Logout',
        onClick: logout,
      },
    ],
  };
  const [providers, setProviders] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(true);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [editingAgent, setEditingAgent] = useState<LibraryAgent | null>(null);

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab]);

  // Fetch user data for dropdown
  useEffect(() => {
    const fetchUserData = async () => {
      try {
        const user = await authApi.getCurrentUser();
        setUserName(user.name || user.username || 'there');
        setUserCredits((user.bundled_credits || 0) + (user.purchased_credits || 0));
        setUserTier(user.subscription_tier || 'free');
      } catch (e) {
        console.error('Failed to fetch user data:', e);
      }
    };
    fetchUserData();
  }, []);

  const loadData = async () => {
    setLoading(true);
    try {
      if (activeTab === 'agents') {
        // Progressive loading: show agents immediately, load models in background
        await loadLibraryAgents();
        setLoading(false);
        loadModelsInBackground();
      } else if (activeTab === 'bases') {
        await loadCreatedBases();
        setLoading(false);
      } else if (activeTab === 'models') {
        await loadModels();
        setLoading(false);
      } else if (activeTab === 'api-keys') {
        await loadApiKeys();
        await loadProviders();
        setLoading(false);
      }
    } catch {
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

  const loadCreatedBases = async () => {
    try {
      const data = await marketplaceApi.getMyCreatedBases();
      setBases(data.bases || []);
    } catch (error) {
      console.error('Failed to load bases:', error);
      toast.error('Failed to load bases');
    }
  };

  const handleToggleBaseVisibility = async (base: LibraryBase) => {
    const newVisibility = base.visibility === 'public' ? 'private' : 'public';
    try {
      await marketplaceApi.setBaseVisibility(base.id, newVisibility);
      toast.success(`Base is now ${newVisibility}`);
      loadCreatedBases();
    } catch (error) {
      console.error('Failed to toggle visibility:', error);
      toast.error('Failed to change visibility');
    }
  };

  const handleDeleteBase = async (base: LibraryBase) => {
    try {
      await marketplaceApi.deleteBase(base.id);
      toast.success('Base deleted');
      loadCreatedBases();
    } catch (error) {
      console.error('Failed to delete base:', error);
      toast.error('Failed to delete base');
    }
  };

  const loadModels = async () => {
    setModelsLoading(true);
    try {
      const data = await marketplaceApi.getAvailableModels();
      setModels(data.models || []);
      setExternalProviders(data.external_providers || []);
    } catch (error) {
      console.error('Failed to load models:', error);
      toast.error('Failed to load models');
    } finally {
      setModelsLoading(false);
    }
  };

  const loadModelsInBackground = async () => {
    setModelsLoading(true);
    try {
      const data = await marketplaceApi.getAvailableModels();
      setModels(data.models || []);
      setExternalProviders(data.external_providers || []);
    } catch (error) {
      console.error('Failed to load models:', error);
      // Graceful degradation - no toast, just log (agents still work without models)
    } finally {
      setModelsLoading(false);
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
    } catch (error: unknown) {
      console.error('Publish toggle failed:', error);
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to toggle publish status');
    }
  };

  const handleModelChange = async (agent: LibraryAgent, model: string) => {
    try {
      // Optimistically update the UI
      setAgents((prevAgents) =>
        prevAgents.map((a) => (a.id === agent.id ? { ...a, selected_model: model } : a))
      );

      await marketplaceApi.selectAgentModel(agent.id, model);
      toast.success('Model updated successfully');

      // Reload to ensure consistency with backend
      await loadLibraryAgents();
    } catch (error: unknown) {
      console.error('Model change failed:', error);
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to change model');
      // Revert on error
      await loadLibraryAgents();
    }
  };

  if (loading) {
    return (
      <div className="h-screen flex items-center justify-center bg-[var(--bg)]">
        <LoadingSpinner message="Loading..." size={80} />
      </div>
    );
  }

  return (
    <>
      {/* Mobile Menu */}
      <MobileMenu leftItems={mobileMenuItems.left} rightItems={mobileMenuItems.right} />
      {/* Top Bar with Tabs */}
      <div className="bg-[var(--surface)] border-b border-white/10">
        <div className="h-12 flex items-center px-4 md:px-6 justify-between border-b border-white/10">
          <h1 className="font-heading text-sm font-semibold text-[var(--text)]">Library</h1>

          <div className="flex items-center gap-3">
            {/* User Dropdown */}
            <UserDropdown userName={userName} userCredits={userCredits} userTier={userTier} />

            {/* Mobile hamburger menu */}
            <button
              onClick={() => window.dispatchEvent(new Event('toggleMobileMenu'))}
              className="md:hidden p-2 hover:bg-white/10 active:bg-white/20 rounded-lg transition-colors"
            >
              <svg
                className="w-6 h-6 text-[var(--text)]"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M4 6h16M4 12h16M4 18h16"
                />
              </svg>
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div className="px-4 md:px-6 pb-3 pt-2">
          <div className="flex items-center gap-2 overflow-x-auto">
            <button
              onClick={() => setActiveTab('agents')}
              className={`px-3 py-1.5 text-xs font-medium transition-all rounded-lg flex items-center gap-2 whitespace-nowrap ${
                activeTab === 'agents'
                  ? 'bg-[var(--primary)] text-white'
                  : 'bg-white/5 text-[var(--text)]/60 hover:bg-white/10 hover:text-[var(--text)]'
              }`}
            >
              <Package size={16} weight={activeTab === 'agents' ? 'fill' : 'regular'} />
              Agents ({agents.length})
            </button>
            <button
              onClick={() => setActiveTab('bases')}
              className={`px-3 py-1.5 text-xs font-medium transition-all rounded-lg flex items-center gap-2 whitespace-nowrap ${
                activeTab === 'bases'
                  ? 'bg-[var(--primary)] text-white'
                  : 'bg-white/5 text-[var(--text)]/60 hover:bg-white/10 hover:text-[var(--text)]'
              }`}
            >
              <Rocket size={16} weight={activeTab === 'bases' ? 'fill' : 'regular'} />
              Bases ({bases.length})
            </button>
            <button
              onClick={() => setActiveTab('models')}
              className={`px-3 py-1.5 text-xs font-medium transition-all rounded-lg flex items-center gap-2 whitespace-nowrap ${
                activeTab === 'models'
                  ? 'bg-[var(--primary)] text-white'
                  : 'bg-white/5 text-[var(--text)]/60 hover:bg-white/10 hover:text-[var(--text)]'
              }`}
            >
              <Cpu size={16} weight={activeTab === 'models' ? 'fill' : 'regular'} />
              Model Management
            </button>
            <button
              onClick={() => setActiveTab('api-keys')}
              className={`px-3 py-1.5 text-xs font-medium transition-all rounded-lg flex items-center gap-2 whitespace-nowrap ${
                activeTab === 'api-keys'
                  ? 'bg-[var(--primary)] text-white'
                  : 'bg-white/5 text-[var(--text)]/60 hover:bg-white/10 hover:text-[var(--text)]'
              }`}
            >
              <Key size={16} weight={activeTab === 'api-keys' ? 'fill' : 'regular'} />
              API Keys ({apiKeys.length})
            </button>
            <button
              onClick={() => setActiveTab('subscriptions')}
              className={`px-3 py-1.5 text-xs font-medium transition-all rounded-lg flex items-center gap-2 whitespace-nowrap ${
                activeTab === 'subscriptions'
                  ? 'bg-[var(--primary)] text-white'
                  : 'bg-white/5 text-[var(--text)]/60 hover:bg-white/10 hover:text-[var(--text)]'
              }`}
            >
              <Repeat size={16} weight={activeTab === 'subscriptions' ? 'fill' : 'regular'} />
              Subscriptions
            </button>
          </div>
        </div>
      </div>

      {/* Scrollable Content */}
      <div className="flex-1 overflow-auto bg-[var(--bg)]">
        <div className="p-4 md:p-6">
          {activeTab === 'agents' && (
            <AgentsTab
              agents={agents}
              models={models}
              modelsLoading={modelsLoading}
              onToggleEnable={handleToggleEnable}
              onEdit={setEditingAgent}
              onTogglePublish={handleTogglePublish}
              onModelChange={handleModelChange}
              onReload={loadLibraryAgents}
            />
          )}

          {activeTab === 'bases' && (
            <BasesTab
              bases={bases}
              loading={loading}
              onSubmit={() => { setEditingBase(null); setShowSubmitBaseModal(true); }}
              onEdit={(base) => { setEditingBase(base); setShowSubmitBaseModal(true); }}
              onToggleVisibility={handleToggleBaseVisibility}
              onDelete={handleDeleteBase}
            />
          )}

          {activeTab === 'models' && (
            <ModelsTab
              models={models}
              externalProviders={externalProviders}
              onSetupProvider={() => setActiveTab('api-keys')}
            />
          )}

          {activeTab === 'api-keys' && (
            <ApiKeysTab apiKeys={apiKeys} providers={providers} onReload={loadApiKeys} />
          )}

          {activeTab === 'subscriptions' && <SubscriptionsTab />}
        </div>
      </div>

      {/* Edit Agent Modal */}
      {editingAgent && (
        <EditAgentModal
          agent={editingAgent}
          availableModels={[...new Set(models.map((m) => m.id))]}
          onClose={() => setEditingAgent(null)}
          onSave={async (updatedData) => {
            try {
              let response;
              if (!editingAgent.id || editingAgent.id === '') {
                // Creating a new agent
                const createData = {
                  name: updatedData.name || '',
                  description: updatedData.description || '',
                  system_prompt: updatedData.system_prompt || '',
                  mode: 'agent',
                  agent_type: 'IterativeAgent',
                  model: updatedData.model || (models.length > 0 ? models[0].id : ''),
                };
                response = await marketplaceApi.createCustomAgent(createData);

                // Update with additional fields (tools, tool_configs, avatar_url)
                if (updatedData.tools || updatedData.tool_configs || updatedData.avatar_url) {
                  await marketplaceApi.updateAgent(response.id, {
                    tools: updatedData.tools,
                    tool_configs: updatedData.tool_configs,
                    avatar_url: updatedData.avatar_url,
                  });
                }

                toast.success('Agent created successfully!');
              } else {
                // Updating existing agent
                response = await marketplaceApi.updateAgent(editingAgent.id, updatedData);
                if (response.forked) {
                  toast.success('Created a custom fork with your changes!');
                } else {
                  toast.success('Agent updated successfully');
                }
              }
              setEditingAgent(null);
              loadLibraryAgents();
            } catch (error: unknown) {
              console.error('Save failed:', error);
              const err = error as { response?: { data?: { detail?: string } } };
              toast.error(err.response?.data?.detail || 'Failed to save agent');
            }
          }}
        />
      )}

      {/* Submit/Edit Base Modal */}
      <SubmitBaseModal
        isOpen={showSubmitBaseModal}
        onClose={() => { setShowSubmitBaseModal(false); setEditingBase(null); }}
        onSuccess={loadCreatedBases}
        editBase={editingBase}
      />
    </>
  );
}

// Agents Tab Component
function AgentsTab({
  agents,
  models,
  modelsLoading,
  onToggleEnable,
  onEdit,
  onTogglePublish,
  onModelChange,
  onReload,
}: {
  agents: LibraryAgent[];
  models: Model[];
  modelsLoading: boolean;
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
          className="px-6 py-3 bg-[var(--primary)] hover:bg-[var(--primary)]/90 rounded-lg text-white transition-colors"
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
            {agents.filter((a) => a.is_enabled).length}
          </div>
          <div className="text-sm text-[var(--text)]/60">Active</div>
        </div>
        <div className="p-4 bg-white/5 border border-[var(--text)]/15 rounded-lg">
          <div className="text-2xl font-bold text-[var(--text)] mb-1">
            {agents.filter((a) => a.is_custom).length}
          </div>
          <div className="text-sm text-[var(--text)]/60">Custom</div>
        </div>
      </div>

      {/* Create New Agent Button */}
      <div className="mb-6">
        <button
          onClick={() => {
            const newAgent: LibraryAgent = {
              id: '',
              name: '',
              slug: '',
              description: '',
              category: 'general',
              mode: 'agent',
              agent_type: 'IterativeAgent',
              model: models.length > 0 ? models[0].id : '',
              source_type: 'open',
              is_forkable: false,
              icon: '🤖',
              avatar_url: null,
              pricing_type: 'free',
              features: [],
              tools: [],
              tool_configs: {},
              purchase_date: new Date().toISOString(),
              purchase_type: 'free',
              expires_at: null,
              is_custom: true,
              parent_agent_id: null,
              system_prompt: '',
              is_enabled: true,
              is_published: false,
              usage_count: 0,
            };
            onEdit(newAgent);
          }}
          disabled={modelsLoading}
          className={`px-4 py-2 ${modelsLoading ? 'bg-[var(--primary)]/50 cursor-wait' : 'bg-[var(--primary)] hover:bg-[var(--primary)]/90'} text-white rounded-lg transition-colors flex items-center gap-2`}
        >
          {modelsLoading ? (
            <>
              <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              Loading Models...
            </>
          ) : (
            <>
              <Plus size={18} />
              Create New Agent
            </>
          )}
        </button>
      </div>

      {/* Agents Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {agents.map((agent) => (
          <AgentCard
            key={agent.id}
            agent={agent}
            availableModels={[...new Set(models.map((m) => m.id))]}
            modelsLoading={modelsLoading}
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

// Bases Tab Component
function BasesTab({
  bases,
  loading,
  onSubmit,
  onEdit,
  onToggleVisibility,
  onDelete,
}: {
  bases: LibraryBase[];
  loading: boolean;
  onSubmit: () => void;
  onEdit: (base: LibraryBase) => void;
  onToggleVisibility: (base: LibraryBase) => void;
  onDelete: (base: LibraryBase) => void;
}) {
  const [deleteTarget, setDeleteTarget] = useState<LibraryBase | null>(null);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <LoadingSpinner />
      </div>
    );
  }

  return (
    <>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h3 className="text-sm font-semibold text-[var(--text)]">Your Base Templates</h3>
          <p className="text-xs text-[var(--text)]/50 mt-1">
            Submit and manage your project templates
          </p>
        </div>
        <button
          onClick={onSubmit}
          className="flex items-center gap-2 px-4 py-2 bg-[var(--primary)] text-white rounded-xl text-sm font-medium hover:opacity-90 transition-all"
        >
          <Plus size={16} />
          Submit Base
        </button>
      </div>

      {bases.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <div className="w-16 h-16 bg-white/5 rounded-2xl flex items-center justify-center mb-4">
            <Rocket size={32} className="text-[var(--text)]/30" />
          </div>
          <h3 className="text-lg font-semibold text-[var(--text)] mb-2">No bases yet</h3>
          <p className="text-sm text-[var(--text)]/50 max-w-sm mb-6">
            Submit your first base template by providing a git repository URL. Share your project
            templates with the community or keep them private.
          </p>
          <button
            onClick={onSubmit}
            className="flex items-center gap-2 px-5 py-2.5 bg-[var(--primary)] text-white rounded-xl text-sm font-medium hover:opacity-90 transition-all"
          >
            <Plus size={16} />
            Submit Your First Base
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {bases.map((base) => (
            <div
              key={base.id}
              className="bg-white/[0.03] border border-white/10 rounded-2xl p-5 hover:border-white/20 transition-all group"
            >
              {/* Header row */}
              <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-3">
                  <span className="text-2xl">{base.icon}</span>
                  <div>
                    <h4 className="text-sm font-semibold text-[var(--text)] line-clamp-1">
                      {base.name}
                    </h4>
                    <span className="text-xs text-[var(--text)]/40">{base.category}</span>
                  </div>
                </div>
                {/* Visibility badge */}
                <div
                  className={`flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${
                    base.visibility === 'public'
                      ? 'bg-green-500/20 text-green-400'
                      : 'bg-gray-500/20 text-gray-400'
                  }`}
                >
                  {base.visibility === 'public' ? (
                    <Globe size={10} />
                  ) : (
                    <LockKey size={10} />
                  )}
                  {base.visibility}
                </div>
              </div>

              {/* Description */}
              <p className="text-xs text-[var(--text)]/50 line-clamp-2 mb-3">{base.description}</p>

              {/* Tech stack tags */}
              {base.tech_stack && base.tech_stack.length > 0 && (
                <div className="flex flex-wrap gap-1 mb-3">
                  {base.tech_stack.slice(0, 4).map((tech) => (
                    <span
                      key={tech}
                      className="px-2 py-0.5 bg-white/5 rounded-md text-[10px] text-[var(--text)]/50"
                    >
                      {tech}
                    </span>
                  ))}
                </div>
              )}

              {/* Stats */}
              <div className="flex items-center gap-3 mb-4 text-xs text-[var(--text)]/40">
                <span>{base.downloads || 0} downloads</span>
                <span>{base.rating?.toFixed(1) || '5.0'} rating</span>
              </div>

              {/* Actions */}
              <div className="flex items-center gap-2">
                <button
                  onClick={() => onToggleVisibility(base)}
                  className="flex items-center gap-1 px-3 py-1.5 bg-white/5 border border-white/10 rounded-lg text-xs text-[var(--text)]/60 hover:bg-white/10 transition-all"
                  title={base.visibility === 'public' ? 'Make Private' : 'Make Public'}
                >
                  {base.visibility === 'public' ? <EyeSlash size={12} /> : <Eye size={12} />}
                  {base.visibility === 'public' ? 'Make Private' : 'Make Public'}
                </button>
                <button
                  onClick={() => onEdit(base)}
                  className="flex items-center gap-1 px-3 py-1.5 bg-white/5 border border-white/10 rounded-lg text-xs text-[var(--text)]/60 hover:bg-white/10 transition-all"
                >
                  <Pencil size={12} />
                  Edit
                </button>
                <button
                  onClick={() => setDeleteTarget(base)}
                  className="flex items-center gap-1 px-3 py-1.5 bg-red-500/10 border border-red-500/20 rounded-lg text-xs text-red-400 hover:bg-red-500/20 transition-all"
                >
                  <Trash size={12} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Delete confirmation */}
      <ConfirmDialog
        isOpen={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        onConfirm={() => {
          if (deleteTarget) {
            onDelete(deleteTarget);
            setDeleteTarget(null);
          }
        }}
        title="Delete Base"
        message={`Are you sure you want to delete "${deleteTarget?.name}"? This will remove it from the marketplace.`}
        confirmText="Delete"
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
  onSetupProvider,
}: {
  models: Model[];
  externalProviders: ExternalProvider[];
  onSetupProvider: (provider: string) => void;
}) {
  const [showAddCustomModel, setShowAddCustomModel] = useState(false);
  const [showAddApiKey, setShowAddApiKey] = useState(false);
  const [customModels, setCustomModels] = useState<Model[]>([]);
  const [systemModels, setSystemModels] = useState<Model[]>([]);
  const [diagramModel, setDiagramModel] = useState<string>('');
  const [loadingPreferences, setLoadingPreferences] = useState(true);
  const [openRouterKeys, setOpenRouterKeys] = useState<ApiKey[]>([]);
  const [loadingKeys, setLoadingKeys] = useState(true);
  const [providers, setProviders] = useState<Provider[]>([]);

  useEffect(() => {
    // Separate custom and system models
    setCustomModels(models.filter((m) => m.source === 'custom'));
    setSystemModels(models.filter((m) => m.source !== 'custom'));
  }, [models]);

  useEffect(() => {
    // Load user preferences
    loadUserPreferences();
    loadOpenRouterKeys();
    loadProviders();
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

  const handleDiagramModelChange = async (modelId: string) => {
    try {
      await usersApi.updatePreferences({ diagram_model: modelId });
      setDiagramModel(modelId);
      toast.success('Diagram generation model updated');
    } catch (error: unknown) {
      console.error('Failed to update diagram model:', error);
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to update diagram model');
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

  const openRouterProvider = externalProviders.find((p) => p.provider === 'openrouter');
  const hasOpenRouterKey = openRouterProvider?.has_key || openRouterKeys.length > 0;

  return (
    <div className="space-y-8">
      {/* BYOK (Bring Your Own Key) Section */}
      <div className="bg-gradient-to-r from-[var(--status-info)]/10 to-[var(--accent)]/10 border border-[var(--status-info)]/20 rounded-xl p-6">
        <div className="flex items-start gap-4 mb-4">
          <div className="p-3 bg-[var(--status-info)]/20 rounded-lg">
            <Key size={24} className="text-[var(--status-info)]" />
          </div>
          <div className="flex-1">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-3">
                <h2 className="text-xl font-bold text-[var(--text)]">Bring Your Own Key</h2>
                <span className="px-2.5 py-1 bg-[var(--status-success)]/10 border border-[var(--status-success)]/20 text-[var(--status-success)] text-xs font-semibold rounded-full">
                  FREE (Limited Time)
                </span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setShowAddApiKey(true)}
                  className="px-4 py-2 bg-[var(--status-info)]/10 hover:bg-[var(--status-info)]/20 border border-[var(--status-info)]/20 text-[var(--status-info)] rounded-lg transition-colors flex items-center gap-2"
                >
                  <Plus size={16} />
                  Add API Key
                </button>
                {hasOpenRouterKey && (
                  <button
                    onClick={() => setShowAddCustomModel(true)}
                    className="px-4 py-2 bg-[var(--primary)]/10 hover:bg-[var(--primary)]/20 border border-[var(--primary)]/20 text-[var(--primary)] rounded-lg transition-colors flex items-center gap-2"
                  >
                    <Plus size={16} />
                    Add Custom Model
                  </button>
                )}
              </div>
            </div>
            <p className="text-[var(--text)]/60 text-sm mb-4">
              Add your own API keys to use models from OpenRouter, OpenAI, Anthropic, Groq, and
              more.{' '}
              <span className="text-[var(--primary)] font-medium">
                Currently free for all users
              </span>{' '}
              — this will become a premium subscription feature in the future.
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
                      <div className="p-2 bg-[var(--status-success)]/10 rounded-lg">
                        <CheckCircle
                          size={16}
                          className="text-[var(--status-success)]"
                          weight="fill"
                        />
                      </div>
                      <div>
                        {key.key_name && (
                          <div className="text-sm font-medium text-[var(--text)]">
                            {key.key_name}
                          </div>
                        )}
                        <div className="text-xs text-[var(--text)]/40 font-mono">
                          {key.key_preview}
                        </div>
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
                      className="p-2 hover:bg-[var(--status-error)]/10 rounded-lg text-[var(--status-error)] transition-colors"
                    >
                      <Trash size={16} />
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <div className="px-4 py-3 bg-[var(--primary)]/10 border border-[var(--primary)]/20 rounded-lg flex items-center gap-2">
                <Circle size={16} className="text-[var(--primary)]" />
                <span className="text-sm text-[var(--primary)]">
                  No API key configured. Add one to get started.
                </span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Diagram Model Selection */}
      <div className="bg-gradient-to-r from-[var(--primary)]/10 to-[var(--accent)]/10 border border-[var(--primary)]/20 rounded-xl p-6">
        <div className="flex items-start gap-4 mb-4">
          <div className="p-3 bg-[var(--primary)]/20 rounded-lg">
            <ChartLine size={24} className="text-[var(--primary)]" />
          </div>
          <div className="flex-1">
            <div className="flex items-center gap-3 mb-2">
              <h2 className="text-xl font-bold text-[var(--text)]">
                Architecture Diagram Generation
              </h2>
              <span className="px-2.5 py-1 bg-[var(--status-success)]/10 border border-[var(--status-success)]/20 text-[var(--status-success)] text-xs font-semibold rounded-full">
                FREE (Limited Time)
              </span>
            </div>
            <p className="text-[var(--text)]/60 text-sm mb-4">
              Select which AI model to use for generating architecture diagrams of your projects.
              This model will analyze your code and create Mermaid diagrams showing component
              relationships.{' '}
              <span className="text-[var(--primary)] font-medium">
                Currently free for all users
              </span>{' '}
              — this feature will become paid in the future.
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
              className="w-full px-4 py-3 bg-[var(--surface)] border border-[var(--text)]/15 rounded-lg text-[var(--text)] focus:outline-none focus:border-[var(--primary)]/50 transition-colors [&>option]:bg-[var(--surface)] [&>option]:text-[var(--text)]"
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
            <div className="mt-3 px-3 py-2 bg-[var(--status-success)]/10 border border-[var(--status-success)]/20 rounded-lg flex items-center gap-2">
              <CheckCircle size={16} className="text-[var(--status-success)]" weight="fill" />
              <span className="text-xs text-[var(--status-success)]">
                Diagram generation configured with{' '}
                {models.find((m) => m.id === diagramModel)?.name || diagramModel}
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
                className="bg-[var(--surface)] border border-[var(--primary)]/20 rounded-lg p-4 hover:border-[var(--primary)]/40 transition-all"
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center gap-3 flex-1">
                    <div className="p-2 bg-[var(--primary)]/10 rounded-lg">
                      <Cpu size={24} className="text-[var(--primary)]" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <h3 className="font-semibold text-[var(--text)] truncate">{model.name}</h3>
                        <span className="px-2 py-0.5 bg-[var(--primary)]/20 text-[var(--primary)] text-xs rounded shrink-0">
                          Custom
                        </span>
                      </div>
                      <div className="flex items-center gap-2 mt-1">
                        <span className="text-xs text-[var(--text)]/40 capitalize">
                          {model.provider}
                        </span>
                      </div>
                    </div>
                  </div>
                  <button
                    onClick={() => model.custom_id && handleDeleteCustomModel(model.custom_id)}
                    className="p-2 hover:bg-[var(--status-error)]/10 rounded-lg text-[var(--status-error)] transition-colors shrink-0"
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
            <div className="flex items-center gap-3 mb-1">
              <h2 className="text-2xl font-bold text-[var(--text)]">Available Models</h2>
              <span className="px-2.5 py-1 bg-[var(--status-success)]/10 border border-[var(--status-success)]/20 text-[var(--status-success)] text-xs font-semibold rounded-full">
                FREE (Limited Time)
              </span>
            </div>
            <p className="text-[var(--text)]/60">
              <span className="text-[var(--primary)] font-medium">
                Currently free for all users
              </span>{' '}
              — these models will become paid features in the future. Use them now while they're
              complimentary!
            </p>
          </div>
          <div className="text-sm text-[var(--text)]/40">
            {systemModels.length} models available
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {systemModels.map((model) => (
            <div
              key={model.id}
              className="bg-[var(--surface)] border border-[var(--text)]/15 rounded-lg p-4 hover:border-[var(--primary)]/30 transition-all"
            >
              <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-3">
                  <div className="p-2 bg-[var(--status-info)]/10 rounded-lg">
                    <Cpu size={24} className="text-[var(--status-info)]" />
                  </div>
                  <div>
                    <h3 className="font-semibold text-[var(--text)]">{model.name}</h3>
                    <div className="flex items-center gap-2 mt-1">
                      <span className="text-xs text-[var(--text)]/40 capitalize">
                        {model.provider}
                      </span>
                      {model.pricing.input === 0 && model.pricing.output === 0 && (
                        <span className="px-2 py-0.5 bg-[var(--status-success)]/20 text-[var(--status-success)] text-xs rounded">
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
                    <div className="text-xs text-[var(--primary)]">
                      {provider.models_count} models
                    </div>
                  </div>
                  {provider.has_key ? (
                    <CheckCircle size={20} className="text-[var(--status-success)]" weight="fill" />
                  ) : (
                    <Circle size={20} className="text-[var(--text)]/20" />
                  )}
                </div>

                {provider.setup_required && (
                  <button
                    onClick={() => onSetupProvider(provider.provider)}
                    className="w-full mt-3 px-4 py-2 bg-[var(--primary)]/10 hover:bg-[var(--primary)]/20 border border-[var(--primary)]/20 text-[var(--primary)] rounded-lg transition-colors flex items-center justify-center gap-2"
                  >
                    <Key size={16} />
                    Add API Key
                  </button>
                )}

                {provider.has_key && (
                  <div className="mt-3 px-3 py-2 bg-[var(--status-success)]/10 border border-[var(--status-success)]/20 rounded-lg flex items-center justify-center gap-2">
                    <CheckCircle size={16} className="text-[var(--status-success)]" weight="fill" />
                    <span className="text-xs text-[var(--status-success)]">Configured</span>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Add API Key Modal - Shows all LLM providers */}
      {showAddApiKey && (
        <AddApiKeyModal
          providers={providers.filter((p) => p.requires_key)}
          onClose={() => setShowAddApiKey(false)}
          onSuccess={() => {
            setShowAddApiKey(false);
            loadOpenRouterKeys();
            // Reload to update all provider statuses
            window.location.reload();
          }}
        />
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
  onReload,
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
          className="px-4 py-2 bg-[var(--primary)] hover:bg-[var(--primary)]/90 rounded-lg text-white transition-colors flex items-center gap-2"
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
            className="px-6 py-3 bg-[var(--primary)] hover:bg-[var(--primary)]/90 rounded-lg text-white transition-colors"
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
        <div className="p-3 bg-[var(--accent)]/10 rounded-lg">
          <Key size={20} className="text-[var(--accent)]" />
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
        className="p-2 hover:bg-[var(--status-error)]/10 rounded-lg text-[var(--status-error)] transition-colors"
      >
        <Trash size={18} />
      </button>

      {/* Delete Confirmation */}
      {showDelete && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50">
          <div className="bg-[var(--surface)] border border-[var(--text)]/15 rounded-lg p-6 max-w-md">
            <h3 className="text-lg font-semibold text-[var(--text)] mb-4">Delete API Key?</h3>
            <p className="text-[var(--text)]/60 mb-6">
              Are you sure you want to delete this {apiKey.provider} API key? This action cannot be
              undone.
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
                className="px-4 py-2 bg-[var(--status-error)] hover:bg-[var(--status-error)]/90 rounded-lg text-white transition-colors"
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
  onSuccess,
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
    } catch (error: unknown) {
      console.error('Add API key failed:', error);
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
              className="w-full px-4 py-2 bg-white/5 border border-[var(--text)]/15 rounded-lg text-[var(--text)] focus:outline-none focus:border-[var(--primary)]/50"
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
              className="px-6 py-2 bg-[var(--primary)] hover:bg-[var(--primary)]/90 rounded-lg text-white transition-colors flex items-center gap-2 disabled:opacity-50"
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
function AgentCardModelSkeleton() {
  return (
    <div className="w-full px-3 py-2 bg-[var(--status-info)]/10 border border-[var(--status-info)]/20 rounded-lg animate-pulse">
      <div className="h-4 bg-[var(--status-info)]/20 rounded w-3/4"></div>
    </div>
  );
}

function AgentCard({
  agent,
  availableModels,
  modelsLoading,
  onToggleEnable,
  onEdit,
  onTogglePublish,
  onModelChange,
  onRemove,
}: {
  agent: LibraryAgent;
  availableModels: string[];
  modelsLoading: boolean;
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
    <div
      className={`relative bg-[var(--surface)] border rounded-2xl p-6 transition-all ${
        agent.is_enabled
          ? 'border-[var(--text)]/15 hover:border-[var(--primary)]/30'
          : 'border-white/5 opacity-60'
      }`}
    >
      {/* Status Badge - Top Right */}
      <div className="absolute top-4 right-4">
        {agent.is_enabled ? (
          <span className="px-2.5 py-1 bg-[var(--status-success)]/20 text-[var(--status-success)] text-xs rounded-md font-medium">
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
        {agent.avatar_url ? (
          <img
            src={agent.avatar_url}
            alt={agent.name}
            className="w-16 h-16 rounded-xl object-cover border-2 border-[var(--text)]/10"
          />
        ) : (
          <div className="w-16 h-16 rounded-xl bg-[var(--surface)] border-2 border-[var(--text)]/10 flex items-center justify-center p-3">
            <img src="/favicon.svg" alt="Tesslate" className="w-full h-full" />
          </div>
        )}
        <div className="flex-1">
          <h3 className="font-heading font-bold text-[var(--text)] text-xl mb-2">{agent.name}</h3>
          <div className="flex flex-wrap items-center gap-2">
            {agent.source_type === 'open' ? (
              <span className="flex items-center gap-1 px-2 py-0.5 bg-[var(--status-success)]/20 text-[var(--status-success)] text-xs rounded">
                <LockSimpleOpen size={10} />
                Open Source
              </span>
            ) : (
              <span className="flex items-center gap-1 px-2 py-0.5 bg-[var(--accent)]/20 text-[var(--accent)] text-xs rounded">
                <LockKey size={10} />
                Closed Source
              </span>
            )}
            {agent.is_custom && (
              <span className="flex items-center gap-1 px-2 py-0.5 bg-[var(--primary)]/20 text-[var(--primary)] text-xs rounded">
                <GitFork size={10} />
                Custom
              </span>
            )}
            {agent.parent_agent_id && (
              <span className="flex items-center gap-1 px-2 py-0.5 bg-[var(--status-info)]/20 text-[var(--status-info)] text-xs rounded">
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
          modelsLoading ? (
            <AgentCardModelSkeleton />
          ) : (
            <div className="relative">
              <select
                value={currentModel}
                onChange={(e) => onModelChange(e.target.value)}
                className="w-full px-3 py-2 pl-8 bg-[var(--status-info)]/10 border border-[var(--status-info)]/20 rounded-lg text-[var(--status-info)] text-xs font-medium focus:outline-none focus:border-[var(--status-info)]/40 hover:bg-[var(--status-info)]/15 transition-colors cursor-pointer appearance-none pr-8 [&>option]:bg-[var(--surface)] [&>option]:text-[var(--text)]"
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
              <Cpu
                size={14}
                className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--status-info)] pointer-events-none"
              />
              <div className="absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none text-[var(--status-info)]">
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                  <path
                    d="M3 4.5L6 7.5L9 4.5"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </div>
            </div>
          )
        ) : (
          <div className="flex items-center gap-2 px-3 py-1.5 bg-[var(--status-info)]/10 border border-[var(--status-info)]/20 rounded-lg w-fit">
            <Cpu size={14} className="text-[var(--status-info)]" />
            <span className="text-xs text-[var(--status-info)] font-medium">
              {currentModel || 'Model not disclosed (closed source)'}
            </span>
          </div>
        )}
      </div>

      {/* Tools */}
      <div className="mb-4">
        <div className="flex flex-wrap gap-1.5">
          {!agent.tools || agent.tools.length === 0 ? (
            <div className="flex items-center gap-1 px-2 py-1 bg-[var(--status-info)]/10 border border-[var(--status-info)]/20 text-[var(--status-info)] text-xs rounded-md font-medium">
              <Wrench size={12} />
              <span>All Tools</span>
            </div>
          ) : (
            agent.tools.map((toolName, idx) => {
              const tool = getToolIcon(toolName);
              if (!tool) return null;
              return (
                <div
                  key={idx}
                  className="flex items-center gap-1 px-2 py-1 bg-[var(--primary)]/10 border border-[var(--primary)]/20 text-[var(--primary)] text-xs rounded-md font-medium"
                  title={tool.label}
                >
                  {tool.icon}
                  <span>{tool.label}</span>
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* Features */}
      <div className="flex flex-wrap gap-2 mb-4">
        {(agent.features || []).slice(0, 3).map((feature, idx) => (
          <span key={idx} className="px-2 py-1 bg-white/5 text-[var(--text)]/60 text-xs rounded">
            {feature}
          </span>
        ))}
      </div>

      {/* Actions */}
      <div className="flex items-center gap-2 pt-4 border-t border-[var(--text)]/15">
        {canEdit && (
          <button
            onClick={onEdit}
            className="flex-1 py-2 px-3 bg-[var(--primary)]/10 hover:bg-[var(--primary)]/20 border border-[var(--primary)]/20 text-[var(--primary)] rounded-lg transition-colors flex items-center justify-center gap-2"
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
                ? 'bg-[var(--status-info)]/10 hover:bg-[var(--status-info)]/20 border border-[var(--status-info)]/20 text-[var(--status-info)]'
                : 'bg-[var(--accent)]/10 hover:bg-[var(--accent)]/20 border border-[var(--accent)]/20 text-[var(--accent)]'
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
              ? 'bg-[var(--status-error)]/10 hover:bg-[var(--status-error)]/20 border border-[var(--status-error)]/20 text-[var(--status-error)]'
              : 'bg-[var(--status-success)]/10 hover:bg-[var(--status-success)]/20 border border-[var(--status-success)]/20 text-[var(--status-success)]'
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
          className="w-full py-2 px-3 bg-white/5 hover:bg-[var(--status-error)]/10 border border-[var(--text)]/15 hover:border-[var(--status-error)]/20 text-[var(--text)]/60 hover:text-[var(--status-error)] rounded-lg transition-colors flex items-center justify-center gap-2"
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
  onSave,
}: {
  agent: LibraryAgent;
  availableModels: string[];
  onClose: () => void;
  onSave: (data: {
    name?: string;
    description?: string;
    system_prompt?: string;
    model?: string;
    tools?: string[];
    tool_configs?: Record<
      string,
      { description?: string; examples?: string[]; system_prompt?: string }
    >;
    avatar_url?: string | null;
  }) => void;
}) {
  const [name, setName] = useState(agent.name);
  const [description, setDescription] = useState(agent.description);
  const [systemPrompt, setSystemPrompt] = useState(agent.system_prompt || '');
  const currentModel = agent.selected_model || agent.model;
  const [model, setModel] = useState(currentModel);
  const [originalPrompt] = useState(agent.system_prompt || '');
  const [tools, setTools] = useState<string[]>(agent.tools || []);
  const [toolConfigs, setToolConfigs] = useState<
    Record<string, { description?: string; examples?: string[]; system_prompt?: string }>
  >(agent.tool_configs || {});
  const [avatarUrl, setAvatarUrl] = useState<string | null>(agent.avatar_url || null);
  const editorRef = useRef<MarkerEditorHandle>(null);

  const handleReset = () => {
    setSystemPrompt(originalPrompt);
    toast.success('Reset to original system prompt');
  };

  const insertMarker = (marker: string) => {
    editorRef.current?.insertMarker(marker);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSave({
      name,
      description,
      system_prompt: systemPrompt,
      model,
      tools,
      tool_configs: toolConfigs,
      avatar_url: avatarUrl,
    });
  };

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-[var(--surface)] border border-[var(--text)]/15 rounded-xl max-w-3xl lg:max-w-6xl w-full p-6 max-h-[90vh] overflow-y-auto">
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
          {/* Two-column layout on desktop */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Left Column: Basic Info & System Prompt */}
            <div className="space-y-4">
              {/* Logo Upload */}
              <div>
                <label className="block text-sm font-medium text-[var(--text)] mb-2">
                  Agent Logo
                </label>
                <ImageUpload value={avatarUrl} onChange={setAvatarUrl} maxSizeKB={200} />
              </div>

              <div>
                <label className="block text-sm font-medium text-[var(--text)] mb-2">
                  Agent Name
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="w-full px-4 py-2 bg-white/5 border border-[var(--text)]/15 rounded-lg text-[var(--text)] focus:outline-none focus:border-[var(--primary)]/50"
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
                  className="w-full px-4 py-2 bg-white/5 border border-[var(--text)]/15 rounded-lg text-[var(--text)] focus:outline-none focus:border-[var(--primary)]/50"
                  required
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-[var(--text)] mb-2">Model</label>
                <select
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  className="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--text)]/15 rounded-lg text-[var(--text)] focus:outline-none focus:border-[var(--primary)]/50 [&>option]:bg-[var(--surface)] [&>option]:text-[var(--text)]"
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
                      className="px-3 py-1 bg-[var(--status-info)]/10 hover:bg-[var(--status-info)]/20 border border-[var(--status-info)]/20 text-[var(--status-info)] text-xs rounded transition-colors"
                    >
                      Reset to Default
                    </button>
                  )}
                </div>

                {/* Rich text editor with inline marker pills */}
                <MarkerEditor
                  ref={editorRef}
                  value={systemPrompt}
                  onChange={setSystemPrompt}
                  rows={12}
                  placeholder="Enter your agent's system prompt..."
                />
                <p className="mt-1 text-xs text-[var(--text)]/40">
                  {systemPrompt.length} characters • Markers appear as pills and show descriptions
                  on hover
                </p>

                {/* Marker Palette */}
                <div className="mt-4 p-4 bg-[var(--text)]/5 rounded-lg border border-[var(--text)]/10">
                  <h3 className="text-sm font-semibold text-[var(--text)] mb-3">
                    Available Markers
                  </h3>
                  <MarkerPalette onInsertMarker={insertMarker} />
                </div>
              </div>
            </div>

            {/* Right Column: Tool Management */}
            <div className="space-y-4">
              <div className="p-4 bg-[var(--text)]/5 rounded-lg border border-[var(--text)]/10">
                <ToolManagement
                  selectedTools={tools}
                  toolConfigs={toolConfigs}
                  onToolsChange={(newTools, newConfigs) => {
                    setTools(newTools);
                    setToolConfigs(newConfigs);
                  }}
                  availableModels={availableModels}
                />
              </div>
            </div>
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
              className="px-6 py-2 bg-[var(--primary)] hover:bg-[var(--primary)]/90 rounded-lg text-white transition-colors flex items-center gap-2"
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
  onSuccess,
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
        pricing_output: pricingOutput ? parseFloat(pricingOutput) : undefined,
      });
      onSuccess();
    } catch (error: unknown) {
      console.error('Add custom model failed:', error);
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to add custom model');
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
            <label className="block text-sm font-medium text-[var(--text)] mb-2">Model ID</label>
            <input
              type="text"
              value={modelId}
              onChange={(e) => setModelId(e.target.value)}
              className="w-full px-4 py-2 bg-white/5 border border-[var(--text)]/15 rounded-lg text-[var(--text)] focus:outline-none focus:border-[var(--primary)]/50 font-mono text-sm"
              placeholder="openrouter/model-name"
              required
            />
            <p className="mt-1 text-xs text-[var(--text)]/40">Find model IDs at openrouter.ai</p>
          </div>

          <div>
            <label className="block text-sm font-medium text-[var(--text)] mb-2">
              Display Name
            </label>
            <input
              type="text"
              value={modelName}
              onChange={(e) => setModelName(e.target.value)}
              className="w-full px-4 py-2 bg-white/5 border border-[var(--text)]/15 rounded-lg text-[var(--text)] focus:outline-none focus:border-[var(--primary)]/50"
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
                className="w-full px-4 py-2 bg-white/5 border border-[var(--text)]/15 rounded-lg text-[var(--text)] focus:outline-none focus:border-[var(--primary)]/50"
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
                className="w-full px-4 py-2 bg-white/5 border border-[var(--text)]/15 rounded-lg text-[var(--text)] focus:outline-none focus:border-[var(--primary)]/50"
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
              className="px-6 py-2 bg-[var(--primary)] hover:bg-[var(--primary)]/90 rounded-lg text-white transition-colors flex items-center gap-2 disabled:opacity-50"
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

// Subscriptions Tab Component
function SubscriptionsTab() {
  const [loading, setLoading] = useState(true);
  const [premiumSubscription, setPremiumSubscription] = useState<Record<string, unknown> | null>(
    null
  );
  const [agentSubscriptions, setAgentSubscriptions] = useState<Array<Record<string, unknown>>>([]);
  const [cancelingId, setCancelingId] = useState<string | null>(null);

  useEffect(() => {
    loadSubscriptions();
  }, []);

  const loadSubscriptions = async () => {
    setLoading(true);
    try {
      // Load premium subscription status
      const subscription = await billingApi.getSubscription();
      console.log('DEBUG: Premium subscription data:', subscription);
      console.log('DEBUG: cancel_at_period_end:', subscription?.cancel_at_period_end);
      console.log('DEBUG: current_period_start:', subscription?.current_period_start);
      console.log('DEBUG: current_period_end:', subscription?.current_period_end);
      setPremiumSubscription(subscription);

      // Load agent subscriptions
      const agents = await marketplaceApi.getUserSubscriptions();
      console.log('DEBUG: Agent subscriptions loaded:', agents);
      agents.forEach((agent, idx) => {
        console.log(`DEBUG: Agent ${idx}:`, {
          name: agent.name,
          purchase_type: agent.purchase_type,
          subscription_id: agent.subscription_id,
        });
      });
      setAgentSubscriptions(agents);
    } catch (error) {
      console.error('Failed to load subscriptions:', error);
      toast.error('Failed to load subscriptions');
    } finally {
      setLoading(false);
    }
  };

  const handleCancelSubscription = async (subscriptionId: string, type: 'premium' | 'agent') => {
    console.log('DEBUG: handleCancelSubscription called:', { subscriptionId, type });

    if (!subscriptionId) {
      console.error('DEBUG: No subscription ID provided!');
      toast.error('Cannot cancel: Missing subscription ID');
      return;
    }

    if (
      !confirm(
        `Are you sure you want to cancel this subscription? You'll continue to have access until the end of your billing period.`
      )
    ) {
      return;
    }

    setCancelingId(subscriptionId);
    try {
      if (type === 'premium') {
        console.log('DEBUG: Cancelling premium subscription');
        await billingApi.cancelSubscription();
        toast.success('Premium subscription cancelled');
      } else {
        console.log('DEBUG: Cancelling agent subscription:', subscriptionId);
        await marketplaceApi.cancelAgentSubscription(subscriptionId);
        toast.success('Agent subscription cancelled');
      }
      await loadSubscriptions();
    } catch (error: unknown) {
      console.error('Failed to cancel subscription:', error);
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to cancel subscription');
    } finally {
      setCancelingId(null);
    }
  };

  const handleRenewSubscription = async (subscriptionId: string, type: 'premium' | 'agent') => {
    console.log('DEBUG: handleRenewSubscription called:', { subscriptionId, type });

    if (!subscriptionId) {
      console.error('DEBUG: No subscription ID provided!');
      toast.error('Cannot renew: Missing subscription ID');
      return;
    }

    if (
      !confirm(
        `Are you sure you want to renew this subscription? It will continue automatically after the current period.`
      )
    ) {
      return;
    }

    setCancelingId(subscriptionId);
    try {
      if (type === 'premium') {
        console.log('DEBUG: Renewing premium subscription');
        await billingApi.renewSubscription();
        toast.success('Premium subscription renewed');
      } else {
        console.log('DEBUG: Renewing agent subscription:', subscriptionId);
        await marketplaceApi.renewAgentSubscription(subscriptionId);
        toast.success('Agent subscription renewed');
      }
      await loadSubscriptions();
    } catch (error: unknown) {
      console.error('Failed to renew subscription:', error);
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to renew subscription');
    } finally {
      setCancelingId(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <LoadingSpinner />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Premium Subscription */}
      <div>
        <h2 className="text-lg font-semibold mb-4" style={{ color: 'var(--text)' }}>
          <div className="flex items-center gap-2">
            <Sparkle size={20} weight="fill" className="text-[var(--primary)]" />
            Premium Subscription
          </div>
        </h2>

        {premiumSubscription?.tier === 'pro' ? (
          <div
            className="rounded-xl p-6 border"
            style={{
              backgroundColor: 'var(--surface)',
              borderColor: 'rgba(255, 107, 0, 0.2)',
            }}
          >
            <div className="flex items-start justify-between">
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-2">
                  <CheckCircle size={20} weight="fill" className="text-[var(--status-success)]" />
                  <span className="font-medium" style={{ color: 'var(--text)' }}>
                    Active Premium Subscription
                  </span>
                </div>

                {/* Subscription dates */}
                <div
                  className="mb-3 text-sm space-y-1"
                  style={{ color: 'var(--text)', opacity: 0.7 }}
                >
                  {premiumSubscription.current_period_start && (
                    <div>
                      Started:{' '}
                      {new Date(premiumSubscription.current_period_start).toLocaleDateString()}
                    </div>
                  )}
                  {premiumSubscription.cancel_at_period_end &&
                  premiumSubscription.current_period_end ? (
                    <div className="text-[var(--primary)]">
                      Cancels on:{' '}
                      {new Date(premiumSubscription.current_period_end).toLocaleDateString()} (
                      {Math.ceil(
                        (new Date(premiumSubscription.current_period_end).getTime() - Date.now()) /
                          (1000 * 60 * 60 * 24)
                      )}{' '}
                      days remaining)
                    </div>
                  ) : premiumSubscription.current_period_end ? (
                    <div>
                      Renews:{' '}
                      {new Date(premiumSubscription.current_period_end).toLocaleDateString()}
                    </div>
                  ) : null}
                </div>

                <div className="space-y-2 text-sm" style={{ color: 'var(--text)', opacity: 0.8 }}>
                  <div className="flex items-center gap-2">
                    <Check size={16} className="text-[var(--status-success)]" />
                    <span>5 projects & deploys</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Check size={16} className="text-[var(--status-success)]" />
                    <span>24/7 running mode</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Check size={16} className="text-[var(--status-success)]" />
                    <span>Use your own API keys</span>
                  </div>
                </div>
              </div>

              {!premiumSubscription.cancel_at_period_end ? (
                <button
                  onClick={() =>
                    handleCancelSubscription(premiumSubscription.subscription_id, 'premium')
                  }
                  disabled={cancelingId === premiumSubscription.subscription_id}
                  className="px-4 py-2 text-sm font-medium text-[var(--status-error)] hover:bg-[var(--status-error)]/10 rounded-lg transition disabled:opacity-50"
                >
                  {cancelingId === premiumSubscription.subscription_id ? 'Canceling...' : 'Cancel'}
                </button>
              ) : (
                <button
                  onClick={() =>
                    handleRenewSubscription(premiumSubscription.subscription_id, 'premium')
                  }
                  disabled={cancelingId === premiumSubscription.subscription_id}
                  className="px-4 py-2 text-sm font-medium text-[var(--status-success)] hover:bg-[var(--status-success)]/10 rounded-lg transition disabled:opacity-50"
                >
                  {cancelingId === premiumSubscription.subscription_id ? 'Renewing...' : 'Renew'}
                </button>
              )}
            </div>
          </div>
        ) : (
          <div
            className="rounded-xl p-6 border text-center"
            style={{
              backgroundColor: 'var(--surface)',
              borderColor: 'rgba(255, 255, 255, 0.1)',
            }}
          >
            <p className="text-sm mb-4" style={{ color: 'var(--text)', opacity: 0.7 }}>
              You're on the free plan
            </p>
            <button
              onClick={() => (window.location.href = '/settings/billing')}
              className="px-6 py-2 bg-gradient-to-r from-[var(--primary)] to-[var(--primary-hover)] hover:from-[var(--primary-hover)] hover:to-[var(--primary)] text-white rounded-lg transition font-medium text-sm"
            >
              Upgrade Plan
            </button>
          </div>
        )}
      </div>

      {/* Agent Subscriptions & Purchases */}
      <div>
        <h2 className="text-lg font-semibold mb-4" style={{ color: 'var(--text)' }}>
          <div className="flex items-center gap-2">
            <Package size={20} weight="fill" />
            Purchased Agents & Subscriptions
          </div>
        </h2>

        {agentSubscriptions.length === 0 ? (
          <div
            className="rounded-xl p-8 border text-center"
            style={{
              backgroundColor: 'var(--surface)',
              borderColor: 'rgba(255, 255, 255, 0.1)',
            }}
          >
            <Package
              size={48}
              weight="fill"
              style={{ color: 'var(--text)', opacity: 0.3 }}
              className="mx-auto mb-3"
            />
            <p className="text-sm" style={{ color: 'var(--text)', opacity: 0.7 }}>
              No purchased agents yet
            </p>
            <button
              onClick={() => (window.location.href = '/marketplace')}
              className="mt-4 px-6 py-2 bg-white/5 hover:bg-white/10 text-white rounded-lg transition font-medium text-sm"
            >
              Browse Marketplace
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {agentSubscriptions.map((sub) => {
              const isSubscription =
                (sub.purchase_type === 'monthly' || sub.purchase_type === 'subscription') &&
                sub.subscription_id;
              const isOneTime = sub.purchase_type === 'onetime' || sub.purchase_type === 'one_time';

              return (
                <div
                  key={sub.id}
                  className="rounded-xl p-4 border"
                  style={{
                    backgroundColor: 'var(--surface)',
                    borderColor: 'rgba(255, 255, 255, 0.1)',
                  }}
                >
                  <div className="flex items-start justify-between mb-3">
                    <div className="flex items-center gap-3">
                      <div className="text-2xl">{sub.icon || '🤖'}</div>
                      <div>
                        <h3 className="font-medium" style={{ color: 'var(--text)' }}>
                          {sub.name}
                        </h3>
                        <p className="text-xs" style={{ color: 'var(--text)', opacity: 0.6 }}>
                          {isSubscription
                            ? `$${(sub.price / 100).toFixed(2)}/month`
                            : `$${(sub.price / 100).toFixed(2)} (One-time)`}
                        </p>
                      </div>
                    </div>
                    {isSubscription && !sub.cancel_at_period_end && (
                      <button
                        onClick={() => handleCancelSubscription(sub.subscription_id, 'agent')}
                        disabled={cancelingId === sub.subscription_id}
                        className="p-2 text-[var(--status-error)] hover:bg-[var(--status-error)]/10 rounded-lg transition disabled:opacity-50"
                        title="Cancel subscription"
                      >
                        <XCircle size={20} />
                      </button>
                    )}
                    {isSubscription && sub.cancel_at_period_end && (
                      <button
                        onClick={() => handleRenewSubscription(sub.subscription_id, 'agent')}
                        disabled={cancelingId === sub.subscription_id}
                        className="p-2 text-[var(--status-success)] hover:bg-[var(--status-success)]/10 rounded-lg transition disabled:opacity-50"
                        title="Renew subscription"
                      >
                        <CheckCircle size={20} />
                      </button>
                    )}
                  </div>

                  <div className="text-xs space-y-1" style={{ color: 'var(--text)', opacity: 0.7 }}>
                    <div>Purchased: {new Date(sub.purchase_date).toLocaleDateString()}</div>
                    <div className="flex items-center gap-1">
                      <CheckCircle size={12} className="text-[var(--status-success)]" />
                      <span>{isSubscription ? 'Active Subscription' : 'Owned'}</span>
                    </div>
                    {/* Show cancellation info for monthly subscriptions */}
                    {isSubscription && sub.cancel_at_period_end && sub.current_period_end && (
                      <div className="text-[var(--primary)] font-medium">
                        Cancels: {new Date(sub.current_period_end).toLocaleDateString()}(
                        {Math.ceil(
                          (new Date(sub.current_period_end).getTime() - Date.now()) /
                            (1000 * 60 * 60 * 24)
                        )}{' '}
                        days left)
                      </div>
                    )}
                    {/* Show renewal date for active monthly subscriptions */}
                    {isSubscription && !sub.cancel_at_period_end && sub.current_period_end && (
                      <div>Renews: {new Date(sub.current_period_end).toLocaleDateString()}</div>
                    )}
                    {isOneTime && sub.expires_at && (
                      <div className="text-xs" style={{ color: 'var(--text)', opacity: 0.6 }}>
                        Access until: {new Date(sub.expires_at).toLocaleDateString()}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
