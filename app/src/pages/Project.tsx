import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { useHotkeys } from 'react-hotkeys-hook';
import {
  ArrowLeft,
  CaretLeft,
  CaretRight,
  Monitor,
  Code,
  GitBranch,
  BookOpen,
  Image,
  Storefront,
  Gear,
  Rocket,
  ShareNetwork,
  ArrowsClockwise,
  Kanban,
  FlowArrow,
  List,
  Article,
  Terminal,
} from '@phosphor-icons/react';
import { FloatingPanel } from '../components/ui/FloatingPanel';
import { MobileMenu } from '../components/ui/MobileMenu';
import { Tooltip } from '../components/ui/Tooltip';
import { Breadcrumbs } from '../components/ui/Breadcrumbs';
import { UserDropdown } from '../components/ui/UserDropdown';
import { ChatContainer } from '../components/chat/ChatContainer';
import { LoadingSpinner } from '../components/PulsingGridSpinner';
import { MobileWarning } from '../components/MobileWarning';
import { BrowserPreview } from '../components/BrowserPreview';
import { ContainerLoadingOverlay } from '../components/ContainerLoadingOverlay';
import { DiscordSupport } from '../components/DiscordSupport';
import { useContainerStartup } from '../hooks/useContainerStartup';
import {
  GitHubPanel,
  NotesPanel,
  SettingsPanel,
  AssetsPanel,
  KanbanPanel,
  TerminalPanel,
} from '../components/panels';
import { DeploymentsDropdown } from '../components/DeploymentsDropdown';
import { DeploymentModal } from '../components/modals/DeploymentModal';
import CodeEditor from '../components/CodeEditor';
import { ContainerSelector } from '../components/ContainerSelector';
import { projectsApi, marketplaceApi } from '../lib/api';
import { useCommandHandlers, type ViewType } from '../contexts/CommandContext';
import { useChatPosition } from '../contexts/ChatPositionContext';
import toast from 'react-hot-toast';
import { fileEvents } from '../utils/fileEvents';
import { motion } from 'framer-motion';
import { Panel, Group as PanelGroup, Separator as PanelResizeHandle } from 'react-resizable-panels';
import { type ChatAgent } from '../types/chat';

type PanelType = 'github' | 'notes' | 'settings' | 'marketplace' | null;
type MainViewType = 'preview' | 'code' | 'kanban' | 'assets' | 'terminal';

export default function Project() {
  const { slug } = useParams<{ slug: string }>();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const containerId = searchParams.get('container');

  const { chatPosition } = useChatPosition();
  const [project, setProject] = useState<Record<string, unknown> | null>(null);
  const [files, setFiles] = useState<Array<Record<string, unknown>>>([]);
  const [container, setContainer] = useState<Record<string, unknown> | null>(null);
  const [containers, setContainers] = useState<Array<Record<string, unknown>>>([]);
  const [agents, setAgents] = useState<ChatAgent[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(() => {
    if (!slug) return null;
    return localStorage.getItem(`tesslate-agent-${slug}`);
  });
  const [activeView, setActiveView] = useState<MainViewType>('preview');
  const [kanbanMounted, setKanbanMounted] = useState(false);
  const [activePanel, setActivePanel] = useState<PanelType>(null);
  const [devServerUrl, setDevServerUrl] = useState<string | null>(null);
  const [devServerUrlWithAuth, setDevServerUrlWithAuth] = useState<string | null>(null);
  const [currentPreviewUrl, setCurrentPreviewUrl] = useState<string>('');
  const [previewMode, setPreviewMode] = useState<'normal' | 'browser-tabs'>('normal');
  const [isLeftSidebarExpanded, setIsLeftSidebarExpanded] = useState(() => {
    const saved = localStorage.getItem('projectSidebarExpanded');
    return saved !== null ? JSON.parse(saved) : true;
  });
  const [showDeploymentsDropdown, setShowDeploymentsDropdown] = useState(false);
  const [showDeployModal, setShowDeployModal] = useState(false);

  // Chat panel width for Discord button positioning (stored in localStorage by react-resizable-panels)
  const [chatPanelWidth, _setChatPanelWidth] = useState(400);

  const refreshTimeoutRef = React.useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const iframeRef = React.useRef<HTMLIFrameElement>(null);
  const isPointerOverPreviewRef = useRef(false);

  // Track if we need to start the container (for the startup hook)
  const [needsContainerStart, setNeedsContainerStart] = useState(false);
  const currentContainerIdRef = useRef<string | null>(null);

  // Container startup hook - handles task polling, logs, and health checks
  const containerStartup = useContainerStartup(
    slug,
    needsContainerStart ? currentContainerIdRef.current : null,
    {
      onReady: (url) => {
        // Container is ready - set the URL for the preview
        setDevServerUrl(url);
        setDevServerUrlWithAuth(url);
        setCurrentPreviewUrl(url);
        setNeedsContainerStart(false);
        toast.success('Development server ready!', { id: 'container-start', duration: 2000 });
      },
      onError: (error) => {
        setNeedsContainerStart(false);
        toast.error(`Container failed: ${error}`, { id: 'container-start' });
      },
    }
  );

  // ============================================================================
  // PROJECT KEYBOARD SHORTCUTS
  // ============================================================================

  // View switching shortcuts (Cmd/Ctrl + 1-5)
  useHotkeys(
    'mod+1',
    (e) => {
      e.preventDefault();
      setActiveView('preview');
    },
    { enableOnFormTags: false }
  );

  useHotkeys(
    'mod+2',
    (e) => {
      e.preventDefault();
      setActiveView('code');
    },
    { enableOnFormTags: false }
  );

  useHotkeys(
    'mod+3',
    (e) => {
      e.preventDefault();
      setActiveView('kanban');
    },
    { enableOnFormTags: false }
  );

  useHotkeys(
    'mod+4',
    (e) => {
      e.preventDefault();
      setActiveView('assets');
    },
    { enableOnFormTags: false }
  );

  useHotkeys(
    'mod+5',
    (e) => {
      e.preventDefault();
      setActiveView('terminal');
    },
    { enableOnFormTags: false }
  );

  // Refresh preview (Cmd/Ctrl + R)
  useHotkeys(
    'mod+r',
    (e) => {
      e.preventDefault();
      if (activeView === 'preview') {
        refreshPreview();
      }
    },
    { enableOnFormTags: false }
  );

  // Sidebar toggle (Cmd/Ctrl + [ and ])
  useHotkeys(
    'mod+[',
    (e) => {
      e.preventDefault();
      setIsLeftSidebarExpanded(false);
    },
    { enableOnFormTags: false }
  );

  useHotkeys(
    'mod+]',
    (e) => {
      e.preventDefault();
      setIsLeftSidebarExpanded(true);
    },
    { enableOnFormTags: false }
  );

  // Panel shortcuts (Cmd/Ctrl + Shift + G/N/S/A)
  useHotkeys(
    'mod+shift+g',
    (e) => {
      e.preventDefault();
      togglePanel('github');
    },
    { enableOnFormTags: false }
  );

  useHotkeys(
    'mod+shift+n',
    (e) => {
      e.preventDefault();
      togglePanel('notes');
    },
    { enableOnFormTags: false }
  );

  useHotkeys(
    'mod+shift+s',
    (e) => {
      e.preventDefault();
      togglePanel('settings');
    },
    { enableOnFormTags: false }
  );

  // Escape to close active panel
  useHotkeys(
    'escape',
    () => {
      if (activePanel) {
        setActivePanel(null);
      }
    },
    { enableOnFormTags: false }
  );

  useEffect(() => {
    if (slug) {
      loadProject();
      loadDevServerUrl();
      loadSettings();
      loadAgents(); // Load user's enabled agents from library
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug]);

  // Load containers on mount and when containerId changes
  useEffect(() => {
    if (slug) {
      loadContainer();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [containerId, slug]);

  // Reload files when container changes (to apply filtering)
  useEffect(() => {
    if (container) {
      loadFiles();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [container]);

  useEffect(() => {
    localStorage.setItem('projectSidebarExpanded', JSON.stringify(isLeftSidebarExpanded));
  }, [isLeftSidebarExpanded]);

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
        } catch {
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

  // Listen for file change events from Assets panel and other components
  useEffect(() => {
    const unsubscribe = fileEvents.on((detail) => {
      console.log('File event received:', detail.type, detail.filePath);
      // Refresh the file list when any file changes
      loadFiles();
    });

    return () => {
      unsubscribe();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug]);

  // Smart polling to catch file changes from agents using bash/exec commands
  // This is a backup mechanism since agents can modify files via shell commands
  useEffect(() => {
    if (!slug) return;

    let pollInterval: NodeJS.Timeout | null = null;
    let isTabVisible = true;

    // Only poll when tab is visible to minimize server load
    const handleVisibilityChange = () => {
      isTabVisible = !document.hidden;

      if (isTabVisible && !pollInterval) {
        // Resume polling when tab becomes visible
        startPolling();
      } else if (!isTabVisible && pollInterval) {
        // Stop polling when tab is hidden
        clearInterval(pollInterval);
        pollInterval = null;
      }
    };

    const startPolling = () => {
      // Poll every 30 seconds - events handle most changes, this catches edge cases
      pollInterval = setInterval(() => {
        if (isTabVisible && slug) {
          loadFiles();
        }
      }, 30000);
    };

    // Listen for visibility changes
    document.addEventListener('visibilitychange', handleVisibilityChange);

    // Start polling if tab is visible
    if (isTabVisible) {
      startPolling();
    }

    return () => {
      if (pollInterval) {
        clearInterval(pollInterval);
      }
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug, container]); // Re-create interval when container changes to use fresh loadFiles

  // Refresh files when switching to code view
  useEffect(() => {
    if (activeView === 'code' && slug) {
      loadFiles();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeView, slug, container]); // Include container to use correct filter

  // Lazily mount KanbanPanel on first visit to preserve state across tab switches
  useEffect(() => {
    if (activeView === 'kanban' && !kanbanMounted) {
      setKanbanMounted(true);
    }
  }, [activeView, kanbanMounted]);

  const loadProject = async () => {
    if (!slug) return;
    try {
      const projectData = await projectsApi.get(slug);
      setProject(projectData);

      // Only load files here if NOT viewing a specific container
      // When viewing a container, loadFiles() will be called after container loads
      // to properly filter files for that container's directory
      if (!containerId) {
        const filesData = await projectsApi.getFiles(slug);
        setFiles(filesData);
      }
    } catch (error) {
      console.error('Failed to load project:', error);
      toast.error('Failed to load project');
    }
  };

  const loadFiles = async () => {
    if (!slug) return;
    try {
      const filesData = await projectsApi.getFiles(slug);

      // If viewing a specific container, filter files to that container's directory
      // Each container has its own directory (e.g., next-js-15/, vite-react-fastapi/)
      // Strip the container directory prefix so paths are relative to container root
      if (containerId && container && container.directory) {
        const containerDir = container.directory as string;
        const filteredFiles = filesData
          .filter((file: Record<string, unknown>) =>
            (file.file_path as string).startsWith(containerDir + '/')
          )
          .map((file: Record<string, unknown>) => ({
            ...file,
            // Strip container directory prefix for display (e.g., "next-js-15/app/page.tsx" -> "app/page.tsx")
            file_path: (file.file_path as string).slice(containerDir.length + 1),
          }));

        // In K8s mode, files are already container-scoped (no prefix)
        // If filtering by prefix returns no files but we have data, use the data directly
        if (filteredFiles.length === 0 && filesData.length > 0) {
          // Files don't have container directory prefix - they're already scoped to this container
          setFiles(filesData);
        } else {
          setFiles(filteredFiles);
        }
      } else {
        // No container selected - show all files
        setFiles(filesData);
      }
    } catch (error) {
      console.error('Failed to load files:', error);
    }
  };

  const loadContainer = async () => {
    if (!slug) return;
    try {
      const allContainers = await projectsApi.getContainers(slug);
      setContainers(allContainers);

      // Find current container (by ID or default to first)
      const foundContainer = containerId
        ? allContainers.find((c: Record<string, unknown>) => c.id === containerId)
        : allContainers[0];

      if (foundContainer) {
        setContainer(foundContainer);

        // Check if container is already running before starting
        try {
          const status = await projectsApi.getContainersStatus(slug);
          // Match the backend's _sanitize_service_name(container.name) which is used
          // as the key in docker compose status. directory="." means root project dir,
          // not a valid service name — so fall through to container name.
          const rawDir = foundContainer.directory;
          const serviceKey = (rawDir && rawDir !== '.' ? rawDir : foundContainer.name)
            ?.toLowerCase()
            .replace(/[\s_.]/g, '-')
            .replace(/[^a-z0-9-]/g, '')
            .replace(/-+/g, '-')
            .replace(/^-|-$/g, '');
          const containerStatus = status?.containers?.[serviceKey];

          console.log('[loadContainer] status response:', JSON.stringify(status));
          console.log('[loadContainer] rawDir:', rawDir, 'serviceKey:', serviceKey);
          console.log('[loadContainer] containerStatus:', JSON.stringify(containerStatus));

          // Check for hibernation - only explicit hibernated status, not just stopped
          if (
            containerStatus?.status === 'hibernated' ||
            status?.environment_status === 'hibernated'
          ) {
            toast('This project has been hibernated. Redirecting to projects...', {
              duration: 3000,
            });
            navigate('/dashboard');
            return;
          }

          if (containerStatus?.running && containerStatus?.url) {
            // Container already running - just set the URL without starting
            console.log('[loadContainer] FAST PATH: container running at', containerStatus.url);
            // Reset any in-flight startup state from a previously loading container
            containerStartup.reset();
            setNeedsContainerStart(false);
            setDevServerUrl(containerStatus.url);
            setDevServerUrlWithAuth(containerStatus.url);
            setCurrentPreviewUrl(containerStatus.url);
            return;
          }
          console.log('[loadContainer] SLOW PATH: container not detected as running');
        } catch (statusError) {
          // Status check failed, proceed with start anyway
          console.warn('Failed to check container status, will attempt start:', statusError);
        }

        // Container not running - use the startup hook to start it with real-time logs
        console.log('[loadContainer] Starting container via startup hook');
        const containerIdToStart = foundContainer.id as string;
        currentContainerIdRef.current = containerIdToStart;
        setNeedsContainerStart(true);
        // Pass containerId directly to avoid timing issues with React state updates
        containerStartup.startContainer(containerIdToStart);
      }
    } catch (error) {
      console.error('Failed to load container:', error);
    }
  };

  const loadAgents = async () => {
    try {
      // Load agents from user's library (enabled agents only)
      const libraryData = await marketplaceApi.getMyAgents();
      const enabledAgents = libraryData.agents.filter(
        (agent: Record<string, unknown>) => agent.is_enabled
      );

      // Convert backend agents to UI format
      const uiAgents = enabledAgents.map((agent: Record<string, unknown>) => ({
        id: agent.slug as string,
        name: agent.name as string,
        icon: (agent.icon as string) || '🤖',
        backendId: agent.id as string,
        mode: agent.mode as string,
        model: agent.model as string | undefined,
        selectedModel: agent.selected_model as string | null | undefined,
        sourceType: agent.source_type as 'open' | 'closed' | undefined,
        isCustom: agent.is_custom as boolean | undefined,
      }));

      setAgents(uiAgents);
    } catch (error) {
      console.error('Failed to load agents:', error);
      toast.error('Failed to load agents');
    }
  };

  // Derive current agent from agents + selectedAgentId (persisted in localStorage)
  const currentAgent = useMemo(() => {
    if (selectedAgentId) {
      const found = agents.find((a) => a.id === selectedAgentId);
      if (found) return found;
    }
    return agents[0] ?? null;
  }, [agents, selectedAgentId]);

  const handleAgentSelect = useCallback(
    (agent: ChatAgent) => {
      setSelectedAgentId(agent.id);
      if (slug) localStorage.setItem(`tesslate-agent-${slug}`, agent.id);
    },
    [slug]
  );

  const handleFileUpdate = useCallback(
    async (filePath: string, content: string) => {
      if (!slug) return;

      // For container-scoped views, prepend container directory when saving
      // (we stripped it for display, now add it back for the API)
      const saveFilePath =
        containerId && container?.directory ? `${container.directory}/${filePath}` : filePath;

      // Track if this is a new file or an update
      let isNewFile = false;
      setFiles((prev) => {
        const existing = prev.find((f) => f.file_path === filePath);
        isNewFile = !existing;
        if (existing) {
          return prev.map((f) => (f.file_path === filePath ? { ...f, content } : f));
        }
        return [...prev, { file_path: filePath, content }];
      });

      try {
        await projectsApi.saveFile(slug, saveFilePath, content);

        // Emit file event to refresh the code editor file tree
        fileEvents.emit(isNewFile ? 'file-created' : 'file-updated', filePath);
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
              iframe.src =
                currentSrc + (currentSrc.includes('?') ? '&' : '?') + 'hmr_fallback=' + Date.now();
            } catch (error) {
              console.log('Preview refresh error:', error);
            }
          }
        }, 5000);
      }
    },
    [slug, containerId, container]
  );

  const loadDevServerUrl = async () => {
    if (!slug) return;
    try {
      const response = await projectsApi.getDevServerUrl(slug);
      const token = localStorage.getItem('token');
      const deploymentMode = import.meta.env.DEPLOYMENT_MODE || 'docker';

      // Handle multi-container projects (no single dev server)
      if (response.status === 'multi_container') {
        toast.dismiss('dev-server');
        setDevServerUrl(null);
        setDevServerUrlWithAuth(null);
        return;
      }

      if (response.status === 'ready' && response.url) {
        toast.dismiss('dev-server');
        toast.success('Development server ready!', { id: 'dev-server', duration: 2000 });
        setDevServerUrl(response.url);
        // Only add auth_token for Kubernetes deployment (NGINX Ingress auth)
        if (token && deploymentMode === 'kubernetes') {
          const urlWithAuth =
            response.url + (response.url.includes('?') ? '&' : '?') + 'auth_token=' + token;
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
          const urlWithAuth =
            response.url + (response.url.includes('?') ? '&' : '?') + 'auth_token=' + token;
          setDevServerUrlWithAuth(urlWithAuth);
        } else {
          setDevServerUrlWithAuth(response.url);
        }
      }
    } catch (error: unknown) {
      toast.dismiss('dev-server');
      const err = error as { response?: { data?: { detail?: { message?: string } | string } } };
      const detail = err.response?.data?.detail;
      const errorMessage =
        (typeof detail === 'object' && detail?.message) ||
        (typeof detail === 'string' ? detail : null) ||
        'Failed to start dev server';
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

  // Register command handlers for CommandPalette
  // These handlers allow the command palette to execute project-specific commands
  useCommandHandlers({
    switchView: (view: ViewType) => setActiveView(view as MainViewType),
    togglePanel: (panel) => togglePanel(panel as PanelType),
    refreshPreview,
  });

  if (!project) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-gray-400">Loading project...</div>
      </div>
    );
  }

  const leftSidebarItems = [
    {
      icon: <Monitor size={18} />,
      title: 'Preview',
      onClick: () => setActiveView('preview'),
      active: activeView === 'preview',
    },
    {
      icon: <Code size={18} />,
      title: 'Code',
      onClick: () => setActiveView('code'),
      active: activeView === 'code',
    },
    {
      icon: <Kanban size={18} />,
      title: 'Kanban Board',
      onClick: () => setActiveView('kanban'),
      active: activeView === 'kanban',
    },
    {
      icon: <Image size={18} />,
      title: 'Assets',
      onClick: () => setActiveView('assets'),
      active: activeView === 'assets',
    },
    {
      icon: <Terminal size={18} />,
      title: 'Terminal',
      onClick: () => setActiveView('terminal'),
      active: activeView === 'terminal',
    },
  ];

  const rightSidebarItems = [
    {
      icon: <BookOpen size={18} />,
      title: 'Notes',
      onClick: () => togglePanel('notes'),
      active: activePanel === 'notes',
    },
    {
      icon: <GitBranch size={18} />,
      title: 'GitHub Sync',
      onClick: () => togglePanel('github'),
      active: activePanel === 'github',
    },
    {
      icon: <Storefront size={18} />,
      title: 'Agents',
      onClick: () => window.open('/marketplace', '_blank'),
    },
    {
      icon: <Article size={18} />,
      title: 'Documentation',
      onClick: () => window.open('https://docs.tesslate.com', '_blank'),
    },
    {
      icon: <Gear size={18} />,
      title: 'Settings',
      onClick: () => togglePanel('settings'),
      active: activePanel === 'settings',
    },
    {
      icon: <ShareNetwork size={18} />,
      title: 'Share',
      onClick: () => toast('Share feature coming soon!', { icon: '🔗' }),
    },
  ];

  return (
    <div className="h-screen flex overflow-hidden bg-[var(--bg)]">
      {/* Mobile Warning */}
      <MobileWarning />

      {/* Mobile Menu - Shows on mobile only */}
      <MobileMenu leftItems={leftSidebarItems} rightItems={rightSidebarItems} />

      {/* Fixed Left Sidebar */}
      <motion.div
        initial={false}
        animate={{ width: isLeftSidebarExpanded ? 192 : 48 }}
        transition={{
          type: 'spring',
          stiffness: 700,
          damping: 28,
          mass: 0.4,
        }}
        className="hidden md:flex flex-col bg-[var(--surface)] border-r border-[var(--sidebar-border)] overflow-x-hidden"
      >
        {/* Tesslate Logo */}
        <div
          className={`flex items-center h-12 flex-shrink-0 ${isLeftSidebarExpanded ? 'px-3 gap-3' : 'justify-center'} border-b border-[var(--sidebar-border)]`}
        >
          <svg className="w-5 h-5 text-[var(--primary)] flex-shrink-0" viewBox="0 0 161.9 126.66">
            <path
              d="m13.45,46.48h54.06c10.21,0,16.68-10.94,11.77-19.89l-9.19-16.75c-2.36-4.3-6.87-6.97-11.77-6.97H22.41c-4.95,0-9.5,2.73-11.84,7.09L1.61,26.71c-4.79,8.95,1.69,19.77,11.84,19.77Z"
              fill="currentColor"
            />
            <path
              d="m61.05,119.93l26.95-46.86c5.09-8.85-1.17-19.91-11.37-20.12l-19.11-.38c-4.9-.1-9.47,2.48-11.91,6.73l-17.89,31.12c-2.47,4.29-2.37,9.6.25,13.8l10.05,16.13c5.37,8.61,17.98,8.39,23.04-.41Z"
              fill="currentColor"
            />
            <path
              d="m148.46,0h-54.06c-10.21,0-16.68,10.94-11.77,19.89l9.19,16.75c2.36,4.3,6.87,6.97,11.77,6.97h35.9c4.95,0,9.5-2.73,11.84-7.09l8.97-16.75C165.08,10.82,158.6,0,148.46,0Z"
              fill="currentColor"
            />
          </svg>
          {isLeftSidebarExpanded && (
            <span className="text-lg font-bold text-[var(--text)]">Tesslate</span>
          )}
        </div>

        <div className="py-3 gap-1 flex flex-col flex-1 overflow-y-auto overflow-x-hidden">
          {/* Back Button */}
          {isLeftSidebarExpanded ? (
            <button
              onClick={() => navigate('/dashboard')}
              className="group flex items-center h-9 hover:bg-[var(--sidebar-hover)] transition-colors flex-shrink-0 gap-3 rounded-lg mx-2 px-3"
            >
              <ArrowLeft
                size={18}
                className="text-[var(--text)]/40 group-hover:text-[var(--text)] transition-colors"
              />
              <span className="text-sm font-medium text-[var(--text)]">Back to Projects</span>
            </button>
          ) : (
            <Tooltip content="Back to Projects" side="right" delay={200}>
              <button
                onClick={() => navigate('/dashboard')}
                className="group flex items-center justify-center h-9 hover:bg-[var(--sidebar-hover)] transition-colors w-full flex-shrink-0"
              >
                <ArrowLeft
                  size={18}
                  className="text-[var(--text)]/40 group-hover:text-[var(--text)] transition-colors"
                />
              </button>
            </Tooltip>
          )}

          <div className="h-px bg-[var(--sidebar-border)] my-1 mx-2 flex-shrink-0" />

          {/* Main View Toggles */}
          {leftSidebarItems.map((item, index) =>
            isLeftSidebarExpanded ? (
              <button
                key={index}
                onClick={item.onClick}
                className={`group flex items-center h-9 transition-colors flex-shrink-0 gap-3 rounded-lg mx-2 px-3 ${
                  item.active ? 'bg-[var(--sidebar-active)]' : 'hover:bg-[var(--sidebar-hover)]'
                }`}
              >
                {React.cloneElement(item.icon, {
                  className: `transition-colors ${
                    item.active
                      ? 'text-[var(--text)]'
                      : 'text-[var(--text)]/40 group-hover:text-[var(--text)]'
                  }`,
                })}
                <span className="text-sm font-medium text-[var(--text)]">{item.title}</span>
              </button>
            ) : (
              <Tooltip key={index} content={item.title} side="right" delay={200}>
                <button
                  onClick={item.onClick}
                  className={`group flex items-center justify-center h-9 transition-colors w-full flex-shrink-0 ${
                    item.active ? 'bg-[var(--sidebar-active)]' : 'hover:bg-[var(--sidebar-hover)]'
                  }`}
                >
                  {React.cloneElement(item.icon, {
                    className: `transition-colors ${
                      item.active
                        ? 'text-[var(--text)]'
                        : 'text-[var(--text)]/40 group-hover:text-[var(--text)]'
                    }`,
                  })}
                </button>
              </Tooltip>
            )
          )}

          <div className="h-px bg-[var(--sidebar-border)] my-1 mx-2 flex-shrink-0" />

          {/* Settings & Tools */}
          {rightSidebarItems.map((item, index) =>
            isLeftSidebarExpanded ? (
              <button
                key={index}
                onClick={item.onClick}
                className={`group flex items-center h-9 transition-colors flex-shrink-0 gap-3 rounded-lg mx-2 px-3 ${
                  item.active ? 'bg-[var(--sidebar-active)]' : 'hover:bg-[var(--sidebar-hover)]'
                }`}
              >
                {React.cloneElement(item.icon, {
                  className: `transition-colors ${
                    item.active
                      ? 'text-[var(--text)]'
                      : 'text-[var(--text)]/40 group-hover:text-[var(--text)]'
                  }`,
                })}
                <span className="text-sm font-medium text-[var(--text)]">{item.title}</span>
              </button>
            ) : (
              <Tooltip key={index} content={item.title} side="right" delay={200}>
                <button
                  onClick={item.onClick}
                  className={`group flex items-center justify-center h-9 transition-colors w-full flex-shrink-0 ${
                    item.active ? 'bg-[var(--sidebar-active)]' : 'hover:bg-[var(--sidebar-hover)]'
                  }`}
                >
                  {React.cloneElement(item.icon, {
                    className: `transition-colors ${
                      item.active
                        ? 'text-[var(--text)]'
                        : 'text-[var(--text)]/40 group-hover:text-[var(--text)]'
                    }`,
                  })}
                </button>
              </Tooltip>
            )
          )}

          {/* Spacer to push collapse button to bottom */}
          <div className="flex-1" />

          <div className="h-px bg-[var(--sidebar-border)] my-1 mx-2 flex-shrink-0" />

          {/* Collapse/Expand Toggle */}
          {isLeftSidebarExpanded ? (
            <button
              onClick={() => setIsLeftSidebarExpanded(false)}
              className="group flex items-center h-9 hover:bg-[var(--sidebar-hover)] transition-colors flex-shrink-0 gap-3 rounded-lg mx-2 px-3"
            >
              <List
                size={18}
                weight="bold"
                className="text-[var(--text)]/40 group-hover:text-[var(--text)] transition-colors"
              />
              <span className="text-sm font-medium text-[var(--text)]">Collapse</span>
            </button>
          ) : (
            <Tooltip content="Expand" side="right" delay={200}>
              <button
                onClick={() => setIsLeftSidebarExpanded(true)}
                className="group flex items-center justify-center h-9 hover:bg-[var(--sidebar-hover)] transition-colors w-full flex-shrink-0"
              >
                <List
                  size={18}
                  weight="bold"
                  className="text-[var(--text)]/40 group-hover:text-[var(--text)] transition-colors"
                />
              </button>
            </Tooltip>
          )}
        </div>
      </motion.div>

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Top Bar with Project Title */}
        <div className="h-12 bg-[var(--surface)] border-b border-[var(--sidebar-border)] flex items-center justify-between px-4 md:px-6">
          <div className="flex items-center gap-4">
            <Breadcrumbs
              items={[
                { label: 'Projects', href: '/dashboard' },
                { label: project.name, href: `/project/${slug}` },
                { label: 'Builder' },
              ]}
            />

            {/* Container Selector */}
            {containers.length > 0 && (
              <div className="hidden md:flex items-center border-l border-white/10 pl-4">
                <ContainerSelector
                  containers={containers.map((c) => ({
                    id: c.id as string,
                    name: c.name as string,
                    status: c.status as string,
                    base: c.base as { slug: string; name: string } | undefined,
                  }))}
                  currentContainerId={containerId || (container?.id as string)}
                  onChange={(id) => navigate(`/project/${slug}/builder?container=${id}`)}
                  onOpenArchitecture={() => navigate(`/project/${slug}`)}
                />
              </div>
            )}
          </div>

          <div className="flex items-center gap-3">
            {/* Architecture Button (Beta) */}
            <button
              onClick={() => navigate(`/project/${slug}`)}
              className="hidden md:flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-white/5 transition-colors"
            >
              <FlowArrow size={18} className="text-[var(--text)]" />
              <span className="text-sm font-medium text-[var(--text)]">Architecture</span>
              <span className="text-xs px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-400 font-medium">
                Beta
              </span>
            </button>

            {/* Deploy Button with Dropdown */}
            <div className="relative hidden md:block">
              <button
                onClick={() => setShowDeploymentsDropdown(!showDeploymentsDropdown)}
                className="flex items-center gap-2 bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white px-4 py-2 rounded-lg font-semibold transition-all text-sm"
              >
                <Rocket size={16} weight="bold" />
                Deploy
              </button>
              <DeploymentsDropdown
                projectSlug={slug!}
                isOpen={showDeploymentsDropdown}
                onClose={() => setShowDeploymentsDropdown(false)}
                onOpenDeployModal={() => setShowDeployModal(true)}
              />
            </div>

            {/* User Dropdown */}
            <UserDropdown />

            {/* Mobile hamburger menu */}
            <button
              onClick={() => window.dispatchEvent(new Event('toggleMobileMenu'))}
              className="md:hidden p-2 hover:bg-[var(--sidebar-hover)] active:bg-[var(--sidebar-active)] rounded-lg transition-colors"
              aria-label="Open menu"
            >
              <svg
                className="w-6 h-6 text-[var(--text)]"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M4 6h16M4 12h16M4 18h16"
                />
              </svg>
            </button>
          </div>
        </div>

        {/* Main View Container - uses react-resizable-panels only when chat is docked */}
        <div className="flex-1 flex overflow-hidden bg-[var(--bg)]">
          {/* Desktop layout - conditionally use PanelGroup only when chat is docked */}
          <div className="hidden md:flex w-full h-full">
            {/* DOCKED CHAT LAYOUT: Use PanelGroup for resizable panels */}
            {(chatPosition === 'left' || chatPosition === 'right') && agents.length > 0 ? (
              <PanelGroup orientation="horizontal">
                {/* LEFT DOCKED CHAT */}
                {chatPosition === 'left' && (
                  <>
                    <Panel
                      id="chat-left"
                      defaultSize="30"
                      minSize="20"
                      maxSize="50"
                      className="bg-[var(--bg-dark)] overflow-hidden"
                    >
                      <ChatContainer
                        projectId={project?.id}
                        containerId={containerId || undefined}
                        viewContext="builder"
                        agents={agents}
                        currentAgent={currentAgent}
                        onSelectAgent={handleAgentSelect}
                        onFileUpdate={handleFileUpdate}
                        projectFiles={files}
                        projectName={project?.name}
                        sidebarExpanded={isLeftSidebarExpanded}
                        isDocked={true}
                        isPointerOverPreviewRef={isPointerOverPreviewRef}
                      />
                    </Panel>
                    <PanelResizeHandle className="w-2 bg-transparent cursor-col-resize [&[data-separator='hover']]:bg-[var(--primary)]/20 [&[data-separator='active']]:bg-[var(--primary)]/40" />
                  </>
                )}

                {/* MAIN CONTENT PANEL (inside PanelGroup) */}
                <Panel id="content" minSize="30" className="overflow-hidden">
                  {/* Preview View */}
                  <div className={`w-full h-full ${activeView === 'preview' ? 'block' : 'hidden'}`}>
                    {containerStartup.isLoading || containerStartup.status === 'error' ? (
                      <ContainerLoadingOverlay
                        phase={containerStartup.phase}
                        progress={containerStartup.progress}
                        message={containerStartup.message}
                        logs={containerStartup.logs}
                        error={containerStartup.error || undefined}
                        onRetry={containerStartup.retry}
                      />
                    ) : devServerUrl ? (
                      previewMode === 'browser-tabs' ? (
                        <BrowserPreview
                          devServerUrl={devServerUrl}
                          devServerUrlWithAuth={devServerUrlWithAuth || devServerUrl}
                          currentPreviewUrl={currentPreviewUrl}
                          onNavigateBack={navigateBack}
                          onNavigateForward={navigateForward}
                          onRefresh={refreshPreview}
                          onUrlChange={setCurrentPreviewUrl}
                          containerStatus={containerStartup.status}
                          startupPhase={containerStartup.phase}
                          startupProgress={containerStartup.progress}
                          startupMessage={containerStartup.message}
                          startupLogs={containerStartup.logs}
                          startupError={containerStartup.error || undefined}
                          onRetryStart={containerStartup.retry}
                        />
                      ) : (
                        <>
                          <div className="bg-[var(--surface)] border-b border-[var(--sidebar-border)] p-2 md:p-3 flex items-center gap-2 md:gap-3">
                            <div className="flex items-center gap-1">
                              <button
                                onClick={navigateBack}
                                className="p-1.5 md:p-2 hover:bg-[var(--sidebar-hover)] active:bg-[var(--sidebar-active)] rounded-lg transition-colors text-[var(--text)]/60 hover:text-[var(--text)]"
                                title="Go back"
                              >
                                <CaretLeft size={18} weight="bold" />
                              </button>
                              <button
                                onClick={navigateForward}
                                className="p-1.5 md:p-2 hover:bg-[var(--sidebar-hover)] active:bg-[var(--sidebar-active)] rounded-lg transition-colors text-[var(--text)]/60 hover:text-[var(--text)]"
                                title="Go forward"
                              >
                                <CaretRight size={18} weight="bold" />
                              </button>
                            </div>
                            <div className="hidden md:block flex-1">
                              <div className="bg-[var(--text)]/5 rounded-lg px-4 py-2 text-sm text-[var(--text)]/60 font-mono flex items-center border border-[var(--border-color)] overflow-hidden">
                                <span className="text-yellow-500 mr-2">🔒</span>
                                <span className="text-[var(--text)]/80 truncate">
                                  {currentPreviewUrl || devServerUrl}
                                </span>
                              </div>
                            </div>
                            <button
                              onClick={refreshPreview}
                              className="p-1.5 md:p-2 hover:bg-[var(--sidebar-hover)] active:bg-[var(--sidebar-active)] rounded-lg transition-colors text-[var(--text)]/60 hover:text-[var(--text)] ml-auto"
                              title="Refresh"
                            >
                              <ArrowsClockwise size={16} />
                            </button>
                          </div>
                          <div
                            className="w-full h-[calc(100%-50px)] bg-white"
                            onMouseEnter={() => {
                              isPointerOverPreviewRef.current = true;
                            }}
                            onMouseLeave={() => {
                              isPointerOverPreviewRef.current = false;
                            }}
                          >
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
                        <LoadingSpinner message="Loading project..." size={60} />
                      </div>
                    )}
                  </div>

                  {/* Code View */}
                  <div
                    className={`w-full h-full ${activeView === 'code' ? 'flex' : 'hidden'} flex-col overflow-hidden`}
                  >
                    <CodeEditor
                      projectId={project?.id}
                      files={files}
                      onFileUpdate={handleFileUpdate}
                    />
                  </div>

                  {/* Kanban View */}
                  {kanbanMounted && project?.id && (
                    <div
                      className={`w-full h-full ${activeView === 'kanban' ? 'block' : 'hidden'}`}
                    >
                      <KanbanPanel projectId={project.id as string} />
                    </div>
                  )}

                  {/* Assets View */}
                  <div className={`w-full h-full ${activeView === 'assets' ? 'block' : 'hidden'}`}>
                    <AssetsPanel projectSlug={slug!} />
                  </div>

                  {/* Terminal View */}
                  <div
                    className={`w-full h-full ${activeView === 'terminal' ? 'block' : 'hidden'}`}
                  >
                    <TerminalPanel projectId={slug!} containerId={containerId || undefined} />
                  </div>
                </Panel>

                {/* RIGHT DOCKED CHAT */}
                {chatPosition === 'right' && (
                  <>
                    <PanelResizeHandle className="w-2 bg-transparent cursor-col-resize [&[data-separator='hover']]:bg-[var(--primary)]/20 [&[data-separator='active']]:bg-[var(--primary)]/40" />
                    <Panel
                      id="chat-right"
                      defaultSize="30"
                      minSize="20"
                      maxSize="50"
                      className="bg-[var(--bg-dark)] overflow-hidden"
                    >
                      <ChatContainer
                        projectId={project?.id}
                        containerId={containerId || undefined}
                        viewContext="builder"
                        agents={agents}
                        currentAgent={currentAgent}
                        onSelectAgent={handleAgentSelect}
                        onFileUpdate={handleFileUpdate}
                        projectFiles={files}
                        projectName={project?.name}
                        sidebarExpanded={isLeftSidebarExpanded}
                        isDocked={true}
                        isPointerOverPreviewRef={isPointerOverPreviewRef}
                      />
                    </Panel>
                  </>
                )}
              </PanelGroup>
            ) : (
              /* CENTER MODE: No PanelGroup wrapper - direct content for better performance */
              <div className="w-full h-full overflow-hidden">
                {/* Preview View */}
                <div className={`w-full h-full ${activeView === 'preview' ? 'block' : 'hidden'}`}>
                  {containerStartup.isLoading || containerStartup.status === 'error' ? (
                    <ContainerLoadingOverlay
                      phase={containerStartup.phase}
                      progress={containerStartup.progress}
                      message={containerStartup.message}
                      logs={containerStartup.logs}
                      error={containerStartup.error || undefined}
                      onRetry={containerStartup.retry}
                    />
                  ) : devServerUrl ? (
                    previewMode === 'browser-tabs' ? (
                      <BrowserPreview
                        devServerUrl={devServerUrl}
                        devServerUrlWithAuth={devServerUrlWithAuth || devServerUrl}
                        currentPreviewUrl={currentPreviewUrl}
                        onNavigateBack={navigateBack}
                        onNavigateForward={navigateForward}
                        onRefresh={refreshPreview}
                        onUrlChange={setCurrentPreviewUrl}
                        containerStatus={containerStartup.status}
                        startupPhase={containerStartup.phase}
                        startupProgress={containerStartup.progress}
                        startupMessage={containerStartup.message}
                        startupLogs={containerStartup.logs}
                        startupError={containerStartup.error || undefined}
                        onRetryStart={containerStartup.retry}
                      />
                    ) : (
                      <>
                        <div className="bg-[var(--surface)] border-b border-[var(--sidebar-border)] p-2 md:p-3 flex items-center gap-2 md:gap-3">
                          <div className="flex items-center gap-1">
                            <button
                              onClick={navigateBack}
                              className="p-1.5 md:p-2 hover:bg-[var(--sidebar-hover)] active:bg-[var(--sidebar-active)] rounded-lg transition-colors text-[var(--text)]/60 hover:text-[var(--text)]"
                              title="Go back"
                            >
                              <CaretLeft size={18} weight="bold" />
                            </button>
                            <button
                              onClick={navigateForward}
                              className="p-1.5 md:p-2 hover:bg-[var(--sidebar-hover)] active:bg-[var(--sidebar-active)] rounded-lg transition-colors text-[var(--text)]/60 hover:text-[var(--text)]"
                              title="Go forward"
                            >
                              <CaretRight size={18} weight="bold" />
                            </button>
                          </div>
                          <div className="hidden md:block flex-1">
                            <div className="bg-[var(--text)]/5 rounded-lg px-4 py-2 text-sm text-[var(--text)]/60 font-mono flex items-center border border-[var(--border-color)] overflow-hidden">
                              <span className="text-yellow-500 mr-2">🔒</span>
                              <span className="text-[var(--text)]/80 truncate">
                                {currentPreviewUrl || devServerUrl}
                              </span>
                            </div>
                          </div>
                          <button
                            onClick={refreshPreview}
                            className="p-1.5 md:p-2 hover:bg-[var(--sidebar-hover)] active:bg-[var(--sidebar-active)] rounded-lg transition-colors text-[var(--text)]/60 hover:text-[var(--text)] ml-auto"
                            title="Refresh"
                          >
                            <ArrowsClockwise size={16} />
                          </button>
                        </div>
                        <div
                          className="w-full h-[calc(100%-50px)] bg-white"
                          onMouseEnter={() => {
                            isPointerOverPreviewRef.current = true;
                          }}
                          onMouseLeave={() => {
                            isPointerOverPreviewRef.current = false;
                          }}
                        >
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
                      <LoadingSpinner message="Loading project..." size={60} />
                    </div>
                  )}
                </div>

                {/* Code View */}
                <div
                  className={`w-full h-full ${activeView === 'code' ? 'flex' : 'hidden'} flex-col overflow-hidden`}
                >
                  <CodeEditor
                    projectId={project?.id}
                    files={files}
                    onFileUpdate={handleFileUpdate}
                  />
                </div>

                {/* Kanban View */}
                {kanbanMounted && project?.id && (
                  <div className={`w-full h-full ${activeView === 'kanban' ? 'block' : 'hidden'}`}>
                    <KanbanPanel projectId={project.id as string} />
                  </div>
                )}

                {/* Assets View */}
                <div className={`w-full h-full ${activeView === 'assets' ? 'block' : 'hidden'}`}>
                  <AssetsPanel projectSlug={slug!} />
                </div>

                {/* Terminal View */}
                <div className={`w-full h-full ${activeView === 'terminal' ? 'block' : 'hidden'}`}>
                  <TerminalPanel projectId={slug!} containerId={containerId || undefined} />
                </div>
              </div>
            )}
          </div>

          {/* Mobile layout - simple full width content */}
          <div className="md:hidden w-full h-full overflow-hidden">
            {/* Preview View */}
            <div className={`w-full h-full ${activeView === 'preview' ? 'block' : 'hidden'}`}>
              {containerStartup.isLoading || containerStartup.status === 'error' ? (
                <ContainerLoadingOverlay
                  phase={containerStartup.phase}
                  progress={containerStartup.progress}
                  message={containerStartup.message}
                  logs={containerStartup.logs}
                  error={containerStartup.error || undefined}
                  onRetry={containerStartup.retry}
                />
              ) : devServerUrl ? (
                <div className="w-full h-full bg-white">
                  <iframe
                    src={devServerUrlWithAuth || devServerUrl}
                    className="w-full h-full"
                    sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals"
                  />
                </div>
              ) : (
                <div className="h-full flex items-center justify-center text-[var(--text)]/60">
                  <LoadingSpinner message="Loading project..." size={60} />
                </div>
              )}
            </div>

            {/* Code View */}
            <div
              className={`w-full h-full ${activeView === 'code' ? 'flex' : 'hidden'} flex-col overflow-hidden`}
            >
              <CodeEditor projectId={project?.id} files={files} onFileUpdate={handleFileUpdate} />
            </div>

            {/* Kanban View */}
            {kanbanMounted && project?.id && (
              <div className={`w-full h-full ${activeView === 'kanban' ? 'block' : 'hidden'}`}>
                <KanbanPanel projectId={project.id as string} />
              </div>
            )}

            {/* Assets View */}
            <div className={`w-full h-full ${activeView === 'assets' ? 'block' : 'hidden'}`}>
              <AssetsPanel projectSlug={slug!} />
            </div>

            {/* Terminal View */}
            <div className={`w-full h-full ${activeView === 'terminal' ? 'block' : 'hidden'}`}>
              <TerminalPanel projectId={slug!} containerId={containerId || undefined} />
            </div>
          </div>
        </div>
      </div>

      {/* Floating Panels */}
      <FloatingPanel
        title="GitHub Sync"
        icon={<GitBranch size={20} />}
        isOpen={activePanel === 'github'}
        onClose={() => setActivePanel(null)}
        defaultPosition={{ x: (isLeftSidebarExpanded ? 192 : 48) + 8, y: 60 }}
        defaultSize={{ width: 420, height: 620 }}
      >
        <GitHubPanel projectId={project?.id} />
      </FloatingPanel>

      <FloatingPanel
        title="Notes & Tasks"
        icon={<BookOpen size={20} />}
        isOpen={activePanel === 'notes'}
        onClose={() => setActivePanel(null)}
        defaultPosition={{ x: (isLeftSidebarExpanded ? 192 : 48) + 8, y: 60 }}
      >
        <NotesPanel projectSlug={slug!} />
      </FloatingPanel>

      <FloatingPanel
        title="Settings"
        icon={<Gear size={20} />}
        isOpen={activePanel === 'settings'}
        onClose={() => setActivePanel(null)}
        defaultPosition={{ x: (isLeftSidebarExpanded ? 192 : 48) + 8, y: 60 }}
      >
        <SettingsPanel projectSlug={slug!} />
      </FloatingPanel>

      {/* FLOATING CHAT - Always on mobile, or when chat position is 'center' on desktop */}
      {/* Mobile always uses floating mode; desktop only shows floating when center position */}
      {agents.length > 0 && (
        <div className={chatPosition !== 'center' ? 'md:hidden' : ''}>
          <ChatContainer
            projectId={project?.id}
            containerId={containerId || undefined}
            viewContext="builder"
            agents={agents}
            currentAgent={currentAgent}
            onSelectAgent={handleAgentSelect}
            onFileUpdate={handleFileUpdate}
            projectFiles={files}
            projectName={project?.name}
            sidebarExpanded={isLeftSidebarExpanded}
            isPointerOverPreviewRef={isPointerOverPreviewRef}
          />
        </div>
      )}

      {/* No Agents Empty State */}
      {agents.length === 0 && (
        <div className="fixed inset-0 z-40 flex items-center justify-center pointer-events-none">
          <div className="bg-[var(--surface)] border border-[var(--sidebar-border)] rounded-2xl shadow-2xl p-8 max-w-md pointer-events-auto">
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
                  className="w-full bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white py-3 px-6 rounded-xl font-semibold transition-all flex items-center justify-center gap-2"
                >
                  <Storefront size={20} weight="fill" />
                  Go to Library
                </button>
                <button
                  onClick={() => navigate('/marketplace')}
                  className="w-full bg-[var(--sidebar-hover)] hover:bg-[var(--sidebar-active)] border border-[var(--sidebar-border)] text-[var(--text)] py-3 px-6 rounded-xl font-semibold transition-all flex items-center justify-center gap-2"
                >
                  <Storefront size={20} weight="fill" />
                  Browse Marketplace
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Discord Support - position adjusts when chat is right-docked */}
      <DiscordSupport chatPosition={chatPosition} chatPanelWidth={chatPanelWidth} />

      {/* Deployment Modal */}
      {showDeployModal && (
        <DeploymentModal
          projectSlug={slug!}
          isOpen={showDeployModal}
          onClose={() => setShowDeployModal(false)}
          onSuccess={() => {
            setShowDeployModal(false);
            toast.success('Deployment started successfully!');
          }}
        />
      )}
    </div>
  );
}
