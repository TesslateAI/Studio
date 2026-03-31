import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useParams, useNavigate, useSearchParams, useLocation } from 'react-router-dom';
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
  ArrowsClockwise,
  Kanban,
  Terminal,
  TreeStructure,
  LockSimple,
  DeviceMobile,
} from '@phosphor-icons/react';
import { FloatingPanel } from '../components/ui/FloatingPanel';
import { MobileMenu } from '../components/ui/MobileMenu';
import { Tooltip } from '../components/ui/Tooltip';
import { NavigationSidebar } from '../components/ui/NavigationSidebar';
import { Breadcrumbs } from '../components/ui/Breadcrumbs';
import { ChatContainer } from '../components/chat/ChatContainer';
import { LoadingSpinner } from '../components/PulsingGridSpinner';
import { MobileWarning } from '../components/MobileWarning';
import { BrowserPreview } from '../components/BrowserPreview';
import { ContainerLoadingOverlay } from '../components/ContainerLoadingOverlay';
import { NoComputePlaceholder } from '../components/NoComputePlaceholder';
import { useContainerStartup } from '../hooks/useContainerStartup';
import { useFileTree } from '../hooks/useFileTree';
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
import { ContainerSelector, PROJECT_ROOT_ID } from '../components/ContainerSelector';
import { PreviewPortPicker, type PreviewableContainer } from '../components/PreviewPortPicker';
import {
  ArchitectureView,
  type ArchitectureViewHandle,
} from '../components/views/ArchitectureView';
import { projectsApi, marketplaceApi } from '../lib/api';
import { useCommandHandlers, type ViewType } from '../contexts/CommandContext';
import { useChatPosition } from '../contexts/ChatPositionContext';
import { useTeam } from '../contexts/TeamContext';
import toast from 'react-hot-toast';
import { fileEvents } from '../utils/fileEvents';
import { Panel, Group as PanelGroup, Separator as PanelResizeHandle } from 'react-resizable-panels';
import { type ChatAgent } from '../types/chat';
import { getFeatures, type ComputeTier } from '../types/project';
import { getEnvironmentStatus } from '../components/ui/environmentStatus';
import { EnvironmentStatusBadge } from '../components/ui/EnvironmentStatusBadge';
import IdleWarningBanner from '../components/IdleWarningBanner';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ProjectViewType = 'architecture' | 'preview' | 'code' | 'kanban' | 'assets' | 'terminal';
type PanelType = 'github' | 'notes' | 'settings' | null;

const VIEW_LABELS: Record<ProjectViewType, string> = {
  architecture: 'Architecture',
  preview: 'Builder',
  code: 'Code',
  kanban: 'Kanban',
  assets: 'Assets',
  terminal: 'Terminal',
};

const VALID_VIEWS: ProjectViewType[] = [
  'architecture',
  'preview',
  'code',
  'kanban',
  'assets',
  'terminal',
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ProjectPage() {
  const { slug } = useParams<{ slug: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const containerId = searchParams.get('container');

  const { chatPosition } = useChatPosition();
  const { can } = useTeam();
  const isBuilderPath = location.pathname.endsWith('/builder');

  // RBAC: viewer-level restriction flags
  const isViewer = !can('chat.send');
  const canChat = can('chat.send');
  const canEditKanban = can('kanban.edit');
  const canAccessTerminal = can('terminal.access');
  const canGitWrite = can('git.write');
  const canEditSettings = can('project.settings');
  const canDeploy = can('deployment.create');
  const canEditAssets = can('file.write');

  // ---------------------------------------------------------------------------
  // Core state
  // ---------------------------------------------------------------------------

  const [project, setProject] = useState<Record<string, unknown> | null>(null);
  const [container, setContainer] = useState<Record<string, unknown> | null>(null);
  const [containers, setContainers] = useState<Array<Record<string, unknown>>>([]);
  const [agents, setAgents] = useState<ChatAgent[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(() => {
    if (!slug) return null;
    return localStorage.getItem(`tesslate-agent-${slug}`);
  });

  // View state — route-based initial value
  const [activeView, setActiveView] = useState<ProjectViewType>(() => {
    if (isBuilderPath) return 'preview';
    const saved = localStorage.getItem(`tesslate-view-${slug}`);
    if (saved && VALID_VIEWS.includes(saved as ProjectViewType)) {
      return saved as ProjectViewType;
    }
    return 'preview';
  });

  // Lazy mount flags
  const [archMounted, setArchMounted] = useState(false);
  const [kanbanMounted, setKanbanMounted] = useState(false);

  // Architecture ref + state for top bar
  const archRef = useRef<ArchitectureViewHandle>(null);
  const [archState, setArchState] = useState({ configDirty: false, isRunning: false });

  const [activePanel, setActivePanel] = useState<PanelType>(null);
  const [devServerUrl, setDevServerUrl] = useState<string | null>(null);
  const [devServerUrlWithAuth, setDevServerUrlWithAuth] = useState<string | null>(null);
  const [currentPreviewUrl, setCurrentPreviewUrl] = useState<string>('');
  const [previewMode, setPreviewMode] = useState<'normal' | 'browser-tabs'>('normal');
  const [viewportMode, setViewportMode] = useState<'desktop' | 'mobile'>('desktop');
  const [isLeftSidebarExpanded, setIsLeftSidebarExpanded] = useState(() => {
    const saved = localStorage.getItem('navigationSidebarExpanded');
    return saved !== null ? JSON.parse(saved) : true;
  });
  const [showDeploymentsDropdown, setShowDeploymentsDropdown] = useState(false);
  const [showDeployModal, setShowDeployModal] = useState(false);
  const [prefillChatMessage, setPrefillChatMessage] = useState<string | null>(null);
  const [_chatExpanded, setChatExpanded] = useState(false);

  // Preview port picker
  const [previewableContainers, setPreviewableContainers] = useState<PreviewableContainer[]>([]);

  const refreshTimeoutRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const isPointerOverPreviewRef = useRef(false);

  // Container startup tracking
  const [needsContainerStart, setNeedsContainerStart] = useState(false);
  const currentContainerIdRef = useRef<string | null>(null);

  // Lifecycle warning state
  const [idleWarningMinutes, setIdleWarningMinutes] = useState<number | null>(null);
  const [environmentStopping, setEnvironmentStopping] = useState(false);
  const [environmentProvisioning, setEnvironmentProvisioning] = useState(false);

  // ---------------------------------------------------------------------------
  // File tree hook
  // ---------------------------------------------------------------------------

  const containerDir = (container as Record<string, unknown> | null)?.directory as
    | string
    | undefined;
  const {
    fileTree,
    isLoaded: filesInitiallyLoaded,
    refresh: loadFileTree,
    refreshWithRetry: loadFilesWithRetry,
    cancelRetry: cancelFileRetry,
  } = useFileTree({
    slug: slug!,
    containerDir,
    enabled: !!slug,
  });

  // ---------------------------------------------------------------------------
  // Container startup hook
  // ---------------------------------------------------------------------------

  const containerStartup = useContainerStartup(
    slug,
    needsContainerStart ? currentContainerIdRef.current : null,
    {
      onReady: (url) => {
        setDevServerUrl(url);
        setDevServerUrlWithAuth(url);
        setCurrentPreviewUrl(url);
        setNeedsContainerStart(false);
        toast.success('Development server ready!', { id: 'container-start', duration: 2000 });
        if (slug) {
          projectsApi
            .get(slug)
            .then((p) => setProject(p))
            .catch(() => {});
        }
        cancelFileRetry();
        loadFilesWithRetry();
        // Refresh previewable containers
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
            })
            .catch(() => {});
        }
      },
      onError: (error) => {
        setNeedsContainerStart(false);
        toast.error(`Container failed: ${error}`, { id: 'container-start' });
      },
    }
  );

  // ---------------------------------------------------------------------------
  // Two-axis state model
  // ---------------------------------------------------------------------------

  const computeTier = (project?.compute_tier as ComputeTier) ?? 'none';
  const features = useMemo(() => getFeatures(computeTier), [computeTier]);
  const noPreview = !features.preview && !devServerUrl;
  const hasFiles = features.fileBrowser;

  const environmentStatus = useMemo(
    () =>
      getEnvironmentStatus(computeTier, {
        provisioning: environmentProvisioning,
        stopping: environmentStopping,
        starting: needsContainerStart && containerStartup.isLoading,
      }),
    [
      computeTier,
      environmentProvisioning,
      environmentStopping,
      needsContainerStart,
      containerStartup.isLoading,
    ]
  );

  // ---------------------------------------------------------------------------
  // Callbacks
  // ---------------------------------------------------------------------------

  const handleStartCompute = useCallback(async () => {
    if (!container || !slug) {
      toast.error('No container found — project may still be loading');
      return;
    }

    // Root view = start all containers (whole environment)
    if ((container.id as string) === PROJECT_ROOT_ID) {
      toast.loading('Starting environment...', { id: 'container-start' });
      try {
        await projectsApi.startAllContainers(slug);
        toast.success('Environment started!', { id: 'container-start', duration: 2000 });
        loadContainer();
      } catch (error) {
        console.error('Failed to start all containers:', error);
        toast.error('Failed to start environment', { id: 'container-start' });
      }
      return;
    }

    currentContainerIdRef.current = container.id as string;
    setNeedsContainerStart(true);
    toast.loading('Starting environment...', { id: 'container-start' });
    containerStartup.startContainer(container.id as string);
  }, [container, containerStartup, slug]);

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

  const togglePanel = (panel: PanelType) => {
    setActivePanel(activePanel === panel ? null : panel);
  };

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

  // ---------------------------------------------------------------------------
  // Previewable containers
  // ---------------------------------------------------------------------------

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
      if (c.container_type === 'service') continue;
      if (c.deployment_mode === 'external') continue;
      const port = (c.internal_port as number) || (c.port as number);
      if (!port) continue;
      const rawDir = c.directory as string;
      const dirKey = rawDir && rawDir !== '.' ? sanitizeKey(rawDir) : null;
      const nameKey = c.name ? sanitizeKey(c.name as string) : null;
      const runtimeStatus = statusContainers?.[dirKey!] ?? statusContainers?.[nameKey!] ?? null;
      if (!runtimeStatus?.running || !runtimeStatus?.url) continue;
      previewable.push({
        id: c.id as string,
        name: c.name as string,
        port,
        url: runtimeStatus.url as string,
        isPrimary: (c.id as string) === primaryContainerId,
      });
    }
    previewable.sort((a, b) => (a.isPrimary ? -1 : b.isPrimary ? 1 : 0));
    return previewable;
  };

  const handlePreviewContainerSwitch = useCallback(
    (target: PreviewableContainer) => {
      if (slug) navigate(`/project/${slug}?container=${target.id}`);
    },
    [slug, navigate]
  );

  // ---------------------------------------------------------------------------
  // File operations
  // ---------------------------------------------------------------------------

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
        if (refreshTimeoutRef.current) clearTimeout(refreshTimeoutRef.current);
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

  // ---------------------------------------------------------------------------
  // Data loaders
  // ---------------------------------------------------------------------------

  const loadProject = async () => {
    if (!slug) return;
    try {
      const projectData = await projectsApi.get(slug);
      setProject(projectData);
      loadFilesWithRetry();
    } catch (error) {
      console.error('Failed to load project:', error);
      toast.error('Failed to load project');
    }
  };

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

  const loadAgents = async () => {
    try {
      const libraryData = await marketplaceApi.getMyAgents();
      const enabledAgents = libraryData.agents.filter(
        (agent: Record<string, unknown>) =>
          agent.is_enabled && !agent.is_admin_disabled && agent.slug !== 'librarian'
      );
      const uiAgents = enabledAgents.map((agent: Record<string, unknown>) => ({
        id: agent.slug as string,
        name: agent.name as string,
        icon: (agent.icon as string) || '\uD83E\uDD16',
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

  const loadDevServerUrl = async () => {
    if (!slug) return;
    try {
      const response = await projectsApi.getDevServerUrl(slug);
      const token = localStorage.getItem('token');
      const deploymentMode = import.meta.env.DEPLOYMENT_MODE || 'docker';

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
        if (token && deploymentMode === 'kubernetes') {
          setDevServerUrlWithAuth(
            response.url + (response.url.includes('?') ? '&' : '?') + 'auth_token=' + token
          );
        } else {
          setDevServerUrlWithAuth(response.url);
        }
      } else if (response.status === 'starting') {
        toast.loading('Development server is starting up...', { id: 'dev-server' });
        setTimeout(() => loadDevServerUrl(), 3000);
      } else if (response.url) {
        setDevServerUrl(response.url);
        if (token && deploymentMode === 'kubernetes') {
          setDevServerUrlWithAuth(
            response.url + (response.url.includes('?') ? '&' : '?') + 'auth_token=' + token
          );
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

  const loadContainer = async () => {
    if (!slug) return;
    try {
      const freshProject = await projectsApi.get(slug);

      // Provisioning — files/containers aren't ready yet. Show the badge,
      // skip container logic entirely, and let loadProject handle file display.
      if (freshProject.environment_status === 'provisioning') {
        setEnvironmentProvisioning(true);
        setNeedsContainerStart(false);
        return;
      }
      setEnvironmentProvisioning(false);

      const allContainers = await projectsApi.getContainers(slug);
      setContainers(allContainers);

      if (!allContainers || allContainers.length === 0) {
        navigate(`/project/${slug}/setup`, { replace: true });
        return;
      }

      // Project Root mode
      if (containerId === PROJECT_ROOT_ID) {
        setContainer({ id: PROJECT_ROOT_ID, name: 'Project Root', status: 'running' });
        localStorage.setItem(`tesslate-container-${slug}`, PROJECT_ROOT_ID);
        return;
      }

      const foundContainer = containerId
        ? allContainers.find((c: Record<string, unknown>) => c.id === containerId)
        : allContainers[0];

      if (foundContainer) {
        setContainer(foundContainer);
        if (slug) {
          localStorage.setItem(`tesslate-container-${slug}`, foundContainer.id as string);
        }

        let status: Record<string, unknown> | null = null;
        try {
          status = await projectsApi.getContainersStatus(slug);

          const sanitizeKey = (s: string) =>
            s
              .toLowerCase()
              .replace(/[^a-z0-9-]/g, '-')
              .replace(/-+/g, '-')
              .replace(/^-|-$/g, '');

          const rawDir = foundContainer.directory;
          const dirKey = rawDir && rawDir !== '.' ? sanitizeKey(rawDir) : null;
          const nameKey = foundContainer.name ? sanitizeKey(foundContainer.name as string) : null;
          const containerStatus =
            status?.containers?.[dirKey!] ?? status?.containers?.[nameKey!] ?? null;

          console.log('[loadContainer] status response:', JSON.stringify(status));
          console.log('[loadContainer] dirKey:', dirKey, 'nameKey:', nameKey);
          console.log('[loadContainer] containerStatus:', JSON.stringify(containerStatus));

          // Build previewable containers
          const statusContainers = status?.containers ?? null;
          const previewable = buildPreviewableContainers(
            allContainers,
            statusContainers,
            foundContainer.id as string
          );
          setPreviewableContainers(previewable);

          // Setup failed — redirect to dashboard, user should delete and recreate
          if (freshProject.environment_status === 'setup_failed') {
            toast.error('This project failed to set up. Please delete it and create a new one.', {
              duration: 5000,
            });
            navigate('/dashboard');
            return;
          }

          // Stopping state
          if (
            status?.environment_status === 'stopping' ||
            freshProject.environment_status === 'stopping'
          ) {
            setEnvironmentStopping(true);
            return;
          }

          // Hibernation
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

          // Fast path: already running
          if (containerStatus?.running && containerStatus?.url) {
            console.log('[loadContainer] FAST PATH: container running at', containerStatus.url);
            containerStartup.reset();
            setNeedsContainerStart(false);
            setDevServerUrl(containerStatus.url);
            setDevServerUrlWithAuth(containerStatus.url);
            setCurrentPreviewUrl(containerStatus.url);
            cancelFileRetry();
            loadFilesWithRetry();
            return;
          }

          // Fallback: any running container with a URL
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
              cancelFileRetry();
              loadFilesWithRetry();
              return;
            }
          }

          console.log('[loadContainer] SLOW PATH: container not detected as running');
        } catch (statusError) {
          console.warn('Failed to check container status, will attempt start:', statusError);
        }

        // Don't interfere with in-progress startup
        if (needsContainerStart && containerStartup.isLoading) return;

        const liveComputeState = status?.compute_state as string | undefined;
        const effectiveComputeTier =
          liveComputeState ?? (freshProject.compute_tier as string) ?? 'none';
        if (effectiveComputeTier !== 'environment') {
          console.log(
            '[loadContainer] compute state',
            effectiveComputeTier,
            '-- skipping container start'
          );
          containerStartup.reset();
          setNeedsContainerStart(false);
          return;
        }

        // Container not running - start via hook
        console.log('[loadContainer] Starting container via startup hook');
        const containerIdToStart = foundContainer.id as string;
        currentContainerIdRef.current = containerIdToStart;
        setNeedsContainerStart(true);
        containerStartup.startContainer(containerIdToStart);
      }
    } catch (error) {
      console.error('Failed to load container:', error);
    }
  };

  // ---------------------------------------------------------------------------
  // Preview helpers
  // ---------------------------------------------------------------------------

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
      iframe.contentWindow.postMessage({ type: 'navigate', direction: 'back' }, '*');
    }
  };

  const navigateForward = () => {
    const iframe = iframeRef.current;
    if (iframe && iframe.contentWindow) {
      iframe.contentWindow.postMessage({ type: 'navigate', direction: 'forward' }, '*');
    }
  };

  // ---------------------------------------------------------------------------
  // Derived state
  // ---------------------------------------------------------------------------

  const currentAgent = useMemo(() => {
    if (selectedAgentId) {
      const found = agents.find((a) => a.id === selectedAgentId);
      if (found) return found;
    }
    return agents[agents.length - 1] ?? null;
  }, [agents, selectedAgentId]);

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

  // ---------------------------------------------------------------------------
  // Persist view choice
  // ---------------------------------------------------------------------------

  useEffect(() => {
    if (slug) localStorage.setItem(`tesslate-view-${slug}`, activeView);
  }, [activeView, slug]);

  // ---------------------------------------------------------------------------
  // Lazy mount
  // ---------------------------------------------------------------------------

  useEffect(() => {
    if (activeView === 'architecture') setArchMounted(true);
  }, [activeView]);

  useEffect(() => {
    if (activeView === 'kanban' && !kanbanMounted) setKanbanMounted(true);
  }, [activeView, kanbanMounted]);

  // Architecture state for top bar rendering (updated via callback from ArchitectureView)
  const handleArchStateChange = useCallback(
    (state: { configDirty: boolean; isRunning: boolean }) => {
      setArchState(state);
    },
    []
  );

  const isEnvironmentRunning = environmentStatus === 'running';

  const handleStartStopAll = useCallback(async () => {
    if (!slug) return;
    try {
      if (isEnvironmentRunning) {
        toast.loading('Stopping environment...', { id: 'env-toggle' });
        await projectsApi.stopAllContainers(slug);
        toast.success('Environment stopped', { id: 'env-toggle', duration: 2000 });
      } else {
        toast.loading('Starting environment...', { id: 'env-toggle' });
        await projectsApi.startAllContainers(slug);
        toast.success('Environment started!', { id: 'env-toggle', duration: 2000 });
      }
      const p = await projectsApi.get(slug);
      setProject(p);
      loadContainer();
    } catch (error) {
      console.error('Failed to toggle environment:', error);
      toast.error('Failed to toggle environment', { id: 'env-toggle' });
    }
  }, [slug, isEnvironmentRunning]);

  // ---------------------------------------------------------------------------
  // Keyboard shortcuts
  // ---------------------------------------------------------------------------

  useHotkeys(
    'mod+1',
    (e) => {
      e.preventDefault();
      setActiveView('architecture');
    },
    { enableOnFormTags: false }
  );
  useHotkeys(
    'mod+2',
    (e) => {
      e.preventDefault();
      setActiveView('preview');
    },
    { enableOnFormTags: false }
  );
  useHotkeys(
    'mod+3',
    (e) => {
      e.preventDefault();
      setActiveView('code');
    },
    { enableOnFormTags: false }
  );
  useHotkeys(
    'mod+4',
    (e) => {
      e.preventDefault();
      setActiveView('kanban');
    },
    { enableOnFormTags: false }
  );
  useHotkeys(
    'mod+5',
    (e) => {
      e.preventDefault();
      setActiveView('assets');
    },
    { enableOnFormTags: false }
  );
  useHotkeys(
    'mod+6',
    (e) => {
      e.preventDefault();
      setActiveView('terminal');
    },
    { enableOnFormTags: false }
  );
  useHotkeys(
    'mod+r',
    (e) => {
      e.preventDefault();
      if (activeView === 'preview') refreshPreview();
    },
    { enableOnFormTags: false }
  );
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
  useHotkeys(
    'escape',
    () => {
      if (activePanel) setActivePanel(null);
    },
    { enableOnFormTags: false }
  );

  // ---------------------------------------------------------------------------
  // Effects
  // ---------------------------------------------------------------------------

  // Mount effect — load project data
  useEffect(() => {
    if (slug) {
      loadProject();
      loadDevServerUrl();
      loadSettings();
      loadAgents();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug]);

  // Provisioning poll — re-check every 3s until status transitions
  useEffect(() => {
    if (!environmentProvisioning || !slug) return;
    const interval = setInterval(async () => {
      try {
        const p = await projectsApi.get(slug);
        if (p.environment_status !== 'provisioning') {
          setEnvironmentProvisioning(false);
          loadProject();
          loadContainer();
        }
      } catch {
        // ignore — next tick will retry
      }
    }, 3000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [environmentProvisioning, slug]);

  // Container change effect — restore from localStorage, load container
  useEffect(() => {
    if (slug) {
      if (!containerId) {
        const savedContainerId = localStorage.getItem(`tesslate-container-${slug}`);
        if (savedContainerId) {
          navigate(`/project/${slug}?container=${savedContainerId}`, { replace: true });
          return;
        }
      }
      loadContainer();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [containerId, slug]);

  // Container dir change effect — reload files for non-v2 projects
  useEffect(() => {
    if (container) {
      if (project?.volume_id) return;
      cancelFileRetry();
      loadFilesWithRetry();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [container, project?.volume_id]);

  // Cleanup
  useEffect(() => {
    return () => {
      if (refreshTimeoutRef.current) clearTimeout(refreshTimeoutRef.current);
    };
  }, []);

  // PostMessage listener for iframe URL changes
  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      if (event.data && event.data.type === 'url-change') {
        const url = event.data.url;
        try {
          const urlObj = new URL(url);
          urlObj.searchParams.delete('auth_token');
          urlObj.searchParams.delete('t');
          urlObj.searchParams.delete('hmr_fallback');
          let cleanUrl = urlObj.origin + urlObj.pathname;
          const remainingParams = urlObj.searchParams.toString();
          if (remainingParams) cleanUrl += '?' + remainingParams;
          if (urlObj.hash) cleanUrl += urlObj.hash;
          setCurrentPreviewUrl(cleanUrl);
        } catch {
          setCurrentPreviewUrl(url);
        }
      }
    };
    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, []);

  // Sync devServerUrl -> currentPreviewUrl
  useEffect(() => {
    if (devServerUrl) setCurrentPreviewUrl(devServerUrl);
  }, [devServerUrl]);

  // Refresh file tree when switching to code view
  useEffect(() => {
    if (activeView === 'code' && slug) loadFileTree();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeView, slug]);

  // Register command handlers for CommandPalette
  useCommandHandlers({
    switchView: (view: ViewType) => setActiveView(view as ProjectViewType),
    togglePanel: (panel) => togglePanel(panel as PanelType),
    refreshPreview,
  });

  // ---------------------------------------------------------------------------
  // Loading state
  // ---------------------------------------------------------------------------

  if (!project) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-gray-400">Loading project...</div>
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Sidebar items
  // ---------------------------------------------------------------------------

  const leftSidebarItems = [
    {
      icon: <TreeStructure size={18} />,
      title: 'Architecture',
      onClick: () => setActiveView('architecture'),
      active: activeView === 'architecture',
      disabled: false,
      restricted: false,
    },
    {
      icon: <Monitor size={18} />,
      title: 'Preview',
      onClick: () => setActiveView('preview'),
      active: activeView === 'preview',
      disabled: false,
      restricted: false,
    },
    {
      icon: <Code size={18} />,
      title: 'Code',
      onClick: () => setActiveView('code'),
      active: activeView === 'code',
      disabled: false,
      restricted: false,
    },
    {
      icon: <Kanban size={18} />,
      title: 'Kanban Board',
      onClick: () => setActiveView('kanban'),
      active: activeView === 'kanban',
      disabled: false,
      restricted: !canEditKanban,
    },
    {
      icon: <Image size={18} />,
      title: 'Assets',
      onClick: () => setActiveView('assets'),
      active: activeView === 'assets',
      disabled: false,
      restricted: !canEditAssets,
    },
    {
      icon: <Terminal size={18} />,
      title: 'Terminal',
      onClick: canAccessTerminal ? () => setActiveView('terminal') : undefined,
      active: activeView === 'terminal',
      disabled: !canAccessTerminal,
      restricted: !canAccessTerminal,
    },
  ];

  const panelItems = [
    {
      icon: <BookOpen size={16} />,
      title: 'Notes',
      onClick: () => togglePanel('notes'),
      active: activePanel === 'notes',
      disabled: false,
      restricted: false,
    },
    {
      icon: <GitBranch size={16} />,
      title: 'GitHub Sync',
      onClick: canGitWrite ? () => togglePanel('github') : undefined,
      active: activePanel === 'github',
      disabled: !canGitWrite,
      restricted: !canGitWrite,
    },
    {
      icon: <Gear size={16} />,
      title: 'Project Settings',
      onClick: canEditSettings ? () => togglePanel('settings') : undefined,
      active: activePanel === 'settings',
      disabled: !canEditSettings,
      restricted: !canEditSettings,
    },
  ];

  // MobileMenu expects a flat items array
  const mobileRightItems = [
    ...panelItems,
    {
      icon: <Storefront size={18} />,
      title: 'Agents',
      onClick: () => window.open('/marketplace', '_blank'),
    },
  ];

  // ---------------------------------------------------------------------------
  // Chat props (shared across docked/floating instances)
  // ---------------------------------------------------------------------------

  const chatViewContext = activeView === 'architecture' ? 'graph' : 'builder';

  const chatProps = {
    projectId: project?.id,
    containerId: containerId || undefined,
    viewContext: chatViewContext as 'graph' | 'builder',
    agents,
    currentAgent,
    onSelectAgent: handleAgentSelect,
    onFileUpdate: handleFileUpdate,
    slug: slug!,
    projectName: project?.name,
    sidebarExpanded: isLeftSidebarExpanded,
    isPointerOverPreviewRef,
    prefillMessage: prefillChatMessage,
    onPrefillConsumed: () => setPrefillChatMessage(null),
    onIdleWarning: handleIdleWarning,
    onEnvironmentStopping: handleEnvironmentStopping,
    onEnvironmentStopped: handleEnvironmentStopped,
    onVolumeReady: () => {
      // Refresh project state when the Hub reports the volume is ready.
      if (slug) {
        projectsApi
          .get(slug)
          .then(setProject)
          .catch(() => {});
      }
    },
    disabled: !canChat,
  } as const;

  // ---------------------------------------------------------------------------
  // Render helpers — content views (shared between docked/center/mobile layouts)
  // ---------------------------------------------------------------------------

  const renderArchitectureView = () =>
    archMounted && (
      <div className={`w-full h-full ${activeView === 'architecture' ? 'flex' : 'hidden'}`}>
        <ArchitectureView
          ref={archRef}
          slug={slug!}
          projectId={project?.id as string}
          isActive={activeView === 'architecture'}
          onContainersChanged={() => {
            if (slug)
              projectsApi
                .getContainers(slug)
                .then(setContainers)
                .catch(() => {});
          }}
          onNavigateToContainer={(id) => {
            setActiveView('preview');
            navigate(`/project/${slug}?container=${id}`);
          }}
          onStateChange={handleArchStateChange}
          readOnly={isViewer}
        />
      </div>
    );

  const renderPreviewView = () => (
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
                selectedPreviewContainerId={containerId || (container?.id as string)}
                onPreviewContainerSwitch={handlePreviewContainerSwitch}
              />
            ) : (
              <>
                <div className="h-10 bg-[var(--surface)] border-b border-[var(--border)] px-2 flex items-center gap-1.5 flex-shrink-0">
                  <div className="flex items-center gap-0.5">
                    <button onClick={navigateBack} className="btn btn-icon btn-sm" title="Go back">
                      <CaretLeft size={14} weight="bold" />
                    </button>
                    <button
                      onClick={navigateForward}
                      className="btn btn-icon btn-sm"
                      title="Go forward"
                    >
                      <CaretRight size={14} weight="bold" />
                    </button>
                  </div>
                  <div className="hidden md:flex flex-1 items-center gap-1.5 h-7 bg-[var(--bg)] border border-[var(--border)] rounded-full px-3 min-w-0">
                    <LockSimple
                      size={11}
                      weight="bold"
                      className="text-[var(--text-subtle)] flex-shrink-0"
                    />
                    <span className="text-[11px] text-[var(--text-muted)] font-mono truncate">
                      {currentPreviewUrl || devServerUrl}
                    </span>
                  </div>
                  <div className="flex items-center gap-0.5 ml-auto">
                    <PreviewPortPicker
                      containers={previewableContainers}
                      selectedContainerId={containerId || (container?.id as string)}
                      onSelect={handlePreviewContainerSwitch}
                    />
                    <button
                      onClick={refreshPreview}
                      className="btn btn-icon btn-sm"
                      title="Refresh"
                    >
                      <ArrowsClockwise size={14} />
                    </button>
                    <button
                      onClick={() =>
                        setViewportMode(viewportMode === 'desktop' ? 'mobile' : 'desktop')
                      }
                      className={`btn btn-icon btn-sm ${viewportMode === 'mobile' ? 'btn-active text-[var(--primary)]' : ''}`}
                      title={
                        viewportMode === 'desktop'
                          ? 'Switch to mobile view'
                          : 'Switch to desktop view'
                      }
                    >
                      {viewportMode === 'desktop' ? (
                        <DeviceMobile size={14} />
                      ) : (
                        <Monitor size={14} />
                      )}
                    </button>
                  </div>
                </div>
                <div
                  className={`flex-1 relative overflow-auto ${viewportMode === 'mobile' ? 'bg-[var(--bg)] flex items-center justify-center' : 'bg-white'}`}
                  style={{ height: 'calc(100% - 40px)' }}
                  onMouseEnter={() => {
                    isPointerOverPreviewRef.current = true;
                  }}
                  onMouseLeave={() => {
                    isPointerOverPreviewRef.current = false;
                  }}
                >
                  <div
                    className={
                      viewportMode === 'mobile'
                        ? 'w-[375px] h-[667px] border border-[var(--border)] rounded-[var(--radius)] overflow-hidden flex-shrink-0 bg-white'
                        : 'w-full h-full'
                    }
                  >
                    <iframe
                      ref={iframeRef}
                      id="preview-iframe"
                      src={devServerUrlWithAuth || devServerUrl}
                      className="w-full h-full"
                      sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals"
                    />
                  </div>
                </div>
              </>
            )
          ) : (
            <div className="h-full flex items-center justify-center text-[var(--text)]/60">
              <LoadingSpinner message="Loading project..." size={60} />
            </div>
          )))}
    </div>
  );

  const renderCodeView = () => (
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
        readOnly={!canEditAssets}
      />
    </div>
  );

  const renderKanbanView = () =>
    kanbanMounted && project?.id ? (
      <div className={`w-full h-full ${activeView === 'kanban' ? 'block' : 'hidden'}`}>
        <KanbanPanel projectId={project.id as string} readOnly={!canEditKanban} />
      </div>
    ) : null;

  const renderAssetsView = () => (
    <div className={`w-full h-full ${activeView === 'assets' ? 'block' : 'hidden'}`}>
      <AssetsPanel projectSlug={slug!} readOnly={!canEditAssets} />
    </div>
  );

  const renderTerminalView = () => (
    <div className={`w-full h-full ${activeView === 'terminal' ? 'block' : 'hidden'}`}>
      {canAccessTerminal ? (
        <TerminalPanel projectId={slug!} projectUuid={project?.id as string} />
      ) : (
        <div className="w-full h-full flex items-center justify-center">
          <div className="text-center p-6">
            <LockSimple size={48} className="text-[var(--text-subtle)] mx-auto mb-3" />
            <p className="text-[var(--text-subtle)] text-sm font-medium">Terminal access is restricted</p>
            <p className="text-[var(--text-subtle)] text-xs mt-1 opacity-60">Viewers cannot access the terminal</p>
          </div>
        </div>
      )}
    </div>
  );

  const renderContentViews = () => (
    <>
      {renderArchitectureView()}
      {renderPreviewView()}
      {renderCodeView()}
      {renderKanbanView()}
      {renderAssetsView()}
      {renderTerminalView()}
    </>
  );

  // ---------------------------------------------------------------------------
  // Top bar — right side actions
  // ---------------------------------------------------------------------------

  const renderTopBarActions = () => (
    <div className="flex items-center gap-[2px]">
      {/* Architecture-only: Save/Load Config */}
      {activeView === 'architecture' && !isViewer && (
        <>
          <button
            onClick={() => archRef.current?.saveConfig()}
            className="hidden md:flex btn"
            disabled={!archState.configDirty}
          >
            Save Config
          </button>
          <button onClick={() => archRef.current?.loadConfig()} className="hidden md:flex btn">
            Load Config
          </button>
        </>
      )}

      {/* Always visible: Start/Stop All */}
      <button
        onClick={can('container.start_stop') ? handleStartStopAll : undefined}
        className="hidden md:flex btn"
        style={!can('container.start_stop') ? { opacity: 0.35, cursor: 'not-allowed' } : undefined}
      >
        {isEnvironmentRunning ? 'Stop All' : 'Start All'}
      </button>

      {/* Always visible: Environment Status Badge */}
      {environmentStatus && (
        <div className="hidden md:flex">
          <EnvironmentStatusBadge status={environmentStatus} showTooltip />
        </div>
      )}

      <div className="w-px h-[22px] bg-[var(--border)] mx-0.5 hidden md:block" />

      {/* Always visible: Deploy Button with Dropdown */}
      <div className="relative">
        <button
          onClick={canDeploy ? () => setShowDeploymentsDropdown(!showDeploymentsDropdown) : undefined}
          className="btn btn-filled"
          style={!canDeploy ? { opacity: 0.35, cursor: 'not-allowed' } : undefined}
          title={!canDeploy ? 'Deployment restricted for viewers' : undefined}
        >
          {!canDeploy && <LockSimple size={13} weight="bold" />}
          <Rocket size={15} weight="bold" />
          <span className="hidden md:inline">Deploy</span>
        </button>
        <DeploymentsDropdown
          projectSlug={slug!}
          isOpen={showDeploymentsDropdown}
          onClose={() => setShowDeploymentsDropdown(false)}
          onOpenDeployModal={() => setShowDeployModal(true)}
          assignedDeploymentTarget={
            container?.deployment_provider as 'vercel' | 'netlify' | 'cloudflare' | null | undefined
          }
          containerName={container?.name as string | undefined}
        />
      </div>
    </div>
  );

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="h-screen flex overflow-hidden bg-[var(--sidebar-bg)]">
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

      {/* Mobile Menu */}
      <MobileMenu leftItems={leftSidebarItems} rightItems={mobileRightItems} />

      {/* Navigation Sidebar */}
      <NavigationSidebar
        activePage="builder"
        onExpandedChange={setIsLeftSidebarExpanded}
        builderSection={({
          isExpanded,
          navButtonClass,
          navButtonClassCollapsed,
          iconClass,
          labelClass,
          _inactiveNavButton,
          _inactiveNavButtonCollapsed,
          inactiveIconClass,
          inactiveLabelClass,
        }) => (
          <>
            {/* Project name / back to projects */}
            {isExpanded ? (
              <button onClick={() => navigate('/dashboard')} className={navButtonClass(false)}>
                <ArrowLeft size={16} className={inactiveIconClass} />
                <span className={`${inactiveLabelClass} truncate`}>
                  {project?.name || 'Project'}
                </span>
              </button>
            ) : (
              <Tooltip content={project?.name || 'Back to Projects'} side="right" delay={200}>
                <button
                  onClick={() => navigate('/dashboard')}
                  className={navButtonClassCollapsed(false)}
                >
                  <ArrowLeft size={16} className={inactiveIconClass} />
                </button>
              </Tooltip>
            )}

            <div className="h-px bg-[var(--sidebar-border)] my-1.5 mx-3 flex-shrink-0" />

            {/* View Toggles */}
            {leftSidebarItems.map((item, index) =>
              isExpanded ? (
                <button
                  key={index}
                  onClick={item.disabled ? undefined : item.onClick}
                  className={navButtonClass(item.active || false)}
                  style={item.disabled ? { opacity: 0.35, cursor: 'not-allowed' } : undefined}
                >
                  {React.cloneElement(item.icon, {
                    size: 16,
                    className: iconClass(item.active || false),
                  })}
                  <span className={labelClass(item.active || false)}>{item.title}</span>
                  {item.restricted && (
                    <span className="ml-auto text-[9px] font-medium uppercase tracking-wider text-[var(--text-subtle)] opacity-50">
                      {item.disabled ? 'locked' : 'view'}
                    </span>
                  )}
                </button>
              ) : (
                <Tooltip key={index} content={item.restricted ? `${item.title} ${item.disabled ? '(Locked)' : '(View only)'}` : item.title} side="right" delay={200}>
                  <button
                    onClick={item.disabled ? undefined : item.onClick}
                    className={navButtonClassCollapsed(item.active || false)}
                    style={item.disabled ? { opacity: 0.35, cursor: 'not-allowed' } : undefined}
                  >
                    {React.cloneElement(item.icon, {
                      size: 16,
                      className: iconClass(item.active || false),
                    })}
                  </button>
                </Tooltip>
              )
            )}

            <div className="h-px bg-[var(--sidebar-border)] my-1.5 mx-3 flex-shrink-0" />

            {/* Panel Toggles */}
            {panelItems.map((item, index) =>
              isExpanded ? (
                <button
                  key={index}
                  onClick={item.disabled ? undefined : item.onClick}
                  className={navButtonClass(item.active)}
                  style={item.disabled ? { opacity: 0.35, cursor: 'not-allowed' } : undefined}
                >
                  {React.cloneElement(item.icon, { className: iconClass(item.active) })}
                  <span className={labelClass(item.active)}>{item.title}</span>
                  {item.restricted && (
                    <span className="ml-auto text-[9px] font-medium uppercase tracking-wider text-[var(--text-subtle)] opacity-50">
                      locked
                    </span>
                  )}
                </button>
              ) : (
                <Tooltip key={index} content={item.restricted ? `${item.title} (Locked)` : item.title} side="right" delay={200}>
                  <button
                    onClick={item.disabled ? undefined : item.onClick}
                    className={navButtonClassCollapsed(item.active)}
                    style={item.disabled ? { opacity: 0.35, cursor: 'not-allowed' } : undefined}
                  >
                    {React.cloneElement(item.icon, { className: iconClass(item.active) })}
                  </button>
                </Tooltip>
              )
            )}
          </>
        )}
      />

      {/* Main Content Area */}
      <div
        className="flex-1 flex flex-col overflow-hidden"
        style={{
          borderRadius: 'var(--radius)',
          margin: 'var(--app-margin)',
          marginLeft: '0',
          border: 'var(--border-width) solid var(--border)',
          backgroundColor: 'var(--bg)',
        }}
      >
        {/* Top Bar */}
        <div
          className="h-10 border-b border-[var(--border)] flex items-center justify-between flex-shrink-0"
          style={{ paddingLeft: '7px', paddingRight: '10px' }}
        >
          <div className="flex items-center gap-2 flex-1 min-w-0">
            <Breadcrumbs
              items={[
                { label: 'Projects', href: '/dashboard' },
                { label: project.name as string, href: `/project/${slug}` },
                { label: VIEW_LABELS[activeView] },
              ]}
            />

            {/* Container Selector — visible for all views except architecture */}
            {activeView !== 'architecture' && containers.length > 0 && (
              <div className="hidden md:flex items-center border-l border-[var(--border)] pl-2">
                <ContainerSelector
                  containers={containers.map((c) => ({
                    id: c.id as string,
                    name: c.name as string,
                    status: c.status as string,
                    base: c.base as { slug: string; name: string } | undefined,
                  }))}
                  currentContainerId={containerId || (container?.id as string)}
                  onChange={(id) => navigate(`/project/${slug}?container=${id}`)}
                  onOpenArchitecture={() => setActiveView('architecture')}
                />
              </div>
            )}
          </div>

          {renderTopBarActions()}
        </div>

        {/* Main View Container */}
        <div className="flex-1 flex overflow-hidden bg-[var(--bg)]">
          {/* Desktop layout */}
          <div className="hidden md:flex w-full h-full">
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
                      <ChatContainer {...chatProps} isDocked={true} />
                    </Panel>
                    <PanelResizeHandle className="w-2 bg-transparent cursor-col-resize [&[data-separator='hover']]:bg-[var(--primary)]/20 [&[data-separator='active']]:bg-[var(--primary)]/40" />
                  </>
                )}

                {/* MAIN CONTENT PANEL */}
                <Panel id="content" minSize="30" className="overflow-hidden">
                  {renderContentViews()}
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
                      <ChatContainer {...chatProps} isDocked={true} />
                    </Panel>
                  </>
                )}
              </PanelGroup>
            ) : (
              /* CENTER MODE: No PanelGroup wrapper */
              <div className="w-full h-full overflow-hidden">{renderContentViews()}</div>
            )}
          </div>

          {/* Mobile layout */}
          <div className="md:hidden w-full h-full overflow-hidden">
            {/* Mobile preview — simplified (no browser toolbar) */}
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

            {/* Mobile code view */}
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
                readOnly={!canEditAssets}
              />
            </div>

            {/* Mobile kanban */}
            {kanbanMounted && project?.id && (
              <div className={`w-full h-full ${activeView === 'kanban' ? 'block' : 'hidden'}`}>
                <KanbanPanel projectId={project.id as string} readOnly={!canEditKanban} />
              </div>
            )}

            {/* Mobile assets */}
            <div className={`w-full h-full ${activeView === 'assets' ? 'block' : 'hidden'}`}>
              <AssetsPanel projectSlug={slug!} readOnly={!canEditAssets} />
            </div>

            {/* Mobile terminal */}
            <div className={`w-full h-full ${activeView === 'terminal' ? 'block' : 'hidden'}`}>
              {canAccessTerminal ? (
                <TerminalPanel projectId={slug!} projectUuid={project?.id as string} />
              ) : (
                <div className="w-full h-full flex items-center justify-center">
                  <div className="text-center p-6">
                    <LockSimple size={48} className="text-[var(--text-subtle)] mx-auto mb-3" />
                    <p className="text-[var(--text-subtle)] text-sm">Terminal access is restricted</p>
                  </div>
                </div>
              )}
            </div>

            {/* Mobile architecture (no architecture on mobile — placeholder) */}
            <div
              className={`w-full h-full ${activeView === 'architecture' ? 'flex' : 'hidden'} items-center justify-center`}
            >
              <div className="text-center p-6">
                <TreeStructure size={48} className="text-[var(--text-subtle)] mx-auto mb-3" />
                <p className="text-[var(--text-subtle)] text-sm">
                  Architecture view is best experienced on desktop.
                </p>
                <button onClick={() => setActiveView('preview')} className="mt-3 btn btn-filled">
                  Switch to Preview
                </button>
              </div>
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
        defaultPosition={{ x: (isLeftSidebarExpanded ? 244 : 48) + 8, y: 60 }}
        defaultSize={{ width: 420, height: 620 }}
      >
        <GitHubPanel projectId={project?.id} />
      </FloatingPanel>

      <FloatingPanel
        title="Notes & Tasks"
        icon={<BookOpen size={20} />}
        isOpen={activePanel === 'notes'}
        onClose={() => setActivePanel(null)}
        defaultPosition={{ x: (isLeftSidebarExpanded ? 244 : 48) + 8, y: 60 }}
      >
        <NotesPanel projectSlug={slug!} />
      </FloatingPanel>

      <FloatingPanel
        title="Settings"
        icon={<Gear size={20} />}
        isOpen={activePanel === 'settings'}
        onClose={() => setActivePanel(null)}
        defaultPosition={{ x: (isLeftSidebarExpanded ? 244 : 48) + 8, y: 60 }}
      >
        <SettingsPanel projectSlug={slug!} />
      </FloatingPanel>

      {/* FLOATING CHAT — mobile always, desktop only when center mode */}
      {agents.length > 0 && (
        <div className={chatPosition !== 'center' ? 'md:hidden' : ''}>
          <ChatContainer {...chatProps} onExpandedChange={setChatExpanded} />
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
