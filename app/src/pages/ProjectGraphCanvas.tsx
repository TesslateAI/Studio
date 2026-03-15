import React, { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { debounce } from 'lodash';
import {
  addEdge,
  useNodesState,
  useEdgesState,
  useReactFlow,
  type Edge,
  type Node,
  type NodeTypes,
  type OnConnect,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {
  ArrowLeft,
  Play,
  Stop,
  Code,
  FlowArrow,
  List,
  Storefront,
  BookOpen,
  GitBranch,
  Gear,
  Article,
  Kanban,
  TreeStructure,
} from '@phosphor-icons/react';
import { motion } from 'framer-motion';
import { ContainerNode } from '../components/ContainerNode';
import { BrowserPreviewNode } from '../components/BrowserPreviewNode';
import { DeploymentTargetNode } from '../components/DeploymentTargetNode';
import { GraphCanvas } from '../components/GraphCanvas';
import { MarketplaceSidebar } from '../components/MarketplaceSidebar';
import { ContainerPropertiesPanel } from '../components/ContainerPropertiesPanel';
import { Breadcrumbs } from '../components/ui/Breadcrumbs';
import { Tooltip } from '../components/ui/Tooltip';
import { MobileWarning } from '../components/MobileWarning';
import { MobileMenu } from '../components/ui/MobileMenu';
import { FloatingPanel } from '../components/ui/FloatingPanel';
import { GitHubPanel, NotesPanel, SettingsPanel, KanbanPanel } from '../components/panels';
import { ChatContainer } from '../components/chat/ChatContainer';
import { DiscordSupport } from '../components/DiscordSupport';
import CodeEditor from '../components/CodeEditor';
import { ExternalServiceCredentialModal } from '../components/ExternalServiceCredentialModal';
import api, { projectsApi, configApi, deploymentTargetsApi, marketplaceApi } from '../lib/api';
import { useTheme } from '../theme/ThemeContext';
import { type ChatAgent } from '../types/chat';
import { fileEvents } from '../utils/fileEvents';
import { connectionEvents } from '../utils/connectionEvents';
import toast from 'react-hot-toast';
import {
  EnvInjectionEdge,
  HttpApiEdge,
  DatabaseEdge,
  CacheEdge,
  BrowserPreviewEdge,
  DeploymentEdge,
  getEdgeType,
} from '../components/edges';
import { getLayoutedElements } from '../utils/autoLayout';

const nodeTypes: NodeTypes = {
  containerNode: ContainerNode,
  browserPreview: BrowserPreviewNode,
  deploymentTarget: DeploymentTargetNode,
};

// Custom edge types for different connector semantics
const edgeTypes = {
  env_injection: EnvInjectionEdge,
  http_api: HttpApiEdge,
  database: DatabaseEdge,
  cache: CacheEdge,
  browser_preview: BrowserPreviewEdge,
  deployment: DeploymentEdge,
};

type PanelType = 'github' | 'notes' | 'settings' | null;
type MainViewType = 'graph' | 'code' | 'kanban';

interface Container {
  id: string;
  name: string;
  base_id: string | null;
  base_name?: string | null;
  position_x: number;
  position_y: number;
  status: 'stopped' | 'starting' | 'running' | 'failed';
  port?: number;
  container_type?: 'base' | 'service';
  service_slug?: string | null;
  service_type?: 'container' | 'external' | 'hybrid' | null;
  icon?: string | null;
  tech_stack?: string[] | null;
  deployment_mode?: string;
  deployment_provider?: string | null;
}

interface ContainerConnection {
  id: string;
  source_container_id: string;
  target_container_id: string;
  connection_type: string;
  connector_type?: string;
  config?: Record<string, unknown> | null;
  label?: string;
}

const ProjectGraphCanvasInner = () => {
  const { slug } = useParams<{ slug: string }>();
  const navigate = useNavigate();
  const { theme } = useTheme();
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const reactFlowInstance = useReactFlow();

  // Refs for stable callback references - prevents node re-renders when parent state changes
  const nodesRef = useRef<Node[]>(nodes);
  const edgesRef = useRef<Edge[]>(edges);
  const filesRef = useRef<Array<Record<string, unknown>>>([]);
  const slugRef = useRef(slug);
  const [project, setProject] = useState<Record<string, unknown> | null>(null);
  const [files, setFiles] = useState<Array<Record<string, unknown>>>([]);
  const [_appDomain, setAppDomain] = useState<string>('localhost');
  const appDomainRef = useRef<string>('localhost');
  const [isRunning, setIsRunning] = useState(false);
  const [activeView, setActiveView] = useState<MainViewType>('graph');
  const [kanbanMounted, setKanbanMounted] = useState(false);
  const [activePanel, setActivePanel] = useState<PanelType>(null);
  const [isLeftSidebarExpanded, setIsLeftSidebarExpanded] = useState(() => {
    const saved = localStorage.getItem('graphCanvasSidebarExpanded');
    return saved !== null ? JSON.parse(saved) : true;
  });
  const [agents, setAgents] = useState<ChatAgent[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(() => {
    if (!slug) return null;
    return localStorage.getItem(`tesslate-graph-agent-${slug}`);
  });
  const [selectedContainer, setSelectedContainer] = useState<{
    id: string;
    name: string;
    status: string;
    port?: number;
    containerType?: 'base' | 'service';
  } | null>(null);

  // Drag state for pausing polling during drag operations - critical for performance
  const [isDragging, setIsDragging] = useState(false);
  const isDraggingRef = useRef(false);

  // External service credential modal state
  const [externalServiceModal, setExternalServiceModal] = useState<{
    isOpen: boolean;
    item: Record<string, unknown> | null;
    position: { x: number; y: number } | null;
  }>({ isOpen: false, item: null, position: null });

  // Keep refs in sync with state - this allows callbacks to access latest values without re-creating
  useEffect(() => {
    nodesRef.current = nodes;
  }, [nodes]);
  useEffect(() => {
    edgesRef.current = edges;
  }, [edges]);

  useEffect(() => {
    filesRef.current = files;
  }, [files]);

  useEffect(() => {
    slugRef.current = slug;
  }, [slug]);

  useEffect(() => {
    isDraggingRef.current = isDragging;
  }, [isDragging]);

  // Lazily mount KanbanPanel on first visit to preserve state across tab switches
  useEffect(() => {
    if (activeView === 'kanban' && !kanbanMounted) {
      setKanbanMounted(true);
    }
  }, [activeView, kanbanMounted]);

  // Fetch app domain config on mount
  useEffect(() => {
    configApi.getAppDomain().then((domain) => {
      setAppDomain(domain);
      appDomainRef.current = domain;
    });
  }, []);

  useEffect(() => {
    if (slug) {
      fetchProjectData();
      loadFiles();
      loadAgents();
    }
  }, [slug]);

  // Poll for container runtime status to update node statuses
  // PERFORMANCE: Skip polling during drag operations to prevent re-renders
  useEffect(() => {
    if (!slug) return;

    const pollContainerStatus = async () => {
      // Skip polling if dragging or no nodes - use ref to avoid dependency
      if (isDraggingRef.current || nodesRef.current.length === 0) return;

      try {
        const statusData = await projectsApi.getContainersRuntimeStatus(slug);
        if (statusData.containers) {
          // Update nodes with actual Docker status - only update if something changed
          setNodes((currentNodes) => {
            let hasChanges = false;
            const updatedNodes = currentNodes.map((node) => {
              // Find matching container by service name (sanitized container name)
              const serviceName = node.data.name
                ?.toLowerCase()
                .replace(/[^a-z0-9-]/g, '-')
                .replace(/-+/g, '-')
                .replace(/^-|-$/g, '');
              const containerStatus = statusData.containers[serviceName];

              if (containerStatus) {
                const newStatus = containerStatus.running ? 'running' : 'stopped';
                if (node.data.status !== newStatus) {
                  hasChanges = true;
                  return {
                    ...node,
                    data: {
                      ...node.data,
                      status: newStatus,
                    },
                  };
                }
              }
              return node;
            });

            // Only return new array if something actually changed
            return hasChanges ? updatedNodes : currentNodes;
          });

          // Update isRunning state based on overall status
          setIsRunning(statusData.status === 'running');
        }
      } catch (error) {
        // Silently ignore errors - container might not be started yet
        console.debug('Container status poll error:', error);
      }
    };

    // Initial poll (delayed to let nodes load)
    const initialPollTimeout = setTimeout(pollContainerStatus, 1000);

    // Poll every 5 seconds
    const interval = setInterval(pollContainerStatus, 5000);

    return () => {
      clearTimeout(initialPollTimeout);
      clearInterval(interval);
    };
  }, [slug, setNodes]); // Removed nodes.length - use ref instead

  useEffect(() => {
    localStorage.setItem('graphCanvasSidebarExpanded', JSON.stringify(isLeftSidebarExpanded));
  }, [isLeftSidebarExpanded]);

  // Listen for file events - PRIMARY real-time update mechanism
  useEffect(() => {
    const unsubscribe = fileEvents.on((detail) => {
      console.log('File event received:', detail.type, detail.filePath);
      if (detail.type !== 'file-updated') {
        loadFiles();
      }
    });

    return () => {
      unsubscribe();
    };
  }, [slug]);

  // Smart Polling - BACKUP mechanism for edge cases
  useEffect(() => {
    if (!slug) return;

    let pollInterval: NodeJS.Timeout | null = null;
    let isTabVisible = true;

    const handleVisibilityChange = () => {
      isTabVisible = !document.hidden;

      if (isTabVisible && !pollInterval) {
        startPolling();
      } else if (!isTabVisible && pollInterval) {
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

    document.addEventListener('visibilitychange', handleVisibilityChange);
    if (isTabVisible) {
      startPolling();
    }

    return () => {
      if (pollInterval) {
        clearInterval(pollInterval);
      }
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [slug]);

  // View-switch refresh - refresh when switching to code view
  useEffect(() => {
    if (activeView === 'code' && slug) {
      loadFiles();
    }
  }, [activeView, slug]);

  const fetchProjectData = async () => {
    try {
      // Fetch project info
      const projectRes = await projectsApi.get(slug!);
      setProject(projectRes);

      // Fetch containers
      const containers = await projectsApi.getContainers(slug!);

      // Fetch connections
      const connectionsRes = await api.get(`/api/projects/${slug}/containers/connections`);
      const connections: ContainerConnection[] = connectionsRes.data;

      // Fetch browser previews
      const browserPreviewsRes = await api.get(`/api/projects/${slug}/browser-previews`);
      const browserPreviews = browserPreviewsRes.data || [];

      // Fetch deployment targets
      let deploymentTargets: Array<{
        id: string;
        provider: string;
        environment: string;
        name?: string;
        position_x: number;
        position_y: number;
        is_connected: boolean;
        connected_containers?: Array<{
          id: string;
          name: string;
          framework?: string;
        }>;
        deployment_history?: Array<{
          id: string;
          version: string;
          status: string;
          deployment_url?: string;
          created_at: string;
          completed_at?: string;
        }>;
      }> = [];
      try {
        const deploymentTargetsRes = await deploymentTargetsApi.list(slug!);
        deploymentTargets = deploymentTargetsRes || [];
      } catch (error) {
        const axiosError = error as { response?: { status?: number } };
        if (axiosError.response?.status === 404) {
          console.debug('Deployment targets endpoint not available');
        } else {
          console.error('Failed to load deployment targets:', error);
          toast.error('Failed to load deployment targets');
        }
      }

      // Convert containers to React Flow nodes
      const containerNodes: Node[] = containers.map((container: Container) => ({
        id: container.id,
        type: 'containerNode',
        position: { x: container.position_x, y: container.position_y },
        data: {
          name: container.name,
          status: container.status,
          port: container.port,
          baseIcon: container.icon || '📦',
          techStack: container.tech_stack || [],
          containerType: container.container_type || 'base',
          serviceType: container.service_type || undefined,
          deploymentProvider: container.deployment_provider || undefined,
          onDelete: handleDeleteContainer,
          onClick: handleContainerClick,
          onDoubleClick: handleOpenBuilder,
        },
      }));

      // Convert browser previews to React Flow nodes
      const browserNodes: Node[] = browserPreviews.map((preview: Record<string, unknown>) => {
        // Find connected container for URL building
        const connectedContainer = preview.connected_container_id
          ? containers.find((c: Container) => c.id === preview.connected_container_id)
          : null;

        let baseUrl = '';
        if (connectedContainer) {
          const sanitizedName =
            connectedContainer.name
              ?.toLowerCase()
              .replace(/[^a-z0-9-]/g, '-')
              .replace(/-+/g, '-')
              .replace(/^-|-$/g, '') || 'app';
          // URL format: {project-slug}-{container-name}.{app_domain}
          const domain = appDomainRef.current;
          const protocol = domain.includes('localhost') ? 'http' : 'https';
          baseUrl = `${protocol}://${projectRes.slug}-${sanitizedName}.${domain}`;
        }

        return {
          id: preview.id,
          type: 'browserPreview',
          position: { x: preview.position_x, y: preview.position_y },
          dragHandle: '.browser-drag-handle',
          data: {
            connectedContainerId: preview.connected_container_id,
            connectedContainerName: connectedContainer?.name,
            connectedPort: connectedContainer?.port,
            baseUrl: baseUrl,
            onDelete: handleDeleteBrowser,
          },
        };
      });

      // Convert deployment targets to React Flow nodes
      const deploymentTargetNodes: Node[] = deploymentTargets.map((target) => ({
        id: target.id,
        type: 'deploymentTarget',
        position: { x: target.position_x, y: target.position_y },
        data: {
          provider: target.provider,
          environment: target.environment,
          name: target.name,
          isConnected: target.is_connected,
          connectedContainers: target.connected_containers || [],
          deploymentHistory: (target.deployment_history || []).map((d) => ({
            id: d.id,
            version: d.version,
            status: d.status,
            deployment_url: d.deployment_url,
            created_at: d.created_at,
            completed_at: d.completed_at,
          })),
          onDeploy: handleDeployFromTarget,
          onConnect: handleConnectDeploymentTarget,
          onDelete: handleDeleteDeploymentTarget,
          onRollback: handleRollbackDeployment,
        },
      }));

      // Combine all nodes
      const flowNodes: Node[] = [...containerNodes, ...browserNodes, ...deploymentTargetNodes];

      // Convert to React Flow edges - animations disabled for performance
      const flowEdges: Edge[] = connections.map((connection) => ({
        id: connection.id,
        source: connection.source_container_id,
        target: connection.target_container_id,
        type: (() => {
          const connectorType =
            connection.connector_type || connection.connection_type || 'depends_on';
          const edgeType = getEdgeType(connectorType);
          return edgeType === 'default' ? 'smoothstep' : edgeType;
        })(),
        label: connection.label,
        animated: connection.connector_type === 'http_api',
      }));

      // Add browser preview edges for connected browsers
      browserPreviews.forEach((preview: Record<string, unknown>) => {
        if (preview.connected_container_id) {
          flowEdges.push({
            id: `browser-edge-${preview.id}`,
            source: preview.connected_container_id,
            target: preview.id,
            type: 'browser_preview',
            animated: false,
          });
        }
      });

      // Add deployment target edges for connected containers
      deploymentTargets.forEach((target) => {
        (target.connected_containers || []).forEach((container) => {
          flowEdges.push({
            id: `deploy-edge-${container.id}-${target.id}`,
            source: container.id,
            target: target.id,
            type: 'deployment',
            animated: false,
          });
        });
      });

      setNodes(flowNodes);
      setEdges(flowEdges);
    } catch (error) {
      console.error('Failed to fetch project data:', error);
      toast.error('Failed to load project');
    }
  };

  const loadFiles = async () => {
    if (!slug) return;
    try {
      const filesData = await projectsApi.getFiles(slug);
      setFiles(filesData);
    } catch (error) {
      console.error('Failed to load files:', error);
    }
  };

  const loadAgents = async () => {
    try {
      const libraryData = await marketplaceApi.getMyAgents();
      const enabledAgents = libraryData.agents.filter(
        (agent: Record<string, unknown>) => agent.is_enabled
      );

      const uiAgents: ChatAgent[] = enabledAgents.map((agent: Record<string, unknown>) => ({
        id: agent.slug as string,
        name: agent.name as string,
        icon: (agent.icon as string) || '🤖',
        avatar_url: (agent.avatar_url as string) || undefined,
        backendId: agent.id as number,
        mode: agent.mode as 'stream' | 'agent',
        model: agent.model as string | undefined,
        selectedModel: agent.selected_model as string | null | undefined,
        sourceType: agent.source_type as 'open' | 'closed' | undefined,
        isCustom: agent.is_custom as boolean | undefined,
      }));

      setAgents(uiAgents);
    } catch (error) {
      console.error('Failed to load agents:', error);
    }
  };

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
      if (slug) localStorage.setItem(`tesslate-graph-agent-${slug}`, agent.id);
    },
    [slug]
  );

  const handleFileUpdate = useCallback(
    async (filePath: string, content: string) => {
      if (!slug) return;

      // Track if this is a new file or an update
      const isNewFile = !files.find((f) => f.file_path === filePath);

      setFiles((prev) => {
        const existing = prev.find((f) => f.file_path === filePath);
        if (existing) {
          return prev.map((f) => (f.file_path === filePath ? { ...f, content } : f));
        }
        return [...prev, { file_path: filePath, content }];
      });

      try {
        await projectsApi.saveFile(slug, filePath, content);

        // Emit file event to refresh the code editor file tree
        fileEvents.emit(isNewFile ? 'file-created' : 'file-updated', filePath);
      } catch (error) {
        console.error('Failed to save file:', error);
        toast.error(`Failed to save ${filePath}`);
      }
    },
    [slug, files]
  );

  const togglePanel = (panel: PanelType) => {
    setActivePanel(activePanel === panel ? null : panel);
  };

  // Stable callback for deleting browser preview nodes - must be defined before onConnect
  const handleDeleteBrowser = useCallback(
    async (browserId: string) => {
      try {
        // Delete from backend
        await api.delete(`/api/projects/${slug}/browser-previews/${browserId}`);

        // Remove the browser node
        setNodes((nds) => nds.filter((node) => node.id !== browserId));
        // Remove any edges connected to this browser
        setEdges((eds) =>
          eds.filter((edge) => edge.source !== browserId && edge.target !== browserId)
        );
        toast.success('Browser removed');
      } catch (error) {
        console.error('Failed to delete browser preview:', error);
        toast.error('Failed to delete browser preview');
      }
    },
    [slug, setNodes, setEdges]
  );

  // Stable callback for deleting deployment target nodes
  const handleDeleteDeploymentTarget = useCallback(
    async (targetId: string) => {
      if (!confirm('Delete this deployment target? Connected containers will be disconnected.'))
        return;

      try {
        await deploymentTargetsApi.delete(slugRef.current!, targetId);

        // Remove the deployment target node
        setNodes((nds) => nds.filter((node) => node.id !== targetId));
        // Remove any edges connected to this target
        setEdges((eds) =>
          eds.filter((edge) => edge.source !== targetId && edge.target !== targetId)
        );
        toast.success('Deployment target removed');
      } catch (error) {
        console.error('Failed to delete deployment target:', error);
        toast.error('Failed to delete deployment target');
      }
    },
    [setNodes, setEdges]
  );

  // Stable callback for deploying from a deployment target
  const handleDeployFromTarget = useCallback(
    async (targetId: string) => {
      try {
        toast.loading('Starting deployment...', { id: `deploy-${targetId}` });
        const result = await deploymentTargetsApi.deploy(slugRef.current!, targetId);

        if (result.failed === 0 && result.success > 0) {
          toast.success(`Deployed ${result.success} container(s) successfully!`, {
            id: `deploy-${targetId}`,
          });
          // Refresh the deployment history
          const history = await deploymentTargetsApi.getHistory(slugRef.current!, targetId);
          setNodes((nds) =>
            nds.map((node) =>
              node.id === targetId
                ? { ...node, data: { ...node.data, deploymentHistory: history } }
                : node
            )
          );
        } else {
          const failedResults = result.results.filter((r) => r.status === 'failed');
          const errorMsg = failedResults[0]?.error || 'Unknown error';
          toast.error(`Deployment failed: ${errorMsg}`, { id: `deploy-${targetId}` });
        }
      } catch (error) {
        console.error('Failed to deploy:', error);
        toast.error('Deployment failed', { id: `deploy-${targetId}` });
      }
    },
    [setNodes]
  );

  // Stable callback for connecting OAuth to deployment target
  const handleConnectDeploymentTarget = useCallback(async (targetId: string) => {
    try {
      // This will return the OAuth URL to redirect to
      const result = await deploymentTargetsApi.startOAuth(slugRef.current!, targetId);

      // Check for error response (provider doesn't support OAuth)
      if (result.error) {
        toast.error(result.error);
        return;
      }

      const oauthUrl = result.oauth_url || result.auth_url;
      if (oauthUrl) {
        // Open OAuth in a popup window
        window.open(oauthUrl, '_blank', 'width=600,height=700');
        toast.success('Complete OAuth in the popup window');
      } else {
        toast.error('No OAuth URL returned. Please check provider configuration.');
      }
    } catch (error) {
      console.error('Failed to start OAuth:', error);
      const axiosError = error as { response?: { data?: { detail?: string } } };
      const errorMessage = axiosError.response?.data?.detail || 'Failed to start OAuth connection';
      toast.error(errorMessage);
    }
  }, []);

  // Stable callback for rolling back a deployment
  const handleRollbackDeployment = useCallback(
    async (targetId: string, deploymentId: string) => {
      if (!confirm('Rollback to this deployment? This will redeploy the previous version.')) return;

      try {
        toast.loading('Rolling back...', { id: `rollback-${deploymentId}` });
        const result = await deploymentTargetsApi.rollback(
          slugRef.current!,
          targetId,
          deploymentId
        );

        if (result.status === 'success') {
          toast.success('Rollback successful!', { id: `rollback-${deploymentId}` });
          // Refresh the deployment history
          const history = await deploymentTargetsApi.getHistory(slugRef.current!, targetId);
          setNodes((nds) =>
            nds.map((node) =>
              node.id === targetId
                ? { ...node, data: { ...node.data, deploymentHistory: history } }
                : node
            )
          );
        } else {
          toast.error(`Rollback failed: ${result.error || 'Unknown error'}`, {
            id: `rollback-${deploymentId}`,
          });
        }
      } catch (error) {
        console.error('Failed to rollback:', error);
        toast.error('Rollback failed', { id: `rollback-${deploymentId}` });
      }
    },
    [setNodes]
  );

  // Debounced position update for deployment targets
  const debouncedDeploymentTargetPositionUpdate = useMemo(
    () =>
      debounce(async (targetId: string, x: number, y: number) => {
        try {
          await deploymentTargetsApi.update(slugRef.current!, targetId, {
            position_x: Math.round(x),
            position_y: Math.round(y),
          });
        } catch (error) {
          console.error('Failed to update deployment target position:', error);
        }
      }, 300),
    []
  );

  const onConnect: OnConnect = useCallback(
    async (connection) => {
      if (!connection.source || !connection.target) return;

      // Prevent self-connections
      if (connection.source === connection.target) return;

      // Check if target is a browser preview node
      const targetNode = nodesRef.current.find((n) => n.id === connection.target);
      const sourceNode = nodesRef.current.find((n) => n.id === connection.source);

      if (targetNode?.type === 'browserPreview' && sourceNode) {
        // This is a connection to a browser preview - update browser data
        const containerName = sourceNode.data.name;
        const containerPort = sourceNode.data.port || 3000;

        // Build the preview URL based on container name
        // Format: {project-slug}-{container-name}.{appDomain}
        const sanitizedName =
          containerName
            ?.toLowerCase()
            .replace(/[^a-z0-9-]/g, '-')
            .replace(/-+/g, '-')
            .replace(/^-|-$/g, '') || 'app';

        const domain = appDomainRef.current;
        const protocol = domain.includes('localhost') ? 'http' : 'https';
        const baseUrl = `${protocol}://${project.slug}-${sanitizedName}.${domain}`;

        try {
          // Save connection to backend
          await api.post(
            `/api/projects/${slug}/browser-previews/${connection.target}/connect/${connection.source}`
          );

          // Update the browser node with container data
          setNodes((nds) =>
            nds.map((node) =>
              node.id === connection.target
                ? {
                    ...node,
                    data: {
                      ...node.data,
                      connectedContainerId: connection.source,
                      connectedContainerName: containerName,
                      connectedPort: containerPort,
                      baseUrl: baseUrl,
                      onDelete: handleDeleteBrowser,
                    },
                  }
                : node
            )
          );

          // Add the edge with browser_preview type
          setEdges((eds) =>
            addEdge(
              {
                ...connection,
                type: 'browser_preview',
                animated: false,
              },
              eds
            )
          );

          toast.success(`Connected ${containerName} to browser`);
        } catch (error) {
          console.error('Failed to connect browser to container:', error);
          toast.error('Failed to connect browser to container');
        }
        return;
      }

      // Handle connection to deployment target node
      if (targetNode?.type === 'deploymentTarget' && sourceNode?.type === 'containerNode') {
        const containerName = sourceNode.data.name;
        const provider = targetNode.data.provider;

        try {
          // Validate the connection first
          const validation = await deploymentTargetsApi.validate(
            slug!,
            connection.target!,
            connection.source!
          );

          if (!validation.allowed) {
            toast.error(validation.reason || `Cannot deploy ${containerName} to ${provider}`);
            return;
          }

          // Connect the container to the deployment target
          await deploymentTargetsApi.connect(slug!, connection.target!, connection.source!);

          // Update the deployment target node with the new connected container
          const connectedContainers = targetNode.data.connectedContainers || [];
          setNodes((nds) =>
            nds.map((node) =>
              node.id === connection.target
                ? {
                    ...node,
                    data: {
                      ...node.data,
                      connectedContainers: [
                        ...connectedContainers,
                        {
                          id: connection.source,
                          name: containerName,
                          framework: sourceNode.data.techStack?.[0] || null,
                        },
                      ],
                    },
                  }
                : node
            )
          );

          // Add the edge with deployment type
          setEdges((eds) =>
            addEdge(
              {
                ...connection,
                type: 'deployment',
                animated: false,
              },
              eds
            )
          );

          toast.success(`Connected ${containerName} to ${provider}`);
        } catch (error) {
          console.error('Failed to connect container to deployment target:', error);
          const axiosError = error as { response?: { data?: { detail?: string } } };
          const errorMessage = axiosError.response?.data?.detail || 'Failed to connect';
          toast.error(errorMessage);
        }
        return;
      }

      // Prevent duplicate connections between the same two containers
      const duplicate = edgesRef.current.some(
        (e) => e.source === connection.source && e.target === connection.target
      );
      if (duplicate) {
        toast.error('Connection already exists between these containers');
        return;
      }

      try {
        // Auto-detect connector_type: service containers use env_injection
        const isSourceService = sourceNode?.data?.containerType === 'service';
        const connectorType = isSourceService ? 'env_injection' : 'depends_on';

        // Create connection in backend (for container-to-container connections)
        await api.post(`/api/projects/${slug}/containers/connections`, {
          project_id: project.id,
          source_container_id: connection.source,
          target_container_id: connection.target,
          connection_type: 'depends_on',
          connector_type: connectorType,
        });

        // Update local state - use correct edge type for connector semantics
        const edgeType = getEdgeType(connectorType);
        setEdges((eds) =>
          addEdge(
            {
              ...connection,
              type: edgeType === 'default' ? 'smoothstep' : edgeType,
              animated: false,
            },
            eds
          )
        );
        // Notify panels that connections changed so injected env vars refresh
        connectionEvents.emit('connection-created', connection.source, connection.target);

        toast.success(
          isSourceService ? 'Connected — env vars will be injected' : 'Connection created'
        );
      } catch (error) {
        console.error('Failed to create connection:', error);
        toast.error('Failed to create connection');
      }
    },
    [slug, project, setEdges, setNodes, handleDeleteBrowser]
  );

  const onDrop = useCallback(
    async (event: React.DragEvent) => {
      event.preventDefault();

      const nodeType = event.dataTransfer.getData('application/reactflow');
      const baseData = event.dataTransfer.getData('base');
      if (!baseData || !reactFlowInstance) return;

      const item = JSON.parse(baseData);

      // Convert screen coordinates to flow coordinates (accounts for zoom and pan)
      const dropPosition = reactFlowInstance.screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });

      // Handle deployment target drops - create standalone deployment target node
      if (nodeType === 'deploymentTarget') {
        // Convert screen coordinates to flow coordinates for accurate positioning
        const flowPosition = reactFlowInstance.screenToFlowPosition({
          x: event.clientX,
          y: event.clientY,
        });

        // Extract provider name from the deployment target slug (e.g., 'vercel-deploy' -> 'vercel')
        const provider = item.slug.replace('-deploy', '');

        // Generate temporary ID for optimistic update
        const tempId = `temp-target-${Date.now()}`;

        // Optimistically add the deployment target node
        const optimisticNode: Node = {
          id: tempId,
          type: 'deploymentTarget',
          position: flowPosition,
          data: {
            provider: provider,
            environment: 'production',
            name: item.name,
            isConnected: false,
            connectedContainers: [],
            deploymentHistory: [],
            onDeploy: handleDeployFromTarget,
            onConnect: handleConnectDeploymentTarget,
            onDelete: handleDeleteDeploymentTarget,
            onRollback: handleRollbackDeployment,
          },
        };

        setNodes((nds) => [...nds, optimisticNode]);

        try {
          // Create deployment target in backend
          const newTarget = await deploymentTargetsApi.create(slug!, {
            provider: provider,
            environment: 'production',
            name: item.name,
            position_x: flowPosition.x,
            position_y: flowPosition.y,
          });

          // Update the temporary node with real ID and refresh callbacks
          setNodes((nds) =>
            nds.map((node) =>
              node.id === tempId
                ? {
                    ...node,
                    id: newTarget.id,
                    data: {
                      ...node.data,
                      isConnected: newTarget.is_connected,
                      onDeploy: handleDeployFromTarget,
                      onConnect: handleConnectDeploymentTarget,
                      onDelete: handleDeleteDeploymentTarget,
                      onRollback: handleRollbackDeployment,
                    },
                  }
                : node
            )
          );

          toast.success(`${item.name} added to canvas`);
        } catch (error: unknown) {
          console.error('Failed to create deployment target:', error);
          // Remove the optimistic node on error
          setNodes((nds) => nds.filter((node) => node.id !== tempId));
          const axiosError = error as { response?: { data?: { detail?: string } } };
          const errorMessage =
            axiosError.response?.data?.detail ||
            (error instanceof Error ? error.message : 'Unknown error');
          toast.error(`Failed to create deployment target: ${errorMessage}`);
        }
        return;
      }

      // Handle browser preview drops
      if (item.type === 'browser') {
        try {
          // Create browser preview in backend
          const response = await api.post(`/api/projects/${slug}/browser-previews`, {
            project_id: project.id,
            position_x: dropPosition.x,
            position_y: dropPosition.y,
          });

          const browserPreview = response.data;
          const browserNode: Node = {
            id: browserPreview.id,
            type: 'browserPreview',
            position: dropPosition,
            dragHandle: '.browser-drag-handle',
            data: {
              onDelete: handleDeleteBrowser,
            },
          };
          setNodes((nds) => [...nds, browserNode]);
          toast.success('Browser preview added');
        } catch (error) {
          console.error('Failed to create browser preview:', error);
          toast.error('Failed to create browser preview');
        }
        return;
      }

      // Handle workflow drops differently
      if (item.type === 'workflow' && item.template_definition) {
        await instantiateWorkflow(item, dropPosition);
        return;
      }

      // Check if this is an external service that needs credentials
      const isExternalService =
        item.type === 'service' &&
        (item.service_type === 'external' || item.service_type === 'hybrid') &&
        item.credential_fields?.length > 0;

      if (isExternalService) {
        // Show credential modal instead of immediately creating
        setExternalServiceModal({
          isOpen: true,
          item: item,
          position: dropPosition,
        });
        return;
      }

      // For container services and bases, create immediately
      await createContainerNode(item, dropPosition);
    },
    [
      slug,
      project,
      setNodes,
      handleDeleteBrowser,
      reactFlowInstance,
      handleDeployFromTarget,
      handleConnectDeploymentTarget,
      handleDeleteDeploymentTarget,
      handleRollbackDeployment,
    ]
  );

  // Instantiate a workflow template (creates multiple nodes and connections)
  const instantiateWorkflow = useCallback(
    async (workflow: Record<string, unknown>, basePosition: { x: number; y: number }) => {
      const template = workflow.template_definition;
      if (!template?.nodes || !template?.edges) {
        toast.error('Invalid workflow template');
        return;
      }

      toast.loading(`Creating ${workflow.name}...`, { id: 'workflow-create' });

      // Track temp IDs for cleanup on failure
      const tempNodeIds: string[] = [];
      const createdContainerIds: string[] = [];

      try {
        // Track mapping from template_id to real container_id
        const templateIdToContainerId: Record<string, string> = {};

        // Create all nodes from the template
        for (const nodeTemplate of template.nodes) {
          // Calculate position relative to drop point
          const nodePosition = {
            x: basePosition.x + (nodeTemplate.position?.x || 0),
            y: basePosition.y + (nodeTemplate.position?.y || 0),
          };

          // Build the item to create based on node type
          let _itemToCreate: unknown;
          if (nodeTemplate.type === 'base') {
            _itemToCreate = {
              type: 'base',
              name: nodeTemplate.name,
              slug: nodeTemplate.base_slug,
              id: nodeTemplate.base_slug, // Will be resolved by backend
            };
          } else if (nodeTemplate.type === 'service') {
            _itemToCreate = {
              type: 'service',
              name: nodeTemplate.name,
              slug: nodeTemplate.service_slug,
              service_type: 'container', // Default to container for now
            };
          }

          // Create the container
          const tempId = `temp-${Date.now()}-${nodeTemplate.template_id}`;
          tempNodeIds.push(tempId);

          // Add optimistic node
          const optimisticNode: Node = {
            id: tempId,
            type: 'containerNode',
            position: nodePosition,
            data: {
              name: nodeTemplate.name,
              status: 'starting',
              baseIcon: '📦',
              techStack: [],
              containerType: nodeTemplate.type,
              onDelete: handleDeleteContainer,
              onClick: handleContainerClick,
              onDoubleClick: handleOpenBuilder,
            },
          };
          setNodes((nds) => [...nds, optimisticNode]);

          // Create in backend
          const payload: Record<string, unknown> = {
            project_id: project.id,
            name: nodeTemplate.name,
            position_x: nodePosition.x,
            position_y: nodePosition.y,
          };

          if (nodeTemplate.type === 'service') {
            payload.container_type = 'service';
            payload.service_slug = nodeTemplate.service_slug;
          } else {
            payload.container_type = 'base';
            // For bases, we need to look up the base_id from the slug
            // For now, use the slug as a marker - backend will handle resolution
            payload.base_id = nodeTemplate.base_slug;
          }

          const response = await api.post(`/api/projects/${slug}/containers`, payload);
          const newContainer = response.data.container;

          // Map template_id to real container_id
          templateIdToContainerId[nodeTemplate.template_id] = newContainer.id;
          createdContainerIds.push(newContainer.id);

          // Update the optimistic node with real data
          setNodes((nds) =>
            nds.map((node) =>
              node.id === tempId
                ? {
                    ...node,
                    id: newContainer.id,
                    data: {
                      ...node.data,
                      name: newContainer.name,
                      status: 'stopped',
                      port: newContainer.port,
                    },
                  }
                : node
            )
          );
        }

        // Create all edges/connections from the template
        for (const edgeTemplate of template.edges) {
          const sourceId = templateIdToContainerId[edgeTemplate.source];
          const targetId = templateIdToContainerId[edgeTemplate.target];

          if (!sourceId || !targetId) {
            console.warn(
              `Missing container for edge: ${edgeTemplate.source} -> ${edgeTemplate.target}`
            );
            continue;
          }

          // Create connection in backend
          await api.post(`/api/projects/${slug}/containers/connections`, {
            project_id: project.id,
            source_container_id: sourceId,
            target_container_id: targetId,
            connector_type: edgeTemplate.connector_type || 'env_injection',
            config: edgeTemplate.config || null,
          });

          // Add edge to graph with proper edge type for visual styling
          const edgeType = getEdgeType(edgeTemplate.connector_type || 'env_injection');
          const newEdge: Edge = {
            id: `${sourceId}-${targetId}`,
            source: sourceId,
            target: targetId,
            type: edgeType,
            animated: edgeTemplate.connector_type === 'http_api',
            data: {
              connector_type: edgeTemplate.connector_type,
              config: edgeTemplate.config,
            },
          };
          setEdges((eds) => [...eds, newEdge]);
        }

        // Increment download count for the workflow
        try {
          await api.post(`/api/marketplace/workflows/${workflow.slug}/increment-downloads`);
        } catch {
          // Ignore download tracking errors
        }

        toast.success(`Created ${workflow.name}!`, { id: 'workflow-create' });
      } catch (error) {
        console.error('Failed to instantiate workflow:', error);

        // Clean up optimistic nodes that weren't replaced with real IDs
        setNodes((nds) => nds.filter((n) => !tempNodeIds.includes(n.id)));

        // Clean up any containers that were successfully created before the error
        for (const containerId of createdContainerIds) {
          try {
            await api.delete(`/api/projects/${slug}/containers/${containerId}`);
          } catch (deleteError) {
            console.warn(`Failed to clean up container ${containerId}:`, deleteError);
          }
        }

        toast.error('Failed to create workflow', { id: 'workflow-create' });
      }
    },
    [slug, project, setNodes, setEdges]
  );

  // Helper function to create container node (used by both regular drop and after credential modal)
  const createContainerNode = useCallback(
    async (
      item: Record<string, unknown>,
      position: { x: number; y: number },
      credentials?: Record<string, string>,
      externalEndpoint?: string
    ) => {
      // Generate temporary ID for optimistic update
      const tempId = `temp-${Date.now()}`;

      // Determine status based on service type
      const isExternal = item.service_type === 'external' || item.service_type === 'hybrid';
      const initialStatus = isExternal ? 'connected' : 'starting';

      // Optimistically add node to canvas immediately for better UX
      const optimisticNode: Node = {
        id: tempId,
        type: 'containerNode',
        position,
        data: {
          name: item.name,
          status: initialStatus,
          baseIcon: item.icon,
          techStack: item.tech_stack || [],
          containerType: item.type || 'base',
          serviceType: item.service_type,
          onDelete: handleDeleteContainer,
          onClick: handleContainerClick,
          onDoubleClick: handleOpenBuilder,
        },
      };

      setNodes((nds) => [...nds, optimisticNode]);

      try {
        // Build request payload based on item type
        const payload: Record<string, unknown> = {
          project_id: project.id,
          name: item.name,
          position_x: position.x,
          position_y: position.y,
        };

        // Add type-specific fields
        if (item.type === 'service') {
          payload.container_type = 'service';
          payload.service_slug = item.slug;

          // For external services, add deployment mode and credentials
          if (item.service_type === 'external' || item.service_type === 'hybrid') {
            payload.deployment_mode = 'external';
            if (externalEndpoint) {
              payload.external_endpoint = externalEndpoint;
            }
            if (credentials && Object.keys(credentials).length > 0) {
              payload.credentials = credentials;
            }
          }
        } else {
          // Default to base
          payload.container_type = 'base';
          payload.base_id = item.id;
        }

        // Create container in backend (happens in background)
        const response = await api.post(`/api/projects/${slug}/containers`, payload);

        // API returns { container: {...}, task_id: "...", status_endpoint: "..." }
        const newContainer = response.data.container;

        // Update the temporary node with real ID and data
        setNodes((nds) =>
          nds.map((node) =>
            node.id === tempId
              ? {
                  ...node,
                  id: newContainer.id,
                  data: {
                    ...node.data,
                    name: newContainer.name,
                    status: isExternal ? 'connected' : 'stopped',
                    containerType: newContainer.container_type || item.type || 'base',
                    serviceType: item.service_type,
                    port: newContainer.port,
                  },
                }
              : node
          )
        );
        toast.success(`Added ${item.name}`);
      } catch (error) {
        console.error('Failed to add container:', error);
        // Remove the optimistic node on error
        setNodes((nds) => nds.filter((node) => node.id !== tempId));
        toast.error('Failed to add container');
      }
    },
    [slug, project, setNodes]
  );

  // Handle credential modal submission
  const handleExternalServiceCredentialSubmit = useCallback(
    async (credentials: Record<string, string>, externalEndpoint?: string) => {
      if (!externalServiceModal.item || !externalServiceModal.position) return;

      // Close modal first
      setExternalServiceModal({ isOpen: false, item: null, position: null });

      // Create the container with credentials
      await createContainerNode(
        externalServiceModal.item,
        externalServiceModal.position,
        credentials,
        externalEndpoint
      );
    },
    [externalServiceModal, createContainerNode]
  );

  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
  }, []);

  // Stable callback - uses ref to access latest nodes without dependency
  const handleContainerClick = useCallback((containerId: string) => {
    const containerNode = nodesRef.current.find((n) => n.id === containerId);
    if (containerNode) {
      setSelectedContainer({
        id: containerId,
        name: containerNode.data.name,
        status: containerNode.data.status,
        port: containerNode.data.port,
        containerType: containerNode.data.containerType,
      });
    }
  }, []); // Empty deps - uses ref

  // Stable callback - uses refs to access latest values without dependencies
  const handleDeleteContainer = useCallback(
    async (containerId: string) => {
      // Get container name for the confirmation message - use ref for latest nodes
      const containerNode = nodesRef.current.find((n) => n.id === containerId);
      const containerName = containerNode?.data?.name || 'this container';
      const currentSlug = slugRef.current;

      if (!confirm(`Are you sure you want to delete ${containerName}?`)) return;

      try {
        // Delete the container from backend
        await api.delete(`/api/projects/${currentSlug}/containers/${containerId}`);

        // Remove from graph
        setNodes((nds) => nds.filter((node) => node.id !== containerId));
        setEdges((eds) =>
          eds.filter((edge) => edge.source !== containerId && edge.target !== containerId)
        );

        toast.success('Container deleted');

        // Ask if user wants to delete associated files
        const deleteFiles = confirm(
          `Do you also want to delete all files associated with ${containerName}?\n\nThis will permanently delete all code files in the container's directory.`
        );

        if (deleteFiles) {
          // Find all files that belong to this container - use ref for latest files
          const containerFiles = filesRef.current.filter((file) => {
            // Files are typically organized as: containerName/...
            const pathParts = file.file_path.split('/');
            return pathParts[0] === containerName || pathParts[0] === containerId;
          });

          if (containerFiles.length === 0) {
            toast('No files found for this container', { icon: 'ℹ️' });
            return;
          }

          // Delete each file
          const deletePromises = containerFiles.map((file) =>
            projectsApi.deleteFile(currentSlug!, file.file_path)
          );

          try {
            await Promise.all(deletePromises);
            toast.success(`Deleted ${containerFiles.length} file(s)`);

            // Refresh file list
            loadFiles();

            // Emit file event
            fileEvents.emit('files-changed');
          } catch (error) {
            console.error('Failed to delete some files:', error);
            toast.error('Failed to delete some files');
          }
        }
      } catch (error) {
        console.error('Failed to delete container:', error);
        toast.error('Failed to delete container');
      }
    },
    [setNodes, setEdges, loadFiles] // Removed slug, nodes, files - now uses refs
  );

  // Debounced position update - batches rapid position changes (300ms delay)
  const debouncedContainerPositionUpdate = useMemo(
    () =>
      debounce(async (nodeId: string, x: number, y: number) => {
        try {
          await api.patch(`/api/projects/${slugRef.current}/containers/${nodeId}`, {
            position_x: Math.round(x),
            position_y: Math.round(y),
          });
        } catch (error) {
          console.error('Failed to update container position:', error);
        }
      }, 300),
    []
  );

  // Debounced browser preview position update
  const debouncedBrowserPositionUpdate = useMemo(
    () =>
      debounce(async (previewId: string, x: number, y: number) => {
        try {
          await api.patch(`/api/projects/${slugRef.current}/browser-previews/${previewId}`, {
            position_x: Math.round(x),
            position_y: Math.round(y),
          });
        } catch (error) {
          console.error('Failed to update browser preview position:', error);
        }
      }, 300),
    []
  );

  // Stable callback - sets dragging state for pausing polling
  const handleNodeDragStart = useCallback(() => {
    setIsDragging(true);
  }, []);

  // Stable callback - uses ref for slug, debounces API call
  const handleNodeDragStop = useCallback(
    async (_event: React.MouseEvent | React.TouchEvent, node: Node) => {
      // End dragging state
      setIsDragging(false);

      // Skip API call for temporary nodes
      if (typeof node.id === 'string' && node.id.startsWith('temp-')) {
        return;
      }

      // Use debounced update for better performance - different endpoint based on node type
      if (node.type === 'browserPreview') {
        debouncedBrowserPositionUpdate(node.id, node.position.x, node.position.y);
      } else if (node.type === 'deploymentTarget') {
        debouncedDeploymentTargetPositionUpdate(node.id, node.position.x, node.position.y);
      } else {
        debouncedContainerPositionUpdate(node.id, node.position.x, node.position.y);
      }
    },
    [
      debouncedContainerPositionUpdate,
      debouncedBrowserPositionUpdate,
      debouncedDeploymentTargetPositionUpdate,
    ]
  );

  // Auto layout handler - arranges nodes using dagre algorithm
  const handleAutoLayout = useCallback(async () => {
    if (nodes.length < 2) {
      toast('Add more nodes to use auto layout', { icon: 'ℹ️' });
      return;
    }

    const { nodes: layoutedNodes } = getLayoutedElements(nodes, edges, {
      direction: 'LR',
      nodeWidth: 180,
      nodeHeight: 100,
    });

    // Update local state immediately for responsive UI
    setNodes(layoutedNodes);

    // Save all positions to backend
    toast.loading('Arranging nodes...', { id: 'autolayout' });

    try {
      const updates = layoutedNodes.map((node) => {
        if (node.type === 'browserPreview') {
          return api.patch(`/api/projects/${slug}/browser-previews/${node.id}`, {
            position_x: Math.round(node.position.x),
            position_y: Math.round(node.position.y),
          });
        } else if (node.type === 'deploymentTarget') {
          return deploymentTargetsApi.update(slug!, node.id, {
            position_x: Math.round(node.position.x),
            position_y: Math.round(node.position.y),
          });
        } else {
          return api.patch(`/api/projects/${slug}/containers/${node.id}`, {
            position_x: Math.round(node.position.x),
            position_y: Math.round(node.position.y),
          });
        }
      });

      await Promise.all(updates);
      toast.success('Layout applied!', { id: 'autolayout' });
    } catch (error) {
      console.error('Failed to save layout:', error);
      toast.error('Failed to save layout', { id: 'autolayout' });
    }
  }, [nodes, edges, slug, setNodes]);

  const handleStartAll = async () => {
    if (!slug) return;

    try {
      toast.loading('Starting all containers...', { id: 'start-all' });
      await api.post(`/api/projects/${slug}/containers/start-all`);
      toast.success('All containers started successfully!', { id: 'start-all', duration: 2000 });
      setIsRunning(true);
    } catch (error) {
      console.error('Failed to start containers:', error);
      toast.error('Failed to start containers', { id: 'start-all' });
    }
  };

  const handleStopAll = async () => {
    if (!slug) return;

    try {
      toast.loading('Stopping all containers...', { id: 'stop-all' });
      await api.post(`/api/projects/${slug}/containers/stop-all`);
      toast.success('All containers stopped successfully!', { id: 'stop-all', duration: 2000 });
      setIsRunning(false);
    } catch (error) {
      console.error('Failed to stop containers:', error);
      toast.error('Failed to stop containers', { id: 'stop-all' });
    }
  };

  // Stable callback - uses ref for slug
  const handleOpenBuilder = useCallback(
    (containerId: string) => {
      navigate(`/project/${slugRef.current}/builder?container=${containerId}`);
    },
    [navigate]
  );

  // Stable callbacks for ReactFlow to prevent re-renders
  const handleNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      // Don't try to select browser preview or deployment target nodes as containers
      if (node.type === 'browserPreview' || node.type === 'deploymentTarget') {
        return;
      }
      handleContainerClick(node.id);
    },
    [handleContainerClick]
  );

  const handleNodeDoubleClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      // Only allow double-click navigation for base containers, not services, browser previews, or deployment targets
      if (node.type === 'browserPreview' || node.type === 'deploymentTarget') {
        return; // Don't open builder for these node types
      }
      const containerType = node.data?.containerType || 'base';
      if (containerType === 'base') {
        handleOpenBuilder(node.id);
      }
    },
    [handleOpenBuilder]
  );

  // Edge click handler - selects the edge (delete button appears on the edge)
  const handleEdgeClick = useCallback((_: React.MouseEvent, _edge: Edge) => {
    // Edge is automatically selected by ReactFlow when clicked
    // The EdgeDeleteButton component renders a delete button on the selected edge
  }, []);

  // Pane click handler - collapse chat panel when clicking on the canvas
  // React Flow captures pointer events internally, so mousedown doesn't bubble
  // to document where ChatContainer's click-outside handler listens.
  // Dispatching a synthetic mousedown on the body triggers that handler.
  const handlePaneClick = useCallback(() => {
    if (document.activeElement instanceof HTMLElement) {
      document.activeElement.blur();
    }
    document.body.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
  }, []);

  // Prevent keyboard delete from removing nodes - only allow edge deletion
  const handleBeforeDelete = useCallback(
    async ({ edges: edgesToDelete }: { nodes: Node[]; edges: Edge[] }) => {
      return { nodes: [] as Node[], edges: edgesToDelete };
    },
    []
  );

  // Edge deletion handler - called when Delete key is pressed on selected edges
  const handleEdgesDelete = useCallback(
    async (deletedEdges: Edge[]) => {
      for (const edge of deletedEdges) {
        try {
          // Check if this is a browser preview edge
          if (edge.type === 'browser_preview' || edge.id.startsWith('browser-edge-')) {
            // Find the browser preview node and disconnect it
            const browserPreviewId = edge.target;
            await api.delete(
              `/api/projects/${slugRef.current}/browser-previews/${browserPreviewId}/disconnect`
            );

            // Update the browser node to remove connected container data
            setNodes((nds) =>
              nds.map((node) =>
                node.id === browserPreviewId
                  ? {
                      ...node,
                      data: {
                        ...node.data,
                        connectedContainerId: undefined,
                        connectedContainerName: undefined,
                        connectedPort: undefined,
                        baseUrl: undefined,
                      },
                    }
                  : node
              )
            );
          } else if (edge.type === 'deployment' || edge.id.startsWith('deploy-edge-')) {
            // Find the deployment target node and disconnect the container
            const deploymentTargetId = edge.target;
            const containerId = edge.source;
            await deploymentTargetsApi.disconnect(
              slugRef.current!,
              deploymentTargetId,
              containerId
            );

            // Update the deployment target node to remove the connected container
            setNodes((nds) =>
              nds.map((node) =>
                node.id === deploymentTargetId
                  ? {
                      ...node,
                      data: {
                        ...node.data,
                        connectedContainers: (node.data.connectedContainers || []).filter(
                          (c: { id: string }) => c.id !== containerId
                        ),
                      },
                    }
                  : node
              )
            );
          } else {
            // Regular container-to-container connection - delete from backend
            await api.delete(`/api/projects/${slugRef.current}/containers/connections/${edge.id}`);
          }
        } catch (error) {
          console.error('Failed to delete connection:', error);
          toast.error('Failed to delete connection');
          return; // Stop processing further deletions on error
        }
      }

      // Remove edges from local state
      setEdges((eds) => eds.filter((e) => !deletedEdges.some((de) => de.id === e.id)));

      // Notify panels that connections changed so injected env vars refresh
      for (const edge of deletedEdges) {
        connectionEvents.emit('connection-deleted', edge.source, edge.target);
      }

      toast.success(`Deleted ${deletedEdges.length} connection(s)`);
    },
    [setNodes, setEdges]
  );

  if (!project) {
    return (
      <div className="flex items-center justify-center h-full bg-[var(--bg)]">
        <div className="text-[var(--text)]/60">Loading project...</div>
      </div>
    );
  }

  const leftSidebarItems = [
    {
      icon: <TreeStructure size={18} />,
      title: 'Architecture',
      onClick: () => setActiveView('graph'),
      active: activeView === 'graph',
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
    // Builder navigation - accessible on mobile via menu
    {
      icon: <Code size={18} />,
      title: 'Open Builder',
      onClick: () => navigate(`/project/${slug}/builder`),
    },
    // Auto Layout - only shows when on graph view
    ...(activeView === 'graph'
      ? [
          {
            icon: <FlowArrow size={18} />,
            title: 'Auto Layout',
            onClick: handleAutoLayout,
          },
        ]
      : []),
  ];

  const rightSidebarItems = [
    {
      icon: <BookOpen size={18} />,
      title: 'Notes',
      onClick: () => togglePanel('notes'),
      active: activePanel === 'notes',
    },
    {
      icon: <Storefront size={18} />,
      title: 'Agents',
      onClick: () => navigate('/marketplace'),
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
        {/* Top Bar with Breadcrumbs */}
        <div className="h-12 bg-[var(--surface)] flex items-center justify-between px-4 md:px-6">
          <Breadcrumbs
            items={[
              { label: 'Projects', href: '/dashboard' },
              { label: project.name, href: `/project/${slug}` },
              { label: 'Architecture' },
            ]}
          />

          {/* Control buttons */}
          <div className="flex items-center gap-3">
            {/* Builder Button */}
            <button
              onClick={() => navigate(`/project/${slug}/builder`)}
              className="hidden md:flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-white/5 transition-colors"
            >
              <Code size={18} className="text-[var(--text)]" />
              <span className="text-sm font-medium text-[var(--text)]">Builder</span>
            </button>

            {/* Auto Layout Button */}
            <button
              onClick={handleAutoLayout}
              disabled={nodes.length < 2}
              className="hidden md:flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-white/5 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              title="Automatically arrange nodes"
            >
              <FlowArrow size={18} className="text-[var(--text)]" />
              <span className="text-sm font-medium text-[var(--text)]">Auto Layout</span>
            </button>

            {isRunning ? (
              <button
                onClick={handleStopAll}
                className="flex items-center gap-2 px-3 md:px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors text-sm"
              >
                <Stop size={16} weight="fill" />
                <span className="hidden md:inline">Stop All</span>
              </button>
            ) : (
              <button
                onClick={handleStartAll}
                className="flex items-center gap-2 px-3 md:px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors text-sm"
              >
                <Play size={16} weight="fill" />
                <span className="hidden md:inline">Start All</span>
              </button>
            )}
          </div>

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

        {/* Main View Container */}
        <div className="flex-1 overflow-hidden bg-[var(--bg)]">
          {/* Graph View */}
          <div className={`w-full h-full ${activeView === 'graph' ? 'flex' : 'hidden'} relative`}>
            {/* React Flow canvas */}
            <div className="flex-1 relative bg-[#0a0a0a] [&_.react-flow__renderer]:will-change-transform [&_.react-flow__edges]:will-change-transform [&_.react-flow__nodes]:will-change-transform">
              {/* Floating component drawer */}
              <MarketplaceSidebar />

              <GraphCanvas
                nodes={nodes}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onConnect={onConnect}
                onDrop={onDrop}
                onDragOver={onDragOver}
                onInit={() => {}}
                onNodeDragStart={handleNodeDragStart}
                onNodeDragStop={handleNodeDragStop}
                onNodeClick={handleNodeClick}
                onNodeDoubleClick={handleNodeDoubleClick}
                onEdgeClick={handleEdgeClick}
                onEdgesDelete={handleEdgesDelete}
                onBeforeDelete={handleBeforeDelete}
                onPaneClick={handlePaneClick}
                nodeTypes={nodeTypes}
                edgeTypes={edgeTypes}
                theme={theme}
              />
            </div>

            {/* Container Properties Panel - inline with graph */}
            {selectedContainer && (
              <ContainerPropertiesPanel
                containerId={selectedContainer.id}
                containerName={selectedContainer.name}
                containerStatus={selectedContainer.status}
                projectSlug={slug || ''}
                port={selectedContainer.port}
                containerType={selectedContainer.containerType}
                onClose={() => setSelectedContainer(null)}
                onStatusChange={(newStatus) => {
                  setNodes((nds) =>
                    nds.map((node) =>
                      node.id === selectedContainer.id
                        ? { ...node, data: { ...node.data, status: newStatus } }
                        : node
                    )
                  );
                  setSelectedContainer({ ...selectedContainer, status: newStatus });
                }}
                onNameChange={(newName) => {
                  // Update node name in the graph - local state is already updated
                  setNodes((nds) =>
                    nds.map((node) =>
                      node.id === selectedContainer.id
                        ? { ...node, data: { ...node.data, name: newName } }
                        : node
                    )
                  );
                  // Update selected container state
                  setSelectedContainer({ ...selectedContainer, name: newName });
                  // PERFORMANCE: Removed fetchProjectData() - local state is sufficient
                }}
              />
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
        </div>
      </div>

      {/* Floating Panels */}
      <FloatingPanel
        title="GitHub Sync"
        icon={<GitBranch size={20} />}
        isOpen={activePanel === 'github'}
        onClose={() => setActivePanel(null)}
        defaultSize={{ width: 420, height: 620 }}
      >
        <GitHubPanel projectId={project?.id} />
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

      {/* Chat Interface */}
      {agents.length > 0 && currentAgent && (
        <ChatContainer
          projectId={project?.id}
          containerId={selectedContainer?.id}
          viewContext="graph"
          agents={agents}
          currentAgent={currentAgent}
          onSelectAgent={handleAgentSelect}
          onFileUpdate={handleFileUpdate}
          projectFiles={files}
          projectName={project?.name}
          sidebarExpanded={isLeftSidebarExpanded}
        />
      )}

      {/* Discord Support */}
      <DiscordSupport />

      {/* External Service Credential Modal */}
      {externalServiceModal.item && (
        <ExternalServiceCredentialModal
          isOpen={externalServiceModal.isOpen}
          item={externalServiceModal.item}
          onClose={() => setExternalServiceModal({ isOpen: false, item: null, position: null })}
          onSubmit={handleExternalServiceCredentialSubmit}
        />
      )}
    </div>
  );
};

// Import ReactFlowProvider for useReactFlow hook
import { ReactFlowProvider } from '@xyflow/react';

// Export wrapped component so useReactFlow works
export const ProjectGraphCanvas = () => (
  <ReactFlowProvider>
    <ProjectGraphCanvasInner />
  </ReactFlowProvider>
);
