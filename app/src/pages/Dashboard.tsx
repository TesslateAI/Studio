import { useState, useEffect, useRef } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { projectsApi, tasksApi } from '../lib/api';
import { useTheme } from '../theme/ThemeContext';
import { MobileMenu, ProjectCard } from '../components/ui';
import type { Status } from '../components/ui';
import { ConfirmDialog, CreateProjectModal, RepoImportModal } from '../components/modals';
import { LoadingSpinner } from '../components/PulsingGridSpinner';
import toast from 'react-hot-toast';
import {
  Folder,
  Storefront,
  Gear,
  Sun,
  Moon,
  FilePlus,
  Books,
  SignOut,
  GitBranch,
  ChatCircleDots,
  Article,
  Trash,
  X,
  FunnelSimple,
  SortAscending,
  SortDescending,
  CaretDown,
} from '@phosphor-icons/react';

type SortField = 'updated_at' | 'created_at' | 'name';
type SortDirection = 'asc' | 'desc';
type FilterStatus = Status | 'all';
type FilterEnvStatus = EnvironmentStatus | 'all';

interface Project {
  id: string;
  slug: string;
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
  status?: Status;
  agents?: Array<{ icon: string; name: string }>;
  environment_status?: string;
  compute_tier?: string;
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
  const [showImportDialog, setShowImportDialog] = useState(false);
  const [selectedProjectIds, setSelectedProjectIds] = useState<Set<string>>(new Set());
  const [showBulkDeleteDialog, setShowBulkDeleteDialog] = useState(false);
  const [viewMode, setViewMode] = useState<'cards' | 'list'>('cards');
  const [sortField, setSortField] = useState<SortField>('updated_at');
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');
  const [filterStatus, setFilterStatus] = useState<FilterStatus>('all');
  const [filterEnvStatus, setFilterEnvStatus] = useState<FilterEnvStatus>('all');
  const [showFilterMenu, setShowFilterMenu] = useState(false);
  const [showSortMenu, setShowSortMenu] = useState(false);
  const filterMenuRef = useRef<HTMLDivElement>(null);
  const sortMenuRef = useRef<HTMLDivElement>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const autoCreateTriggered = useRef(false);
  const [createBaseId, setCreateBaseId] = useState<string | undefined>();
  const [createBaseVersion, setCreateBaseVersion] = useState<string | undefined>();
  const [importRepoUrl, setImportRepoUrl] = useState<string | undefined>();

  useEffect(() => {
    loadProjects();
  }, []);

  // Open create modal with pre-selected base from search params (e.g., from marketplace "Use This Version")
  useEffect(() => {
    if (autoCreateTriggered.current) return;
    const shouldCreate = searchParams.get('create');
    const baseId = searchParams.get('base_id');
    const baseVersion = searchParams.get('base_version');
    if (shouldCreate === 'true' && baseId) {
      autoCreateTriggered.current = true;
      setSearchParams({}, { replace: true });
      setCreateBaseId(baseId);
      setCreateBaseVersion(baseVersion || undefined);
      setShowCreateDialog(true);
      return;
    }

    const importRepo = searchParams.get('import_repo');
    if (importRepo) {
      autoCreateTriggered.current = true;
      setSearchParams({}, { replace: true });
      setImportRepoUrl(importRepo);
      setShowImportDialog(true);
    }
  }, [searchParams]);

  // Poll for project status updates every 60 seconds
  useEffect(() => {
    const pollInterval = setInterval(() => {
      loadProjects();
    }, 60000);

    return () => clearInterval(pollInterval);
  }, []);

  const loadProjects = async () => {
    try {
      const data = await projectsApi.getAll();
      // Add mock status and agents to existing projects
      const projectsWithMeta = data.map((p: Project) => ({
        ...p,
        status: (p.status || 'build') as Status,
        agents: p.agents || [],
      }));
      setProjects(projectsWithMeta);
    } catch {
      toast.error('Failed to load projects');
    } finally {
      setLoading(false);
    }
  };

  const handleCreateProject = async (
    projectName: string,
    baseId?: string,
    baseVersion?: string
  ) => {
    if (isCreating) return;

    setIsCreating(true);
    const creatingToast = toast.loading('Creating project...');

    try {
      // Create project with base (creates container automatically)
      // baseId is required - CreateProjectModal auto-selects a base
      const response = await projectsApi.create(
        projectName,
        '',
        'base', // Always use 'base' source type
        undefined,
        'main',
        baseId,
        baseVersion || undefined
      );

      const project = response.project;
      const taskId = response.task_id;

      // Poll for task completion to get container_id
      if (taskId) {
        toast.loading('Setting up project...', { id: creatingToast });
        try {
          await tasksApi.pollUntilComplete(taskId);
          toast.success('Project created!', { id: creatingToast, duration: 2000 });
          setShowCreateDialog(false);
          setIsCreating(false);

          // Navigate to setup page for user to review config
          navigate(`/project/${project.slug}/setup`);
        } catch (taskError) {
          console.error('Project setup task failed:', taskError);
          const taskErrMsg = taskError instanceof Error ? taskError.message : 'Setup failed';
          toast.error(taskErrMsg, { id: creatingToast });
          setIsCreating(false);
          // Navigate to graph canvas as fallback
          navigate(`/project/${project.slug}`);
        }
      } else {
        toast.success('Project created!', { id: creatingToast, duration: 2000 });
        setShowCreateDialog(false);
        setIsCreating(false);
        // Navigate to setup page
        navigate(`/project/${project.slug}/setup`);
      }
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      const detail = err?.response?.data?.detail;
      const errorMessage = typeof detail === 'string' ? detail : 'Failed to create project';
      toast.error(errorMessage, { id: creatingToast });
      setIsCreating(false);
    }
  };

  // Close menus on outside click
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (filterMenuRef.current && !filterMenuRef.current.contains(e.target as Node)) {
        setShowFilterMenu(false);
      }
      if (sortMenuRef.current && !sortMenuRef.current.contains(e.target as Node)) {
        setShowSortMenu(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Filter and sort projects
  const filteredProjects = projects
    .filter((p) => {
      if (filterStatus !== 'all' && (p.status || 'build') !== filterStatus) return false;
      if (filterEnvStatus !== 'all' && p.environment_status !== filterEnvStatus) return false;
      return true;
    })
    .sort((a, b) => {
      const dir = sortDirection === 'asc' ? 1 : -1;
      if (sortField === 'name') {
        return dir * a.name.localeCompare(b.name);
      }
      const dateA = new Date(a[sortField] || 0).getTime();
      const dateB = new Date(b[sortField] || 0).getTime();
      return dir * (dateA - dateB);
    });

  const hasActiveFilters = filterStatus !== 'all' || filterEnvStatus !== 'all';

  const clearFilters = () => {
    setFilterStatus('all');
    setFilterEnvStatus('all');
  };

  const sortLabels: Record<SortField, string> = {
    updated_at: 'Last updated',
    created_at: 'Date created',
    name: 'Name',
  };

  // Prune selection when projects reload (remove IDs for projects that no longer exist)
  useEffect(() => {
    setSelectedProjectIds((prev) => {
      const projectIdSet = new Set(projects.map((p) => p.id));
      const pruned = new Set([...prev].filter((id) => projectIdSet.has(id)));
      return pruned.size !== prev.size ? pruned : prev;
    });
  }, [projects]);

  // Escape key clears selection
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && selectedProjectIds.size > 0) {
        setSelectedProjectIds(new Set());
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [selectedProjectIds.size]);

  const toggleProjectSelection = (id: string) => {
    setSelectedProjectIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const clearSelection = () => setSelectedProjectIds(new Set());

  const _selectAllProjects = () => {
    setSelectedProjectIds(new Set(filteredProjects.map((p) => p.id)));
  };

  const confirmBulkDelete = async () => {
    const toDelete = projects.filter((p) => selectedProjectIds.has(p.id));
    if (toDelete.length === 0) return;

    setShowBulkDeleteDialog(false);

    // Mark all as deleting
    setDeletingProjectIds((prev) => {
      const next = new Set(prev);
      for (const p of toDelete) next.add(p.id);
      return next;
    });

    // Clear selection so floating bar disappears
    setSelectedProjectIds(new Set());

    const deletingToast = toast.loading(
      `Deleting ${toDelete.length} project${toDelete.length > 1 ? 's' : ''}...`
    );

    const results = await Promise.allSettled(
      toDelete.map(async (project) => {
        const response = await projectsApi.delete(project.slug);
        const taskId = response.task_id;
        if (taskId) {
          await tasksApi.pollUntilComplete(taskId);
        }
        return project.id;
      })
    );

    let successCount = 0;
    let failCount = 0;

    for (const result of results) {
      if (result.status === 'fulfilled') {
        successCount++;
        const projectId = result.value;
        setProjects((prev) => prev.filter((p) => p.id !== projectId));
        setDeletingProjectIds((prev) => {
          const next = new Set(prev);
          next.delete(projectId);
          return next;
        });
      } else {
        failCount++;
      }
    }

    // Clear remaining deleting states for failures
    if (failCount > 0) {
      setDeletingProjectIds((prev) => {
        const next = new Set(prev);
        for (const p of toDelete) next.delete(p.id);
        return next;
      });
      await loadProjects();
    }

    // Summary toast
    if (failCount === 0) {
      toast.success(`Deleted ${successCount} project${successCount > 1 ? 's' : ''}`, {
        id: deletingToast,
      });
    } else if (successCount === 0) {
      toast.error(`Failed to delete ${failCount} project${failCount > 1 ? 's' : ''}`, {
        id: deletingToast,
      });
    } else {
      toast.success(`Deleted ${successCount}, failed ${failCount}`, { id: deletingToast });
    }
  };

  const deleteProject = (id: string) => {
    const project = projects.find((p) => p.id === id);
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
    setDeletingProjectIds((prev) => new Set(prev).add(projectId));
    const deletingToast = toast.loading('Deleting project...');

    try {
      const response = await projectsApi.delete(projectSlug); // Use slug for API call
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
          setProjects((prev) => prev.filter((p) => p.id !== projectId));

          setDeletingProjectIds((prev) => {
            const updated = new Set(prev);
            updated.delete(projectId);
            return updated;
          });
        } catch (taskError) {
          // Task failed - show error and reload to get accurate state
          console.error('Project deletion task failed:', taskError);
          toast.error('Project deletion failed', { id: deletingToast });

          setDeletingProjectIds((prev) => {
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
        setDeletingProjectIds((prev) => {
          const updated = new Set(prev);
          updated.delete(projectId);
          return updated;
        });
      }
    } catch {
      toast.error('Failed to delete project', { id: deletingToast });
      // Remove from deleting state on error
      setDeletingProjectIds((prev) => {
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
      setProjects((prev) => prev.map((p) => (p.id === id ? { ...p, status } : p)));
      toast.success(`Project moved to ${status}`);
      // TODO: Add API call to persist status
    } catch {
      toast.error('Failed to update status');
    }
  };

  const handleHibernateProject = async (slug: string) => {
    const hibernatingToast = toast.loading('Hibernating project...');
    try {
      await projectsApi.hibernateProject(slug);
      toast.success('Hibernation started', { id: hibernatingToast });
      await loadProjects();
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      const errorMessage = err?.response?.data?.detail || 'Failed to hibernate project';
      toast.error(errorMessage, { id: hibernatingToast });
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
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      const errorMessage = err?.response?.data?.detail || 'Failed to fork project';
      toast.error(errorMessage, { id: forkingToast });
    }
  };

  const logout = () => {
    localStorage.removeItem('token');
    navigate('/login');
  };

  const formatDate = (dateString: string) => {
    if (!dateString) return 'Never';

    try {
      // Handle ISO 8601 format with or without timezone
      // If the date string doesn't have timezone info, assume UTC
      const dateStr =
        dateString.includes('Z') ||
        dateString.includes('+') ||
        (dateString.includes('T') && dateString.match(/[+-]\d{2}:\d{2}$/))
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

  // Sidebar items for mobile menu - matches NavigationSidebar desktop items
  const mobileMenuItems = {
    left: [
      {
        icon: <Folder className="w-5 h-5" weight="fill" />,
        title: 'Projects',
        onClick: () => {},
        active: true,
      },
      {
        icon: <Storefront className="w-5 h-5" weight="fill" />,
        title: 'Marketplace',
        onClick: () => navigate('/marketplace'),
      },
      {
        icon: <Books className="w-5 h-5" weight="fill" />,
        title: 'Library',
        onClick: () => navigate('/library'),
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

      {/* Header */}
      <div className="flex-shrink-0">
        {/* Title Row — with border below */}
        <div
          className="h-10 flex items-center justify-between gap-[6px]"
          style={{
            paddingLeft: '18px',
            paddingRight: '4px',
            borderBottom: 'var(--border-width) solid var(--border)',
          }}
        >
          {/* Mobile hamburger — hidden on md+ */}
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

          <h2 className="text-xs font-semibold text-[var(--text)] flex-1">Projects</h2>

          <button
            onClick={() => setShowCreateDialog(true)}
            disabled={isCreating}
            className="btn btn-icon"
            aria-label="New project"
          >
            <FilePlus className="w-4 h-4" />
          </button>
        </div>

        {/* Tab Bar — views left, filter/sort/display right */}
        <div
          className="h-10 flex items-center justify-between"
          style={{ paddingLeft: '7px', paddingRight: '10px' }}
        >
          {/* Left: View tabs */}
          <div className="flex items-center gap-1 flex-1 min-w-0">
            <button
              onClick={() => {
                setFilterStatus('all');
                setFilterEnvStatus('all');
              }}
              className={`btn ${!hasActiveFilters ? 'btn-tab-active' : 'btn-tab'}`}
            >
              All projects
            </button>

            {/* Active filter pills */}
            {filterStatus !== 'all' && (
              <button onClick={() => setFilterStatus('all')} className="btn btn-tab-active btn-sm">
                {filterStatus.charAt(0).toUpperCase() + filterStatus.slice(1)}
                <X className="w-3 h-3 ml-0.5 opacity-60" />
              </button>
            )}
            {filterEnvStatus !== 'all' && (
              <button
                onClick={() => setFilterEnvStatus('all')}
                className="btn btn-tab-active btn-sm"
              >
                {filterEnvStatus.charAt(0).toUpperCase() + filterEnvStatus.slice(1)}
                <X className="w-3 h-3 ml-0.5 opacity-60" />
              </button>
            )}
          </div>

          {/* Right: Filter, Sort, Display */}
          <div className="flex items-center gap-[2px]">
            {/* Filter button */}
            <div ref={filterMenuRef} className="relative">
              <button
                onClick={() => {
                  setShowFilterMenu((v) => !v);
                  setShowSortMenu(false);
                }}
                className={`btn btn-icon ${hasActiveFilters ? 'btn-active' : ''}`}
                aria-label="Filter"
              >
                <FunnelSimple className="w-4 h-4" weight={hasActiveFilters ? 'fill' : 'regular'} />
              </button>

              {showFilterMenu && (
                <div
                  className="absolute right-0 top-full mt-1 z-50 min-w-[200px] py-1 rounded-[var(--radius-medium)] border bg-[var(--surface)] shadow-xl"
                  style={{ borderWidth: 'var(--border-width)', borderColor: 'var(--border-hover)' }}
                >
                  {/* Status filter */}
                  <div className="px-3 py-1.5 text-[10px] font-semibold text-[var(--text-subtle)] uppercase tracking-wider">
                    Status
                  </div>
                  {(['all', 'idea', 'build', 'launch'] as const).map((status) => (
                    <button
                      key={status}
                      onClick={() => {
                        setFilterStatus(status);
                        setShowFilterMenu(false);
                      }}
                      className={`w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 transition-colors ${
                        filterStatus === status
                          ? 'text-[var(--text)] bg-[var(--surface-hover)]'
                          : 'text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]'
                      }`}
                    >
                      {status === 'all' ? (
                        'All statuses'
                      ) : (
                        <>
                          <span
                            className={`w-2 h-2 rounded-full ${
                              status === 'idea'
                                ? 'bg-purple-500'
                                : status === 'build'
                                  ? 'bg-yellow-500'
                                  : 'bg-emerald-500'
                            }`}
                          />
                          {status.charAt(0).toUpperCase() + status.slice(1)}
                        </>
                      )}
                      {filterStatus === status && (
                        <svg className="w-3 h-3 ml-auto" fill="currentColor" viewBox="0 0 16 16">
                          <path d="M13.78 4.22a.75.75 0 010 1.06l-7.25 7.25a.75.75 0 01-1.06 0L2.22 9.28a.75.75 0 011.06-1.06L6 10.94l6.72-6.72a.75.75 0 011.06 0z" />
                        </svg>
                      )}
                    </button>
                  ))}

                  {/* Divider */}
                  <div className="my-1 border-t" style={{ borderColor: 'var(--border)' }} />

                  {/* Environment filter */}
                  <div className="px-3 py-1.5 text-[10px] font-semibold text-[var(--text-subtle)] uppercase tracking-wider">
                    Environment
                  </div>
                  {(['all', 'active', 'hibernated', 'stopped', 'creating'] as const).map(
                    (envStatus) => (
                      <button
                        key={envStatus}
                        onClick={() => {
                          setFilterEnvStatus(envStatus);
                          setShowFilterMenu(false);
                        }}
                        className={`w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 transition-colors ${
                          filterEnvStatus === envStatus
                            ? 'text-[var(--text)] bg-[var(--surface-hover)]'
                            : 'text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]'
                        }`}
                      >
                        {envStatus === 'all'
                          ? 'All environments'
                          : envStatus.charAt(0).toUpperCase() + envStatus.slice(1)}
                        {filterEnvStatus === envStatus && (
                          <svg className="w-3 h-3 ml-auto" fill="currentColor" viewBox="0 0 16 16">
                            <path d="M13.78 4.22a.75.75 0 010 1.06l-7.25 7.25a.75.75 0 01-1.06 0L2.22 9.28a.75.75 0 011.06-1.06L6 10.94l6.72-6.72a.75.75 0 011.06 0z" />
                          </svg>
                        )}
                      </button>
                    )
                  )}

                  {/* Clear all filters */}
                  {hasActiveFilters && (
                    <>
                      <div className="my-1 border-t" style={{ borderColor: 'var(--border)' }} />
                      <button
                        onClick={() => {
                          clearFilters();
                          setShowFilterMenu(false);
                        }}
                        className="w-full text-left px-3 py-1.5 text-xs text-[var(--status-error)] hover:bg-[var(--surface-hover)] transition-colors"
                      >
                        Clear all filters
                      </button>
                    </>
                  )}
                </div>
              )}
            </div>

            {/* Sort button */}
            <div ref={sortMenuRef} className="relative">
              <button
                onClick={() => {
                  setShowSortMenu((v) => !v);
                  setShowFilterMenu(false);
                }}
                className={`btn ${sortField !== 'updated_at' || sortDirection !== 'desc' ? 'btn-active' : ''}`}
                aria-label="Sort"
                style={{ gap: '4px' }}
              >
                {sortDirection === 'desc' ? (
                  <SortDescending className="w-4 h-4" />
                ) : (
                  <SortAscending className="w-4 h-4" />
                )}
                <span className="hidden sm:inline text-xs">{sortLabels[sortField]}</span>
                <CaretDown className="w-3 h-3 opacity-50" />
              </button>

              {showSortMenu && (
                <div
                  className="absolute right-0 top-full mt-1 z-50 min-w-[180px] py-1 rounded-[var(--radius-medium)] border bg-[var(--surface)] shadow-xl"
                  style={{ borderWidth: 'var(--border-width)', borderColor: 'var(--border-hover)' }}
                >
                  <div className="px-3 py-1.5 text-[10px] font-semibold text-[var(--text-subtle)] uppercase tracking-wider">
                    Sort by
                  </div>
                  {(['updated_at', 'created_at', 'name'] as SortField[]).map((field) => (
                    <button
                      key={field}
                      onClick={() => {
                        if (sortField === field) {
                          setSortDirection((d) => (d === 'asc' ? 'desc' : 'asc'));
                        } else {
                          setSortField(field);
                          setSortDirection(field === 'name' ? 'asc' : 'desc');
                        }
                        setShowSortMenu(false);
                      }}
                      className={`w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 transition-colors ${
                        sortField === field
                          ? 'text-[var(--text)] bg-[var(--surface-hover)]'
                          : 'text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]'
                      }`}
                    >
                      {sortLabels[field]}
                      {sortField === field && (
                        <span className="ml-auto text-[var(--text-subtle)]">
                          {sortDirection === 'asc' ? (
                            <SortAscending className="w-3.5 h-3.5" />
                          ) : (
                            <SortDescending className="w-3.5 h-3.5" />
                          )}
                        </span>
                      )}
                    </button>
                  ))}

                  <div className="my-1 border-t" style={{ borderColor: 'var(--border)' }} />

                  {/* Direction toggle */}
                  <div className="px-3 py-1.5 text-[10px] font-semibold text-[var(--text-subtle)] uppercase tracking-wider">
                    Direction
                  </div>
                  {(['desc', 'asc'] as SortDirection[]).map((dir) => (
                    <button
                      key={dir}
                      onClick={() => {
                        setSortDirection(dir);
                        setShowSortMenu(false);
                      }}
                      className={`w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 transition-colors ${
                        sortDirection === dir
                          ? 'text-[var(--text)] bg-[var(--surface-hover)]'
                          : 'text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]'
                      }`}
                    >
                      {dir === 'desc' ? (
                        <>
                          <SortDescending className="w-3.5 h-3.5" /> Descending
                        </>
                      ) : (
                        <>
                          <SortAscending className="w-3.5 h-3.5" /> Ascending
                        </>
                      )}
                      {sortDirection === dir && (
                        <svg className="w-3 h-3 ml-auto" fill="currentColor" viewBox="0 0 16 16">
                          <path d="M13.78 4.22a.75.75 0 010 1.06l-7.25 7.25a.75.75 0 01-1.06 0L2.22 9.28a.75.75 0 011.06-1.06L6 10.94l6.72-6.72a.75.75 0 011.06 0z" />
                        </svg>
                      )}
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Display mode toggle */}
            <button
              onClick={() => setViewMode((v) => (v === 'cards' ? 'list' : 'cards'))}
              className={`btn btn-icon ${viewMode === 'list' ? 'btn-active' : ''}`}
              aria-label={viewMode === 'cards' ? 'Switch to list view' : 'Switch to card view'}
            >
              {viewMode === 'cards' ? (
                /* Grid icon */
                <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 16 16">
                  <path d="M1 2.5A1.5 1.5 0 012.5 1h3A1.5 1.5 0 017 2.5v3A1.5 1.5 0 015.5 7h-3A1.5 1.5 0 011 5.5v-3zm8 0A1.5 1.5 0 0110.5 1h3A1.5 1.5 0 0115 2.5v3A1.5 1.5 0 0113.5 7h-3A1.5 1.5 0 019 5.5v-3zm-8 8A1.5 1.5 0 012.5 9h3A1.5 1.5 0 017 10.5v3A1.5 1.5 0 015.5 15h-3A1.5 1.5 0 011 13.5v-3zm8 0A1.5 1.5 0 0110.5 9h3a1.5 1.5 0 011.5 1.5v3a1.5 1.5 0 01-1.5 1.5h-3A1.5 1.5 0 019 13.5v-3z" />
                </svg>
              ) : (
                /* List icon */
                <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 16 16">
                  <path d="M2 4a1 1 0 011-1h10a1 1 0 110 2H3a1 1 0 01-1-1zm0 4a1 1 0 011-1h10a1 1 0 110 2H3a1 1 0 01-1-1zm1 3a1 1 0 100 2h10a1 1 0 100-2H3z" />
                </svg>
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Scrollable Content */}
      <div className="flex-1 overflow-auto">
        {viewMode === 'cards' ? (
          /* ===== CARDS VIEW ===== */
          <div className="p-4 md:p-5">
            <div
              className={
                filteredProjects.length === 0
                  ? 'flex flex-wrap justify-center gap-4'
                  : 'grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4'
              }
            >
              {/* Create New Project Card */}
              <button
                onClick={() => setShowCreateDialog(true)}
                disabled={isCreating}
                className={`
                  group bg-white/[0.01] rounded-[var(--radius)] p-6
                  border-2 border-dashed border-[rgba(var(--primary-rgb),0.3)]
                  hover:border-[rgba(var(--primary-rgb),0.6)]
                  transition-all duration-300
                  flex flex-col items-center justify-center gap-3
                  ${filteredProjects.length === 0 ? 'w-full max-w-sm min-h-[280px]' : 'min-h-[240px]'}
                  ${isCreating ? 'opacity-50 cursor-not-allowed' : ''}
                `}
              >
                <div className="w-14 h-14 bg-[rgba(var(--primary-rgb),0.2)] rounded-[var(--radius)] flex items-center justify-center group-hover:bg-[rgba(var(--primary-rgb),0.3)] transition-colors">
                  <FilePlus className="w-7 h-7 text-[var(--primary)]" weight="fill" />
                </div>
                <div className="text-center">
                  <h3 className="text-sm font-semibold text-[var(--text)] mb-1.5">
                    Create New Project
                  </h3>
                  <p className="text-xs text-[var(--text-muted)]">
                    Start building something amazing
                  </p>
                </div>
              </button>

              {/* Import from Repository Card */}
              <button
                onClick={() => setShowImportDialog(true)}
                className={`
                  group bg-white/[0.01] rounded-[var(--radius)] p-6
                  border-2 border-dashed border-emerald-500/30
                  hover:border-emerald-500/60
                  transition-all duration-300
                  flex flex-col items-center justify-center gap-3
                  ${filteredProjects.length === 0 ? 'w-full max-w-sm min-h-[280px]' : 'min-h-[240px]'}
                `}
              >
                <div className="w-14 h-14 bg-emerald-500/20 rounded-[var(--radius)] flex items-center justify-center group-hover:bg-emerald-500/30 transition-colors">
                  <GitBranch className="w-7 h-7 text-emerald-500" weight="fill" />
                </div>
                <div className="text-center">
                  <h3 className="text-sm font-semibold text-[var(--text)] mb-1.5">
                    Import from Repository
                  </h3>
                  <p className="text-xs text-[var(--text-muted)]">
                    Connect a GitHub, GitLab, or Bitbucket repo
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
                    slug: project.slug,
                    compute_tier: project.compute_tier,
                    environment_status: project.environment_status,
                  }}
                  onOpen={() => {
                    if (project.environment_status === 'setup_failed') {
                      deleteProject(project.id);
                    } else {
                      navigate(`/project/${project.slug}`);
                    }
                  }}
                  onDelete={() => deleteProject(project.id)}
                  onStatusChange={(status) => updateProjectStatus(project.id, status)}
                  onFork={() => handleForkProject(project.id)}
                  onHibernate={
                    project.compute_tier === 'environment' &&
                    project.environment_status === 'active'
                      ? () => handleHibernateProject(project.slug)
                      : undefined
                  }
                  isDeleting={deletingProjectIds.has(project.id)}
                  isSelected={selectedProjectIds.has(project.id)}
                  onSelectionToggle={() => toggleProjectSelection(project.id)}
                />
              ))}
            </div>
          </div>
        ) : (
          /* ===== LIST VIEW ===== */
          <div className="w-full">
            {filteredProjects.length > 0 ? (
              <>
                {/* List Header */}
                <div className="h-8 flex items-center px-4 md:px-5 text-[var(--text-subtle)]">
                  <div className="w-8 flex-shrink-0" />
                  <div className="flex-1 min-w-0 text-xs font-medium">Name</div>
                  <div className="hidden md:block w-28 text-xs font-medium text-right">Status</div>
                  <div className="hidden lg:block w-32 text-xs font-medium text-right">Updated</div>
                  <div className="w-24 flex-shrink-0" />
                </div>

                {/* Project Rows */}
                {filteredProjects.map((project) => (
                  <div
                    key={project.id}
                    className={`group h-12 flex items-center px-4 md:px-5 transition-colors cursor-pointer ${
                      selectedProjectIds.has(project.id)
                        ? 'bg-[var(--surface)]'
                        : 'hover:bg-[var(--surface)]'
                    } ${deletingProjectIds.has(project.id) ? 'opacity-40 pointer-events-none' : ''} ${project.environment_status === 'setup_failed' ? 'border-l-2 border-red-500/50' : ''}`}
                    onClick={() => {
                      if (project.environment_status === 'setup_failed') {
                        deleteProject(project.id);
                      } else {
                        navigate(`/project/${project.slug}`);
                      }
                    }}
                  >
                    {/* Checkbox */}
                    <div className="w-8 flex-shrink-0 flex items-center">
                      <button
                        role="checkbox"
                        aria-checked={selectedProjectIds.has(project.id)}
                        onClick={(e) => {
                          e.stopPropagation();
                          toggleProjectSelection(project.id);
                        }}
                        className={`w-4 h-4 rounded border flex items-center justify-center transition-all ${
                          selectedProjectIds.has(project.id)
                            ? 'bg-[var(--primary)] border-[var(--primary)]'
                            : 'border-[var(--border-hover)] opacity-0 group-hover:opacity-100'
                        }`}
                      >
                        {selectedProjectIds.has(project.id) && (
                          <svg
                            className="w-2.5 h-2.5 text-white"
                            fill="none"
                            viewBox="0 0 24 24"
                            stroke="currentColor"
                            strokeWidth={3}
                          >
                            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                          </svg>
                        )}
                      </button>
                    </div>

                    {/* Project icon + name + description */}
                    <div className="flex-1 min-w-0 flex items-center gap-3">
                      <svg
                        className="w-4 h-4 text-[var(--text-subtle)] flex-shrink-0"
                        fill="currentColor"
                        viewBox="0 0 256 256"
                      >
                        <path d="M216,64H176V56a24,24,0,0,0-24-24H104A24,24,0,0,0,80,56v8H40A16,16,0,0,0,24,80V200a16,16,0,0,0,16,16H216a16,16,0,0,0,16-16V80A16,16,0,0,0,216,64ZM96,56a8,8,0,0,1,8-8h48a8,8,0,0,1,8,8v8H96Z" />
                      </svg>
                      <span className="text-xs font-medium text-[var(--text)] truncate">
                        {project.name}
                      </span>
                      {project.description && (
                        <span className="hidden xl:inline text-xs text-[var(--text-subtle)] truncate max-w-[200px]">
                          {project.description}
                        </span>
                      )}
                      {project.environment_status === 'provisioning' ? (
                        <span className="text-[10px] text-blue-400 flex-shrink-0">
                          Setting up...
                        </span>
                      ) : project.environment_status === 'setup_failed' ? (
                        <span className="text-[10px] text-red-400 flex-shrink-0">Setup failed</span>
                      ) : project.environment_status && project.environment_status !== 'active' ? (
                        <span className="text-[10px] text-[var(--text-subtle)] flex-shrink-0">
                          {project.environment_status}
                        </span>
                      ) : null}
                    </div>

                    {/* Status */}
                    <div className="hidden md:flex w-28 justify-end">
                      <span
                        className={`text-[10px] font-medium px-2 py-0.5 rounded-full border ${
                          project.status === 'launch'
                            ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                            : project.status === 'build'
                              ? 'bg-yellow-500/10 text-yellow-400 border-yellow-500/20'
                              : 'bg-purple-500/10 text-purple-400 border-purple-500/20'
                        }`}
                      >
                        {(project.status || 'build').charAt(0).toUpperCase() +
                          (project.status || 'build').slice(1)}
                      </span>
                    </div>

                    {/* Updated */}
                    <div className="hidden lg:block w-32 text-right">
                      <span className="text-xs text-[var(--text-subtle)]">
                        {formatDate(project.updated_at)}
                      </span>
                    </div>

                    {/* Row Actions */}
                    <div className="w-24 flex-shrink-0 flex items-center justify-end gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleForkProject(project.id);
                        }}
                        className="btn btn-icon btn-sm"
                        title="Fork"
                      >
                        <GitBranch className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          deleteProject(project.id);
                        }}
                        className="btn btn-icon btn-sm btn-danger"
                        title="Delete"
                      >
                        <Trash className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                ))}
              </>
            ) : (
              <div className="text-center py-16 flex flex-col items-center gap-4">
                <p className="text-[var(--text-muted)] text-xs">No projects yet</p>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setShowCreateDialog(true)}
                    disabled={isCreating}
                    className="btn"
                  >
                    <FilePlus className="w-4 h-4" />
                    Create project
                  </button>
                  <button onClick={() => setShowImportDialog(true)} className="btn">
                    <GitBranch className="w-4 h-4" />
                    Import repo
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Floating Action Bar — Linear-style: "N selected" + clear + divider + actions */}
      {selectedProjectIds.size > 0 && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 animate-in slide-in-from-bottom-4 fade-in duration-200 flex items-center gap-[2px]">
          <button className="btn" style={{ fontVariantNumeric: 'tabular-nums' }} tabIndex={-1}>
            <span>{selectedProjectIds.size}</span>&nbsp;selected
          </button>

          <button
            onClick={clearSelection}
            className="btn btn-icon"
            aria-label="Clear selected"
            tabIndex={-1}
          >
            <X className="w-4 h-4" />
          </button>

          <button
            onClick={() => setShowBulkDeleteDialog(true)}
            className="btn btn-danger"
            tabIndex={-1}
          >
            <Trash className="w-4 h-4" />
            Delete
          </button>
        </div>
      )}

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

      {/* Bulk Delete Confirmation Dialog */}
      <ConfirmDialog
        isOpen={showBulkDeleteDialog}
        onClose={() => setShowBulkDeleteDialog(false)}
        onConfirm={confirmBulkDelete}
        title={`Delete ${selectedProjectIds.size} Project${selectedProjectIds.size > 1 ? 's' : ''}`}
        message={
          <div>
            <p className="mb-3">
              Are you sure you want to delete{' '}
              {selectedProjectIds.size === 1
                ? 'this project'
                : `these ${selectedProjectIds.size} projects`}
              ? This action cannot be undone.
            </p>
            <div className="max-h-40 overflow-y-auto space-y-1 bg-white/5 rounded-xl p-3 border border-white/10">
              {projects
                .filter((p) => selectedProjectIds.has(p.id))
                .map((p) => (
                  <div key={p.id} className="text-sm text-gray-300 truncate">
                    {p.name}
                  </div>
                ))}
            </div>
          </div>
        }
        confirmText={`Delete ${selectedProjectIds.size} Project${selectedProjectIds.size > 1 ? 's' : ''}`}
        cancelText="Cancel"
        variant="danger"
      />

      {/* Create Project Modal */}
      <CreateProjectModal
        isOpen={showCreateDialog}
        onClose={() => {
          setShowCreateDialog(false);
          setCreateBaseId(undefined);
          setCreateBaseVersion(undefined);
        }}
        onConfirm={handleCreateProject}
        isLoading={isCreating}
        initialBaseId={createBaseId}
        baseVersion={createBaseVersion}
      />

      {/* Import from Repository Modal */}
      <RepoImportModal
        isOpen={showImportDialog}
        onClose={() => {
          setShowImportDialog(false);
          setImportRepoUrl(undefined);
        }}
        initialRepoUrl={importRepoUrl}
        onCreateProject={async (provider, repoUrl, branch, projectName) => {
          setIsCreating(true);
          const creatingToast = toast.loading(`Importing from ${provider}...`);

          try {
            const response = await projectsApi.create(
              projectName,
              '',
              provider, // 'github', 'gitlab', or 'bitbucket'
              repoUrl,
              branch,
              undefined
            );

            const project = response.project;
            const taskId = response.task_id;

            // Poll for task completion to get container_id (same pattern as base imports)
            if (taskId) {
              toast.loading('Setting up project...', { id: creatingToast });
              try {
                await tasksApi.pollUntilComplete(taskId);
                toast.success('Project imported successfully!', {
                  id: creatingToast,
                  duration: 2000,
                });
                setShowImportDialog(false);
                setIsCreating(false);

                // Navigate to setup page for user to review config
                navigate(`/project/${project.slug}/setup`);
              } catch (taskError) {
                console.error('Project import task failed:', taskError);
                const taskErrMsg =
                  taskError instanceof Error ? taskError.message : 'Import setup failed';
                toast.error(taskErrMsg, { id: creatingToast });
                setIsCreating(false);
                navigate(`/project/${project.slug}`);
              }
            } else {
              toast.success('Project imported successfully!', {
                id: creatingToast,
                duration: 2000,
              });
              setShowImportDialog(false);
              setIsCreating(false);
              navigate(`/project/${project.slug}/setup`);
            }
          } catch (error: unknown) {
            const err = error as { response?: { data?: { detail?: string } } };
            const detail = err?.response?.data?.detail;
            const errorMessage = typeof detail === 'string' ? detail : 'Failed to import project';
            toast.error(errorMessage, { id: creatingToast });
            throw error; // Re-throw so the modal knows it failed
          } finally {
            setIsCreating(false);
          }
        }}
      />
    </>
  );
}
