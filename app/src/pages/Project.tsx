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
  ArrowsClockwise
} from '@phosphor-icons/react';
import { FloatingSidebar } from '../components/ui/FloatingSidebar';
import { FloatingPanel } from '../components/ui/FloatingPanel';
import { ChatContainer } from '../components/chat/ChatContainer';
import { LoadingSpinner } from '../components/PulsingGridSpinner';
import {
  GitHubPanel,
  ArchitecturePanel,
  NotesPanel,
  SettingsPanel,
  AssetsPanel
} from '../components/panels';
import CodeEditor from '../components/CodeEditor';
import { projectsApi } from '../lib/api';
import { useTheme } from '../theme/ThemeContext';
import toast from 'react-hot-toast';

type PanelType = 'github' | 'architecture' | 'notes' | 'settings' | 'marketplace' | 'assets' | null;

export default function Project() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { theme, toggleTheme } = useTheme();
  const [project, setProject] = useState<any>(null);
  const [files, setFiles] = useState<any[]>([]);
  const [activeView, setActiveView] = useState<'preview' | 'code'>('preview');
  const [activePanel, setActivePanel] = useState<PanelType>(null);
  const [devServerUrl, setDevServerUrl] = useState<string | null>(null);
  const [devServerUrlWithAuth, setDevServerUrlWithAuth] = useState<string | null>(null);
  const [currentPreviewUrl, setCurrentPreviewUrl] = useState<string>('');
  const projectId = parseInt(id!);

  const refreshTimeoutRef = React.useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const iframeRef = React.useRef<HTMLIFrameElement>(null);
  const urlCheckIntervalRef = React.useRef<ReturnType<typeof setInterval> | undefined>(undefined);

  useEffect(() => {
    loadProject();
    loadDevServerUrl();
  }, [projectId]);

  useEffect(() => {
    return () => {
      if (refreshTimeoutRef.current) {
        clearTimeout(refreshTimeoutRef.current);
      }
      if (urlCheckIntervalRef.current) {
        clearInterval(urlCheckIntervalRef.current);
      }
    };
  }, []);

  // Track iframe URL changes with polling
  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe) return;

    let lastUrl = '';

    const updateUrl = () => {
      try {
        const iframeUrl = iframe.contentWindow?.location.href;
        if (iframeUrl && iframeUrl !== 'about:blank' && iframeUrl !== lastUrl) {
          // Remove auth token from display
          const urlObj = new URL(iframeUrl);
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

          if (cleanUrl !== lastUrl) {
            lastUrl = cleanUrl;
            setCurrentPreviewUrl(cleanUrl);
          }
        }
      } catch (error) {
        // Cross-origin error - can't access iframe URL
        // Keep showing the current URL
      }
    };

    // Update URL on initial load
    iframe.addEventListener('load', updateUrl);

    // Poll for URL changes (catches navigation without page reload)
    urlCheckIntervalRef.current = setInterval(updateUrl, 500);

    return () => {
      iframe.removeEventListener('load', updateUrl);
      if (urlCheckIntervalRef.current) {
        clearInterval(urlCheckIntervalRef.current);
      }
    };
  }, [devServerUrl]);

  // Initialize current URL when dev server is ready
  useEffect(() => {
    if (devServerUrl) {
      setCurrentPreviewUrl(devServerUrl);
    }
  }, [devServerUrl]);

  // Listen for URL change messages from iframe
  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      // Handle URL change messages from the user project iframe
      if (event.data && event.data.type === 'urlchange') {
        const newUrl = event.data.url;
        if (newUrl && devServerUrl) {
          // Construct full URL from relative path
          try {
            const baseUrl = new URL(devServerUrl);
            const fullUrlObj = new URL(newUrl, baseUrl.origin);

            // Remove auth tokens from display
            fullUrlObj.searchParams.delete('auth_token');
            fullUrlObj.searchParams.delete('t');
            fullUrlObj.searchParams.delete('hmr_fallback');

            // Reconstruct clean URL
            let cleanUrl = fullUrlObj.origin + fullUrlObj.pathname;
            const remainingParams = fullUrlObj.searchParams.toString();
            if (remainingParams) {
              cleanUrl += '?' + remainingParams;
            }
            if (fullUrlObj.hash) {
              cleanUrl += fullUrlObj.hash;
            }

            setCurrentPreviewUrl(cleanUrl);
          } catch (error) {
            console.log('Error parsing URL from iframe:', error);
          }
        }
      }
    };

    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, [devServerUrl]);

  const loadProject = async () => {
    try {
      const [projectData, filesData] = await Promise.all([
        projectsApi.get(projectId),
        projectsApi.getFiles(projectId),
      ]);
      setProject(projectData);
      setFiles(filesData);
    } catch (error) {
      console.error('Failed to load project:', error);
      toast.error('Failed to load project');
    }
  };

  const handleFileUpdate = useCallback(async (filePath: string, content: string) => {
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
      await projectsApi.saveFile(projectId, filePath, content);
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
  }, [projectId]);

  const loadDevServerUrl = async () => {
    try {
      const response = await projectsApi.getDevServerUrl(projectId);
      const token = localStorage.getItem('token');

      if (response.status === 'ready' && response.url) {
        toast.dismiss('dev-server');
        toast.success('Development server ready!', { id: 'dev-server', duration: 2000 });

        // Store clean URL for display (without auth token)
        setDevServerUrl(response.url);

        // For Kubernetes mode: Add auth_token query param for authentication
        // Note: Docker mode does NOT validate this token - authentication gap that needs to be addressed
        if (token) {
          const urlWithAuth = response.url + (response.url.includes('?') ? '&' : '?') + 'auth_token=' + token;
          setDevServerUrlWithAuth(urlWithAuth);
        } else {
          setDevServerUrlWithAuth(response.url);
        }
      } else if (response.status === 'starting') {
        toast.loading('Development server is starting up...', { id: 'dev-server' });
        setTimeout(() => loadDevServerUrl(), 3000);
      } else if (response.url) {
        // Store clean URL for display
        setDevServerUrl(response.url);

        // Add auth token to iframe URL (Kubernetes auth, Docker has no validation)
        if (token) {
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

  const updateIframeUrl = () => {
    const iframe = iframeRef.current;
    if (!iframe) return;

    try {
      const iframeUrl = iframe.contentWindow?.location.href;
      if (iframeUrl && iframeUrl !== 'about:blank') {
        const urlObj = new URL(iframeUrl);
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
      }
    } catch (error) {
      // Cross-origin error - can't access iframe URL
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


  const agents = [
    { id: 'builder', name: 'Builder AI', icon: <Cube className="w-4 h-4" />, active: true },
    { id: 'react', name: 'React Expert', icon: <Code className="w-4 h-4" /> },
  ];

  if (!project) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-gray-400">Loading project...</div>
      </div>
    );
  }

  return (
    <div className="h-screen flex flex-col overflow-hidden relative">

      {/* Back Button */}
      <div className="absolute top-6 left-6 z-50">
        <button
          onClick={() => navigate('/dashboard')}
          className="flex items-center gap-2 px-4 py-2 bg-white/5 hover:bg-white/10 rounded-xl border border-white/10 text-[var(--text)]/80 hover:text-[var(--text)] transition-all"
        >
          <ArrowLeft size={20} />
          <span className="font-medium hidden sm:inline">Back to Projects</span>
        </button>
      </div>

      {/* Project Title */}
      <div className="absolute top-6 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3">
        <h1 className="font-heading text-xl sm:text-2xl font-bold text-[var(--text)]">{project.name}</h1>
        <div className="flex items-center gap-2 px-3 py-2 bg-white/5 rounded-lg text-xs text-green-400">
          <div className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
          <GitBranch size={14} />
          <span>Synced</span>
        </div>
      </div>

      {/* Left Sidebar */}
      <FloatingSidebar
        position="left"
        items={[
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
            icon: <Folder size={20} />,
            title: 'Files',
            onClick: () => alert('File tree feature')
          },
          {
            icon: <Cube size={20} />,
            title: 'Components',
            onClick: () => alert('Components library')
          },
          {
            icon: <GitBranch size={20} />,
            title: 'Architecture',
            onClick: () => togglePanel('architecture'),
            active: activePanel === 'architecture'
          },
          {
            icon: <BookOpen size={20} />,
            title: 'Notes & Tasks',
            onClick: () => togglePanel('notes'),
            active: activePanel === 'notes'
          }
        ]}
      />

      {/* Right Sidebar */}
      <FloatingSidebar
        position="right"
        items={[
          {
            icon: theme === 'dark' ? <Sun size={20} /> : <Moon size={20} />,
            title: 'Toggle Theme',
            onClick: toggleTheme
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
            onClick: () => alert('Deploy feature')
          },
          {
            icon: <ShareNetwork size={20} />,
            title: 'Share',
            onClick: () => alert('Share feature')
          }
        ]}
      />

      {/* Main Preview/Code Container */}
      <div className="h-screen w-screen flex items-center justify-center px-20 sm:px-32 py-20 sm:py-24 transition-all duration-500 relative z-10">
        <div className="w-full h-full relative bg-[var(--surface)] rounded-[20px] overflow-hidden border border-white/8 transition-all duration-500 shadow-2xl">
          {/* Preview View */}
          <div className={`w-full h-full ${activeView === 'preview' ? 'block' : 'hidden'}`}>
            {devServerUrl ? (
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
            ) : (
              <div className="h-full flex items-center justify-center text-[var(--text)]/60">
                <LoadingSpinner message="Starting development server..." size={60} />
              </div>
            )}
          </div>

          {/* Code View */}
          <div className={`w-full h-full ${activeView === 'code' ? 'flex' : 'hidden'} flex-col overflow-hidden`}>
            <CodeEditor
              projectId={projectId}
              files={files}
              onFileUpdate={handleFileUpdate}
            />
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
        <GitHubPanel projectId={projectId} />
      </FloatingPanel>

      <FloatingPanel
        title="Architecture"
        icon={<GitBranch size={20} />}
        isOpen={activePanel === 'architecture'}
        onClose={() => setActivePanel(null)}
      >
        <ArchitecturePanel projectId={projectId} />
      </FloatingPanel>

      <FloatingPanel
        title="Notes & Tasks"
        icon={<BookOpen size={20} />}
        isOpen={activePanel === 'notes'}
        onClose={() => setActivePanel(null)}
      >
        <NotesPanel projectId={projectId} />
      </FloatingPanel>

      <FloatingPanel
        title="Settings"
        icon={<Gear size={20} />}
        isOpen={activePanel === 'settings'}
        onClose={() => setActivePanel(null)}
      >
        <SettingsPanel projectId={projectId} />
      </FloatingPanel>

      <FloatingPanel
        title="Assets"
        icon={<Image size={20} />}
        isOpen={activePanel === 'assets'}
        onClose={() => setActivePanel(null)}
      >
        <AssetsPanel projectId={projectId} />
      </FloatingPanel>

      {/* Chat Interface */}
      <ChatContainer
        projectId={projectId}
        agents={agents}
        currentAgent={agents[0]}
        onSelectAgent={(agent) => console.log('Selected agent:', agent)}
        onFileUpdate={handleFileUpdate}
        onUpload={(type) => console.log('Upload:', type)}
        onAction={(action) => console.log('Action:', action)}
        onGetMoreCredits={() => alert('Get more credits')}
        creditsLeft={10}
      />
    </div>
  );
}
