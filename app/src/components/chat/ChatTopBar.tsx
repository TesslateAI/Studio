import { PanelLeft, SquarePen } from 'lucide-react';
import { ProjectConnector } from './ProjectConnector';

interface ChatTopBarProps {
  isSidebarOpen: boolean;
  onToggleSidebar: () => void;
  sessionTitle: string;
  onNewSession: () => void;
  connectedProjectId: string | null;
  connectedProjectName: string | null;
  onConnectProject: (projectId: string, projectName: string) => void;
  onDisconnectProject: () => void;
  onRequestNewWorkspace: () => void;
}

export function ChatTopBar({
  isSidebarOpen,
  onToggleSidebar,
  sessionTitle,
  onNewSession,
  connectedProjectId,
  connectedProjectName,
  onConnectProject,
  onDisconnectProject,
  onRequestNewWorkspace,
}: ChatTopBarProps) {
  return (
    <div
      className="flex items-center gap-1 h-10 border-b border-[var(--border)] flex-shrink-0"
      style={{ paddingLeft: 7, paddingRight: 10 }}
    >
      {/* When the sidebar is closed, the toggle + new buttons live here in
          the same slot the sidebar header would occupy — same icons, same
          gap, same padding — so toggling doesn't shift anything visually. */}
      {!isSidebarOpen && (
        <>
          <button
            onClick={onToggleSidebar}
            className="flex items-center justify-center w-7 h-7 rounded-[var(--radius-small)] text-[var(--text-subtle)] hover:text-[var(--text)] hover:bg-[var(--surface-hover)] transition-colors"
            aria-label="Open session sidebar"
          >
            <PanelLeft size={14} />
          </button>
          <button
            onClick={onNewSession}
            className="flex items-center justify-center w-7 h-7 rounded-[var(--radius-small)] text-[var(--text-subtle)] hover:text-[var(--text)] hover:bg-[var(--surface-hover)] transition-colors"
            aria-label="New session"
          >
            <SquarePen size={14} />
          </button>
        </>
      )}
      <span className="text-xs font-medium text-[var(--text)] truncate max-w-[120px] sm:max-w-[200px] ml-1">
        {sessionTitle}
      </span>
      <div className="ml-auto">
        <ProjectConnector
          projectId={connectedProjectId}
          projectName={connectedProjectName}
          onConnect={onConnectProject}
          onDisconnect={onDisconnectProject}
          onRequestNewWorkspace={onRequestNewWorkspace}
        />
      </div>
    </div>
  );
}
