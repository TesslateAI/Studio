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
      icon: <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 256 256"><path d="M216,72H131.31L104,44.69A15.86,15.86,0,0,0,92.69,40H40A16,16,0,0,0,24,56V200.62A15.4,15.4,0,0,0,39.38,216H216.89A15.13,15.13,0,0,0,232,200.89V88A16,16,0,0,0,216,72ZM40,56H92.69l16,16H40ZM216,200H40V88H216Z"/></svg>,
      title: 'Projects',
      onClick: () => {},
      active: true
    },
    {
      icon: <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 256 256"><path d="M216,64H176a48,48,0,0,0-96,0H40A16,16,0,0,0,24,80V200a16,16,0,0,0,16,16H216a16,16,0,0,0,16-16V80A16,16,0,0,0,216,64ZM128,32a32,32,0,0,1,32,32H96A32,32,0,0,1,128,32Zm88,168H40V80H216V200Z"/></svg>,
      title: 'Marketplace',
      onClick: () => toast('Marketplace coming soon!')
    },
    {
      icon: <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 256 256"><path d="M224,177.32l-47.06-21.93a8,8,0,0,0-7.12.12c-17.74,10.44-35.78,10.44-47.56,0a8,8,0,0,0-7.12-.12L68.08,177.32A8,8,0,0,0,64,184.34V208a16,16,0,0,0,16,16H176a16,16,0,0,0,16-16V184.34A8,8,0,0,0,224,177.32Z"/><path d="M240,80H16a8,8,0,0,0-8,8v72a8,8,0,0,0,8,8h8V128a16,16,0,0,1,16-16h96v24a8,8,0,0,0,16,0V112h96a16,16,0,0,1,16,16v40h8a8,8,0,0,0,8-8V88A8,8,0,0,0,240,80Z"/></svg>,
      title: 'Components',
      onClick: () => toast('Components library coming soon!')
    },
    {
      icon: <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 256 256"><path d="M128,80a48,48,0,1,0,48,48A48.05,48.05,0,0,0,128,80Zm0,80a32,32,0,1,1,32-32A32,32,0,0,1,128,160Zm88-29.84q.06-2.16,0-4.32l14.92-18.64a8,8,0,0,0,1.48-7.06,107.21,107.21,0,0,0-10.88-26.25,8,8,0,0,0-6-3.93l-23.72-2.64q-1.48-1.56-3-3L186,40.54a8,8,0,0,0-3.94-6,107.71,107.71,0,0,0-26.25-10.87,8,8,0,0,0-7.06,1.49L130.16,40Q128,40,125.84,40L107.2,25.11a8,8,0,0,0-7.06-1.48A107.6,107.6,0,0,0,73.89,34.51a8,8,0,0,0-3.93,6L67.32,64.27q-1.56,1.49-3,3L40.54,70a8,8,0,0,0-6,3.94,107.71,107.71,0,0,0-10.87,26.25,8,8,0,0,0,1.49,7.06L40,125.84Q40,128,40,130.16L25.11,148.8a8,8,0,0,0-1.48,7.06,107.21,107.21,0,0,0,10.88,26.25,8,8,0,0,0,6,3.93l23.72,2.64q1.48,1.56,3,3L70,215.46a8,8,0,0,0,3.94,6,107.71,107.71,0,0,0,26.25,10.87,8,8,0,0,0,7.06-1.49L125.84,216q2.16.06,4.32,0l18.64,14.92a8,8,0,0,0,7.06,1.48,107.21,107.21,0,0,0,26.25-10.88,8,8,0,0,0,3.93-6l2.64-23.72q1.56-1.48,3-3L215.46,186a8,8,0,0,0,6-3.94,107.71,107.71,0,0,0,10.87-26.25,8,8,0,0,0-1.49-7.06Zm-16.1-6.5a73.93,73.93,0,0,1,0,8.68,8,8,0,0,0,1.74,5.48l14.19,17.73a91.57,91.57,0,0,1-6.23,15L187,173.11a8,8,0,0,0-5.1,2.64,74.11,74.11,0,0,1-6.14,6.14,8,8,0,0,0-2.64,5.1l-2.51,22.58a91.32,91.32,0,0,1-15,6.23l-17.74-14.19a8,8,0,0,0-5-1.75h-.48a73.93,73.93,0,0,1-8.68,0,8,8,0,0,0-5.48,1.74L100.45,215.8a91.57,91.57,0,0,1-15-6.23L82.89,187a8,8,0,0,0-2.64-5.1,74.11,74.11,0,0,1-6.14-6.14,8,8,0,0,0-5.1-2.64L46.43,170.6a91.32,91.32,0,0,1-6.23-15l14.19-17.74a8,8,0,0,0,1.74-5.48,73.93,73.93,0,0,1,0-8.68,8,8,0,0,0-1.74-5.48L40.2,100.45a91.57,91.57,0,0,1,6.23-15L69,82.89a8,8,0,0,0,5.1-2.64,74.11,74.11,0,0,1,6.14-6.14A8,8,0,0,0,82.89,69L85.4,46.43a91.32,91.32,0,0,1,15-6.23l17.74,14.19a8,8,0,0,0,5.48,1.74,73.93,73.93,0,0,1,8.68,0,8,8,0,0,0,5.48-1.74L155.55,40.2a91.57,91.57,0,0,1,15,6.23L173.11,69a8,8,0,0,0,2.64,5.1,74.11,74.11,0,0,1,6.14,6.14,8,8,0,0,0,5.1,2.64l22.58,2.51a91.32,91.32,0,0,1,6.23,15l-14.19,17.74A8,8,0,0,0,199.87,123.66Z"/></svg>,
      title: 'Settings',
      onClick: () => toast('Settings coming soon!')
    }
  ];

  const rightSidebarItems = [
    {
      icon: theme === 'dark'
        ? <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 256 256"><path d="M233.54,142.23a8,8,0,0,0-8-2,88.08,88.08,0,0,1-109.8-109.8,8,8,0,0,0-10-10,104.84,104.84,0,0,0-52.91,37A104,104,0,0,0,136,224a103.09,103.09,0,0,0,62.52-20.88,104.84,104.84,0,0,0,37-52.91A8,8,0,0,0,233.54,142.23ZM188.9,190.34A88,88,0,0,1,65.66,67.11a89,89,0,0,1,31.4-26A106,106,0,0,0,96,56,104.11,104.11,0,0,0,200,160a106,106,0,0,0,14.92-1.06A89,89,0,0,1,188.9,190.34Z"/></svg>
        : <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 256 256"><path d="M120,40V16a8,8,0,0,1,16,0V40a8,8,0,0,1-16,0Zm72,88a64,64,0,1,1-64-64A64.07,64.07,0,0,1,192,128Zm-16,0a48,48,0,1,0-48,48A48.05,48.05,0,0,0,176,128ZM58.34,69.66A8,8,0,0,0,69.66,58.34l-16-16A8,8,0,0,0,42.34,53.66Zm0,116.68-16,16a8,8,0,0,0,11.32,11.32l16-16a8,8,0,0,0-11.32-11.32ZM192,72a8,8,0,0,0,5.66-2.34l16-16a8,8,0,0,0-11.32-11.32l-16,16A8,8,0,0,0,192,72Zm5.66,114.34a8,8,0,0,0-11.32,11.32l16,16a8,8,0,0,0,11.32-11.32ZM48,128a8,8,0,0,0-8-8H16a8,8,0,0,0,0,16H40A8,8,0,0,0,48,128Zm80,80a8,8,0,0,0-8,8v24a8,8,0,0,0,16,0V216A8,8,0,0,0,128,208Zm112-88H216a8,8,0,0,0,0,16h24a8,8,0,0,0,0-16Z"/></svg>,
      title: theme === 'dark' ? 'Light Mode' : 'Dark Mode',
      onClick: toggleTheme
    },
    {
      icon: <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 256 256"><path d="M232,128a104.5,104.5,0,0,1-4.56,30.56,8,8,0,0,1-2,3.31l-24.94,24.94A104,104,0,1,1,69.13,55.44L94.07,30.5a8,8,0,0,1,3.31-2A104.5,104.5,0,0,1,128,24,104.11,104.11,0,0,1,232,128Zm-16.35-8H184a71.84,71.84,0,0,0-16.4-45.6l22.75-22.75A87.72,87.72,0,0,1,215.65,120Zm-135.3,0H48a87.72,87.72,0,0,1,25.3-68.35L96.4,74.84A71.84,71.84,0,0,0,80.35,120Zm16,16a71.84,71.84,0,0,0,16.4,45.6L89.65,204.35A87.72,87.72,0,0,1,64.35,136Zm39.6,76.58,31.5-31.5a72.1,72.1,0,0,0,64.08,0l31.5,31.5A87.74,87.74,0,0,1,136,215.65Zm0-175.16a87.74,87.74,0,0,1,63.42,25.23l-31.5,31.5a72.1,72.1,0,0,0-64.08,0L104,52.42A88.2,88.2,0,0,1,136,40.42Zm0,71.58a24,24,0,1,1-24,24A24,24,0,0,1,136,112Z"/></svg>,
      title: 'Help',
      onClick: () => toast('Help & support coming soon!')
    }
  ];

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center space-y-4">
          <div className="w-16 h-16 bg-[rgba(255,107,0,0.2)] backdrop-blur-sm rounded-2xl flex items-center justify-center mx-auto animate-pulse">
            <svg className="w-8 h-8 text-[var(--primary)]" fill="currentColor" viewBox="0 0 256 256">
              <path d="M213.66,82.34l-56-56A8,8,0,0,0,152,24H56A16,16,0,0,0,40,40V216a16,16,0,0,0,16,16H200a16,16,0,0,0,16-16V88A8,8,0,0,0,213.66,82.34ZM160,51.31,188.69,80H160ZM200,216H56V40h88V88a8,8,0,0,0,8,8h48V216Z"/>
            </svg>
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
            <svg className="w-5 h-5 text-[var(--accent)]" fill="currentColor" viewBox="0 0 256 256">
              <path d="M215.79,118.17a8,8,0,0,0-5-5.66L153.18,90.9l14.66-73.33a8,8,0,0,0-13.69-7l-112,120a8,8,0,0,0,3,13l57.63,21.61-14.62,73.25a8,8,0,0,0,13.69,7l112-120A8,8,0,0,0,215.79,118.17ZM109.37,214l10.47-52.38a8,8,0,0,0-5-9.06L62,132.71l84.62-90.66L136.16,94.43a8,8,0,0,0,5,9.06l52.8,19.8Z"/>
            </svg>
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
            <svg className="w-5 h-5 text-orange-400" fill="currentColor" viewBox="0 0 256 256">
              <path d="M240,128a16,16,0,0,1-6.65,12.94L208,160l10.65,19.06A16,16,0,0,1,204.94,198l-19.06-10.65L166.82,212A16,16,0,0,1,149.19,214l-10-20.24-10,20.24A16,16,0,0,1,111.56,218a15.93,15.93,0,0,1-7.38-4L85.12,187.35,66.06,198a16,16,0,0,1-13.71-18.94L62,160,36.65,140.94A16,16,0,0,1,30,128a16,16,0,0,1,6.65-12.94L62,96,52.35,76.94A16,16,0,0,1,66.06,58l19.06,10.65L104.18,44a16,16,0,0,1,17.63-2,15.93,15.93,0,0,1,7.38,4l10,20.24,10-20.24a16,16,0,0,1,17.63-2,15.93,15.93,0,0,1,7.38,4l19.06,24.65L212.94,62a16,16,0,0,1,13.71,18.94L218,100l25.35,19.06A16,16,0,0,1,240,128Z"/>
            </svg>
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
                <svg className="w-5 h-5 text-blue-400" fill="currentColor" viewBox="0 0 256 256">
                  <path d="M128,80a48,48,0,1,0,48,48A48.05,48.05,0,0,0,128,80Zm0,80a32,32,0,1,1,32-32A32,32,0,0,1,128,160ZM231.77,154.8c-1.59-2.5-3.89-6.11-6.93-10.86-6.38-10-16-24.84-29.17-44.26s-26.42-37.34-38.55-53.28c-5.76-7.58-10.92-14.34-15.48-20.25a146,146,0,0,0-83.26,0C53.84,31.91,48.67,38.66,42.92,46.24,30.79,62.18,20.51,80.76,13.33,99.68S1.59,135.8,0,149.2a146,146,0,0,0,83.26,0c4.56-5.91,9.72-12.67,15.48-20.25,12.13-15.94,22.41-34.52,29.59-53.44s11.74-33.88,13.33-47.28a146,146,0,0,0,0,83.26c-1.59,13.4-6.15,25.36-13.33,44.28s-17.46,37.34-29.59,53.28c-5.76,7.58-10.92,14.34-15.48,20.25a146,146,0,0,0,83.26,0c4.56-5.91,9.72-12.67,15.48-20.25,12.13-15.94,22.41-34.52,29.59-53.44s11.74-33.88,13.33-47.28a146,146,0,0,0,0-83.26c-1.59,13.4-6.15,25.36-13.33,44.28s-17.46,37.34-29.59,53.28c-5.76,7.58-10.92,14.34-15.48,20.25Z"/>
                </svg>
              </div>
            }
            badge="Free"
          />
          <MarketplaceCard
            title="Database Pro"
            description="SQL optimization & design"
            icon={
              <div className="w-10 h-10 bg-purple-500/20 rounded-lg flex items-center justify-center">
                <svg className="w-5 h-5 text-purple-400" fill="currentColor" viewBox="0 0 256 256">
                  <path d="M128,24C74.17,24,32,48.6,32,80v96c0,31.4,42.17,56,96,56s96-24.6,96-56V80C224,48.6,181.83,24,128,24Zm80,104c0,9.62-7.88,19.43-21.61,26.92C170.93,163.35,150.19,168,128,168s-42.93-4.65-58.39-13.08C55.88,147.43,48,137.62,48,128V111.36c17.06,15,46.23,24.64,80,24.64s62.94-9.68,80-24.64ZM69.61,53.08C85.07,44.65,105.81,40,128,40s42.93,4.65,58.39,13.08C200.12,60.57,208,70.38,208,80s-7.88,19.43-21.61,26.92C170.93,115.35,150.19,120,128,120s-42.93-4.65-58.39-13.08C55.88,99.43,48,89.62,48,80S55.88,60.57,69.61,53.08ZM186.39,202.92C170.93,211.35,150.19,216,128,216s-42.93-4.65-58.39-13.08C55.88,195.43,48,185.62,48,176V159.36c17.06,15,46.23,24.64,80,24.64s62.94-9.68,80-24.64V176C208,185.62,200.12,195.43,186.39,202.92Z"/>
                </svg>
              </div>
            }
            badge="Free"
          />
          <MarketplaceCard
            title="Security Scanner"
            description="Code vulnerability detection"
            icon={
              <div className="w-10 h-10 bg-green-500/20 rounded-lg flex items-center justify-center">
                <svg className="w-5 h-5 text-green-400" fill="currentColor" viewBox="0 0 256 256">
                  <path d="M208,40H48A16,16,0,0,0,32,56v58.78c0,89.61,75.82,119.34,91,124.39a15.53,15.53,0,0,0,10,0c15.2-5.05,91-34.78,91-124.39V56A16,16,0,0,0,208,40Zm0,74.79c0,78.42-66.35,104.62-80,109.91-13.53-5.19-80-31.09-80-109.91V56H208Z"/>
                </svg>
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
            <svg className="w-8 h-8 text-[var(--primary)]" fill="currentColor" viewBox="0 0 256 256">
              <path d="M224,128a8,8,0,0,1-8,8H136v80a8,8,0,0,1-16,0V136H40a8,8,0,0,1,0-16h80V40a8,8,0,0,1,16,0v80h80A8,8,0,0,1,224,128Z"/>
            </svg>
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
            <svg className="w-10 h-10 text-gray-500" fill="currentColor" viewBox="0 0 256 256">
              <path d="M216,72H131.31L104,44.69A15.86,15.86,0,0,0,92.69,40H40A16,16,0,0,0,24,56V200.62A15.4,15.4,0,0,0,39.38,216H216.89A15.13,15.13,0,0,0,232,200.89V88A16,16,0,0,0,216,72ZM40,56H92.69l16,16H40ZM216,200H40V88H216Z"/>
            </svg>
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
                <svg className="w-8 h-8 text-[var(--primary)]" fill="currentColor" viewBox="0 0 256 256">
                  <path d="M224,128a8,8,0,0,1-8,8H136v80a8,8,0,0,1-16,0V136H40a8,8,0,0,1,0-16h80V40a8,8,0,0,1,16,0v80h80A8,8,0,0,1,224,128Z"/>
                </svg>
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
