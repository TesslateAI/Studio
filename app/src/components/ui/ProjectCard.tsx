import { type ReactNode } from 'react';
import type { Status } from './StatusBadge';
import { AgentTag } from './AgentTag';
import { Dropdown } from './Dropdown';
import { type VolumeState, type ComputeTier } from '../../types/project';
import { getEnvironmentStatus } from './environmentStatus';
import { EnvironmentStatusBadge } from './EnvironmentStatusBadge';

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
  slug?: string;
  volume_state?: string;
  compute_tier?: string;
}

interface ProjectCardProps {
  project: Project;
  onOpen: () => void;
  onDelete: () => void;
  onFork?: () => void;
  onHibernate?: () => void;
  onStatusChange: (status: Status) => void;
  onAddAgent?: () => void;
  isDeleting?: boolean;
  isSelected?: boolean;
  onSelectionToggle?: () => void;
}

export function ProjectCard({
  project,
  onOpen,
  onDelete,
  onFork,
  onHibernate,
  onStatusChange: _onStatusChange,
  onAddAgent,
  isDeleting = false,
  isSelected = false,
  onSelectionToggle,
}: ProjectCardProps) {
  return (
    <div
      className={`
        project-card relative group
        bg-[var(--surface)] rounded-2xl
        border transition-all duration-300 ease-[var(--ease)]
        hover:transform hover:-translate-y-1
        hover:shadow-[0_12px_40px_rgba(0,0,0,0.2)]
        ${isSelected ? 'border-[var(--primary)]' : 'border-white/8 hover:border-[rgba(var(--primary-rgb),0.3)]'}
      `}
      style={{ overflow: isDeleting ? 'hidden' : 'visible' }}
    >
      {/* Selection Checkbox */}
      {onSelectionToggle && (
        <button
          role="checkbox"
          aria-checked={isSelected}
          aria-label={`Select ${project.name}`}
          onClick={(e) => {
            e.stopPropagation();
            onSelectionToggle();
          }}
          disabled={isDeleting}
          className={`
            absolute top-3 right-3 z-20
            w-6 h-6 rounded-md border-2 flex items-center justify-center
            transition-all duration-200
            ${isDeleting ? 'pointer-events-none opacity-0' : ''}
            ${
              isSelected
                ? 'bg-[var(--primary)] border-[var(--primary)] opacity-100'
                : 'border-white/30 bg-black/30 backdrop-blur-sm opacity-0 md:opacity-0 md:group-hover:opacity-100 max-md:opacity-100 hover:border-white/60'
            }
          `}
        >
          {isSelected && (
            <svg
              className="w-3.5 h-3.5 text-white"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={3}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
            </svg>
          )}
        </button>
      )}

      {/* Deleting Overlay */}
      {isDeleting && (
        <div className="absolute inset-0 bg-black/70 backdrop-blur-sm rounded-2xl flex flex-col items-center justify-center z-10 overflow-hidden">
          <svg
            className="w-12 h-12 mb-3"
            viewBox="0 0 50 50"
            style={{
              animation: 'spin 1s linear infinite',
            }}
          >
            <circle
              cx="25"
              cy="25"
              r="20"
              fill="none"
              stroke="rgba(var(--primary-rgb), 0.3)"
              strokeWidth="4"
            />
            <circle
              cx="25"
              cy="25"
              r="20"
              fill="none"
              stroke="var(--primary)"
              strokeWidth="4"
              strokeDasharray="31.4 94.2"
              strokeLinecap="round"
            />
          </svg>
          <p className="text-white font-medium text-sm">Deleting project...</p>
          <p className="text-gray-400 text-xs mt-1">This may take a few seconds</p>
        </div>
      )}

      <div
        className={`p-4 sm:p-6 flex flex-col h-full ${isDeleting ? 'pointer-events-none opacity-50' : ''}`}
      >
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
              {/* Environment Status Badge */}
              {(() => {
                const status = getEnvironmentStatus(
                  (project.volume_state ?? 'local') as VolumeState,
                  (project.compute_tier ?? 'none') as ComputeTier
                );
                if (!status) return null;
                return <EnvironmentStatusBadge status={status} size="sm" />;
              })()}
              {project.hasGitRepo && (
                <div className="flex items-center gap-1 px-2 py-0.5 bg-[rgba(var(--status-green-rgb),0.1)] border border-[rgba(var(--status-green-rgb),0.2)] rounded text-xs text-[var(--status-green)] flex-shrink-0">
                  <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 256 256">
                    <path d="M208.31,75.68A59.78,59.78,0,0,0,202.93,28,8,8,0,0,0,196,24a59.75,59.75,0,0,0-48,24H124A59.75,59.75,0,0,0,76,24a8,8,0,0,0-6.93,4,59.78,59.78,0,0,0-5.38,47.68A58.14,58.14,0,0,0,56,104v8a56.06,56.06,0,0,0,48.44,55.47A39.8,39.8,0,0,0,96,192v8H72a24,24,0,0,1-24-24A40,40,0,0,0,8,136a8,8,0,0,0,0,16,24,24,0,0,1,24,24,40,40,0,0,0,40,40H96v16a8,8,0,0,0,16,0V192a24,24,0,0,1,48,0v40a8,8,0,0,0,16,0V192a39.8,39.8,0,0,0-8.44-24.53A56.06,56.06,0,0,0,216,112v-8A58.14,58.14,0,0,0,208.31,75.68Z" />
                  </svg>
                  <span className="font-medium text-[10px]">
                    {project.gitSyncStatus === 'synced'
                      ? '✓'
                      : project.gitSyncStatus === 'ahead'
                        ? '↑'
                        : project.gitSyncStatus === 'behind'
                          ? '↓'
                          : project.gitSyncStatus === 'diverged'
                            ? '⚠'
                            : '⚠'}
                  </span>
                </div>
              )}
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
              <AgentTag key={idx} icon={agent.icon} name={agent.name} />
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
        <div className="flex gap-2">
          <button
            onClick={onOpen}
            className="
              flex-1 min-w-0 bg-[var(--primary)] hover:bg-[var(--primary-hover)]
              text-white font-semibold py-2.5 px-4 rounded-xl
              transition-all duration-200
              flex items-center justify-center gap-2
              shadow-lg shadow-[rgba(var(--primary-rgb),0.2)]
              hover:shadow-xl hover:shadow-[rgba(var(--primary-rgb),0.3)]
              hover:scale-[1.02]
              text-sm
            "
          >
            <svg className="w-4 h-4 flex-shrink-0" fill="currentColor" viewBox="0 0 256 256">
              <path d="M224.49,136.49l-72,72a12,12,0,0,1-17,0l-72-72a12,12,0,0,1,17-17L116,155V40a12,12,0,0,1,24,0V155l35.51-35.52a12,12,0,0,1,17,17ZM216,204H40a12,12,0,0,0,0,24H216a12,12,0,0,0,0-24Z" />
            </svg>
            <span className="hidden sm:inline truncate">Open</span>
          </button>

          <Dropdown
            trigger={
              <button
                className="
                  flex-shrink-0 bg-white/5 hover:bg-white/10
                  text-[var(--text-secondary,#9ca3af)] hover:text-[var(--text)]
                  font-semibold py-2.5 px-3 rounded-xl
                  border border-white/10 hover:border-white/20
                  transition-all duration-200
                  flex items-center justify-center
                  hover:scale-[1.02]
                "
                title="More actions"
              >
                <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 256 256">
                  <path d="M128,96a32,32,0,1,0,32,32A32,32,0,0,0,128,96Zm0,40a8,8,0,1,1,8-8A8,8,0,0,1,128,136Zm0-72a32,32,0,1,0-32-32A32,32,0,0,0,128,64Zm0-40a8,8,0,1,1-8,8A8,8,0,0,1,128,24Zm0,168a32,32,0,1,0,32,32A32,32,0,0,0,128,192Zm0,40a8,8,0,1,1,8-8A8,8,0,0,1,128,232Z" />
                </svg>
              </button>
            }
            items={[
              ...(onFork
                ? [
                    {
                      icon: (
                        <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 256 256">
                          <path d="M224,64a32,32,0,1,0-40,31v17a8,8,0,0,1-8,8H80a8,8,0,0,1-8-8V95a32,32,0,1,0-16,0v17a24,24,0,0,0,24,24h40v25a32,32,0,1,0,16,0V136h40a24,24,0,0,0,24-24V95A32.06,32.06,0,0,0,224,64ZM48,64A16,16,0,1,1,64,80,16,16,0,0,1,48,64ZM144,192a16,16,0,1,1-16-16A16,16,0,0,1,144,192ZM192,80a16,16,0,1,1,16-16A16,16,0,0,1,192,80Z" />
                        </svg>
                      ),
                      label: 'Fork',
                      onClick: onFork,
                    },
                  ]
                : []),
              ...(onHibernate
                ? [
                    {
                      icon: (
                        <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 256 256">
                          <path d="M240,96a8,8,0,0,1-8,8H216v16a8,8,0,0,1-16,0V104H184a8,8,0,0,1,0-16h16V72a8,8,0,0,1,16,0V88h16A8,8,0,0,1,240,96ZM144,56h8v8a8,8,0,0,0,16,0V56h8a8,8,0,0,0,0-16h-8V32a8,8,0,0,0-16,0v8h-8a8,8,0,0,0,0,16Zm-2.16,135.81A88,88,0,0,1,64.19,114.16a8,8,0,0,0-2.08-11.36,8.15,8.15,0,0,0-3.92-1.25A8,8,0,0,0,51.34,104,104.07,104.07,0,0,0,152,204.66a8,8,0,0,0,1.21-15.67A8.15,8.15,0,0,0,141.84,191.81Z" />
                        </svg>
                      ),
                      label: 'Hibernate',
                      onClick: onHibernate,
                    },
                  ]
                : []),
              {
                icon: (
                  <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 256 256">
                    <path d="M216,48H176V40a24,24,0,0,0-24-24H104A24,24,0,0,0,80,40v8H40a8,8,0,0,0,0,16h8V208a16,16,0,0,0,16,16H192a16,16,0,0,0,16-16V64h8a8,8,0,0,0,0-16ZM96,40a8,8,0,0,1,8-8h48a8,8,0,0,1,8,8v8H96Zm96,168H64V64H192ZM112,104v64a8,8,0,0,1-16,0V104a8,8,0,0,1,16,0Zm48,0v64a8,8,0,0,1-16,0V104a8,8,0,0,1,16,0Z" />
                  </svg>
                ),
                label: 'Delete',
                onClick: onDelete,
                variant: 'danger' as const,
                separator: true,
              },
            ]}
            position="bottom-right"
          />
        </div>
      </div>
    </div>
  );
}
