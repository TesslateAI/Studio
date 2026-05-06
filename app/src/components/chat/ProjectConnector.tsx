import { useState, useRef, useEffect, useCallback } from 'react';
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
  /** Called when the user clicks "+ New Workspace" in the dropdown. The
      parent owns the create flow (modal, project creation, auto-connect). */
  onRequestNewWorkspace?: () => void;
}

export function ProjectConnector({
  projectId,
  projectName,
  onConnect,
  onDisconnect,
  onRequestNewWorkspace,
}: ProjectConnectorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [search, setSearch] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);

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

  // Focus search on open; reset highlight
  useEffect(() => {
    if (isOpen) {
      searchInputRef.current?.focus();
      setActiveIndex(-1);
    }
  }, [isOpen]);

  // Fetch projects on open
  useEffect(() => {
    if (!isOpen) return;
    setIsLoading(true);
    projectsApi
      .getAll()
      .then((data) => {
        setProjects(Array.isArray(data) ? data : data.projects || []);
      })
      .catch(() => {})
      .finally(() => setIsLoading(false));
  }, [isOpen]);

  const filtered = projects.filter(
    (p) =>
      p.name.toLowerCase().includes(search.toLowerCase()) ||
      p.slug.toLowerCase().includes(search.toLowerCase())
  );

  const totalItems = filtered.length + (onRequestNewWorkspace ? 1 : 0);
  const newWorkspaceIndex = onRequestNewWorkspace ? filtered.length : -1;

  const selectIndex = useCallback(
    (idx: number) => {
      if (idx < 0 || idx >= totalItems) return;
      if (idx === newWorkspaceIndex && onRequestNewWorkspace) {
        setIsOpen(false);
        setSearch('');
        onRequestNewWorkspace();
        return;
      }
      const project = filtered[idx];
      if (project) {
        onConnect(project.id, project.name);
        setIsOpen(false);
        setSearch('');
      }
    },
    [filtered, newWorkspaceIndex, onConnect, onRequestNewWorkspace, totalItems]
  );

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!isOpen) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIndex((i) => {
        const next = i + 1 >= totalItems ? 0 : i + 1;
        itemRefs.current[next]?.scrollIntoView({ block: 'nearest' });
        return next;
      });
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIndex((i) => {
        const next = i <= 0 ? totalItems - 1 : i - 1;
        itemRefs.current[next]?.scrollIntoView({ block: 'nearest' });
        return next;
      });
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (activeIndex >= 0) {
        selectIndex(activeIndex);
      } else if (filtered.length === 1) {
        selectIndex(0);
      }
    } else if (e.key === 'Escape') {
      e.preventDefault();
      setIsOpen(false);
    }
  };

  if (projectId && projectName) {
    return (
      <div className="flex items-center gap-1.5 h-7 px-2.5 rounded-full bg-[var(--surface)] border border-[var(--border)] text-[11px]">
        <Circle size={6} fill="var(--status-success)" className="text-[var(--status-success)]" />
        <span className="text-[var(--text)] font-medium truncate max-w-[120px]">{projectName}</span>
        <button
          onClick={onDisconnect}
          className="p-0.5 rounded-full text-[var(--text-subtle)] hover:text-[var(--text)] hover:bg-[var(--surface-hover)] transition-colors"
          aria-label="Disconnect workspace"
        >
          <X size={10} />
        </button>
      </div>
    );
  }

  return (
    <div ref={dropdownRef} className="relative" onKeyDown={handleKeyDown}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        aria-expanded={isOpen}
        aria-haspopup="listbox"
        className="flex items-center gap-1.5 h-7 px-2.5 rounded-full bg-[var(--surface)] border border-[var(--border)] text-[11px] text-[var(--text-muted)] hover:text-[var(--text)] hover:border-[var(--border-hover)] transition-colors"
      >
        <Plus size={12} />
        <span>Connect workspace</span>
      </button>

      {isOpen && (
        <div
          role="listbox"
          className="absolute top-full mt-1 right-0 w-80 max-w-[calc(100vw-2rem)] bg-[var(--surface)] border border-[var(--border-hover)] rounded-[var(--radius-medium)] shadow-lg z-50 overflow-hidden"
        >
          {/* Search */}
          <div className="p-2 border-b border-[var(--border)]">
            <div className="relative">
              <Search
                size={12}
                className="absolute left-2 top-1/2 -translate-y-1/2 text-[var(--text-subtle)]"
              />
              <input
                ref={searchInputRef}
                type="text"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setActiveIndex(-1);
                }}
                placeholder="Search workspaces..."
                className="w-full h-8 pl-7 pr-2 text-[12px] rounded-[var(--radius-small)] bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] placeholder:text-[var(--text-subtle)] focus:border-[var(--border-hover)] focus:outline-none"
              />
            </div>
          </div>

          {/* Project list */}
          <div className="max-h-[240px] overflow-y-auto py-1">
            {isLoading && (
              <div className="px-3 py-4 text-center text-[11px] text-[var(--text-subtle)]">
                Loading...
              </div>
            )}
            {!isLoading && filtered.length === 0 && (
              <div className="px-3 py-4 text-center text-[11px] text-[var(--text-subtle)]">
                {search ? 'No workspaces match.' : 'No workspaces yet.'}
              </div>
            )}
            {!isLoading && filtered.length > 0 && !search && (
              <div className="px-3 pt-1 pb-1.5 text-[10px] uppercase tracking-wide text-[var(--text-subtle)]">
                Recent
              </div>
            )}
            {!isLoading &&
              filtered.map((project, idx) => (
                <button
                  key={project.id}
                  ref={(el) => {
                    itemRefs.current[idx] = el;
                  }}
                  role="option"
                  aria-selected={activeIndex === idx}
                  onMouseEnter={() => setActiveIndex(idx)}
                  onClick={() => selectIndex(idx)}
                  className={`w-full flex items-center justify-between gap-2 px-3 py-2 text-left transition-colors ${
                    activeIndex === idx
                      ? 'bg-[var(--surface-hover)]'
                      : 'hover:bg-[var(--surface-hover)]'
                  }`}
                >
                  <span className="text-[12px] text-[var(--text)] truncate">{project.name}</span>
                  <span className="text-[10px] text-[var(--text-subtle)] flex-shrink-0 truncate max-w-[120px]">
                    {project.slug}
                  </span>
                </button>
              ))}
          </div>

          {/* "New Workspace" footer — defers to the parent for the actual
              create flow (modal + projectsApi.create + auto-connect). */}
          {onRequestNewWorkspace && (
            <button
              ref={(el) => {
                itemRefs.current[newWorkspaceIndex] = el;
              }}
              role="option"
              aria-selected={activeIndex === newWorkspaceIndex}
              onMouseEnter={() => setActiveIndex(newWorkspaceIndex)}
              onClick={() => selectIndex(newWorkspaceIndex)}
              className={`w-full flex items-center gap-2 px-3 py-2.5 text-left border-t border-[var(--border)] bg-[var(--surface-hover)]/60 transition-colors ${
                activeIndex === newWorkspaceIndex
                  ? 'bg-[var(--surface-hover)]'
                  : 'hover:bg-[var(--surface-hover)]'
              }`}
            >
              <Plus size={14} className="text-[var(--primary)] flex-shrink-0" />
              <span className="text-[12px] font-medium text-[var(--text)]">New workspace</span>
            </button>
          )}
        </div>
      )}
    </div>
  );
}
