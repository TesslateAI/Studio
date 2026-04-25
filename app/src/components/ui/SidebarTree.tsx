import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowRight, Folder, FolderOpen, Loader2, MessageSquare, Plus } from 'lucide-react';
import { AnimatePresence, motion } from 'framer-motion';
import { Tooltip } from './Tooltip';
import {
  sidebarApi,
  type SidebarChat,
  type SidebarProject,
  type SidebarTreeResponse,
} from '../../lib/api';

const COLLAPSED_KEY = 'sidebarTree.collapsedProjects';

/**
 * Interval between refetches of the sidebar tree. The poll drives the
 * "agent running" spinner on every chat row so users can see parallel
 * work across projects without opening each one.
 *
 * 4s is a balance: fast enough that a new agent-running state appears
 * before users wonder if anything's happening, slow enough that the
 * backend query stays trivial.
 */
const POLL_INTERVAL_MS = 4000;

/** Chat statuses that should render a running-spinner in the sidebar. */
const RUNNING_STATUSES = new Set(['running', 'waiting_approval']);

function loadCollapsed(): Set<string> {
  try {
    const raw = localStorage.getItem(COLLAPSED_KEY);
    if (!raw) return new Set();
    const arr = JSON.parse(raw);
    if (Array.isArray(arr)) return new Set(arr.filter((x) => typeof x === 'string'));
  } catch {
    // ignore corrupted value
  }
  return new Set();
}

function saveCollapsed(set: Set<string>) {
  try {
    localStorage.setItem(COLLAPSED_KEY, JSON.stringify(Array.from(set)));
  } catch {
    // ignore quota / disabled storage
  }
}

function formatRelativeTime(dateStr: string | null): string {
  if (!dateStr) return '';
  const diffMs = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return 'now';
  if (mins < 60) return `${mins}m`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d`;
  return new Date(dateStr).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
  });
}

interface SidebarTreeProps {
  /** Re-fetch key: bump to force a refresh (e.g. team switch). */
  reloadKey?: string | number;
  /** Called when the user clicks the "+" button. */
  onCreateProject: () => void;
  /** Collapsed-mode icon placeholder — caller renders something different. */
  collapsed?: boolean;
  /** Currently-active project slug (for highlight). */
  activeProjectSlug?: string | null;
  /** Currently-active chat id (for highlight). */
  activeChatId?: string | null;
}

export function SidebarTree({
  reloadKey,
  onCreateProject,
  collapsed = false,
  activeProjectSlug,
  activeChatId,
}: SidebarTreeProps) {
  const navigate = useNavigate();
  const [tree, setTree] = useState<SidebarTreeResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [collapsedSet, setCollapsedSet] = useState<Set<string>>(() => loadCollapsed());
  const inflightRef = useRef(false);

  useEffect(() => {
    saveCollapsed(collapsedSet);
  }, [collapsedSet]);

  const refreshTree = useCallback(async () => {
    if (inflightRef.current) return;
    inflightRef.current = true;
    try {
      const data = await sidebarApi.getTree();
      setTree(data);
    } catch {
      // Silent failure — the sidebar must never block the UI. Keep the
      // previous tree visible if a poll fails transiently.
      setTree((prev) => prev ?? { rootChats: [], projects: [] });
    } finally {
      inflightRef.current = false;
    }
  }, []);

  // Initial + team-switch fetch. `reloadKey` changes on team switch /
  // after project creation to force a fresh tree.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    refreshTree().finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [reloadKey, refreshTree]);

  // Background poll so parallel agent activity shows up as live spinners
  // even when the user is viewing a different chat. Pauses while the tab
  // is hidden so we don't keep a backend request loop going in background
  // tabs.
  useEffect(() => {
    const tick = () => {
      if (document.visibilityState === 'visible') {
        refreshTree();
      }
    };
    const id = window.setInterval(tick, POLL_INTERVAL_MS);
    const onVis = () => {
      if (document.visibilityState === 'visible') refreshTree();
    };
    document.addEventListener('visibilitychange', onVis);
    return () => {
      window.clearInterval(id);
      document.removeEventListener('visibilitychange', onVis);
    };
  }, [refreshTree]);

  const toggleProject = useCallback((id: string) => {
    setCollapsedSet((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  // Project-nested chats open in the project's builder view (with the
  // chat preselected via route state). Root-level "loose" chats remain on
  // /chat. Passing the slug — rather than re-deriving from chat.project_id —
  // keeps this self-contained at the call site where we already iterate
  // tree.projects[].chats.
  const openChat = useCallback(
    (chat: SidebarChat, projectSlug?: string | null) => {
      if (projectSlug) {
        navigate(`/project/${projectSlug}/builder`, { state: { sessionId: chat.id } });
      } else {
        navigate('/chat', { state: { sessionId: chat.id } });
      }
    },
    [navigate]
  );

  const openProject = useCallback(
    (project: SidebarProject) => {
      navigate(`/project/${project.slug}/builder`);
    },
    [navigate]
  );

  /** Untitled / unnamed chats clutter the sidebar — typically the result of
   * accidentally creating a chat without sending a first message. Hide them
   * so the sidebar only surfaces conversations the user actually intended. */
  const isMeaningfulChat = useCallback(
    (chat: SidebarChat): boolean => {
      const t = (chat.title || '').trim();
      if (!t) return false;
      if (t.toLowerCase() === 'untitled') return false;
      // Always show the active chat even if untitled — the user is looking
      // at it right now and removing it from the sidebar would be jarring.
      if (activeChatId && chat.id === activeChatId) return true;
      return true;
    },
    [activeChatId]
  );

  const recencyKey = (chat: SidebarChat): number => {
    const ts = chat.updated_at || chat.created_at;
    return ts ? new Date(ts).getTime() : 0;
  };

  const projectRecencyKey = (project: SidebarProject): number => {
    let max = 0;
    if (project.latest_activity_at) {
      max = new Date(project.latest_activity_at).getTime();
    }
    if (project.updated_at) {
      max = Math.max(max, new Date(project.updated_at).getTime());
    }
    for (const c of project.chats) {
      max = Math.max(max, recencyKey(c));
    }
    return max;
  };

  /** Filter + sort the tree:
   *  - Drop "Untitled" chats (so empty/abandoned chats don't pile up).
   *  - Sort root chats by recency (newest first).
   *  - Sort project chats by recency.
   *  - Sort projects by recency, then float the currently-open project to
   *    the top so the user's active context is always visible first. */
  const visibleRootChats = useMemo(() => {
    const chats = (tree?.rootChats ?? []).filter(isMeaningfulChat);
    return [...chats].sort((a, b) => recencyKey(b) - recencyKey(a));
  }, [tree?.rootChats, isMeaningfulChat]);

  const orderedProjects = useMemo(() => {
    const projects = (tree?.projects ?? []).map((p) => ({
      ...p,
      chats: [...p.chats]
        .filter((c) => isMeaningfulChat(c) || c.id === activeChatId)
        .sort((a, b) => recencyKey(b) - recencyKey(a)),
    }));

    projects.sort((a, b) => projectRecencyKey(b) - projectRecencyKey(a));

    if (!activeProjectSlug) return projects;
    const idx = projects.findIndex((p) => p.slug === activeProjectSlug);
    if (idx <= 0) return projects;
    return [projects[idx], ...projects.slice(0, idx), ...projects.slice(idx + 1)];
  }, [tree?.projects, activeProjectSlug, isMeaningfulChat, activeChatId]);

  const hasContent = useMemo(() => {
    return visibleRootChats.length > 0 || orderedProjects.length > 0;
  }, [visibleRootChats, orderedProjects]);

  /**
   * Total count of chats currently showing a running-agent spinner. Shown
   * next to the section header so users see "3 running" across their whole
   * workspace at a glance — even when no project is expanded.
   */
  const runningCount = useMemo(() => {
    if (!tree) return 0;
    let n = 0;
    for (const c of tree.rootChats) if (RUNNING_STATUSES.has(c.status)) n += 1;
    for (const p of tree.projects) {
      for (const c of p.chats) if (RUNNING_STATUSES.has(c.status)) n += 1;
    }
    return n;
  }, [tree]);

  const projectRunningCount = useCallback((project: SidebarProject) => {
    let n = 0;
    for (const c of project.chats) if (RUNNING_STATUSES.has(c.status)) n += 1;
    return n;
  }, []);

  // Collapsed sidebar variant: single Folder icon; a tiny Loader2 overlay
  // signals background agent activity so users notice it even when the
  // sidebar is narrow.
  if (collapsed) {
    const tip =
      runningCount > 0
        ? `${runningCount} agent${runningCount === 1 ? '' : 's'} running`
        : 'Workspaces and Threads';
    return (
      <Tooltip content={tip} side="right" delay={200}>
        <button
          onClick={onCreateProject}
          className="group relative flex items-center justify-center h-7 w-full transition-colors rounded-lg hover:bg-[var(--sidebar-hover)]"
        >
          <Folder size={16} className="text-[var(--text-muted)]" />
          {runningCount > 0 && (
            <Loader2
              size={9}
              className="absolute -top-0.5 -right-0.5 animate-spin text-[var(--accent)]"
              aria-hidden="true"
            />
          )}
        </button>
      </Tooltip>
    );
  }

  return (
    <>
      <div className="h-px bg-[var(--sidebar-border)] my-2 mx-3 flex-shrink-0" />

      {loading && !tree ? (
        <div className="px-[7px] py-1 text-[11px] text-[var(--text-subtle)]">Loading…</div>
      ) : !hasContent ? (
        <button
          onClick={onCreateProject}
          className="group flex items-center h-7 w-full transition-colors rounded-lg pl-[7px] pr-[7px] gap-2 hover:bg-[var(--sidebar-hover)]"
        >
          <Plus size={14} className="flex-shrink-0 text-[var(--text-muted)]" />
          <span className="text-[12px] text-[var(--text-muted)] group-hover:text-[var(--sidebar-text)] transition-colors">
            Create your first workspace
          </span>
        </button>
      ) : (
        <div className="flex flex-col gap-0.5 mt-0.5">
          {/* Root-level chats first — un-nested, the "loose" chats. Sorted by
              recency, with untitled/empty chats hidden. */}
          {visibleRootChats.map((chat) => (
            <ChatRow
              key={chat.id}
              chat={chat}
              nested={false}
              active={activeChatId === chat.id}
              onClick={() => openChat(chat)}
            />
          ))}

          {/* Projects (folders) with their chats underneath. Active project
              is hoisted to the top via `orderedProjects`. */}
          {orderedProjects.map((project) => {
            const isOpen = !collapsedSet.has(project.id);
            const isActive = activeProjectSlug === project.slug;
            const projRunning = projectRunningCount(project);
            return (
              <div key={project.id} className="flex flex-col gap-0.5">
                <div className="group flex items-center h-7 w-full rounded-lg pl-[7px] pr-[7px] gap-2 hover:bg-[var(--sidebar-hover)]">
                  <button
                    type="button"
                    onClick={() => toggleProject(project.id)}
                    aria-expanded={isOpen}
                    aria-label={isOpen ? `Collapse ${project.name}` : `Expand ${project.name}`}
                    className={`flex items-center gap-2 flex-1 min-w-0 text-left h-7 rounded transition-colors ${
                      isActive ? 'text-[var(--sidebar-text)]' : ''
                    }`}
                  >
                    {isOpen ? (
                      <FolderOpen
                        size={14}
                        className={`flex-shrink-0 transition-colors ${
                          isActive
                            ? 'text-[var(--sidebar-text)]'
                            : 'text-[var(--text-muted)] group-hover:text-[var(--sidebar-text)]'
                        }`}
                      />
                    ) : (
                      <Folder
                        size={14}
                        className={`flex-shrink-0 transition-colors ${
                          isActive
                            ? 'text-[var(--sidebar-text)]'
                            : 'text-[var(--text-muted)] group-hover:text-[var(--sidebar-text)]'
                        }`}
                      />
                    )}
                    <span
                      className={`text-[13px] truncate flex-1 transition-colors ${
                        isActive
                          ? 'text-[var(--sidebar-text)]'
                          : 'text-[var(--text-muted)] group-hover:text-[var(--sidebar-text)]'
                      }`}
                    >
                      {project.name}
                    </span>
                    {projRunning > 0 ? (
                      <Tooltip
                        content={`${projRunning} running in ${project.name}`}
                        side="top"
                        delay={300}
                      >
                        <span className="flex items-center gap-1 text-[10px] text-[var(--accent)] tabular-nums flex-shrink-0">
                          <Loader2 size={10} className="animate-spin" aria-hidden="true" />
                          {projRunning}
                        </span>
                      </Tooltip>
                    ) : project.chats.length > 0 ? (
                      <span className="text-[10px] text-[var(--text-subtle)] tabular-nums flex-shrink-0 group-hover:hidden">
                        {project.chats.length}
                      </span>
                    ) : null}
                  </button>
                  <Tooltip content="Open project" side="top" delay={300}>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        openProject(project);
                      }}
                      aria-label={`Open ${project.name}`}
                      className="hidden group-hover:flex items-center justify-center h-5 w-5 flex-shrink-0 rounded hover:bg-[var(--sidebar-hover)] text-[var(--text-muted)] hover:text-[var(--sidebar-text)] transition-colors"
                    >
                      <ArrowRight size={12} />
                    </button>
                  </Tooltip>
                </div>

                <AnimatePresence initial={false}>
                  {isOpen && (
                    <motion.div
                      key={project.id}
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration: 0.18, ease: [0.4, 0, 0.2, 1] }}
                      style={{ overflow: 'hidden' }}
                    >
                      <div className="flex flex-col gap-0.5">
                        {project.chats.length === 0 ? (
                          <div className="pl-[29px] pr-[7px] h-6 flex items-center text-[11px] text-[var(--text-subtle)] italic">
                            No threads yet
                          </div>
                        ) : (
                          project.chats.map((chat) => (
                            <ChatRow
                              key={chat.id}
                              chat={chat}
                              nested
                              active={activeChatId === chat.id}
                              onClick={() => openChat(chat, project.slug)}
                            />
                          ))
                        )}
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}

interface ChatRowProps {
  chat: SidebarChat;
  nested: boolean;
  active: boolean;
  onClick: () => void;
}

function ChatRow({ chat, nested, active, onClick }: ChatRowProps) {
  const paddingLeft = nested ? 'pl-[29px]' : 'pl-[7px]';
  const isRunning = RUNNING_STATUSES.has(chat.status);
  const tooltip = isRunning
    ? chat.status === 'waiting_approval'
      ? `${chat.title} — awaiting approval`
      : `${chat.title} — agent running`
    : chat.title;
  return (
    <button
      type="button"
      onClick={onClick}
      title={tooltip}
      className={`group flex items-center h-7 w-full transition-colors rounded-lg ${paddingLeft} pr-[7px] gap-2 ${
        active ? 'bg-[var(--sidebar-active)]' : 'hover:bg-[var(--sidebar-hover)]'
      }`}
    >
      {isRunning ? (
        <Loader2
          size={12}
          className="flex-shrink-0 animate-spin text-[var(--accent)]"
          aria-label="Agent running"
        />
      ) : (
        <MessageSquare size={12} className="flex-shrink-0 text-[var(--text-subtle)]" />
      )}
      <span
        className={`text-[13px] truncate flex-1 text-left transition-colors ${
          isRunning
            ? 'text-[var(--sidebar-text)] font-medium'
            : active
              ? 'text-[var(--sidebar-text)]'
              : 'text-[var(--text-muted)] group-hover:text-[var(--sidebar-text)]'
        }`}
      >
        {chat.title}
      </span>
      <span className="text-[10px] text-[var(--text-subtle)] tabular-nums flex-shrink-0">
        {formatRelativeTime(chat.updated_at)}
      </span>
    </button>
  );
}
