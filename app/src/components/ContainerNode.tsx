import { memo } from 'react';
import { Handle, Position, type Node } from '@xyflow/react';
import { Cube, X } from '@phosphor-icons/react';

interface ContainerNodeData extends Record<string, unknown> {
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
        className="!bg-[var(--primary)] !w-3 !h-3 !border-2 !border-[var(--surface)]"
      />
      <Handle
        type="source"
        position={Position.Right}
        className="!bg-[var(--primary)] !w-3 !h-3 !border-2 !border-[var(--surface)]"
      />

      {/* Node content */}
      <div className="bg-[var(--surface)] border-2 border-[var(--border-color)] rounded-lg shadow-lg min-w-[200px] hover:border-[var(--primary)] transition-colors">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--border-color)] bg-gradient-to-r from-[var(--sidebar-hover)] to-[var(--surface)]">
          <div className="flex items-center gap-3">
            {data.baseIcon ? (
              <span className="text-2xl">{data.baseIcon}</span>
            ) : (
              <Cube size={24} weight="duotone" className="text-[var(--primary)]" />
            )}
            <div>
              <h3 className="font-semibold text-[var(--text)]">{data.name}</h3>
              <div className="flex items-center gap-2 mt-1">
                <div className={`w-2 h-2 rounded-full ${statusDot}`} />
                <span className="text-xs text-[var(--text)]/70 capitalize">{data.status}</span>
              </div>
            </div>
          </div>

          {/* Delete button */}
          {data.onDelete && (
            <button
              onClick={() => data.onDelete?.(id)}
              className="p-1 text-[var(--text)]/40 hover:text-red-500 hover:bg-red-500/10 rounded transition-colors"
              title="Delete container"
            >
              <X size={16} weight="bold" />
            </button>
          )}
        </div>

        {/* Body */}
        <div className="px-4 py-3">
          {data.port && (
            <div className="text-xs text-[var(--text)]/70 mb-2">
              Port: <span className="font-mono font-medium text-[var(--primary)]">{data.port}</span>
            </div>
          )}

          {data.techStack && data.techStack.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {data.techStack.slice(0, 3).map((tech, index) => (
                <span
                  key={index}
                  className="px-2 py-1 text-xs font-medium bg-[var(--primary)]/10 text-[var(--primary)] rounded"
                >
                  {tech}
                </span>
              ))}
              {data.techStack.length > 3 && (
                <span className="px-2 py-1 text-xs font-medium bg-[var(--sidebar-hover)] text-[var(--text)]/70 rounded">
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
