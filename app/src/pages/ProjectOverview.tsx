import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { NavigationSidebar, MobileMenu, Breadcrumbs } from '../components/ui';
import { Tabs, type Tab } from '../components/ui/Tabs';
import { useTheme } from '../theme/ThemeContext';
import { projectsApi } from '../lib/api';
import toast from 'react-hot-toast';
import {
  Lightbulb,
  Hammer,
  CloudUpload,
  Rocket,
  DollarSign,
  FolderOpen,
  Store,
  BookOpen,
  Package,
  Settings,
  Sun,
  Moon,
  LogOut,
} from 'lucide-react';

export default function ProjectOverview() {
  const { slug } = useParams<{ slug: string }>();
  const navigate = useNavigate();
  const { theme, toggleTheme } = useTheme();

  // Format slug as fallback display name
  const formattedSlug = slug?.replace(/-/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase()) || '';
  const [projectName, setProjectName] = useState<string>(formattedSlug);

  // Persist active tab in localStorage per project
  const storageKey = `project-tab-${slug}`;
  const [activeTab, setActiveTab] = useState<string>(() => {
    return localStorage.getItem(storageKey) || 'plan';
  });

  // Fetch project data
  useEffect(() => {
    const fetchProject = async () => {
      if (!slug) return;
      try {
        const project = await projectsApi.get(slug);
        setProjectName(project.name);
      } catch (error) {
        console.error('Failed to fetch project:', error);
        toast.error('Failed to load project');
      }
    };
    fetchProject();
  }, [slug]);

  // Save tab to localStorage whenever it changes
  useEffect(() => {
    localStorage.setItem(storageKey, activeTab);
  }, [activeTab, storageKey]);

  const logout = () => {
    localStorage.removeItem('token');
    navigate('/login');
  };

  // Mobile menu items
  const mobileMenuItems = {
    left: [
      {
        icon: <FolderOpen className="w-5 h-5" />,
        title: 'Projects',
        onClick: () => navigate('/dashboard'),
      },
      {
        icon: <Store className="w-5 h-5" />,
        title: 'Marketplace',
        onClick: () => navigate('/marketplace')
      },
      {
        icon: <BookOpen className="w-5 h-5" />,
        title: 'Library',
        onClick: () => navigate('/library')
      },
      {
        icon: <Package className="w-5 h-5" />,
        title: 'Components',
        onClick: () => toast('Components library coming soon!')
      }
    ],
    right: [
      {
        icon: theme === 'dark' ? <Sun className="w-5 h-5" /> : <Moon className="w-5 h-5" />,
        title: theme === 'dark' ? 'Light Mode' : 'Dark Mode',
        onClick: toggleTheme
      },
      {
        icon: <Settings className="w-5 h-5" />,
        title: 'Settings',
        onClick: () => navigate('/settings')
      },
      {
        icon: <LogOut className="w-5 h-5" />,
        title: 'Logout',
        onClick: logout
      }
    ]
  };

  const tabs: Tab[] = [
    {
      id: 'plan',
      label: 'Plan',
      icon: <Lightbulb size={16} />,
    },
    {
      id: 'build',
      label: 'Build',
      icon: <Hammer size={16} />,
    },
    {
      id: 'deploy',
      label: 'Deploy',
      icon: <CloudUpload size={16} />,
    },
    {
      id: 'launch',
      label: 'Launch',
      icon: <Rocket size={16} />,
    },
    {
      id: 'sell',
      label: 'Sell',
      icon: <DollarSign size={16} />,
    },
  ];

  const handleOpenBuilder = () => {
    navigate(`/project/${slug}/builder`);
  };

  return (
    <div className="h-screen flex bg-[var(--bg-dark)]">
      {/* Mobile Menu */}
      <MobileMenu leftItems={mobileMenuItems.left} rightItems={mobileMenuItems.right} />

      {/* Navigation Sidebar */}
      <NavigationSidebar activePage="dashboard" />

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Top Bar */}
        <div className="h-12 bg-[var(--surface)] border-b border-[var(--sidebar-border)] flex items-center px-4 md:px-6 justify-between">
          <Breadcrumbs
            items={[
              { label: 'Projects', href: '/dashboard' },
              { label: projectName }
            ]}
          />
        </div>

        {/* Tabs Navigation */}
        <div className="flex-shrink-0">
          <Tabs tabs={tabs} activeTab={activeTab} onTabChange={setActiveTab} />
        </div>

        {/* Tab Content */}
        <div className="flex-1 overflow-y-auto bg-[var(--bg-dark)]">
          <div className="p-4 md:p-6">
            {/* Plan Tab */}
            {activeTab === 'plan' && (
              <div className="max-w-4xl">
                <div className="bg-[var(--surface)] rounded-2xl border border-[var(--sidebar-border)] p-6 sm:p-8">
                  <div className="flex items-center gap-3 mb-4">
                    <div className="w-10 h-10 sm:w-12 sm:h-12 rounded-xl bg-[rgba(var(--status-purple-rgb),0.1)] flex items-center justify-center">
                      <Lightbulb className="w-6 h-6 sm:w-7 sm:h-7 text-[var(--status-purple)]" />
                    </div>
                    <h2 className="text-xl sm:text-2xl font-bold text-[var(--text)]">Plan</h2>
                  </div>
                  <p className="text-gray-400 text-sm sm:text-base">
                    Planning features coming soon. This is where you'll manage your project roadmap, milestones, and requirements.
                  </p>
                </div>
              </div>
            )}

            {/* Build Tab */}
            {activeTab === 'build' && (
              <div className="max-w-4xl">
                <div className="bg-[var(--surface)] rounded-2xl border border-[var(--sidebar-border)] p-6 sm:p-8">
                  <div className="flex items-center gap-3 mb-4">
                    <div className="w-10 h-10 sm:w-12 sm:h-12 rounded-xl bg-[rgba(var(--primary-rgb),0.1)] flex items-center justify-center">
                      <Hammer className="w-6 h-6 sm:w-7 sm:h-7 text-[var(--primary)]" />
                    </div>
                    <h2 className="text-xl sm:text-2xl font-bold text-[var(--text)]">Build</h2>
                  </div>
                  <p className="text-gray-400 text-sm sm:text-base mb-6">
                    Access your full development environment with code editor, preview, terminal, and more.
                  </p>
                  <button
                    onClick={handleOpenBuilder}
                    className="
                      bg-[var(--primary)] hover:bg-[var(--primary-hover)]
                      text-white font-semibold
                      px-6 py-3 rounded-xl
                      transition-all duration-200
                      flex items-center gap-2
                      shadow-lg shadow-[rgba(var(--primary-rgb),0.2)]
                      hover:shadow-xl hover:shadow-[rgba(var(--primary-rgb),0.3)]
                      hover:scale-[1.02]
                    "
                  >
                    <Hammer className="w-5 h-5" />
                    Open Builder
                  </button>
                </div>
              </div>
            )}

            {/* Deploy Tab */}
            {activeTab === 'deploy' && (
              <div className="max-w-4xl">
                <div className="bg-[var(--surface)] rounded-2xl border border-[var(--sidebar-border)] p-6 sm:p-8">
                  <div className="flex items-center gap-3 mb-4">
                    <div className="w-10 h-10 sm:w-12 sm:h-12 rounded-xl bg-[rgba(var(--status-blue-rgb),0.1)] flex items-center justify-center">
                      <CloudUpload className="w-6 h-6 sm:w-7 sm:h-7 text-[var(--status-blue)]" />
                    </div>
                    <h2 className="text-xl sm:text-2xl font-bold text-[var(--text)]">Deploy</h2>
                  </div>
                  <p className="text-gray-400 text-sm sm:text-base">
                    Deployment features coming soon. This is where you'll configure and manage your deployment pipelines.
                  </p>
                </div>
              </div>
            )}

            {/* Launch Tab */}
            {activeTab === 'launch' && (
              <div className="max-w-4xl">
                <div className="bg-[var(--surface)] rounded-2xl border border-[var(--sidebar-border)] p-6 sm:p-8">
                  <div className="flex items-center gap-3 mb-4">
                    <div className="w-10 h-10 sm:w-12 sm:h-12 rounded-xl bg-[rgba(var(--status-green-rgb),0.1)] flex items-center justify-center">
                      <Rocket className="w-6 h-6 sm:w-7 sm:h-7 text-[var(--status-green)]" />
                    </div>
                    <h2 className="text-xl sm:text-2xl font-bold text-[var(--text)]">Launch</h2>
                  </div>
                  <p className="text-gray-400 text-sm sm:text-base">
                    Launch features coming soon. This is where you'll manage your launch checklist, marketing, and analytics.
                  </p>
                </div>
              </div>
            )}

            {/* Sell Tab */}
            {activeTab === 'sell' && (
              <div className="max-w-4xl">
                <div className="bg-[var(--surface)] rounded-2xl border border-[var(--sidebar-border)] p-6 sm:p-8">
                  <div className="flex items-center gap-3 mb-4">
                    <div className="w-10 h-10 sm:w-12 sm:h-12 rounded-xl bg-[rgba(var(--status-green-rgb),0.1)] flex items-center justify-center">
                      <DollarSign className="w-6 h-6 sm:w-7 sm:h-7 text-[var(--status-green)]" />
                    </div>
                    <h2 className="text-xl sm:text-2xl font-bold text-[var(--text)]">Sell</h2>
                  </div>
                  <p className="text-gray-400 text-sm sm:text-base">
                    Monetization features coming soon. This is where you'll manage pricing, payments, and sales analytics.
                  </p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
