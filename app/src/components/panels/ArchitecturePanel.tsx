import { useNavigate } from 'react-router-dom';
import { GitBranch, ArrowSquareOut } from '@phosphor-icons/react';

interface ArchitecturePanelProps {
  projectSlug: string;
}

export function ArchitecturePanel({ projectSlug }: ArchitecturePanelProps) {
  const navigate = useNavigate();

  return (
    <div className="h-full flex flex-col">
      <div className="panel-section p-6 flex-1 flex flex-col">
        {/* Header */}
        <div className="flex items-center gap-3 mb-6">
          <div className="p-2 bg-orange-500/20 rounded-lg">
            <GitBranch size={20} className="text-orange-400" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-[var(--text)]">Architecture</h2>
            <p className="text-xs text-[var(--text)]/60">
              Visual canvas of your project services
            </p>
          </div>
        </div>

        {/* Canvas Link */}
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center">
            <div className="w-20 h-20 bg-[rgba(var(--primary-rgb),0.1)] rounded-2xl flex items-center justify-center mx-auto mb-4">
              <GitBranch size={36} className="text-[var(--primary)]" />
            </div>
            <h3 className="text-lg font-bold text-[var(--text)] mb-2">
              Architecture Canvas
            </h3>
            <p className="text-sm text-[var(--text)]/50 mb-6 max-w-xs">
              View and edit your project's service architecture, connections, and infrastructure on the visual canvas.
            </p>
            <button
              onClick={() => navigate(`/project/${projectSlug}`)}
              className="px-6 py-3 bg-[var(--primary)] text-white rounded-xl font-medium hover:opacity-90 transition-opacity flex items-center gap-2 mx-auto"
            >
              <ArrowSquareOut size={18} />
              Open Canvas
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
