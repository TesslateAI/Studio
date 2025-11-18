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
} from '@phosphor-icons/react';
import { motion } from 'framer-motion';
import { ContainerNode } from '../components/ContainerNode';
import { BaseSidebar } from '../components/BaseSidebar';
import { Breadcrumbs } from '../components/ui/Breadcrumbs';
import { Tooltip } from '../components/ui/Tooltip';
import { MobileWarning } from '../components/MobileWarning';
import { MobileMenu } from '../components/ui/MobileMenu';
import { ChatContainer } from '../components/chat/ChatContainer';
import { FloatingPanel } from '../components/ui/FloatingPanel';
import { GitHubPanel, NotesPanel, SettingsPanel, KanbanPanel } from '../components/panels';
import { DiscordSupport } from '../components/DiscordSupport';
import CodeEditor from '../components/CodeEditor';
import api, { projectsApi, marketplaceApi } from '../lib/api';
import { useTheme } from '../theme/ThemeContext';
import { fileEvents } from '../utils/fileEvents';
import toast from 'react-hot-toast';

const nodeTypes: NodeTypes = {
  containerNode: ContainerNode,
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

  useEffect(() => {
    if (slug) {
      fetchProjectData();
      loadFiles();
      loadAgents();
    }
  }, [slug]);

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
          onDelete: handleDeleteContainer,
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

      const base = JSON.parse(baseData);
      const reactFlowBounds = reactFlowWrapper.current.getBoundingClientRect();

      // Calculate position on canvas
      const position = {
        x: event.clientX - reactFlowBounds.left - 100, // Center the node
        y: event.clientY - reactFlowBounds.top - 50,
      };

      try {
        // Create container in backend
        const response = await api.post(`/api/projects/${slug}/containers`, {
          project_id: project.id,
          base_id: base.id,
          name: base.name,
          position_x: position.x,
          position_y: position.y,
        });

        const newContainer = response.data;

        // Add to canvas
        const newNode: Node = {
          id: newContainer.id,
          type: 'containerNode',
          position,
          data: {
            name: newContainer.name,
            status: 'stopped',
            baseIcon: base.icon,
            techStack: base.tech_stack || [],
            onDelete: handleDeleteContainer,
          },
        };

        setNodes((nds) => [...nds, newNode]);
        toast.success(`Added ${base.name}`);
      } catch (error) {
        console.error('Failed to add container:', error);
        toast.error('Failed to add container');
      }
    },
    [slug, project, setNodes]
  );

  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
  }, []);

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
      title: 'Architecture Graph',
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
      title: 'Agent Marketplace',
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
          <div className={`w-full h-full ${activeView === 'graph' ? 'flex' : 'hidden'}`}>
            {/* Left sidebar with bases (only in graph view) */}
            <BaseSidebar />

            {/* React Flow canvas */}
            <div className="flex-1" ref={reactFlowWrapper}>
              <ReactFlow
                nodes={nodes}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onConnect={onConnect}
                onDrop={onDrop}
                onDragOver={onDragOver}
                onNodeDragStop={handleNodeDragStop}
                onNodeDoubleClick={(_, node) => handleOpenBuilder(node.id)}
                nodeTypes={nodeTypes}
                defaultViewport={{ x: 0, y: 0, zoom: 0.5 }}
                fitView
                fitViewOptions={{ padding: 0.3, minZoom: 0.3, maxZoom: 1.5 }}
                minZoom={0.1}
                maxZoom={2}
                className="bg-[var(--bg)]"
              >
                <Background
                  variant={BackgroundVariant.Dots}
                  gap={16}
                  size={1}
                  color={theme === 'dark' ? '#374151' : '#e5e7eb'}
                />
                <Controls />
                <Panel position="top-right" className="bg-[var(--surface)] px-4 py-2 rounded-lg shadow-lg border border-[var(--sidebar-border)]">
                  <p className="text-xs text-[var(--text)]/60">
                    Double-click a container to open the builder
                  </p>
                </Panel>
              </ReactFlow>
            </div>
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
          agents={agents}
          currentAgent={agents[0]}
          onSelectAgent={(agent) => console.log('Selected agent:', agent)}
          onFileUpdate={handleFileUpdate}
          projectFiles={files}
          projectName={project?.name}
          sidebarExpanded={isLeftSidebarExpanded}
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
    </div>
  );
};
