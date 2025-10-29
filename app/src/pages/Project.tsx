import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  CaretLeft,
  CaretRight,
  Monitor,
  Code,
  Folder,
  Cube,
  GitBranch,
  BookOpen,
  Sun,
  Moon,
  Image,
  Storefront,
  Gear,
  Rocket,
  ShareNetwork,
  ArrowsClockwise,
  Kanban,
  FlowArrow
} from '@phosphor-icons/react';
import { FloatingSidebar } from '../components/ui/FloatingSidebar';
import { FloatingPanel } from '../components/ui/FloatingPanel';
import { MobileMenu } from '../components/ui/MobileMenu';
import { ChatContainer } from '../components/chat/ChatContainer';
import { LoadingSpinner } from '../components/PulsingGridSpinner';
import { MobileWarning } from '../components/MobileWarning';
import { BrowserPreview } from '../components/BrowserPreview';
import { DiscordSupport } from '../components/DiscordSupport';
import {
  GitHubPanel,
  ArchitecturePanel,
  NotesPanel,
  SettingsPanel,
  AssetsPanel,
  KanbanPanel
} from '../components/panels';
import CodeEditor from '../components/CodeEditor';
import { projectsApi, marketplaceApi } from '../lib/api';
import { useTheme } from '../theme/ThemeContext';
import toast from 'react-hot-toast';

type PanelType = 'github' | 'architecture' | 'notes' | 'settings' | 'marketplace' | 'assets' | null;
type MainViewType = 'preview' | 'code' | 'kanban';

interface UIAgent {
  id: string;
  name: string;
  icon: string;
  backendId: number;
  mode: 'stream' | 'agent';
}

export default function Project() {
  const { slug } = useParams<{ slug: string }>();
  const navigate = useNavigate();
  const { theme, toggleTheme } = useTheme();
  const [project, setProject] = useState<any>(null);
  const [files, setFiles] = useState<any[]>([]);
  const [agents, setAgents] = useState<UIAgent[]>([]);
  const [activeView, setActiveView] = useState<MainViewType>('preview');
  const [activePanel, setActivePanel] = useState<PanelType>(null);
  const [devServerUrl, setDevServerUrl] = useState<string | null>(null);
  const [devServerUrlWithAuth, setDevServerUrlWithAuth] = useState<string | null>(null);
  const [currentPreviewUrl, setCurrentPreviewUrl] = useState<string>('');
  const [previewMode, setPreviewMode] = useState<'normal' | 'browser-tabs'>('normal');
  // Note: We still have projectId for internal use, but it comes from the loaded project object

  const refreshTimeoutRef = React.useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const iframeRef = React.useRef<HTMLIFrameElement>(null);

  useEffect(() => {
    if (slug) {
      loadProject();
      loadDevServerUrl();
      loadSettings();
      loadAgents(); // Load user's enabled agents from library
    }
  }, [slug]);

  const loadSettings = async () => {
    if (!slug) return;
    try {
      const data = await projectsApi.getSettings(slug);
      const settings = data.settings || {};
      setPreviewMode(settings.preview_mode || 'normal');
    } catch (error) {
      console.error('Failed to load settings:', error);
    }
  };

  useEffect(() => {
    return () => {
      if (refreshTimeoutRef.current) {
        clearTimeout(refreshTimeoutRef.current);
      }
    };
  }, []);

  // Track iframe URL changes via postMessage
  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      // Handle URL change messages from iframe
      if (event.data && event.data.type === 'url-change') {
        const url = event.data.url;

        // Remove auth token from display
        try {
          const urlObj = new URL(url);
          urlObj.searchParams.delete('auth_token');
          urlObj.searchParams.delete('t');
          urlObj.searchParams.delete('hmr_fallback');

          // Reconstruct URL without the removed params
          let cleanUrl = urlObj.origin + urlObj.pathname;
          const remainingParams = urlObj.searchParams.toString();
          if (remainingParams) {
            cleanUrl += '?' + remainingParams;
          }
          if (urlObj.hash) {
            cleanUrl += urlObj.hash;
          }

          setCurrentPreviewUrl(cleanUrl);
        } catch (error) {
          // If URL parsing fails, use it as-is
          setCurrentPreviewUrl(url);
        }
      }
    };

    // Listen for messages from iframe
    window.addEventListener('message', handleMessage);

    return () => {
      window.removeEventListener('message', handleMessage);
    };
  }, []);

  // Initialize current URL when dev server is ready
  useEffect(() => {
    if (devServerUrl) {
      setCurrentPreviewUrl(devServerUrl);
    }
  }, [devServerUrl]);

  const loadProject = async () => {
    if (!slug) return;
    try {
      const [projectData, filesData] = await Promise.all([
        projectsApi.get(slug),
        projectsApi.getFiles(slug),
      ]);
      setProject(projectData);
      setFiles(filesData);
    } catch (error) {
      console.error('Failed to load project:', error);
      toast.error('Failed to load project');
    }
  };

  const loadAgents = async () => {
    try {
      // Load agents from user's library (enabled agents only)
      const libraryData = await marketplaceApi.getMyAgents();
      const enabledAgents = libraryData.agents.filter((agent: any) => agent.is_enabled);

      // Convert backend agents to UI format
      const uiAgents = enabledAgents.map((agent: any) => ({
        id: agent.slug,
        name: agent.name,
        icon: agent.icon || '🤖',
        backendId: agent.id,
        mode: agent.mode
      }));

      setAgents(uiAgents);
    } catch (error) {
      console.error('Failed to load agents:', error);
      toast.error('Failed to load agents');
    }
  };

  const handleFileUpdate = useCallback(async (filePath: string, content: string) => {
    if (!slug) return;

    setFiles(prev => {
      const existing = prev.find(f => f.file_path === filePath);
      if (existing) {
        return prev.map(f =>
          f.file_path === filePath ? { ...f, content } : f
        );
      }
      return [...prev, { file_path: filePath, content }];
    });

    try {
      await projectsApi.saveFile(slug, filePath, content);
    } catch (error) {
      console.error('Failed to save file:', error);
      toast.error(`Failed to save ${filePath}`);
    }

    if (filePath.match(/\.(jsx?|tsx?|css|html)$/i)) {
      if (refreshTimeoutRef.current) {
        clearTimeout(refreshTimeoutRef.current);
      }

      refreshTimeoutRef.current = setTimeout(() => {
        const iframe = iframeRef.current;
        if (iframe) {
          try {
            const currentSrc = iframe.src;
            iframe.src = currentSrc + (currentSrc.includes('?') ? '&' : '?') + 'hmr_fallback=' + Date.now();
          } catch (error) {
            console.log('Preview refresh error:', error);
          }
        }
      }, 5000);
    }
  }, [slug]);

  const loadDevServerUrl = async () => {
    if (!slug) return;
    try {
      const response = await projectsApi.getDevServerUrl(slug);
      const token = localStorage.getItem('token');
      const deploymentMode = import.meta.env.DEPLOYMENT_MODE || 'docker';

      if (response.status === 'ready' && response.url) {
        toast.dismiss('dev-server');
        toast.success('Development server ready!', { id: 'dev-server', duration: 2000 });
        setDevServerUrl(response.url);
        // Only add auth_token for Kubernetes deployment (NGINX Ingress auth)
        if (token && deploymentMode === 'kubernetes') {
          const urlWithAuth = response.url + (response.url.includes('?') ? '&' : '?') + 'auth_token=' + token;
          setDevServerUrlWithAuth(urlWithAuth);
        } else {
          setDevServerUrlWithAuth(response.url);
        }
      } else if (response.status === 'starting') {
        toast.loading('Development server is starting up...', { id: 'dev-server' });
        setTimeout(() => loadDevServerUrl(), 3000);
      } else if (response.url) {
        setDevServerUrl(response.url);
        // Only add auth_token for Kubernetes deployment (NGINX Ingress auth)
        if (token && deploymentMode === 'kubernetes') {
          const urlWithAuth = response.url + (response.url.includes('?') ? '&' : '?') + 'auth_token=' + token;
          setDevServerUrlWithAuth(urlWithAuth);
        } else {
          setDevServerUrlWithAuth(response.url);
        }
      }
    } catch (error: any) {
      toast.dismiss('dev-server');
      const errorMessage = error.response?.data?.detail?.message || error.response?.data?.detail || 'Failed to start dev server';
      toast.error(errorMessage, { id: 'dev-server' });
      setTimeout(() => loadDevServerUrl(), 5000);
    }
  };

  const refreshPreview = () => {
    if (devServerUrlWithAuth) {
      const iframe = iframeRef.current;
      if (iframe) {
        const url = new URL(devServerUrlWithAuth);
        url.searchParams.set('t', Date.now().toString());
        iframe.src = url.toString();
      }
    }
  };

  const navigateBack = () => {
    const iframe = iframeRef.current;
    if (iframe && iframe.contentWindow) {
      // Use postMessage to communicate with iframe instead of direct history access
      iframe.contentWindow.postMessage({ type: 'navigate', direction: 'back' }, '*');
    }
  };

  const navigateForward = () => {
    const iframe = iframeRef.current;
    if (iframe && iframe.contentWindow) {
      // Use postMessage to communicate with iframe instead of direct history access
      iframe.contentWindow.postMessage({ type: 'navigate', direction: 'forward' }, '*');
    }
  };

  const togglePanel = (panel: PanelType) => {
    setActivePanel(activePanel === panel ? null : panel);
  };

  if (!project) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-gray-400">Loading project...</div>
      </div>
    );
  }

  const leftSidebarItems = [
    {
      icon: <Monitor size={20} />,
      title: 'Preview',
      onClick: () => setActiveView('preview'),
      active: activeView === 'preview'
    },
    {
      icon: <Code size={20} />,
      title: 'Code',
      onClick: () => setActiveView('code'),
      active: activeView === 'code'
    },
    {
      icon: <Kanban size={20} />,
      title: 'Kanban Board',
      onClick: () => setActiveView('kanban'),
      active: activeView === 'kanban'
    },
    {
      icon: <Folder size={20} />,
      title: 'Files',
      onClick: () => toast('File tree feature coming soon!', { icon: '📁' })
    },
    {
      icon: <Cube size={20} />,
      title: 'Components',
      onClick: () => toast('Components library coming soon!', { icon: '🧩' })
    },
    {
      icon: <FlowArrow size={20} />,
      title: 'Architecture',
      onClick: () => togglePanel('architecture'),
      active: activePanel === 'architecture'
    }
  ];

  const rightSidebarItems = [
    {
      icon: theme === 'dark' ? <Sun size={20} /> : <Moon size={20} />,
      title: 'Toggle Theme',
      onClick: toggleTheme
    },
    {
      icon: <BookOpen size={20} />,
      title: 'Notes',
      onClick: () => togglePanel('notes'),
      active: activePanel === 'notes'
    },
    {
      icon: <GitBranch size={20} />,
      title: 'GitHub Sync',
      onClick: () => togglePanel('github'),
      active: activePanel === 'github'
    },
    {
      icon: <Image size={20} />,
      title: 'Assets',
      onClick: () => togglePanel('assets'),
      active: activePanel === 'assets'
    },
    {
      icon: <Storefront size={20} />,
      title: 'Agent Marketplace',
      onClick: () => navigate('/marketplace')
    },
    {
      icon: <Gear size={20} />,
      title: 'Settings',
      onClick: () => togglePanel('settings'),
      active: activePanel === 'settings'
    },
    {
      icon: <Rocket size={20} />,
      title: 'Deploy',
      onClick: () => toast('Deploy feature coming soon!', { icon: '🚀' })
    },
    {
      icon: <ShareNetwork size={20} />,
      title: 'Share',
      onClick: () => toast('Share feature coming soon!', { icon: '🔗' })
    }
  ];

  return (
    <div className="h-screen flex flex-col overflow-hidden relative">
      {/* Mobile Warning */}
      <MobileWarning />

      {/* Mobile Menu - Shows on mobile only */}
      <MobileMenu leftItems={leftSidebarItems} rightItems={rightSidebarItems} />

      {/* Back Button */}
      <div className="absolute top-4 left-4 md:top-6 md:left-6 z-50">
        <button
          onClick={() => navigate('/dashboard')}
          className="flex items-center gap-2 px-3 py-2 md:px-4 md:py-2 bg-white/5 hover:bg-white/10 rounded-xl border border-white/10 text-[var(--text)]/80 hover:text-[var(--text)] transition-all"
        >
          <ArrowLeft size={18} className="md:w-5 md:h-5" />
          <span className="font-medium text-sm md:text-base hidden sm:inline">Back to Projects</span>
        </button>
      </div>

      {/* Project Title - Hidden on mobile */}
      <div className="absolute top-6 left-1/2 -translate-x-1/2 z-50 hidden md:flex items-center gap-3">
        <h1 className="font-heading text-xl lg:text-2xl font-bold text-[var(--text)]">{project.name}</h1>
      </div>

      {/* Left Sidebar - Desktop only */}
      <FloatingSidebar
        position="left"
        items={leftSidebarItems}
      />

      {/* Right Sidebar - Desktop only */}
      <FloatingSidebar
        position="right"
        items={rightSidebarItems}
      />

      {/* Main Preview/Code Container */}
      <div className="h-screen w-screen flex items-center justify-center px-2 sm:px-8 md:px-20 lg:px-32 py-16 sm:py-20 md:py-24 transition-all duration-500 relative z-10">
        <div className="w-full h-full relative bg-[var(--surface)] rounded-[20px] overflow-hidden border border-white/8 transition-all duration-500 shadow-2xl">
          {/* Preview View */}
          <div className={`w-full h-full ${activeView === 'preview' ? 'block' : 'hidden'}`}>
            {devServerUrl ? (
              previewMode === 'browser-tabs' ? (
                <BrowserPreview
                  devServerUrl={devServerUrl}
                  devServerUrlWithAuth={devServerUrlWithAuth || devServerUrl}
                  currentPreviewUrl={currentPreviewUrl}
                  onNavigateBack={navigateBack}
                  onNavigateForward={navigateForward}
                  onRefresh={refreshPreview}
                  onUrlChange={setCurrentPreviewUrl}
                />
              ) : (
                <>
                  {/* Browser-style chrome */}
                  <div className="bg-[var(--surface)] border-b border-white/10 p-3 flex items-center gap-3">
                    <div className="flex items-center gap-2">
                      <div className="w-3 h-3 rounded-full bg-red-500" />
                      <div className="w-3 h-3 rounded-full bg-yellow-500" />
                      <div className="w-3 h-3 rounded-full bg-green-500" />
                    </div>
                    <div className="flex items-center gap-1">
                      <button
                        onClick={navigateBack}
                        className="p-2 hover:bg-white/10 rounded-lg transition-colors text-[var(--text)]/60 hover:text-[var(--text)]"
                        title="Go back"
                      >
                        <CaretLeft size={18} weight="bold" />
                      </button>
                      <button
                        onClick={navigateForward}
                        className="p-2 hover:bg-white/10 rounded-lg transition-colors text-[var(--text)]/60 hover:text-[var(--text)]"
                        title="Go forward"
                      >
                        <CaretRight size={18} weight="bold" />
                      </button>
                    </div>
                    <div className="flex-1">
                      <div className="bg-[var(--text)]/5 rounded-lg px-4 py-2 text-sm text-[var(--text)]/60 font-mono flex items-center border border-[var(--border-color)] overflow-hidden">
                        <span className="text-yellow-500 mr-2">🔒</span>
                        <span className="text-[var(--text)]/80 truncate">{currentPreviewUrl || devServerUrl}</span>
                      </div>
                    </div>
                    <button
                      onClick={refreshPreview}
                      className="p-2 hover:bg-white/10 rounded-lg transition-colors text-[var(--text)]/60 hover:text-[var(--text)]"
                      title="Refresh"
                    >
                      <ArrowsClockwise size={16} />
                    </button>
                  </div>
                  {/* Preview iframe */}
                  <div className="w-full h-[calc(100%-50px)] bg-white">
                    <iframe
                      ref={iframeRef}
                      id="preview-iframe"
                      src={devServerUrlWithAuth || devServerUrl}
                      className="w-full h-full"
                      sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals"
                    />
                  </div>
                </>
              )
            ) : (
              <div className="h-full flex items-center justify-center text-[var(--text)]/60">
                <LoadingSpinner message="Starting development server..." size={60} />
              </div>
            )}
          </div>

          {/* Code View */}
          <div className={`w-full h-full ${activeView === 'code' ? 'flex' : 'hidden'} flex-col overflow-hidden`}>
            <CodeEditor
              projectId={project?.id}
              files={files}
              onFileUpdate={handleFileUpdate}
            />
          </div>

          {/* Kanban View */}
          <div className={`w-full h-full ${activeView === 'kanban' ? 'block' : 'hidden'}`}>
            <KanbanPanel projectId={project?.id} />
          </div>
        </div>
      </div>

      {/* Floating Panels */}
      <FloatingPanel
        title="GitHub Sync"
        icon={<GitBranch size={20} />}
        isOpen={activePanel === 'github'}
        onClose={() => setActivePanel(null)}
      >
        <GitHubPanel projectId={project?.id} />
      </FloatingPanel>

      <FloatingPanel
        title="Architecture"
        icon={<FlowArrow size={20} />}
        isOpen={activePanel === 'architecture'}
        onClose={() => setActivePanel(null)}
        defaultSize={{ width: 900, height: 700 }}
        defaultPosition={{ x: 200, y: 100 }}
      >
        <ArchitecturePanel projectSlug={slug!} />
      </FloatingPanel>

      <FloatingPanel
        title="Notes & Tasks"
        icon={<BookOpen size={20} />}
        isOpen={activePanel === 'notes'}
        onClose={() => setActivePanel(null)}
      >
        <NotesPanel projectSlug={slug!} />
      </FloatingPanel>

      <FloatingPanel
        title="Settings"
        icon={<Gear size={20} />}
        isOpen={activePanel === 'settings'}
        onClose={() => setActivePanel(null)}
      >
        <SettingsPanel projectSlug={slug!} />
      </FloatingPanel>

      <FloatingPanel
        title="Assets"
        icon={<Image size={20} />}
        isOpen={activePanel === 'assets'}
        onClose={() => setActivePanel(null)}
      >
        <AssetsPanel projectId={project?.id} />
      </FloatingPanel>

      {/* Chat Interface or Empty State */}
      {agents.length > 0 ? (
        <ChatContainer
          projectId={project?.id}
          agents={agents}
          currentAgent={agents[0]}
          onSelectAgent={(agent) => console.log('Selected agent:', agent)}
          onFileUpdate={handleFileUpdate}
          projectFiles={files}
          projectName={project?.name}
        />
      ) : (
        <div className="fixed inset-0 z-40 flex items-center justify-center pointer-events-none">
          <div className="bg-[var(--surface)] border border-white/10 rounded-2xl shadow-2xl p-8 max-w-md pointer-events-auto">
            <div className="text-center">
              <div className="w-16 h-16 bg-[rgba(255,107,0,0.2)] rounded-2xl flex items-center justify-center mx-auto mb-4">
                <Storefront className="w-8 h-8 text-[var(--primary)]" weight="fill" />
              </div>
              <h3 className="font-heading text-xl font-bold text-[var(--text)] mb-2">
                No Agents Enabled
              </h3>
              <p className="text-[var(--text)]/60 mb-6">
                Add agents from the marketplace to your library and enable them to start building
              </p>
              <div className="flex flex-col gap-3">
                <button
                  onClick={() => navigate('/library')}
                  className="w-full bg-[var(--primary)] hover:bg-orange-600 text-white py-3 px-6 rounded-xl font-semibold transition-all flex items-center justify-center gap-2"
                >
                  <Storefront size={20} weight="fill" />
                  Go to Library
                </button>
                <button
                  onClick={() => navigate('/marketplace')}
                  className="w-full bg-white/5 hover:bg-white/10 border border-white/10 text-[var(--text)] py-3 px-6 rounded-xl font-semibold transition-all flex items-center justify-center gap-2"
                >
                  <Storefront size={20} weight="fill" />
                  Browse Marketplace
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Discord Support */}
      <DiscordSupport />
    </div>
  );
}
