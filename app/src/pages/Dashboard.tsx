import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { projectsApi } from '../lib/api';
import { useTheme } from '../theme/ThemeContext';
import {
  FloatingSidebar,
  ProjectCard,
  MarketplaceCard
} from '../components/ui';
import type { Status } from '../components/ui';
import toast from 'react-hot-toast';
import {
  Atom,
  Database,
  ShieldCheck,
  Sparkle,
  Lightning,
  Folder,
  Storefront,
  Package,
  Gear,
  Sun,
  Moon,
  Question,
  FilePlus,
  FolderOpen
} from '@phosphor-icons/react';

interface Project {
  id: number;
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

  const createProject = async () => {
    if (!newProject.name.trim()) {
      toast.error('Project name is required');
      return;
    }

    setIsCreating(true);
    const creatingToast = toast.loading('Creating your project...');

    try {
      const project = await projectsApi.create(newProject.name, newProject.description);
      toast.success('Project created successfully!', { id: creatingToast });
      setShowCreateModal(false);
      setNewProject({ name: '', description: '' });
      setTimeout(() => {
        navigate(`/project/${project.id}`);
      }, 500);
    } catch (error) {
      toast.error('Failed to create project', { id: creatingToast });
    } finally {
      setIsCreating(false);
    }
  };

  const deleteProject = async (id: number) => {
    const project = projects.find(p => p.id === id);
    if (!confirm(`Delete "${project?.name}"? This cannot be undone.`)) return;

    try {
      await projectsApi.delete(id);
      toast.success('Project deleted');
      loadProjects();
    } catch (error) {
      toast.error('Failed to delete project');
    }
  };

  const updateProjectStatus = async (id: number, status: Status) => {
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
    const date = new Date(dateString);
    const now = new Date();
    const diffInMinutes = (now.getTime() - date.getTime()) / (1000 * 60);

    if (diffInMinutes < 60) return `${Math.floor(diffInMinutes)}m ago`;
    if (diffInMinutes < 1440) return `${Math.floor(diffInMinutes / 60)}h ago`;
    if (diffInMinutes < 10080) return `${Math.floor(diffInMinutes / 1440)}d ago`;
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  };

  // Sidebar items
  const leftSidebarItems = [
    {
      icon: <Folder className="w-5 h-5" weight="fill" />,
      title: 'Projects',
      onClick: () => {},
      active: true
    },
    {
      icon: <Storefront className="w-5 h-5" weight="fill" />,
      title: 'Marketplace',
      onClick: () => toast('Marketplace coming soon!')
    },
    {
      icon: <Package className="w-5 h-5" weight="fill" />,
      title: 'Components',
      onClick: () => toast('Components library coming soon!')
    },
    {
      icon: <Gear className="w-5 h-5" weight="fill" />,
      title: 'Settings',
      onClick: () => toast('Settings coming soon!')
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
        <div className="text-center space-y-4">
          <div className="w-16 h-16 bg-[rgba(255,107,0,0.2)] backdrop-blur-sm rounded-2xl flex items-center justify-center mx-auto animate-pulse">
            <Folder className="w-8 h-8 text-[var(--primary)]" weight="fill" />
          </div>
          <p className="text-[var(--text)] font-medium">Loading projects...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen px-20 sm:px-32 py-20 sm:py-24 relative">
      {/* Floating Sidebars */}
      <FloatingSidebar position="left" items={leftSidebarItems} />
      <FloatingSidebar position="right" items={rightSidebarItems} />

      {/* Header */}
      <div className="mb-10">
        <div className="flex items-center justify-between mb-4">
          <h1 className="font-heading text-4xl font-bold text-[var(--text)]">My Projects</h1>

          {/* Credits Display */}
          <div className="flex items-center gap-3 px-6 py-3 bg-gradient-to-r from-[rgba(0,217,255,0.1)] to-[rgba(0,217,255,0.05)] border border-[rgba(0,217,255,0.2)] rounded-2xl">
            <Lightning className="w-5 h-5 text-[var(--accent)]" weight="fill" />
            <span className="text-[var(--accent)] font-semibold">247 credits left</span>
            <button
              onClick={() => toast('Upgrade to PRO!')}
              className="text-xs bg-[rgba(0,217,255,0.2)] hover:bg-[rgba(0,217,255,0.3)] px-3 py-1 rounded-full transition-colors"
            >
              Get More
            </button>
          </div>
        </div>

        {/* Tab Navigation */}
        <div className="flex items-center gap-4">
          {[
            { key: 'all', label: 'All Projects' },
            { key: 'idea', label: 'Idea' },
            { key: 'build', label: 'Build' },
            { key: 'launch', label: 'Launch' }
          ].map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key as TabFilter)}
              className={`
                font-heading text-xl pb-2 border-b-2 transition-all
                ${activeTab === tab.key
                  ? 'text-[var(--primary)] border-[var(--primary)]'
                  : 'text-gray-400 border-transparent hover:text-[var(--text)]'
                }
              `}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* Marketplace Section */}
      <div className="bg-white/[0.02] dark:bg-white/[0.02] border border-white/[0.08] rounded-2xl p-5 mb-8">
        <div className="flex items-center justify-between mb-6">
          <h2 className="font-heading text-xl font-bold text-[var(--text)] flex items-center gap-2">
            <Sparkle className="w-5 h-5 text-orange-400" weight="fill" />
            Recommended for Your Projects
          </h2>
          <button
            onClick={() => toast('Browse marketplace')}
            className="text-sm text-[var(--primary)] hover:text-orange-400 transition-colors"
          >
            Browse Marketplace →
          </button>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <MarketplaceCard
            title="React Expert"
            description="Advanced React assistant"
            icon={
              <div className="w-10 h-10 bg-blue-500/20 rounded-lg flex items-center justify-center">
                <Atom className="w-5 h-5 text-blue-400" weight="fill" />
              </div>
            }
            badge="Free"
          />
          <MarketplaceCard
            title="Database Pro"
            description="SQL optimization & design"
            icon={
              <div className="w-10 h-10 bg-purple-500/20 rounded-lg flex items-center justify-center">
                <Database className="w-5 h-5 text-purple-400" weight="fill" />
              </div>
            }
            badge="Free"
          />
          <MarketplaceCard
            title="Security Scanner"
            description="Code vulnerability detection"
            icon={
              <div className="w-10 h-10 bg-green-500/20 rounded-lg flex items-center justify-center">
                <ShieldCheck className="w-5 h-5 text-green-400" weight="fill" />
              </div>
            }
            badge="PRO"
          />
        </div>
      </div>

      {/* Projects Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {/* Create New Project Card */}
        <button
          onClick={() => setShowCreateModal(true)}
          className="
            group bg-[var(--surface)] rounded-2xl p-8
            border-2 border-dashed border-[rgba(255,107,0,0.3)]
            hover:border-[rgba(255,107,0,0.6)]
            transition-all duration-300
            hover:transform hover:-translate-y-1
            flex flex-col items-center justify-center gap-4
            min-h-[280px]
          "
        >
          <div className="w-16 h-16 bg-[rgba(255,107,0,0.2)] rounded-2xl flex items-center justify-center group-hover:bg-[rgba(255,107,0,0.3)] transition-colors">
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
              isLive: project.status === 'launch'
            }}
            onOpen={() => navigate(`/project/${project.id}`)}
            onDelete={() => deleteProject(project.id)}
            onStatusChange={(status) => updateProjectStatus(project.id, status)}
          />
        ))}
      </div>

      {/* Empty State */}
      {filteredProjects.length === 0 && (
        <div className="text-center py-16">
          <div className="w-20 h-20 bg-white/5 rounded-2xl flex items-center justify-center mx-auto mb-4">
            <FolderOpen className="w-10 h-10 text-gray-500" weight="fill" />
          </div>
          <h3 className="text-lg font-semibold text-[var(--text)] mb-2">
            {activeTab === 'all' ? 'No projects yet' : `No ${activeTab} projects`}
          </h3>
          <p className="text-gray-500 mb-6">
            {activeTab === 'all'
              ? 'Create your first project to get started'
              : `No projects in ${activeTab} phase`
            }
          </p>
          <button
            onClick={() => setShowCreateModal(true)}
            className="px-6 py-3 bg-[var(--primary)] hover:bg-orange-600 text-white rounded-xl font-semibold transition-all"
          >
            Create Project
          </button>
        </div>
      )}

      {/* Create Project Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50" onClick={() => !isCreating && setShowCreateModal(false)}>
          <div className="bg-[var(--surface)] p-8 rounded-3xl w-full max-w-md shadow-2xl border border-white/10" onClick={(e) => e.stopPropagation()}>
            <div className="text-center mb-6">
              <div className="w-16 h-16 bg-[rgba(255,107,0,0.2)] rounded-2xl flex items-center justify-center mx-auto mb-4">
                <FilePlus className="w-8 h-8 text-[var(--primary)]" weight="fill" />
              </div>
              <h2 className="font-heading text-2xl font-bold text-[var(--text)] mb-2">Create New Project</h2>
              <p className="text-gray-500">Build something incredible with AI</p>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-[var(--text)] mb-2">Project Name</label>
                <input
                  type="text"
                  value={newProject.name}
                  onChange={(e) => setNewProject({ ...newProject, name: e.target.value })}
                  className="w-full bg-white/5 border border-white/10 text-[var(--text)] px-4 py-3 rounded-xl focus:outline-none focus:ring-2 focus:ring-[var(--primary)] placeholder-gray-500"
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
                  className="w-full bg-white/5 border border-white/10 text-[var(--text)] px-4 py-3 rounded-xl focus:outline-none focus:ring-2 focus:ring-[var(--primary)] placeholder-gray-500 resize-none"
                  rows={3}
                  placeholder="Describe your project..."
                  disabled={isCreating}
                />
              </div>

              <div className="flex gap-3 pt-4">
                <button
                  onClick={createProject}
                  disabled={isCreating || !newProject.name.trim()}
                  className="flex-1 bg-[var(--primary)] hover:bg-orange-600 disabled:bg-gray-600 disabled:cursor-not-allowed text-white py-3 rounded-xl font-semibold transition-all"
                >
                  {isCreating ? 'Creating...' : 'Create Project'}
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
    </div>
  );
}
