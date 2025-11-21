import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { projectsApi, authApi, tasksApi } from '../lib/api';
import { useTheme } from '../theme/ThemeContext';
import {
  MobileMenu,
  ProjectCard
} from '../components/ui';
import type { Status } from '../components/ui';
import { ConfirmDialog, CreateProjectModal } from '../components/modals';
import { LoadingSpinner } from '../components/PulsingGridSpinner';
import toast from 'react-hot-toast';
import {
  Folder,
  Storefront,
  Package,
  Gear,
  Sun,
  Moon,
  FilePlus,
  Books,
  SignOut,
  CaretDown,
  Coins,
  CreditCard,
  User
} from '@phosphor-icons/react';

interface Project {
  id: string;
  slug: string;
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
  const [isCreating, setIsCreating] = useState(false);
  const [deletingProjectIds, setDeletingProjectIds] = useState<Set<string>>(new Set());
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [projectToDelete, setProjectToDelete] = useState<Project | null>(null);
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [userName, setUserName] = useState<string>('');
  const [userCredits, setUserCredits] = useState<number>(0);
  const [userTier, setUserTier] = useState<string>('free');
  const [showUserDropdown, setShowUserDropdown] = useState(false);

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

  const handleCreateProject = async (projectName: string) => {
    if (isCreating) return;

    setIsCreating(true);
    const creatingToast = toast.loading('Creating project...');

    try {
      // Create empty project (containers with marketplace bases are added later in ProjectGraphCanvas)
      const response = await projectsApi.create(
        projectName,
        '',
        'template',  // Empty project - no base needed at project level
        undefined,
        'main',
        undefined
      );

      const project = response.project;

      toast.success('Project created!', { id: creatingToast, duration: 2000 });
      setShowCreateDialog(false);
      setIsCreating(false);

      // Navigate to project graph canvas
      navigate(`/project/${project.slug}`);
    } catch (error: any) {
      const detail = error?.response?.data?.detail;
      const errorMessage = typeof detail === 'string' ? detail : 'Failed to create project';
      toast.error(errorMessage, { id: creatingToast });
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
    const projectSlug = projectToDelete.slug;
    setShowDeleteDialog(false);
    setDeletingProjectIds(prev => new Set(prev).add(projectId));
    const deletingToast = toast.loading('Deleting project...');

    try {
      const response = await projectsApi.delete(projectSlug);  // Use slug for API call
      // Response now includes { task_id, status_endpoint }
      const taskId = response.task_id;

      toast.loading('Deleting project...', { id: deletingToast });

      // Wait for deletion task to complete
      if (taskId) {
        try {
          await tasksApi.pollUntilComplete(taskId);

          // Task completed successfully - remove project from UI
          toast.success('Project deleted successfully', { id: deletingToast });

          // Remove project from state
          setProjects(prev => prev.filter(p => p.id !== projectId));

          setDeletingProjectIds(prev => {
            const updated = new Set(prev);
            updated.delete(projectId);
            return updated;
          });
        } catch (taskError) {
          // Task failed - show error and reload to get accurate state
          console.error('Project deletion task failed:', taskError);
          toast.error('Project deletion failed', { id: deletingToast });

          setDeletingProjectIds(prev => {
            const updated = new Set(prev);
            updated.delete(projectId);
            return updated;
          });

          // Reload to ensure UI matches backend state
          await loadProjects();
        }
      } else {
        // No task ID returned - reload to verify state
        toast.success('Project deleted', { id: deletingToast });
        await loadProjects();
        setDeletingProjectIds(prev => {
          const updated = new Set(prev);
          updated.delete(projectId);
          return updated;
        });
      }
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
        onClick: () => navigate('/settings')
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
    <>
      {/* Mobile Menu - Shows on mobile only */}
      <MobileMenu leftItems={mobileMenuItems.left} rightItems={mobileMenuItems.right} />

      {/* Top Bar */}
      <div className="h-12 bg-[var(--surface)] border-b border-[var(--sidebar-border)] flex items-center px-4 md:px-6 justify-between">
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
                          navigate('/settings');
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
                onClick={() => setShowCreateDialog(true)}
                disabled={isCreating}
                className={`
                  group bg-white/[0.01] rounded-2xl p-6
                  border-2 border-dashed border-[rgba(var(--primary-rgb),0.3)]
                  hover:border-[rgba(var(--primary-rgb),0.6)]
                  transition-all duration-300
                  hover:transform hover:-translate-y-1
                  flex flex-col items-center justify-center gap-3
                  ${filteredProjects.length === 0 ? 'w-full min-h-[400px]' : 'min-h-[240px]'}
                  ${isCreating ? 'opacity-50 cursor-not-allowed' : ''}
                `}
              >
                <div className="w-16 h-16 bg-[rgba(var(--primary-rgb),0.2)] rounded-2xl flex items-center justify-center group-hover:bg-[rgba(var(--primary-rgb),0.3)] transition-colors">
                  <FilePlus className="w-8 h-8 text-[var(--primary)]" weight="fill" />
                </div>
                <div className="text-center">
                  <h3 className="font-heading text-lg font-bold text-[var(--text)] mb-2">
                    Create New Project
                  </h3>
                  <p className="text-sm text-gray-500">
                    Start building something amazing
                  </p>
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
                    slug: project.slug
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
                <p className="text-[var(--text)]/40 text-sm">No projects found. Create one to get started!</p>
              </div>
            )}
          </div>
        </div>


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

      {/* Create Project Modal */}
      <CreateProjectModal
        isOpen={showCreateDialog}
        onClose={() => setShowCreateDialog(false)}
        onConfirm={handleCreateProject}
        isLoading={isCreating}
      />

    </>
  );
}
