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
          <div className="p-2 bg-[var(--surface-hover)] rounded-[var(--radius-medium)] border border-[var(--border)]">
            <GitBranch size={18} className="text-[var(--primary)]" />
          </div>
          <div>
            <h2 className="text-xs font-semibold text-[var(--text)]">Architecture</h2>
            <p className="text-[11px] text-[var(--text-muted)]">
              Visual canvas of your project services
            </p>
          </div>
        </div>

        {/* Canvas Link */}
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center">
            <div className="w-16 h-16 bg-[var(--surface-hover)] border border-[var(--border)] rounded-[var(--radius)] flex items-center justify-center mx-auto mb-4">
              <GitBranch size={28} className="text-[var(--primary)]" />
            </div>
            <h3 className="text-sm font-semibold text-[var(--text)] mb-1.5">
              Architecture Canvas
            </h3>
            <p className="text-[11px] text-[var(--text-muted)] mb-5 max-w-xs leading-relaxed">
              View and edit your project's service architecture, connections, and infrastructure on the visual canvas.
            </p>
            <button
              onClick={() => navigate(`/project/${projectSlug}`)}
              className="btn btn-filled"
            >
              <ArrowSquareOut size={15} />
              Open Canvas
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
