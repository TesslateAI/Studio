import { useState, useRef, useEffect } from 'react';
import { Plus, X, Search, Circle } from 'lucide-react';
import { projectsApi } from '../../lib/api';

interface Project {
  id: string;
  name: string;
  slug: string;
  status?: string;
}

interface ProjectConnectorProps {
  projectId: string | null;
  projectName: string | null;
  onConnect: (projectId: string, projectName: string) => void;
  onDisconnect: () => void;
}

export function ProjectConnector({
  projectId,
  projectName,
  onConnect,
  onDisconnect,
}: ProjectConnectorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [search, setSearch] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  // Close on click outside
  useEffect(() => {
    if (!isOpen) return;
    const handleClick = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [isOpen]);

  // Focus search on open
  useEffect(() => {
    if (isOpen && searchInputRef.current) {
      searchInputRef.current.focus();
    }
  }, [isOpen]);

  // Fetch projects on open
  useEffect(() => {
    if (!isOpen) return;
    setIsLoading(true);
    projectsApi.getAll()
      .then((data) => {
        setProjects(Array.isArray(data) ? data : data.projects || []);
      })
      .catch(() => {})
      .finally(() => setIsLoading(false));
  }, [isOpen]);

  const filtered = projects.filter((p) =>
    p.name.toLowerCase().includes(search.toLowerCase()) ||
    p.slug.toLowerCase().includes(search.toLowerCase())
  );

  if (projectId && projectName) {
    return (
      <div className="flex items-center gap-1.5 h-7 px-2.5 rounded-full bg-[var(--surface)] border border-[var(--border)] text-[11px]">
        <Circle size={6} fill="var(--status-success)" className="text-[var(--status-success)]" />
        <span className="text-[var(--text)] font-medium truncate max-w-[120px]">{projectName}</span>
        <button
          onClick={onDisconnect}
          className="p-0.5 rounded-full text-[var(--text-subtle)] hover:text-[var(--text)] hover:bg-[var(--surface-hover)] transition-colors"
          aria-label="Disconnect project"
        >
          <X size={10} />
        </button>
      </div>
    );
  }

  return (
    <div ref={dropdownRef} className="relative">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-1.5 h-7 px-2.5 rounded-full bg-[var(--surface)] border border-[var(--border)] text-[11px] text-[var(--text-muted)] hover:text-[var(--text)] hover:border-[var(--border-hover)] transition-colors"
      >
        <Plus size={12} />
        <span>Connect a project</span>
      </button>

      {isOpen && (
        <div className="absolute top-full mt-1 right-0 w-64 max-w-[calc(100vw-2rem)] bg-[var(--surface)] border border-[var(--border-hover)] rounded-[var(--radius-medium)] z-50 overflow-hidden">
          {/* Search */}
          <div className="p-2 border-b border-[var(--border)]">
            <div className="relative">
              <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-[var(--text-subtle)]" />
              <input
                ref={searchInputRef}
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search projects..."
                className="w-full h-7 pl-7 pr-2 text-[11px] rounded-[var(--radius-small)] bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] placeholder:text-[var(--text-subtle)] focus:border-[var(--border-hover)] focus:outline-none"
              />
            </div>
          </div>

          {/* Project list */}
          <div className="max-h-[200px] overflow-y-auto py-1">
            {isLoading && (
              <div className="px-3 py-4 text-center text-[11px] text-[var(--text-subtle)]">
                Loading...
              </div>
            )}
            {!isLoading && filtered.length === 0 && (
              <div className="px-3 py-4 text-center text-[11px] text-[var(--text-subtle)]">
                No projects found
              </div>
            )}
            {!isLoading && filtered.map((project) => (
              <button
                key={project.id}
                onClick={() => {
                  onConnect(project.id, project.name);
                  setIsOpen(false);
                  setSearch('');
                }}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-left hover:bg-[var(--surface-hover)] transition-colors"
              >
                <span className="text-[11px] text-[var(--text)] truncate">{project.name}</span>
                <span className="text-[10px] text-[var(--text-subtle)] flex-shrink-0">{project.slug}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
