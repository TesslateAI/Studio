import { memo, useState } from 'react';
import { Handle, Position, type Node } from '@xyflow/react';
import { Cube, X, Rocket } from '@phosphor-icons/react';

interface ContainerNodeData extends Record<string, unknown> {
  name: string;
  baseIcon?: string;
  status: 'stopped' | 'starting' | 'running' | 'failed' | 'connected';
  port?: number;
  techStack?: string[];
  containerType?: 'base' | 'service';
  serviceType?: 'container' | 'external' | 'hybrid';
  deploymentProvider?: 'vercel' | 'netlify' | 'cloudflare' | null;
  onDelete?: (id: string) => void;
  onClick?: (id: string) => void;
  onDoubleClick?: (id: string) => void;
}

type ContainerNodeProps = Node<ContainerNodeData> & { id: string; data: ContainerNodeData };

// Icon color based on container TYPE (not status)
const TYPE_COLORS: Record<string, string> = {
  external: 'bg-purple-500',
  hybrid: 'bg-cyan-500',
  service: 'bg-blue-500',
  base: 'bg-green-500',
  default: 'bg-gray-500',
};

const getTypeColor = (containerType?: string, serviceType?: string): string => {
  if (serviceType && TYPE_COLORS[serviceType]) return TYPE_COLORS[serviceType];
  if (containerType && TYPE_COLORS[containerType]) return TYPE_COLORS[containerType];
  return TYPE_COLORS.default;
};

// Custom comparison function for memo - only re-render when visual data changes
const arePropsEqual = (
  prevProps: ContainerNodeProps,
  nextProps: ContainerNodeProps
): boolean => {
  const prevData = prevProps.data;
  const nextData = nextProps.data;

  return (
    prevProps.id === nextProps.id &&
    prevData.name === nextData.name &&
    prevData.status === nextData.status &&
    prevData.port === nextData.port &&
    prevData.baseIcon === nextData.baseIcon &&
    prevData.containerType === nextData.containerType &&
    prevData.serviceType === nextData.serviceType &&
    prevData.deploymentProvider === nextData.deploymentProvider &&
    prevData.techStack?.length === nextData.techStack?.length &&
    (prevData.techStack?.every((t, i) => t === nextData.techStack?.[i]) ?? true)
  );
};

const ContainerNodeComponent = ({ data, id }: ContainerNodeProps) => {
  const typeColor = getTypeColor(data.containerType, data.serviceType);
  const [isDragOver, setIsDragOver] = useState(false);
  const dragCounter = useState(0);

  // Only base containers can receive deployment targets
  const canReceiveDeployTarget = data.containerType === 'base';

  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault();
    // Check if this is a deployment target being dragged
    const nodeType = e.dataTransfer.types.includes('application/reactflow');
    if (nodeType && canReceiveDeployTarget) {
      dragCounter[1](prev => prev + 1);
      setIsDragOver(true);
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    // Keep showing the indicator while dragging over
    if (canReceiveDeployTarget && e.dataTransfer.types.includes('application/reactflow')) {
      setIsDragOver(true);
    }
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    dragCounter[1](prev => {
      const newCount = prev - 1;
      if (newCount <= 0) {
        setIsDragOver(false);
        return 0;
      }
      return newCount;
    });
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    // Don't stopPropagation - let it bubble up to ProjectGraphCanvas for handling
    setIsDragOver(false);
    dragCounter[1](0);
  };

  return (
    <div
      className={`relative group transition-all duration-150 ${
        isDragOver ? 'scale-105' : ''
      }`}
      style={{ contain: 'layout style' }}
      onDragEnter={handleDragEnter}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {/* Connection handles */}
      <Handle
        type="target"
        position={Position.Left}
        className="!bg-[#333] !w-2.5 !h-2.5 !border !border-[#444]"
      />
      <Handle
        type="source"
        position={Position.Right}
        className="!bg-[#333] !w-2.5 !h-2.5 !border !border-[#444]"
      />

      {/* Deployment provider badge - bottom right corner */}
      {data.deploymentProvider && (
        <div className="absolute -bottom-1.5 -right-1.5 z-10" title={`Deploys to ${data.deploymentProvider}`}>
          <div className={`w-6 h-6 rounded-md flex items-center justify-center text-xs font-bold shadow-lg border-2
            ${data.deploymentProvider === 'vercel' ? 'bg-white text-black border-gray-300' : ''}
            ${data.deploymentProvider === 'netlify' ? 'bg-[#00C7B7] text-white border-[#00A799]' : ''}
            ${data.deploymentProvider === 'cloudflare' ? 'bg-[#F38020] text-white border-[#D97218]' : ''}
          `}>
            {data.deploymentProvider === 'vercel' && '▲'}
            {data.deploymentProvider === 'netlify' && '◆'}
            {data.deploymentProvider === 'cloudflare' && '🔥'}
          </div>
        </div>
      )}

      {/* Drop zone overlay - shows when dragging deployment target over */}
      {isDragOver && canReceiveDeployTarget && (
        <div className="absolute inset-0 z-20 bg-purple-500/20 border-2 border-dashed border-purple-500 rounded-xl flex items-center justify-center pointer-events-none">
          <div className="bg-purple-500 text-white px-3 py-1.5 rounded-lg text-xs font-medium flex items-center gap-1.5 shadow-lg">
            <Rocket size={14} weight="fill" />
            Drop to assign
          </div>
        </div>
      )}

      {/* Node content - no transitions for performance */}
      <div
        onClick={() => data.onClick?.(id)}
        onDoubleClick={() => {
          if (data.containerType === 'base' && data.onDoubleClick) {
            data.onDoubleClick(id);
          }
        }}
        className={`bg-[#1a1a1a] rounded-xl min-w-[180px] cursor-pointer shadow-md ${
          isDragOver && canReceiveDeployTarget ? 'ring-2 ring-purple-500' : ''
        }`}
      >
        {/* Header - Color-coded icon + Title/Status */}
        <div className="flex items-center gap-3 p-3">
          {/* Color-coded icon square */}
          <div className={`w-9 h-9 rounded-lg flex items-center justify-center ${typeColor}`}>
            {data.baseIcon ? (
              <span className="text-lg">{data.baseIcon}</span>
            ) : (
              <Cube size={20} weight="fill" className="text-white" />
            )}
          </div>

          {/* Title and status */}
          <div className="flex-1 min-w-0">
            <h3 className="font-medium text-white text-sm truncate">{data.name}</h3>
            <span className="text-xs text-gray-400 capitalize">{data.status}</span>
          </div>

          {/* Delete button - visible on hover, no transition */}
          {data.onDelete && (
            <button
              onClick={(e) => { e.stopPropagation(); data.onDelete?.(id); }}
              className="p-1.5 text-gray-500 hover:text-red-400 hover:bg-red-500/10 rounded-lg opacity-0 group-hover:opacity-100"
              title="Delete container"
            >
              <X size={14} weight="bold" />
            </button>
          )}
        </div>

        {/* Body - Only show if has content */}
        {(data.port || (data.techStack && data.techStack.length > 0)) && (
          <div className="px-3 pb-3 pt-0">
            {data.port && (
              <div className="text-xs text-gray-500 mb-2">
                Port: <span className="font-mono text-gray-400">{data.port}</span>
              </div>
            )}

            {data.techStack && data.techStack.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {data.techStack.slice(0, 3).map((tech, index) => (
                  <span
                    key={index}
                    className="px-1.5 py-0.5 text-[10px] font-medium bg-white/5 text-gray-400 rounded"
                  >
                    {tech}
                  </span>
                ))}
                {data.techStack.length > 3 && (
                  <span className="px-1.5 py-0.5 text-[10px] text-gray-500 rounded">
                    +{data.techStack.length - 3}
                  </span>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

// Export memoized component with custom comparison to prevent unnecessary re-renders
export const ContainerNode = memo(ContainerNodeComponent, arePropsEqual);

ContainerNode.displayName = 'ContainerNode';
