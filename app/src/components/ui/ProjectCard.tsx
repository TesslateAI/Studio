import { type ReactNode } from 'react';
import { StatusBadge } from './StatusBadge';
import type { Status } from './StatusBadge';
import { AgentTag } from './AgentTag';
import { Dropdown } from './Dropdown';

interface Project {
  id: number;
  name: string;
  description: string;
  status: Status;
  agents: Array<{ icon: ReactNode; name: string }>;
  lastUpdated: string;
  isLive?: boolean;
  userCount?: string;
  hasGitRepo?: boolean;
  gitRepoName?: string;
  gitSyncStatus?: 'synced' | 'ahead' | 'behind' | 'diverged' | 'error';
}

interface ProjectCardProps {
  project: Project;
  onOpen: () => void;
  onDelete: () => void;
  onStatusChange: (status: Status) => void;
  onAddAgent?: () => void;
  isDeleting?: boolean;
}

export function ProjectCard({
  project,
  onOpen,
  onDelete,
  onStatusChange,
  onAddAgent,
  isDeleting = false
}: ProjectCardProps) {
  const getActionIcon = () => {
    if (project.status === 'launch') {
      return (
        <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 256 256">
          <path d="M247.31,124.76c-.35-.79-8.82-19.58-27.65-38.41C194.57,61.26,162.88,48,128,48S61.43,61.26,36.34,86.35C17.51,105.18,9,124,8.69,124.76a8,8,0,0,0,0,6.5c.35.79,8.82,19.57,27.65,38.4C61.43,194.74,93.12,208,128,208s66.57-13.26,91.66-38.34c18.83-18.83,27.3-37.61,27.65-38.4A8,8,0,0,0,247.31,124.76ZM128,192c-30.78,0-57.67-11.19-79.93-33.25A133.47,133.47,0,0,1,25,128,133.33,133.33,0,0,1,48.07,97.25C70.33,75.19,97.22,64,128,64s57.67,11.19,79.93,33.25A133.46,133.46,0,0,1,231.05,128C223.84,141.46,192.43,192,128,192Zm0-112a48,48,0,1,0,48,48A48.05,48.05,0,0,0,128,80Zm0,80a32,32,0,1,1,32-32A32,32,0,0,1,128,160Z" />
        </svg>
      );
    }
    return (
      <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 256 256">
        <path d="M224.49,136.49l-72,72a12,12,0,0,1-17,0l-72-72a12,12,0,0,1,17-17L116,155V40a12,12,0,0,1,24,0V155l35.51-35.52a12,12,0,0,1,17,17ZM216,204H40a12,12,0,0,0,0,24H216a12,12,0,0,0,0-24Z" />
      </svg>
    );
  };

  const getActionLabel = () => {
    return project.status === 'launch' ? 'View' : 'Open';
  };

  const getActionColor = () => {
    return project.status === 'launch' ? 'text-green-500 hover:text-green-400' : 'text-orange-500 hover:text-orange-400';
  };

  return (
    <div
      className="
        project-card relative
        bg-[var(--surface)] rounded-2xl
        border border-white/8
        transition-all duration-300 ease-[var(--ease)]
        cursor-pointer
        hover:transform hover:-translate-y-1
        hover:shadow-[0_12px_40px_rgba(0,0,0,0.2)]
        hover:border-[rgba(255,107,0,0.3)]
      "
      onClick={isDeleting ? undefined : onOpen}
      style={{ overflow: isDeleting ? 'hidden' : 'visible' }}
    >
      {/* Deleting Overlay */}
      {isDeleting && (
        <div className="absolute inset-0 bg-black/70 backdrop-blur-sm rounded-2xl flex flex-col items-center justify-center z-10 overflow-hidden">
          <svg
            className="w-12 h-12 mb-3"
            viewBox="0 0 50 50"
            style={{
              animation: 'spin 1s linear infinite'
            }}
          >
            <circle
              cx="25"
              cy="25"
              r="20"
              fill="none"
              stroke="rgba(255, 107, 0, 0.3)"
              strokeWidth="4"
            />
            <circle
              cx="25"
              cy="25"
              r="20"
              fill="none"
              stroke="#ff6b00"
              strokeWidth="4"
              strokeDasharray="31.4 94.2"
              strokeLinecap="round"
            />
          </svg>
          <p className="text-white font-medium text-sm">Deleting project...</p>
          <p className="text-gray-400 text-xs mt-1">This may take a few seconds</p>
        </div>
      )}

      <div className={`p-6 ${isDeleting ? 'pointer-events-none opacity-50' : ''}`}>
        {/* Header */}
        <div className="flex items-start justify-between mb-4">
          <div className="flex-1">
            <div className="flex items-center gap-2 mb-2">
              <h3 className="font-heading text-xl font-bold text-white">
                {project.name}
              </h3>
              {project.hasGitRepo && (
                <div className="flex items-center gap-1 px-2 py-1 bg-green-500/20 rounded text-xs text-green-400">
                  <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 256 256">
                    <path d="M208.31,75.68A59.78,59.78,0,0,0,202.93,28,8,8,0,0,0,196,24a59.75,59.75,0,0,0-48,24H124A59.75,59.75,0,0,0,76,24a8,8,0,0,0-6.93,4,59.78,59.78,0,0,0-5.38,47.68A58.14,58.14,0,0,0,56,104v8a56.06,56.06,0,0,0,48.44,55.47A39.8,39.8,0,0,0,96,192v8H72a24,24,0,0,1-24-24A40,40,0,0,0,8,136a8,8,0,0,0,0,16,24,24,0,0,1,24,24,40,40,0,0,0,40,40H96v16a8,8,0,0,0,16,0V192a24,24,0,0,1,48,0v40a8,8,0,0,0,16,0V192a39.8,39.8,0,0,0-8.44-24.53A56.06,56.06,0,0,0,216,112v-8A58.14,58.14,0,0,0,208.31,75.68Z" />
                  </svg>
                  <span className="font-medium">
                    {project.gitSyncStatus === 'synced' ? '✓' :
                     project.gitSyncStatus === 'ahead' ? '↑' :
                     project.gitSyncStatus === 'behind' ? '↓' :
                     project.gitSyncStatus === 'diverged' ? '⚠' : '⚠'}
                  </span>
                </div>
              )}
            </div>
            <StatusBadge
              status={project.status}
              onChange={onStatusChange}
            />
          </div>
          <Dropdown
            trigger={
              <button
                className="text-gray-400 hover:text-white transition-colors p-1"
              >
                <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 256 256">
                  <path d="M156,128a28,28,0,1,1-28-28A28,28,0,0,1,156,128ZM48,100a28,28,0,1,0,28,28A28,28,0,0,0,48,100Zm160,0a28,28,0,1,0,28,28A28,28,0,0,0,208,100Z" />
                </svg>
              </button>
            }
            items={[
              {
                icon: (
                  <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 256 256">
                    <path d="M176,232a8,8,0,0,1-8,8H88a8,8,0,0,1,0-16h80A8,8,0,0,1,176,232Zm40-128a87.55,87.55,0,0,1-33.64,69.21A16.24,16.24,0,0,0,176,186v6a16,16,0,0,1-16,16H96a16,16,0,0,1-16-16v-6a16,16,0,0,0-6.23-12.66A87.59,87.59,0,0,1,40,104.49C39.74,56.83,78.26,17.14,125.88,16A88,88,0,0,1,216,104Z" />
                  </svg>
                ),
                label: 'Idea',
                onClick: () => onStatusChange('idea')
              },
              {
                icon: (
                  <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 256 256">
                    <path d="M192,104a8,8,0,0,1-8,8H72a8,8,0,0,1,0-16H184A8,8,0,0,1,192,104Zm-8,24H72a8,8,0,0,0,0,16H184a8,8,0,0,0,0-16Zm40-80V208a16,16,0,0,1-16,16H48a16,16,0,0,1-16-16V48A16,16,0,0,1,48,32H208A16,16,0,0,1,224,48ZM208,208V48H48V208H208Z" />
                  </svg>
                ),
                label: 'Build',
                onClick: () => onStatusChange('build')
              },
              {
                icon: (
                  <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 256 256">
                    <path d="M152,224a8,8,0,0,1-8,8H112a8,8,0,0,1,0-16h32A8,8,0,0,1,152,224ZM128,112a12,12,0,1,0-12-12A12,12,0,0,0,128,112Zm95.62,43.83-12.36,55.63a16,16,0,0,1-25.51,9.11L158.51,200h-61L70.25,220.57a16,16,0,0,1-25.51-9.11L32.38,155.83a15.95,15.95,0,0,1,1.93-12.78L64,96.28V48a16,16,0,0,1,16-16h96a16,16,0,0,1,16,16V96.28l29.69,46.77A15.95,15.95,0,0,1,223.62,155.83Z" />
                  </svg>
                ),
                label: 'Launch',
                onClick: () => onStatusChange('launch')
              },
              {
                icon: (
                  <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 256 256">
                    <path d="M216,48H176V40a24,24,0,0,0-24-24H104A24,24,0,0,0,80,40v8H40a8,8,0,0,0,0,16h8V208a16,16,0,0,0,16,16H192a16,16,0,0,0,16-16V64h8a8,8,0,0,0,0-16ZM96,40a8,8,0,0,1,8-8h48a8,8,0,0,1,8,8v8H96Zm96,168H64V64H192ZM112,104v64a8,8,0,0,1-16,0V104a8,8,0,0,1,16,0Zm48,0v64a8,8,0,0,1-16,0V104a8,8,0,0,1,16,0Z" />
                  </svg>
                ),
                label: 'Delete',
                onClick: onDelete,
                variant: 'danger',
                separator: true
              }
            ]}
          />
        </div>

        {/* Description */}
        <p className="text-gray-400 text-sm mb-3">
          {project.description}
        </p>

        {/* Agents */}
        {project.agents.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-4">
            {project.agents.map((agent, idx) => (
              <AgentTag
                key={idx}
                icon={agent.icon}
                name={agent.name}
              />
            ))}
            {onAddAgent && (
              <AgentTag
                icon={
                  <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 256 256">
                    <path d="M224,128a8,8,0,0,1-8,8H136v80a8,8,0,0,1-16,0V136H40a8,8,0,0,1,0-16h80V40a8,8,0,0,1,16,0v80h80A8,8,0,0,1,224,128Z" />
                  </svg>
                }
                name="Add"
                onClick={(e) => {
                  e?.stopPropagation();
                  onAddAgent();
                }}
              />
            )}
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between mt-auto">
          <span className="text-xs text-gray-500">
            {project.isLive ? `Live • ${project.userCount} users` : `Updated ${project.lastUpdated}`}
          </span>
          <button
            className={`text-sm font-medium transition-colors flex items-center gap-1 ${getActionColor()}`}
            onClick={(e) => {
              e.stopPropagation();
              onOpen();
            }}
          >
            <span>{getActionLabel()}</span>
            {getActionIcon()}
          </button>
        </div>
      </div>
    </div>
  );
}
