import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ArrowClockwise,
  ArrowSquareOut,
  CaretDown,
  FileCode,
  FileText,
  Folder,
  FolderOpen,
  GitBranch,
  GithubLogo,
  HardDrives,
  MagnifyingGlass,
  Warning,
  X,
} from '@phosphor-icons/react';
import { projectsApi } from '../../lib/api';
import { buildFileTree, filterFileTree, type FileNode } from '../../utils/buildFileTree';

interface RepositoryPanelProps {
  projectSlug: string;
}

interface GitTreeResponse {
  status: string;
  source: 'github' | 'local';
  owner: string | null;
  repo: string | null;
  branch: string | null;
  sha: string | null;
  truncated: boolean;
  html_url: string | null;
  files: Array<{
    path: string;
    name: string;
    is_dir: boolean;
    size: number;
    mod_time: number;
    sha?: string;
  }>;
}

/** Map extension → color class. Keeps the tree scannable without being noisy. */
function fileAccentClass(name: string): string {
  const lower = name.toLowerCase();
  const ext = lower.slice(lower.lastIndexOf('.') + 1);
  switch (ext) {
    case 'ts':
    case 'tsx':
      return 'text-[#3b82f6]';
    case 'js':
    case 'jsx':
    case 'mjs':
    case 'cjs':
      return 'text-[#eab308]';
    case 'py':
      return 'text-[#22c55e]';
    case 'go':
      return 'text-[#06b6d4]';
    case 'rs':
      return 'text-[#f97316]';
    case 'md':
    case 'mdx':
    case 'txt':
    case 'rst':
      return 'text-[var(--text-muted)]';
    case 'json':
    case 'yaml':
    case 'yml':
    case 'toml':
      return 'text-[#a78bfa]';
    case 'html':
    case 'css':
    case 'scss':
      return 'text-[#ec4899]';
    default:
      return 'text-[var(--text-subtle)]';
  }
}

function isDocExt(name: string): boolean {
  const lower = name.toLowerCase();
  return (
    lower.endsWith('.md') ||
    lower.endsWith('.mdx') ||
    lower.endsWith('.txt') ||
    lower.endsWith('.rst') ||
    lower === 'license'
  );
}

interface TreeRowProps {
  node: FileNode;
  depth: number;
  expanded: Set<string>;
  toggle: (path: string) => void;
  sourceHtmlUrl: string | null;
  branch: string | null;
  source: 'github' | 'local';
}

function TreeRow({ node, depth, expanded, toggle, sourceHtmlUrl, branch, source }: TreeRowProps) {
  const isOpen = expanded.has(node.path);
  // Finger-friendly row on touch: min-h of 32px, ample hit target to the left.
  const paddingLeft = 8 + depth * 14;

  if (node.isDirectory) {
    return (
      <>
        <button
          type="button"
          onClick={() => toggle(node.path)}
          className="group w-full flex items-center gap-1.5 min-h-[32px] px-2 text-left text-[12px] rounded-[var(--radius-small)] hover:bg-[var(--surface-hover)] transition-colors"
          style={{ paddingLeft }}
          aria-expanded={isOpen}
        >
          <span
            className={`text-[var(--text-subtle)] transition-transform duration-150 ${
              isOpen ? 'rotate-0' : '-rotate-90'
            }`}
          >
            <CaretDown size={10} weight="bold" />
          </span>
          <span className="text-[var(--primary)] flex-shrink-0">
            {isOpen ? <FolderOpen size={14} weight="fill" /> : <Folder size={14} weight="fill" />}
          </span>
          <span className="truncate text-[var(--text)]">{node.name}</span>
          {node.children && node.children.length > 0 && (
            <span className="ml-auto text-[10px] text-[var(--text-subtle)] pr-1">
              {node.children.length}
            </span>
          )}
        </button>
        {isOpen &&
          node.children?.map((child) => (
            <TreeRow
              key={child.path}
              node={child}
              depth={depth + 1}
              expanded={expanded}
              toggle={toggle}
              sourceHtmlUrl={sourceHtmlUrl}
              branch={branch}
              source={source}
            />
          ))}
      </>
    );
  }

  const accent = fileAccentClass(node.name);
  const Icon = isDocExt(node.name) ? FileText : FileCode;
  const href =
    source === 'github' && sourceHtmlUrl && branch
      ? `${sourceHtmlUrl}/blob/${branch}/${encodeURI(node.path)}`
      : null;

  const rowInner = (
    <>
      <span className="w-[10px] flex-shrink-0" />
      <span className={`flex-shrink-0 ${accent}`}>
        <Icon size={14} weight="duotone" />
      </span>
      <span className="truncate text-[12px] text-[var(--text)]">{node.name}</span>
    </>
  );

  if (href) {
    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="group w-full flex items-center gap-1.5 min-h-[32px] px-2 text-left rounded-[var(--radius-small)] hover:bg-[var(--surface-hover)] transition-colors"
        style={{ paddingLeft }}
      >
        {rowInner}
        <span className="ml-auto flex items-center gap-1 text-[10px] text-[var(--text-subtle)] opacity-0 group-hover:opacity-100 transition-opacity pr-1">
          <ArrowSquareOut size={11} weight="bold" />
        </span>
      </a>
    );
  }

  return (
    <div
      className="group w-full flex items-center gap-1.5 min-h-[32px] px-2 text-left rounded-[var(--radius-small)]"
      style={{ paddingLeft }}
    >
      {rowInner}
    </div>
  );
}

export function RepositoryPanel({ projectSlug }: RepositoryPanelProps) {
  const [data, setData] = useState<GitTreeResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const fetchTree = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await projectsApi.getGitTree(projectSlug);
      setData(result);

      // Default-expand the top-level directories so first-time users see
      // one level of structure without having to hunt.
      const topDirs = new Set<string>();
      for (const entry of result.files) {
        if (entry.is_dir && !entry.path.includes('/')) {
          topDirs.add(entry.path);
        }
      }
      setExpanded(topDirs);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load repository tree';
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [projectSlug]);

  useEffect(() => {
    fetchTree();
  }, [fetchTree]);

  const fullTree = useMemo(() => {
    if (!data) return [];
    return buildFileTree(data.files);
  }, [data]);

  const visibleTree = useMemo(() => {
    if (!query.trim()) return fullTree;
    return filterFileTree(fullTree, query.trim());
  }, [fullTree, query]);

  // When searching, expand every directory that has a match so the user sees
  // results in context rather than collapsed.
  useEffect(() => {
    if (!query.trim()) return;
    const next = new Set<string>(expanded);
    const walk = (nodes: FileNode[]) => {
      for (const n of nodes) {
        if (n.isDirectory) {
          next.add(n.path);
          if (n.children) walk(n.children);
        }
      }
    };
    walk(visibleTree);
    setExpanded(next);
    // We intentionally depend on query + visibleTree only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, visibleTree]);

  const toggle = useCallback((path: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }, []);

  const totalFiles = data?.files.filter((f) => !f.is_dir).length ?? 0;
  const totalDirs = data?.files.filter((f) => f.is_dir).length ?? 0;

  return (
    <div className="w-full h-full flex flex-col bg-[var(--bg)] overflow-hidden">
      {/* Header card */}
      <div className="flex-shrink-0 p-2 sm:p-3 pb-2">
        <div className="bg-[var(--surface-hover)] rounded-[var(--radius)] border border-[var(--border)] overflow-hidden">
          <div className="flex items-center gap-2 px-3 py-2 sm:py-2.5">
            <span className="flex-shrink-0 text-[var(--text-muted)]">
              {data?.source === 'github' ? (
                <GithubLogo size={16} weight="bold" />
              ) : (
                <HardDrives size={16} weight="bold" />
              )}
            </span>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1.5 min-w-0">
                <span className="text-[12px] font-semibold text-[var(--text)] truncate">
                  {data?.source === 'github' && data.owner && data.repo
                    ? `${data.owner}/${data.repo}`
                    : 'Project files'}
                </span>
                {data?.source === 'github' && data.html_url && (
                  <a
                    href={data.html_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[var(--text-subtle)] hover:text-[var(--text)] transition-colors flex-shrink-0"
                    title="Open on GitHub"
                    aria-label="Open on GitHub"
                  >
                    <ArrowSquareOut size={12} weight="bold" />
                  </a>
                )}
              </div>
              <div className="flex items-center gap-1.5 mt-0.5 text-[10px] text-[var(--text-muted)]">
                {data?.branch && (
                  <span className="inline-flex items-center gap-1">
                    <GitBranch size={10} weight="bold" />
                    <span className="truncate max-w-[120px]">{data.branch}</span>
                  </span>
                )}
                {data && !loading && (
                  <>
                    {data.branch && <span className="text-[var(--text-subtle)]">·</span>}
                    <span>
                      {totalFiles.toLocaleString()} {totalFiles === 1 ? 'file' : 'files'}
                    </span>
                    <span className="text-[var(--text-subtle)]">·</span>
                    <span>
                      {totalDirs.toLocaleString()} {totalDirs === 1 ? 'folder' : 'folders'}
                    </span>
                  </>
                )}
              </div>
            </div>
            <button
              type="button"
              onClick={fetchTree}
              disabled={loading}
              className="btn btn-icon btn-sm flex-shrink-0"
              title="Refresh"
              aria-label="Refresh repository tree"
            >
              <ArrowClockwise size={13} weight="bold" className={loading ? 'animate-spin' : ''} />
            </button>
          </div>

          {data?.truncated && (
            <div className="flex items-center gap-2 px-3 py-2 border-t border-[var(--border)] bg-[var(--bg)] text-[10px] text-[var(--status-warning)]">
              <Warning size={12} weight="bold" />
              <span>This repository is large — some files were not included in the listing.</span>
            </div>
          )}
        </div>
      </div>

      {/* Search */}
      <div className="flex-shrink-0 px-2 sm:px-3 pb-2">
        <div className="relative">
          <span className="absolute left-2 top-1/2 -translate-y-1/2 text-[var(--text-subtle)] pointer-events-none">
            <MagnifyingGlass size={13} weight="bold" />
          </span>
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search files…"
            className="w-full pl-7 pr-8 py-1.5 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)]"
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery('')}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-subtle)] hover:text-[var(--text)]"
              aria-label="Clear search"
            >
              <X size={12} weight="bold" />
            </button>
          )}
        </div>
      </div>

      {/* Tree */}
      <div className="flex-1 overflow-y-auto px-2 sm:px-3 pb-3">
        <div className="bg-[var(--surface-hover)] rounded-[var(--radius)] border border-[var(--border)] p-1.5 min-h-full">
          {loading && !data && (
            <div className="flex flex-col items-center justify-center py-10 gap-2">
              <ArrowClockwise
                size={18}
                weight="bold"
                className="animate-spin text-[var(--text-muted)]"
              />
              <p className="text-[11px] text-[var(--text-muted)]">Loading repository…</p>
            </div>
          )}

          {error && !loading && (
            <div className="flex flex-col items-center justify-center py-10 px-4 text-center gap-2">
              <Warning size={22} weight="bold" className="text-[var(--status-warning)]" />
              <p className="text-xs text-[var(--text)]">We couldn't load the repository</p>
              <p className="text-[10px] text-[var(--text-muted)] max-w-xs">{error}</p>
              <button type="button" onClick={fetchTree} className="btn btn-sm mt-1">
                Try again
              </button>
            </div>
          )}

          {!loading && !error && visibleTree.length === 0 && (
            <div className="flex flex-col items-center justify-center py-10 px-4 text-center gap-2">
              <Folder size={22} weight="duotone" className="text-[var(--text-subtle)]" />
              <p className="text-xs text-[var(--text-muted)]">
                {query ? 'No files match your search.' : 'No files in this repository yet.'}
              </p>
              {query && (
                <button type="button" onClick={() => setQuery('')} className="btn btn-sm mt-1">
                  Clear search
                </button>
              )}
            </div>
          )}

          {!error &&
            visibleTree.map((node) => (
              <TreeRow
                key={node.path}
                node={node}
                depth={0}
                expanded={expanded}
                toggle={toggle}
                sourceHtmlUrl={data?.html_url ?? null}
                branch={data?.branch ?? null}
                source={data?.source ?? 'local'}
              />
            ))}
        </div>
      </div>
    </div>
  );
}

export default RepositoryPanel;
