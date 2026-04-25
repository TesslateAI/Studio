import { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useTeam } from '../contexts/TeamContext';
import {
  Folder,
  Storefront,
  Books,
  Sun,
  Moon,
  Gear,
  SignOut,
  ChatCircleDots,
  Article,
} from '@phosphor-icons/react';
import AgentsPage from './library/AgentsPage';
import SkillsPage from './library/SkillsPage';
import BasesPage from './library/BasesPage';
import ConnectorsPage from './library/ConnectorsPage';
import ModelsPage from './library/ModelsPage';
import ThemesPage from './library/ThemesPage';
import type { LibraryTheme } from './library/ThemesPage';
import type { LibraryAgent } from './library/types';
import { LoadingSpinner } from '../components/PulsingGridSpinner';
import { MobileMenu } from '../components/ui';
import { type CustomProvider } from '../components/settings/CustomProviderComponents';
import { marketplaceApi, secretsApi, billingApi } from '../lib/api';
import toast from 'react-hot-toast';
import { useTheme } from '../theme/ThemeContext';

// LibraryAgent type is imported from ./library/types

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

export default function Library() {
  const navigate = useNavigate();
  const { theme, toggleTheme, themePresetId, setThemePreset } = useTheme();
  const { teamSwitchKey } = useTeam();
  const [searchParams] = useSearchParams();
  const tabParam = searchParams.get('tab');
  // Normalize legacy tab aliases.
  // - "api-keys" was renamed to "models".
  // - "connectors" is the new URL alias for "mcp_servers" (#307). Bookmarks
  //   against either param keep working.
  const normalizedTab: TabType =
    tabParam === 'api-keys'
      ? 'models'
      : tabParam === 'connectors'
        ? 'mcp_servers'
        : (tabParam as TabType) || 'agents';
  const [activeTab, setActiveTab] = useState<TabType>(normalizedTab);

  // Sync activeTab when URL search params change (e.g. sidebar navigation)
  useEffect(() => {
    setActiveTab(normalizedTab);
  }, [normalizedTab]);

  const [agents, setAgents] = useState<LibraryAgent[]>([]);
  const [bases, setBases] = useState<LibraryBase[]>([]);
  const [libraryThemes, setLibraryThemes] = useState<LibraryTheme[]>([]);
  const [apiKeys, setApiKeys] = useState<ApiKey[]>([]);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [byokEnabled, setByokEnabled] = useState<boolean | null>(null);
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

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, teamSwitchKey]);

  const loadData = async () => {
    setLoading(true);
    try {
      if (activeTab === 'agents') {
        await loadLibraryAgents();
        setLoading(false);
      } else if (activeTab === 'bases') {
        await loadBases();
        setLoading(false);
      } else if (activeTab === 'skills') {
        await loadSkills();
        setLoading(false);
      } else if (activeTab === 'mcp_servers') {
        // Connectors page needs the agent list to populate the
        // "Add to Agent" dropdown — load both in parallel so the dropdown
        // works on first open without a manual round-trip through the
        // Agents tab.
        await Promise.all([loadMcpServers(), loadLibraryAgents()]);
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
      setSkills((data.skills || []).filter((s: Record<string, unknown>) => s.is_purchased));
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

  const loadBases = async () => {
    try {
      const data = await marketplaceApi.getUserBases();
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

      // If the user disabled the theme that's currently applied, fall back
      // to the default for their current mode so the UI doesn't keep
      // rendering a "disabled" theme.
      if (!newState && themePresetId === t.id) {
        const fallback = theme === 'dark' ? 'default-dark' : 'default-light';
        await setThemePreset(fallback);
        toast.success('Theme disabled — reverted to default');
      } else {
        toast.success(`Theme ${newState ? 'enabled' : 'disabled'}`);
      }

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

      {/* Header */}
      <div className="flex-shrink-0">
        <div
          className="h-10 flex items-center justify-between gap-[6px]"
          style={{
            paddingLeft: '18px',
            paddingRight: '4px',
            borderBottom: 'var(--border-width) solid var(--border)',
          }}
        >
          <button
            onClick={() => window.dispatchEvent(new Event('toggleMobileMenu'))}
            className="mobile-only btn btn-icon mr-1"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M4 6h16M4 12h16M4 18h16"
              />
            </svg>
          </button>
          <h2 className="text-xs font-semibold text-[var(--text)] flex-1">
            {activeTab === 'mcp_servers'
              ? 'Connectors'
              : activeTab.charAt(0).toUpperCase() + activeTab.slice(1)}
          </h2>
        </div>
      </div>

      {/* Scrollable Content */}
      <div
        key={teamSwitchKey}
        className="flex-1 overflow-hidden flex flex-col"
        style={{ animation: 'fade-in 0.25s ease-out' }}
      >
        {activeTab === 'agents' && (
          <AgentsPage
            agents={agents}
            loading={loading}
            onReload={loadLibraryAgents}
            onToggleEnable={async (agent: LibraryAgent) => {
              try {
                const newState = !agent.is_enabled;
                await marketplaceApi.toggleAgent(agent.id, newState);
                toast.success(`Agent ${newState ? 'enabled' : 'disabled'}`);
                loadLibraryAgents();
              } catch (error) {
                console.error('Toggle failed:', error);
                toast.error('Failed to toggle agent');
              }
            }}
            onTogglePublish={async (agent: LibraryAgent) => {
              try {
                if (agent.is_published) {
                  await marketplaceApi.unpublishAgent(Number(agent.id));
                  toast.success('Agent unpublished from marketplace');
                } else {
                  await marketplaceApi.publishAgent(Number(agent.id));
                  toast.success('Agent published to community marketplace!');
                }
                loadLibraryAgents();
              } catch (error: unknown) {
                console.error('Publish toggle failed:', error);
                const err = error as { response?: { data?: { detail?: string } } };
                toast.error(err.response?.data?.detail || 'Failed to toggle publish status');
              }
            }}
          />
        )}

        {activeTab === 'bases' && (
          <BasesPage
            bases={bases}
            loading={loading}
            onBrowse={() => navigate('/marketplace/browse/base')}
          />
        )}

        {activeTab === 'skills' && (
          <SkillsPage
            skills={skills}
            agents={agents}
            loading={loading}
            onBrowse={() => navigate('/marketplace/browse/skill')}
          />
        )}

        {activeTab === 'mcp_servers' && (
          <ConnectorsPage
            servers={mcpServers}
            agents={agents}
            loading={loading}
            onReload={loadMcpServers}
            onBrowse={() => navigate('/marketplace/browse/mcp_server')}
          />
        )}

        {activeTab === 'themes' && (
          <ThemesPage
            themes={libraryThemes}
            loading={loading}
            onToggleEnable={handleToggleThemeEnable}
            onTogglePublish={handleToggleThemePublish}
            onRemove={handleRemoveTheme}
            onDelete={handleDeleteTheme}
            onSave={async (theme, data) => {
              try {
                if (!theme.id || theme.id === '') {
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
                  await marketplaceApi.updateTheme(theme.id, data);
                  toast.success('Theme updated successfully');
                }
                loadLibraryThemes();
              } catch (error: unknown) {
                console.error('Save failed:', error);
                const err = error as { response?: { data?: { detail?: string } } };
                toast.error(err.response?.data?.detail || 'Failed to save theme');
              }
            }}
          />
        )}

        {activeTab === 'models' && (
          <ModelsPage
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
    </>
  );
}
