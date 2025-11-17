import { memo } from 'react';
import { Handle, Position, type Node } from '@xyflow/react';
import { Cube, X } from '@phosphor-icons/react';

interface ContainerNodeData {
  name: string;
  baseIcon?: string;
  status: 'stopped' | 'starting' | 'running' | 'failed';
  port?: number;
  techStack?: string[];
  onDelete?: (id: string) => void;
}

type ContainerNodeProps = Node<ContainerNodeData> & { id: string; data: ContainerNodeData };

export const ContainerNode = memo(({ data, id }: ContainerNodeProps) => {
  const statusColors = {
    stopped: 'bg-gray-500',
    starting: 'bg-yellow-500',
    running: 'bg-green-500',
    failed: 'bg-red-500',
  };

  const statusDot = statusColors[data.status] || 'bg-gray-500';

  return (
    <div className="relative">
      {/* Connection handles */}
      <Handle
        type="target"
        position={Position.Left}
        className="!bg-blue-500 !w-3 !h-3 !border-2 !border-white"
      />
      <Handle
        type="source"
        position={Position.Right}
        className="!bg-blue-500 !w-3 !h-3 !border-2 !border-white"
      />

      {/* Node content */}
      <div className="bg-white border-2 border-gray-300 rounded-lg shadow-lg min-w-[200px] hover:border-blue-500 transition-colors">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 bg-gradient-to-r from-gray-50 to-white">
          <div className="flex items-center gap-3">
            {data.baseIcon ? (
              <span className="text-2xl">{data.baseIcon}</span>
            ) : (
              <Cube size={24} weight="duotone" className="text-blue-500" />
            )}
            <div>
              <h3 className="font-semibold text-gray-900">{data.name}</h3>
              <div className="flex items-center gap-2 mt-1">
                <div className={`w-2 h-2 rounded-full ${statusDot}`} />
                <span className="text-xs text-gray-600 capitalize">{data.status}</span>
              </div>
            </div>
          </div>

          {/* Delete button */}
          {data.onDelete && (
            <button
              onClick={() => data.onDelete(id)}
              className="p-1 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded transition-colors"
              title="Delete container"
            >
              <X size={16} weight="bold" />
            </button>
          )}
        </div>

        {/* Body */}
        <div className="px-4 py-3">
          {data.port && (
            <div className="text-xs text-gray-600 mb-2">
              Port: <span className="font-mono font-medium text-blue-600">{data.port}</span>
            </div>
          )}

          {data.techStack && data.techStack.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {data.techStack.slice(0, 3).map((tech, index) => (
                <span
                  key={index}
                  className="px-2 py-1 text-xs font-medium bg-blue-100 text-blue-700 rounded"
                >
                  {tech}
                </span>
              ))}
              {data.techStack.length > 3 && (
                <span className="px-2 py-1 text-xs font-medium bg-gray-100 text-gray-600 rounded">
                  +{data.techStack.length - 3}
                </span>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
});

ContainerNode.displayName = 'ContainerNode';
