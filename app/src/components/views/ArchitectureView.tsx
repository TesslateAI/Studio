import React, {
  useState,
  useCallback,
  useRef,
  useEffect,
  useMemo,
  forwardRef,
  useImperativeHandle,
} from 'react';
import { debounce } from 'lodash';
import {
  addEdge,
  useNodesState,
  useEdgesState,
  useReactFlow,
  ReactFlowProvider,
  type Edge,
  type Node,
  type NodeTypes,
  type OnConnect,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { ContainerNode } from '../ContainerNode';
import { BrowserPreviewNode } from '../BrowserPreviewNode';
import { DeploymentTargetNode } from '../DeploymentTargetNode';
import { GraphCanvas } from '../GraphCanvas';
import { MarketplaceSidebar } from '../MarketplaceSidebar';
import { ContainerPropertiesPanel } from '../ContainerPropertiesPanel';
import type { InspectorJumpTarget } from '../apps/PublishAsAppDrawer';
import {
  ExternalServiceCredentialModal,
  type ExternalServiceItem,
} from '../ExternalServiceCredentialModal';
import { ProviderConnectModal } from '../modals/ProviderConnectModal';
import { ConfirmDialog } from '../modals/ConfirmDialog';
import api, {
  projectsApi,
  deploymentTargetsApi,
  deploymentCredentialsApi,
  configSyncApi,
  setupApi,
  type DeploymentTarget,
} from '../../lib/api';
import { useTheme } from '../../theme/ThemeContext';
import { fileEvents } from '../../utils/fileEvents';
import { connectionEvents } from '../../utils/connectionEvents';
import { nodeConfigEvents } from '../../utils/nodeConfigEvents';
import { inspectorFocusEvents } from '../../utils/inspectorFocusEvents';
import { useNodeConfigPending } from '../../contexts/NodeConfigPendingContext';
import toast from 'react-hot-toast';
import {
  EnvInjectionEdge,
  HttpApiEdge,
  DatabaseEdge,
  CacheEdge,
  BrowserPreviewEdge,
  DeploymentEdge,
  getEdgeType,
} from '../edges';
import { getLayoutedElements } from '../../utils/autoLayout';
import { appsCanvasNodeTypes, appsCanvasEdgeTypes } from '../canvas/appNodes';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const nodeTypes = {
  containerNode: ContainerNode,
  browserPreview: BrowserPreviewNode,
  deploymentTarget: DeploymentTargetNode,
  ...appsCanvasNodeTypes,
} as unknown as NodeTypes;

const edgeTypes = {
  env_injection: EnvInjectionEdge,
  http_api: HttpApiEdge,
  database: DatabaseEdge,
  cache: CacheEdge,
  browser_preview: BrowserPreviewEdge,
  deployment: DeploymentEdge,
  ...appsCanvasEdgeTypes,
};

// ---------------------------------------------------------------------------
// Interfaces
// ---------------------------------------------------------------------------

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
  startup_command?: string | null;
  build_command?: string | null;
  output_directory?: string | null;
  framework?: string | null;
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

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export interface ArchitectureViewProps {
  slug: string;
  projectId: string;
  isActive: boolean;
  onContainersChanged: () => void;
  onNavigateToContainer: (id: string) => void;
  onStateChange?: (state: { configDirty: boolean; isRunning: boolean }) => void;
  readOnly?: boolean;
  /**
   * Deep-link signal forwarded to the floating MarketplaceSidebar. The
   * unified Deploy hub bumps `nonce` to ask the sidebar to open and
   * expand a specific category (e.g., "deployment") so the user lands
   * directly in the right component list.
   */
  marketplaceFocus?: { category: string; nonce: number } | null;
}

export interface ArchitectureViewHandle {
  saveConfig: () => Promise<void>;
  loadConfig: () => Promise<void>;
  autoLayout: () => Promise<void>;
  startAll: () => Promise<void>;
  stopAll: () => Promise<void>;
  configDirty: boolean;
  isRunning: boolean;
}

// ---------------------------------------------------------------------------
// Inner component (requires ReactFlowProvider ancestor)
// ---------------------------------------------------------------------------

const ArchitectureViewInner = forwardRef<ArchitectureViewHandle, ArchitectureViewProps>(
  (
    {
      slug,
      projectId,
      isActive,
      onContainersChanged,
      onNavigateToContainer,
      onStateChange,
      readOnly = false,
      marketplaceFocus,
    },
    ref
  ) => {
    const { theme } = useTheme();
    const { isPending: isNodePending } = useNodeConfigPending();
    const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
    const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
    const reactFlowInstance = useReactFlow();

    // Refs for stable callback references — prevents node re-renders when parent state changes
    const nodesRef = useRef<Node[]>(nodes);
    const edgesRef = useRef<Edge[]>(edges);
    const filesRef = useRef<
      Array<{ path: string; name: string; is_dir: boolean; size: number; mod_time: number }>
    >([]);
    const slugRef = useRef(slug);
    const isDraggingRef = useRef(false);

    // Runtime URLs keyed by container_id — populated by status poller, read by browser preview nodes
    const runtimeUrlsRef = useRef<Map<string, string>>(new Map());
    const getContainerUrl = useCallback(
      (containerId: string) => runtimeUrlsRef.current.get(containerId) || '',
      []
    );

    const [project, setProject] = useState<Record<string, unknown> | null>(null);
    const [fileTree, setFileTree] = useState<
      Array<{ path: string; name: string; is_dir: boolean; size: number; mod_time: number }>
    >([]);
    const [configDirty, setConfigDirty] = useState(false);
    const [isRunning, setIsRunning] = useState(false);
    const [selectedContainer, setSelectedContainer] = useState<{
      id: string;
      name: string;
      status: string;
      port?: number;
      containerType?: 'base' | 'service';
    } | null>(null);

    // Drag state for pausing polling during drag operations — critical for performance
    const [isDragging, setIsDragging] = useState(false);

    // External service credential modal state
    const [externalServiceModal, setExternalServiceModal] = useState<{
      isOpen: boolean;
      item: Record<string, unknown> | null;
      position: { x: number; y: number } | null;
    }>({ isOpen: false, item: null, position: null });

    // Provider connect modal state for deployment targets
    const [providerConnectModal, setProviderConnectModal] = useState<{
      isOpen: boolean;
      targetId: string | null;
      provider: string | null;
    }>({ isOpen: false, targetId: null, provider: null });
    const [connectedProviders, setConnectedProviders] = useState<string[]>([]);


    // Confirm dialog state (replaces native confirm() popups)
    const [confirmDialog, setConfirmDialog] = useState<{
      isOpen: boolean;
      title: string;
      message: string;
      confirmText: string;
      variant: 'danger' | 'warning' | 'info';
      onConfirm: () => void;
    }>({
      isOpen: false,
      title: '',
      message: '',
      confirmText: 'Confirm',
      variant: 'info',
      onConfirm: () => {},
    });

    // -----------------------------------------------------------------------
    // Ref sync effects
    // -----------------------------------------------------------------------

    useEffect(() => {
      nodesRef.current = nodes;
    }, [nodes]);

    useEffect(() => {
      edgesRef.current = edges;
    }, [edges]);

    useEffect(() => {
      filesRef.current = fileTree;
    }, [fileTree]);

    useEffect(() => {
      slugRef.current = slug;
    }, [slug]);

    useEffect(() => {
      isDraggingRef.current = isDragging;
    }, [isDragging]);

    // Sync the pulsing ring on containerNode nodes whose config is pending.
    // Additive: when no ids are pending, no node data changes.
    useEffect(() => {
      setNodes((nds) => {
        let changed = false;
        const next = nds.map((n) => {
          if (n.type !== 'containerNode') return n;
          const pending = isNodePending(n.id);
          const current = (n.data as { pendingConfig?: boolean }).pendingConfig ?? false;
          if (pending === current) return n;
          changed = true;
          return { ...n, data: { ...n.data, pendingConfig: pending } };
        });
        return changed ? next : nds;
      });
    }, [isNodePending, setNodes]);

    // Refresh canvas when the agent announces a newly added architecture node.
    useEffect(() => {
      const unsub = nodeConfigEvents.on('architecture-node-added', () => {
        fetchProjectDataRef.current?.();
      });
      return unsub;
    }, []);

    // -----------------------------------------------------------------------
    // Data fetching
    // -----------------------------------------------------------------------

    const fetchProjectDataRef = useRef<(() => Promise<void>) | null>(null);

    const fetchProjectData = async () => {
      try {
        // Fetch project info
        const projectRes = await projectsApi.get(slug);
        setProject(projectRes);

        // Fetch containers
        const containers = await projectsApi.getContainers(slug);

        // Fetch connections
        const connectionsRes = await api.get(`/api/projects/${slug}/containers/connections`);
        const connections: ContainerConnection[] = connectionsRes.data;

        // Fetch browser previews
        const browserPreviewsRes = await api.get(`/api/projects/${slug}/browser-previews`);
        const browserPreviews = browserPreviewsRes.data || [];

        // Fetch deployment targets
        let deploymentTargets: DeploymentTarget[] = [];
        try {
          const deploymentTargetsRes = await deploymentTargetsApi.list(slug);
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
            baseIcon: undefined,
            techStack: container.tech_stack || [],
            containerType: container.container_type || 'base',
            serviceType: container.service_type || undefined,
            deploymentProvider: container.deployment_provider || undefined,
            onDelete: handleDeleteContainer,
            onClick: handleContainerClick,
            onDoubleClick: handleOpenBuilder,
          },
        }));

        // Seed runtime URL map from initial status fetch
        try {
          const statusData = await projectsApi.getContainersRuntimeStatus(projectRes.slug);
          for (const info of Object.values(statusData.containers || {}) as Record<
            string,
            unknown
          >[]) {
            if (info.container_id && info.url) {
              runtimeUrlsRef.current.set(info.container_id as string, info.url as string);
            }
          }
        } catch {
          // URLs will be populated by polling
        }

        // Convert browser previews to React Flow nodes
        const browserNodes: Node[] = browserPreviews.map((preview: Record<string, unknown>) => {
          const connectedContainer = preview.connected_container_id
            ? containers.find((c: Container) => c.id === preview.connected_container_id)
            : null;

          return {
            id: preview.id as string,
            type: 'browserPreview',
            position: { x: preview.position_x as number, y: preview.position_y as number },
            dragHandle: '.browser-drag-handle',
            data: {
              connectedContainerId: preview.connected_container_id,
              connectedContainerName: connectedContainer?.name,
              connectedPort: connectedContainer?.port,
              getContainerUrl,
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
            providerInfo: target.provider_info,
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
            onEnvironmentChange: handleEnvironmentChange,
            onDelete: handleDeleteDeploymentTarget,
            onRollback: handleRollbackDeployment,
          },
        }));

        // Combine all nodes
        const flowNodes: Node[] = [...containerNodes, ...browserNodes, ...deploymentTargetNodes];

        // Convert to React Flow edges — animations disabled for performance
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
        (browserPreviews as Array<Record<string, unknown>>).forEach((preview) => {
          if (preview.connected_container_id) {
            flowEdges.push({
              id: `browser-edge-${preview.id as string}`,
              source: preview.connected_container_id as string,
              target: preview.id as string,
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

    // -----------------------------------------------------------------------
    // File loading
    // -----------------------------------------------------------------------

    const loadFiles = useCallback(async () => {
      if (!slugRef.current) return;
      try {
        const entries = await projectsApi.getFileTree(slugRef.current);
        setFileTree((prev) => {
          const prevPaths = prev.map((f) => f.path).join('\0');
          const newPaths = entries.map((f: { path: string }) => f.path).join('\0');
          if (prevPaths === newPaths) return prev;
          return entries;
        });
      } catch (error) {
        console.error('Failed to load files:', error);
      }
    }, []);

    // Notify parent when configDirty or isRunning change
    useEffect(() => {
      onStateChange?.({ configDirty, isRunning });
    }, [configDirty, isRunning, onStateChange]);

    // Keep a stable ref to fetchProjectData so subscriptions can call it.
    useEffect(() => {
      fetchProjectDataRef.current = fetchProjectData;
    });

    // -----------------------------------------------------------------------
    // Initial load
    // -----------------------------------------------------------------------

    useEffect(() => {
      if (slug) {
        fetchProjectData();
        loadFiles();
        setupApi
          .getConfig(slug)
          .then((r) => {
            if (!r.exists) setConfigDirty(true);
          })
          .catch(() => {});
      }
    }, [slug]);

    // -----------------------------------------------------------------------
    // Container status polling — 5s interval, pauses when !isActive OR isDragging
    // -----------------------------------------------------------------------

    useEffect(() => {
      if (!slug) return;

      const pollContainerStatus = async () => {
        // Skip polling if not active, dragging, or no nodes
        if (!isActive || isDraggingRef.current || nodesRef.current.length === 0) return;

        try {
          const statusData = await projectsApi.getContainersRuntimeStatus(slug);
          if (statusData.containers) {
            // Populate runtime URL map for browser preview nodes to read
            for (const info of Object.values(statusData.containers) as Record<string, unknown>[]) {
              if (info.container_id && info.url) {
                runtimeUrlsRef.current.set(info.container_id as string, info.url as string);
              }
            }

            // Update container node statuses
            setNodes((currentNodes) => {
              let hasChanges = false;
              const updatedNodes = currentNodes.map((node) => {
                const serviceName = (node.data.name as string | undefined)
                  ?.toLowerCase()
                  .replace(/[^a-z0-9-]/g, '-')
                  .replace(/-+/g, '-')
                  .replace(/^-|-$/g, '');
                const containerStatus = serviceName
                  ? (statusData.containers as Record<string, Record<string, unknown>>)[serviceName]
                  : undefined;

                if (containerStatus) {
                  const newStatus = containerStatus.running ? 'running' : 'stopped';
                  if ((node.data.status as string | undefined) !== newStatus) {
                    hasChanges = true;
                    return {
                      ...node,
                      data: { ...node.data, status: newStatus },
                    };
                  }
                }
                return node;
              });

              return hasChanges ? updatedNodes : currentNodes;
            });

            setIsRunning(statusData.status === 'running');
          }
        } catch (error) {
          // Silently ignore errors — container might not be started yet
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
    }, [slug, setNodes, isActive]);

    // -----------------------------------------------------------------------
    // File event listeners + smart polling backup
    // -----------------------------------------------------------------------

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

    // -----------------------------------------------------------------------
    // Browser preview handlers
    // -----------------------------------------------------------------------

    const handleDeleteBrowser = useCallback(
      async (browserId: string) => {
        try {
          await api.delete(`/api/projects/${slug}/browser-previews/${browserId}`);
          setNodes((nds) => nds.filter((node) => node.id !== browserId));
          setEdges((eds) =>
            eds.filter((edge) => edge.source !== browserId && edge.target !== browserId)
          );
          toast.success('Browser removed');
          setConfigDirty(true);
        } catch (error) {
          console.error('Failed to delete browser preview:', error);
          toast.error('Failed to delete browser preview');
        }
      },
      [slug, setNodes, setEdges]
    );

    // -----------------------------------------------------------------------
    // Deployment target handlers
    // -----------------------------------------------------------------------

    const handleDeleteDeploymentTarget = useCallback(
      (targetId: string) => {
        setConfirmDialog({
          isOpen: true,
          title: 'Delete Deployment Target',
          message:
            'This will remove the deployment target and disconnect all linked containers. This action cannot be undone.',
          confirmText: 'Delete',
          variant: 'danger',
          onConfirm: async () => {
            setConfirmDialog((prev) => ({ ...prev, isOpen: false }));
            try {
              await deploymentTargetsApi.delete(slugRef.current!, targetId);
              setNodes((nds) => nds.filter((node) => node.id !== targetId));
              setEdges((eds) =>
                eds.filter((edge) => edge.source !== targetId && edge.target !== targetId)
              );
              toast.success('Deployment target removed');
              setConfigDirty(true);
            } catch (error) {
              console.error('Failed to delete deployment target:', error);
              toast.error('Failed to delete deployment target');
            }
          },
        });
      },
      [setNodes, setEdges]
    );

    const refreshDeploymentHistory = useCallback(
      async (targetId: string) => {
        try {
          const history = await deploymentTargetsApi.getHistory(slugRef.current!, targetId);
          setNodes((nds) =>
            nds.map((node) =>
              node.id === targetId
                ? {
                    ...node,
                    data: {
                      ...node.data,
                      deploymentHistory: (history || []).map((d) => ({
                        id: d.id,
                        version: d.version,
                        status: d.status,
                        deployment_url: d.deployment_url,
                        created_at: d.created_at,
                        completed_at: d.completed_at,
                      })),
                    },
                  }
                : node
            )
          );
        } catch (error) {
          console.error('Failed to refresh deployment history:', error);
        }
      },
      [setNodes]
    );

    const handleDeployFromTarget = useCallback(
      async (targetId: string) => {
        try {
          toast.loading('Starting deployment...', { id: `deploy-${targetId}` });
          const result = await deploymentTargetsApi.deploy(slugRef.current!, targetId);

          if (result.failed === 0 && result.success > 0) {
            toast.success(`Deployed ${result.success} container(s) successfully!`, {
              id: `deploy-${targetId}`,
            });
          } else {
            const failedResults = result.results.filter((r) => r.status === 'failed');
            const errorMsg = failedResults[0]?.error || 'Unknown error';
            toast.error(`Deployment failed: ${errorMsg}`, { id: `deploy-${targetId}` });
          }
        } catch (error) {
          console.error('Failed to deploy:', error);
          toast.error('Deployment failed', { id: `deploy-${targetId}` });
        } finally {
          await refreshDeploymentHistory(targetId);
        }
      },
      [refreshDeploymentHistory]
    );

    const handleConnectDeploymentTarget = useCallback(async (targetId: string) => {
      try {
        const target = await deploymentTargetsApi.get(slugRef.current!, targetId);
        const provider = target.provider;

        if (target.provider_info?.auth_type === 'oauth') {
          const result = await deploymentCredentialsApi.startOAuth(provider);
          const oauthUrl = result.auth_url;
          if (oauthUrl) {
            window.open(oauthUrl, '_blank', 'width=600,height=700');
            toast.success('Complete OAuth in the popup window');
          } else {
            toast.error('No OAuth URL returned. Please check provider configuration.');
          }
          return;
        }

        setProviderConnectModal({ isOpen: true, targetId, provider });
      } catch (error) {
        console.error('Failed to connect deployment target:', error);
        const axiosError = error as { response?: { data?: { detail?: string } } };
        toast.error(axiosError.response?.data?.detail || 'Failed to connect');
      }
    }, []);

    const handleProviderConnected = useCallback(
      async (provider: string) => {
        const { targetId } = providerConnectModal;
        if (!targetId || !slugRef.current) return;

        try {
          const updatedTarget = await deploymentTargetsApi.get(slugRef.current, targetId);
          setNodes((nds) =>
            nds.map((node) =>
              node.id === targetId
                ? { ...node, data: { ...node.data, isConnected: updatedTarget.is_connected } }
                : node
            )
          );
          setConnectedProviders((prev) => (prev.includes(provider) ? prev : [...prev, provider]));
        } catch {
          // Target might have been refreshed already
        }
      },
      [providerConnectModal, setNodes]
    );

    const handleEnvironmentChange = useCallback(
      async (targetId: string, environment: 'production' | 'staging' | 'preview') => {
        setNodes((nds) =>
          nds.map((node) =>
            node.id === targetId ? { ...node, data: { ...node.data, environment } } : node
          )
        );

        try {
          await deploymentTargetsApi.update(slugRef.current!, targetId, { environment });
          setConfigDirty(true);
        } catch (error) {
          console.error('Failed to update environment:', error);
          toast.error('Failed to update environment');
        }
      },
      [setNodes]
    );

    const handleRollbackDeployment = useCallback(
      (targetId: string, deploymentId: string) => {
        setConfirmDialog({
          isOpen: true,
          title: 'Rollback Deployment',
          message:
            'This will redeploy the selected previous version. Your current deployment will be replaced.',
          confirmText: 'Rollback',
          variant: 'warning',
          onConfirm: async () => {
            setConfirmDialog((prev) => ({ ...prev, isOpen: false }));
            try {
              toast.loading('Rolling back...', { id: `rollback-${deploymentId}` });
              const result = await deploymentTargetsApi.rollback(
                slugRef.current!,
                targetId,
                deploymentId
              );

              if (result.status === 'success') {
                toast.success('Rollback successful!', { id: `rollback-${deploymentId}` });
              } else {
                toast.error(
                  `Rollback failed: ${((result as Record<string, unknown>).error as string) || result.message || 'Unknown error'}`,
                  {
                    id: `rollback-${deploymentId}`,
                  }
                );
              }
            } catch (error) {
              console.error('Failed to rollback:', error);
              toast.error('Rollback failed', { id: `rollback-${deploymentId}` });
            } finally {
              await refreshDeploymentHistory(targetId);
            }
          },
        });
      },
      [refreshDeploymentHistory]
    );

    // -----------------------------------------------------------------------
    // Debounced position updates
    // -----------------------------------------------------------------------

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

    // -----------------------------------------------------------------------
    // Connection handler
    // -----------------------------------------------------------------------

    const onConnect: OnConnect = useCallback(
      async (connection) => {
        if (!connection.source || !connection.target) return;
        if (connection.source === connection.target) return;

        const targetNode = nodesRef.current.find((n) => n.id === connection.target);
        const sourceNode = nodesRef.current.find((n) => n.id === connection.source);

        // Browser preview connection
        if (targetNode?.type === 'browserPreview' && sourceNode) {
          const containerName = sourceNode.data.name as string;
          const containerPort = (sourceNode.data.port as number | undefined) || 3000;

          try {
            await api.post(
              `/api/projects/${slug}/browser-previews/${connection.target}/connect/${connection.source}`
            );

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
                        getContainerUrl,
                        onDelete: handleDeleteBrowser,
                      },
                    }
                  : node
              )
            );

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
            setConfigDirty(true);
          } catch (error) {
            console.error('Failed to connect browser to container:', error);
            toast.error('Failed to connect browser to container');
          }
          return;
        }

        // Deployment target connection
        if (targetNode?.type === 'deploymentTarget' && sourceNode?.type === 'containerNode') {
          const containerName = sourceNode.data.name as string;
          const provider = targetNode.data.provider as string;

          try {
            const validation = await deploymentTargetsApi.validate(
              slug,
              connection.target!,
              connection.source!
            );

            if (!validation.allowed) {
              toast.error(validation.reason || `Cannot deploy ${containerName} to ${provider}`);
              return;
            }

            await deploymentTargetsApi.connect(slug, connection.target!, connection.source!);

            const connectedContainers =
              (targetNode.data.connectedContainers as Array<Record<string, unknown>> | undefined) ||
              [];
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
                            framework:
                              (sourceNode.data.techStack as string[] | undefined)?.[0] || null,
                          },
                        ],
                      },
                    }
                  : node
              )
            );

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
            setConfigDirty(true);
          } catch (error) {
            console.error('Failed to connect container to deployment target:', error);
            const axiosError = error as { response?: { data?: { detail?: string } } };
            const errorMessage = axiosError.response?.data?.detail || 'Failed to connect';
            toast.error(errorMessage);
          }
          return;
        }

        // Container-to-container connection — prevent duplicates
        const duplicate = edgesRef.current.some(
          (e) => e.source === connection.source && e.target === connection.target
        );
        if (duplicate) {
          toast.error('Connection already exists between these containers');
          return;
        }

        try {
          const isSourceService = sourceNode?.data?.containerType === 'service';
          const connectorType = isSourceService ? 'env_injection' : 'depends_on';

          await api.post(`/api/projects/${slug}/containers/connections`, {
            project_id: project?.id ?? projectId,
            source_container_id: connection.source,
            target_container_id: connection.target,
            connection_type: 'depends_on',
            connector_type: connectorType,
          });

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
          connectionEvents.emit('connection-created', connection.source, connection.target);

          toast.success(
            isSourceService ? 'Connected — env vars will be injected' : 'Connection created'
          );
          setConfigDirty(true);
        } catch (error) {
          console.error('Failed to create connection:', error);
          toast.error('Failed to create connection');
        }
      },
      [slug, project, projectId, setEdges, setNodes, handleDeleteBrowser]
    );

    // -----------------------------------------------------------------------
    // Container CRUD
    // -----------------------------------------------------------------------

    const handleContainerClick = useCallback((containerId: string) => {
      const containerNode = nodesRef.current.find((n) => n.id === containerId);
      if (containerNode) {
        setSelectedContainer({
          id: containerId,
          name: containerNode.data.name as string,
          status: containerNode.data.status as string,
          port: containerNode.data.port as number | undefined,
          containerType: containerNode.data.containerType as 'base' | 'service' | undefined,
        });
      }
    }, []);

    /**
     * Phase 5: PublishAsAppDrawer "Fix in inspector" handler.
     *
     * The drawer hands us a container *name* (manifest-side identifier) plus
     * an optional action / connector to focus. We resolve the React Flow
     * node by name (case-sensitive — manifest names round-trip exactly),
     * select it, and emit an inspector-focus-request so the inspector's
     * effect can scroll the App Contract section to the right row once
     * it mounts.
     *
     * Non-blocking: if no node matches the name, surface a toast and bail
     * — the drawer has already closed itself per its contract, so the user
     * isn't stuck.
     */
    const handleJumpToInspector = useCallback((target: InspectorJumpTarget) => {
      const containerNode = nodesRef.current.find(
        (n) => (n.data?.name as string | undefined) === target.containerName
      );
      if (!containerNode) {
        toast.error(`Container "${target.containerName}" not found on canvas`);
        return;
      }
      setSelectedContainer({
        id: containerNode.id,
        name: containerNode.data.name as string,
        status: containerNode.data.status as string,
        port: containerNode.data.port as number | undefined,
        containerType: containerNode.data.containerType as 'base' | 'service' | undefined,
      });
      // Defer the focus request one tick so the panel mounts before its
      // effect listener subscribes. Without the delay, the event fires
      // before the panel's useEffect attaches its handler.
      const detail = {
        containerId: containerNode.id,
        kind: (target.actionName ? 'action' : 'connector') as 'action' | 'connector',
        name: target.actionName ?? target.connectorId,
      };
      requestAnimationFrame(() => {
        inspectorFocusEvents.emit('inspector-focus-request', detail);
      });
    }, []);

    // The Publish drawer (now hoisted to ProjectPage) emits this event when
    // the user clicks "Fix in inspector". We're the only listener — we own
    // the React Flow node graph. Subscribing here means the canvas only
    // reacts when it's mounted; if the drawer is opened from the toolbar
    // without the architecture tab open, the event drops silently and the
    // user gets the YAML-editor fallback.
    useEffect(() => {
      const off = inspectorFocusEvents.on('publish-inspector-jump-request', (target) => {
        handleJumpToInspector(target);
      });
      return off;
    }, [handleJumpToInspector]);

    const handleOpenBuilder = useCallback(
      (containerId: string) => {
        onNavigateToContainer(containerId);
      },
      [onNavigateToContainer]
    );

    const handleDeleteContainer = useCallback(
      (containerId: string) => {
        const containerNode = nodesRef.current.find((n) => n.id === containerId);
        const containerName = (containerNode?.data?.name as string | undefined) || 'this container';
        const currentSlug = slugRef.current;

        setConfirmDialog({
          isOpen: true,
          title: 'Delete Container',
          message: `Are you sure you want to delete ${containerName}? This will remove the container and disconnect all linked services.`,
          confirmText: 'Delete',
          variant: 'danger',
          onConfirm: async () => {
            try {
              await api.delete(`/api/projects/${currentSlug}/containers/${containerId}`);

              setNodes((nds) => nds.filter((node) => node.id !== containerId));
              setEdges((eds) =>
                eds.filter((edge) => edge.source !== containerId && edge.target !== containerId)
              );

              toast.success('Container deleted');
              setConfigDirty(true);
              onContainersChanged();

              // Offer to delete associated files
              const containerFiles = filesRef.current.filter((entry) => {
                const pathParts = entry.path.split('/');
                return (
                  !entry.is_dir && (pathParts[0] === containerName || pathParts[0] === containerId)
                );
              });

              if (containerFiles.length > 0) {
                setConfirmDialog({
                  isOpen: true,
                  title: 'Delete Container Files',
                  message: `Do you also want to delete all ${containerFiles.length} file(s) associated with ${containerName}?\n\nThis will permanently delete all code files in the container's directory.`,
                  confirmText: 'Delete Files',
                  variant: 'danger',
                  onConfirm: async () => {
                    try {
                      await Promise.all(
                        containerFiles.map((entry) =>
                          projectsApi.deleteFile(currentSlug!, entry.path)
                        )
                      );
                      toast.success(`Deleted ${containerFiles.length} file(s)`);
                      loadFiles();
                      fileEvents.emit('files-changed');
                    } catch (error) {
                      console.error('Failed to delete some files:', error);
                      toast.error('Failed to delete some files');
                    }
                  },
                });
              }
            } catch (error) {
              console.error('Failed to delete container:', error);
              toast.error('Failed to delete container');
            }
          },
        });
      },
      [setNodes, setEdges, loadFiles, onContainersChanged]
    );

    const createContainerNode = useCallback(
      async (
        item: Record<string, unknown>,
        position: { x: number; y: number },
        credentials?: Record<string, string>,
        externalEndpoint?: string
      ) => {
        const tempId = `temp-${Date.now()}`;
        const isExternal = item.service_type === 'external' || item.service_type === 'hybrid';
        const initialStatus = isExternal ? 'connected' : 'starting';

        const optimisticNode: Node = {
          id: tempId,
          type: 'containerNode',
          position,
          data: {
            name: item.name,
            status: initialStatus,
            baseIcon: undefined,
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
          const payload: Record<string, unknown> = {
            project_id: project?.id ?? projectId,
            name: item.name,
            position_x: position.x,
            position_y: position.y,
          };

          if (item.type === 'service') {
            payload.container_type = 'service';
            payload.service_slug = item.slug;

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
            payload.container_type = 'base';
            payload.base_id = item.id;
          }

          const response = await api.post(`/api/projects/${slug}/containers`, payload);
          const newContainer = response.data.container;

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
          setConfigDirty(true);
          onContainersChanged();
        } catch (error) {
          console.error('Failed to add container:', error);
          setNodes((nds) => nds.filter((node) => node.id !== tempId));
          toast.error('Failed to add container');
        }
      },
      [
        slug,
        project,
        projectId,
        setNodes,
        onContainersChanged,
        handleDeleteContainer,
        handleContainerClick,
        handleOpenBuilder,
      ]
    );

    // -----------------------------------------------------------------------
    // External service credential submit
    // -----------------------------------------------------------------------

    const handleExternalServiceCredentialSubmit = useCallback(
      async (credentials: Record<string, string>, externalEndpoint?: string) => {
        if (!externalServiceModal.item || !externalServiceModal.position) return;
        setExternalServiceModal({ isOpen: false, item: null, position: null });
        await createContainerNode(
          externalServiceModal.item,
          externalServiceModal.position,
          credentials,
          externalEndpoint
        );
      },
      [externalServiceModal, createContainerNode]
    );

    // -----------------------------------------------------------------------
    // Workflow instantiation
    // -----------------------------------------------------------------------

    const instantiateWorkflow = useCallback(
      async (workflow: Record<string, unknown>, basePosition: { x: number; y: number }) => {
        const template = workflow.template_definition as Record<string, unknown> | undefined;
        if (!template?.nodes || !template?.edges) {
          toast.error('Invalid workflow template');
          return;
        }

        toast.loading(`Creating ${workflow.name}...`, { id: 'workflow-create' });

        const tempNodeIds: string[] = [];
        const createdContainerIds: string[] = [];

        try {
          const templateIdToContainerId: Record<string, string> = {};

          for (const nodeTemplate of template.nodes as Array<Record<string, unknown>>) {
            const nodePosition = {
              x: basePosition.x + ((nodeTemplate.position as Record<string, number>)?.x || 0),
              y: basePosition.y + ((nodeTemplate.position as Record<string, number>)?.y || 0),
            };

            const tempId = `temp-${Date.now()}-${nodeTemplate.template_id}`;
            tempNodeIds.push(tempId);

            const optimisticNode: Node = {
              id: tempId,
              type: 'containerNode',
              position: nodePosition,
              data: {
                name: nodeTemplate.name,
                status: 'starting',
                baseIcon: undefined,
                techStack: [],
                containerType: nodeTemplate.type,
                onDelete: handleDeleteContainer,
                onClick: handleContainerClick,
                onDoubleClick: handleOpenBuilder,
              },
            };
            setNodes((nds) => [...nds, optimisticNode]);

            const payload: Record<string, unknown> = {
              project_id: project?.id ?? projectId,
              name: nodeTemplate.name,
              position_x: nodePosition.x,
              position_y: nodePosition.y,
            };

            if (nodeTemplate.type === 'service') {
              payload.container_type = 'service';
              payload.service_slug = nodeTemplate.service_slug;
            } else {
              payload.container_type = 'base';
              payload.base_id = nodeTemplate.base_slug;
            }

            const response = await api.post(`/api/projects/${slug}/containers`, payload);
            const newContainer = response.data.container;

            templateIdToContainerId[nodeTemplate.template_id as string] = newContainer.id;
            createdContainerIds.push(newContainer.id);

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

          for (const edgeTemplate of template.edges as Array<Record<string, unknown>>) {
            const sourceId = templateIdToContainerId[edgeTemplate.source as string];
            const targetId = templateIdToContainerId[edgeTemplate.target as string];

            if (!sourceId || !targetId) {
              console.warn(
                `Missing container for edge: ${edgeTemplate.source} -> ${edgeTemplate.target}`
              );
              continue;
            }

            await api.post(`/api/projects/${slug}/containers/connections`, {
              project_id: project?.id ?? projectId,
              source_container_id: sourceId,
              target_container_id: targetId,
              connector_type: edgeTemplate.connector_type || 'env_injection',
              config: edgeTemplate.config || null,
            });

            const edgeType = getEdgeType(
              (edgeTemplate.connector_type as string) || 'env_injection'
            );
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

          try {
            await api.post(`/api/marketplace/workflows/${workflow.slug}/increment-downloads`);
          } catch {
            // Ignore download tracking errors
          }

          toast.success(`Created ${workflow.name}!`, { id: 'workflow-create' });
          onContainersChanged();
        } catch (error) {
          console.error('Failed to instantiate workflow:', error);

          setNodes((nds) => nds.filter((n) => !tempNodeIds.includes(n.id)));

          for (const containerId of createdContainerIds) {
            try {
              await api.delete(`/api/projects/${slug}/containers/${containerId}`);
            } catch (deleteError) {
              console.warn('Failed to clean up container %s:', containerId, deleteError);
            }
          }

          toast.error('Failed to create workflow', { id: 'workflow-create' });
        }
      },
      [
        slug,
        project,
        projectId,
        setNodes,
        setEdges,
        onContainersChanged,
        handleDeleteContainer,
        handleContainerClick,
        handleOpenBuilder,
      ]
    );

    // -----------------------------------------------------------------------
    // Drag & drop
    // -----------------------------------------------------------------------

    const onDrop = useCallback(
      async (event: React.DragEvent) => {
        event.preventDefault();

        const nodeType = event.dataTransfer.getData('application/reactflow');
        const baseData = event.dataTransfer.getData('base');
        if (!baseData || !reactFlowInstance) return;

        const item = JSON.parse(baseData);

        const dropPosition = reactFlowInstance.screenToFlowPosition({
          x: event.clientX,
          y: event.clientY,
        });

        // Deployment target drops
        if (nodeType === 'deploymentTarget') {
          const flowPosition = reactFlowInstance.screenToFlowPosition({
            x: event.clientX,
            y: event.clientY,
          });

          const provider =
            item.provider_key || item.slug.replace('deploy-', '').replace('-deploy', '');

          const tempId = `temp-target-${Date.now()}`;

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
              onEnvironmentChange: handleEnvironmentChange,
              onDelete: handleDeleteDeploymentTarget,
              onRollback: handleRollbackDeployment,
            },
          };

          setNodes((nds) => [...nds, optimisticNode]);

          try {
            const newTarget = await deploymentTargetsApi.create(slug, {
              provider: provider,
              environment: 'production',
              name: item.name,
              position_x: flowPosition.x,
              position_y: flowPosition.y,
            });

            setNodes((nds) =>
              nds.map((node) =>
                node.id === tempId
                  ? {
                      ...node,
                      id: newTarget.id,
                      data: {
                        ...node.data,
                        isConnected: newTarget.is_connected,
                        providerInfo: newTarget.provider_info,
                        onDeploy: handleDeployFromTarget,
                        onConnect: handleConnectDeploymentTarget,
                        onEnvironmentChange: handleEnvironmentChange,
                        onDelete: handleDeleteDeploymentTarget,
                        onRollback: handleRollbackDeployment,
                      },
                    }
                  : node
              )
            );

            toast.success(`${item.name} added to canvas`);
            setConfigDirty(true);
          } catch (error: unknown) {
            console.error('Failed to create deployment target:', error);
            setNodes((nds) => nds.filter((node) => node.id !== tempId));
            const axiosError = error as { response?: { data?: { detail?: string } } };
            const errorMessage =
              axiosError.response?.data?.detail ||
              (error instanceof Error ? error.message : 'Unknown error');
            toast.error(`Failed to create deployment target: ${errorMessage}`);
          }
          return;
        }

        // Browser preview drops
        if (item.type === 'browser') {
          try {
            const response = await api.post(`/api/projects/${slug}/browser-previews`, {
              project_id: project?.id ?? projectId,
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
            setConfigDirty(true);
          } catch (error) {
            console.error('Failed to create browser preview:', error);
            toast.error('Failed to create browser preview');
          }
          return;
        }

        // Workflow drops
        if (item.type === 'workflow' && item.template_definition) {
          await instantiateWorkflow(item, dropPosition);
          return;
        }

        // External service with credentials
        const isExternalService =
          item.type === 'service' &&
          (item.service_type === 'external' || item.service_type === 'hybrid') &&
          item.credential_fields?.length > 0;

        if (isExternalService) {
          setExternalServiceModal({
            isOpen: true,
            item: item,
            position: dropPosition,
          });
          return;
        }

        // Default: create container node
        await createContainerNode(item, dropPosition);
      },
      [
        slug,
        project,
        projectId,
        setNodes,
        handleDeleteBrowser,
        reactFlowInstance,
        handleDeployFromTarget,
        handleConnectDeploymentTarget,
        handleDeleteDeploymentTarget,
        handleRollbackDeployment,
        handleEnvironmentChange,
        createContainerNode,
        instantiateWorkflow,
      ]
    );

    const onDragOver = useCallback((event: React.DragEvent) => {
      event.preventDefault();
      event.dataTransfer.dropEffect = 'move';
    }, []);

    // -----------------------------------------------------------------------
    // Node interaction callbacks
    // -----------------------------------------------------------------------

    const handleNodeDragStart = useCallback(() => {
      setIsDragging(true);
    }, []);

    const handleNodeDragStop = useCallback(
      async (_event: React.MouseEvent | React.TouchEvent | MouseEvent | TouchEvent, node: Node) => {
        setIsDragging(false);

        if (typeof node.id === 'string' && node.id.startsWith('temp-')) {
          return;
        }

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

    const handleNodeClick = useCallback(
      (_: React.MouseEvent, node: Node) => {
        if (node.type === 'browserPreview' || node.type === 'deploymentTarget') {
          return;
        }
        handleContainerClick(node.id);
      },
      [handleContainerClick]
    );

    const handleNodeDoubleClick = useCallback(
      (_: React.MouseEvent, node: Node) => {
        if (node.type === 'browserPreview' || node.type === 'deploymentTarget') {
          return;
        }
        const containerType = node.data?.containerType || 'base';
        if (containerType === 'base') {
          handleOpenBuilder(node.id);
        }
      },
      [handleOpenBuilder]
    );

    const handleEdgeClick = useCallback((_: React.MouseEvent, _edge: Edge) => {
      // Edge is automatically selected by ReactFlow — EdgeDeleteButton renders on selection
    }, []);

    const handlePaneClick = useCallback(() => {
      if (document.activeElement instanceof HTMLElement) {
        document.activeElement.blur();
      }
      document.body.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    }, []);

    const handleBeforeDelete = useCallback(
      async ({ edges: edgesToDelete }: { nodes: Node[]; edges: Edge[] }) => {
        return { nodes: [] as Node[], edges: edgesToDelete };
      },
      []
    );

    // -----------------------------------------------------------------------
    // Edge deletion
    // -----------------------------------------------------------------------

    const handleEdgesDelete = useCallback(
      async (deletedEdges: Edge[]) => {
        for (const edge of deletedEdges) {
          try {
            if (edge.type === 'browser_preview' || edge.id.startsWith('browser-edge-')) {
              const browserPreviewId = edge.target;
              await api.delete(
                `/api/projects/${slugRef.current}/browser-previews/${browserPreviewId}/disconnect`
              );

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
              const deploymentTargetId = edge.target;
              const containerId = edge.source;
              await deploymentTargetsApi.disconnect(
                slugRef.current!,
                deploymentTargetId,
                containerId
              );

              setNodes((nds) =>
                nds.map((node) =>
                  node.id === deploymentTargetId
                    ? {
                        ...node,
                        data: {
                          ...node.data,
                          connectedContainers: (
                            (node.data.connectedContainers as Array<{ id: string }> | undefined) ||
                            []
                          ).filter((c) => c.id !== containerId),
                        },
                      }
                    : node
                )
              );
            } else {
              await api.delete(
                `/api/projects/${slugRef.current}/containers/connections/${edge.id}`
              );
            }
          } catch (error) {
            console.error('Failed to delete connection:', error);
            toast.error('Failed to delete connection');
            return;
          }
        }

        setEdges((eds) => eds.filter((e) => !deletedEdges.some((de) => de.id === e.id)));

        for (const edge of deletedEdges) {
          connectionEvents.emit('connection-deleted', edge.source, edge.target);
        }

        toast.success(`Deleted ${deletedEdges.length} connection(s)`);
        setConfigDirty(true);
      },
      [setNodes, setEdges]
    );

    // -----------------------------------------------------------------------
    // Auto layout
    // -----------------------------------------------------------------------

    const handleAutoLayout = useCallback(async () => {
      if (nodes.length < 2) {
        toast('Add more nodes to use auto layout', { icon: '\u2139\uFE0F' });
        return;
      }

      const { nodes: layoutedNodes } = getLayoutedElements(nodes, edges, {
        direction: 'LR',
        nodeWidth: 180,
        nodeHeight: 100,
      });

      setNodes(layoutedNodes);
      toast.loading('Arranging nodes...', { id: 'autolayout' });

      try {
        const updates = layoutedNodes.map((node) => {
          if (node.type === 'browserPreview') {
            return api.patch(`/api/projects/${slug}/browser-previews/${node.id}`, {
              position_x: Math.round(node.position.x),
              position_y: Math.round(node.position.y),
            });
          } else if (node.type === 'deploymentTarget') {
            return deploymentTargetsApi.update(slug, node.id, {
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

    // -----------------------------------------------------------------------
    // Start / Stop all
    // -----------------------------------------------------------------------

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

    // -----------------------------------------------------------------------
    // Config sync
    // -----------------------------------------------------------------------

    const handleSaveConfig = async () => {
      if (!slug) return;
      try {
        toast.loading('Saving config to .tesslate/config.json...', { id: 'save-config' });
        const result = await configSyncApi.save(slug);
        const total = Object.values(result.sections).reduce((sum, n) => sum + n, 0);
        toast.success(`Config saved (${total} items)`, { id: 'save-config', duration: 2000 });
        setConfigDirty(false);
        loadFiles();
        fileEvents.emit('file-updated', '.tesslate/config.json');
      } catch (_error) {
        toast.error('Failed to save configuration', { id: 'save-config' });
      }
    };

    const handleLoadConfig = async () => {
      if (!slug) return;
      try {
        toast.loading('Loading config from .tesslate/config.json...', { id: 'load-config' });
        const configResponse = await setupApi.getConfig(slug);
        if (!configResponse.exists) {
          toast.error('No .tesslate/config.json found', { id: 'load-config' });
          return;
        }
        const { exists: _exists, ...config } = configResponse;
        const result = await configSyncApi.load(slug, config);
        toast.success(`Config loaded (${result.container_ids.length} containers)`, {
          id: 'load-config',
          duration: 2000,
        });
        await fetchProjectData();
        setConfigDirty(false);
        onContainersChanged();
      } catch (_error) {
        toast.error('Failed to load configuration', { id: 'load-config' });
      }
    };

    // -----------------------------------------------------------------------
    // Imperative handle
    // -----------------------------------------------------------------------

    useImperativeHandle(ref, () => ({
      saveConfig: handleSaveConfig,
      loadConfig: handleLoadConfig,
      autoLayout: handleAutoLayout,
      startAll: handleStartAll,
      stopAll: handleStopAll,
      get configDirty() {
        return configDirty;
      },
      get isRunning() {
        return isRunning;
      },
    }));

    // -----------------------------------------------------------------------
    // Loading state
    // -----------------------------------------------------------------------

    if (!project) {
      return (
        <div className="flex items-center justify-center h-full bg-[var(--bg)]">
          <div className="text-[var(--text)]/60">Loading project...</div>
        </div>
      );
    }

    // -----------------------------------------------------------------------
    // Render
    // -----------------------------------------------------------------------

    return (
      <div className="flex-1 flex relative h-full">
        {/* React Flow canvas area */}
        <div className="flex-1 relative bg-[var(--bg)] [&_.react-flow__renderer]:will-change-transform [&_.react-flow__edges]:will-change-transform [&_.react-flow__nodes]:will-change-transform">
          {/* Floating component drawer — hidden for viewers */}
          {!readOnly && (
            <MarketplaceSidebar
              onAutoLayout={handleAutoLayout}
              autoLayoutDisabled={nodes.length < 2}
              focusSignal={marketplaceFocus ?? null}
            />
          )}

          <GraphCanvas
            nodes={nodes}
            edges={edges}
            onNodesChange={(readOnly ? undefined : onNodesChange)!}
            onEdgesChange={(readOnly ? undefined : onEdgesChange)!}
            onConnect={(readOnly ? undefined : onConnect)!}
            onDrop={(readOnly ? undefined : onDrop)!}
            onDragOver={(readOnly ? undefined : onDragOver)!}
            onInit={() => {}}
            onNodeDragStart={readOnly ? undefined : handleNodeDragStart}
            onNodeDragStop={(readOnly ? undefined : handleNodeDragStop)!}
            onNodeClick={handleNodeClick}
            onNodeDoubleClick={(readOnly ? undefined : handleNodeDoubleClick)!}
            onEdgeClick={readOnly ? undefined : handleEdgeClick}
            onEdgesDelete={readOnly ? undefined : handleEdgesDelete}
            onBeforeDelete={readOnly ? undefined : handleBeforeDelete}
            onPaneClick={handlePaneClick}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            theme={theme}
          />
        </div>

        {/* Container Properties Panel — inline with graph, hidden for viewers */}
        {selectedContainer && !readOnly && (
          <ContainerPropertiesPanel
            containerId={selectedContainer.id}
            containerName={selectedContainer.name}
            containerStatus={selectedContainer.status}
            projectSlug={slug}
            port={selectedContainer.port}
            containerType={selectedContainer.containerType}
            onConfigure={
              projectId
                ? () =>
                    nodeConfigEvents.emit('open-config-tab-request', {
                      projectId,
                      containerId: selectedContainer.id,
                      containerName: selectedContainer.name,
                    })
                : undefined
            }
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
              setNodes((nds) =>
                nds.map((node) =>
                  node.id === selectedContainer.id
                    ? { ...node, data: { ...node.data, name: newName } }
                    : node
                )
              );
              setSelectedContainer({ ...selectedContainer, name: newName });
            }}
          />
        )}

        {/* External Service Credential Modal */}
        {externalServiceModal.item && (
          <ExternalServiceCredentialModal
            isOpen={externalServiceModal.isOpen}
            item={externalServiceModal.item as unknown as ExternalServiceItem}
            onClose={() => setExternalServiceModal({ isOpen: false, item: null, position: null })}
            onSubmit={handleExternalServiceCredentialSubmit}
          />
        )}

        {/* Provider Connect Modal for deployment targets */}
        <ProviderConnectModal
          isOpen={providerConnectModal.isOpen}
          onClose={() => setProviderConnectModal({ isOpen: false, targetId: null, provider: null })}
          onConnected={handleProviderConnected}
          defaultProvider={providerConnectModal.provider || undefined}
          connectedProviders={connectedProviders}
        />

        {/* Confirm dialog for destructive actions */}
        <ConfirmDialog
          isOpen={confirmDialog.isOpen}
          onClose={() => setConfirmDialog((prev) => ({ ...prev, isOpen: false }))}
          onConfirm={confirmDialog.onConfirm}
          title={confirmDialog.title}
          message={confirmDialog.message}
          confirmText={confirmDialog.confirmText}
          variant={confirmDialog.variant}
        />

      </div>
    );
  }
);

ArchitectureViewInner.displayName = 'ArchitectureViewInner';

// ---------------------------------------------------------------------------
// Outer wrapper — provides ReactFlowProvider
// ---------------------------------------------------------------------------

export const ArchitectureView = forwardRef<ArchitectureViewHandle, ArchitectureViewProps>(
  (props, ref) => (
    <ReactFlowProvider>
      <ArchitectureViewInner ref={ref} {...props} />
    </ReactFlowProvider>
  )
);

ArchitectureView.displayName = 'ArchitectureView';
