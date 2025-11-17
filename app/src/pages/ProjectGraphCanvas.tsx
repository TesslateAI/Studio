import { useState, useCallback, useRef, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
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
import api from '../lib/api';
import toast from 'react-hot-toast';

import { ContainerNode } from '../components/ContainerNode';
import { BaseSidebar } from '../components/BaseSidebar';
import { Play, Stop, ArrowLeft } from '@phosphor-icons/react';

const nodeTypes: NodeTypes = {
  containerNode: ContainerNode,
};

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

export const ProjectGraphCanvas = () => {
  const { slug } = useParams<{ slug: string }>();
  const navigate = useNavigate();
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [project, setProject] = useState<any>(null);
  const [isRunning, setIsRunning] = useState(false);

  useEffect(() => {
    if (slug) {
      fetchProjectData();
    }
  }, [slug]);

  const fetchProjectData = async () => {
    try {
      // Fetch project info
      const projectRes = await api.get(`/api/projects/${slug}`);
      setProject(projectRes.data);

      // Fetch containers
      const containersRes = await api.get(`/api/projects/${slug}/containers`);
      const containers: Container[] = containersRes.data;

      // Fetch connections
      const connectionsRes = await api.get(`/api/projects/${slug}/containers/connections`);
      const connections: ContainerConnection[] = connectionsRes.data;

      // Convert to React Flow nodes
      const flowNodes: Node[] = containers.map((container) => ({
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
      if (!confirm('Are you sure you want to delete this container?')) return;

      try {
        await api.delete(`/api/projects/${slug}/containers/${containerId}`);
        setNodes((nds) => nds.filter((node) => node.id !== containerId));
        setEdges((eds) =>
          eds.filter((edge) => edge.source !== containerId && edge.target !== containerId)
        );
        toast.success('Container deleted');
      } catch (error) {
        console.error('Failed to delete container:', error);
        toast.error('Failed to delete container');
      }
    },
    [slug, setNodes, setEdges]
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
    try {
      // TODO: Implement start all containers endpoint
      toast.success('Starting all containers...');
      setIsRunning(true);
    } catch (error) {
      toast.error('Failed to start containers');
    }
  };

  const handleStopAll = async () => {
    try {
      // TODO: Implement stop all containers endpoint
      toast.success('Stopping all containers...');
      setIsRunning(false);
    } catch (error) {
      toast.error('Failed to stop containers');
    }
  };

  const handleOpenBuilder = (containerId: string) => {
    navigate(`/project/${slug}/builder?container=${containerId}`);
  };

  return (
    <div className="flex h-screen bg-gray-50">
      {/* Left sidebar with bases */}
      <BaseSidebar />

      {/* Main canvas area */}
      <div className="flex-1 flex flex-col">
        {/* Top bar */}
        <div className="h-16 bg-white border-b border-gray-200 flex items-center justify-between px-6">
          <div className="flex items-center gap-4">
            <button
              onClick={() => navigate('/dashboard')}
              className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
            >
              <ArrowLeft size={20} />
            </button>
            <div>
              <h1 className="text-lg font-semibold text-gray-900">{project?.name || 'Project'}</h1>
              <p className="text-sm text-gray-500">Container Architecture</p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {isRunning ? (
              <button
                onClick={handleStopAll}
                className="flex items-center gap-2 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors"
              >
                <Stop size={18} weight="fill" />
                Stop All
              </button>
            ) : (
              <button
                onClick={handleStartAll}
                className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors"
              >
                <Play size={18} weight="fill" />
                Start All
              </button>
            )}
          </div>
        </div>

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
            fitView
            className="bg-gray-50"
          >
            <Background variant={BackgroundVariant.Dots} gap={16} size={1} color="#e5e7eb" />
            <Controls />
            <MiniMap
              nodeColor={(node) => {
                const status = (node.data as any).status;
                return status === 'running' ? '#10b981' : '#6b7280';
              }}
              className="!bg-white !border-2 !border-gray-200"
            />
            <Panel position="top-right" className="bg-white px-4 py-2 rounded-lg shadow-lg border border-gray-200">
              <p className="text-xs text-gray-500">
                Double-click a container to open the builder
              </p>
            </Panel>
          </ReactFlow>
        </div>
      </div>
    </div>
  );
};
