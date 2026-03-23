import { Link } from 'react-router-dom';
import { PanelLeft, House } from 'lucide-react';
import { ProjectConnector } from './ProjectConnector';

interface ChatTopBarProps {
  isSidebarOpen: boolean;
  onToggleSidebar: () => void;
  sessionTitle: string;
  projectId: string | null;
  projectName: string | null;
  onConnectProject: (projectId: string, projectName: string) => void;
  onDisconnectProject: () => void;
}

export function ChatTopBar({
  isSidebarOpen,
  onToggleSidebar,
  sessionTitle,
  projectId,
  projectName,
  onConnectProject,
  onDisconnectProject,
}: ChatTopBarProps) {
  return (
    <div
      className="flex items-center h-10 border-b border-[var(--border)] flex-shrink-0"
      style={{ paddingLeft: 7, paddingRight: 10 }}
    >
      {/* Left: sidebar toggle + title */}
      <div className="flex items-center gap-2 min-w-0">
        <Link
          to="/dashboard"
          className="flex items-center justify-center w-7 h-7 rounded-[var(--radius-small)] text-[var(--text-subtle)] hover:text-[var(--text)] hover:bg-[var(--surface-hover)] transition-colors"
          aria-label="Back to Dashboard"
        >
          <House size={14} />
        </Link>
        {!isSidebarOpen && (
          <button
            onClick={onToggleSidebar}
            className="flex items-center justify-center w-7 h-7 rounded-[var(--radius-small)] text-[var(--text-subtle)] hover:text-[var(--text)] hover:bg-[var(--surface-hover)] transition-colors"
            aria-label="Open session sidebar"
          >
            <PanelLeft size={14} />
          </button>
        )}
        <span className="text-xs font-medium text-[var(--text)] truncate max-w-[120px] sm:max-w-[200px]">
          {sessionTitle}
        </span>
      </div>

      {/* Right: Project connector */}
      <div className="flex-1 flex items-center justify-end">
        <ProjectConnector
          projectId={projectId}
          projectName={projectName}
          onConnect={onConnectProject}
          onDisconnect={onDisconnectProject}
        />
      </div>
    </div>
  );
}
