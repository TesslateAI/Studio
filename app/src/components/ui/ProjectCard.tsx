import { type ReactNode } from 'react';
import type { Status } from './StatusBadge';
import { AgentTag } from './AgentTag';

interface Project {
  id: string;
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
  onFork?: () => void;
  onStatusChange: (status: Status) => void;
  onAddAgent?: () => void;
  isDeleting?: boolean;
}

export function ProjectCard({
  project,
  onOpen,
  onDelete,
  onFork,
  onStatusChange,
  onAddAgent,
  isDeleting = false
}: ProjectCardProps) {
  // Status badge configuration (read-only, no dropdown)
  const statusConfig = {
    idea: {
      label: 'Idea',
      className: 'bg-purple-500/10 text-purple-400 border border-purple-500/20'
    },
    build: {
      label: 'Build',
      className: 'bg-orange-500/10 text-orange-400 border border-orange-500/20'
    },
    launch: {
      label: 'Launch',
      className: 'bg-green-500/10 text-green-400 border border-green-500/20'
    }
  };

  return (
    <div
      className="
        project-card relative group
        bg-[var(--surface)] rounded-2xl
        border border-white/8
        transition-all duration-300 ease-[var(--ease)]
        hover:transform hover:-translate-y-1
        hover:shadow-[0_12px_40px_rgba(0,0,0,0.2)]
        hover:border-[rgba(255,107,0,0.3)]
      "
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

      <div className={`p-4 sm:p-6 flex flex-col h-full ${isDeleting ? 'pointer-events-none opacity-50' : ''}`}>
        {/* Header with Status Badge */}
        <div className="flex items-start justify-between mb-3 sm:mb-4">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-2">
              <h3
                className="font-heading text-lg sm:text-xl font-bold text-[var(--text)] truncate cursor-pointer hover:text-[var(--primary)] transition-colors"
                onClick={onOpen}
              >
                {project.name}
              </h3>
              {project.hasGitRepo && (
                <div className="flex items-center gap-1 px-2 py-0.5 bg-green-500/10 border border-green-500/20 rounded text-xs text-green-400 flex-shrink-0">
                  <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 256 256">
                    <path d="M208.31,75.68A59.78,59.78,0,0,0,202.93,28,8,8,0,0,0,196,24a59.75,59.75,0,0,0-48,24H124A59.75,59.75,0,0,0,76,24a8,8,0,0,0-6.93,4,59.78,59.78,0,0,0-5.38,47.68A58.14,58.14,0,0,0,56,104v8a56.06,56.06,0,0,0,48.44,55.47A39.8,39.8,0,0,0,96,192v8H72a24,24,0,0,1-24-24A40,40,0,0,0,8,136a8,8,0,0,0,0,16,24,24,0,0,1,24,24,40,40,0,0,0,40,40H96v16a8,8,0,0,0,16,0V192a24,24,0,0,1,48,0v40a8,8,0,0,0,16,0V192a39.8,39.8,0,0,0-8.44-24.53A56.06,56.06,0,0,0,216,112v-8A58.14,58.14,0,0,0,208.31,75.68Z" />
                  </svg>
                  <span className="font-medium text-[10px]">
                    {project.gitSyncStatus === 'synced' ? '✓' :
                     project.gitSyncStatus === 'ahead' ? '↑' :
                     project.gitSyncStatus === 'behind' ? '↓' :
                     project.gitSyncStatus === 'diverged' ? '⚠' : '⚠'}
                  </span>
                </div>
              )}
            </div>

            {/* Read-only status badge */}
            <div className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold uppercase tracking-wide ${statusConfig[project.status].className}`}>
              {statusConfig[project.status].label}
            </div>
          </div>
        </div>

        {/* Description */}
        <p className="text-gray-400 text-xs sm:text-sm mb-3 sm:mb-4 line-clamp-2 leading-relaxed">
          {project.description}
        </p>

        {/* Agents */}
        {project.agents.length > 0 && (
          <div className="flex flex-wrap gap-1.5 sm:gap-2 mb-3 sm:mb-4">
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

        {/* Spacer */}
        <div className="flex-1"></div>

        {/* Updated timestamp */}
        <div className="text-xs text-gray-500 mb-3">
          {project.isLive ? `Live • ${project.userCount} users` : `Updated ${project.lastUpdated}`}
        </div>

        {/* Action Buttons */}
        <div className="flex gap-1.5 sm:gap-2">
          <button
            onClick={onOpen}
            className="
              flex-1 bg-[var(--primary)] hover:bg-orange-600
              text-white font-semibold py-2 sm:py-2.5 px-3 sm:px-4 rounded-lg sm:rounded-xl
              transition-all duration-200
              flex items-center justify-center gap-1.5 sm:gap-2
              shadow-lg shadow-orange-500/20
              hover:shadow-xl hover:shadow-orange-500/30
              hover:scale-[1.02]
              text-sm sm:text-base
            "
          >
            <svg className="w-3.5 h-3.5 sm:w-4 sm:h-4" fill="currentColor" viewBox="0 0 256 256">
              <path d="M224.49,136.49l-72,72a12,12,0,0,1-17,0l-72-72a12,12,0,0,1,17-17L116,155V40a12,12,0,0,1,24,0V155l35.51-35.52a12,12,0,0,1,17,17ZM216,204H40a12,12,0,0,0,0,24H216a12,12,0,0,0,0-24Z" />
            </svg>
            <span className="hidden xs:inline sm:inline">Open</span>
          </button>

          {onFork && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onFork();
              }}
              className="
                flex-1 bg-white/5 hover:bg-white/10
                text-[var(--text)] font-semibold py-2 sm:py-2.5 px-3 sm:px-4 rounded-lg sm:rounded-xl
                border border-white/10 hover:border-white/20
                transition-all duration-200
                flex items-center justify-center gap-1.5 sm:gap-2
                hover:scale-[1.02]
                text-sm sm:text-base
              "
            >
              <svg className="w-3.5 h-3.5 sm:w-4 sm:h-4" fill="currentColor" viewBox="0 0 256 256">
                <path d="M224,64a32,32,0,1,0-40,31v17a8,8,0,0,1-8,8H80a8,8,0,0,1-8-8V95a32,32,0,1,0-16,0v17a24,24,0,0,0,24,24h40v25a32,32,0,1,0,16,0V136h40a24,24,0,0,0,24-24V95A32.06,32.06,0,0,0,224,64ZM48,64A16,16,0,1,1,64,80,16,16,0,0,1,48,64ZM144,192a16,16,0,1,1-16-16A16,16,0,0,1,144,192ZM192,80a16,16,0,1,1,16-16A16,16,0,0,1,192,80Z" />
              </svg>
              <span className="hidden xs:inline sm:inline">Fork</span>
            </button>
          )}

          <button
            onClick={(e) => {
              e.stopPropagation();
              onDelete();
            }}
            className="
              bg-white/5 hover:bg-red-500/10
              text-gray-400 hover:text-red-400
              font-semibold py-2 sm:py-2.5 px-3 sm:px-4 rounded-lg sm:rounded-xl
              border border-white/10 hover:border-red-500/30
              transition-all duration-200
              flex items-center justify-center
              hover:scale-[1.02]
            "
            title="Delete project"
          >
            <svg className="w-3.5 h-3.5 sm:w-4 sm:h-4" fill="currentColor" viewBox="0 0 256 256">
              <path d="M216,48H176V40a24,24,0,0,0-24-24H104A24,24,0,0,0,80,40v8H40a8,8,0,0,0,0,16h8V208a16,16,0,0,0,16,16H192a16,16,0,0,0,16-16V64h8a8,8,0,0,0,0-16ZM96,40a8,8,0,0,1,8-8h48a8,8,0,0,1,8,8v8H96Zm96,168H64V64H192ZM112,104v64a8,8,0,0,1-16,0V104a8,8,0,0,1,16,0Zm48,0v64a8,8,0,0,1-16,0V104a8,8,0,0,1,16,0Z" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}
