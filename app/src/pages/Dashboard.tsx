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
      <header className="mb-12 text-center">
        <div className="flex items-center justify-center gap-4 mb-4">
          <div className="w-12 h-12 bg-gradient-to-br from-[var(--primary)] to-orange-600 rounded-2xl flex items-center justify-center shadow-lg">
            <svg className="w-6 h-6 text-white" fill="currentColor" viewBox="0 0 256 256">
              <path d="M213.66,82.34l-56-56A8,8,0,0,0,152,24H56A16,16,0,0,0,40,40V216a16,16,0,0,0,16,16H200a16,16,0,0,0,16-16V88A8,8,0,0,0,213.66,82.34ZM160,51.31,188.69,80H160ZM200,216H56V40h88V88a8,8,0,0,0,8,8h48V216Z"/>
            </svg>
          </div>
          <h1 className="font-heading text-4xl font-bold text-[var(--text)]">Tesslate Studio</h1>
        </div>

        {/* Credits Display */}
        <div className="inline-flex items-center gap-3 px-6 py-3 bg-gradient-to-r from-[rgba(0,217,255,0.1)] to-[rgba(0,217,255,0.05)] border border-[rgba(0,217,255,0.2)] rounded-2xl">
          <svg className="w-5 h-5 text-[var(--accent)]" fill="currentColor" viewBox="0 0 256 256">
            <path d="M215.79,118.17a8,8,0,0,0-5-5.66L153.18,90.9l14.66-73.33a8,8,0,0,0-13.69-7l-112,120a8,8,0,0,0,3,13l57.63,21.61-14.62,73.25a8,8,0,0,0,13.69,7l112-120A8,8,0,0,0,215.79,118.17ZM109.37,214l10.47-52.38a8,8,0,0,0-5-9.06L62,132.71l84.62-90.66L136.16,94.43a8,8,0,0,0,5,9.06l52.8,19.8Z"/>
          </svg>
          <span className="text-[var(--accent)] font-semibold">150 credits left</span>
          <button
            onClick={() => toast('Upgrade to PRO!')}
            className="px-4 py-1.5 bg-[var(--accent)] text-black rounded-lg text-sm font-semibold hover:opacity-90 transition-all"
          >
            Get More
          </button>
        </div>
      </header>

      {/* Tab Navigation */}
      <div className="flex justify-center gap-2 mb-12">
        {[
          { key: 'all', label: 'All Projects', icon: <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 256 256"><path d="M224,177.32l-47.06-21.93a8,8,0,0,0-7.12.12c-17.74,10.44-35.78,10.44-47.56,0a8,8,0,0,0-7.12-.12L68.08,177.32A8,8,0,0,0,64,184.34V208a16,16,0,0,0,16,16H176a16,16,0,0,0,16-16V184.34A8,8,0,0,0,224,177.32Z"/></svg> },
          { key: 'idea', label: 'Idea', icon: <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 256 256"><path d="M176,232a8,8,0,0,1-8,8H88a8,8,0,0,1,0-16h80A8,8,0,0,1,176,232Zm40-128a87.55,87.55,0,0,1-33.64,69.21A16.24,16.24,0,0,0,176,186v6a16,16,0,0,1-16,16H96a16,16,0,0,1-16-16v-6a16,16,0,0,0-6.23-12.66A87.59,87.59,0,0,1,40,104.49C39.74,56.83,78.26,17.14,125.88,16A88,88,0,0,1,216,104Z"/></svg> },
          { key: 'build', label: 'Build', icon: <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 256 256"><path d="M192,104a8,8,0,0,1-8,8H72a8,8,0,0,1,0-16H184A8,8,0,0,1,192,104Zm-8,24H72a8,8,0,0,0,0,16H184a8,8,0,0,0,0-16Zm40-80V208a16,16,0,0,1-16,16H48a16,16,0,0,1-16-16V48A16,16,0,0,1,48,32H208A16,16,0,0,1,224,48ZM208,208V48H48V208H208Z"/></svg> },
          { key: 'launch', label: 'Launch', icon: <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 256 256"><path d="M152,224a8,8,0,0,1-8,8H112a8,8,0,0,1,0-16h32A8,8,0,0,1,152,224ZM128,112a12,12,0,1,0-12-12A12,12,0,0,0,128,112Zm95.62,43.83-12.36,55.63a16,16,0,0,1-25.51,9.11L158.51,200h-61L70.25,220.57a16,16,0,0,1-25.51-9.11L32.38,155.83a15.95,15.95,0,0,1,1.93-12.78L64,96.28V48a16,16,0,0,1,16-16h96a16,16,0,0,1,16,16V96.28l29.69,46.77A15.95,15.95,0,0,1,223.62,155.83Z"/></svg> }
        ].map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key as TabFilter)}
            className={`
              tab-link px-6 py-3 rounded-xl font-medium transition-all flex items-center gap-2
              ${activeTab === tab.key
                ? 'tab-active bg-[var(--primary)] text-white shadow-lg'
                : 'bg-white/5 border border-white/10 text-gray-400 hover:text-[var(--text)] hover:bg-white/8'
              }
            `}
          >
            {tab.icon}
            <span>{tab.label}</span>
            <span className={`
              px-2 py-0.5 rounded-full text-xs font-bold
              ${activeTab === tab.key ? 'bg-white/20' : 'bg-white/5'}
            `}>
              {tab.key === 'all' ? projects.length : projects.filter(p => p.status === tab.key).length}
            </span>
          </button>
        ))}
      </div>

      {/* Marketplace Section */}
      <div className="marketplace-section mb-12">
        <div className="flex items-center justify-between mb-6">
          <h2 className="font-heading text-2xl font-bold text-[var(--text)]">Recommended for You</h2>
          <button
            onClick={() => toast('Browse marketplace')}
            className="text-[var(--primary)] hover:text-orange-400 font-semibold flex items-center gap-2 transition-colors"
          >
            Browse Marketplace
            <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 256 256">
              <path d="M221.66,133.66l-72,72a8,8,0,0,1-11.32-11.32L196.69,136H40a8,8,0,0,1,0-16H196.69L138.34,61.66a8,8,0,0,1,11.32-11.32l72,72A8,8,0,0,1,221.66,133.66Z"/>
            </svg>
          </button>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <MarketplaceCard
            title="React Expert AI"
            description="Advanced React patterns and optimization"
            icon={<svg className="w-6 h-6 text-cyan-400" fill="currentColor" viewBox="0 0 256 256"><path d="M128,80a48,48,0,1,0,48,48A48.05,48.05,0,0,0,128,80Zm0,80a32,32,0,1,1,32-32A32,32,0,0,1,128,160ZM231.77,154.8c-1.59-2.5-3.89-6.11-6.93-10.86-6.38-10-16-24.84-29.17-44.26s-26.42-37.34-38.55-53.28c-5.76-7.58-10.92-14.34-15.48-20.25a146,146,0,0,0-83.26,0C53.84,31.91,48.67,38.66,42.92,46.24,30.79,62.18,20.51,80.76,13.33,99.68S1.59,135.8,0,149.2a146,146,0,0,0,83.26,0c4.56-5.91,9.72-12.67,15.48-20.25,12.13-15.94,22.41-34.52,29.59-53.44s11.74-33.88,13.33-47.28a146,146,0,0,0,0,83.26c-1.59,13.4-6.15,25.36-13.33,44.28s-17.46,37.34-29.59,53.28c-5.76,7.58-10.92,14.34-15.48,20.25a146,146,0,0,0,83.26,0c4.56-5.91,9.72-12.67,15.48-20.25,12.13-15.94,22.41-34.52,29.59-53.44s11.74-33.88,13.33-47.28a146,146,0,0,0,0-83.26c-1.59,13.4-6.15,25.36-13.33,44.28s-17.46,37.34-29.59,53.28c-5.76,7.58-10.92,14.34-15.48,20.25Z"/></svg>}
            badge="PRO"
          />
          <MarketplaceCard
            title="Database Pro"
            description="PostgreSQL and MongoDB expertise"
            icon={<svg className="w-6 h-6 text-purple-400" fill="currentColor" viewBox="0 0 256 256"><path d="M128,24C74.17,24,32,48.6,32,80v96c0,31.4,42.17,56,96,56s96-24.6,96-56V80C224,48.6,181.83,24,128,24Zm80,104c0,9.62-7.88,19.43-21.61,26.92C170.93,163.35,150.19,168,128,168s-42.93-4.65-58.39-13.08C55.88,147.43,48,137.62,48,128V111.36c17.06,15,46.23,24.64,80,24.64s62.94-9.68,80-24.64ZM69.61,53.08C85.07,44.65,105.81,40,128,40s42.93,4.65,58.39,13.08C200.12,60.57,208,70.38,208,80s-7.88,19.43-21.61,26.92C170.93,115.35,150.19,120,128,120s-42.93-4.65-58.39-13.08C55.88,99.43,48,89.62,48,80S55.88,60.57,69.61,53.08ZM186.39,202.92C170.93,211.35,150.19,216,128,216s-42.93-4.65-58.39-13.08C55.88,195.43,48,185.62,48,176V159.36c17.06,15,46.23,24.64,80,24.64s62.94-9.68,80-24.64V176C208,185.62,200.12,195.43,186.39,202.92Z"/></svg>}
            badge="Free"
            installed
          />
          <MarketplaceCard
            title="UI/UX Designer"
            description="Beautiful interfaces instantly"
            icon={<svg className="w-6 h-6 text-pink-400" fill="currentColor" viewBox="0 0 256 256"><path d="M201.54,54.46A104,104,0,0,0,54.46,201.54,104,104,0,0,0,201.54,54.46ZM96,210V152H48.8A88.15,88.15,0,0,1,96,210Zm0-74V46a88.15,88.15,0,0,1,0,164Zm16,74a88.15,88.15,0,0,0,47.2-58H112Zm95.2-74H160V46A88.15,88.15,0,0,1,207.2,136Z"/></svg>}
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
