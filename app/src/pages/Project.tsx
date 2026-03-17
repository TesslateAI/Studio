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
  Books,
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
import { StartupLogViewer } from '../components/StartupLogViewer';
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
import { PreviewPortPicker, type PreviewableContainer } from '../components/PreviewPortPicker';
import { projectsApi, marketplaceApi } from '../lib/api';
import { useCommandHandlers, type ViewType } from '../contexts/CommandContext';
import { useChatPosition } from '../contexts/ChatPositionContext';
import toast from 'react-hot-toast';
import { fileEvents } from '../utils/fileEvents';
import { motion } from 'framer-motion';
import { Panel, Group as PanelGroup, Separator as PanelResizeHandle } from 'react-resizable-panels';
import { type ChatAgent } from '../types/chat';
import { getFeatures, type ComputeTier } from '../types/project';
import { getEnvironmentStatus } from '../components/ui/environmentStatus';
import { EnvironmentStatusBadge } from '../components/ui/EnvironmentStatusBadge';
import IdleWarningBanner from '../components/IdleWarningBanner';

type PanelType = 'github' | 'notes' | 'settings' | 'marketplace' | null;
type MainViewType = 'preview' | 'code' | 'kanban' | 'assets' | 'terminal';

// Placeholder for views that require compute (preview, terminal)
interface NoComputePlaceholderProps {
  onStart?: () => void;
  variant: 'terminal' | 'preview';
  computeTier?: ComputeTier;
  isStarting?: boolean;
  startupProgress?: number;
  startupMessage?: string;
  startupLogs?: string[];
  startupError?: string;
  onRetry?: () => void;
  onAskAgent?: (msg: string) => void;
  containerPort?: number;
}

function NoComputePlaceholder({
  onStart,
  variant,
  computeTier,
  isStarting,
  startupProgress,
  startupMessage,
  startupLogs,
  startupError,
  onRetry,
  onAskAgent,
  containerPort = 3000,
}: NoComputePlaceholderProps) {
  const accessLabel = variant === 'terminal' ? 'terminal access' : 'live preview';

  // Starting state — show progress + logs
  if (isStarting) {
    // Error during startup
    if (startupError) {
      const isHealthCheck = startupError.startsWith('HEALTH_CHECK_TIMEOUT:');
      const displayError = isHealthCheck
        ? startupError.replace('HEALTH_CHECK_TIMEOUT:', '')
        : startupError;
      return (
        <div className="h-full flex flex-col items-center justify-center bg-[var(--bg)] p-6">
          <div className="flex flex-col items-center gap-4 max-w-lg text-center">
            <div className="w-16 h-16 rounded-full bg-red-500/20 flex items-center justify-center">
              <Terminal size={32} className="text-red-400" />
            </div>
            <h3 className="text-lg font-semibold text-[var(--text)]">
              {isHealthCheck ? 'Container needs setup' : 'Failed to Start'}
            </h3>
            <p className="text-[var(--text)]/60 text-sm">{displayError}</p>

            <div className="flex items-center gap-3">
              {onAskAgent && isHealthCheck && (
                <button
                  onClick={() =>
                    onAskAgent(
                      `Use the running tmux process to get this up and running. The port for the preview url is ${containerPort}.`
                    )
                  }
                  className="flex items-center gap-2 px-4 py-2 bg-[var(--primary)] text-white rounded-lg hover:bg-[var(--primary)]/80 transition-colors text-sm font-medium"
                >
                  Ask Agent
                </button>
              )}
              {onRetry && (
                <button
                  onClick={onRetry}
                  className="flex items-center gap-2 px-4 py-2 text-[var(--text)]/60 hover:text-[var(--text)] transition-colors text-sm"
                >
                  Retry
                </button>
              )}
            </div>

            {startupLogs && startupLogs.length > 0 && (
              <StartupLogViewer logs={startupLogs.slice(-10)} maxHeight="h-32" />
            )}
          </div>
        </div>
      );
    }

    return (
      <div className="h-full flex flex-col items-center justify-center bg-[var(--bg)] p-6">
        <div className="flex flex-col items-center gap-3 max-w-lg text-center">
          <div className="w-12 h-12 rounded-full bg-[var(--primary)]/10 flex items-center justify-center animate-pulse">
            <Terminal size={24} className="text-[var(--primary)]" />
          </div>
          <p className="text-sm font-medium text-[var(--text)]">Starting compute environment...</p>
          {startupProgress !== undefined && (
            <div className="w-48 h-1.5 bg-[var(--text)]/10 rounded-full overflow-hidden">
              <div
                className="h-full bg-[var(--primary)] rounded-full transition-all"
                style={{ width: `${startupProgress}%` }}
              />
            </div>
          )}
          {startupMessage && <p className="text-xs text-[var(--text)]/50">{startupMessage}</p>}

          {startupLogs && startupLogs.length > 0 && (
            <StartupLogViewer logs={startupLogs} maxHeight="h-36" className="mt-2" />
          )}
        </div>
      </div>
    );
  }

  // Determine icon, title, description, and button label based on state
  let icon = <Monitor size={32} className="text-emerald-400" />;
  let iconBg = 'bg-emerald-500/10';
  let title = 'Files available';
  let description = `Start the environment for ${accessLabel}.`;
  let buttonLabel = 'Start Environment';

  if (computeTier === 'ephemeral') {
    icon = <Terminal size={32} className="text-[var(--primary)]" />;
    iconBg = 'bg-[var(--primary)]/10';
    title = 'Agent commands running';
    description = `Start full environment for ${accessLabel}.`;
    buttonLabel = 'Start Environment';
  }

  return (
    <div className="h-full flex flex-col items-center justify-center bg-[var(--bg)] p-6">
      <div className="flex flex-col items-center gap-4 max-w-md text-center">
        <div className={`w-16 h-16 rounded-full ${iconBg} flex items-center justify-center`}>
          {icon}
        </div>
        <h3 className="text-lg font-semibold text-[var(--text)]">{title}</h3>
        <p className="text-[var(--text)]/60 text-sm">{description}</p>
        {onStart && buttonLabel && (
          <button
            onClick={onStart}
            className="px-5 py-2.5 bg-[var(--primary)] text-white rounded-lg hover:opacity-80 transition font-medium"
          >
            {buttonLabel}
          </button>
        )}
      </div>
    </div>
  );
}

export default function Project() {
  const { slug } = useParams<{ slug: string }>();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const containerId = searchParams.get('container');

  const { chatPosition } = useChatPosition();
  const [project, setProject] = useState<Record<string, unknown> | null>(null);
  const [fileTree, setFileTree] = useState<
    Array<{ path: string; name: string; is_dir: boolean; size: number; mod_time: number }>
  >([]);
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
  const [prefillChatMessage, setPrefillChatMessage] = useState<string | null>(null);
  const [chatExpanded, setChatExpanded] = useState(false);

  // Preview port picker state
  const [previewableContainers, setPreviewableContainers] = useState<PreviewableContainer[]>([]);
  const [selectedPreviewContainerId, setSelectedPreviewContainerId] = useState<string | null>(null);

  const [filesInitiallyLoaded, setFilesInitiallyLoaded] = useState(false);
  const fileRetryRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const fileRetryCountRef = useRef(0);
  const fileRetryCancelledRef = useRef(false);

  const refreshTimeoutRef = React.useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const iframeRef = React.useRef<HTMLIFrameElement>(null);
  const isPointerOverPreviewRef = useRef(false);

  // Stable ref to the latest loadFiles so event listeners never capture a stale closure
  const loadFilesRef = useRef<() => Promise<void>>(() => Promise.resolve());

  // Track if we need to start the container (for the startup hook)
  const [needsContainerStart, setNeedsContainerStart] = useState(false);
  const currentContainerIdRef = useRef<string | null>(null);

  // Idle warning state (set by WebSocket idle_warning event)
  const [idleWarningMinutes, setIdleWarningMinutes] = useState<number | null>(null);
  // Environment stopping state (set by WebSocket environment_stopping event)
  const [environmentStopping, setEnvironmentStopping] = useState(false);

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
        // Re-fetch project to pick up updated compute_tier (enables preview/terminal gates)
        if (slug) {
          projectsApi
            .get(slug)
            .then((p) => setProject(p))
            .catch(() => {});
        }
        // Container just became ready - load files with retry (pod may still be warming up)
        fileRetryCancelledRef.current = true;
        if (fileRetryRef.current) clearTimeout(fileRetryRef.current);
        fileRetryCountRef.current = 0;
        loadFilesWithRetry();
        // Refresh previewable containers now that container(s) are running
        if (slug) {
          Promise.all([projectsApi.getContainers(slug), projectsApi.getContainersStatus(slug)])
            .then(([allContainers, status]) => {
              const statusContainers = status?.containers ?? null;
              const primaryId = currentContainerIdRef.current;
              const previewable = buildPreviewableContainers(
                allContainers,
                statusContainers,
                primaryId
              );
              setPreviewableContainers(previewable);
              if (previewable.length > 0) {
                setSelectedPreviewContainerId((prev) => prev || previewable[0].id);
              }
            })
            .catch(() => {
              /* non-blocking */
            });
        }
      },
      onError: (error) => {
        setNeedsContainerStart(false);
        toast.error(`Container failed: ${error}`, { id: 'container-start' });
      },
    }
  );

  // ============================================================================
  // TWO-AXIS STATE MODEL
  // ============================================================================
  const computeTier = (project?.compute_tier as ComputeTier) ?? 'none';
  const features = useMemo(() => getFeatures(computeTier), [computeTier]);
  const noPreview = !features.preview && !devServerUrl;
  const hasFiles = features.fileBrowser;

  const environmentStatus = useMemo(
    () =>
      getEnvironmentStatus(computeTier, {
        stopping: environmentStopping,
        starting: needsContainerStart && containerStartup.isLoading,
      }),
    [computeTier, environmentStopping, needsContainerStart, containerStartup.isLoading]
  );

  const handleStartCompute = useCallback(() => {
    if (!container) {
      toast.error('No container found — project may still be loading');
      return;
    }
    currentContainerIdRef.current = container.id as string;
    setNeedsContainerStart(true);
    toast.loading('Starting environment...', { id: 'container-start' });
    containerStartup.startContainer(container.id as string);
  }, [container, containerStartup]);

  // ============================================================================
  // LIFECYCLE EVENT HANDLERS (idle warning, environment stopped, volume restore)
  // ============================================================================

  const handleIdleWarning = useCallback((minutesLeft: number) => {
    setIdleWarningMinutes(minutesLeft);
  }, []);

  const handleEnvironmentStopping = useCallback(() => {
    setEnvironmentStopping(true);
  }, []);

  const handleEnvironmentStopped = useCallback(
    (reason: string) => {
      setEnvironmentStopping(false);
      setIdleWarningMinutes(null);
      // Refresh project to pick up compute_tier=none changes
      if (slug) {
        projectsApi
          .get(slug)
          .then((p) => setProject(p))
          .catch(() => {});
      }
      if (reason === 'idle_timeout') {
        toast('Environment stopped due to inactivity', { icon: '\u23F8\uFE0F', duration: 5000 });
      }
    },
    [slug]
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
      // Reset file sync state for the new project
      setFilesInitiallyLoaded(false);
      fileRetryCancelledRef.current = true;
      if (fileRetryRef.current) clearTimeout(fileRetryRef.current);
      fileRetryCountRef.current = 0;

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
      // If no container specified in URL, restore last-viewed container
      if (!containerId) {
        const savedContainerId = localStorage.getItem(`tesslate-container-${slug}`);
        if (savedContainerId) {
          navigate(`/project/${slug}/builder?container=${savedContainerId}`, { replace: true });
          return; // Navigation will re-trigger this effect with the containerId
        }
      }
      loadContainer();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [containerId, slug]);

  // Reload files when container changes (to apply filtering)
  useEffect(() => {
    if (container) {
      if (project?.volume_id) return; // v2 project — files already loaded via loadProject
      // Cancel any in-flight retry sequence before starting a new one
      fileRetryCancelledRef.current = true;
      if (fileRetryRef.current) clearTimeout(fileRetryRef.current);
      fileRetryCountRef.current = 0;
      setFilesInitiallyLoaded(false);
      loadFilesWithRetry();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [container, project?.volume_id]);

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
      if (fileRetryRef.current) {
        clearTimeout(fileRetryRef.current);
      }
      fileRetryCancelledRef.current = true;
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

  // Listen for file change events from Assets panel and other components.
  // Uses loadFilesRef to always call the latest loadFiles (with correct container
  // context), avoiding a stale closure that would skip prefix filtering and
  // corrupt the file tree with raw server paths.
  useEffect(() => {
    const unsubscribe = fileEvents.on((detail) => {
      console.log('File event received:', detail.type, detail.filePath);
      if (detail.type !== 'file-updated') {
        loadFilesRef.current();
      }
    });

    return () => {
      unsubscribe();
    };
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
      // Poll every 60 seconds - tree metadata only, cheap
      pollInterval = setInterval(() => {
        if (isTabVisible && slug) {
          loadFileTree();
        }
      }, 60000);
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

  // Refresh file tree when switching to code view
  useEffect(() => {
    if (activeView === 'code' && slug) {
      loadFileTree();
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

      // Hub always has canonical data — files are always loadable
      loadFilesWithRetry();
    } catch (error) {
      console.error('Failed to load project:', error);
      toast.error('Failed to load project');
    }
  };

  const loadFileTree = async () => {
    if (!slug) return;
    try {
      const containerDir = (container as Record<string, unknown> | null)?.directory as
        | string
        | undefined;
      const entries = await projectsApi.getFileTree(slug, containerDir);
      setFileTree((prev) => {
        // Skip update if paths haven't changed — prevents re-renders from polling.
        const prevPaths = prev.map((f) => f.path).join('\0');
        const newPaths = entries.map((f) => f.path).join('\0');
        if (prevPaths === newPaths) return prev;
        return entries;
      });
    } catch (error) {
      console.error('Failed to load file tree:', error);
    }
  };
  // Keep ref in sync so event listeners never use a stale closure
  loadFilesRef.current = loadFileTree;

  const FILE_RETRY_MAX = 8;

  const loadFilesWithRetry = async () => {
    if (!slug) return;

    // Mark this retry sequence as active
    fileRetryCancelledRef.current = false;

    try {
      const containerDir = (container as Record<string, unknown> | null)?.directory as
        | string
        | undefined;
      const entries = await projectsApi.getFileTree(slug, containerDir);

      // Bail if this sequence was cancelled while the request was in-flight
      if (fileRetryCancelledRef.current) return;

      if (entries.length > 0) {
        setFileTree(entries);
        setFilesInitiallyLoaded(true);
        fileRetryCountRef.current = 0;
        return;
      }

      // Empty result - retry with backoff
      if (fileRetryCountRef.current < FILE_RETRY_MAX) {
        const delay = Math.min((fileRetryCountRef.current + 1) * 1000, 5000);
        fileRetryCountRef.current += 1;
        fileRetryRef.current = setTimeout(() => {
          loadFilesWithRetry();
        }, delay);
      } else {
        // Exhausted retries - accept empty
        setFileTree([]);
        setFilesInitiallyLoaded(true);
        fileRetryCountRef.current = 0;
      }
    } catch (error) {
      if (fileRetryCancelledRef.current) return;
      console.error('Failed to load file tree (retry):', error);

      if (fileRetryCountRef.current < FILE_RETRY_MAX) {
        const delay = Math.min((fileRetryCountRef.current + 1) * 1000, 5000);
        fileRetryCountRef.current += 1;
        fileRetryRef.current = setTimeout(() => {
          loadFilesWithRetry();
        }, delay);
      } else {
        setFilesInitiallyLoaded(true);
        fileRetryCountRef.current = 0;
      }
    }
  };

  /**
   * Build the list of previewable containers from container metadata + runtime status.
   * Excludes service containers (postgres, redis, etc.) and containers without ports/URLs.
   */
  const buildPreviewableContainers = (
    allContainers: Array<Record<string, unknown>>,
    statusContainers: Record<string, Record<string, unknown>> | null,
    primaryContainerId: string | null
  ): PreviewableContainer[] => {
    const sanitizeKey = (s: string) =>
      s
        .toLowerCase()
        .replace(/[^a-z0-9-]/g, '-')
        .replace(/-+/g, '-')
        .replace(/^-|-$/g, '');

    const previewable: PreviewableContainer[] = [];

    for (const c of allContainers) {
      // Skip service containers (postgres, redis, mongodb, etc.)
      if (c.container_type === 'service') continue;
      // Skip external-only containers
      if (c.deployment_mode === 'external') continue;

      const port = (c.internal_port as number) || (c.port as number);
      if (!port) continue;

      // Try to find runtime URL from status data
      const rawDir = c.directory as string;
      const dirKey = rawDir && rawDir !== '.' ? sanitizeKey(rawDir) : null;
      const nameKey = c.name ? sanitizeKey(c.name as string) : null;
      const runtimeStatus = statusContainers?.[dirKey!] ?? statusContainers?.[nameKey!] ?? null;

      // Only include containers that are running and have a URL
      if (!runtimeStatus?.running || !runtimeStatus?.url) continue;

      previewable.push({
        id: c.id as string,
        name: c.name as string,
        port,
        url: runtimeStatus.url as string,
        isPrimary: (c.id as string) === primaryContainerId,
      });
    }

    // Sort so primary is first
    previewable.sort((a, b) => (a.isPrimary ? -1 : b.isPrimary ? 1 : 0));

    return previewable;
  };

  const handlePreviewContainerSwitch = useCallback((target: PreviewableContainer) => {
    const token = localStorage.getItem('token');
    const deploymentMode = import.meta.env.DEPLOYMENT_MODE || 'docker';

    setSelectedPreviewContainerId(target.id);
    setDevServerUrl(target.url);

    if (token && deploymentMode === 'kubernetes') {
      const urlWithAuth =
        target.url + (target.url.includes('?') ? '&' : '?') + 'auth_token=' + token;
      setDevServerUrlWithAuth(urlWithAuth);
    } else {
      setDevServerUrlWithAuth(target.url);
    }
    setCurrentPreviewUrl(target.url);
  }, []);

  const loadContainer = async () => {
    if (!slug) return;
    try {
      // Fetch fresh project data to avoid stale closure on `project` state
      // (loadProject and loadContainer fire in the same render cycle on mount)
      const freshProject = await projectsApi.get(slug);

      const allContainers = await projectsApi.getContainers(slug);
      setContainers(allContainers);

      // No containers = project needs setup
      if (!allContainers || allContainers.length === 0) {
        navigate(`/project/${slug}/setup`, { replace: true });
        return;
      }

      // Find current container (by ID or default to first)
      const foundContainer = containerId
        ? allContainers.find((c: Record<string, unknown>) => c.id === containerId)
        : allContainers[0];

      if (foundContainer) {
        setContainer(foundContainer);

        // Persist last-viewed container for this project
        if (slug) {
          localStorage.setItem(`tesslate-container-${slug}`, foundContainer.id as string);
        }

        // Check if container is already running before starting
        let status: Record<string, unknown> | null = null;
        try {
          status = await projectsApi.getContainersStatus(slug);

          // Match backend's _sanitize_status_key: replace non-[a-z0-9-] with dash,
          // collapse runs, trim leading/trailing dashes.
          const sanitizeKey = (s: string) =>
            s
              .toLowerCase()
              .replace(/[^a-z0-9-]/g, '-')
              .replace(/-+/g, '-')
              .replace(/^-|-$/g, '');

          const rawDir = foundContainer.directory;
          const dirKey = rawDir && rawDir !== '.' ? sanitizeKey(rawDir) : null;
          const nameKey = foundContainer.name ? sanitizeKey(foundContainer.name as string) : null;

          // Try directory key first, then name key (backend adds aliases for both)
          const containerStatus =
            status?.containers?.[dirKey!] ?? status?.containers?.[nameKey!] ?? null;

          console.log('[loadContainer] status response:', JSON.stringify(status));
          console.log('[loadContainer] dirKey:', dirKey, 'nameKey:', nameKey);
          console.log('[loadContainer] containerStatus:', JSON.stringify(containerStatus));

          // Build previewable containers list from status data
          const statusContainers = status?.containers ?? null;
          const previewable = buildPreviewableContainers(
            allContainers,
            statusContainers,
            foundContainer.id as string
          );
          setPreviewableContainers(previewable);
          // Default to the current/primary container
          if (!selectedPreviewContainerId && previewable.length > 0) {
            setSelectedPreviewContainerId(previewable[0].id);
          }

          // Check for stopping — show badge but don't auto-start
          if (
            status?.environment_status === 'stopping' ||
            freshProject.environment_status === 'stopping'
          ) {
            setEnvironmentStopping(true);
            return;
          }

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
            containerStartup.reset();
            setNeedsContainerStart(false);
            setDevServerUrl(containerStatus.url);
            setDevServerUrlWithAuth(containerStatus.url);
            setCurrentPreviewUrl(containerStatus.url);
            fileRetryCancelledRef.current = true;
            if (fileRetryRef.current) clearTimeout(fileRetryRef.current);
            fileRetryCountRef.current = 0;
            loadFilesWithRetry();
            return;
          }

          // If per-container lookup missed but overall environment is running,
          // try to find any running container entry with a URL as a fallback
          if (
            status?.status === 'running' ||
            status?.status === 'partial' ||
            status?.status === 'active'
          ) {
            const containers = status?.containers ?? {};
            const fallback = Object.values(containers).find(
              (c: Record<string, unknown>) => c.running && c.url
            ) as Record<string, unknown> | undefined;
            if (fallback) {
              console.log(
                '[loadContainer] FAST PATH (fallback): found running container at',
                fallback.url
              );
              containerStartup.reset();
              setNeedsContainerStart(false);
              setDevServerUrl(fallback.url as string);
              setDevServerUrlWithAuth(fallback.url as string);
              setCurrentPreviewUrl(fallback.url as string);
              fileRetryCancelledRef.current = true;
              if (fileRetryRef.current) clearTimeout(fileRetryRef.current);
              fileRetryCountRef.current = 0;
              loadFilesWithRetry();
              return;
            }
          }

          console.log('[loadContainer] SLOW PATH: container not detected as running');
        } catch (statusError) {
          // Status check failed, proceed with start anyway
          console.warn('Failed to check container status, will attempt start:', statusError);
        }

        // Check compute tier before auto-starting
        // Don't interfere with an in-progress startup
        if (needsContainerStart && containerStartup.isLoading) {
          return;
        }
        // Prefer live compute_state from status endpoint over stale DB
        const liveComputeState = status?.compute_state as string | undefined;
        const effectiveComputeTier =
          liveComputeState ?? (freshProject.compute_tier as string) ?? 'none';
        if (effectiveComputeTier !== 'environment') {
          // No environment running — let user decide via Start button
          console.log(
            '[loadContainer] compute state',
            effectiveComputeTier,
            '— skipping container start'
          );
          containerStartup.reset();
          setNeedsContainerStart(false);
          return;
        }
        // compute state is 'environment' — fall through to existing status check

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
        (agent: Record<string, unknown>) =>
          agent.is_enabled && !agent.is_admin_disabled && agent.slug !== 'librarian'
      );

      // Convert backend agents to UI format
      const uiAgents = enabledAgents.map((agent: Record<string, unknown>) => ({
        id: agent.slug as string,
        name: agent.name as string,
        icon: (agent.icon as string) || '🤖',
        avatar_url: (agent.avatar_url as string) || undefined,
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
    return agents[agents.length - 1] ?? null;
  }, [agents, selectedAgentId]);

  const handleAgentSelect = useCallback(
    (agent: ChatAgent) => {
      setSelectedAgentId(agent.id);
      if (slug) localStorage.setItem(`tesslate-agent-${slug}`, agent.id);
    },
    [slug]
  );

  const handleAskAgent = useCallback((message: string) => {
    setPrefillChatMessage(message);
  }, []);

  const previewPlaceholder = (
    <NoComputePlaceholder
      variant="preview"
      computeTier={computeTier}
      onStart={features.startButton && container ? handleStartCompute : undefined}
      isStarting={needsContainerStart && containerStartup.isLoading}
      startupProgress={containerStartup.progress}
      startupMessage={containerStartup.message}
      startupLogs={containerStartup.logs}
      startupError={containerStartup.error || undefined}
      onRetry={containerStartup.retry}
      onAskAgent={handleAskAgent}
      containerPort={(container?.internal_port as number) || 3000}
    />
  );

  const loadingOverlay =
    containerStartup.isLoading || containerStartup.status === 'error' ? (
      <ContainerLoadingOverlay
        phase={containerStartup.phase}
        progress={containerStartup.progress}
        message={containerStartup.message}
        logs={containerStartup.logs}
        error={containerStartup.error || undefined}
        onRetry={containerStartup.retry}
        onAskAgent={handleAskAgent}
        containerPort={(container?.internal_port as number) || 3000}
      />
    ) : null;

  const codeEditorOverlay = hasFiles ? undefined : (loadingOverlay ?? undefined);

  const handleFileUpdate = useCallback(
    async (filePath: string, content: string) => {
      if (!slug) return;

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
              iframe.src =
                currentSrc + (currentSrc.includes('?') ? '&' : '?') + 'hmr_fallback=' + Date.now();
            } catch (error) {
              console.log('Preview refresh error:', error);
            }
          }
        }, 5000);
      }
    },
    [slug]
  );

  const handleFileCreate = useCallback(
    async (filePath: string) => {
      if (!slug) return;
      try {
        await projectsApi.saveFile(slug, filePath, '');
        fileEvents.emit('file-created', filePath);
      } catch (error) {
        console.error('Failed to create file:', error);
        toast.error(`Failed to create ${filePath}`);
      }
    },
    [slug]
  );

  const handleFileDelete = useCallback(
    async (filePath: string, isDirectory: boolean) => {
      if (!slug) return;
      try {
        await projectsApi.deleteFile(slug, filePath, isDirectory);
        fileEvents.emit('file-deleted', filePath);
      } catch (error) {
        console.error('Failed to delete:', error);
        toast.error(`Failed to delete ${filePath}`);
      }
    },
    [slug]
  );

  const handleFileRename = useCallback(
    async (oldPath: string, newPath: string) => {
      if (!slug) return;
      try {
        await projectsApi.renameFile(slug, oldPath, newPath);
        fileEvents.emit('files-changed');
      } catch (error) {
        console.error('Failed to rename:', error);
        toast.error(`Failed to rename ${oldPath}`);
      }
    },
    [slug]
  );

  const handleDirectoryCreate = useCallback(
    async (dirPath: string) => {
      if (!slug) return;
      try {
        await projectsApi.createDirectory(slug, dirPath);
        fileEvents.emit('file-created', dirPath);
      } catch (error) {
        console.error('Failed to create directory:', error);
        toast.error(`Failed to create folder ${dirPath}`);
      }
    },
    [slug]
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
      icon: <Books size={18} />,
      title: 'Library',
      onClick: () => navigate('/library'),
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
      onClick: () => toast('Share feature coming soon!'),
      disabled: true,
    },
  ];

  return (
    <div className="h-screen flex overflow-hidden bg-[var(--bg)]">
      {/* Idle Warning Banner */}
      {idleWarningMinutes !== null && slug && (
        <IdleWarningBanner
          minutesLeft={idleWarningMinutes}
          projectSlug={slug}
          onDismiss={() => setIdleWarningMinutes(null)}
        />
      )}

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
                onClick={item.disabled ? undefined : item.onClick}
                disabled={item.disabled}
                className={`group flex items-center h-9 transition-colors flex-shrink-0 gap-3 rounded-lg mx-2 px-3 ${
                  item.disabled
                    ? 'opacity-40 cursor-not-allowed'
                    : item.active
                      ? 'bg-[var(--sidebar-active)]'
                      : 'hover:bg-[var(--sidebar-hover)]'
                }`}
              >
                {React.cloneElement(item.icon, {
                  className: `transition-colors ${
                    item.disabled
                      ? 'text-[var(--text)]/40'
                      : item.active
                        ? 'text-[var(--text)]'
                        : 'text-[var(--text)]/40 group-hover:text-[var(--text)]'
                  }`,
                })}
                <span className="text-sm font-medium text-[var(--text)]">{item.title}</span>
              </button>
            ) : (
              <Tooltip
                key={index}
                content={item.disabled ? `${item.title} (Coming soon)` : item.title}
                side="right"
                delay={200}
              >
                <button
                  onClick={item.disabled ? undefined : item.onClick}
                  disabled={item.disabled}
                  className={`group flex items-center justify-center h-9 transition-colors w-full flex-shrink-0 ${
                    item.disabled
                      ? 'opacity-40 cursor-not-allowed'
                      : item.active
                        ? 'bg-[var(--sidebar-active)]'
                        : 'hover:bg-[var(--sidebar-hover)]'
                  }`}
                >
                  {React.cloneElement(item.icon, {
                    className: `transition-colors ${
                      item.disabled
                        ? 'text-[var(--text)]/40'
                        : item.active
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

            {/* Deployment Target Badge */}
            {container?.deployment_provider && (
              <div className="hidden md:flex items-center gap-2 px-3 py-1.5 bg-purple-500/10 border border-purple-500/30 rounded-lg">
                <span className="text-xs text-purple-400">Deploy to:</span>
                <span
                  className={`text-xs font-semibold flex items-center gap-1
                  ${container.deployment_provider === 'vercel' ? 'text-white' : ''}
                  ${container.deployment_provider === 'netlify' ? 'text-[#00C7B7]' : ''}
                  ${container.deployment_provider === 'cloudflare' ? 'text-[#F38020]' : ''}
                `}
                >
                  {container.deployment_provider === 'vercel' && '▲'}
                  {container.deployment_provider === 'netlify' && '◆'}
                  {container.deployment_provider === 'cloudflare' && '🔥'}
                  {(container.deployment_provider as string).charAt(0).toUpperCase() +
                    (container.deployment_provider as string).slice(1)}
                </span>
              </div>
            )}

            {/* Environment Status Badge */}
            {environmentStatus && (
              <div className="hidden md:flex">
                <EnvironmentStatusBadge status={environmentStatus} showTooltip />
              </div>
            )}

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
                assignedDeploymentTarget={
                  container?.deployment_provider as
                    | 'vercel'
                    | 'netlify'
                    | 'cloudflare'
                    | null
                    | undefined
                }
                containerName={container?.name as string | undefined}
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
                        slug={slug!}
                        projectName={project?.name}
                        sidebarExpanded={isLeftSidebarExpanded}
                        isDocked={true}
                        isPointerOverPreviewRef={isPointerOverPreviewRef}
                        prefillMessage={prefillChatMessage}
                        onPrefillConsumed={() => setPrefillChatMessage(null)}
                        onIdleWarning={handleIdleWarning}
                        onEnvironmentStopping={handleEnvironmentStopping}
                        onEnvironmentStopped={handleEnvironmentStopped}
                      />
                    </Panel>
                    <PanelResizeHandle className="w-2 bg-transparent cursor-col-resize [&[data-separator='hover']]:bg-[var(--primary)]/20 [&[data-separator='active']]:bg-[var(--primary)]/40" />
                  </>
                )}

                {/* MAIN CONTENT PANEL (inside PanelGroup) */}
                <Panel id="content" minSize="30" className="overflow-hidden">
                  {/* Preview View */}
                  <div className={`w-full h-full ${activeView === 'preview' ? 'block' : 'hidden'}`}>
                    {noPreview
                      ? previewPlaceholder
                      : (loadingOverlay ??
                        (devServerUrl ? (
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
                              previewableContainers={previewableContainers}
                              selectedPreviewContainerId={selectedPreviewContainerId}
                              onPreviewContainerSwitch={handlePreviewContainerSwitch}
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
                                <PreviewPortPicker
                                  containers={previewableContainers}
                                  selectedContainerId={selectedPreviewContainerId}
                                  onSelect={handlePreviewContainerSwitch}
                                />
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
                        )))}
                  </div>

                  {/* Code View */}
                  <div
                    className={`w-full h-full ${activeView === 'code' ? 'flex' : 'hidden'} flex-col overflow-hidden`}
                  >
                    <CodeEditor
                      projectId={project?.id}
                      slug={slug!}
                      fileTree={fileTree}
                      onFileUpdate={handleFileUpdate}
                      onFileCreate={handleFileCreate}
                      onFileDelete={handleFileDelete}
                      onFileRename={handleFileRename}
                      onDirectoryCreate={handleDirectoryCreate}
                      isFilesSyncing={!filesInitiallyLoaded && fileTree.length === 0}
                      startupOverlay={codeEditorOverlay}
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
                    <TerminalPanel projectId={slug!} projectUuid={project?.id as string} />
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
                        slug={slug!}
                        projectName={project?.name}
                        sidebarExpanded={isLeftSidebarExpanded}
                        isDocked={true}
                        isPointerOverPreviewRef={isPointerOverPreviewRef}
                        prefillMessage={prefillChatMessage}
                        onPrefillConsumed={() => setPrefillChatMessage(null)}
                        onIdleWarning={handleIdleWarning}
                        onEnvironmentStopping={handleEnvironmentStopping}
                        onEnvironmentStopped={handleEnvironmentStopped}
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
                  {noPreview
                    ? previewPlaceholder
                    : (loadingOverlay ??
                      (devServerUrl ? (
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
                            previewableContainers={previewableContainers}
                            selectedPreviewContainerId={selectedPreviewContainerId}
                            onPreviewContainerSwitch={handlePreviewContainerSwitch}
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
                              <PreviewPortPicker
                                containers={previewableContainers}
                                selectedContainerId={selectedPreviewContainerId}
                                onSelect={handlePreviewContainerSwitch}
                              />
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
                      )))}
                </div>

                {/* Code View */}
                <div
                  className={`w-full h-full ${activeView === 'code' ? 'flex' : 'hidden'} flex-col overflow-hidden`}
                >
                  <CodeEditor
                    projectId={project?.id}
                    slug={slug!}
                    fileTree={fileTree}
                    onFileUpdate={handleFileUpdate}
                    onFileCreate={handleFileCreate}
                    onFileDelete={handleFileDelete}
                    onFileRename={handleFileRename}
                    onDirectoryCreate={handleDirectoryCreate}
                    isFilesSyncing={!filesInitiallyLoaded && fileTree.length === 0}
                    startupOverlay={codeEditorOverlay}
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
                  <TerminalPanel projectId={slug!} projectUuid={project?.id as string} />
                </div>
              </div>
            )}
          </div>

          {/* Mobile layout - simple full width content */}
          <div className="md:hidden w-full h-full overflow-hidden">
            {/* Preview View */}
            <div className={`w-full h-full ${activeView === 'preview' ? 'block' : 'hidden'}`}>
              {noPreview
                ? previewPlaceholder
                : (loadingOverlay ??
                  (devServerUrl ? (
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
                  )))}
            </div>

            {/* Code View */}
            <div
              className={`w-full h-full ${activeView === 'code' ? 'flex' : 'hidden'} flex-col overflow-hidden`}
            >
              <CodeEditor
                projectId={project?.id}
                slug={slug!}
                fileTree={fileTree}
                onFileUpdate={handleFileUpdate}
                onFileCreate={handleFileCreate}
                onFileDelete={handleFileDelete}
                onFileRename={handleFileRename}
                onDirectoryCreate={handleDirectoryCreate}
                isFilesSyncing={!filesInitiallyLoaded && fileTree.length === 0}
                startupOverlay={codeEditorOverlay}
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
              <TerminalPanel projectId={slug!} projectUuid={project?.id as string} />
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
            slug={slug!}
            projectName={project?.name}
            sidebarExpanded={isLeftSidebarExpanded}
            isPointerOverPreviewRef={isPointerOverPreviewRef}
            prefillMessage={prefillChatMessage}
            onPrefillConsumed={() => setPrefillChatMessage(null)}
            onExpandedChange={setChatExpanded}
            onIdleWarning={handleIdleWarning}
            onEnvironmentStopping={handleEnvironmentStopping}
            onEnvironmentStopped={handleEnvironmentStopped}
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
      <DiscordSupport chatPosition={chatPosition} mobileChatOpen={chatExpanded} />

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
          defaultProvider={container?.deployment_provider as string | undefined}
        />
      )}
    </div>
  );
}
