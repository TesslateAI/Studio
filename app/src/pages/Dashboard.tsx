import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { projectsApi, marketplaceApi } from '../lib/api';
import { githubApi } from '../lib/github-api';
import { useTheme } from '../theme/ThemeContext';
import {
  FloatingSidebar,
  MobileMenu,
  ProjectCard,
  MarketplaceCard
} from '../components/ui';
import type { Status } from '../components/ui';
import { GitHubConnectModal, ConfirmDialog } from '../components/modals';
import { LoadingSpinner } from '../components/PulsingGridSpinner';
import { MobileWarning } from '../components/MobileWarning';
import { DiscordSupport } from '../components/DiscordSupport';
import toast from 'react-hot-toast';
import {
  Atom,
  Database,
  ShieldCheck,
  Sparkle,
  Lightning as LightningIcon,
  Folder,
  Storefront,
  Package,
  Gear,
  Sun,
  Moon,
  Question,
  FilePlus,
  FolderOpen,
  GithubLogo,
  GitBranch,
  ShoppingCart,
  DiscordLogo,
  SignOut,
  CaretDown,
  Check,
  ArrowSquareOut
} from '@phosphor-icons/react';

interface Project {
  id: string;
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
  status?: Status;
  agents?: Array<{ icon: any; name: string }>;
}

type TabFilter = 'all' | 'idea' | 'build' | 'launch';

export default function Dashboard() {
  const navigate = useNavigate();
  const { theme, toggleTheme } = useTheme();
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newProject, setNewProject] = useState({ name: '', description: '' });
  const [activeTab, setActiveTab] = useState<TabFilter>('all');
  const [isCreating, setIsCreating] = useState(false);
  const [sourceType, setSourceType] = useState<'template' | 'github' | 'base'>('template');
  const [githubRepoUrl, setGithubRepoUrl] = useState('');
  const [githubBranch, setGithubBranch] = useState('main');
  const [githubConnected, setGithubConnected] = useState(false);
  const [checkingGithub, setCheckingGithub] = useState(false);
  const [showGithubConnectModal, setShowGithubConnectModal] = useState(false);
  const [bases, setBases] = useState<any[]>([]);
  const [selectedBase, setSelectedBase] = useState<number | null>(null);
  const [isBaseDropdownOpen, setIsBaseDropdownOpen] = useState(false);
  const [deletingProjectIds, setDeletingProjectIds] = useState<Set<number>>(new Set());
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [projectToDelete, setProjectToDelete] = useState<Project | null>(null);
  const [userName, setUserName] = useState<string>('');

  // Get user name from JWT token
  useEffect(() => {
    const token = localStorage.getItem('token');
    if (token) {
      try {
        const payload = JSON.parse(atob(token.split('.')[1]));
        setUserName(payload.sub || 'there');
      } catch (e) {
        setUserName('there');
      }
    }
  }, []);

  useEffect(() => {
    loadProjects();
  }, []);

  useEffect(() => {
    if (showCreateModal) {
      checkGithubConnection();
      loadUserBases();
    }
  }, [showCreateModal]);

  const loadProjects = async () => {
    try {
      const data = await projectsApi.getAll();
      // Add mock status and agents to existing projects
      const projectsWithMeta = data.map((p: Project) => ({
        ...p,
        status: (p.status || 'build') as Status,
        agents: p.agents || []
      }));
      setProjects(projectsWithMeta);
    } catch (error) {
      toast.error('Failed to load projects');
    } finally {
      setLoading(false);
    }
  };

  const checkGithubConnection = async () => {
    setCheckingGithub(true);
    try {
      const status = await githubApi.getStatus();
      setGithubConnected(status.connected);
    } catch (error) {
      setGithubConnected(false);
    } finally {
      setCheckingGithub(false);
    }
  };

  const loadUserBases = async () => {
    try {
      const data = await marketplaceApi.getUserBases();
      setBases(data.bases || []);
    } catch (error) {
      console.error('Failed to load bases:', error);
      setBases([]);
    }
  };

  const createProject = async () => {
    if (!newProject.name.trim()) {
      toast.error('Project name is required');
      return;
    }

    if (sourceType === 'github') {
      if (!githubRepoUrl.trim()) {
        toast.error('GitHub repository URL is required');
        return;
      }
      // GitHub connection is optional - works for public repos without authentication
    }

    if (sourceType === 'base') {
      if (!selectedBase) {
        toast.error('Please select a base');
        return;
      }
    }

    setIsCreating(true);
    const creatingToast = toast.loading(
      sourceType === 'github'
        ? 'Importing from GitHub...'
        : sourceType === 'base'
        ? 'Creating from base...'
        : 'Creating your project...'
    );

    try {
      const project = await projectsApi.create(
        newProject.name,
        newProject.description,
        sourceType,
        githubRepoUrl || undefined,
        githubBranch || 'main',
        selectedBase || undefined
      );
      toast.success('Project created successfully!', { id: creatingToast });
      setShowCreateModal(false);
      setNewProject({ name: '', description: '' });
      setSourceType('template');
      setGithubRepoUrl('');
      setGithubBranch('main');
      setTimeout(() => {
        navigate(`/project/${project.slug}`);
      }, 500);
    } catch (error: any) {
      const detail = error?.response?.data?.detail;
      const errorMessage = typeof detail === 'string' ? detail : 'Failed to create project';
      toast.error(errorMessage, { id: creatingToast });
    } finally {
      setIsCreating(false);
    }
  };

  const deleteProject = (id: string) => {
    const project = projects.find(p => p.id === id);
    if (project) {
      setProjectToDelete(project);
      setShowDeleteDialog(true);
    }
  };

  const confirmDeleteProject = async () => {
    if (!projectToDelete) return;

    const projectId = projectToDelete.id;
    setShowDeleteDialog(false);
    setDeletingProjectIds(prev => new Set(prev).add(projectId));
    const deletingToast = toast.loading('Deleting project...');

    try {
      await projectsApi.delete(projectId);
      toast.success('Project deleted successfully', { id: deletingToast });
      await loadProjects();
      // Only remove from deleting state after project list is refreshed
      setDeletingProjectIds(prev => {
        const updated = new Set(prev);
        updated.delete(projectId);
        return updated;
      });
    } catch (error) {
      toast.error('Failed to delete project', { id: deletingToast });
      // Remove from deleting state on error
      setDeletingProjectIds(prev => {
        const updated = new Set(prev);
        updated.delete(projectId);
        return updated;
      });
    } finally {
      setProjectToDelete(null);
    }
  };

  const updateProjectStatus = async (id: string, status: Status) => {
    try {
      // Update local state immediately for better UX
      setProjects(prev => prev.map(p =>
        p.id === id ? { ...p, status } : p
      ));
      toast.success(`Project moved to ${status}`);
      // TODO: Add API call to persist status
    } catch (error) {
      toast.error('Failed to update status');
    }
  };

  const handleForkProject = async (id: string) => {
    const forkingToast = toast.loading('Forking project...');
    try {
      const forkedProject = await projectsApi.forkProject(id);
      toast.success('Project forked successfully!', { id: forkingToast });
      await loadProjects(); // Refresh project list
      // Navigate to the forked project after a brief delay
      setTimeout(() => {
        navigate(`/project/${forkedProject.id}`);
      }, 500);
    } catch (error: any) {
      const errorMessage = error?.response?.data?.detail || 'Failed to fork project';
      toast.error(errorMessage, { id: forkingToast });
    }
  };

  const logout = () => {
    localStorage.removeItem('token');
    navigate('/login');
  };

  // Filter projects by tab
  const filteredProjects = projects.filter(project => {
    if (activeTab === 'all') return true;
    return project.status === activeTab;
  });

  const formatDate = (dateString: string) => {
    if (!dateString) return 'Never';

    try {
      // Handle ISO 8601 format with or without timezone
      // If the date string doesn't have timezone info, assume UTC
      const dateStr = dateString.includes('Z') || dateString.includes('+') || dateString.includes('T') && dateString.match(/[+-]\d{2}:\d{2}$/)
        ? dateString
        : dateString.replace(' ', 'T') + 'Z';

      const date = new Date(dateStr);

      // Check if date is valid
      if (isNaN(date.getTime())) {
        return 'Invalid date';
      }

      const now = new Date();
      const diffInMinutes = Math.floor((now.getTime() - date.getTime()) / (1000 * 60));

      // Handle negative differences (future dates)
      if (diffInMinutes < 0) {
        return 'Just now';
      }

      if (diffInMinutes < 1) return 'Just now';
      if (diffInMinutes < 60) return `${diffInMinutes}m ago`;
      if (diffInMinutes < 1440) return `${Math.floor(diffInMinutes / 60)}h ago`;
      if (diffInMinutes < 10080) return `${Math.floor(diffInMinutes / 1440)}d ago`;
      return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    } catch (error) {
      console.error('Error formatting date:', dateString, error);
      return 'Invalid date';
    }
  };

  // Sidebar items
  const leftSidebarItems = [
    {
      icon: <Folder className="w-5 h-5" weight="fill" />,
      title: 'Projects',
      onClick: () => {},
      active: true,
      dataTour: 'dashboard-link'
    },
    {
      icon: <Storefront className="w-5 h-5" weight="fill" />,
      title: 'Marketplace',
      onClick: () => navigate('/marketplace'),
      dataTour: 'marketplace-link'
    },
    {
      icon: <ShoppingCart className="w-5 h-5" weight="fill" />,
      title: 'Library',
      onClick: () => navigate('/library'),
      dataTour: 'library-link'
    },
    {
      icon: <Package className="w-5 h-5" weight="fill" />,
      title: 'Components',
      onClick: () => toast('Components library coming soon!')
    },
    {
      icon: <SignOut className="w-5 h-5" weight="fill" />,
      title: 'Logout',
      onClick: logout
    }
  ];

  const rightSidebarItems = [
    {
      icon: theme === 'dark' ? <Sun className="w-5 h-5" weight="fill" /> : <Moon className="w-5 h-5" weight="fill" />,
      title: theme === 'dark' ? 'Light Mode' : 'Dark Mode',
      onClick: toggleTheme
    },
    {
      icon: <Question className="w-5 h-5" weight="fill" />,
      title: 'Help',
      onClick: () => toast('Help & support coming soon!')
    }
  ];

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <LoadingSpinner message="Loading projects..." size={80} />
      </div>
    );
  }

  return (
    <div className="min-h-screen px-4 sm:px-8 md:px-20 lg:px-32 py-6 sm:py-12 md:py-20 lg:py-24 relative flex flex-col">
      {/* Mobile Warning */}
      <MobileWarning />

      {/* Mobile Menu - Shows on mobile only */}
      <MobileMenu leftItems={leftSidebarItems} rightItems={rightSidebarItems} />

      {/* Floating Sidebars - Desktop only */}
      <FloatingSidebar position="left" items={leftSidebarItems} />
      <FloatingSidebar position="right" items={rightSidebarItems} />

      {/* Main Content */}
      <div className="flex-grow">
        {/* Header */}
        <div className="mb-6 md:mb-10">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h1 className="font-heading text-2xl sm:text-3xl md:text-4xl font-bold text-[var(--text)]">
              Welcome, {userName}! 👋
            </h1>
            <p className="text-[var(--text)]/60 mt-2">Ready to build something amazing?</p>
          </div>
        </div>

        {/* Tab Navigation */}
        <div className="flex items-center gap-2 sm:gap-4 overflow-x-auto pb-2">
          {[
            { key: 'all', label: 'All Projects', enabled: true },
            { key: 'idea', label: 'Idea', enabled: false },
            { key: 'build', label: 'Build', enabled: true },
            { key: 'launch', label: 'Launch', enabled: false }
          ].map((tab) => (
            <button
              key={tab.key}
              onClick={() => tab.enabled ? setActiveTab(tab.key as TabFilter) : toast('Coming soon!')}
              className={`
                font-heading text-sm sm:text-lg md:text-xl pb-2 border-b-2 transition-all whitespace-nowrap
                ${activeTab === tab.key
                  ? 'text-[var(--primary)] border-[var(--primary)]'
                  : tab.enabled
                    ? 'text-gray-400 border-transparent hover:text-[var(--text)]'
                    : 'text-gray-600 border-transparent cursor-not-allowed opacity-50'
                }
              `}
            >
              {tab.label}{!tab.enabled && ' 🔒'}
            </button>
          ))}
        </div>
      </div>

      {/* Marketplace Section */}
      <div className="bg-white/[0.02] dark:bg-white/[0.02] border border-white/[0.08] rounded-2xl p-8 mb-8">
        <div className="flex items-center justify-center">
          <h2 className="font-heading text-xl font-bold text-[var(--text)] flex items-center gap-2">
            <Sparkle className="w-5 h-5 text-orange-400" weight="fill" />
            Recommendations coming soon for your project
          </h2>
        </div>
      </div>

      {/* Projects Grid */}
      <div className={filteredProjects.length === 0 ? "" : "grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 sm:gap-6"}>
        {/* Create New Project Card */}
        <button
          onClick={() => setShowCreateModal(true)}
          data-tour="create-project"
          className={`
            group bg-white/[0.01] dark:bg-white/[0.01] rounded-2xl p-6 sm:p-8
            border-2 border-dashed border-[rgba(255,107,0,0.3)]
            hover:border-[rgba(255,107,0,0.6)]
            transition-all duration-300
            hover:transform hover:-translate-y-1
            flex flex-col items-center justify-center gap-3 sm:gap-4
            ${filteredProjects.length === 0 ? 'w-full min-h-[300px] sm:min-h-[400px]' : 'min-h-[240px] sm:min-h-[280px]'}
          `}
        >
          <div className="w-12 h-12 sm:w-16 sm:h-16 bg-[rgba(255,107,0,0.2)] rounded-2xl flex items-center justify-center group-hover:bg-[rgba(255,107,0,0.3)] transition-colors">
            <FilePlus className="w-6 h-6 sm:w-8 sm:h-8 text-[var(--primary)]" weight="fill" />
          </div>
          <div className="text-center">
            <h3 className="font-heading text-base sm:text-lg font-bold text-[var(--text)] mb-1.5 sm:mb-2">Create New Project</h3>
            <p className="text-xs sm:text-sm text-gray-500">Start building something amazing</p>
          </div>
        </button>

        {/* Project Cards */}
        {filteredProjects.map((project) => (
          <ProjectCard
            key={project.id}
            project={{
              id: project.id,
              name: project.name,
              description: project.description || 'No description',
              status: project.status || 'build',
              agents: project.agents || [],
              lastUpdated: formatDate(project.updated_at),
              isLive: project.status === 'launch'
            }}
            onOpen={() => navigate(`/project/${project.slug}`)}
            onDelete={() => deleteProject(project.id)}
            onStatusChange={(status) => updateProjectStatus(project.id, status)}
            onFork={() => handleForkProject(project.id)}
            isDeleting={deletingProjectIds.has(project.id)}
          />
        ))}
      </div>

        {/* Empty State */}
        {filteredProjects.length === 0 && (
          <div className="text-center py-16">
          </div>
        )}
      </div>

      {/* Create Project Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50" onClick={() => !isCreating && setShowCreateModal(false)}>
          <div className="bg-[var(--surface)] p-8 rounded-3xl w-full max-w-lg shadow-2xl border border-white/10" onClick={(e) => e.stopPropagation()}>
            <div className="text-center mb-6">
              <div className="w-16 h-16 bg-[rgba(255,107,0,0.2)] rounded-2xl flex items-center justify-center mx-auto mb-4">
                <FilePlus className="w-8 h-8 text-[var(--primary)]" weight="fill" />
              </div>
              <h2 className="font-heading text-2xl font-bold text-[var(--text)] mb-2">Create New Project</h2>
              <p className="text-gray-500">Choose how to start your project</p>
            </div>

            <div className="space-y-4">
              {/* Source Type Selection */}
              <div>
                <label className="block text-sm font-medium text-[var(--text)] mb-3">Project Source</label>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  <button
                    onClick={() => setSourceType('template')}
                    disabled={isCreating}
                    className={`
                      p-4 rounded-xl border-2 transition-all
                      ${sourceType === 'template'
                        ? 'border-[var(--primary)] bg-[rgba(255,107,0,0.1)]'
                        : theme === 'light'
                          ? 'border-black/10 bg-black/5 hover:border-black/20'
                          : 'border-white/10 bg-white/5 hover:border-white/20'
                      }
                      ${isCreating ? 'opacity-50 cursor-not-allowed' : ''}
                    `}
                  >
                    <FilePlus className="w-6 h-6 text-[var(--primary)] mx-auto mb-2" weight="fill" />
                    <div className="text-sm font-semibold text-[var(--text)]">Template</div>
                    <div className={`text-xs mt-1 ${theme === 'light' ? 'text-black/50' : 'text-gray-500'}`}>Frontend-only (Vite)</div>
                  </button>
                  <button
                    onClick={() => setSourceType('base')}
                    disabled={isCreating}
                    className={`
                      p-4 rounded-xl border-2 transition-all
                      ${sourceType === 'base'
                        ? 'border-[var(--primary)] bg-[rgba(255,107,0,0.1)]'
                        : theme === 'light'
                          ? 'border-black/10 bg-black/5 hover:border-black/20'
                          : 'border-white/10 bg-white/5 hover:border-white/20'
                      }
                      ${isCreating ? 'opacity-50 cursor-not-allowed' : ''}
                    `}
                  >
                    <Package className="w-6 h-6 text-[var(--primary)] mx-auto mb-2" weight="fill" />
                    <div className="text-sm font-semibold text-[var(--text)]">From Base</div>
                    <div className={`text-xs mt-1 ${theme === 'light' ? 'text-black/50' : 'text-gray-500'}`}>Use template</div>
                  </button>
                  <button
                    onClick={() => setSourceType('github')}
                    disabled={isCreating}
                    className={`
                      p-4 rounded-xl border-2 transition-all
                      ${sourceType === 'github'
                        ? 'border-[var(--primary)] bg-[rgba(255,107,0,0.1)]'
                        : theme === 'light'
                          ? 'border-black/10 bg-black/5 hover:border-black/20'
                          : 'border-white/10 bg-white/5 hover:border-white/20'
                      }
                      ${isCreating ? 'opacity-50 cursor-not-allowed' : ''}
                    `}
                  >
                    <GithubLogo className="w-6 h-6 text-[var(--primary)] mx-auto mb-2" weight="fill" />
                    <div className="text-sm font-semibold text-[var(--text)]">GitHub</div>
                    <div className={`text-xs mt-1 ${theme === 'light' ? 'text-black/50' : 'text-gray-500'}`}>Import repository</div>
                  </button>
                </div>
              </div>

              {/* Base Selection */}
              {sourceType === 'base' && (
                <div className="space-y-3">
                  <p className="text-sm text-white/60">
                    Select a base from your library:
                  </p>
                  {bases.length === 0 ? (
                    <div className="text-center py-6 bg-white/5 border border-white/10 rounded-xl">
                      <Package className="w-12 h-12 text-white/40 mx-auto mb-3" weight="fill" />
                      <p className="text-white/40 mb-3">No bases in your library</p>
                      <button
                        onClick={() => {
                          setShowCreateModal(false);
                          navigate('/marketplace');
                        }}
                        className="text-[var(--primary)] hover:text-orange-400 text-sm font-medium"
                      >
                        Browse Marketplace
                      </button>
                    </div>
                  ) : (
                    <div className="relative">
                      <button
                        type="button"
                        onClick={() => !isCreating && setIsBaseDropdownOpen(!isBaseDropdownOpen)}
                        disabled={isCreating}
                        className={`
                          w-full px-3 py-3 border rounded-lg text-left
                          flex items-center justify-between transition-all
                          ${theme === 'light' ? 'bg-black/5' : 'bg-white/5'}
                          ${isBaseDropdownOpen
                            ? 'border-[var(--primary)]'
                            : theme === 'light'
                              ? 'border-black/20 hover:border-black/30'
                              : 'border-white/10 hover:border-white/20'
                          }
                          ${isCreating ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
                        `}
                      >
                        <div className="flex items-center gap-2 flex-1 min-w-0">
                          {selectedBase ? (
                            <>
                              <span className="text-xl flex-shrink-0">
                                {bases.find(b => b.id === selectedBase)?.icon}
                              </span>
                              <div className="min-w-0 flex-1">
                                <div className="font-medium text-[var(--text)] truncate">
                                  {bases.find(b => b.id === selectedBase)?.name}
                                </div>
                                <div className={`text-xs truncate ${theme === 'light' ? 'text-black/60' : 'text-white/60'}`}>
                                  {bases.find(b => b.id === selectedBase)?.description}
                                </div>
                              </div>
                            </>
                          ) : (
                            <span className={theme === 'light' ? 'text-black/40' : 'text-white/40'}>Choose a base...</span>
                          )}
                        </div>
                        <CaretDown
                          className={`flex-shrink-0 ml-2 transition-transform ${isBaseDropdownOpen ? 'rotate-180' : ''}`}
                          size={16}
                          weight="bold"
                        />
                      </button>

                      {isBaseDropdownOpen && (
                        <>
                          <div
                            className="fixed inset-0 z-10"
                            onClick={() => setIsBaseDropdownOpen(false)}
                          />
                          <div className={`absolute z-20 w-full mt-1 bg-[var(--surface)] border rounded-lg shadow-xl max-h-60 overflow-y-auto ${theme === 'light' ? 'border-black/10' : 'border-white/10'}`}>
                            {bases.map((base: any) => (
                              <button
                                key={base.id}
                                type="button"
                                onClick={() => {
                                  setSelectedBase(base.id);
                                  setIsBaseDropdownOpen(false);
                                }}
                                className={`
                                  w-full px-3 py-3 text-left transition-colors
                                  flex items-center gap-3
                                  ${selectedBase === base.id
                                    ? 'bg-[rgba(255,107,0,0.1)]'
                                    : theme === 'light' ? 'hover:bg-black/5' : 'hover:bg-white/5'
                                  }
                                `}
                              >
                                <span className="text-xl flex-shrink-0">{base.icon}</span>
                                <div className="flex-1 min-w-0">
                                  <div className={`font-medium truncate ${selectedBase === base.id ? 'text-[var(--primary)]' : 'text-[var(--text)]'}`}>
                                    {base.name}
                                  </div>
                                  <div className={`text-xs truncate ${theme === 'light' ? 'text-black/60' : 'text-white/60'}`}>
                                    {base.description}
                                  </div>
                                  <div className="flex gap-1 mt-1 flex-wrap">
                                    {base.tech_stack?.slice(0, 3).map((tech: string, idx: number) => (
                                      <span
                                        key={idx}
                                        className={`text-xs px-1.5 py-0.5 rounded ${theme === 'light' ? 'bg-black/10 text-black/70' : 'bg-white/10 text-white/70'}`}
                                      >
                                        {tech}
                                      </span>
                                    ))}
                                  </div>
                                </div>
                                {selectedBase === base.id && (
                                  <Check size={20} weight="bold" className="flex-shrink-0 text-[var(--primary)]" />
                                )}
                              </button>
                            ))}
                          </div>
                        </>
                      )}
                    </div>
                  )}
                </div>
              )}

              {/* GitHub Connection Status */}
              {sourceType === 'github' && (
                <div className={`border rounded-xl p-3 ${theme === 'light' ? 'bg-black/5 border-black/10' : 'bg-white/5 border-white/10'}`}>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <GithubLogo className="w-4 h-4" weight="fill" />
                      <span className="text-sm font-medium text-[var(--text)]">GitHub Connection:</span>
                      {checkingGithub ? (
                        <span className="text-xs text-gray-500">Checking...</span>
                      ) : githubConnected ? (
                        <span className="text-xs text-green-400">✓ Connected</span>
                      ) : (
                        <span className="text-xs text-orange-400">Not Connected</span>
                      )}
                    </div>
                    {!githubConnected && !checkingGithub && (
                      <button
                        onClick={() => setShowGithubConnectModal(true)}
                        disabled={isCreating}
                        className="text-xs bg-purple-500 hover:bg-purple-600 disabled:bg-gray-600 disabled:cursor-not-allowed text-white px-3 py-1.5 rounded-lg font-medium transition-all"
                      >
                        Connect
                      </button>
                    )}
                  </div>
                  {!githubConnected && !checkingGithub && (
                    <p className="text-xs text-gray-500 mt-2">
                      Connection optional for public repos. Required for private repos.
                    </p>
                  )}
                  {githubConnected && (
                    <p className="text-xs text-gray-500 mt-2">
                      You can import both public and private repositories.
                    </p>
                  )}
                </div>
              )}

              {/* GitHub Repository URL */}
              {sourceType === 'github' && (
                <>
                  <div>
                    <label className="block text-sm font-medium text-[var(--text)] mb-2">Repository URL</label>
                    <input
                      type="text"
                      value={githubRepoUrl}
                      onChange={(e) => setGithubRepoUrl(e.target.value)}
                      className={`w-full border text-[var(--text)] px-4 py-3 rounded-xl focus:outline-none focus:ring-2 focus:ring-[var(--primary)] ${theme === 'light' ? 'bg-black/5 border-black/20 placeholder-black/40' : 'bg-white/5 border-white/10 placeholder-gray-500'}`}
                      placeholder="https://github.com/username/repository"
                      disabled={isCreating}
                    />
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-[var(--text)] mb-2">Branch</label>
                    <div className="relative">
                      <GitBranch className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-500" />
                      <input
                        type="text"
                        value={githubBranch}
                        onChange={(e) => setGithubBranch(e.target.value)}
                        className={`w-full border text-[var(--text)] pl-10 pr-4 py-3 rounded-xl focus:outline-none focus:ring-2 focus:ring-[var(--primary)] ${theme === 'light' ? 'bg-black/5 border-black/20 placeholder-black/40' : 'bg-white/5 border-white/10 placeholder-gray-500'}`}
                        placeholder="main"
                        disabled={isCreating}
                      />
                    </div>
                  </div>
                </>
              )}

              {/* Project Name & Description */}
              <div>
                <label className="block text-sm font-medium text-[var(--text)] mb-2">Project Name</label>
                <input
                  type="text"
                  value={newProject.name}
                  onChange={(e) => setNewProject({ ...newProject, name: e.target.value })}
                  className={`w-full border text-[var(--text)] px-4 py-3 rounded-xl focus:outline-none focus:ring-2 focus:ring-[var(--primary)] ${theme === 'light' ? 'bg-black/5 border-black/20 placeholder-black/40' : 'bg-white/5 border-white/10 placeholder-gray-500'}`}
                  placeholder="My Awesome App"
                  disabled={isCreating}
                  autoFocus
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-[var(--text)] mb-2">Description</label>
                <textarea
                  value={newProject.description}
                  onChange={(e) => setNewProject({ ...newProject, description: e.target.value })}
                  className={`w-full border text-[var(--text)] px-4 py-3 rounded-xl focus:outline-none focus:ring-2 focus:ring-[var(--primary)] resize-none ${theme === 'light' ? 'bg-black/5 border-black/20 placeholder-black/40' : 'bg-white/5 border-white/10 placeholder-gray-500'}`}
                  rows={3}
                  placeholder="Describe your project..."
                  disabled={isCreating}
                />
              </div>

              <div className="flex gap-3 pt-4">
                <button
                  onClick={createProject}
                  disabled={
                    isCreating ||
                    !newProject.name.trim() ||
                    (sourceType === 'github' && !githubRepoUrl.trim()) ||
                    (sourceType === 'base' && !selectedBase)
                  }
                  className="flex-1 bg-[var(--primary)] hover:bg-orange-600 disabled:bg-gray-600 disabled:cursor-not-allowed text-white py-3 rounded-xl font-semibold transition-all"
                >
                  {isCreating
                    ? sourceType === 'github' ? 'Importing...' : sourceType === 'base' ? 'Creating...' : 'Creating...'
                    : sourceType === 'github' ? 'Import & Create' : sourceType === 'base' ? 'Create from Base' : 'Create Project'
                  }
                </button>
                <button
                  onClick={() => setShowCreateModal(false)}
                  disabled={isCreating}
                  className="flex-1 bg-white/5 border border-white/10 text-[var(--text)] py-3 rounded-xl font-semibold hover:bg-white/10 transition-all disabled:opacity-50"
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* GitHub Connect Modal */}
      <GitHubConnectModal
        isOpen={showGithubConnectModal}
        onClose={() => setShowGithubConnectModal(false)}
        onSuccess={() => {
          checkGithubConnection();
          setShowGithubConnectModal(false);
        }}
      />

      {/* Delete Confirmation Dialog */}
      <ConfirmDialog
        isOpen={showDeleteDialog}
        onClose={() => {
          setShowDeleteDialog(false);
          setProjectToDelete(null);
        }}
        onConfirm={confirmDeleteProject}
        title="Delete Project"
        message={`Are you sure you want to delete "${projectToDelete?.name}"? This action cannot be undone.`}
        confirmText="Delete"
        cancelText="Cancel"
        variant="danger"
      />

      {/* Discord Support Bubble */}
      <DiscordSupport />

      {/* Tesslate Footer */}
      <div className="mt-16 pt-6 border-t border-white/5">
        <div className="flex flex-wrap items-center justify-center gap-x-6 gap-y-3 text-sm text-gray-400">
          <div className="flex items-center gap-2">
            <svg className="w-5 h-5 text-[var(--primary)]" viewBox="0 0 161.9 126.66">
              <path d="m13.45,46.48h54.06c10.21,0,16.68-10.94,11.77-19.89l-9.19-16.75c-2.36-4.3-6.87-6.97-11.77-6.97H22.41c-4.95,0-9.5,2.73-11.84,7.09L1.61,26.71c-4.79,8.95,1.69,19.77,11.84,19.77Z" fill="currentColor"/>
              <path d="m61.05,119.93l26.95-46.86c5.09-8.85-1.17-19.91-11.37-20.12l-19.11-.38c-4.9-.1-9.47,2.48-11.91,6.73l-17.89,31.12c-2.47,4.29-2.37,9.6.25,13.8l10.05,16.13c5.37,8.61,17.98,8.39,23.04-.41Z" fill="currentColor"/>
              <path d="m148.46,0h-54.06c-10.21,0-16.68,10.94-11.77,19.89l9.19,16.75c2.36,4.3,6.87,6.97,11.77,6.97h35.9c4.95,0,9.5-2.73,11.84-7.09l8.97-16.75C165.08,10.82,158.6,0,148.46,0Z" fill="currentColor"/>
            </svg>
            <span className="font-semibold text-[var(--text)]">Tesslate.</span>
            <span className="text-[var(--primary)] font-semibold">Build beyond limits</span>
          </div>
          <span className="hidden sm:inline text-gray-600">•</span>
          <span>We're committed to open sourcing AI to empower builders everywhere</span>
          <span className="hidden sm:inline text-gray-600">•</span>
          <a
            href="https://tesslate.com"
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-[var(--primary)] transition-colors flex items-center gap-1.5"
          >
            Learn more
            <ArrowSquareOut className="w-4 h-4" weight="bold" />
          </a>
          <span className="hidden sm:inline text-gray-600">•</span>
          <a
            href="https://docs.tesslate.com"
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-[var(--primary)] transition-colors flex items-center gap-1.5"
          >
            <svg className="w-4 h-4 text-[var(--primary)]" viewBox="0 0 161.9 126.66">
              <path d="m13.45,46.48h54.06c10.21,0,16.68-10.94,11.77-19.89l-9.19-16.75c-2.36-4.3-6.87-6.97-11.77-6.97H22.41c-4.95,0-9.5,2.73-11.84,7.09L1.61,26.71c-4.79,8.95,1.69,19.77,11.84,19.77Z" fill="currentColor"/>
              <path d="m61.05,119.93l26.95-46.86c5.09-8.85-1.17-19.91-11.37-20.12l-19.11-.38c-4.9-.1-9.47,2.48-11.91,6.73l-17.89,31.12c-2.47,4.29-2.37,9.6.25,13.8l10.05,16.13c5.37,8.61,17.98,8.39,23.04-.41Z" fill="currentColor"/>
              <path d="m148.46,0h-54.06c-10.21,0-16.68,10.94-11.77,19.89l9.19,16.75c2.36,4.3,6.87,6.97,11.77,6.97h35.9c4.95,0,9.5-2.73,11.84-7.09l8.97-16.75C165.08,10.82,158.6,0,148.46,0Z" fill="currentColor"/>
            </svg>
            Documentation for <span className="font-semibold">Studio</span>
            <ArrowSquareOut className="w-4 h-4" weight="bold" />
          </a>
        </div>
      </div>
    </div>
  );
}
