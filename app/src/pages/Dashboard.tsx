import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { projectsApi, marketplaceApi, authApi } from '../lib/api';
import { githubApi } from '../lib/github-api';
import { useTheme } from '../theme/ThemeContext';
import {
  MobileMenu,
  NavigationSidebar,
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
  Folder,
  Storefront,
  Package,
  Gear,
  Sun,
  Moon,
  FilePlus,
  GithubLogo,
  GitBranch,
  Books,
  SignOut,
  CaretDown,
  Check,
  Coins,
  CreditCard,
  User
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

export default function Dashboard() {
  const navigate = useNavigate();
  const { theme, toggleTheme } = useTheme();
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newProject, setNewProject] = useState({ name: '', description: '' });
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
  const [userCredits, setUserCredits] = useState<number>(0);
  const [userTier, setUserTier] = useState<string>('free');
  const [showUserDropdown, setShowUserDropdown] = useState(false);
  const [containerStatuses, setContainerStatuses] = useState<Record<string, 'starting' | 'running' | 'stopped' | 'error'>>({});

  // Fetch current user data
  useEffect(() => {
    const fetchUserData = async () => {
      try {
        const user = await authApi.getCurrentUser();
        setUserName(user.name || user.username || 'there');
        setUserCredits(user.credits_balance || 0);
        setUserTier(user.subscription_tier || 'free');
      } catch (e) {
        console.error('Failed to fetch user data:', e);
        setUserName('there');
        setUserCredits(0);
        setUserTier('free');
      }
    };
    fetchUserData();
  }, []);

  useEffect(() => {
    loadProjects();
  }, []);

  // Poll container statuses
  useEffect(() => {
    const pollContainerStatuses = async () => {
      if (projects.length === 0) return;

      for (const project of projects) {
        try {
          const status = await projectsApi.getContainerStatus(project.slug);
          setContainerStatuses(prev => ({
            ...prev,
            [project.slug]: status.running ? (status.health === 'healthy' ? 'running' : 'starting') : 'stopped'
          }));
        } catch (error) {
          // Container might not exist yet, that's okay
          setContainerStatuses(prev => ({
            ...prev,
            [project.slug]: 'stopped'
          }));
        }
      }
    };

    // Poll immediately and then every 10 seconds
    pollContainerStatuses();
    const interval = setInterval(pollContainerStatuses, 10000);

    return () => clearInterval(interval);
  }, [projects]);

  useEffect(() => {
    if (showCreateModal) {
      checkGithubConnection();
      loadUserBases();
    }
  }, [showCreateModal]);

  // Handle Ctrl+Enter keyboard shortcut for creating project
  useEffect(() => {
    if (!showCreateModal) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        // Check if form is valid before submitting
        const isValid = newProject.name.trim() &&
          (sourceType !== 'github' || githubRepoUrl.trim()) &&
          (sourceType !== 'base' || selectedBase !== null);

        if (isValid && !isCreating) {
          createProject();
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [showCreateModal, newProject, sourceType, githubRepoUrl, selectedBase, isCreating]);

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

  const handleRestartContainer = async (slug: string) => {
    const restartToast = toast.loading('Restarting container...');
    try {
      setContainerStatuses(prev => ({ ...prev, [slug]: 'starting' }));
      await projectsApi.restartDevServer(slug);
      toast.success('Container restarted successfully', { id: restartToast });
      // Status will be updated by the polling
    } catch (error) {
      toast.error('Failed to restart container', { id: restartToast });
      setContainerStatuses(prev => ({ ...prev, [slug]: 'error' }));
    }
  };

  const handleStopContainer = async (slug: string) => {
    const stopToast = toast.loading('Stopping container...');
    try {
      await projectsApi.stopDevServer(slug);
      toast.success('Container stopped successfully', { id: stopToast });
      setContainerStatuses(prev => ({ ...prev, [slug]: 'stopped' }));
    } catch (error) {
      toast.error('Failed to stop container', { id: stopToast });
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

  // Show all projects (no filtering)
  const filteredProjects = projects;

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

  // Sidebar items for mobile menu
  const mobileMenuItems = {
    left: [
      {
        icon: <Folder className="w-5 h-5" weight="fill" />,
        title: 'Projects',
        onClick: () => {},
        active: true
      },
      {
        icon: <Storefront className="w-5 h-5" weight="fill" />,
        title: 'Marketplace',
        onClick: () => navigate('/marketplace')
      },
      {
        icon: <Books className="w-5 h-5" weight="fill" />,
        title: 'Library',
        onClick: () => navigate('/library')
      },
      {
        icon: <Package className="w-5 h-5" weight="fill" />,
        title: 'Components',
        onClick: () => toast('Components library coming soon!')
      }
    ],
    right: [
      {
        icon: theme === 'dark' ? <Sun className="w-5 h-5" weight="fill" /> : <Moon className="w-5 h-5" weight="fill" />,
        title: theme === 'dark' ? 'Light Mode' : 'Dark Mode',
        onClick: toggleTheme
      },
      {
        icon: <Gear className="w-5 h-5" weight="fill" />,
        title: 'Settings',
        onClick: () => toast('Settings coming soon!')
      },
      {
        icon: <SignOut className="w-5 h-5" weight="fill" />,
        title: 'Logout',
        onClick: logout
      }
    ]
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <LoadingSpinner message="Loading projects..." size={80} />
      </div>
    );
  }

  return (
    <div className="h-screen flex overflow-hidden bg-[var(--bg)]">
      {/* Mobile Warning */}
      <MobileWarning />

      {/* Mobile Menu - Shows on mobile only */}
      <MobileMenu leftItems={mobileMenuItems.left} rightItems={mobileMenuItems.right} />

      {/* Navigation Sidebar */}
      <NavigationSidebar activePage="dashboard" />

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Top Bar */}
        <div className="h-12 bg-[#0a0a0a] border-b border-white/10 flex items-center px-4 md:px-6 justify-between">
          <div className="flex items-center gap-4 md:gap-6">
            <h1 className="font-heading text-sm font-semibold text-[var(--text)]">Projects</h1>
          </div>

          {/* Right side - User Profile */}
          <div className="flex items-center gap-3">
            {/* Credits Display */}
            <div className="hidden md:flex items-center gap-2 px-3 py-1.5 bg-[var(--primary)]/10 border border-[var(--primary)]/20 rounded-lg">
              <Coins size={16} className="text-[var(--primary)]" weight="fill" />
              <span className="text-sm font-semibold text-[var(--primary)]">
                {userCredits.toLocaleString()}
              </span>
            </div>

            {/* User Dropdown */}
            <div className="relative">
              <button
                onClick={() => setShowUserDropdown(!showUserDropdown)}
                className="hidden md:flex items-center gap-2 px-3 py-1.5 hover:bg-white/5 rounded-lg transition-colors"
              >
                <User size={18} className="text-[var(--text)]" weight="fill" />
                <span className="text-sm font-medium text-[var(--text)]">{userName}</span>
                {userTier === 'pro' && (
                  <span className="px-2 py-0.5 bg-gradient-to-r from-[var(--primary)] to-[var(--primary-hover)] text-white text-xs font-bold rounded-md">
                    PRO
                  </span>
                )}
                <CaretDown
                  size={14}
                  className={`text-[var(--text)]/60 transition-transform ${showUserDropdown ? 'rotate-180' : ''}`}
                />
              </button>

              {/* Dropdown Menu */}
              {showUserDropdown && (
                <>
                  {/* Backdrop */}
                  <div
                    className="fixed inset-0 z-40"
                    onClick={() => setShowUserDropdown(false)}
                  />

                  {/* Menu */}
                  <div className="absolute right-0 mt-2 w-56 bg-[var(--surface)] border border-white/10 rounded-xl shadow-2xl z-50 overflow-hidden">
                    <div className="py-2">
                      {/* Credits Item */}
                      <button
                        onClick={() => {
                          setShowUserDropdown(false);
                          navigate('/billing');
                        }}
                        className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-white/5 transition-colors text-left"
                      >
                        <Coins size={18} className="text-[var(--primary)]" weight="fill" />
                        <div className="flex-1">
                          <div className="text-sm font-medium text-[var(--text)]">Credits</div>
                          <div className="text-xs text-[var(--text)]/60">{userCredits.toLocaleString()} available</div>
                        </div>
                      </button>

                      <div className="h-px bg-white/10 my-2" />

                      {/* Subscriptions */}
                      <button
                        onClick={() => {
                          setShowUserDropdown(false);
                          navigate('/billing/plans');
                        }}
                        className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-white/5 transition-colors text-left"
                      >
                        <CreditCard size={18} className="text-[var(--text)]/80" />
                        <span className="text-sm font-medium text-[var(--text)]">Subscriptions</span>
                      </button>

                      {/* Settings */}
                      <button
                        onClick={() => {
                          setShowUserDropdown(false);
                          toast('Settings coming soon!');
                        }}
                        className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-white/5 transition-colors text-left"
                      >
                        <Gear size={18} className="text-[var(--text)]/80" />
                        <span className="text-sm font-medium text-[var(--text)]">Settings</span>
                      </button>

                      <div className="h-px bg-white/10 my-2" />

                      {/* Logout */}
                      <button
                        onClick={() => {
                          setShowUserDropdown(false);
                          navigate('/logout');
                        }}
                        className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-red-500/10 transition-colors text-left group"
                      >
                        <SignOut size={18} className="text-red-400 group-hover:text-red-400" />
                        <span className="text-sm font-medium text-red-400">Logout</span>
                      </button>
                    </div>
                  </div>
                </>
              )}
            </div>

            {/* Mobile hamburger menu */}
            <button
              onClick={() => window.dispatchEvent(new Event('toggleMobileMenu'))}
              className="md:hidden p-2 hover:bg-white/10 active:bg-white/20 rounded-lg transition-colors"
            >
              <svg className="w-6 h-6 text-[var(--text)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            </button>
          </div>
        </div>

        {/* Tab Filters - Mobile */}

        {/* Scrollable Content */}
        <div className="flex-1 overflow-auto bg-[var(--bg)]">
          <div className="p-4 md:p-6">
            {/* Projects Grid */}
            <div className={filteredProjects.length === 0 ? "" : "grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4"}>
              {/* Create New Project Card */}
              <button
                onClick={() => setShowCreateModal(true)}
                className={`
                  group bg-white/[0.01] rounded-2xl p-6
                  border-2 border-dashed border-[rgba(var(--primary-rgb),0.3)]
                  hover:border-[rgba(var(--primary-rgb),0.6)]
                  transition-all duration-300
                  hover:transform hover:-translate-y-1
                  flex flex-col items-center justify-center gap-3
                  ${filteredProjects.length === 0 ? 'w-full min-h-[400px]' : 'min-h-[240px]'}
                `}
              >
                <div className="w-16 h-16 bg-[rgba(var(--primary-rgb),0.2)] rounded-2xl flex items-center justify-center group-hover:bg-[rgba(var(--primary-rgb),0.3)] transition-colors">
                  <FilePlus className="w-8 h-8 text-[var(--primary)]" weight="fill" />
                </div>
                <div className="text-center">
                  <h3 className="font-heading text-lg font-bold text-[var(--text)] mb-2">Create New Project</h3>
                  <p className="text-sm text-gray-500">Start building something amazing</p>
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
                    isLive: project.status === 'launch',
                    containerStatus: containerStatuses[project.slug],
                    slug: project.slug
                  }}
                  onOpen={() => navigate(`/project/${project.slug}`)}
                  onDelete={() => deleteProject(project.id)}
                  onStatusChange={(status) => updateProjectStatus(project.id, status)}
                  onFork={() => handleForkProject(project.id)}
                  onRestartContainer={() => handleRestartContainer(project.slug)}
                  onStopContainer={() => handleStopContainer(project.slug)}
                  isDeleting={deletingProjectIds.has(project.id)}
                />
              ))}
            </div>

            {/* Empty State */}
            {filteredProjects.length === 0 && (
              <div className="text-center py-16">
                <p className="text-[var(--text)]/40 text-sm">No projects found. Create one to get started!</p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Create Project Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50" onClick={() => !isCreating && setShowCreateModal(false)}>
          <div className="bg-[var(--surface)] p-8 rounded-3xl w-full max-w-lg shadow-2xl border border-white/10" onClick={(e) => e.stopPropagation()}>
            <div className="text-center mb-6">
              <div className="w-16 h-16 bg-[rgba(var(--primary-rgb),0.2)] rounded-2xl flex items-center justify-center mx-auto mb-4">
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
                        ? 'border-[var(--primary)] bg-[rgba(var(--primary-rgb),0.1)]'
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
                        ? 'border-[var(--primary)] bg-[rgba(var(--primary-rgb),0.1)]'
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
                        ? 'border-[var(--primary)] bg-[rgba(var(--primary-rgb),0.1)]'
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
                        className="text-[var(--primary)] hover:text-[var(--primary-hover)] text-sm font-medium"
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
                                    ? 'bg-[rgba(var(--primary-rgb),0.1)]'
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
                        <span className="text-xs text-[var(--primary)]">Not Connected</span>
                      )}
                    </div>
                    {!githubConnected && !checkingGithub && (
                      <button
                        onClick={() => setShowGithubConnectModal(true)}
                        disabled={isCreating}
                        className="text-xs bg-[var(--status-purple)] hover:bg-[var(--status-purple)]/80 disabled:bg-gray-600 disabled:cursor-not-allowed text-white px-3 py-1.5 rounded-lg font-medium transition-all"
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
                  className="flex-1 bg-[var(--primary)] hover:bg-[var(--primary-hover)] disabled:bg-gray-600 disabled:cursor-not-allowed text-white py-3 rounded-xl font-semibold transition-all"
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
    </div>
  );
}
