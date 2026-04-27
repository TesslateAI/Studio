import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useParams, useNavigate, useSearchParams, useLocation } from 'react-router-dom';
import { useHotkeys } from 'react-hotkeys-hook';
import {
  Monitor,
  Code,
  Image,
  Storefront,
  Rocket,
  Kanban,
  Terminal,
  TreeStructure,
  LockSimple,
  PencilRuler,
  SidebarSimple,
  Chat,
  Plus,
  GithubLogo,
  Clock,
  BookOpen,
  Gear,
} from '@phosphor-icons/react';
import { Tooltip } from '../components/ui/Tooltip';
import { Breadcrumbs } from '../components/ui/Breadcrumbs';
import { ChatContainer } from '../components/chat/ChatContainer';
import { ContainerLoadingOverlay } from '../components/ContainerLoadingOverlay';
import { TimelinePanel } from '../components/panels/TimelinePanel';
import { NoComputePlaceholder } from '../components/NoComputePlaceholder';
import { useContainerStartup } from '../hooks/useContainerStartup';
import { useFileTree } from '../hooks/useFileTree';
import { useToolDock, type ToolType, type TabInstance } from '../hooks/useToolDock';
import { ToolTabsPanel, type TabRenderer } from '../components/project/ToolTabsPanel';
import { PreviewPane } from '../components/project/PreviewPane';
import {
  NotesPanel,
  SettingsPanel,
  AssetsPanel,
  KanbanPanel,
  TerminalPanel,
  RepositoryPanel,
  NodeConfigPanel,
} from '../components/panels';
import {
  NodeConfigPendingProvider,
  useNodeConfigPending,
} from '../contexts/NodeConfigPendingContext';
import { AgentRunsProvider } from '../contexts/AgentRunsProvider';
import {
  useBuilderShell,
  useRegisterBuilderSection,
} from '../contexts/BuilderShellContext';
import { nodeConfigEvents } from '../utils/nodeConfigEvents';
import { nodeConfigApi } from '../lib/api';
import { DeploymentModal } from '../components/modals/DeploymentModal';
import { ProviderConnectModal } from '../components/modals/ProviderConnectModal';
import { DeployHubDrawer } from '../components/deploy/DeployHubDrawer';
import CodeEditor from '../components/CodeEditor';
import { ContainerSelector, PROJECT_ROOT_ID } from '../components/ContainerSelector';
import { type PreviewableContainer } from '../components/PreviewPortPicker';
import {
  ArchitectureView,
  type ArchitectureViewHandle,
} from '../components/views/ArchitectureView';
import DesignView from '../components/views/DesignView';
import { projectsApi, marketplaceApi } from '../lib/api';
import PublishAsAppDrawer from '../components/apps/PublishAsAppDrawer';
import { inspectorFocusEvents } from '../utils/inspectorFocusEvents';
import { useCommandHandlers, type ViewType } from '../contexts/CommandContext';
import { useChatPosition } from '../contexts/ChatPositionContext';
import { useTeam } from '../contexts/TeamContext';
import toast from 'react-hot-toast';
import { fileEvents } from '../utils/fileEvents';
import { Panel, Group as PanelGroup, Separator as PanelResizeHandle } from 'react-resizable-panels';
import { type ChatAgent } from '../types/chat';
import { getFeatures, type ComputeTier } from '../types/project';
import { getEnvironmentStatus } from '../components/ui/environmentStatus';
import IdleWarningBanner from '../components/IdleWarningBanner';
import { VolumeHealthBanner } from '../components/VolumeHealthBanner';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

const TOOL_LABELS: Record<ToolType, string> = {
  architecture: 'Architecture',
  preview: 'Preview',
  code: 'Code',
  design: 'Design',
  kanban: 'Kanban',
  assets: 'Assets',
  terminal: 'Terminal',
  repository: 'Repository',
  'node-config': 'Configure',
  volume: 'Snapshots',
  notes: 'Notes',
  settings: 'Settings',
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

function ProjectPageInner() {
  const { slug } = useParams<{ slug: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const containerId = searchParams.get('container');

  const { chatPosition } = useChatPosition();
  const { can, teamSwitchKey } = useTeam();
  const isBuilderPath = location.pathname.endsWith('/builder');

  // RBAC: viewer-level restriction flags
  const isViewer = !can('chat.send');
  const canChat = can('chat.send');
  const canEditKanban = can('kanban.edit');
  const canAccessTerminal = can('terminal.access');
  const canEditSettings = can('project.settings');
  const canDeploy = can('deployment.create');
  const canEditAssets = can('file.write');

  // Redirect to dashboard when the active team changes — the current project
  // belongs to the old team and should no longer be displayed.
  const teamSwitchRef = useRef(teamSwitchKey);
  useEffect(() => {
    if (teamSwitchRef.current !== teamSwitchKey) {
      teamSwitchRef.current = teamSwitchKey;
      navigate('/dashboard');
    }
  }, [teamSwitchKey, navigate]);

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

  // Tool dock (tabs only — preview is a regular tab in this model).
  const dock = useToolDock(slug);
  const { markPending, clearPending } = useNodeConfigPending();
  const activeTabType: ToolType | null = useMemo(() => {
    const active = dock.state.tabs.find((t) => t.id === dock.state.activeTabId);
    return active?.type ?? null;
  }, [dock.state]);

  // Agent-driven node configuration event wiring. Events are emitted by
  // `useAgentChat` when the corresponding SSE events arrive on the chat stream;
  // we translate them into dock + canvas updates here.
  useEffect(() => {
    const unsubs: Array<() => void> = [];

    unsubs.push(
      nodeConfigEvents.on('architecture-node-added', () => {
        if (slug) {
          projectsApi
            .getContainers(slug)
            .then(setContainers)
            .catch(() => {});
        }
      })
    );

    unsubs.push(
      nodeConfigEvents.on('user-input-required', (payload) => {
        if (!project?.id) return;
        dock.openNodeConfigTab({
          projectId: project.id as string,
          containerId: payload.container_id,
          containerName: payload.container_name,
          schema: payload.schema,
          initialValues: payload.initial_values,
          mode: payload.mode,
          preset: payload.preset,
          agentInputId: payload.input_id,
        });
        markPending(payload.container_id);
      })
    );

    unsubs.push(
      nodeConfigEvents.on('node-config-resumed', (payload) => {
        dock.closeNodeConfigTabByInputId(payload.input_id);
        clearPending(payload.container_id);
        if (slug) {
          projectsApi
            .getContainers(slug)
            .then(setContainers)
            .catch(() => {});
        }
        const parts: string[] = [];
        if (payload.updated_keys.length) parts.push(`${payload.updated_keys.length} updated`);
        if (payload.rotated_secrets.length) parts.push(`${payload.rotated_secrets.length} rotated`);
        if (payload.cleared_secrets.length) parts.push(`${payload.cleared_secrets.length} cleared`);
        toast.success(parts.length > 0 ? `Config saved · ${parts.join(', ')}` : 'Config saved');
      })
    );

    unsubs.push(
      nodeConfigEvents.on('node-config-cancelled', (payload) => {
        dock.closeNodeConfigTabByInputId(payload.input_id);
        clearPending(payload.container_id);
        toast('Config cancelled', { icon: 'ℹ️' });
      })
    );

    unsubs.push(
      nodeConfigEvents.on('open-config-tab-request', async (payload) => {
        try {
          const cfg = await nodeConfigApi.getContainerConfig(
            payload.projectId,
            payload.containerId
          );
          dock.openNodeConfigTab({
            projectId: payload.projectId,
            containerId: payload.containerId,
            containerName: payload.containerName,
            schema: cfg.schema,
            initialValues: cfg.values,
            mode: 'edit',
            preset: cfg.preset,
          });
        } catch (err) {
          const message = err instanceof Error ? err.message : 'Failed to load container config';
          toast.error(message);
        }
      })
    );

    unsubs.push(
      nodeConfigEvents.on('secret-rotated', (payload) => {
        if (slug) {
          projectsApi
            .getContainers(slug)
            .then(setContainers)
            .catch(() => {});
        }
        toast(`Secret rotated: ${payload.keys.join(', ')}`, { icon: '🔐' });
      })
    );

    return () => {
      for (const u of unsubs) u();
    };
  }, [slug, project?.id, dock, markPending, clearPending]);

  // Chat pane visibility — collapsible so the dock can take the full canvas.
  // Persisted globally so the preference survives project switches.
  const [isChatVisible, setIsChatVisible] = useState<boolean>(() => {
    if (typeof window === 'undefined') return true;
    const saved = window.localStorage.getItem('tesslate-chat-visible');
    return saved === null ? true : saved === 'true';
  });

  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem('tesslate-chat-visible', String(isChatVisible));
  }, [isChatVisible]);

  const toggleChatVisible = useCallback(() => {
    setIsChatVisible((v) => {
      const next = !v;
      // Hiding chat with an empty dock would leave a blank canvas —
      // auto-open a Preview tab so there is always content.
      if (!next && !dock.isOpen) dock.openTool('preview');
      return next;
    });
  }, [dock]);

  // Architecture ref + state for top bar
  const archRef = useRef<ArchitectureViewHandle>(null);
  const [archState, setArchState] = useState({ configDirty: false, isRunning: false });

  // Publish-as-App drawer state. Lives at the project level so the
  // toolbar button (above the dock), the architecture canvas button, and
  // the command palette all open the same drawer instance. The drawer
  // owns its own draft fetch (one source of truth) — a parent pre-fetch
  // would race with the drawer's own effect when the response landed
  // after mount.
  const [isPublishOpen, setIsPublishOpen] = useState(false);

  // Zen mode is declared near the BuilderShell destructure below.

  const [devServerUrl, setDevServerUrl] = useState<string | null>(null);
  const [devServerUrlWithAuth, setDevServerUrlWithAuth] = useState<string | null>(null);
  const [currentPreviewUrl, setCurrentPreviewUrl] = useState<string>('');
  const { isLeftSidebarExpanded, setIsLeftSidebarExpanded } = useBuilderShell();

  // Zen mode hides the chat panel and collapses the navigation rail; ⌘⇧\.
  // Derived: if both are already hidden we restore them; otherwise hide both.
  const toggleZenMode = useCallback(() => {
    const inZen = !isChatVisible && !isLeftSidebarExpanded;
    setIsChatVisible(inZen);
    setIsLeftSidebarExpanded(inZen);
  }, [isChatVisible, isLeftSidebarExpanded, setIsLeftSidebarExpanded]);

  const toggleNavRail = useCallback(() => {
    setIsLeftSidebarExpanded(!isLeftSidebarExpanded);
  }, [isLeftSidebarExpanded, setIsLeftSidebarExpanded]);
  // Unified Deploy hub — replaces the legacy DeploymentsDropdown + standalone
  // "Publish as App" entry. The hub fans out to PublishAsAppDrawer (hero),
  // the architecture canvas (graph deeplink), and DeploymentModal /
  // ProviderConnectModal (per-provider quick deploy).
  const [isDeployHubOpen, setIsDeployHubOpen] = useState(false);
  const [showDeployModal, setShowDeployModal] = useState(false);
  const [deployModalProvider, setDeployModalProvider] = useState<string | undefined>(undefined);
  const [providerConnectTarget, setProviderConnectTarget] = useState<string | null>(null);
  const [marketplaceFocus, setMarketplaceFocus] = useState<{
    category: string;
    nonce: number;
  } | null>(null);
  const [deployHubRefreshNonce, setDeployHubRefreshNonce] = useState(0);
  const [prefillChatMessage, setPrefillChatMessage] = useState<string | null>(null);

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

  // Selection-aware chat: DesignView dispatches `tesslate:design-ask-ai`
  // when the user asks the AI about the currently selected element.
  // We forward it as a chat prefill so the user can type their question
  // after the element reference.
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<{ prefill?: string }>).detail;
      if (detail?.prefill) {
        setPrefillChatMessage(detail.prefill);
      }
    };
    window.addEventListener('tesslate:design-ask-ai', handler);
    return () => window.removeEventListener('tesslate:design-ask-ai', handler);
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

  const loadAgents = async () => {
    try {
      const libraryData = await marketplaceApi.getMyAgents();
      const enabledAgents = libraryData.agents.filter(
        (agent: Record<string, unknown>) =>
          agent.is_enabled && !agent.is_admin_disabled && !agent.is_system
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
          const containersMap = status?.containers as Record<string, unknown> | null | undefined;
          const containerStatus = (containersMap?.[dirKey!] ??
            containersMap?.[nameKey!] ??
            null) as Record<string, unknown> | null;

          const statusContainers =
            (status?.containers as Record<string, Record<string, unknown>> | null | undefined) ??
            null;
          const previewable = buildPreviewableContainers(
            allContainers,
            statusContainers,
            foundContainer.id as string
          );
          setPreviewableContainers(previewable);

          if (freshProject.environment_status === 'setup_failed') {
            toast.error('This project failed to set up. Please delete it and create a new one.', {
              duration: 5000,
            });
            navigate('/dashboard');
            return;
          }

          if (
            status?.environment_status === 'stopping' ||
            freshProject.environment_status === 'stopping'
          ) {
            setEnvironmentStopping(true);
            return;
          }

          // Hibernation — show start button instead of redirecting
          if (
            containerStatus?.status === 'hibernated' ||
            status?.environment_status === 'hibernated'
          ) {
            containerStartup.reset();
            setNeedsContainerStart(false);
            setDevServerUrl(null);
            return;
          }

          if (containerStatus?.running && containerStatus?.url) {
            containerStartup.reset();
            setNeedsContainerStart(false);
            setDevServerUrl(containerStatus.url as string);
            setDevServerUrlWithAuth(containerStatus.url as string);
            setCurrentPreviewUrl(containerStatus.url as string);
            cancelFileRetry();
            loadFilesWithRetry();
            return;
          }

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
        } catch (statusError) {
          console.warn('Failed to check container status, will attempt start:', statusError);
        }

        if (needsContainerStart && containerStartup.isLoading) return;

        const liveComputeState = status?.compute_state as string | undefined;
        const effectiveComputeTier =
          liveComputeState ?? (freshProject.compute_tier as string) ?? 'none';
        if (effectiveComputeTier !== 'environment') {
          containerStartup.reset();
          setNeedsContainerStart(false);
          return;
        }

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

  const refreshPreview = useCallback(() => {
    if (devServerUrlWithAuth) {
      const iframe = iframeRef.current;
      if (iframe) {
        const url = new URL(devServerUrlWithAuth);
        url.searchParams.set('t', Date.now().toString());
        iframe.src = url.toString();
      }
    }
  }, [devServerUrlWithAuth]);

  const navigateBack = useCallback(() => {
    const iframe = iframeRef.current;
    if (iframe && iframe.contentWindow) {
      iframe.contentWindow.postMessage({ type: 'navigate', direction: 'back' }, '*');
    }
  }, []);

  const navigateForward = useCallback(() => {
    const iframe = iframeRef.current;
    if (iframe && iframe.contentWindow) {
      iframe.contentWindow.postMessage({ type: 'navigate', direction: 'forward' }, '*');
    }
  }, []);

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
        projectSlug={slug}
        onRetry={containerStartup.retry}
        onAskAgent={handleAskAgent}
        containerPort={(container?.internal_port as number) || 3000}
      />
    ) : null;

  const codeEditorOverlay = hasFiles ? undefined : (loadingOverlay ?? undefined);

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

  // Explicit lifecycle commands — separate from the toggle button so command-
  // palette / keyboard invocations have predictable semantics (Run only starts;
  // Stop only stops; Restart cycles).
  const handleRunProject = useCallback(async () => {
    if (!slug) return;
    if (isEnvironmentRunning) {
      toast('Environment already running', { icon: 'ℹ️' });
      return;
    }
    try {
      toast.loading('Starting environment...', { id: 'env-toggle' });
      await projectsApi.startAllContainers(slug);
      toast.success('Environment started!', { id: 'env-toggle', duration: 2000 });
      const p = await projectsApi.get(slug);
      setProject(p);
      loadContainer();
    } catch (error) {
      console.error('runProject failed:', error);
      toast.error('Failed to start environment', { id: 'env-toggle' });
    }
  }, [slug, isEnvironmentRunning]);

  const handleStopProject = useCallback(async () => {
    if (!slug) return;
    if (!isEnvironmentRunning) {
      toast('Environment is not running', { icon: 'ℹ️' });
      return;
    }
    try {
      toast.loading('Stopping environment...', { id: 'env-toggle' });
      await projectsApi.stopAllContainers(slug);
      toast.success('Environment stopped', { id: 'env-toggle', duration: 2000 });
      const p = await projectsApi.get(slug);
      setProject(p);
      loadContainer();
    } catch (error) {
      console.error('stopProject failed:', error);
      toast.error('Failed to stop environment', { id: 'env-toggle' });
    }
  }, [slug, isEnvironmentRunning]);

  const handleRestartProject = useCallback(async () => {
    if (!slug) return;
    try {
      toast.loading('Restarting environment...', { id: 'env-toggle' });
      if (isEnvironmentRunning) {
        await projectsApi.stopAllContainers(slug);
      }
      await projectsApi.startAllContainers(slug);
      toast.success('Environment restarted!', { id: 'env-toggle', duration: 2000 });
      const p = await projectsApi.get(slug);
      setProject(p);
      loadContainer();
    } catch (error) {
      console.error('restartProject failed:', error);
      toast.error('Failed to restart environment', { id: 'env-toggle' });
    }
  }, [slug, isEnvironmentRunning]);

  // ---------------------------------------------------------------------------
  // Dock / tool helpers
  // ---------------------------------------------------------------------------

  const isDesktop = typeof window !== 'undefined' ? window.innerWidth >= 768 : true;

  const openToolAndShowDock = useCallback(
    (tool: ToolType, options?: { forceNew?: boolean }) => {
      if (options?.forceNew) dock.openToolNew(tool);
      else dock.openTool(tool);
    },
    [dock]
  );

  // If builder deep-link was used, open Preview by default on first load
  const builderBootedRef = useRef(false);
  useEffect(() => {
    if (!isBuilderPath || builderBootedRef.current) return;
    builderBootedRef.current = true;
    if (dock.state.tabs.length === 0) {
      dock.openTool('preview');
    }
  }, [isBuilderPath, dock]);

  // ---------------------------------------------------------------------------
  // Keyboard shortcuts
  // ---------------------------------------------------------------------------

  useHotkeys(
    'mod+1',
    (e) => {
      e.preventDefault();
      openToolAndShowDock('architecture');
    },
    { enableOnFormTags: false }
  );
  useHotkeys(
    'mod+2',
    (e) => {
      e.preventDefault();
      openToolAndShowDock('preview');
    },
    { enableOnFormTags: false }
  );
  useHotkeys(
    'mod+3',
    (e) => {
      e.preventDefault();
      openToolAndShowDock('code');
    },
    { enableOnFormTags: false }
  );
  useHotkeys(
    'mod+4',
    (e) => {
      e.preventDefault();
      openToolAndShowDock('design');
    },
    { enableOnFormTags: false }
  );
  useHotkeys(
    'mod+5',
    (e) => {
      e.preventDefault();
      openToolAndShowDock('kanban');
    },
    { enableOnFormTags: false }
  );
  useHotkeys(
    'mod+6',
    (e) => {
      e.preventDefault();
      openToolAndShowDock('assets');
    },
    { enableOnFormTags: false }
  );
  useHotkeys(
    'mod+7',
    (e) => {
      e.preventDefault();
      if (!canAccessTerminal) return;
      openToolAndShowDock('terminal');
    },
    { enableOnFormTags: false }
  );
  useHotkeys(
    'mod+8',
    (e) => {
      e.preventDefault();
      openToolAndShowDock('repository');
    },
    { enableOnFormTags: false }
  );
  useHotkeys(
    'mod+r',
    (e) => {
      e.preventDefault();
      if (dock.hasType('preview')) refreshPreview();
    },
    { enableOnFormTags: false }
  );
  useHotkeys(
    'mod+b',
    (e) => {
      e.preventDefault();
      toggleChatVisible();
    },
    { enableOnFormTags: false }
  );
  useHotkeys(
    'mod+shift+g',
    (e) => {
      e.preventDefault();
      dock.openTool('repository');
    },
    { enableOnFormTags: false }
  );
  useHotkeys(
    'mod+shift+n',
    (e) => {
      e.preventDefault();
      dock.openTool('notes');
    },
    { enableOnFormTags: false }
  );
  useHotkeys(
    'mod+shift+s',
    (e) => {
      e.preventDefault();
      dock.openTool('settings');
    },
    { enableOnFormTags: false }
  );
  useHotkeys(
    'mod+shift+a',
    (e) => {
      e.preventDefault();
      dock.openTool('architecture');
    },
    { enableOnFormTags: false }
  );
  // Project lifecycle
  useHotkeys(
    'mod+e',
    (e) => {
      e.preventDefault();
      handleRunProject();
    },
    { enableOnFormTags: false }
  );
  useHotkeys(
    'mod+shift+e',
    (e) => {
      e.preventDefault();
      handleStopProject();
    },
    { enableOnFormTags: false }
  );
  useHotkeys(
    'mod+shift+r',
    (e) => {
      e.preventDefault();
      handleRestartProject();
    },
    { enableOnFormTags: false }
  );
  // Layout
  useHotkeys(
    'mod+\\',
    (e) => {
      e.preventDefault();
      toggleNavRail();
    },
    { enableOnFormTags: false }
  );
  useHotkeys(
    'mod+shift+\\',
    (e) => {
      e.preventDefault();
      toggleZenMode();
    },
    { enableOnFormTags: false }
  );

  // ---------------------------------------------------------------------------
  // Effects
  // ---------------------------------------------------------------------------

  useEffect(() => {
    if (slug) {
      loadProject();
      loadDevServerUrl();
      loadAgents();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug]);

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

  useEffect(() => {
    if (container) {
      if (project?.volume_id) return;
      cancelFileRetry();
      loadFilesWithRetry();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [container, project?.volume_id]);

  useEffect(() => {
    return () => {
      if (refreshTimeoutRef.current) clearTimeout(refreshTimeoutRef.current);
    };
  }, []);

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

  useEffect(() => {
    if (devServerUrl) setCurrentPreviewUrl(devServerUrl);
  }, [devServerUrl]);

  // Health poll — detect pod death after container is ready.
  // If health fails twice in a row, clear the preview and re-enter loadContainer.
  useEffect(() => {
    if (!devServerUrl || !slug || !currentContainerIdRef.current) return;
    if (containerStartup.isLoading) return; // Don't poll during startup

    let failCount = 0;
    const id = setInterval(async () => {
      try {
        const result = await projectsApi.checkContainerHealth(slug, currentContainerIdRef.current!);
        if (result.healthy) {
          failCount = 0;
        } else {
          failCount++;
          if (failCount >= 2) {
            clearInterval(id);
            console.log('[health-poll] Container unhealthy — re-entering startup flow');
            setDevServerUrl(null);
            containerStartup.reset();
            setNeedsContainerStart(false);
            loadContainer();
          }
        }
      } catch {
        failCount++;
        if (failCount >= 2) {
          clearInterval(id);
          setDevServerUrl(null);
          containerStartup.reset();
          setNeedsContainerStart(false);
          loadContainer();
        }
      }
    }, 15000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [devServerUrl, slug, containerStartup.isLoading]);

  // Refresh file tree when the code or design tab becomes active
  useEffect(() => {
    if ((activeTabType === 'code' || activeTabType === 'design') && slug) loadFileTree();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTabType, slug]);

  // Publish action — declared up here (above useCommandHandlers) so the
  // palette command can reference the same callback. Hook order stays stable
  // because this runs on every render before any early returns.
  //
  // Single entry point shared by the project toolbar button, the
  // architecture canvas button, and the command palette `publishProject`
  // action. The legacy `/creator/publish/:appId` page is gone (v9 spec
  // puts the publish flow on the architecture canvas + drawer).
  const canPublish = project?.project_kind !== 'app_runtime' && canEditSettings;
  const handlePublishAsApp = useCallback(() => {
    if (!slug || !canPublish) return;
    setIsPublishOpen(true);
  }, [slug, canPublish]);

  // Register command handlers for CommandPalette
  useCommandHandlers({
    switchView: (view: ViewType) => {
      // Preview is a pinned pane, others are tabs — dock.openTool handles both
      dock.openTool(view);
    },
    togglePanel: (panel) => {
      // Panels were folded into the top tab dock. Map command-palette panel
      // names to their corresponding dock tab.
      switch (panel) {
        case 'github':
          dock.openTool('repository');
          return;
        case 'architecture':
          dock.openTool('architecture');
          return;
        case 'notes':
          dock.openTool('notes');
          return;
        case 'settings':
          dock.openTool('settings');
          return;
        default:
          // 'marketplace' has no project-page equivalent — ignore.
          return;
      }
    },
    refreshPreview,
    runProject: handleRunProject,
    stopProject: handleStopProject,
    restartProject: handleRestartProject,
    toggleLeftSidebar: toggleChatVisible,
    toggleRightSidebar: toggleNavRail,
    toggleZenMode,
    archAutoLayout: () => {
      const ref = archRef.current;
      if (!ref) {
        toast('Open the Architecture view first', { icon: 'ℹ️' });
        dock.openTool('architecture');
        return;
      }
      ref.autoLayout().catch((err) => {
        console.error('archAutoLayout failed', err);
        toast.error('Auto-layout failed');
      });
    },
    archSaveConfig: () => {
      const ref = archRef.current;
      if (!ref) {
        dock.openTool('architecture');
        toast('Open the Architecture view first', { icon: 'ℹ️' });
        return;
      }
      ref.saveConfig().catch((err) => {
        console.error('archSaveConfig failed', err);
        toast.error('Save failed');
      });
    },
    archLoadConfig: () => {
      const ref = archRef.current;
      if (!ref) {
        dock.openTool('architecture');
        toast('Open the Architecture view first', { icon: 'ℹ️' });
        return;
      }
      ref.loadConfig().catch((err) => {
        console.error('archLoadConfig failed', err);
        toast.error('Load failed');
      });
    },
    openTimeline: () => dock.openTool('volume'),
    publishProject: () => {
      // handlePublishAsApp is defined further down — we reference the same
      // callback by name so the palette command and the toolbar button stay
      // in sync.
      handlePublishAsApp();
    },
    forkProject: () => {
      if (project?.id) navigate(`/apps/${project.id}/fork`);
    },
    openProjectOverview: () => {
      if (slug) navigate(`/project/${slug}`);
    },
    viewContainerLogs: () => dock.openTool('terminal'),
    restartContainer: handleRestartProject,
    copyDebugInfo: async () => {
      const debug = {
        slug,
        projectId: project?.id,
        runtime: project?.runtime,
        environmentStatus,
        userAgent: navigator.userAgent,
        timestamp: new Date().toISOString(),
      };
      try {
        await navigator.clipboard.writeText(JSON.stringify(debug, null, 2));
        toast.success('Debug info copied');
      } catch {
        toast.error('Could not copy to clipboard');
      }
    },
  });

  // ---------------------------------------------------------------------------
  // Sidebar registration — must run on every render (not gated by the loading
  // early-return below) so the hook order stays stable when `project` flips
  // from null to populated. (handlePublishAsApp is declared above next to
  // useCommandHandlers so the palette command and the toolbar button share
  // the same callback identity.)
  // ---------------------------------------------------------------------------

  // The builder sidebar is intentionally identical to the dashboard sidebar.
  // No project-specific affordances are injected — going Dashboard ↔ Project
  // should feel like only the main panel changes. Users navigate back via
  // the breadcrumb in the top bar (Projects → ...).
  useRegisterBuilderSection(undefined);

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
  // Top bar — tool buttons
  // ---------------------------------------------------------------------------

  const toolButtonDefs: Array<{
    id: ToolType;
    icon: React.ReactElement;
    hotkey: string;
    disabled?: boolean;
    restricted?: boolean;
  }> = [
    { id: 'architecture', icon: <TreeStructure size={14} weight="bold" />, hotkey: '⌘1' },
    { id: 'preview', icon: <Monitor size={14} weight="bold" />, hotkey: '⌘2' },
    { id: 'code', icon: <Code size={14} weight="bold" />, hotkey: '⌘3' },
    { id: 'design', icon: <PencilRuler size={14} weight="bold" />, hotkey: '⌘4' },
    {
      id: 'kanban',
      icon: <Kanban size={14} weight="bold" />,
      hotkey: '⌘5',
      restricted: !canEditKanban,
    },
    {
      id: 'assets',
      icon: <Image size={14} weight="bold" />,
      hotkey: '⌘6',
      restricted: !canEditAssets,
    },
    {
      id: 'terminal',
      icon: <Terminal size={14} weight="bold" />,
      hotkey: '⌘7',
      disabled: !canAccessTerminal,
      restricted: !canAccessTerminal,
    },
    { id: 'repository', icon: <GithubLogo size={14} weight="bold" />, hotkey: '⌘8' },
    { id: 'volume', icon: <Clock size={14} weight="bold" />, hotkey: '' },
    { id: 'notes', icon: <BookOpen size={14} weight="bold" />, hotkey: '⌘⇧N' },
    {
      id: 'settings',
      icon: <Gear size={14} weight="bold" />,
      hotkey: '⌘⇧S',
      disabled: !canEditSettings,
      restricted: !canEditSettings,
    },
  ];

  const handleToolButtonClick = (id: ToolType, e: React.MouseEvent) => {
    // ⇧-click always creates a new tab instance; a plain click focuses the
    // first existing tab of that type (or creates one if none).
    openToolAndShowDock(id, { forceNew: e.shiftKey });
  };

  const renderToolButtons = () => (
    <div className="flex items-center gap-0.5 border-l border-r border-[var(--border)] px-1 mx-1">
      {toolButtonDefs.map((def) => {
        const active = dock.isActiveType(def.id);
        const count = dock.countOf(def.id);
        const label = TOOL_LABELS[def.id];
        return (
          <Tooltip
            key={def.id}
            content={`${label} ${def.hotkey} · shift-click for new`}
            side="bottom"
            delay={200}
          >
            <button
              onClick={def.disabled ? undefined : (e) => handleToolButtonClick(def.id, e)}
              className={`relative h-7 w-7 flex items-center justify-center rounded-[var(--radius-small)] transition-colors ${
                active
                  ? 'bg-[var(--surface-hover)] text-[var(--primary)]'
                  : count > 0
                    ? 'text-[var(--text)] hover:bg-[var(--surface-hover)]'
                    : 'text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-hover)]'
              }`}
              style={def.disabled ? { opacity: 0.35, cursor: 'not-allowed' } : undefined}
              aria-pressed={active}
              aria-label={label}
            >
              {def.icon}
              {count > 1 && (
                <span className="absolute -top-0.5 -right-0.5 text-[9px] font-semibold leading-none px-1 py-[1px] rounded bg-[var(--primary)]/15 text-[var(--primary)]">
                  {count}
                </span>
              )}
              {def.restricted && !def.disabled && (
                <LockSimple
                  size={9}
                  className="absolute -bottom-0.5 -right-0.5 text-[var(--text-subtle)]"
                />
              )}
            </button>
          </Tooltip>
        );
      })}
    </div>
  );

  // ---------------------------------------------------------------------------
  // Sidebar items (panels only — view toggles moved to top bar)
  // ---------------------------------------------------------------------------

  // ---------------------------------------------------------------------------
  // Chat props
  // ---------------------------------------------------------------------------

  const chatViewContext = activeTabType === 'architecture' ? 'graph' : 'builder';

  // Deep-link from the sidebar: when the user clicks a project-nested chat
  // row we navigate here with `state: { sessionId }`. ChatContainer seeds
  // its currentChatId from this and re-syncs whenever it changes (so
  // clicking another chat in the same project swaps sessions in place).
  const initialChatIdFromRoute =
    (location.state as Record<string, unknown> | null)?.sessionId as string | undefined;

  const chatProps = {
    projectId: project?.id as number,
    containerId: containerId || undefined,
    viewContext: chatViewContext as 'graph' | 'builder',
    agents,
    currentAgent,
    onSelectAgent: handleAgentSelect,
    onFileUpdate: handleFileUpdate,
    slug: slug!,
    projectName: project?.name as string | undefined,
    sidebarExpanded: isLeftSidebarExpanded,
    isPointerOverPreviewRef,
    prefillMessage: prefillChatMessage,
    onPrefillConsumed: () => setPrefillChatMessage(null),
    onIdleWarning: handleIdleWarning,
    onEnvironmentStopping: handleEnvironmentStopping,
    onEnvironmentStopped: handleEnvironmentStopped,
    onVolumeReady: () => {
      if (slug) {
        projectsApi
          .get(slug)
          .then(setProject)
          .catch(() => {});
      }
    },
    disabled: !canChat,
    initialChatId: initialChatIdFromRoute ?? null,
  } as const;

  // ---------------------------------------------------------------------------
  // Tab renderers (keep-alive managed inside ToolTabsPanel)
  //
  // Each renderer receives the TabInstance + its 0-based index within its
  // type, so multiple tabs of the same type can scope their own state.
  // Only the FIRST preview tab owns the shared iframeRef (used by
  // refreshPreview/navigateBack etc). Additional preview tabs get their own
  // iframes but the shared controls continue to target the primary one.
  // ---------------------------------------------------------------------------

  const selectedPreviewContainerId = containerId || (container?.id as string) || null;

  const tabRenderers: Partial<Record<ToolType, TabRenderer>> = {
    architecture: (_tab: TabInstance, _idx: number) => (
      <ArchitectureView
        ref={archRef}
        slug={slug!}
        projectId={project?.id as string}
        isActive={activeTabType === 'architecture'}
        onContainersChanged={() => {
          if (slug)
            projectsApi
              .getContainers(slug)
              .then(setContainers)
              .catch(() => {});
        }}
        onNavigateToContainer={(id) => {
          dock.openTool('preview');
          navigate(`/project/${slug}?container=${id}`);
        }}
        onStateChange={handleArchStateChange}
        readOnly={isViewer}
        onPublishAsApp={canPublish ? handlePublishAsApp : undefined}
        marketplaceFocus={marketplaceFocus}
      />
    ),
    preview: (_tab: TabInstance, idx: number) => (
      <PreviewPane
        // First instance owns the shared iframeRef; others get their own
        // element via null ref so refreshPreview still works predictably.
        ref={idx === 0 ? iframeRef : null}
        devServerUrl={devServerUrl}
        devServerUrlWithAuth={devServerUrlWithAuth}
        currentPreviewUrl={currentPreviewUrl}
        previewableContainers={previewableContainers}
        selectedPreviewContainerId={selectedPreviewContainerId}
        onPreviewContainerSwitch={handlePreviewContainerSwitch}
        onRefresh={refreshPreview}
        onNavigateBack={navigateBack}
        onNavigateForward={navigateForward}
        onPointerEnter={() => {
          isPointerOverPreviewRef.current = true;
        }}
        onPointerLeave={() => {
          isPointerOverPreviewRef.current = false;
        }}
        placeholder={noPreview ? previewPlaceholder : undefined}
        overlay={loadingOverlay ?? undefined}
        showClose={false}
      />
    ),
    code: (_tab: TabInstance, _idx: number) => (
      <CodeEditor
        projectId={project?.id as number}
        slug={slug!}
        fileTree={fileTree}
        containerDir={containerDir}
        onFileUpdate={handleFileUpdate}
        onFileCreate={handleFileCreate}
        onFileDelete={handleFileDelete}
        onFileRename={handleFileRename}
        onDirectoryCreate={handleDirectoryCreate}
        isFilesSyncing={!filesInitiallyLoaded && fileTree.length === 0}
        startupOverlay={codeEditorOverlay}
        readOnly={!canEditAssets}
      />
    ),
    design: (_tab: TabInstance, _idx: number) =>
      project?.id && devServerUrl ? (
        <DesignView
          slug={slug!}
          projectId={project?.id as number}
          fileTree={fileTree}
          devServerUrl={devServerUrl}
          devServerUrlWithAuth={devServerUrlWithAuth || devServerUrl}
          onFileUpdate={handleFileUpdate}
          onFileCreate={handleFileCreate}
          onFileDelete={handleFileDelete}
          onFileRename={handleFileRename}
          onDirectoryCreate={handleDirectoryCreate}
          isFilesSyncing={!filesInitiallyLoaded && fileTree.length === 0}
          containerDir={containerDir}
          onRefreshPreview={refreshPreview}
        />
      ) : (
        <div className="h-full flex items-center justify-center">
          <div className="text-center px-6">
            <PencilRuler size={28} className="mx-auto mb-3 text-[var(--text-subtle)]" />
            <p className="text-xs text-[var(--text-muted)]">
              Start your environment to use the Design view
            </p>
            <p className="text-[10px] text-[var(--text-subtle)] mt-1">
              The visual builder requires a running dev server
            </p>
          </div>
        </div>
      ),
    kanban: (_tab: TabInstance, _idx: number) =>
      project?.id ? (
        <KanbanPanel projectId={project.id as string} readOnly={!canEditKanban} />
      ) : null,
    assets: (_tab: TabInstance, _idx: number) => (
      <AssetsPanel projectSlug={slug!} readOnly={!canEditAssets} />
    ),
    repository: (_tab: TabInstance, _idx: number) => (
      <RepositoryPanel projectSlug={slug!} projectId={project?.id as number | undefined} />
    ),
    'node-config': (tab: TabInstance, _idx: number) => {
      const payload = dock.getNodeConfigPayload(tab.id);
      if (!payload) {
        return (
          <div className="w-full h-full flex items-center justify-center">
            <p className="text-xs text-[var(--text-muted)]">
              This configuration session is no longer available.
            </p>
          </div>
        );
      }
      return (
        <NodeConfigPanel
          projectId={payload.projectId}
          containerId={payload.containerId}
          containerName={payload.containerName}
          schema={payload.schema}
          initialValues={payload.initialValues}
          mode={payload.mode}
          preset={payload.preset}
          agentInputId={payload.agentInputId}
          onClose={() => {
            if (payload.agentInputId) {
              clearPending(payload.containerId);
            }
            dock.closeTab(tab.id);
          }}
        />
      );
    },
    terminal: (tab: TabInstance, _idx: number) =>
      canAccessTerminal ? (
        <TerminalPanel projectId={slug!} projectUuid={project?.id as string} instanceId={tab.id} />
      ) : (
        <div className="w-full h-full flex items-center justify-center">
          <div className="text-center p-6">
            <LockSimple size={48} className="text-[var(--text-subtle)] mx-auto mb-3" />
            <p className="text-[var(--text-subtle)] text-sm font-medium">
              Terminal access is restricted
            </p>
            <p className="text-[var(--text-subtle)] text-xs mt-1 opacity-60">
              Viewers cannot access the terminal
            </p>
          </div>
        </div>
      ),
    volume: (_tab: TabInstance, _idx: number) => (
      <TimelinePanel
        projectId={project?.id as string}
        projectSlug={slug!}
        projectStatus={(project?.environment_status as string) || 'stopped'}
        onRestored={() => {
          loadFilesWithRetry();
          fileEvents.emit('files-changed');
          setDevServerUrl(null);
          containerStartup.reset();
          setNeedsContainerStart(false);
          loadContainer();
        }}
      />
    ),
    notes: (_tab: TabInstance, _idx: number) => <NotesPanel projectSlug={slug!} />,
    settings: (_tab: TabInstance, _idx: number) =>
      canEditSettings ? (
        <SettingsPanel projectSlug={slug!} />
      ) : (
        <div className="w-full h-full flex items-center justify-center">
          <div className="text-center p-6">
            <LockSimple size={48} className="text-[var(--text-subtle)] mx-auto mb-3" />
            <p className="text-[var(--text-subtle)] text-sm font-medium">
              Project settings are restricted
            </p>
            <p className="text-[var(--text-subtle)] text-xs mt-1 opacity-60">
              Viewers cannot edit settings
            </p>
          </div>
        </div>
      ),
  };

  // ---------------------------------------------------------------------------
  // Top bar — right side actions
  // ---------------------------------------------------------------------------

  const renderTopBarActions = () => (
    <div className="flex items-center gap-[2px]">
      {/* Architecture-only: Save/Load Config */}
      {activeTabType === 'architecture' && !isViewer && (
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

      {/* Tool buttons — VS Code style activity bar, inline */}
      <div className="hidden md:flex">{renderToolButtons()}</div>

      {/* Chat visibility toggle — VS Code Cmd+B style */}
      <Tooltip content={`${isChatVisible ? 'Hide' : 'Show'} chat  ⌘B`} side="bottom" delay={200}>
        <button
          onClick={toggleChatVisible}
          className={`hidden md:flex h-7 px-2 items-center gap-1.5 rounded-[var(--radius-small)] text-[11px] font-medium transition-colors ${
            isChatVisible
              ? 'text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-hover)]'
              : 'bg-[var(--surface-hover)] text-[var(--primary)]'
          }`}
          aria-pressed={!isChatVisible}
          aria-label={isChatVisible ? 'Hide chat' : 'Show chat'}
        >
          {isChatVisible ? (
            <SidebarSimple size={14} weight="bold" />
          ) : (
            <Chat size={14} weight="bold" />
          )}
        </button>
      </Tooltip>

      {/* Always visible: Start/Stop All */}
      <button
        onClick={can('container.start_stop') ? handleStartStopAll : undefined}
        className="hidden md:flex btn"
        style={!can('container.start_stop') ? { opacity: 0.35, cursor: 'not-allowed' } : undefined}
      >
        {isEnvironmentRunning ? 'Stop All' : 'Start All'}
      </button>

      <div className="w-px h-[22px] bg-[var(--border)] mx-0.5 hidden md:block" />

      <button
        onClick={canDeploy ? () => setIsDeployHubOpen(true) : undefined}
        className="btn btn-filled"
        style={!canDeploy ? { opacity: 0.35, cursor: 'not-allowed' } : undefined}
        title={!canDeploy ? 'Deployment restricted for viewers' : undefined}
      >
        {!canDeploy && <LockSimple size={13} weight="bold" />}
        <Rocket size={15} weight="bold" />
        <span className="hidden md:inline">Deploy</span>
      </button>
    </div>
  );

  // ---------------------------------------------------------------------------
  // Main layout helpers
  // ---------------------------------------------------------------------------

  const dockOpen = dock.isOpen;
  const chatIsFloating = chatPosition === 'center';
  const chatOnLeft = chatPosition === 'left';
  const hasAgents = agents.length > 0;

  const renderDockedChatPane = () => <ChatContainer {...chatProps} isDocked={true} />;

  const activeDockTabType = dock.state.tabs.find((t) => t.id === dock.state.activeTabId)?.type;
  const dockExtraHeader = (
    <div className="flex items-center gap-1">
      {activeDockTabType === 'terminal' && (
        <Tooltip content="New terminal" side="bottom" delay={200}>
          <button
            onClick={() => dock.openToolNew('terminal')}
            className="flex items-center justify-center h-6 w-6 rounded-[var(--radius-small)] text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-hover)] transition-colors"
            aria-label="New terminal"
          >
            <Plus size={12} weight="bold" />
          </button>
        </Tooltip>
      )}
      {canPublish && (
        <Tooltip content="Publish as App" side="bottom" delay={200}>
          <button
            onClick={handlePublishAsApp}
            className="flex items-center justify-center h-6 w-6 rounded-[var(--radius-small)] text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-hover)] transition-colors"
            aria-label="Publish as App"
          >
            <Rocket size={12} weight="bold" />
          </button>
        </Tooltip>
      )}
    </div>
  );

  const renderDockContainer = () => (
    <ToolTabsPanel
      tabs={dock.state.tabs}
      activeTabId={dock.state.activeTabId}
      onFocus={dock.focusTab}
      onClose={dock.closeTab}
      renderers={tabRenderers}
      extraHeader={dockExtraHeader}
      onReorder={dock.reorderTabs}
    />
  );

  // Desktop: chat + dock horizontal split (when both visible docked) or
  // whichever is alone. Floating chat (center) renders the dock full-width
  // in the main canvas and the chat lives in a separate fixed-position layer.
  const renderDesktopContent = () => {
    if (!hasAgents) {
      return <div className="w-full h-full" />;
    }

    // Floating chat mode: main canvas is dock-only. If the dock is closed,
    // render an empty canvas — the floating chat overlays everything.
    if (chatIsFloating) {
      return (
        <div className="w-full h-full">
          {dockOpen ? renderDockContainer() : <div className="w-full h-full bg-[var(--bg)]" />}
        </div>
      );
    }

    // Chat hidden — dock takes the full canvas.
    if (!isChatVisible && dockOpen) {
      return <div className="w-full h-full">{renderDockContainer()}</div>;
    }

    // Dock closed (or chat hidden with nothing to show) — chat takes full canvas.
    if (!dockOpen) {
      return <div className="w-full h-full flex bg-[var(--bg-dark)]">{renderDockedChatPane()}</div>;
    }

    // Both visible — split. Chat gets a generous default + a hard 33% floor so
    // it never collapses into a sliver when the browser preview is opened.
    return (
      <PanelGroup orientation="horizontal">
        {chatOnLeft ? (
          <>
            <Panel
              id="chat-left"
              defaultSize="50"
              minSize="15"
              maxSize="85"
              className="bg-[var(--bg-dark)] overflow-hidden"
            >
              {renderDockedChatPane()}
            </Panel>
            <PanelResizeHandle className="w-1.5 bg-transparent cursor-col-resize [&[data-separator='hover']]:bg-[var(--primary)]/20 [&[data-separator='active']]:bg-[var(--primary)]/40" />
            <Panel id="dock-right" defaultSize="50" minSize="15" className="overflow-hidden">
              {renderDockContainer()}
            </Panel>
          </>
        ) : (
          <>
            <Panel id="dock-left" defaultSize="50" minSize="15" className="overflow-hidden">
              {renderDockContainer()}
            </Panel>
            <PanelResizeHandle className="w-1.5 bg-transparent cursor-col-resize [&[data-separator='hover']]:bg-[var(--primary)]/20 [&[data-separator='active']]:bg-[var(--primary)]/40" />
            <Panel
              id="chat-right"
              defaultSize="50"
              minSize="15"
              maxSize="85"
              className="bg-[var(--bg-dark)] overflow-hidden"
            >
              {renderDockedChatPane()}
            </Panel>
          </>
        )}
      </PanelGroup>
    );
  };

  // Mobile: dock is always the primary view; chat floats on top via a button
  // (mirrors desktop's chatPosition === 'center' treatment).
  const renderMobileContent = () => {
    if (!hasAgents) return <div className="w-full h-full" />;
    return (
      <div className="w-full h-full">
        {dockOpen ? renderDockContainer() : <div className="w-full h-full bg-[var(--bg)]" />}
      </div>
    );
  };

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <>
      {idleWarningMinutes !== null && slug && (
        <IdleWarningBanner
          minutesLeft={idleWarningMinutes}
          projectSlug={slug}
          onDismiss={() => setIdleWarningMinutes(null)}
        />
      )}

      {/* Volume Health Banner — shows when volume is degraded, with recover controls */}
      {slug && !!project?.volume_id && (
        <VolumeHealthBanner
          projectSlug={slug}
          pollInterval={30000}
          onRecovered={() => {
            loadFileTree();
            loadFilesWithRetry();
          }}
        />
      )}

      {/* Top Bar */}
      <div
        className="h-10 border-b border-[var(--border)] flex items-center justify-between flex-shrink-0"
        style={{ paddingLeft: '18px', paddingRight: '10px' }}
      >
        <div className="flex items-center gap-2 flex-1 min-w-0">
          <Breadcrumbs
            items={[
              { label: 'Projects', href: '/dashboard' },
              { label: project.name as string, href: `/project/${slug}` },
              { label: activeTabType ? TOOL_LABELS[activeTabType] : 'Agents' },
            ]}
          />

          {activeTabType && activeTabType !== 'architecture' && containers.length > 0 && (
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
                onOpenArchitecture={() => dock.openTool('architecture')}
                environmentStatus={environmentStatus}
              />
            </div>
          )}
        </div>

        {renderTopBarActions()}
      </div>

      {/* Main View Container */}
      <div className="flex-1 flex overflow-hidden bg-[var(--bg)]">
        <div className="hidden md:flex w-full h-full">{renderDesktopContent()}</div>
        <div className="md:hidden w-full h-full">{renderMobileContent()}</div>
      </div>

      {/* Floating chat — always on mobile; desktop only when chatPosition === 'center'.
          JS-gated (not CSS) so exactly one ChatContainer mounts at a time and
          left/right docked chat doesn't get cloned into an offscreen instance. */}
      {hasAgents && isChatVisible && (!isDesktop || chatIsFloating) && (
        <ChatContainer {...chatProps} isDocked={false} />
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

      {showDeployModal && (
        <DeploymentModal
          projectSlug={slug!}
          isOpen={showDeployModal}
          onClose={() => {
            setShowDeployModal(false);
            setDeployModalProvider(undefined);
          }}
          onSuccess={() => {
            setShowDeployModal(false);
            setDeployModalProvider(undefined);
            // Hub may show this deployment in the recent list — bump nonce
            // so the next open re-fetches.
            setDeployHubRefreshNonce((n) => n + 1);
            toast.success('Deployment started successfully!');
          }}
          defaultProvider={
            deployModalProvider ??
            (container?.deployment_provider as string | undefined)
          }
        />
      )}

      {/* Unified Deploy hub — toolbar Deploy button opens this. Hands off to
          PublishAsAppDrawer (hero), the architecture canvas (Card B), and
          DeploymentModal / ProviderConnectModal (per-provider quick deploy). */}
      <DeployHubDrawer
        isOpen={isDeployHubOpen}
        onClose={() => setIsDeployHubOpen(false)}
        projectSlug={slug!}
        canPublish={canPublish}
        refreshNonce={deployHubRefreshNonce}
        onOpenPublishDrawer={handlePublishAsApp}
        onOpenArchitectureWithDeploymentCategory={() => {
          dock.openTool('architecture');
          setMarketplaceFocus({ category: 'deployment', nonce: Date.now() });
        }}
        onOpenDeployModal={(provider) => {
          setIsDeployHubOpen(false);
          setDeployModalProvider(provider);
          setShowDeployModal(true);
        }}
        onOpenProviderConnectModal={(provider) => {
          setProviderConnectTarget(provider);
        }}
      />

      {/* ProviderConnectModal triggered from the Deploy hub when a chip
          without credentials is clicked. After connecting, we open the
          DeploymentModal preselected to that provider so the user can
          ship right away without a second trip through the hub. */}
      {providerConnectTarget && (
        <ProviderConnectModal
          isOpen={true}
          defaultProvider={providerConnectTarget}
          onClose={() => setProviderConnectTarget(null)}
          onConnected={(provider) => {
            setProviderConnectTarget(null);
            setDeployHubRefreshNonce((n) => n + 1);
            setIsDeployHubOpen(false);
            setDeployModalProvider(provider);
            setShowDeployModal(true);
          }}
        />
      )}

      {/* Publish-as-App drawer — single instance shared by the project
          toolbar button, the architecture canvas button, and the command
          palette `publishProject` action. The drawer owns its own draft
          fetch on mount. The "Fix in inspector" button is canvas-aware:
          we open the architecture tab and emit a
          publish-inspector-jump-request event; ArchitectureView listens
          and selects the matching React Flow node. */}
      {isPublishOpen && (
        <PublishAsAppDrawer
          projectSlug={slug!}
          projectName={(project?.name as string | undefined) ?? slug!}
          onClose={() => setIsPublishOpen(false)}
          onPublished={() => {
            // Project's app_role / project_kind flips on first publish; the
            // toolbar button label depends on it, so refresh project data.
            loadProject();
          }}
          onJumpToInspector={(target) => {
            setIsPublishOpen(false);
            // Make sure the canvas tab is mounted so it can hear the event.
            dock.openTool('architecture');
            // Defer one rAF tick to let ArchitectureView's effect attach
            // its listener after mounting. inspectorFocusEvents drops the
            // event silently if no one is listening, so without the
            // deferral a fresh-mount canvas would miss the request.
            requestAnimationFrame(() => {
              inspectorFocusEvents.emit('publish-inspector-jump-request', target);
            });
          }}
        />
      )}
    </>
  );
}

function ProjectPageWithRuns() {
  const { projectId } = useParams<{ projectId: string }>();
  return (
    <AgentRunsProvider projectId={projectId ?? null}>
      <ProjectPageInner />
    </AgentRunsProvider>
  );
}

export default function ProjectPage() {
  return (
    <NodeConfigPendingProvider>
      <ProjectPageWithRuns />
    </NodeConfigPendingProvider>
  );
}
