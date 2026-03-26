import { type ReactNode } from 'react';
import type { Status } from './StatusBadge';
import { AgentTag } from './AgentTag';
import { type ComputeTier } from '../../types/project';
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
  compute_tier?: string;
  environment_status?: string;
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
  onManageAccess?: () => void;
  visibility?: 'team' | 'private';
  isAdmin?: boolean;
}

export function ProjectCard({
  project,
  onOpen,
  onDelete,
  onFork,
  onHibernate: _onHibernate,
  onStatusChange: _onStatusChange,
  onAddAgent,
  isDeleting = false,
  isSelected = false,
  onSelectionToggle,
  onManageAccess,
  visibility = 'team',
  isAdmin = false,
}: ProjectCardProps) {
  return (
    <div
      className={`
        project-card relative group
        bg-[var(--surface-hover)] rounded-[var(--radius)]
        transition-all duration-300 ease-[var(--ease)]
        hover:transform hover:-translate-y-0.5
      `}
      style={{
        overflow: isDeleting ? 'hidden' : 'visible',
        border: `var(--border-width) solid ${isSelected ? 'var(--primary)' : 'var(--border)'}`,
      }}
      onMouseEnter={(e) => {
        if (!isSelected) e.currentTarget.style.borderColor = 'var(--border-hover)';
      }}
      onMouseLeave={(e) => {
        if (!isSelected) e.currentTarget.style.borderColor = 'var(--border)';
      }}
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
        <div className="absolute inset-0 bg-black/70 backdrop-blur-sm rounded-[var(--radius)] flex flex-col items-center justify-center z-10 overflow-hidden">
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
          <p className="text-white font-medium text-xs">Deleting project...</p>
          <p className="text-[var(--text-muted)] text-xs mt-1">This may take a few seconds</p>
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
                className="font-heading text-sm font-semibold text-[var(--text)] truncate cursor-pointer hover:text-[var(--primary)] transition-colors"
                onClick={onOpen}
              >
                {project.name}
              </h3>
              {/* Environment Status Badge */}
              {project.environment_status === 'provisioning' ? (
                <EnvironmentStatusBadge status="provisioning" size="sm" />
              ) : project.environment_status === 'setup_failed' ? (
                <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-red-500/10 text-red-400 border border-red-500/20">
                  Setup failed
                </span>
              ) : (
                (() => {
                  const status = getEnvironmentStatus(
                    (project.compute_tier ?? 'none') as ComputeTier
                  );
                  if (!status) return null;
                  return <EnvironmentStatusBadge status={status} size="sm" />;
                })()
              )}
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
              {/* Visibility / Access */}
              {isAdmin && onManageAccess && (
                <button
                  onClick={(e) => { e.stopPropagation(); onManageAccess(); }}
                  className="flex items-center gap-1 px-1.5 py-0.5 rounded-[var(--radius-small)] hover:bg-[var(--surface)] transition-colors text-[var(--text-subtle)] hover:text-[var(--text)] flex-shrink-0"
                  title="Manage project access"
                >
                  {visibility === 'private' ? (
                    <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 256 256"><path d="M53.92,34.62A8,8,0,1,0,42.08,45.38L61.32,66.55C25,88.84,9.38,123.2,8.69,124.76a8,8,0,0,0,0,6.5c.35.79,8.82,19.57,27.65,38.4C61.43,194.74,93.12,208,128,208a127.11,127.11,0,0,0,52.07-10.83l22,24.21a8,8,0,1,0,11.84-10.76Zm47.33,75.8,41.67,45.85a32,32,0,0,1-41.67-45.85ZM128,192c-30.78,0-57.67-11.19-79.93-33.29A133.47,133.47,0,0,1,25,128c4.69-8.79,19.66-33.39,47.35-49.38l18,19.75a48,48,0,0,0,63.66,70l14.73,16.2A112,112,0,0,1,128,192Zm6-95.43a8,8,0,0,1,3-15.72,48.16,48.16,0,0,1,38.77,42.64,8,8,0,0,1-7.22,8.71,6.39,6.39,0,0,1-.75,0,8,8,0,0,1-8-7.26A32.09,32.09,0,0,0,134,96.57Zm113.28,34.69c-.42.94-10.55,23.37-33.36,43.8a8,8,0,1,1-10.67-11.92A132.77,132.77,0,0,0,231.05,128a133.15,133.15,0,0,0-23.12-30.77C185.67,75.19,158.78,64,128,64a118.37,118.37,0,0,0-19.36,1.57A8,8,0,1,1,106,49.79,134,134,0,0,1,128,48c34.88,0,66.57,13.26,91.66,38.35,18.83,18.83,27.3,37.62,27.65,38.41A8,8,0,0,1,247.31,131.26Z"/></svg>
                  ) : (
                    <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 256 256"><path d="M247.31,124.76c-.35-.79-8.82-19.58-27.65-38.41C194.57,61.26,162.88,48,128,48S61.43,61.26,36.34,86.35C17.51,105.18,9,123.97,8.69,124.76a8,8,0,0,0,0,6.5c.35.79,8.82,19.57,27.65,38.4C61.43,194.74,93.12,208,128,208s66.57-13.26,91.66-38.34c18.83-18.83,27.3-37.61,27.65-38.4A8,8,0,0,0,247.31,124.76ZM128,192c-30.78,0-57.67-11.19-79.93-33.29A133.47,133.47,0,0,1,25,128,133.33,133.33,0,0,1,48.07,97.29C70.33,75.19,97.22,64,128,64s57.67,11.19,79.93,33.29A133.46,133.46,0,0,1,231.05,128C223.84,141.46,192.43,192,128,192Zm0-112a48,48,0,1,0,48,48A48.05,48.05,0,0,0,128,80Zm0,80a32,32,0,1,1,32-32A32,32,0,0,1,128,160Z"/></svg>
                  )}
                </button>
              )}
            </div>
          </div>
        </div>

        {/* Description */}
        <p className="text-[var(--text-muted)] text-xs mb-3 line-clamp-2 leading-relaxed">
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
        <div className="text-xs text-[var(--text-subtle)] mb-3">
          {project.isLive ? `Live • ${project.userCount} users` : `Updated ${project.lastUpdated}`}
        </div>

        {/* Action Buttons — pill buttons, hug text */}
        <div className="flex gap-1 flex-wrap">
          {project.environment_status === 'setup_failed' ? (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onDelete();
              }}
              className="btn btn-danger"
              title="Delete failed project"
            >
              <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 256 256">
                <path d="M216,48H176V40a24,24,0,0,0-24-24H104A24,24,0,0,0,80,40v8H40a8,8,0,0,0,0,16h8V208a16,16,0,0,0,16,16H192a16,16,0,0,0,16-16V64h8a8,8,0,0,0,0-16ZM96,40a8,8,0,0,1,8-8h48a8,8,0,0,1,8,8v8H96Zm96,168H64V64H192ZM112,104v64a8,8,0,0,1-16,0V104a8,8,0,0,1,16,0Zm48,0v64a8,8,0,0,1-16,0V104a8,8,0,0,1,16,0Z" />
              </svg>
              Delete
            </button>
          ) : (
            <>
              <button onClick={onOpen} className="btn btn-primary">
                <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 256 256">
                  <path d="M224.49,136.49l-72,72a12,12,0,0,1-17,0l-72-72a12,12,0,0,1,17-17L116,155V40a12,12,0,0,1,24,0V155l35.51-35.52a12,12,0,0,1,17,17ZM216,204H40a12,12,0,0,0,0,24H216a12,12,0,0,0,0-24Z" />
                </svg>
                Open
              </button>

              {onFork && (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onFork();
                  }}
                  className="btn"
                >
                  <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 256 256">
                    <path d="M224,64a32,32,0,1,0-40,31v17a8,8,0,0,1-8,8H80a8,8,0,0,1-8-8V95a32,32,0,1,0-16,0v17a24,24,0,0,0,24,24h40v25a32,32,0,1,0,16,0V136h40a24,24,0,0,0,24-24V95A32.06,32.06,0,0,0,224,64ZM48,64A16,16,0,1,1,64,80,16,16,0,0,1,48,64ZM144,192a16,16,0,1,1-16-16A16,16,0,0,1,144,192ZM192,80a16,16,0,1,1,16-16A16,16,0,0,1,192,80Z" />
                  </svg>
                  Fork
                </button>
              )}

              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete();
                }}
                className="btn btn-danger"
                title="Delete project"
              >
                <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 256 256">
                  <path d="M216,48H176V40a24,24,0,0,0-24-24H104A24,24,0,0,0,80,40v8H40a8,8,0,0,0,0,16h8V208a16,16,0,0,0,16,16H192a16,16,0,0,0,16-16V64h8a8,8,0,0,0,0-16ZM96,40a8,8,0,0,1,8-8h48a8,8,0,0,1,8,8v8H96Zm96,168H64V64H192ZM112,104v64a8,8,0,0,1-16,0V104a8,8,0,0,1,16,0Zm48,0v64a8,8,0,0,1-16,0V104a8,8,0,0,1,16,0Z" />
                </svg>
                Delete
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
