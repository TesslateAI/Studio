import React, { useState, useCallback, useRef, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ReactFlow,
  Background,
  Controls,
  addEdge,
  useNodesState,
  useEdgesState,
  type Edge,
  type Node,
  type NodeTypes,
  BackgroundVariant,
  Panel,
  type OnConnect,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {
  ArrowLeft,
  Play,
  Stop,
  Code,
  FlowArrow,
  Sun,
  Moon,
  List,
  Storefront,
  BookOpen,
  GitBranch,
  Gear,
  Article,
  Kanban,
  Package,
  X,
  ArrowsOutSimple,
  Hand,
} from '@phosphor-icons/react';
import { motion, AnimatePresence } from 'framer-motion';
import { ContainerNode } from '../components/ContainerNode';
import { MarketplaceSidebar } from '../components/MarketplaceSidebar';
import { ContainerPropertiesPanel } from '../components/ContainerPropertiesPanel';
import { Breadcrumbs } from '../components/ui/Breadcrumbs';
import { Tooltip } from '../components/ui/Tooltip';
import { MobileWarning } from '../components/MobileWarning';
import { MobileMenu } from '../components/ui/MobileMenu';
import { ChatContainer } from '../components/chat/ChatContainer';
import { FloatingPanel } from '../components/ui/FloatingPanel';
import { GitHubPanel, NotesPanel, SettingsPanel, KanbanPanel } from '../components/panels';
import { DiscordSupport } from '../components/DiscordSupport';
import CodeEditor from '../components/CodeEditor';
import { ExternalServiceCredentialModal } from '../components/ExternalServiceCredentialModal';
import api, { projectsApi, marketplaceApi, deploymentCredentialsApi } from '../lib/api';
import { useTheme } from '../theme/ThemeContext';
import { fileEvents } from '../utils/fileEvents';
import toast from 'react-hot-toast';
import { EnvInjectionEdge, HttpApiEdge, DatabaseEdge, CacheEdge, getEdgeType } from '../components/edges';

const nodeTypes: NodeTypes = {
  containerNode: ContainerNode,
};

// Custom edge types for different connector semantics
const edgeTypes = {
  env_injection: EnvInjectionEdge,
  http_api: HttpApiEdge,
  database: DatabaseEdge,
  cache: CacheEdge,
};

type PanelType = 'github' | 'notes' | 'settings' | null;
type MainViewType = 'graph' | 'code' | 'kanban';

interface Container {
  id: string;
  name: string;
  base_id: string | null;
  position_x: number;
  position_y: number;
  status: 'stopped' | 'starting' | 'running' | 'failed';
  port?: number;
}

interface ContainerConnection {
  id: string;
  source_container_id: string;
  target_container_id: string;
  connection_type: string;
  label?: string;
}

interface UIAgent {
  id: string;
  name: string;
  icon: string;
  backendId: number;
  mode: 'stream' | 'agent';
}

export const ProjectGraphCanvas = () => {
  const { slug } = useParams<{ slug: string }>();
  const navigate = useNavigate();
  const { theme, toggleTheme } = useTheme();
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [project, setProject] = useState<any>(null);
  const [files, setFiles] = useState<any[]>([]);
  const [agents, setAgents] = useState<UIAgent[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const [activeView, setActiveView] = useState<MainViewType>('graph');
  const [activePanel, setActivePanel] = useState<PanelType>(null);
  const [isLeftSidebarExpanded, setIsLeftSidebarExpanded] = useState(() => {
    const saved = localStorage.getItem('graphCanvasSidebarExpanded');
    return saved !== null ? JSON.parse(saved) : true;
  });
  const [selectedContainer, setSelectedContainer] = useState<{id: string, name: string, status: string} | null>(null);

  // Mobile state
  const [isMobileComponentsOpen, setIsMobileComponentsOpen] = useState(false);

  // External service credential modal state
  const [externalServiceModal, setExternalServiceModal] = useState<{
    isOpen: boolean;
    item: any | null;
    position: { x: number; y: number } | null;
  }>({ isOpen: false, item: null, position: null });

  useEffect(() => {
    if (slug) {
      fetchProjectData();
      loadFiles();
      loadAgents();
    }
  }, [slug]);

  // Poll for container runtime status to update node statuses
  useEffect(() => {
    if (!slug || nodes.length === 0) return;

    const pollContainerStatus = async () => {
      try {
        const statusData = await projectsApi.getContainersRuntimeStatus(slug);
        if (statusData.containers) {
          // Update nodes with actual Docker status
          setNodes((currentNodes) =>
            currentNodes.map((node) => {
              // Find matching container by service name (sanitized container name)
              // Must match backend sanitization: lowercase, replace non-alphanumeric with dash, collapse dashes, strip leading/trailing dashes
              const serviceName = node.data.name?.toLowerCase()
                .replace(/[^a-z0-9-]/g, '-')
                .replace(/-+/g, '-')
                .replace(/^-|-$/g, ''); // Strip leading/trailing dashes
              const containerStatus = statusData.containers[serviceName];

              if (containerStatus) {
                const newStatus = containerStatus.running ? 'running' : 'stopped';
                if (node.data.status !== newStatus) {
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
            })
          );

          // Update isRunning state based on overall status
          setIsRunning(statusData.status === 'running');
        }
      } catch (error) {
        // Silently ignore errors - container might not be started yet
        console.debug('Container status poll error:', error);
      }
    };

    // Initial poll
    pollContainerStatus();

    // Poll every 5 seconds
    const interval = setInterval(pollContainerStatus, 5000);

    return () => clearInterval(interval);
  }, [slug, nodes.length, setNodes]);

  useEffect(() => {
    localStorage.setItem('graphCanvasSidebarExpanded', JSON.stringify(isLeftSidebarExpanded));
  }, [isLeftSidebarExpanded]);

  // Listen for file events - PRIMARY real-time update mechanism
  useEffect(() => {
    const unsubscribe = fileEvents.on((detail) => {
      console.log('File event received:', detail.type, detail.filePath);
      // Refresh the file list when any file changes
      loadFiles();
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

      // Convert to React Flow nodes
      const flowNodes: Node[] = containers.map((container: Container) => ({
        id: container.id,
        type: 'containerNode',
        position: { x: container.position_x, y: container.position_y },
        data: {
          name: container.name,
          status: container.status,
          port: container.port,
          baseIcon: '📦', // TODO: Get from base info
          techStack: [], // TODO: Get from base info
          containerType: container.container_type || 'base',
          onDelete: handleDeleteContainer,
          onClick: handleContainerClick,
          onDoubleClick: handleOpenBuilder,
        },
      }));

      // Convert to React Flow edges
      const flowEdges: Edge[] = connections.map((connection) => ({
        id: connection.id,
        source: connection.source_container_id,
        target: connection.target_container_id,
        type: 'smoothstep',
        label: connection.label,
        animated: true,
      }));

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

    // Track if this is a new file or an update
    const isNewFile = !files.find(f => f.file_path === filePath);

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

      // Emit file event to refresh the code editor file tree
      fileEvents.emit(isNewFile ? 'file-created' : 'file-updated', filePath);
    } catch (error) {
      console.error('Failed to save file:', error);
      toast.error(`Failed to save ${filePath}`);
    }
  }, [slug, files]);

  const togglePanel = (panel: PanelType) => {
    setActivePanel(activePanel === panel ? null : panel);
  };

  const onConnect: OnConnect = useCallback(
    async (connection) => {
      if (!connection.source || !connection.target) return;

      try {
        // Create connection in backend
        await api.post(`/api/projects/${slug}/containers/connections`, {
          project_id: project.id,
          source_container_id: connection.source,
          target_container_id: connection.target,
          connection_type: 'depends_on',
        });

        // Update local state
        setEdges((eds) => addEdge({ ...connection, type: 'smoothstep', animated: true }, eds));
        toast.success('Connection created');
      } catch (error) {
        console.error('Failed to create connection:', error);
        toast.error('Failed to create connection');
      }
    },
    [slug, project, setEdges]
  );

  const onDrop = useCallback(
    async (event: React.DragEvent) => {
      event.preventDefault();

      const baseData = event.dataTransfer.getData('base');
      if (!baseData || !reactFlowWrapper.current) return;

      const item = JSON.parse(baseData);
      const reactFlowBounds = reactFlowWrapper.current.getBoundingClientRect();

      // Calculate position on canvas (base position for dropped item or workflow)
      const dropPosition = {
        x: event.clientX - reactFlowBounds.left - 100,
        y: event.clientY - reactFlowBounds.top - 50,
      };

      // Handle workflow drops differently
      if (item.type === 'workflow' && item.template_definition) {
        await instantiateWorkflow(item, dropPosition);
        return;
      }

      // Check if this is an external service that needs credentials
      const isExternalService = item.type === 'service' &&
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
    [slug, project, setNodes]
  );

  // Instantiate a workflow template (creates multiple nodes and connections)
  const instantiateWorkflow = useCallback(
    async (workflow: any, basePosition: { x: number; y: number }) => {
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
          let itemToCreate: any;
          if (nodeTemplate.type === 'base') {
            itemToCreate = {
              type: 'base',
              name: nodeTemplate.name,
              slug: nodeTemplate.base_slug,
              id: nodeTemplate.base_slug, // Will be resolved by backend
            };
          } else if (nodeTemplate.type === 'service') {
            itemToCreate = {
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
          const payload: any = {
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
            console.warn(`Missing container for edge: ${edgeTemplate.source} -> ${edgeTemplate.target}`);
            continue;
          }

          // Create connection in backend
          await api.post(`/api/projects/${slug}/connections`, {
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
        } catch (e) {
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
      item: any,
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
        const payload: any = {
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

  const handleContainerClick = useCallback((containerId: string) => {
    const containerNode = nodes.find(n => n.id === containerId);
    if (containerNode) {
      setSelectedContainer({
        id: containerId,
        name: containerNode.data.name,
        status: containerNode.data.status,
        port: containerNode.data.port,
      });
    }
  }, [nodes]);

  const handleDeleteContainer = useCallback(
    async (containerId: string) => {
      // Get container name for the confirmation message
      const containerNode = nodes.find(n => n.id === containerId);
      const containerName = containerNode?.data?.name || 'this container';

      if (!confirm(`Are you sure you want to delete ${containerName}?`)) return;

      try {
        // Delete the container from backend
        await api.delete(`/api/projects/${slug}/containers/${containerId}`);

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
          // Find all files that belong to this container
          const containerFiles = files.filter(file => {
            // Files are typically organized as: containerName/...
            const pathParts = file.file_path.split('/');
            return pathParts[0] === containerName || pathParts[0] === containerId;
          });

          if (containerFiles.length === 0) {
            toast.info('No files found for this container');
            return;
          }

          // Delete each file
          const deletePromises = containerFiles.map(file =>
            projectsApi.deleteFile(slug!, file.file_path)
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
    [slug, nodes, files, setNodes, setEdges, loadFiles]
  );

  const handleNodeDragStop = useCallback(
    async (_event: any, node: Node) => {
      // Skip API call for temporary nodes (not yet saved to backend)
      if (typeof node.id === 'string' && node.id.startsWith('temp-')) {
        return;
      }

      try {
        // Update position in backend
        await api.patch(`/api/projects/${slug}/containers/${node.id}`, {
          position_x: node.position.x,
          position_y: node.position.y,
        });
      } catch (error) {
        console.error('Failed to update container position:', error);
      }
    },
    [slug]
  );

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

  const handleOpenBuilder = (containerId: string) => {
    navigate(`/project/${slug}/builder?container=${containerId}`);
  };

  if (!project) {
    return (
      <div className="flex items-center justify-center h-full bg-[var(--bg)]">
        <div className="text-[var(--text)]/60">Loading project...</div>
      </div>
    );
  }

  const leftSidebarItems = [
    {
      icon: <FlowArrow size={18} />,
      title: 'Architecture',
      onClick: () => setActiveView('graph'),
      active: activeView === 'graph'
    },
    {
      icon: <Code size={18} />,
      title: 'Code',
      onClick: () => setActiveView('code'),
      active: activeView === 'code'
    },
    {
      icon: <Kanban size={18} />,
      title: 'Kanban Board',
      onClick: () => setActiveView('kanban'),
      active: activeView === 'kanban'
    },
  ];

  const rightSidebarItems = [
    {
      icon: theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />,
      title: 'Toggle Theme',
      onClick: toggleTheme
    },
    {
      icon: <BookOpen size={18} />,
      title: 'Notes',
      onClick: () => togglePanel('notes'),
      active: activePanel === 'notes'
    },
    {
      icon: <GitBranch size={18} />,
      title: 'GitHub Sync',
      onClick: () => togglePanel('github'),
      active: activePanel === 'github'
    },
    {
      icon: <Storefront size={18} />,
      title: 'Agents',
      onClick: () => navigate('/marketplace')
    },
    {
      icon: <Article size={18} />,
      title: 'Documentation',
      onClick: () => window.open('https://docs.tesslate.com', '_blank')
    },
    {
      icon: <Gear size={18} />,
      title: 'Settings',
      onClick: () => togglePanel('settings'),
      active: activePanel === 'settings'
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
          type: "spring",
          stiffness: 700,
          damping: 28,
          mass: 0.4
        }}
        className="hidden md:flex flex-col bg-[var(--surface)] border-r border-[var(--sidebar-border)] overflow-x-hidden"
      >
        {/* Tesslate Logo */}
        <div className={`flex items-center h-12 flex-shrink-0 ${isLeftSidebarExpanded ? 'px-3 gap-3' : 'justify-center'} border-b border-[var(--sidebar-border)]`}>
          <svg className="w-5 h-5 text-[var(--primary)] flex-shrink-0" viewBox="0 0 161.9 126.66">
            <path d="m13.45,46.48h54.06c10.21,0,16.68-10.94,11.77-19.89l-9.19-16.75c-2.36-4.3-6.87-6.97-11.77-6.97H22.41c-4.95,0-9.5,2.73-11.84,7.09L1.61,26.71c-4.79,8.95,1.69,19.77,11.84,19.77Z" fill="currentColor"/>
            <path d="m61.05,119.93l26.95-46.86c5.09-8.85-1.17-19.91-11.37-20.12l-19.11-.38c-4.9-.1-9.47,2.48-11.91,6.73l-17.89,31.12c-2.47,4.29-2.37,9.6.25,13.8l10.05,16.13c5.37,8.61,17.98,8.39,23.04-.41Z" fill="currentColor"/>
            <path d="m148.46,0h-54.06c-10.21,0-16.68,10.94-11.77,19.89l9.19,16.75c2.36,4.3,6.87,6.97,11.77,6.97h35.9c4.95,0,9.5-2.73,11.84-7.09l8.97-16.75C165.08,10.82,158.6,0,148.46,0Z" fill="currentColor"/>
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
              <ArrowLeft size={18} className="text-[var(--text)]/40 group-hover:text-[var(--text)] transition-colors" />
              <span className="text-sm font-medium text-[var(--text)]">Back to Projects</span>
            </button>
          ) : (
            <Tooltip content="Back to Projects" side="right" delay={200}>
              <button
                onClick={() => navigate('/dashboard')}
                className="group flex items-center justify-center h-9 hover:bg-[var(--sidebar-hover)] transition-colors w-full flex-shrink-0"
              >
                <ArrowLeft size={18} className="text-[var(--text)]/40 group-hover:text-[var(--text)] transition-colors" />
              </button>
            </Tooltip>
          )}

          <div className="h-px bg-[var(--sidebar-border)] my-1 mx-2 flex-shrink-0" />

          {/* Main View Toggles */}
          {leftSidebarItems.map((item, index) => (
            isLeftSidebarExpanded ? (
              <button
                key={index}
                onClick={item.onClick}
                className={`group flex items-center h-9 transition-colors flex-shrink-0 gap-3 rounded-lg mx-2 px-3 ${
                  item.active
                    ? 'bg-[var(--sidebar-active)]'
                    : 'hover:bg-[var(--sidebar-hover)]'
                }`}
              >
                {React.cloneElement(item.icon, {
                  className: `transition-colors ${
                    item.active
                      ? 'text-[var(--text)]'
                      : 'text-[var(--text)]/40 group-hover:text-[var(--text)]'
                  }`
                })}
                <span className="text-sm font-medium text-[var(--text)]">{item.title}</span>
              </button>
            ) : (
              <Tooltip key={index} content={item.title} side="right" delay={200}>
                <button
                  onClick={item.onClick}
                  className={`group flex items-center justify-center h-9 transition-colors w-full flex-shrink-0 ${
                    item.active
                      ? 'bg-[var(--sidebar-active)]'
                      : 'hover:bg-[var(--sidebar-hover)]'
                  }`}
                >
                  {React.cloneElement(item.icon, {
                    className: `transition-colors ${
                      item.active
                        ? 'text-[var(--text)]'
                        : 'text-[var(--text)]/40 group-hover:text-[var(--text)]'
                    }`
                  })}
                </button>
              </Tooltip>
            )
          ))}

          <div className="h-px bg-[var(--sidebar-border)] my-1 mx-2 flex-shrink-0" />

          {/* Settings & Tools */}
          {rightSidebarItems.map((item, index) => (
            isLeftSidebarExpanded ? (
              <button
                key={index}
                onClick={item.onClick}
                className={`group flex items-center h-9 transition-colors flex-shrink-0 gap-3 rounded-lg mx-2 px-3 ${
                  item.active
                    ? 'bg-[var(--sidebar-active)]'
                    : 'hover:bg-[var(--sidebar-hover)]'
                }`}
              >
                {React.cloneElement(item.icon, {
                  className: `transition-colors ${
                    item.active
                      ? 'text-[var(--text)]'
                      : 'text-[var(--text)]/40 group-hover:text-[var(--text)]'
                  }`
                })}
                <span className="text-sm font-medium text-[var(--text)]">{item.title}</span>
              </button>
            ) : (
              <Tooltip key={index} content={item.title} side="right" delay={200}>
                <button
                  onClick={item.onClick}
                  className={`group flex items-center justify-center h-9 transition-colors w-full flex-shrink-0 ${
                    item.active
                      ? 'bg-[var(--sidebar-active)]'
                      : 'hover:bg-[var(--sidebar-hover)]'
                  }`}
                >
                  {React.cloneElement(item.icon, {
                    className: `transition-colors ${
                      item.active
                        ? 'text-[var(--text)]'
                        : 'text-[var(--text)]/40 group-hover:text-[var(--text)]'
                    }`
                  })}
                </button>
              </Tooltip>
            )
          ))}

          {/* Spacer to push collapse button to bottom */}
          <div className="flex-1" />

          <div className="h-px bg-[var(--sidebar-border)] my-1 mx-2 flex-shrink-0" />

          {/* Collapse/Expand Toggle */}
          {isLeftSidebarExpanded ? (
            <button
              onClick={() => setIsLeftSidebarExpanded(false)}
              className="group flex items-center h-9 hover:bg-[var(--sidebar-hover)] transition-colors flex-shrink-0 gap-3 rounded-lg mx-2 px-3"
            >
              <List size={18} weight="bold" className="text-[var(--text)]/40 group-hover:text-[var(--text)] transition-colors" />
              <span className="text-sm font-medium text-[var(--text)]">Collapse</span>
            </button>
          ) : (
            <Tooltip content="Expand" side="right" delay={200}>
              <button
                onClick={() => setIsLeftSidebarExpanded(true)}
                className="group flex items-center justify-center h-9 hover:bg-[var(--sidebar-hover)] transition-colors w-full flex-shrink-0"
              >
                <List size={18} weight="bold" className="text-[var(--text)]/40 group-hover:text-[var(--text)] transition-colors" />
              </button>
            </Tooltip>
          )}
        </div>
      </motion.div>

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Top Bar with Breadcrumbs */}
        <div className="h-12 bg-[var(--surface)] border-b border-[var(--sidebar-border)] flex items-center justify-between px-4 md:px-6">
          <Breadcrumbs
            items={[
              { label: 'Projects', href: '/dashboard' },
              { label: project.name, href: `/project/${slug}` },
              { label: 'Architecture' }
            ]}
          />

          {/* Control buttons */}
          <div className="flex items-center gap-3">
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
            <svg className="w-6 h-6 text-[var(--text)]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
        </div>

        {/* Main View Container */}
        <div className="flex-1 overflow-hidden bg-[var(--bg)]">
          {/* Graph View */}
          <div className={`w-full h-full ${activeView === 'graph' ? 'flex' : 'hidden'} relative`}>
            {/* Left sidebar with marketplace items - hidden on mobile, shown as overlay when toggled */}
            <div className="hidden md:block">
              <MarketplaceSidebar />
            </div>

            {/* Mobile Components Sidebar Overlay */}
            <AnimatePresence>
              {isMobileComponentsOpen && (
                <>
                  {/* Backdrop */}
                  <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.2 }}
                    className="md:hidden fixed inset-0 bg-black/50 z-40"
                    onClick={() => setIsMobileComponentsOpen(false)}
                  />
                  {/* Sidebar */}
                  <motion.div
                    initial={{ x: '-100%' }}
                    animate={{ x: 0 }}
                    exit={{ x: '-100%' }}
                    transition={{ type: 'spring', stiffness: 400, damping: 30 }}
                    className="md:hidden fixed left-0 top-0 bottom-0 w-80 max-w-[85vw] z-50 shadow-2xl"
                  >
                    <div className="relative h-full">
                      <MarketplaceSidebar />
                      {/* Close button */}
                      <button
                        onClick={() => setIsMobileComponentsOpen(false)}
                        className="absolute top-3 right-3 p-2 bg-[var(--surface)] hover:bg-[var(--sidebar-hover)] rounded-full shadow-lg border border-[var(--sidebar-border)] z-10"
                      >
                        <X size={18} className="text-[var(--text)]" />
                      </button>
                    </div>
                  </motion.div>
                </>
              )}
            </AnimatePresence>

            {/* React Flow canvas */}
            <div className="flex-1 relative" ref={reactFlowWrapper}>
              <ReactFlow
                nodes={nodes}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onConnect={onConnect}
                onDrop={onDrop}
                onDragOver={onDragOver}
                onNodeDragStop={handleNodeDragStop}
                onNodeClick={(_, node) => handleContainerClick(node.id)}
                onNodeDoubleClick={(_, node) => {
                  // Only allow double-click navigation for base containers, not services
                  const containerType = node.data?.containerType || 'base';
                  if (containerType === 'base') {
                    handleOpenBuilder(node.id);
                  }
                }}
                nodeTypes={nodeTypes}
                edgeTypes={edgeTypes}
                defaultViewport={{ x: 0, y: 0, zoom: 0.5 }}
                fitView
                fitViewOptions={{ padding: 0.3, minZoom: 0.3, maxZoom: 1.5 }}
                minZoom={0.1}
                maxZoom={2}
                panOnScroll
                panOnDrag
                zoomOnPinch
                zoomOnScroll
                selectNodesOnDrag={false}
                className="bg-[var(--bg)] touch-none"
              >
                <Background
                  variant={BackgroundVariant.Dots}
                  gap={16}
                  size={1}
                  color={theme === 'dark' ? '#374151' : '#e5e7eb'}
                />
                <Controls className="!bg-[var(--surface)] !border-[var(--sidebar-border)] !shadow-lg [&>button]:!bg-[var(--surface)] [&>button]:!border-[var(--sidebar-border)] [&>button]:!fill-[var(--text)] [&>button:hover]:!bg-[var(--sidebar-hover)]" />

                {/* Desktop hint */}
                <Panel position="top-right" className="hidden md:block bg-[var(--surface)] px-4 py-2 rounded-lg shadow-lg border border-[var(--sidebar-border)]">
                  <p className="text-xs text-[var(--text)]/60">
                    Double-click a container to open the builder
                  </p>
                </Panel>

                {/* Mobile hint */}
                <Panel position="top-center" className="md:hidden bg-[var(--surface)] px-3 py-1.5 rounded-lg shadow-lg border border-[var(--sidebar-border)]">
                  <p className="text-[10px] text-[var(--text)]/60 flex items-center gap-1.5">
                    <Hand size={12} className="text-[var(--primary)]" />
                    Pinch to zoom • Drag to pan
                  </p>
                </Panel>
              </ReactFlow>

              {/* Mobile floating button to open components sidebar */}
              <button
                onClick={() => setIsMobileComponentsOpen(true)}
                className="md:hidden fixed bottom-24 left-4 z-30 flex items-center gap-2 px-4 py-3 bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white rounded-full shadow-lg transition-all active:scale-95"
              >
                <Package size={20} weight="fill" />
                <span className="text-sm font-medium">Components</span>
              </button>
            </div>

            {/* Container Properties Panel - inline with graph */}
            {selectedContainer && (
              <ContainerPropertiesPanel
                containerId={selectedContainer.id}
                containerName={selectedContainer.name}
                containerStatus={selectedContainer.status}
                projectSlug={slug || ''}
                port={selectedContainer.port}
                onClose={() => setSelectedContainer(null)}
                onStatusChange={(newStatus) => {
                  setNodes((nds) =>
                    nds.map((node) =>
                      node.id === selectedContainer.id
                        ? { ...node, data: { ...node.data, status: newStatus } }
                        : node
                    )
                  );
                  setSelectedContainer({...selectedContainer, status: newStatus});
                }}
                onNameChange={(newName) => {
                  // Update node name in the graph
                  setNodes((nds) =>
                    nds.map((node) =>
                      node.id === selectedContainer.id
                        ? { ...node, data: { ...node.data, name: newName } }
                        : node
                    )
                  );
                  // Update selected container state
                  setSelectedContainer({...selectedContainer, name: newName});
                  // Refresh project data to get updated container list
                  fetchProjectData();
                }}
              />
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

      {/* Chat Interface or Empty State */}
      {agents.length > 0 ? (
        <ChatContainer
          projectId={project?.id}
          containerId={selectedContainer?.id}
          agents={agents}
          currentAgent={agents[0]}
          onSelectAgent={(agent) => console.log('Selected agent:', agent)}
          onFileUpdate={handleFileUpdate}
          projectFiles={files}
          projectName={project?.name}
          sidebarExpanded={isLeftSidebarExpanded}
          containerId={selectedContainer?.id}
        />
      ) : (
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
