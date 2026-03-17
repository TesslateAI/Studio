import { useState, useEffect, useRef } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Package,
  Pencil,
  Power,
  GitFork,
  LockSimpleOpen,
  LockKey,
  Check,
  XCircle,
  Rocket,
  Key,
  Cpu,
  Plus,
  Trash,
  Eye,
  EyeSlash,
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
  ChatCircleDots,
  Article,
  CaretDown,
  CaretRight,
  Robot,
  ToggleLeft,
  ToggleRight,
  Plugs,
  PaintBrush,
  X,
  Info,
  MagnifyingGlass,
  Lightning,
  GithubLogo,
  Code,
  PaintBucket,
  Broadcast,
  TestTube,
  Database,
  Shield,
  FilmStrip,
  Sparkle,
  Stack,
  ArrowSquareOut,
} from '@phosphor-icons/react';
import { LoadingSpinner } from '../components/PulsingGridSpinner';
import { ModelSelector } from '../components/chat/ModelSelector';
import {
  MobileMenu,
  MarkerEditor,
  MarkerPalette,
  UserDropdown,
  type MarkerEditorHandle,
} from '../components/ui';
import { ConfirmDialog, SubmitBaseModal } from '../components/modals';
import {
  CustomProviderCard,
  CustomProviderModal,
  type CustomProvider,
} from '../components/settings/CustomProviderComponents';
import { ToolManagement } from '../components/ToolManagement';
import { ImageUpload } from '../components/ImageUpload';
import { marketplaceApi, secretsApi, billingApi } from '../lib/api';
import toast from 'react-hot-toast';
import { useTheme } from '../theme/ThemeContext';
import { motion } from 'framer-motion';
import { Badge, CardSurface, CardHeader, CardActions, StatusDot, StatCard, staggerContainer, staggerItem } from '../components/cards';

/** Convert USD per 1M tokens to credits (1 credit = $0.01) */
function formatCreditsPerMillion(usdPer1M: number): string {
  const credits = usdPer1M * 100;
  if (credits === 0) return '0';
  if (Number.isInteger(credits)) return credits.toLocaleString();
  return credits.toFixed(1);
}

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
  config?: {
    features?: Record<string, boolean>;
    [key: string]: unknown;
  };
  is_enabled?: boolean;
  is_published?: boolean;
  usage_count?: number;
  creator_type?: 'official' | 'community';
  creator_name?: string;
  creator_username?: string | null;
  creator_avatar_url?: string | null;
  created_by_user_id?: string | null;
  forked_by_user_id?: string | null;
}

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

type TabType = 'agents' | 'bases' | 'skills' | 'mcp_servers' | 'themes' | 'models';

interface ModelInfo {
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

interface LibraryTheme {
  id: string;
  name: string;
  slug: string;
  description: string;
  mode: string;
  author: string;
  creator_username?: string | null;
  icon: string;
  category: string;
  tags: string[];
  source_type: string;
  pricing_type: string;
  is_published: boolean;
  is_enabled: boolean;
  is_custom: boolean;
  is_in_library: boolean;
  created_by_user_id?: string | null;
  parent_theme_id?: string | null;
  downloads: number;
  color_swatches?: {
    primary?: string;
    accent?: string;
    background?: string;
    surface?: string;
  };
  theme_json: {
    colors: Record<string, unknown>;
    typography?: Record<string, unknown>;
    spacing?: Record<string, unknown>;
    animation?: Record<string, unknown>;
  };
  added_date?: string;
}

interface LibraryBase {
  id: string;
  name: string;
  slug: string;
  description: string;
  long_description?: string;
  git_repo_url?: string;
  default_branch?: string;
  category: string;
  icon: string;
  visibility: 'private' | 'public';
  tags?: string[];
  features?: string[];
  tech_stack?: string[];
  downloads: number;
  rating: number;
  source_type?: 'git' | 'archive';
  archive_size_bytes?: number;
  created_at: string;
}

interface LibrarySkill {
  id: string;
  name: string;
  slug: string;
  description: string;
  category: string;
  icon: string;
  pricing_type: string;
  price: number;
  downloads: number;
  rating: number;
  tags: string[];
  is_purchased: boolean;
  source_type?: string;
  git_repo_url?: string;
  features?: string[];
}

interface InstalledMcpServer {
  id: string;
  server_name: string | null;
  server_slug: string | null;
  is_active: boolean;
  marketplace_agent_id: string;
  enabled_capabilities: string[] | null;
  env_vars: string[] | null;
  created_at: string;
  updated_at: string | null;
}

// All available tools in the system
const _ALL_TOOLS = [
  'read_file',
  'write_file',
  'patch_file',
  'multi_edit',
  'apply_patch',
  'bash_exec',
  'shell_open',
  'shell_exec',
  'shell_close',
  'get_project_info',
  'todo_read',
  'todo_write',
  'save_plan',
  'update_plan',
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
    save_plan: { icon: <ListChecks size={12} weight="fill" />, label: 'Save Plan' },
    update_plan: { icon: <ListChecks size={12} weight="fill" />, label: 'Update Plan' },
    apply_patch: { icon: <FileText size={12} weight="fill" />, label: 'Apply Patch' },
    web_fetch: { icon: <Globe size={12} weight="fill" />, label: 'Web Fetch' },
  };
  return toolIcons[toolName] || null;
};

export default function Library() {
  const navigate = useNavigate();
  const { theme, toggleTheme } = useTheme();
  const [searchParams] = useSearchParams();
  const tabParam = searchParams.get('tab');
  // Normalize legacy "api-keys" tab to "models"
  const normalizedTab: TabType =
    tabParam === 'api-keys' ? 'models' : (tabParam as TabType) || 'agents';
  const [activeTab, setActiveTab] = useState<TabType>(normalizedTab);
  const [agents, setAgents] = useState<LibraryAgent[]>([]);
  const [bases, setBases] = useState<LibraryBase[]>([]);
  const [libraryThemes, setLibraryThemes] = useState<LibraryTheme[]>([]);
  const [apiKeys, setApiKeys] = useState<ApiKey[]>([]);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [byokEnabled, setByokEnabled] = useState<boolean | null>(null);
  const [showSubmitBaseModal, setShowSubmitBaseModal] = useState(false);
  const [editingBase, setEditingBase] = useState<LibraryBase | null>(null);
  const [editingTheme, setEditingTheme] = useState<LibraryTheme | null>(null);
  const [skills, setSkills] = useState<LibrarySkill[]>([]);
  const [mcpServers, setMcpServers] = useState<InstalledMcpServer[]>([]);
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
        icon: <ChatCircleDots className="w-5 h-5" weight="fill" />,
        title: 'Feedback',
        onClick: () => navigate('/feedback'),
      },
      {
        icon: <Article className="w-5 h-5" weight="fill" />,
        title: 'Documentation',
        onClick: () => window.open('https://docs.tesslate.com', '_blank'),
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
  const [customProviders, setCustomProviders] = useState<CustomProvider[]>([]);
  const [loading, setLoading] = useState(true);
  const [editingAgent, setEditingAgent] = useState<LibraryAgent | null>(null);

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab]);

  const loadData = async () => {
    setLoading(true);
    try {
      if (activeTab === 'agents') {
        await loadLibraryAgents();
        setLoading(false);
      } else if (activeTab === 'bases') {
        await loadCreatedBases();
        setLoading(false);
      } else if (activeTab === 'skills') {
        await loadSkills();
        setLoading(false);
      } else if (activeTab === 'mcp_servers') {
        await loadMcpServers();
        setLoading(false);
      } else if (activeTab === 'themes') {
        await loadLibraryThemes();
        setLoading(false);
      } else if (activeTab === 'models') {
        await Promise.all([loadModels(), loadApiKeys(), loadProviders()]);
        try {
          const sub = await billingApi.getSubscription();
          setByokEnabled(sub.byok_enabled ?? false);
        } catch {
          setByokEnabled(false);
        }
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

  const loadSkills = async () => {
    try {
      const data = await marketplaceApi.getAllSkills({ limit: 100 });
      setSkills(
        (data.skills || []).filter((s: Record<string, unknown>) => s.is_purchased)
      );
    } catch (err) {
      console.error('Failed to load skills:', err);
      toast.error('Failed to load skills');
    }
  };

  const loadMcpServers = async () => {
    try {
      const data = await marketplaceApi.getInstalledMcpServers();
      setMcpServers(Array.isArray(data) ? data : []);
    } catch (err) {
      console.error('Failed to load MCP servers:', err);
      toast.error('Failed to load MCP servers');
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

  const loadLibraryThemes = async () => {
    try {
      const data = await marketplaceApi.getUserLibraryThemes();
      setLibraryThemes(data.themes || []);
    } catch (error) {
      console.error('Failed to load themes:', error);
      toast.error('Failed to load themes');
    }
  };

  const handleToggleThemeEnable = async (t: LibraryTheme) => {
    try {
      const newState = !t.is_enabled;
      await marketplaceApi.toggleTheme(t.id, newState);
      toast.success(`Theme ${newState ? 'enabled' : 'disabled'}`);
      loadLibraryThemes();
    } catch (error) {
      console.error('Toggle failed:', error);
      toast.error('Failed to toggle theme');
    }
  };

  const handleToggleThemePublish = async (t: LibraryTheme) => {
    try {
      if (t.is_published) {
        await marketplaceApi.unpublishTheme(t.id);
        toast.success('Theme unpublished from marketplace');
      } else {
        await marketplaceApi.publishTheme(t.id);
        toast.success('Theme published to community marketplace!');
      }
      loadLibraryThemes();
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to update publish status');
    }
  };

  const handleRemoveTheme = async (t: LibraryTheme) => {
    try {
      await marketplaceApi.removeThemeFromLibrary(t.id);
      toast.success('Theme removed from library');
      loadLibraryThemes();
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to remove theme');
    }
  };

  const handleDeleteTheme = async (t: LibraryTheme) => {
    try {
      await marketplaceApi.deleteTheme(t.id);
      toast.success('Theme deleted');
      loadLibraryThemes();
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to delete theme');
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
      const [provData, customData] = await Promise.all([
        secretsApi.getProviders(),
        secretsApi.listCustomProviders(),
      ]);
      setProviders(provData.providers || []);
      setCustomProviders(customData.providers || []);
    } catch (error) {
      console.error('Failed to load providers:', error);
    }
  };

  const loadModels = async () => {
    try {
      const data = await marketplaceApi.getAvailableModels();
      const raw: ModelInfo[] = data.models || [];
      setModels(raw);
    } catch (error) {
      console.error('Failed to load models:', error);
    }
  };

  const handleToggleModel = async (modelId: string, enable: boolean) => {
    try {
      await secretsApi.toggleModel(modelId, enable);
      // Optimistic update
      setModels((prev) => prev.map((m) => (m.id === modelId ? { ...m, disabled: !enable } : m)));
    } catch {
      toast.error('Failed to update model preference');
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
      <div className="bg-[var(--surface)] border-b border-[var(--border)]">
        <div className="h-12 flex items-center px-4 md:px-6 justify-between border-b border-[var(--border)]">
          <h1 className="font-heading text-sm font-semibold text-[var(--text)]">Library</h1>

          <div className="flex items-center gap-3">
            {/* User Dropdown */}
            <UserDropdown />

            {/* Mobile hamburger menu */}
            <button
              onClick={() => window.dispatchEvent(new Event('toggleMobileMenu'))}
              className="md:hidden p-2 hover:bg-[var(--surface-hover)] active:bg-[var(--surface-hover)] rounded-lg transition-colors"
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
                  : 'bg-[var(--surface)] text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]'
              }`}
            >
              <Package size={16} weight={activeTab === 'agents' ? 'fill' : 'regular'} />
              Agents
            </button>
            <button
              onClick={() => setActiveTab('bases')}
              className={`px-3 py-1.5 text-xs font-medium transition-all rounded-lg flex items-center gap-2 whitespace-nowrap ${
                activeTab === 'bases'
                  ? 'bg-[var(--primary)] text-white'
                  : 'bg-[var(--surface)] text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]'
              }`}
            >
              <Rocket size={16} weight={activeTab === 'bases' ? 'fill' : 'regular'} />
              Bases
            </button>
            <button
              onClick={() => setActiveTab('skills')}
              className={`px-3 py-1.5 text-xs font-medium transition-all rounded-lg flex items-center gap-2 whitespace-nowrap ${
                activeTab === 'skills'
                  ? 'bg-[var(--primary)] text-white'
                  : 'bg-[var(--surface)] text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]'
              }`}
            >
              <Lightning size={16} weight={activeTab === 'skills' ? 'fill' : 'regular'} />
              Skills
            </button>
            <button
              onClick={() => setActiveTab('mcp_servers')}
              className={`px-3 py-1.5 text-xs font-medium transition-all rounded-lg flex items-center gap-2 whitespace-nowrap ${
                activeTab === 'mcp_servers'
                  ? 'bg-[var(--primary)] text-white'
                  : 'bg-[var(--surface)] text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]'
              }`}
            >
              <Plugs size={16} weight={activeTab === 'mcp_servers' ? 'fill' : 'regular'} />
              MCP Servers
            </button>
            <button
              onClick={() => setActiveTab('models')}
              className={`px-3 py-1.5 text-xs font-medium transition-all rounded-lg flex items-center gap-2 whitespace-nowrap ${
                activeTab === 'models'
                  ? 'bg-[var(--primary)] text-white'
                  : 'bg-[var(--surface)] text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]'
              }`}
            >
              <Cpu size={16} weight={activeTab === 'models' ? 'fill' : 'regular'} />
              Models
            </button>
            <button
              onClick={() => setActiveTab('themes')}
              className={`px-3 py-1.5 text-xs font-medium transition-all rounded-lg flex items-center gap-2 whitespace-nowrap ${
                activeTab === 'themes'
                  ? 'bg-[var(--primary)] text-white'
                  : 'bg-[var(--surface)] text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]'
              }`}
            >
              <PaintBrush size={16} weight={activeTab === 'themes' ? 'fill' : 'regular'} />
              Themes
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
              onToggleEnable={handleToggleEnable}
              onEdit={setEditingAgent}
              onTogglePublish={handleTogglePublish}
              onReload={loadLibraryAgents}
            />
          )}

          {activeTab === 'bases' && (
            <BasesTab
              bases={bases}
              loading={loading}
              onSubmit={() => {
                setEditingBase(null);
                setShowSubmitBaseModal(true);
              }}
              onEdit={(base) => {
                setEditingBase(base);
                setShowSubmitBaseModal(true);
              }}
              onToggleVisibility={handleToggleBaseVisibility}
              onDelete={handleDeleteBase}
            />
          )}

          {activeTab === 'skills' && (
            <SkillsTab
              skills={skills}
              agents={agents}
              loading={loading}
              onBrowse={() => navigate('/marketplace/browse/skill')}
            />
          )}

          {activeTab === 'mcp_servers' && (
            <McpServersTab
              servers={mcpServers}
              agents={agents}
              loading={loading}
              onReload={loadMcpServers}
              onBrowse={() => navigate('/marketplace/browse/mcp_server')}
            />
          )}

          {activeTab === 'themes' && (
            <ThemesTab
              themes={libraryThemes}
              loading={loading}
              onToggleEnable={handleToggleThemeEnable}
              onTogglePublish={handleToggleThemePublish}
              onEdit={setEditingTheme}
              onRemove={handleRemoveTheme}
              onDelete={handleDeleteTheme}
              onCreate={() => {
                setEditingTheme({
                  id: '',
                  name: '',
                  slug: '',
                  description: '',
                  mode: 'dark',
                  author: '',
                  icon: 'palette',
                  category: 'general',
                  tags: [],
                  source_type: 'open',
                  pricing_type: 'free',
                  is_published: false,
                  is_enabled: true,
                  is_custom: true,
                  is_in_library: true,
                  downloads: 0,
                  theme_json: {
                    colors: {
                      primary: '#6366f1',
                      primaryHover: '#818cf8',
                      primaryRgb: '99, 102, 241',
                      accent: '#8b5cf6',
                      background: '#0a0a0a',
                      surface: '#141414',
                      surfaceHover: '#1a1a1a',
                      text: '#ffffff',
                      textMuted: 'rgba(255, 255, 255, 0.6)',
                      textSubtle: 'rgba(255, 255, 255, 0.4)',
                      border: 'rgba(255, 255, 255, 0.1)',
                      borderHover: 'rgba(255, 255, 255, 0.2)',
                      error: '#ef4444',
                      success: '#22c55e',
                      warning: '#f59e0b',
                      info: '#3b82f6',
                    },
                    typography: {
                      fontFamily: "'Inter', system-ui, -apple-system, sans-serif",
                      fontFamilyMono: "'JetBrains Mono', 'Fira Code', monospace",
                      fontSizeBase: '14px',
                      lineHeight: '1.6',
                    },
                    spacing: {
                      radiusSmall: '6px',
                      radiusMedium: '10px',
                      radiusLarge: '14px',
                      radiusXl: '20px',
                    },
                    animation: {
                      durationFast: '0.15s',
                      durationNormal: '0.2s',
                      durationSlow: '0.3s',
                      easing: 'cubic-bezier(0.4, 0, 0.2, 1)',
                    },
                  },
                });
              }}
            />
          )}

          {activeTab === 'models' && (
            <ModelsTab
              models={models}
              apiKeys={apiKeys}
              providers={providers}
              customProviders={customProviders}
              byokEnabled={byokEnabled}
              onToggleModel={handleToggleModel}
              onReload={loadApiKeys}
              onReloadProviders={loadProviders}
              onReloadModels={loadModels}
            />
          )}
        </div>
      </div>

      {/* Edit Agent Modal */}
      {editingAgent && (
        <EditAgentModal
          agent={editingAgent}
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
                  model: updatedData.model || '',
                };
                response = await marketplaceApi.createCustomAgent(createData);

                // Update with additional fields (tools, tool_configs, avatar_url, config)
                const agentId = response.agent_id || response.id;
                if (
                  agentId &&
                  (updatedData.tools ||
                    updatedData.tool_configs ||
                    updatedData.avatar_url ||
                    updatedData.config)
                ) {
                  await marketplaceApi.updateAgent(agentId, {
                    tools: updatedData.tools,
                    tool_configs: updatedData.tool_configs,
                    avatar_url: updatedData.avatar_url,
                    config: updatedData.config,
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
              const err = error as {
                response?: { data?: { detail?: string | Array<{ msg: string }> } };
              };
              const detail = err.response?.data?.detail;
              const message =
                typeof detail === 'string'
                  ? detail
                  : Array.isArray(detail)
                    ? detail.map((d) => d.msg).join(', ')
                    : 'Failed to save agent';
              toast.error(message);
            }
          }}
        />
      )}

      {/* Submit/Edit Base Modal */}
      <SubmitBaseModal
        isOpen={showSubmitBaseModal}
        onClose={() => {
          setShowSubmitBaseModal(false);
          setEditingBase(null);
        }}
        onSuccess={loadCreatedBases}
        editBase={editingBase}
      />

      {/* Edit Theme Modal */}
      {editingTheme && (
        <EditThemeModal
          theme={editingTheme}
          onClose={() => setEditingTheme(null)}
          onSave={async (data) => {
            try {
              if (!editingTheme.id || editingTheme.id === '') {
                await marketplaceApi.createCustomTheme({
                  name: data.name,
                  description: data.description,
                  mode: data.mode,
                  theme_json: data.theme_json,
                  icon: data.icon,
                  category: data.category,
                  tags: data.tags,
                });
                toast.success('Theme created successfully!');
              } else {
                await marketplaceApi.updateTheme(editingTheme.id, data);
                toast.success('Theme updated successfully');
              }
              setEditingTheme(null);
              loadLibraryThemes();
            } catch (error: unknown) {
              console.error('Save failed:', error);
              const err = error as { response?: { data?: { detail?: string } } };
              toast.error(err.response?.data?.detail || 'Failed to save theme');
            }
          }}
        />
      )}
    </>
  );
}

// Themes Tab Component
function ThemesTab({
  themes,
  loading,
  onToggleEnable,
  onTogglePublish,
  onEdit,
  onRemove,
  onDelete,
  onCreate,
}: {
  themes: LibraryTheme[];
  loading: boolean;
  onToggleEnable: (theme: LibraryTheme) => void;
  onTogglePublish: (theme: LibraryTheme) => void;
  onEdit: (theme: LibraryTheme) => void;
  onRemove: (theme: LibraryTheme) => void;
  onDelete: (theme: LibraryTheme) => void;
  onCreate: () => void;
}) {
  const navigate = useNavigate();
  const { themePresetId, setThemePreset } = useTheme();
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [themeToDelete, setThemeToDelete] = useState<LibraryTheme | null>(null);
  const [deleteAction, setDeleteAction] = useState<'remove' | 'delete'>('remove');

  const handleApply = (t: LibraryTheme) => {
    setThemePreset(t.id);
    toast.success(`Applied "${t.name}" theme`);
  };

  const handleRemove = (t: LibraryTheme) => {
    setThemeToDelete(t);
    setDeleteAction('remove');
    setShowDeleteDialog(true);
  };

  const handleDelete = (t: LibraryTheme) => {
    setThemeToDelete(t);
    setDeleteAction('delete');
    setShowDeleteDialog(true);
  };

  const darkThemes = themes.filter((t) => t.mode === 'dark');
  const lightThemes = themes.filter((t) => t.mode === 'light');

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <p className="text-sm text-[var(--text-muted)]">
          {themes.length} theme{themes.length !== 1 ? 's' : ''} in your library
        </p>
        <div className="flex items-center gap-2">
          <button
            onClick={() => navigate('/marketplace?type=theme')}
            className="px-3 py-1.5 text-xs font-medium bg-white/5 text-[var(--text-muted)] hover:bg-white/10 rounded-lg transition-colors"
          >
            Browse Themes
          </button>
          <button
            onClick={onCreate}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white rounded-lg text-xs font-medium transition-colors"
          >
            <Plus size={14} weight="bold" />
            Create Theme
          </button>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-12">
          <LoadingSpinner message="Loading themes..." size={40} />
        </div>
      ) : themes.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <PaintBrush size={48} className="text-[var(--text-subtle)] mb-4" />
          <h3 className="text-lg font-medium text-[var(--text-muted)] mb-2">No themes yet</h3>
          <p className="text-sm text-[var(--text-muted)] max-w-md mb-4">
            Add themes from the marketplace or create your own custom theme.
          </p>
          <button
            onClick={() => navigate('/marketplace?type=theme')}
            className="px-4 py-2 bg-[var(--primary)] text-white rounded-lg text-sm font-medium"
          >
            Browse Themes
          </button>
        </div>
      ) : (
        <>
          {/* Dark Themes */}
          {darkThemes.length > 0 && (
            <div>
              <h3 className="text-sm font-medium text-[var(--text)]/70 mb-3">Dark Themes</h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
                {darkThemes.map((t) => (
                  <LibraryThemeCard
                    key={t.id}
                    theme={t}
                    isActive={themePresetId === t.id}
                    onApply={handleApply}
                    onEdit={onEdit}
                    onToggleEnable={onToggleEnable}
                    onTogglePublish={onTogglePublish}
                    onRemove={handleRemove}
                    onDelete={handleDelete}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Light Themes */}
          {lightThemes.length > 0 && (
            <div>
              <h3 className="text-sm font-medium text-[var(--text)]/70 mb-3">Light Themes</h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
                {lightThemes.map((t) => (
                  <LibraryThemeCard
                    key={t.id}
                    theme={t}
                    isActive={themePresetId === t.id}
                    onApply={handleApply}
                    onEdit={onEdit}
                    onToggleEnable={onToggleEnable}
                    onTogglePublish={onTogglePublish}
                    onRemove={handleRemove}
                    onDelete={handleDelete}
                  />
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {/* Delete/Remove confirmation */}
      <ConfirmDialog
        isOpen={showDeleteDialog}
        title={deleteAction === 'delete' ? 'Delete Theme' : 'Remove Theme'}
        message={
          deleteAction === 'delete'
            ? `Are you sure you want to permanently delete "${themeToDelete?.name}"? This cannot be undone.`
            : `Remove "${themeToDelete?.name}" from your library? You can add it back later from the marketplace.`
        }
        confirmLabel={deleteAction === 'delete' ? 'Delete' : 'Remove'}
        onConfirm={() => {
          if (themeToDelete) {
            if (deleteAction === 'delete') {
              onDelete(themeToDelete);
            } else {
              onRemove(themeToDelete);
            }
          }
          setShowDeleteDialog(false);
          setThemeToDelete(null);
        }}
        onCancel={() => {
          setShowDeleteDialog(false);
          setThemeToDelete(null);
        }}
      />
    </div>
  );
}

// Library Theme Card Component
function LibraryThemeCard({
  theme: t,
  isActive,
  onApply,
  onEdit,
  onToggleEnable,
  onTogglePublish,
  onRemove,
  onDelete,
}: {
  theme: LibraryTheme;
  isActive: boolean;
  onApply: (theme: LibraryTheme) => void;
  onEdit: (theme: LibraryTheme) => void;
  onToggleEnable: (theme: LibraryTheme) => void;
  onTogglePublish: (theme: LibraryTheme) => void;
  onRemove: (theme: LibraryTheme) => void;
  onDelete: (theme: LibraryTheme) => void;
}) {
  const colors = t.color_swatches || t.theme_json?.colors || {};
  const isDefault = t.id === 'default-dark' || t.id === 'default-light';

  return (
    <CardSurface
      isActive={isActive}
      isDisabled={!t.is_enabled}
      disableHoverLift={!t.is_enabled}
      role="article"
      aria-label={`${t.name} theme${isActive ? ' (active)' : ''}${!t.is_enabled ? ' (disabled)' : ''}`}
    >
      {/* Header: swatches + title + status */}
      <CardHeader
        icon={
          <div className="w-11 h-11 sm:w-12 sm:h-12 rounded-xl bg-[var(--bg)] border border-[var(--border)] grid grid-cols-2 gap-0.5 p-1 shrink-0 transition-colors group-hover:border-[rgba(var(--primary-rgb),0.3)]">
            {(['primary', 'background', 'surface', 'accent'] as const).map((key) => (
              <div
                key={key}
                className="rounded-sm"
                style={{ backgroundColor: (colors as Record<string, string>)[key] || '#333' }}
              />
            ))}
          </div>
        }
        title={t.name}
        subtitle={t.creator_username ? `@${t.creator_username}` : t.author || 'Tesslate'}
        trailing={<StatusDot active={isActive} />}
      />

      {/* Description */}
      <p className="text-xs sm:text-[13px] leading-relaxed text-[var(--text-muted)] line-clamp-2 mb-3 min-h-[32px]">
        {t.description || 'No description'}
      </p>

      {/* Badges row */}
      <div className="flex items-center gap-1.5 mb-3 flex-wrap">
        <Badge intent="muted" icon={t.mode === 'dark' ? <Moon size={11} /> : <Sun size={11} />}>
          {t.mode === 'dark' ? 'Dark' : 'Light'}
        </Badge>
        {t.source_type === 'open' && (
          <Badge intent="success" icon={<LockSimpleOpen size={11} />}>Open</Badge>
        )}
        {t.is_custom && (
          <Badge intent="primary" icon={<GitFork size={11} />}>Custom</Badge>
        )}
        {t.is_published && t.is_custom && (
          <Badge intent="success" icon={<CheckCircle size={11} />}>Published</Badge>
        )}
      </div>

      {/* Actions */}
      <CardActions>
        {/* Apply */}
        {!isActive && t.is_enabled && (
          <button
            onClick={() => onApply(t)}
            aria-label={`Apply ${t.name} theme`}
            className="flex items-center justify-center sm:justify-start gap-1.5 px-3 py-2 sm:py-1.5 bg-[var(--primary)]/10 border border-[var(--primary)]/20 text-[var(--primary)] hover:bg-[var(--primary)]/20 active:bg-[var(--primary)]/30 active:scale-[0.97] rounded-lg text-xs font-medium transition-all hover:shadow-sm min-h-[36px] sm:min-h-0"
          >
            <PaintBrush size={14} />
            Apply
          </button>
        )}

        {/* Edit — auto-forks on backend if user doesn't own the theme */}
        <button
          onClick={() => onEdit(t)}
          aria-label={`Edit ${t.name}`}
          className="flex items-center justify-center sm:justify-start gap-1.5 px-3 py-2 sm:py-1.5 bg-[var(--surface)] border border-[var(--border)] text-[var(--text-muted)] hover:bg-[var(--surface-hover)] active:bg-[var(--border)] active:scale-[0.97] rounded-lg text-xs transition-all min-h-[36px] sm:min-h-0"
        >
          <Pencil size={14} />
          Edit
        </button>

        {/* Publish toggle */}
        {t.is_custom && (
          <button
            onClick={() => onTogglePublish(t)}
            aria-label={t.is_published ? `Unpublish ${t.name}` : `Publish ${t.name} to marketplace`}
            className={`flex items-center justify-center sm:justify-start gap-1.5 px-3 py-2 sm:py-1.5 rounded-lg text-xs transition-all active:scale-[0.97] min-h-[36px] sm:min-h-0 ${
              t.is_published
                ? 'bg-[var(--status-success)]/10 border border-[var(--status-success)]/20 text-[var(--status-success)] hover:bg-[var(--status-success)]/20'
                : 'bg-[var(--surface)] border border-[var(--border)] text-[var(--text-subtle)] hover:bg-[var(--surface-hover)]'
            }`}
          >
            {t.is_published ? <Eye size={14} /> : <EyeSlash size={14} />}
            {t.is_published ? 'Published' : 'Publish'}
          </button>
        )}

        {/* Enable/disable */}
        {!isDefault && (
          <button
            onClick={() => onToggleEnable(t)}
            aria-label={t.is_enabled ? `Disable ${t.name}` : `Enable ${t.name}`}
            className={`flex items-center justify-center sm:justify-start gap-1.5 px-3 py-2 sm:py-1.5 rounded-lg text-xs transition-all active:scale-[0.97] min-h-[36px] sm:min-h-0 ${
              t.is_enabled
                ? 'bg-[var(--surface)] border border-[var(--border)] text-[var(--text-subtle)] hover:bg-[var(--surface-hover)]'
                : 'bg-[var(--status-success)]/10 border border-[var(--status-success)]/20 text-[var(--status-success)] hover:bg-[var(--status-success)]/20'
            }`}
          >
            {t.is_enabled ? <Power size={14} /> : <Power size={14} />}
            {t.is_enabled ? 'Disable' : 'Enable'}
          </button>
        )}

        {/* Delete or Remove */}
        {t.is_custom && !t.is_published ? (
          <button
            onClick={() => onDelete(t)}
            aria-label={`Delete ${t.name}`}
            className="flex items-center justify-center sm:justify-start gap-1.5 px-3 py-2 sm:py-1.5 text-[var(--error)] hover:bg-[var(--error)]/10 active:bg-[var(--error)]/15 active:scale-[0.97] rounded-lg text-xs transition-all sm:ml-auto min-h-[36px] sm:min-h-0"
          >
            <Trash size={14} />
            Delete
          </button>
        ) : !isDefault ? (
          <button
            onClick={() => onRemove(t)}
            aria-label={`Remove ${t.name} from library`}
            className="flex items-center justify-center sm:justify-start gap-1.5 px-3 py-2 sm:py-1.5 text-[var(--text-subtle)] hover:text-[var(--error)] hover:bg-[var(--error)]/10 active:bg-[var(--error)]/15 active:scale-[0.97] rounded-lg text-xs transition-all sm:ml-auto min-h-[36px] sm:min-h-0"
          >
            <XCircle size={14} />
            Remove
          </button>
        ) : null}
      </CardActions>
    </CardSurface>
  );
}

// Edit Theme Modal
function EditThemeModal({
  theme,
  onClose,
  onSave,
}: {
  theme: LibraryTheme;
  onClose: () => void;
  onSave: (data: {
    name: string;
    description: string;
    mode: string;
    theme_json: Record<string, unknown>;
    icon: string;
    category: string;
    tags: string[];
  }) => void;
}) {
  const [name, setName] = useState(theme.name);
  const [description, setDescription] = useState(theme.description || '');
  const [mode, setMode] = useState(theme.mode || 'dark');
  const [icon, setIcon] = useState(theme.icon || 'palette');
  const [category, setCategory] = useState(theme.category || 'general');
  const [tagsInput, setTagsInput] = useState((theme.tags || []).join(', '));
  const [themeColors, setThemeColors] = useState<Record<string, string>>(() => {
    const c = (theme.theme_json?.colors || {}) as Record<string, unknown>;
    const flat: Record<string, string> = {};
    for (const [k, v] of Object.entries(c)) {
      if (typeof v === 'string') {
        flat[k] = v;
      } else if (typeof v === 'object' && v !== null) {
        // Nested objects like sidebar.background
        for (const [nk, nv] of Object.entries(v as Record<string, string>)) {
          flat[`${k}.${nk}`] = nv;
        }
      }
    }
    return flat;
  });
  const [saving, setSaving] = useState(false);

  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({
    primary: true,
    background: true,
    text: false,
    border: false,
    sidebar: false,
    input: false,
    status: false,
    code: false,
    typography: false,
    spacing: false,
    animation: false,
  });

  const toggleSection = (key: string) => {
    setExpandedSections((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const colorGroups = [
    {
      key: 'primary',
      label: 'Primary Colors',
      fields: ['primary', 'primaryHover', 'primaryRgb', 'accent'],
    },
    {
      key: 'background',
      label: 'Background',
      fields: ['background', 'surface', 'surfaceHover'],
    },
    {
      key: 'text',
      label: 'Text',
      fields: ['text', 'textMuted', 'textSubtle'],
    },
    {
      key: 'border',
      label: 'Border',
      fields: ['border', 'borderHover'],
    },
    {
      key: 'sidebar',
      label: 'Sidebar',
      fields: [
        'sidebar.background',
        'sidebar.text',
        'sidebar.border',
        'sidebar.hover',
        'sidebar.active',
      ],
    },
    {
      key: 'input',
      label: 'Input',
      fields: [
        'input.background',
        'input.border',
        'input.borderFocus',
        'input.text',
        'input.placeholder',
      ],
    },
    {
      key: 'status',
      label: 'Status Colors',
      fields: ['error', 'success', 'warning', 'info'],
    },
    {
      key: 'code',
      label: 'Code',
      fields: [
        'code.inlineBackground',
        'code.inlineText',
        'code.blockBackground',
        'code.blockBorder',
        'code.blockText',
      ],
    },
  ];

  const updateColor = (key: string, value: string) => {
    setThemeColors((prev) => ({ ...prev, [key]: value }));
  };

  // Convert hex to something usable for color input (strip rgba/rgb, just use hex)
  const toHexForInput = (val: string) => {
    if (!val) return '#333333';
    if (val.startsWith('#') && (val.length === 7 || val.length === 4)) return val;
    // Try to parse rgb/rgba
    const rgbMatch = val.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
    if (rgbMatch) {
      const r = parseInt(rgbMatch[1]).toString(16).padStart(2, '0');
      const g = parseInt(rgbMatch[2]).toString(16).padStart(2, '0');
      const b = parseInt(rgbMatch[3]).toString(16).padStart(2, '0');
      return `#${r}${g}${b}`;
    }
    return '#333333';
  };

  const handleSave = () => {
    if (!name.trim()) {
      toast.error('Theme name is required');
      return;
    }
    setSaving(true);

    // Reconstruct nested color object from flat keys
    const colors: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(themeColors)) {
      if (k.includes('.')) {
        const [parent, child] = k.split('.');
        if (!colors[parent]) colors[parent] = {};
        (colors[parent] as Record<string, string>)[child] = v;
      } else {
        colors[k] = v;
      }
    }

    onSave({
      name: name.trim(),
      description: description.trim(),
      mode,
      theme_json: {
        colors,
        typography: theme.theme_json?.typography || {},
        spacing: theme.theme_json?.spacing || {},
        animation: theme.theme_json?.animation || {},
      },
      icon,
      category,
      tags: tagsInput
        .split(',')
        .map((t) => t.trim())
        .filter(Boolean),
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="bg-[var(--surface)] rounded-2xl border border-white/10 w-full max-w-4xl max-h-[90vh] overflow-hidden flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-white/10">
          <h2 className="text-lg font-semibold text-[var(--text)]">
            {theme.id ? 'Edit Theme' : 'Create New Theme'}
          </h2>
          <button
            onClick={onClose}
            className="p-1.5 hover:bg-white/10 rounded-lg transition-colors text-[var(--text-muted)]"
          >
            <X size={18} />
          </button>
        </div>

        {/* Content - two columns */}
        <div className="flex-1 overflow-auto p-4">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Left: Basic Info */}
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">
                  Name
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm text-[var(--text)] focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
                  placeholder="My Custom Theme"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">
                  Description
                </label>
                <input
                  type="text"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm text-[var(--text)] focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
                  placeholder="A beautiful dark theme with..."
                />
              </div>
              <div className="flex gap-4">
                <div className="flex-1">
                  <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">
                    Mode
                  </label>
                  <div className="flex gap-2">
                    <button
                      onClick={() => setMode('dark')}
                      className={`flex-1 px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
                        mode === 'dark'
                          ? 'bg-[var(--primary)] text-white'
                          : 'bg-white/5 text-[var(--text-muted)] hover:bg-white/10'
                      }`}
                    >
                      Dark
                    </button>
                    <button
                      onClick={() => setMode('light')}
                      className={`flex-1 px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
                        mode === 'light'
                          ? 'bg-[var(--primary)] text-white'
                          : 'bg-white/5 text-[var(--text-muted)] hover:bg-white/10'
                      }`}
                    >
                      Light
                    </button>
                  </div>
                </div>
                <div className="flex-1">
                  <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">
                    Category
                  </label>
                  <select
                    value={category}
                    onChange={(e) => setCategory(e.target.value)}
                    className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm text-[var(--text)] focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
                  >
                    <option value="general">General</option>
                    <option value="minimal">Minimal</option>
                    <option value="vibrant">Vibrant</option>
                    <option value="professional">Professional</option>
                  </select>
                </div>
              </div>
              <div className="flex gap-4">
                <div className="flex-1">
                  <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">
                    Icon
                  </label>
                  <input
                    type="text"
                    value={icon}
                    onChange={(e) => setIcon(e.target.value)}
                    className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm text-[var(--text)] focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
                    placeholder="palette"
                  />
                </div>
                <div className="flex-1">
                  <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">
                    Tags
                  </label>
                  <input
                    type="text"
                    value={tagsInput}
                    onChange={(e) => setTagsInput(e.target.value)}
                    className="w-full px-3 py-2 bg-white/5 border border-white/10 rounded-lg text-sm text-[var(--text)] focus:outline-none focus:ring-2 focus:ring-[var(--primary)]"
                    placeholder="dark, minimal, blue"
                  />
                </div>
              </div>

              {/* Live Preview */}
              <div>
                <label className="block text-xs font-medium text-[var(--text-muted)] mb-2">
                  Preview
                </label>
                <div
                  className="rounded-xl border overflow-hidden p-4"
                  style={{
                    backgroundColor: themeColors.background || '#0a0a0a',
                    borderColor: themeColors.border || 'rgba(255,255,255,0.1)',
                  }}
                >
                  <div
                    className="rounded-lg p-3 mb-2"
                    style={{
                      backgroundColor: themeColors.surface || '#141414',
                      borderColor: themeColors.border || 'rgba(255,255,255,0.1)',
                      border: '1px solid',
                    }}
                  >
                    <div
                      className="text-sm font-medium mb-1"
                      style={{ color: themeColors.text || '#fff' }}
                    >
                      Sample Card
                    </div>
                    <div
                      className="text-xs mb-2"
                      style={{ color: themeColors.textMuted || 'rgba(255,255,255,0.6)' }}
                    >
                      This is how content looks with your theme colors.
                    </div>
                    <button
                      className="px-3 py-1 rounded-md text-xs font-medium text-white"
                      style={{ backgroundColor: themeColors.primary || '#6366f1' }}
                    >
                      Primary Button
                    </button>
                  </div>
                  <div className="flex gap-2">
                    <span
                      className="px-2 py-0.5 rounded text-[10px] font-medium"
                      style={{
                        backgroundColor: themeColors.success || '#22c55e',
                        color: '#fff',
                      }}
                    >
                      Success
                    </span>
                    <span
                      className="px-2 py-0.5 rounded text-[10px] font-medium"
                      style={{
                        backgroundColor: themeColors.error || '#ef4444',
                        color: '#fff',
                      }}
                    >
                      Error
                    </span>
                    <span
                      className="px-2 py-0.5 rounded text-[10px] font-medium"
                      style={{
                        backgroundColor: themeColors.accent || '#8b5cf6',
                        color: '#fff',
                      }}
                    >
                      Accent
                    </span>
                  </div>
                </div>
              </div>
            </div>

            {/* Right: Color Editor */}
            <div className="space-y-2 max-h-[60vh] overflow-auto pr-1">
              {colorGroups.map((group) => (
                <div key={group.key} className="border border-white/5 rounded-lg overflow-hidden">
                  <button
                    onClick={() => toggleSection(group.key)}
                    className="w-full flex items-center justify-between px-3 py-2 hover:bg-white/5 transition-colors"
                  >
                    <span className="text-xs font-medium text-[var(--text)]/70">{group.label}</span>
                    {expandedSections[group.key] ? (
                      <CaretDown size={12} className="text-[var(--text-subtle)]" />
                    ) : (
                      <CaretRight size={12} className="text-[var(--text-subtle)]" />
                    )}
                  </button>
                  {expandedSections[group.key] && (
                    <div className="px-3 pb-3 space-y-2">
                      {group.fields.map((field) => (
                        <div key={field} className="flex items-center gap-2">
                          <input
                            type="color"
                            value={toHexForInput(themeColors[field] || '')}
                            onChange={(e) => updateColor(field, e.target.value)}
                            className="w-7 h-7 rounded border border-white/10 cursor-pointer bg-transparent"
                          />
                          <div className="flex-1 min-w-0">
                            <label className="text-[10px] text-[var(--text-subtle)] block truncate">
                              {field}
                            </label>
                            <input
                              type="text"
                              value={themeColors[field] || ''}
                              onChange={(e) => updateColor(field, e.target.value)}
                              className="w-full px-2 py-1 bg-white/5 border border-white/10 rounded text-[11px] text-[var(--text-muted)] focus:outline-none focus:ring-1 focus:ring-[var(--primary)]"
                              placeholder="#000000"
                            />
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 p-4 border-t border-white/10">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-[var(--text-muted)] hover:bg-white/5 rounded-lg transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving || !name.trim()}
            className="px-4 py-2 bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50"
          >
            {saving ? 'Saving...' : theme.id ? 'Save Changes' : 'Create Theme'}
          </button>
        </div>
      </div>
    </div>
  );
}

// Agents Tab Component
function AgentsTab({
  agents,
  onToggleEnable,
  onEdit,
  onTogglePublish,
  onReload,
}: {
  agents: LibraryAgent[];
  onToggleEnable: (agent: LibraryAgent) => void;
  onEdit: (agent: LibraryAgent) => void;
  onTogglePublish: (agent: LibraryAgent) => void;
  onReload: () => void;
}) {
  const navigate = useNavigate();
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [agentToDelete, setAgentToDelete] = useState<LibraryAgent | null>(null);

  const [deleteAction, setDeleteAction] = useState<'remove' | 'delete'>('remove');

  const handleRemove = (agent: LibraryAgent) => {
    setAgentToDelete(agent);
    setDeleteAction('remove');
    setShowDeleteDialog(true);
  };

  const handleDelete = (agent: LibraryAgent) => {
    setAgentToDelete(agent);
    setDeleteAction('delete');
    setShowDeleteDialog(true);
  };

  const confirmRemoveAgent = async () => {
    if (!agentToDelete) return;

    setShowDeleteDialog(false);
    const isDelete = deleteAction === 'delete';
    const actionToast = toast.loading(
      isDelete ? `Deleting ${agentToDelete.name}...` : `Removing ${agentToDelete.name}...`
    );

    try {
      if (isDelete) {
        await marketplaceApi.deleteCustomAgent(agentToDelete.id);
        toast.success(`${agentToDelete.name} deleted permanently`, { id: actionToast });
      } else {
        await marketplaceApi.removeFromLibrary(agentToDelete.id);
        toast.success(`${agentToDelete.name} removed from library`, { id: actionToast });
      }
      onReload();
    } catch (error: unknown) {
      console.error(`${isDelete ? 'Delete' : 'Remove'} failed:`, error);
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(
        err.response?.data?.detail || `Failed to ${isDelete ? 'delete' : 'remove'} agent`,
        { id: actionToast }
      );
    } finally {
      setAgentToDelete(null);
    }
  };

  if (agents.length === 0) {
    return (
      <div className="text-center py-16">
        <Package size={48} className="mx-auto mb-4 text-[var(--text-subtle)]" />
        <p className="text-[var(--text-muted)] mb-4">Your library is empty</p>
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
        <StatCard value={agents.length} label="Total Agents" index={0} />
        <StatCard value={agents.filter((a) => a.is_enabled).length} label="Active" index={1} />
        <StatCard value={agents.filter((a) => a.is_custom).length} label="Custom" index={2} />
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
              model: '',
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
          className="px-4 py-2 bg-[var(--primary)] hover:bg-[var(--primary)]/90 text-white rounded-lg transition-colors flex items-center gap-2"
        >
          <Plus size={18} />
          Create New Agent
        </button>
      </div>

      {/* Agents Grid */}
      <motion.div variants={staggerContainer} initial="initial" animate="animate" className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
        {agents.map((agent) => (
          <AgentCard
            key={agent.id}
            agent={agent}
            onToggleEnable={() => onToggleEnable(agent)}
            onEdit={() => onEdit(agent)}
            onTogglePublish={() => onTogglePublish(agent)}
            onRemove={() => handleRemove(agent)}
            onDelete={() => handleDelete(agent)}
          />
        ))}
      </motion.div>

      {/* Delete/Remove Confirmation Dialog */}
      <ConfirmDialog
        isOpen={showDeleteDialog}
        onClose={() => {
          setShowDeleteDialog(false);
          setAgentToDelete(null);
        }}
        onConfirm={confirmRemoveAgent}
        title={deleteAction === 'delete' ? 'Delete Agent' : 'Remove Agent'}
        message={
          deleteAction === 'delete'
            ? `Permanently delete "${agentToDelete?.name}"? This will remove the agent entirely and cannot be undone.`
            : `Remove "${agentToDelete?.name}" from your library? You can re-install it from the Marketplace at any time.`
        }
        confirmText={deleteAction === 'delete' ? 'Delete Permanently' : 'Remove'}
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
          <p className="text-xs text-[var(--text-muted)] mt-1">
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
          <div className="w-16 h-16 bg-[var(--surface)] rounded-2xl flex items-center justify-center mb-4">
            <Rocket size={32} className="text-[var(--text)]/30" />
          </div>
          <h3 className="text-lg font-semibold text-[var(--text)] mb-2">No bases yet</h3>
          <p className="text-sm text-[var(--text-muted)] max-w-sm mb-6">
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
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          {bases.map((base) => (
            <div
              key={base.id}
              role="article"
              aria-label={`${base.name} base template`}
              className="group relative flex flex-col bg-[var(--surface)] border border-[var(--border)] rounded-[var(--radius-large)] p-4 sm:p-5 hover:border-[rgba(var(--primary-rgb),0.3)] hover:-translate-y-1 hover:shadow-[0_8px_30px_rgba(0,0,0,0.12)] transition-all duration-200 ease-out"
            >
              {/* Header: icon + title + badge */}
              <div className="flex items-start gap-3 mb-3 pr-16">
                <div className="w-11 h-11 sm:w-12 sm:h-12 rounded-xl bg-[var(--bg)] border border-[var(--border)] flex items-center justify-center shrink-0 transition-colors group-hover:border-[rgba(var(--primary-rgb),0.3)]">
                  <span className="text-2xl">{base.icon}</span>
                </div>
                <div className="flex-1 min-w-0">
                  <h4 className="text-sm font-semibold text-[var(--text)] line-clamp-1 group-hover:text-[var(--primary)] transition-colors">
                    {base.name}
                  </h4>
                  <span className="text-xs text-[var(--text-muted)]">{base.category}</span>
                </div>
              </div>

              {/* Status indicator — top-right */}
              <div className="absolute top-3 right-3 sm:top-4 sm:right-4 flex items-center gap-1.5">
                {base.source_type === 'archive' && (
                  <span className="px-2 py-0.5 rounded-md text-[11px] font-medium bg-[var(--primary)]/15 text-[var(--primary)]">
                    Exported
                  </span>
                )}
                <span
                  className={`flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium ${
                    base.visibility === 'public'
                      ? 'bg-[var(--status-success)]/15 text-[var(--status-success)]'
                      : 'bg-[var(--surface)] border border-[var(--border)] text-[var(--text-subtle)]'
                  }`}
                >
                  {base.visibility === 'public' ? <Globe size={11} /> : <LockKey size={11} />}
                  {base.visibility}
                </span>
              </div>

              {/* Description */}
              <p className="text-xs sm:text-[13px] leading-relaxed text-[var(--text-muted)] line-clamp-2 mb-3 min-h-[32px]">
                {base.description}
              </p>

              {/* Tech stack tags */}
              {base.tech_stack && base.tech_stack.length > 0 && (
                <div className="flex flex-wrap gap-1 mb-3">
                  {base.tech_stack.slice(0, 4).map((tech) => (
                    <span
                      key={tech}
                      className="px-2 py-0.5 bg-[var(--surface)] border border-[var(--border)] rounded-md text-[11px] text-[var(--text-muted)]"
                    >
                      {tech}
                    </span>
                  ))}
                </div>
              )}

              {/* Stats */}
              <div className="flex items-center gap-3 mb-0 text-xs text-[var(--text-subtle)]">
                <span>{base.downloads || 0} downloads</span>
                <span>{base.rating?.toFixed(1) || '5.0'} rating</span>
                {base.source_type === 'archive' && base.archive_size_bytes && (
                  <span>
                    {base.archive_size_bytes < 1024 * 1024
                      ? `${(base.archive_size_bytes / 1024).toFixed(0)} KB`
                      : `${(base.archive_size_bytes / 1024 / 1024).toFixed(1)} MB`}
                  </span>
                )}
              </div>

              {/* Actions — grid on mobile, flex on desktop */}
              <div className="mt-auto pt-3 border-t border-[var(--border)] grid grid-cols-2 sm:flex sm:flex-wrap sm:items-center gap-2">
                <button
                  onClick={() => onToggleVisibility(base)}
                  aria-label={
                    base.visibility === 'public'
                      ? `Make ${base.name} private`
                      : `Make ${base.name} public`
                  }
                  className={`flex items-center justify-center sm:justify-start gap-1.5 px-3 py-2 sm:py-1.5 rounded-lg text-xs transition-all active:scale-[0.97] min-h-[36px] sm:min-h-0 ${
                    base.visibility === 'public'
                      ? 'bg-[var(--status-success)]/10 border border-[var(--status-success)]/20 text-[var(--status-success)] hover:bg-[var(--status-success)]/20'
                      : 'bg-[var(--surface)] border border-[var(--border)] text-[var(--text-subtle)] hover:bg-[var(--surface-hover)]'
                  }`}
                >
                  {base.visibility === 'public' ? <Eye size={14} /> : <EyeSlash size={14} />}
                  {base.visibility === 'public' ? 'Public' : 'Private'}
                </button>
                <button
                  onClick={() => onEdit(base)}
                  aria-label={`Edit ${base.name}`}
                  className="flex items-center justify-center sm:justify-start gap-1.5 px-3 py-2 sm:py-1.5 bg-[var(--primary)]/10 border border-[var(--primary)]/20 text-[var(--primary)] hover:bg-[var(--primary)]/20 active:bg-[var(--primary)]/30 active:scale-[0.97] rounded-lg text-xs font-medium transition-all hover:shadow-sm min-h-[36px] sm:min-h-0"
                >
                  <Pencil size={14} />
                  Edit
                </button>
                <button
                  onClick={() => setDeleteTarget(base)}
                  aria-label={`Delete ${base.name}`}
                  className="flex items-center justify-center sm:justify-start gap-1.5 px-3 py-2 sm:py-1.5 text-[var(--error)] hover:bg-[var(--error)]/10 active:bg-[var(--error)]/15 active:scale-[0.97] rounded-lg text-xs transition-all sm:ml-auto min-h-[36px] sm:min-h-0"
                >
                  <Trash size={14} />
                  Delete
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

// API Keys Tab Component
/** Get a friendly provider label */
function getProviderLabel(provider: string, providerName?: string): string {
  if (providerName) return providerName;
  const labels: Record<string, string> = {
    internal: 'Tesslate (System)',
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
      className={`bg-[var(--surface)] border rounded-[var(--radius-large)] p-3 transition-all ${
        isDisabled
          ? 'border-[var(--border)] opacity-50'
          : 'border-[var(--border)] hover:border-[var(--border-hover)]'
      }`}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="p-1.5 bg-[rgba(var(--primary-rgb),0.1)] rounded-[var(--radius-small)] flex-shrink-0">
            <Cpu size={14} className="text-[var(--primary)]" />
          </div>
          <div className="min-w-0">
            <div className="text-sm font-medium text-[var(--text)] truncate">{displayName}</div>
            {model.pricing && (model.pricing.input > 0 || model.pricing.output > 0) && (
              <div className="text-[10px] text-[var(--text-subtle)] font-mono mt-0.5">
                {formatCreditsPerMillion(model.pricing.input)}/{formatCreditsPerMillion(model.pricing.output)} credits per 1M
              </div>
            )}
          </div>
        </div>
        {/* Health dot + Delete + Toggle */}
        <div className="flex items-center gap-2 flex-shrink-0">
          {model.health === 'operational' && (
            <div className="w-1.5 h-1.5 rounded-full bg-[var(--status-success)]" />
          )}
          {model.custom_id && onDelete && (
            <button
              onClick={() => onDelete(model.custom_id!)}
              className="text-[var(--text-subtle)] hover:text-[var(--status-error)] transition-colors"
              title="Remove custom model"
            >
              <X size={14} />
            </button>
          )}
          <button
            onClick={() => onToggle(model.id, !!isDisabled)}
            className="text-[var(--text-muted)] hover:text-[var(--text)] transition-colors"
            title={isDisabled ? 'Enable model' : 'Disable model'}
          >
            {isDisabled ? (
              <ToggleLeft size={20} />
            ) : (
              <ToggleRight size={20} className="text-[var(--primary)]" />
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

function ModelsTab({
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
  const [addingModelProvider, setAddingModelProvider] = useState<string | null>(null);
  const [newModelId, setNewModelId] = useState('');
  const [addingModelLoading, setAddingModelLoading] = useState(false);

  const handleAddModel = async (provider: string) => {
    if (!newModelId.trim()) return;
    setAddingModelLoading(true);
    try {
      await marketplaceApi.addCustomModel({
        model_id: newModelId.trim(),
        model_name: newModelId.trim(),
        provider,
      });
      toast.success('Model added');
      setNewModelId('');
      setAddingModelProvider(null);
      onReloadModels();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to add model';
      const axiosErr = err as { response?: { data?: { detail?: string } } };
      toast.error(axiosErr.response?.data?.detail || message);
    } finally {
      setAddingModelLoading(false);
    }
  };

  const handleDeleteModel = async (customId: string) => {
    try {
      await marketplaceApi.deleteCustomModel(customId);
      toast.success('Model removed');
      onReloadModels();
    } catch {
      toast.error('Failed to remove model');
    }
  };

  const handleDeleteProvider = async (providerId: string) => {
    try {
      await secretsApi.deleteCustomProvider(providerId);
      toast.success('Custom provider deleted');
      onReloadProviders();
    } catch {
      toast.error('Failed to delete provider');
    }
  };

  // Filter models by search
  const filteredModels = models.filter(
    (m) =>
      !modelSearch ||
      m.name.toLowerCase().includes(modelSearch.toLowerCase()) ||
      m.id.toLowerCase().includes(modelSearch.toLowerCase())
  );

  // Group models by source/provider
  const systemModels = filteredModels.filter((m) => m.source === 'system');
  const providerModels = filteredModels.filter((m) => m.source === 'provider');
  const customModels = filteredModels.filter((m) => m.source === 'custom');

  const providerGroups: Record<string, { label: string; models: ModelInfo[] }> = {};
  for (const m of providerModels) {
    const key = m.provider;
    if (!providerGroups[key]) {
      providerGroups[key] = { label: getProviderLabel(m.provider, m.provider_name), models: [] };
    }
    providerGroups[key].models.push(m);
  }
  // Include providers that have API keys but no models yet
  for (const key of apiKeys) {
    const provider = key.provider;
    if (!providerGroups[provider] && provider !== 'internal') {
      providerGroups[provider] = { label: getProviderLabel(provider), models: [] };
    }
  }

  // Loading state
  if (byokEnabled === null) {
    return (
      <div className="flex items-center justify-center py-20">
        <LoadingSpinner />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div>
        <h2 className="text-2xl font-bold text-[var(--text)] mb-1">Models</h2>
        <p className="text-[var(--text-muted)]">Manage your AI models, API keys &amp; providers</p>
      </div>

      {/* ── Available Models Section ── */}
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded-[var(--radius-large)] p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-[var(--text)]">Available Models</h3>
          <div className="relative">
            <MagnifyingGlass
              size={14}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-subtle)]"
            />
            <input
              type="text"
              value={modelSearch}
              onChange={(e) => setModelSearch(e.target.value)}
              placeholder="Search models..."
              className="pl-8 pr-3 py-1.5 bg-[var(--bg)] border border-[var(--border)] rounded-[var(--radius-small)] text-sm text-[var(--text)] placeholder:text-[var(--text-subtle)] focus:outline-none focus:border-[var(--primary)] w-48"
            />
          </div>
        </div>

        {models.length === 0 ? (
          <div className="text-center py-10">
            <Cpu size={36} className="mx-auto mb-3 text-[var(--text-subtle)]" />
            <p className="text-sm text-[var(--text-muted)]">No models available</p>
          </div>
        ) : (
          <div className="space-y-5">
            {/* System models */}
            {systemModels.length > 0 && (
              <div>
                <h4 className="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-2.5">
                  Tesslate (System)
                </h4>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-2.5">
                  {systemModels.map((m) => (
                    <ModelCard key={m.id} model={m} onToggle={onToggleModel} />
                  ))}
                </div>
              </div>
            )}

            {/* Provider model groups */}
            {Object.entries(providerGroups).map(([key, group]) => (
              <div key={key}>
                <div className="flex items-center justify-between mb-2.5">
                  <h4 className="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-wider">
                    {group.label} (via API Key)
                  </h4>
                  <button
                    onClick={() => {
                      setAddingModelProvider(addingModelProvider === key ? null : key);
                      setNewModelId('');
                    }}
                    className="flex items-center gap-1 text-xs text-[var(--primary)] hover:text-[var(--primary-hover)] transition-colors"
                  >
                    <Plus size={14} /> Add Model
                  </button>
                </div>
                {addingModelProvider === key && (
                  <div className="flex items-center gap-2 mb-3">
                    <input
                      value={newModelId}
                      onChange={(e) => setNewModelId(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') handleAddModel(key);
                        if (e.key === 'Escape') {
                          setAddingModelProvider(null);
                          setNewModelId('');
                        }
                      }}
                      placeholder="e.g. gpt-4o-audio-preview"
                      autoFocus
                      className="flex-1 px-3 py-1.5 bg-[var(--bg)] border border-[var(--border)] rounded-[var(--radius-small)] text-sm text-[var(--text)] placeholder:text-[var(--text-subtle)] focus:outline-none focus:border-[var(--primary)]"
                    />
                    <button
                      onClick={() => handleAddModel(key)}
                      disabled={!newModelId.trim() || addingModelLoading}
                      className="px-3 py-1.5 bg-[var(--primary)] text-white text-sm rounded-[var(--radius-small)] hover:bg-[var(--primary-hover)] transition-colors disabled:opacity-50"
                    >
                      {addingModelLoading ? 'Adding...' : 'Add'}
                    </button>
                    <button
                      onClick={() => {
                        setAddingModelProvider(null);
                        setNewModelId('');
                      }}
                      className="px-3 py-1.5 bg-[var(--surface)] border border-[var(--border)] text-sm text-[var(--text-muted)] rounded-[var(--radius-small)] hover:text-[var(--text)] transition-colors"
                    >
                      Cancel
                    </button>
                  </div>
                )}
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-2.5">
                  {group.models.map((m) => (
                    <ModelCard
                      key={m.id}
                      model={m}
                      onToggle={onToggleModel}
                      onDelete={handleDeleteModel}
                    />
                  ))}
                </div>
              </div>
            ))}

            {/* Custom models (non-builtin providers) */}
            {customModels.length > 0 && (
              <div>
                <h4 className="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-2.5">
                  Custom Models
                </h4>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-2.5">
                  {customModels.map((m) => (
                    <ModelCard
                      key={m.id}
                      model={m}
                      onToggle={onToggleModel}
                      onDelete={handleDeleteModel}
                    />
                  ))}
                </div>
              </div>
            )}

            {/* No search results */}
            {filteredModels.length === 0 && modelSearch && (
              <p className="text-sm text-[var(--text-muted)] text-center py-4">
                No models matching &ldquo;{modelSearch}&rdquo;
              </p>
            )}
          </div>
        )}
      </div>

      {/* ── API Keys Section ── */}
      {byokEnabled === false ? (
        <div className="bg-[var(--surface)] border border-[var(--border)] rounded-[var(--radius-large)] p-5">
          <div className="flex flex-col items-center justify-center py-10 text-center">
            <div className="w-12 h-12 rounded-xl bg-[var(--primary)]/10 flex items-center justify-center mb-4">
              <LockKey size={24} className="text-[var(--primary)]" />
            </div>
            <h3 className="text-lg font-semibold text-[var(--text)] mb-1">Bring Your Own Key</h3>
            <p className="text-[var(--text-muted)] max-w-md mb-4 text-sm">
              Use your own API keys for OpenAI, Anthropic, and other providers. Available on all
              paid plans.
            </p>
            <button
              onClick={() => navigate('/settings/billing')}
              className="px-5 py-2.5 bg-[var(--primary)] hover:bg-[var(--primary)]/90 rounded-lg text-white font-medium transition-colors flex items-center gap-2"
            >
              <Rocket size={16} />
              Upgrade Plan
            </button>
          </div>
        </div>
      ) : (
        <div className="bg-[var(--surface)] border border-[var(--border)] rounded-[var(--radius-large)] p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold text-[var(--text)]">API Keys</h3>
            <button
              onClick={() => setShowAddModal(true)}
              className="px-3 py-1.5 bg-[var(--primary)] hover:bg-[var(--primary)]/90 rounded-lg text-white text-sm transition-colors flex items-center gap-2"
            >
              <Plus size={16} />
              Add Key
            </button>
          </div>

          {apiKeys.length === 0 ? (
            <div className="text-center py-10">
              <Key size={36} className="mx-auto mb-3 text-[var(--text-subtle)]" />
              <p className="text-sm text-[var(--text-muted)] mb-3">No API keys configured</p>
              <button
                onClick={() => setShowAddModal(true)}
                className="px-5 py-2.5 bg-[var(--primary)] hover:bg-[var(--primary)]/90 rounded-lg text-white text-sm transition-colors"
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
        </div>
      )}

      {/* ── Providers Section ── */}
      {byokEnabled !== false && (
        <div className="bg-[var(--surface)] border border-[var(--border)] rounded-[var(--radius-large)] p-5">
          {/* Custom Providers */}
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-lg font-semibold text-[var(--text)]">Providers</h3>
              <p className="text-sm text-[var(--text-muted)] mt-0.5">
                Connect Ollama, vLLM, or any OpenAI-compatible API
              </p>
            </div>
            <button
              onClick={() => {
                setEditingProvider(null);
                setShowProviderModal(true);
              }}
              className="px-3 py-1.5 bg-[var(--surface-hover)] hover:bg-[var(--border)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-muted)] hover:text-[var(--text)] transition-colors flex items-center gap-2"
            >
              <Plus size={16} />
              Add Provider
            </button>
          </div>

          {customProviders.length === 0 ? (
            <div className="text-center py-8">
              <Plugs size={32} className="mx-auto mb-2 text-[var(--text-subtle)]" />
              <p className="text-sm text-[var(--text-muted)] mb-1">No custom providers</p>
              <p className="text-xs text-[var(--text-subtle)]">
                Add a provider to use your own model endpoints
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {customProviders.map((cp) => (
                <CustomProviderCard
                  key={cp.id}
                  provider={cp}
                  onEdit={() => {
                    setEditingProvider(cp);
                    setShowProviderModal(true);
                  }}
                  onDelete={handleDeleteProvider}
                />
              ))}
            </div>
          )}

          {/* Tip Box */}
          <div className="mt-5 flex items-start gap-3 p-4 bg-[var(--info)]/10 border border-[var(--info)]/20 rounded-xl">
            <Info size={20} className="text-[var(--info)] flex-shrink-0 mt-0.5" />
            <p className="text-sm text-[var(--text-muted)]">
              <span className="font-medium text-[var(--text)]">Tip:</span> Want to use different
              models with a built-in provider? Create a custom provider using the same base URL and
              API type. You can find the base URL and available model IDs in your provider&apos;s
              API documentation.
            </p>
          </div>

          {/* Supported Providers Info */}
          <div className="mt-6">
            <h4 className="text-sm font-semibold text-[var(--text)] mb-3">Supported Providers</h4>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {providers.map((provider) => {
                const hasKey = apiKeys.some((k) => k.provider === provider.id);
                return (
                  <div
                    key={provider.id}
                    className="bg-[var(--bg)] border border-[var(--border)] rounded-lg p-3"
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <div
                        className={`w-2 h-2 rounded-full flex-shrink-0 ${hasKey ? 'bg-[var(--status-success)]' : 'bg-[var(--text-subtle)]'}`}
                      />
                      <h5 className="font-medium text-sm text-[var(--text)]">{provider.name}</h5>
                    </div>
                    <p className="text-xs text-[var(--text-muted)] mb-1">{provider.description}</p>
                    <div className="text-xs text-[var(--text-subtle)] capitalize">
                      {provider.auth_type.replace('_', ' ')}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* Add API Key Modal */}
      {showAddModal && (
        <AddApiKeyModal
          providers={providers}
          customProviders={customProviders}
          onClose={() => setShowAddModal(false)}
          onSuccess={() => {
            setShowAddModal(false);
            onReload();
            onReloadModels();
          }}
        />
      )}

      {/* Custom Provider Modal */}
      {showProviderModal && (
        <CustomProviderModal
          existing={editingProvider}
          onClose={() => {
            setShowProviderModal(false);
            setEditingProvider(null);
          }}
          onSuccess={() => {
            setShowProviderModal(false);
            setEditingProvider(null);
            onReloadProviders();
            onReloadModels();
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
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded-lg p-4 flex items-center justify-between">
      <div className="flex items-center gap-4">
        <div className="p-3 bg-[var(--accent)]/10 rounded-lg">
          <Key size={20} className="text-[var(--accent)]" />
        </div>
        <div>
          <div className="font-semibold text-[var(--text)] capitalize">{apiKey.provider}</div>
          {apiKey.key_name && (
            <div className="text-sm text-[var(--text-muted)]">{apiKey.key_name}</div>
          )}
          <div className="text-xs text-[var(--text-subtle)] font-mono mt-1">
            {apiKey.key_preview}
          </div>
          {apiKey.base_url && (
            <div className="text-xs text-[var(--text-subtle)] font-mono mt-0.5">
              {apiKey.base_url}
            </div>
          )}
          <div className="text-xs text-[var(--text-subtle)] mt-1">
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
          <div className="bg-[var(--surface)] border border-[var(--border)] rounded-lg p-6 max-w-md">
            <h3 className="text-lg font-semibold text-[var(--text)] mb-4">Delete API Key?</h3>
            <p className="text-[var(--text-muted)] mb-6">
              Are you sure you want to delete this {apiKey.provider} API key? This action cannot be
              undone.
            </p>
            <div className="flex items-center gap-3 justify-end">
              <button
                onClick={() => setShowDelete(false)}
                className="px-4 py-2 bg-[var(--surface-hover)] hover:bg-[var(--border)] rounded-lg text-[var(--text-muted)] transition-colors"
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
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded-xl max-w-md w-full p-6">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-2xl font-bold text-[var(--text)]">Add API Key</h2>
          <button
            onClick={onClose}
            className="p-2 hover:bg-[var(--surface-hover)] rounded-lg transition-colors text-[var(--text-muted)]"
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
              className="w-full px-4 py-2 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-[var(--text)] focus:outline-none focus:border-[var(--primary)]/50 [&>option]:bg-[var(--surface)] [&>option]:text-[var(--text)]"
              required
            >
              <option value="">Select a provider...</option>
              <optgroup label="Built-in Providers">
                {providers
                  .filter((p) => p.requires_key)
                  .map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
              </optgroup>
              {customProviders.length > 0 && (
                <optgroup label="Custom Providers">
                  {customProviders.map((p) => (
                    <option key={p.slug} value={p.slug}>
                      {p.name}
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
                className="w-full px-4 py-2 pr-12 bg-[var(--bg)] border border-[var(--border)] rounded-lg text-[var(--text)] focus:outline-none focus:border-[var(--primary)]/50 font-mono text-sm"
                placeholder="sk-..."
                required
              />
              <button
                type="button"
                onClick={() => setShowKey(!showKey)}
                className="absolute right-3 top-1/2 -translate-y-1/2 p-1 hover:bg-[var(--surface-hover)] rounded transition-colors text-[var(--text-muted)]"
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
              className="w-full px-4 py-2 bg-[var(--bg)] border border-[var(--border)] rounded-lg text-[var(--text)] focus:outline-none focus:border-[var(--primary)]/50"
              placeholder="My API Key"
            />
            <p className="mt-1 text-xs text-[var(--text-subtle)]">
              Useful if you have multiple keys for the same provider
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
                className="w-full px-4 py-2 bg-[var(--bg)] border border-[var(--border)] rounded-lg text-[var(--text)] focus:outline-none focus:border-[var(--primary)]/50 font-mono text-sm"
                placeholder={selectedCustomProvider?.base_url || 'https://api.example.com/v1'}
              />
              <p className="mt-1 text-xs text-[var(--text-subtle)]">
                Override the provider's default base URL for this key
              </p>
            </div>
          )}

          <div className="flex items-center gap-3 justify-end pt-4 border-t border-[var(--border)]">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 bg-[var(--surface-hover)] hover:bg-[var(--border)] rounded-lg text-[var(--text-muted)] transition-colors"
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

function AgentCard({
  agent,
  onToggleEnable,
  onEdit,
  onTogglePublish,
  onRemove,
  onDelete,
}: {
  agent: LibraryAgent;
  onToggleEnable: () => void;
  onEdit: () => void;
  onTogglePublish: () => void;
  onRemove: () => void;
  onDelete: () => void;
}) {
  const canEdit = agent.source_type === 'open' || agent.is_custom;

  return (
    <CardSurface
      isDisabled={!agent.is_enabled}
      role="article"
      aria-label={`${agent.name} agent${agent.is_enabled ? '' : ' (disabled)'}`}
    >
      {/* Header: avatar + title + status */}
      <CardHeader
        icon={
          agent.avatar_url ? (
            <img
              src={agent.avatar_url}
              alt=""
              className="w-11 h-11 sm:w-12 sm:h-12 rounded-xl object-cover border border-[var(--border)] shrink-0 transition-colors group-hover:border-[rgba(var(--primary-rgb),0.3)]"
            />
          ) : (
            <div className="w-11 h-11 sm:w-12 sm:h-12 rounded-xl bg-[var(--bg)] border border-[var(--border)] flex items-center justify-center p-2.5 shrink-0 transition-colors group-hover:border-[rgba(var(--primary-rgb),0.3)]">
              <img src="/favicon.svg" alt="" className="w-full h-full" />
            </div>
          )
        }
        title={agent.name}
        subtitle={agent.creator_username ? `@${agent.creator_username}` : agent.category}
        trailing={<StatusDot active={agent.is_enabled} />}
      />

      {/* Description */}
      <p className="text-xs sm:text-[13px] leading-relaxed text-[var(--text-muted)] line-clamp-2 mb-3 min-h-[32px]">
        {agent.description}
      </p>

      {/* Badges, model & tools row */}
      <div className="flex flex-wrap items-center gap-1.5 mb-0">
        {agent.source_type === 'open' ? (
          <Badge intent="success" icon={<LockSimpleOpen size={11} />}>Open</Badge>
        ) : (
          <Badge intent="accent" icon={<LockKey size={11} />}>Closed</Badge>
        )}
        {agent.is_custom && (
          <Badge intent="primary" icon={<GitFork size={11} />}>Custom</Badge>
        )}
        {agent.parent_agent_id && (
          <Badge intent="info" icon={<GitFork size={11} />}>Forked</Badge>
        )}
        {/* Compact model display */}
        <Badge intent="muted" icon={<Cpu size={11} />}>
          <span className="truncate max-w-[80px]">{agent.selected_model || agent.model}</span>
          {canEdit && (
            <button
              onClick={(e) => { e.stopPropagation(); onEdit(); }}
              className="ml-0.5 text-[var(--text-subtle)] hover:text-[var(--primary)] transition-colors"
              title="Edit model"
            >
              <Pencil size={10} />
            </button>
          )}
        </Badge>
        {/* Tools */}
        {!agent.tools || agent.tools.length === 0 ? (
          <Badge intent="info" icon={<Wrench size={11} />}>All Tools</Badge>
        ) : (
          agent.tools.map((toolName, idx) => {
            const tool = getToolIcon(toolName);
            if (!tool) return null;
            return (
              <Badge key={idx} intent="primary" icon={tool.icon}>
                {tool.label}
              </Badge>
            );
          })
        )}
      </div>

      {/* Actions */}
      <CardActions>
        {canEdit && (
          <button
            onClick={onEdit}
            aria-label={`Edit ${agent.name}`}
            className="flex items-center justify-center sm:justify-start gap-1.5 px-3 py-2 sm:py-1.5 bg-[var(--primary)]/10 border border-[var(--primary)]/20 text-[var(--primary)] hover:bg-[var(--primary)]/20 active:bg-[var(--primary)]/30 active:scale-[0.97] rounded-lg text-xs font-medium transition-all hover:shadow-sm min-h-[36px] sm:min-h-0"
          >
            <Pencil size={14} />
            Edit
          </button>
        )}
        {agent.is_custom && (
          <button
            onClick={onTogglePublish}
            aria-label={agent.is_published ? `Unpublish ${agent.name}` : `Publish ${agent.name}`}
            className={`flex items-center justify-center sm:justify-start gap-1.5 px-3 py-2 sm:py-1.5 rounded-lg text-xs transition-all active:scale-[0.97] min-h-[36px] sm:min-h-0 ${
              agent.is_published
                ? 'bg-[var(--status-success)]/10 border border-[var(--status-success)]/20 text-[var(--status-success)] hover:bg-[var(--status-success)]/20'
                : 'bg-[var(--surface)] border border-[var(--border)] text-[var(--text-subtle)] hover:bg-[var(--surface-hover)]'
            }`}
          >
            {agent.is_published ? <Eye size={14} /> : <EyeSlash size={14} />}
            {agent.is_published ? 'Published' : 'Publish'}
          </button>
        )}
        <button
          onClick={onToggleEnable}
          aria-label={agent.is_enabled ? `Disable ${agent.name}` : `Enable ${agent.name}`}
          className={`flex items-center justify-center sm:justify-start gap-1.5 px-3 py-2 sm:py-1.5 rounded-lg text-xs transition-all active:scale-[0.97] min-h-[36px] sm:min-h-0 ${
            agent.is_enabled
              ? 'bg-[var(--surface)] border border-[var(--border)] text-[var(--text-subtle)] hover:bg-[var(--surface-hover)]'
              : 'bg-[var(--status-success)]/10 border border-[var(--status-success)]/20 text-[var(--status-success)] hover:bg-[var(--status-success)]/20'
          }`}
        >
          {agent.is_enabled ? <Power size={14} /> : <Power size={14} />}
          {agent.is_enabled ? 'Disable' : 'Enable'}
        </button>

        {/* Delete or Remove */}
        {agent.is_custom && !agent.is_published ? (
          <button
            onClick={onDelete}
            aria-label={`Delete ${agent.name}`}
            className="flex items-center justify-center sm:justify-start gap-1.5 px-3 py-2 sm:py-1.5 text-[var(--error)] hover:bg-[var(--error)]/10 active:bg-[var(--error)]/15 active:scale-[0.97] rounded-lg text-xs transition-all sm:ml-auto min-h-[36px] sm:min-h-0"
          >
            <Trash size={14} />
            Delete
          </button>
        ) : (
          <button
            onClick={onRemove}
            aria-label={`Remove ${agent.name} from library`}
            className="flex items-center justify-center sm:justify-start gap-1.5 px-3 py-2 sm:py-1.5 text-[var(--text-subtle)] hover:text-[var(--error)] hover:bg-[var(--error)]/10 active:bg-[var(--error)]/15 active:scale-[0.97] rounded-lg text-xs transition-all sm:ml-auto min-h-[36px] sm:min-h-0"
          >
            <XCircle size={14} />
            Remove
          </button>
        )}
      </CardActions>
    </CardSurface>
  );
}

// Feature flag definitions with descriptions
const FEATURE_FLAGS = [
  { key: 'streaming', label: 'Streaming', description: 'SSE token streaming' },
  { key: 'subagents', label: 'Subagents', description: 'Invoke specialized subagents' },
  { key: 'plan_mode', label: 'Plan Mode', description: 'save_plan / update_plan tools' },
  { key: 'web_search', label: 'Web Search', description: 'web_fetch tool' },
  { key: 'apply_patch', label: 'Apply Patch', description: 'Unified diff patches' },
] as const;

// Subagent type for the UI
interface SubagentItem {
  id: string;
  name: string;
  description: string;
  system_prompt: string;
  tools: string[];
  model: string;
  is_builtin: boolean;
}

// Category-to-icon mapping for skills (replaces emoji icons)
const SKILL_CATEGORY_ICONS: Record<string, React.ReactNode> = {
  frontend: <Code size={20} weight="duotone" />,
  design: <PaintBucket size={20} weight="duotone" />,
  backend: <Broadcast size={20} weight="duotone" />,
  testing: <TestTube size={20} weight="duotone" />,
  database: <Database size={20} weight="duotone" />,
  security: <Shield size={20} weight="duotone" />,
  media: <FilmStrip size={20} weight="duotone" />,
  'code-quality': <Sparkle size={20} weight="duotone" />,
  deployment: <Rocket size={20} weight="duotone" />,
  devops: <Stack size={20} weight="duotone" />,
};

function getSkillCategoryIcon(category: string): React.ReactNode {
  return SKILL_CATEGORY_ICONS[category] || <Lightning size={20} weight="duotone" />;
}

// MCP Servers Tab Component
function McpServersTab({
  servers,
  agents,
  loading,
  onReload,
  onBrowse,
}: {
  servers: InstalledMcpServer[];
  agents: LibraryAgent[];
  loading: boolean;
  onReload: () => void;
  onBrowse: () => void;
}) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <LoadingSpinner />
      </div>
    );
  }

  const activeCount = servers.filter((s) => s.is_active).length;
  const inactiveCount = servers.filter((s) => !s.is_active).length;

  return (
    <>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h3 className="text-sm font-semibold text-[var(--text)]">Installed MCP Servers</h3>
          <p className="text-xs text-[var(--text-muted)] mt-1">
            MCP servers extend your agents with external tool integrations and data sources
          </p>
        </div>
        <button
          onClick={onBrowse}
          className="flex items-center gap-2 px-4 py-2 bg-[var(--primary)] text-white rounded-xl text-sm font-medium hover:opacity-90 transition-all"
        >
          <Plus size={16} />
          Browse MCP Servers
        </button>
      </div>

      {servers.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <div className="w-16 h-16 bg-[var(--surface)] rounded-2xl flex items-center justify-center mb-4 border border-[var(--border)]">
            <Plugs size={32} className="text-[var(--text-subtle)]" />
          </div>
          <h3 className="text-lg font-semibold text-[var(--text)] mb-2">No MCP servers yet</h3>
          <p className="text-sm text-[var(--text-muted)] max-w-sm mb-6">
            MCP servers connect your agents to external tools, APIs, and data sources.
            Browse the marketplace to find and install MCP servers.
          </p>
          <button
            onClick={onBrowse}
            className="flex items-center gap-2 px-5 py-2.5 bg-[var(--primary)] text-white rounded-xl text-sm font-medium hover:opacity-90 transition-all"
          >
            <Plus size={16} />
            Browse MCP Servers Marketplace
          </button>
        </div>
      ) : (
        <>
          {/* Stats */}
          <div className="grid grid-cols-3 gap-4 mb-6">
            <StatCard value={servers.length} label="Total Servers" index={0} />
            <StatCard value={activeCount} label="Active" index={1} />
            <StatCard value={inactiveCount} label="Inactive" index={2} />
          </div>

          {/* Servers Grid */}
          <motion.div variants={staggerContainer} initial="initial" animate="animate" className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {servers.map((server) => (
              <McpServerCard key={server.id} server={server} agents={agents} onReload={onReload} />
            ))}
          </motion.div>
        </>
      )}
    </>
  );
}

// Individual MCP server card — matches SkillCard design
function McpServerCard({ server, agents, onReload }: { server: InstalledMcpServer; agents: LibraryAgent[]; onReload: () => void }) {
  const [showDropdown, setShowDropdown] = useState(false);
  const [assigning, setAssigning] = useState(false);
  const [showCredentials, setShowCredentials] = useState(false);
  const [showDetails, setShowDetails] = useState(false);
  const [credentialValues, setCredentialValues] = useState<Record<string, string>>({});
  const [savingCredentials, setSavingCredentials] = useState(false);
  const [discoveryResult, setDiscoveryResult] = useState<{ tools?: { name: string; description: string }[]; resources?: { uri: string; name: string; description?: string }[]; prompts?: { name: string; description: string }[] } | null>(null);
  const [discovering, setDiscovering] = useState(false);
  const [testingId, setTestingId] = useState(false);
  const [uninstalling, setUninstalling] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Close dropdown on outside click
  useEffect(() => {
    if (!showDropdown) return;
    const handleClick = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setShowDropdown(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [showDropdown]);

  const handleAssign = async (agentId: string, agentName: string) => {
    setAssigning(true);
    try {
      await marketplaceApi.assignMcpToAgent(server.id, agentId);
      toast.success(`${server.server_name || server.server_slug} added to ${agentName}`);
      setShowDropdown(false);
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to assign MCP server');
    } finally {
      setAssigning(false);
    }
  };

  const handleSaveCredentials = async () => {
    setSavingCredentials(true);
    try {
      await marketplaceApi.updateMcpServer(server.id, { credentials: credentialValues });
      toast.success('Credentials saved');
      setShowCredentials(false);
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to save credentials');
    } finally {
      setSavingCredentials(false);
    }
  };

  const handleDiscover = async () => {
    if (discoveryResult) { setShowDetails(!showDetails); return; }
    setShowDetails(true);
    setDiscovering(true);
    try {
      const result = await marketplaceApi.discoverMcpServer(server.id);
      setDiscoveryResult(result);
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Discovery failed');
      setShowDetails(false);
    } finally {
      setDiscovering(false);
    }
  };

  const handleTestConnection = async () => {
    setTestingId(true);
    try {
      const result = await marketplaceApi.testMcpServer(server.id);
      if (result.success) {
        toast.success('Connection successful');
      } else {
        toast.error(result.error || 'Connection failed');
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Connection test failed');
    } finally {
      setTestingId(false);
    }
  };

  const handleUninstall = async () => {
    setUninstalling(true);
    try {
      await marketplaceApi.uninstallMcpServer(server.id);
      toast.success('MCP server uninstalled');
      onReload();
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to uninstall MCP server');
    } finally {
      setUninstalling(false);
    }
  };

  const enabledAgents = agents.filter(a => a.is_enabled !== false);
  const hasEnvVars = server.env_vars && server.env_vars.length > 0;

  return (
    <CardSurface
      role="article"
      aria-label={`${server.server_name || server.server_slug || 'MCP'} MCP server`}
    >
      {/* Header: icon + title */}
      <CardHeader
        icon={
          <div className="w-11 h-11 sm:w-12 sm:h-12 rounded-xl bg-[var(--bg)] border border-[var(--border)] flex items-center justify-center shrink-0 text-[var(--primary)] transition-colors group-hover:border-[rgba(var(--primary-rgb),0.3)]">
            <Plugs size={20} weight="duotone" />
          </div>
        }
        title={server.server_name || server.server_slug || 'MCP Server'}
        subtitle={<span className="font-mono">{server.server_slug}</span>}
      />

      {/* Status badge */}
      <div className="flex items-center gap-2 mb-3">
        {server.is_active ? (
          <Badge intent="success" icon={<span className="w-1.5 h-1.5 rounded-full bg-[var(--status-success)]" />}>Active</Badge>
        ) : (
          <Badge intent="muted" icon={<span className="w-1.5 h-1.5 rounded-full bg-[var(--text-subtle)]" />}>Inactive</Badge>
        )}
      </div>

      {/* Actions bar */}
      <div className="flex items-center gap-1 mb-3">
        <button
          onClick={() => handleTestConnection()}
          disabled={testingId}
          className="flex items-center gap-1 px-2 py-1.5 text-[11px] font-medium text-[var(--text-muted)] hover:text-[var(--primary)] hover:bg-[var(--surface-hover)] rounded-lg transition-colors disabled:opacity-50"
        >
          <TestTube size={13} />
          {testingId ? 'Testing...' : 'Test'}
        </button>
        {hasEnvVars && (
          <button
            onClick={() => setShowCredentials(!showCredentials)}
            className={`flex items-center gap-1 px-2 py-1.5 text-[11px] font-medium rounded-lg transition-colors ${showCredentials ? 'text-[var(--primary)] bg-[var(--primary)]/10' : 'text-[var(--text-muted)] hover:text-[var(--primary)] hover:bg-[var(--surface-hover)]'}`}
          >
            <Key size={13} />
            Credentials
          </button>
        )}
        <button
          onClick={handleDiscover}
          className={`flex items-center gap-1 px-2 py-1.5 text-[11px] font-medium rounded-lg transition-colors ${showDetails ? 'text-[var(--primary)] bg-[var(--primary)]/10' : 'text-[var(--text-muted)] hover:text-[var(--primary)] hover:bg-[var(--surface-hover)]'}`}
        >
          <Info size={13} />
          Details
        </button>
        <button
          onClick={handleUninstall}
          disabled={uninstalling}
          className="flex items-center gap-1 px-2 py-1.5 text-[11px] font-medium text-[var(--text-muted)] hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors disabled:opacity-50 ml-auto"
        >
          <Trash size={13} />
          {uninstalling ? 'Removing...' : 'Uninstall'}
        </button>
      </div>

      {/* Credentials section */}
      {showCredentials && hasEnvVars && (
        <div className="mb-3 p-3 bg-[var(--bg)] rounded-lg border border-[var(--border)]">
          <p className="text-[11px] text-[var(--text-muted)] mb-2 font-medium">Server Credentials</p>
          {server.env_vars!.map((key) => (
            <div key={key} className="mb-2">
              <label className="text-[10px] text-[var(--text-subtle)] font-mono">{key}</label>
              <input
                type="password"
                placeholder={`Enter ${key}`}
                value={credentialValues[key] || ''}
                onChange={(e) => setCredentialValues(prev => ({ ...prev, [key]: e.target.value }))}
                className="w-full mt-0.5 px-2 py-1.5 text-xs bg-[var(--surface)] border border-[var(--border)] rounded-lg text-[var(--text)] placeholder:text-[var(--text-subtle)] focus:outline-none focus:border-[var(--primary)]"
              />
            </div>
          ))}
          <button
            onClick={handleSaveCredentials}
            disabled={savingCredentials}
            className="w-full mt-1 px-3 py-1.5 text-xs font-medium bg-[var(--primary)] text-white rounded-lg hover:opacity-90 transition-colors disabled:opacity-50"
          >
            {savingCredentials ? 'Saving...' : 'Save Credentials'}
          </button>
        </div>
      )}

      {/* Details / Discovery section */}
      {showDetails && (
        <div className="mb-3 p-3 bg-[var(--bg)] rounded-lg border border-[var(--border)]">
          {discovering ? (
            <div className="flex items-center justify-center py-4">
              <LoadingSpinner />
            </div>
          ) : discoveryResult ? (
            <div className="space-y-2">
              {discoveryResult.tools && discoveryResult.tools.length > 0 && (
                <div>
                  <p className="text-[11px] font-medium text-[var(--text-muted)] mb-1">Tools ({discoveryResult.tools.length})</p>
                  {discoveryResult.tools.map((t) => (
                    <div key={t.name} className="flex items-start gap-1.5 py-1">
                      <Wrench size={11} className="text-[var(--text-subtle)] mt-0.5 shrink-0" />
                      <div>
                        <p className="text-[11px] font-medium text-[var(--text)] font-mono">{t.name}</p>
                        {t.description && <p className="text-[10px] text-[var(--text-muted)]">{t.description}</p>}
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {discoveryResult.resources && discoveryResult.resources.length > 0 && (
                <div>
                  <p className="text-[11px] font-medium text-[var(--text-muted)] mb-1">Resources ({discoveryResult.resources.length})</p>
                  {discoveryResult.resources.map((r) => (
                    <div key={r.uri} className="flex items-start gap-1.5 py-1">
                      <Database size={11} className="text-[var(--text-subtle)] mt-0.5 shrink-0" />
                      <div>
                        <p className="text-[11px] font-medium text-[var(--text)] font-mono">{r.name}</p>
                        <p className="text-[10px] text-[var(--text-subtle)] font-mono">{r.uri}</p>
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {discoveryResult.prompts && discoveryResult.prompts.length > 0 && (
                <div>
                  <p className="text-[11px] font-medium text-[var(--text-muted)] mb-1">Prompts ({discoveryResult.prompts.length})</p>
                  {discoveryResult.prompts.map((p) => (
                    <div key={p.name} className="flex items-start gap-1.5 py-1">
                      <ChatCircleDots size={11} className="text-[var(--text-subtle)] mt-0.5 shrink-0" />
                      <div>
                        <p className="text-[11px] font-medium text-[var(--text)]">{p.name}</p>
                        {p.description && <p className="text-[10px] text-[var(--text-muted)]">{p.description}</p>}
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {(!discoveryResult.tools || discoveryResult.tools.length === 0) && (!discoveryResult.resources || discoveryResult.resources.length === 0) && (!discoveryResult.prompts || discoveryResult.prompts.length === 0) && (
                <p className="text-[11px] text-[var(--text-muted)] text-center py-2">No capabilities discovered</p>
              )}
            </div>
          ) : null}
        </div>
      )}

      {/* Spacer */}
      <div className="flex-1" />

      {/* Add to Agent action */}
      <div ref={dropdownRef} className="relative mt-1">
        <button
          onClick={() => setShowDropdown(!showDropdown)}
          disabled={assigning}
          className="w-full flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg bg-[var(--primary)]/10 text-[var(--primary)] hover:bg-[var(--primary)]/20 transition-colors disabled:opacity-50"
        >
          {assigning ? (
            <LoadingSpinner />
          ) : (
            <>
              <Plugs size={14} />
              Add to Agent
            </>
          )}
        </button>
        {showDropdown && (
          <div className="absolute left-0 right-0 bottom-full mb-1 bg-[var(--surface)] border border-[var(--border)] rounded-xl shadow-xl z-20 py-1.5 max-h-52 overflow-y-auto">
            {enabledAgents.length === 0 ? (
              <p className="px-3 py-3 text-xs text-[var(--text-muted)] text-center">
                No active agents. Enable an agent first.
              </p>
            ) : (
              enabledAgents.map((agent) => (
                <button
                  key={agent.id}
                  onClick={() => handleAssign(agent.id, agent.name)}
                  className="w-full text-left px-3 py-2 text-xs text-[var(--text)] hover:bg-[var(--primary)]/5 transition-colors flex items-center gap-2.5"
                >
                  {agent.avatar_url ? (
                    <img src={agent.avatar_url} alt="" className="w-6 h-6 rounded-lg object-cover border border-[var(--border)]" />
                  ) : (
                    <div className="w-6 h-6 rounded-lg bg-[var(--bg)] border border-[var(--border)] flex items-center justify-center">
                      <img src="/favicon.svg" alt="" className="w-4 h-4" />
                    </div>
                  )}
                  <span className="truncate font-medium">{agent.name}</span>
                </button>
              ))
            )}
          </div>
        )}
      </div>
    </CardSurface>
  );
}

// Skills Tab Component
function SkillsTab({
  skills,
  agents,
  loading,
  onBrowse,
}: {
  skills: LibrarySkill[];
  agents: LibraryAgent[];
  loading: boolean;
  onBrowse: () => void;
}) {
  const dropdownRef = useRef<HTMLDivElement>(null);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <LoadingSpinner />
      </div>
    );
  }

  const openSourceCount = skills.filter(s => s.source_type === 'open' && s.git_repo_url).length;
  const categoryCount = new Set(skills.map(s => s.category)).size;

  return (
    <>
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h3 className="text-sm font-semibold text-[var(--text)]">Installed Skills</h3>
          <p className="text-xs text-[var(--text-muted)] mt-1">
            Skills extend your agents with specialized knowledge and workflows
          </p>
        </div>
        <button
          onClick={onBrowse}
          className="flex items-center gap-2 px-4 py-2 bg-[var(--primary)] text-white rounded-xl text-sm font-medium hover:opacity-90 transition-all"
        >
          <Plus size={16} />
          Browse Skills
        </button>
      </div>

      {skills.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <div className="w-16 h-16 bg-[var(--surface)] rounded-2xl flex items-center justify-center mb-4 border border-[var(--border)]">
            <Lightning size={32} className="text-[var(--text-subtle)]" />
          </div>
          <h3 className="text-lg font-semibold text-[var(--text)] mb-2">No skills yet</h3>
          <p className="text-sm text-[var(--text-muted)] max-w-sm mb-6">
            Skills teach your agents specialized patterns and best practices.
            Browse the marketplace to find skills for frontend, backend, DevOps, and more.
          </p>
          <button
            onClick={onBrowse}
            className="flex items-center gap-2 px-5 py-2.5 bg-[var(--primary)] text-white rounded-xl text-sm font-medium hover:opacity-90 transition-all"
          >
            <Plus size={16} />
            Browse Skills Marketplace
          </button>
        </div>
      ) : (
        <>
          {/* Stats */}
          <div className="grid grid-cols-3 gap-4 mb-6">
            <StatCard value={skills.length} label="Total Skills" index={0} />
            <StatCard value={openSourceCount} label="Open Source" index={1} />
            <StatCard value={categoryCount} label="Categories" index={2} />
          </div>

          {/* Skills Grid */}
          <motion.div ref={dropdownRef} variants={staggerContainer} initial="initial" animate="animate" className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {skills.map((skill) => (
              <SkillCard key={skill.id} skill={skill} agents={agents} />
            ))}
          </motion.div>
        </>
      )}
    </>
  );
}

// Individual skill card — matches AgentsTab card design
function SkillCard({ skill, agents }: { skill: LibrarySkill; agents: LibraryAgent[] }) {
  const [showDropdown, setShowDropdown] = useState(false);
  const [installing, setInstalling] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Close dropdown on outside click
  useEffect(() => {
    if (!showDropdown) return;
    const handleClick = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setShowDropdown(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [showDropdown]);

  const handleInstall = async (agentId: string, agentName: string) => {
    setInstalling(true);
    try {
      await marketplaceApi.installSkillOnAgent(skill.id, agentId);
      toast.success(`${skill.name} added to ${agentName}`);
      setShowDropdown(false);
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to install skill');
    } finally {
      setInstalling(false);
    }
  };

  const enabledAgents = agents.filter(a => a.is_enabled !== false);

  return (
    <CardSurface
      role="article"
      aria-label={`${skill.name} skill`}
    >
      {/* Header: icon + title */}
      <CardHeader
        icon={
          <div className="w-11 h-11 sm:w-12 sm:h-12 rounded-xl bg-[var(--bg)] border border-[var(--border)] flex items-center justify-center shrink-0 text-[var(--primary)] transition-colors group-hover:border-[rgba(var(--primary-rgb),0.3)]">
            {getSkillCategoryIcon(skill.category)}
          </div>
        }
        title={skill.name}
        subtitle={<span className="capitalize">{skill.category}</span>}
      />

      {/* Description */}
      <p className="text-xs sm:text-[13px] leading-relaxed text-[var(--text-muted)] line-clamp-2 mb-3 min-h-[32px]">
        {skill.description}
      </p>

      {/* Badges row */}
      <div className="flex flex-wrap items-center gap-1.5 mb-3">
        {skill.source_type === 'open' ? (
          <Badge intent="success" icon={<LockSimpleOpen size={11} />}>Open</Badge>
        ) : (
          <Badge intent="accent" icon={<LockKey size={11} />}>Closed</Badge>
        )}
        {skill.pricing_type === 'free' && (
          <Badge intent="success">Free</Badge>
        )}
        {skill.features && skill.features.length > 0 && (
          <>
            {skill.features.slice(0, 2).map((feature, i) => (
              <Badge key={i} intent="muted">{feature}</Badge>
            ))}
            {skill.features.length > 2 && (
              <span className="px-1.5 py-0.5 text-[var(--text-subtle)] text-[11px] font-medium">
                +{skill.features.length - 2}
              </span>
            )}
          </>
        )}
      </div>

      {/* GitHub repo link */}
      {skill.git_repo_url && (
        <a
          href={skill.git_repo_url}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1.5 text-[11px] text-[var(--text-muted)] hover:text-[var(--primary)] transition-colors mb-3"
          onClick={(e) => e.stopPropagation()}
        >
          <GithubLogo size={13} weight="fill" />
          <span className="truncate">{skill.git_repo_url.replace('https://github.com/', '')}</span>
          <ArrowSquareOut size={10} className="shrink-0 opacity-0 group-hover:opacity-100 transition-opacity" />
        </a>
      )}

      {/* Spacer to push action to bottom */}
      <div className="flex-1" />

      {/* Add to Agent action */}
      <div ref={dropdownRef} className="relative mt-1">
        <button
          onClick={() => setShowDropdown(!showDropdown)}
          disabled={installing}
          className="w-full flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium rounded-lg bg-[var(--primary)]/10 text-[var(--primary)] hover:bg-[var(--primary)]/20 transition-colors disabled:opacity-50"
        >
          {installing ? (
            <LoadingSpinner />
          ) : (
            <>
              <Plugs size={14} />
              Add to Agent
            </>
          )}
        </button>
        {showDropdown && (
          <div className="absolute left-0 right-0 bottom-full mb-1 bg-[var(--surface)] border border-[var(--border)] rounded-xl shadow-xl z-20 py-1.5 max-h-52 overflow-y-auto">
            {enabledAgents.length === 0 ? (
              <p className="px-3 py-3 text-xs text-[var(--text-muted)] text-center">
                No active agents. Enable an agent first.
              </p>
            ) : (
              enabledAgents.map((agent) => (
                <button
                  key={agent.id}
                  onClick={() => handleInstall(agent.id, agent.name)}
                  className="w-full text-left px-3 py-2 text-xs text-[var(--text)] hover:bg-[var(--primary)]/5 transition-colors flex items-center gap-2.5"
                >
                  {agent.avatar_url ? (
                    <img src={agent.avatar_url} alt="" className="w-6 h-6 rounded-lg object-cover border border-[var(--border)]" />
                  ) : (
                    <div className="w-6 h-6 rounded-lg bg-[var(--bg)] border border-[var(--border)] flex items-center justify-center">
                      <img src="/favicon.svg" alt="" className="w-4 h-4" />
                    </div>
                  )}
                  <span className="truncate font-medium">{agent.name}</span>
                </button>
              ))
            )}
          </div>
        )}
      </div>
    </CardSurface>
  );
}

// Edit Agent Modal Component
function EditAgentModal({
  agent,
  onClose,
  onSave,
}: {
  agent: LibraryAgent;
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
    config?: Record<string, unknown>;
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

  // Feature flags state — default all enabled
  const defaultFeatures: Record<string, boolean> = {};
  FEATURE_FLAGS.forEach((f) => {
    defaultFeatures[f.key] = true;
  });
  const [features, setFeatures] = useState<Record<string, boolean>>({
    ...defaultFeatures,
    ...(agent.config?.features || {}),
  });

  // Subagents state
  const [subagents, setSubagents] = useState<SubagentItem[]>([]);
  const [subagentsExpanded, setSubagentsExpanded] = useState(false);
  const [subagentsLoading, setSubagentsLoading] = useState(false);
  const [editingSubagent, setEditingSubagent] = useState<string | null>(null);
  const [editingSubagentPrompt, setEditingSubagentPrompt] = useState('');
  const [showAddSubagent, setShowAddSubagent] = useState(false);
  const [newSubagent, setNewSubagent] = useState({
    name: '',
    description: '',
    system_prompt: '',
  });

  // Skills state
  const [agentSkills, setAgentSkills] = useState<{ id: string; name: string; description: string; slug: string }[]>([]);
  const [skillsExpanded, setSkillsExpanded] = useState(false);
  const [skillsLoading, setSkillsLoading] = useState(false);
  const [showSkillSearch, setShowSkillSearch] = useState(false);
  const [skillSearchQuery, setSkillSearchQuery] = useState('');
  const [skillSearchResults, setSkillSearchResults] = useState<{ id: string; name: string; description: string; slug: string; category: string }[]>([]);
  const [skillSearchLoading, setSkillSearchLoading] = useState(false);

  // Load subagents when section is expanded
  useEffect(() => {
    if (subagentsExpanded && agent.id && subagents.length === 0) {
      setSubagentsLoading(true);
      marketplaceApi
        .getSubagents(agent.id)
        .then((data) => {
          setSubagents(data.subagents || []);
        })
        .catch((err) => {
          console.error('Failed to load subagents:', err);
        })
        .finally(() => setSubagentsLoading(false));
    }
  }, [subagentsExpanded, agent.id, subagents.length]);

  // Load skills when section is expanded
  useEffect(() => {
    if (skillsExpanded && agent.id && agentSkills.length === 0) {
      setSkillsLoading(true);
      marketplaceApi
        .getAgentSkills(agent.id)
        .then((data) => {
          setAgentSkills((data.skills || []).map((s: { id: string; name: string; description: string; slug: string }) => ({
            id: s.id,
            name: s.name,
            description: s.description,
            slug: s.slug,
          })));
        })
        .catch((err) => {
          console.error('Failed to load agent skills:', err);
        })
        .finally(() => setSkillsLoading(false));
    }
  }, [skillsExpanded, agent.id, agentSkills.length]);

  const toggleFeature = (key: string) => {
    setFeatures((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const handleReset = () => {
    setSystemPrompt(originalPrompt);
    toast.success('Reset to original system prompt');
  };

  const insertMarker = (marker: string) => {
    editorRef.current?.insertMarker(marker);
  };

  const handleSaveSubagentPrompt = async (subagentId: string) => {
    try {
      await marketplaceApi.updateSubagent(agent.id, subagentId, {
        system_prompt: editingSubagentPrompt,
      });
      setSubagents((prev) =>
        prev.map((s) => (s.id === subagentId ? { ...s, system_prompt: editingSubagentPrompt } : s))
      );
      setEditingSubagent(null);
      toast.success('Subagent prompt updated');
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to update subagent');
    }
  };

  const handleAddSubagent = async () => {
    if (!newSubagent.name.trim() || !newSubagent.system_prompt.trim()) {
      toast.error('Name and system prompt are required');
      return;
    }
    try {
      const created = await marketplaceApi.createSubagent(agent.id, {
        name: newSubagent.name,
        description: newSubagent.description,
        system_prompt: newSubagent.system_prompt,
      });
      setSubagents((prev) => [...prev, created]);
      setShowAddSubagent(false);
      setNewSubagent({ name: '', description: '', system_prompt: '' });
      toast.success('Subagent created');
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to create subagent');
    }
  };

  const handleDeleteSubagent = async (subagentId: string) => {
    try {
      await marketplaceApi.deleteSubagent(agent.id, subagentId);
      setSubagents((prev) => prev.filter((s) => s.id !== subagentId));
      toast.success('Subagent removed');
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to delete subagent');
    }
  };

  const handleSearchSkills = async (query: string) => {
    setSkillSearchQuery(query);
    if (!query.trim()) {
      setSkillSearchResults([]);
      return;
    }
    setSkillSearchLoading(true);
    try {
      const data = await marketplaceApi.getAllSkills({ search: query, limit: 5 });
      const installed = new Set(agentSkills.map((s) => s.id));
      setSkillSearchResults(
        (data.skills || [])
          .filter((s: { id: string }) => !installed.has(s.id))
          .map((s: { id: string; name: string; description: string; slug: string; category: string }) => ({
            id: s.id,
            name: s.name,
            description: s.description,
            slug: s.slug,
            category: s.category,
          }))
      );
    } catch {
      setSkillSearchResults([]);
    } finally {
      setSkillSearchLoading(false);
    }
  };

  const handleInstallSkill = async (skillId: string) => {
    try {
      await marketplaceApi.installSkillOnAgent(skillId, agent.id);
      const skill = skillSearchResults.find((s) => s.id === skillId);
      if (skill) {
        setAgentSkills((prev) => [...prev, { id: skill.id, name: skill.name, description: skill.description, slug: skill.slug }]);
        setSkillSearchResults((prev) => prev.filter((s) => s.id !== skillId));
      }
      toast.success('Skill installed');
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to install skill');
    }
  };

  const handleUninstallSkill = async (skillId: string) => {
    try {
      await marketplaceApi.uninstallSkillFromAgent(skillId, agent.id);
      setAgentSkills((prev) => prev.filter((s) => s.id !== skillId));
      toast.success('Skill removed');
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to remove skill');
    }
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
      config: { features },
    });
  };

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded-xl max-w-3xl lg:max-w-6xl w-full p-6 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-2xl font-bold text-[var(--text)] flex items-center gap-2">
            <Pencil size={24} />
            Edit Agent
          </h2>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                handleSubmit({ preventDefault: () => {} } as React.FormEvent);
              }}
              className="px-5 py-2 bg-[var(--primary)] hover:bg-[var(--primary)]/90 rounded-lg text-white transition-colors flex items-center gap-2 text-sm font-medium"
            >
              <Check size={16} />
              Save
            </button>
            <button
              onClick={onClose}
              className="p-2 hover:bg-white/5 rounded-lg transition-colors text-[var(--text-muted)]"
            >
              ✕
            </button>
          </div>
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
                  className="w-full px-4 py-2 bg-white/5 border border-[var(--border)] rounded-lg text-[var(--text)] focus:outline-none focus:border-[var(--primary)]/50"
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
                  className="w-full px-4 py-2 bg-white/5 border border-[var(--border)] rounded-lg text-[var(--text)] focus:outline-none focus:border-[var(--primary)]/50"
                  required
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-[var(--text)] mb-2">Model</label>
                <ModelSelector
                  currentAgent={{
                    id: agent.id,
                    name: agent.name,
                    icon: agent.icon || '',
                    model: agent.model,
                    selectedModel: model,
                    sourceType: agent.source_type,
                    isCustom: agent.is_custom,
                  }}
                  onModelChange={setModel}
                  dropUp={false}
                />
                {agent.source_type !== 'open' && !agent.is_custom && (
                  <p className="mt-1 text-xs text-[var(--text-subtle)]">
                    Model can only be changed for open source agents
                  </p>
                )}
              </div>

              {/* Feature Flags */}
              {agent.agent_type === 'TesslateAgent' && (
                <div className="p-4 bg-[var(--text)]/5 rounded-lg border border-[var(--text)]/10">
                  <h3 className="text-sm font-semibold text-[var(--text)] mb-3 flex items-center gap-2">
                    <Gear size={16} />
                    Features
                  </h3>
                  <div className="space-y-2">
                    {FEATURE_FLAGS.map((flag) => (
                      <button
                        key={flag.key}
                        type="button"
                        onClick={() => toggleFeature(flag.key)}
                        className="w-full flex items-center justify-between px-3 py-2 rounded-lg hover:bg-white/5 transition-colors"
                      >
                        <div className="flex flex-col items-start">
                          <span className="text-sm text-[var(--text)]">{flag.label}</span>
                          <span className="text-xs text-[var(--text-subtle)]">
                            {flag.description}
                          </span>
                        </div>
                        {features[flag.key] ? (
                          <ToggleRight
                            size={28}
                            weight="fill"
                            className="text-[var(--primary)] flex-shrink-0"
                          />
                        ) : (
                          <ToggleLeft
                            size={28}
                            weight="fill"
                            className="text-[var(--text)]/30 flex-shrink-0"
                          />
                        )}
                      </button>
                    ))}
                  </div>
                </div>
              )}

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
                <p className="mt-1 text-xs text-[var(--text-subtle)]">
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

            {/* Right Column: Tool Management + Subagents */}
            <div className="space-y-4">
              <div className="p-4 bg-[var(--text)]/5 rounded-lg border border-[var(--text)]/10">
                <ToolManagement
                  selectedTools={tools}
                  toolConfigs={toolConfigs}
                  onToolsChange={(newTools, newConfigs) => {
                    setTools(newTools);
                    setToolConfigs(newConfigs);
                  }}
                />
              </div>

              {/* Subagents Section (collapsible) */}
              {agent.agent_type === 'TesslateAgent' && (
                <div className="p-4 bg-[var(--text)]/5 rounded-lg border border-[var(--text)]/10">
                  <button
                    type="button"
                    onClick={() => setSubagentsExpanded(!subagentsExpanded)}
                    className="w-full flex items-center justify-between text-sm font-semibold text-[var(--text)]"
                  >
                    <span className="flex items-center gap-2">
                      <Robot size={16} />
                      Subagents
                      {subagents.length > 0 && (
                        <span className="text-xs font-normal text-[var(--text-subtle)]">
                          ({subagents.length})
                        </span>
                      )}
                    </span>
                    {subagentsExpanded ? <CaretDown size={16} /> : <CaretRight size={16} />}
                  </button>

                  {subagentsExpanded && (
                    <div className="mt-3 space-y-2">
                      {subagentsLoading ? (
                        <div className="flex items-center justify-center py-4">
                          <LoadingSpinner />
                        </div>
                      ) : (
                        <>
                          {subagents.map((sub) => (
                            <div
                              key={sub.id}
                              className="p-3 bg-white/5 rounded-lg border border-[var(--text)]/10"
                            >
                              {editingSubagent === sub.id ? (
                                /* Inline prompt editor */
                                <div className="space-y-2">
                                  <div className="flex items-center justify-between">
                                    <span className="text-sm font-medium text-[var(--text)]">
                                      {sub.name}
                                      {sub.is_builtin && (
                                        <span className="ml-2 text-xs text-[var(--text-subtle)]">
                                          built-in (editing creates fork)
                                        </span>
                                      )}
                                    </span>
                                  </div>
                                  <textarea
                                    value={editingSubagentPrompt}
                                    onChange={(e) => setEditingSubagentPrompt(e.target.value)}
                                    className="w-full px-3 py-2 bg-white/5 border border-[var(--border)] rounded-lg text-[var(--text)] text-xs font-mono focus:outline-none focus:border-[var(--primary)]/50 resize-y"
                                    rows={8}
                                  />
                                  <div className="flex items-center gap-2 justify-end">
                                    <button
                                      type="button"
                                      onClick={() => setEditingSubagent(null)}
                                      className="px-3 py-1 text-xs bg-white/5 hover:bg-white/10 rounded transition-colors text-[var(--text-muted)]"
                                    >
                                      Cancel
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() => handleSaveSubagentPrompt(sub.id)}
                                      className="px-3 py-1 text-xs bg-[var(--primary)] hover:bg-[var(--primary)]/90 rounded transition-colors text-white"
                                    >
                                      Save Prompt
                                    </button>
                                  </div>
                                </div>
                              ) : (
                                /* Normal view */
                                <div className="flex items-center justify-between">
                                  <div className="flex-1 min-w-0">
                                    <div className="flex items-center gap-2">
                                      <span className="text-sm font-medium text-[var(--text)]">
                                        {sub.name}
                                      </span>
                                      {sub.is_builtin && (
                                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--text)]/10 text-[var(--text-muted)]">
                                          built-in
                                        </span>
                                      )}
                                    </div>
                                    <p className="text-xs text-[var(--text-subtle)] truncate">
                                      {sub.description}
                                    </p>
                                    {sub.tools.length > 0 && (
                                      <p className="text-[10px] text-[var(--text)]/30 mt-0.5">
                                        {sub.tools.length} tool{sub.tools.length !== 1 ? 's' : ''}
                                      </p>
                                    )}
                                  </div>
                                  <div className="flex items-center gap-1 flex-shrink-0 ml-2">
                                    <button
                                      type="button"
                                      onClick={() => {
                                        setEditingSubagent(sub.id);
                                        setEditingSubagentPrompt(sub.system_prompt || '');
                                      }}
                                      className="px-2 py-1 text-[10px] bg-white/5 hover:bg-white/10 rounded transition-colors text-[var(--text-muted)]"
                                    >
                                      Edit Prompt
                                    </button>
                                    {!sub.is_builtin && (
                                      <button
                                        type="button"
                                        onClick={() => handleDeleteSubagent(sub.id)}
                                        className="p-1 hover:bg-red-500/10 rounded transition-colors text-red-400/60 hover:text-red-400"
                                      >
                                        <Trash size={12} />
                                      </button>
                                    )}
                                  </div>
                                </div>
                              )}
                            </div>
                          ))}

                          {/* Add Subagent */}
                          {showAddSubagent ? (
                            <div className="p-3 bg-white/5 rounded-lg border border-[var(--primary)]/20 space-y-2">
                              <input
                                type="text"
                                value={newSubagent.name}
                                onChange={(e) =>
                                  setNewSubagent((p) => ({ ...p, name: e.target.value }))
                                }
                                placeholder="Subagent name"
                                className="w-full px-3 py-1.5 bg-white/5 border border-[var(--border)] rounded text-sm text-[var(--text)] focus:outline-none focus:border-[var(--primary)]/50"
                              />
                              <input
                                type="text"
                                value={newSubagent.description}
                                onChange={(e) =>
                                  setNewSubagent((p) => ({ ...p, description: e.target.value }))
                                }
                                placeholder="Description (optional)"
                                className="w-full px-3 py-1.5 bg-white/5 border border-[var(--border)] rounded text-sm text-[var(--text)] focus:outline-none focus:border-[var(--primary)]/50"
                              />
                              <textarea
                                value={newSubagent.system_prompt}
                                onChange={(e) =>
                                  setNewSubagent((p) => ({ ...p, system_prompt: e.target.value }))
                                }
                                placeholder="System prompt..."
                                className="w-full px-3 py-2 bg-white/5 border border-[var(--border)] rounded text-xs font-mono text-[var(--text)] focus:outline-none focus:border-[var(--primary)]/50 resize-y"
                                rows={6}
                              />
                              <div className="flex items-center gap-2 justify-end">
                                <button
                                  type="button"
                                  onClick={() => {
                                    setShowAddSubagent(false);
                                    setNewSubagent({
                                      name: '',
                                      description: '',
                                      system_prompt: '',
                                    });
                                  }}
                                  className="px-3 py-1 text-xs bg-white/5 hover:bg-white/10 rounded transition-colors text-[var(--text-muted)]"
                                >
                                  Cancel
                                </button>
                                <button
                                  type="button"
                                  onClick={handleAddSubagent}
                                  className="px-3 py-1 text-xs bg-[var(--primary)] hover:bg-[var(--primary)]/90 rounded transition-colors text-white"
                                >
                                  Create
                                </button>
                              </div>
                            </div>
                          ) : (
                            <button
                              type="button"
                              onClick={() => setShowAddSubagent(true)}
                              className="w-full flex items-center justify-center gap-1 py-2 text-xs text-[var(--text-subtle)] hover:text-[var(--text-muted)] hover:bg-white/5 rounded-lg border border-dashed border-[var(--text)]/10 hover:border-[var(--text)]/20 transition-colors"
                            >
                              <Plus size={12} />
                              Add Subagent
                            </button>
                          )}
                        </>
                      )}
                    </div>
                  )}
                </div>
              )}

              {/* Skills Section (collapsible) */}
              <div className="p-4 bg-[var(--text)]/5 rounded-lg border border-[var(--text)]/10">
                <button
                  type="button"
                  onClick={() => setSkillsExpanded(!skillsExpanded)}
                  className="w-full flex items-center justify-between text-sm font-semibold text-[var(--text)]"
                >
                  <span className="flex items-center gap-2">
                    <Plugs size={16} />
                    Skills
                    {agentSkills.length > 0 && (
                      <span className="text-xs font-normal text-[var(--text-subtle)]">
                        ({agentSkills.length})
                      </span>
                    )}
                  </span>
                  {skillsExpanded ? <CaretDown size={16} /> : <CaretRight size={16} />}
                </button>

                {skillsExpanded && (
                  <div className="mt-3 space-y-2">
                    {skillsLoading ? (
                      <div className="flex items-center justify-center py-4">
                        <LoadingSpinner />
                      </div>
                    ) : (
                      <>
                        {agentSkills.map((skill) => (
                          <div
                            key={skill.id}
                            className="flex items-center justify-between p-3 bg-white/5 rounded-lg border border-[var(--text)]/10"
                          >
                            <div className="flex-1 min-w-0">
                              <span className="text-sm font-medium text-[var(--text)]">
                                {skill.name}
                              </span>
                              <p className="text-xs text-[var(--text-subtle)] truncate">
                                {skill.description}
                              </p>
                            </div>
                            <button
                              type="button"
                              onClick={() => handleUninstallSkill(skill.id)}
                              className="p-1 hover:bg-red-500/10 rounded transition-colors text-red-400/60 hover:text-red-400 flex-shrink-0 ml-2"
                              title="Remove skill"
                            >
                              <Trash size={12} />
                            </button>
                          </div>
                        ))}

                        {/* Search & add skills */}
                        {showSkillSearch ? (
                          <div className="p-3 bg-white/5 rounded-lg border border-[var(--primary)]/20 space-y-2">
                            <input
                              type="text"
                              value={skillSearchQuery}
                              onChange={(e) => handleSearchSkills(e.target.value)}
                              placeholder="Search skills..."
                              className="w-full px-3 py-1.5 bg-white/5 border border-[var(--border)] rounded text-sm text-[var(--text)] focus:outline-none focus:border-[var(--primary)]/50"
                              autoFocus
                            />
                            {skillSearchLoading && (
                              <div className="flex items-center justify-center py-2">
                                <LoadingSpinner />
                              </div>
                            )}
                            {skillSearchResults.map((skill) => (
                              <div
                                key={skill.id}
                                className="flex items-center justify-between p-2 bg-white/5 rounded-lg"
                              >
                                <div className="flex items-center gap-2.5 flex-1 min-w-0">
                                  <div className="w-7 h-7 rounded-lg bg-[var(--primary)]/10 flex items-center justify-center shrink-0 text-[var(--primary)]">
                                    {getSkillCategoryIcon(skill.category)}
                                  </div>
                                  <div className="min-w-0">
                                    <span className="text-sm font-medium text-[var(--text)]">
                                      {skill.name}
                                    </span>
                                    <p className="text-xs text-[var(--text-subtle)] truncate">
                                      {skill.description}
                                    </p>
                                  </div>
                                </div>
                                <button
                                  type="button"
                                  onClick={() => handleInstallSkill(skill.id)}
                                  className="px-2 py-1 text-[10px] bg-[var(--primary)] hover:bg-[var(--primary)]/90 rounded transition-colors text-white flex-shrink-0 ml-2"
                                >
                                  Install
                                </button>
                              </div>
                            ))}
                            {skillSearchQuery && !skillSearchLoading && skillSearchResults.length === 0 && (
                              <p className="text-xs text-[var(--text-subtle)] text-center py-2">
                                No skills found
                              </p>
                            )}
                            <div className="flex justify-end">
                              <button
                                type="button"
                                onClick={() => {
                                  setShowSkillSearch(false);
                                  setSkillSearchQuery('');
                                  setSkillSearchResults([]);
                                }}
                                className="px-3 py-1 text-xs bg-white/5 hover:bg-white/10 rounded transition-colors text-[var(--text-muted)]"
                              >
                                Close
                              </button>
                            </div>
                          </div>
                        ) : (
                          <button
                            type="button"
                            onClick={() => setShowSkillSearch(true)}
                            className="w-full flex items-center justify-center gap-1 py-2 text-xs text-[var(--text-subtle)] hover:text-[var(--text-muted)] hover:bg-white/5 rounded-lg border border-dashed border-[var(--text)]/10 hover:border-[var(--text)]/20 transition-colors"
                          >
                            <Plus size={12} />
                            Add Skill
                          </button>
                        )}
                      </>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>

        </form>
      </div>
    </div>
  );
}
