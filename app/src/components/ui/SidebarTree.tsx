import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowRight,
  Folder,
  FolderOpen,
  Loader2,
  MessageSquare,
  Plus,
  SlidersHorizontal,
  Workflow,
  Terminal,
  Check,
} from 'lucide-react';
import {
  DiscordLogo,
  SlackLogo,
  TelegramLogo,
  WhatsappLogo,
} from '@phosphor-icons/react';
import { AnimatePresence, motion } from 'framer-motion';
import { Tooltip } from './Tooltip';
import {
  sidebarApi,
  type SidebarAutomation,
  type SidebarChat,
  type SidebarChatPlatform,
  type SidebarProject,
  type SidebarTreeResponse,
} from '../../lib/api';

const COLLAPSED_KEY = 'sidebarTree.collapsedProjects';
const EXPANDED_NESTED_KEY = 'sidebarTree.expandedNestedProjects';
const PREFS_KEY = 'sidebarTree.prefs';

/** Top-level visible cap before "Show all (N)" routes to /chat. */
const TOP_LEVEL_LIMIT = 10;
/** Chats shown inside a project before its inline "Show all" expands. */
const PROJECT_NESTED_LIMIT = 3;

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

type FilterType = 'all' | 'chats' | 'projects' | 'automations';
type SortField = 'recency' | 'name';

interface TreePrefs {
  filterType: FilterType;
  sortField: SortField;
}

const DEFAULT_PREFS: TreePrefs = { filterType: 'all', sortField: 'recency' };

function loadStringSet(key: string): Set<string> {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return new Set();
    const arr = JSON.parse(raw);
    if (Array.isArray(arr)) return new Set(arr.filter((x) => typeof x === 'string'));
  } catch {
    // ignore corrupted value
  }
  return new Set();
}

function saveStringSet(key: string, set: Set<string>) {
  try {
    localStorage.setItem(key, JSON.stringify(Array.from(set)));
  } catch {
    // ignore quota / disabled storage
  }
}

function loadPrefs(): TreePrefs {
  try {
    const raw = localStorage.getItem(PREFS_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      const filterType: FilterType =
        parsed?.filterType === 'chats' ||
        parsed?.filterType === 'projects' ||
        parsed?.filterType === 'automations'
          ? parsed.filterType
          : 'all';
      const sortField: SortField = parsed?.sortField === 'name' ? 'name' : 'recency';
      return { filterType, sortField };
    }
  } catch {
    // ignore corrupted value
  }
  return { ...DEFAULT_PREFS };
}

function savePrefs(prefs: TreePrefs) {
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
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

// ─── Item modeling ───────────────────────────────────────────────────────────
//
// The sidebar timeline is a single recency-sorted feed mixing root-level
// chats, projects (which fan out their own threads), and active automations.
// Modeling them as one discriminated union lets us share the sort, filter,
// active-item-hoist, slice-to-top-N, and "Show all" pipeline.
type SidebarItem =
  | { kind: 'rootChat'; id: string; recency: number; name: string; chat: SidebarChat }
  | {
      kind: 'project';
      id: string;
      recency: number;
      name: string;
      project: SidebarProject;
    }
  | {
      kind: 'automation';
      id: string;
      recency: number;
      name: string;
      automation: SidebarAutomation;
    };

function chatRecency(chat: SidebarChat): number {
  const ts = chat.updated_at || chat.created_at;
  return ts ? new Date(ts).getTime() : 0;
}

function projectRecency(project: SidebarProject): number {
  let max = 0;
  if (project.latest_activity_at) {
    max = new Date(project.latest_activity_at).getTime();
  }
  if (project.updated_at) {
    max = Math.max(max, new Date(project.updated_at).getTime());
  }
  for (const c of project.chats) {
    max = Math.max(max, chatRecency(c));
  }
  return max;
}

function automationRecency(a: SidebarAutomation): number {
  const ts = a.updated_at || a.created_at;
  return ts ? new Date(ts).getTime() : 0;
}

// ─── Main component ──────────────────────────────────────────────────────────

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
  const [collapsedSet, setCollapsedSet] = useState<Set<string>>(() =>
    loadStringSet(COLLAPSED_KEY)
  );
  const [expandedNestedSet, setExpandedNestedSet] = useState<Set<string>>(() =>
    loadStringSet(EXPANDED_NESTED_KEY)
  );
  const [prefs, setPrefs] = useState<TreePrefs>(() => loadPrefs());
  const inflightRef = useRef(false);

  useEffect(() => {
    saveStringSet(COLLAPSED_KEY, collapsedSet);
  }, [collapsedSet]);
  useEffect(() => {
    saveStringSet(EXPANDED_NESTED_KEY, expandedNestedSet);
  }, [expandedNestedSet]);
  useEffect(() => {
    savePrefs(prefs);
  }, [prefs]);

  const refreshTree = useCallback(async () => {
    if (inflightRef.current) return;
    inflightRef.current = true;
    try {
      const data = await sidebarApi.getTree();
      setTree(data);
    } catch {
      // Silent failure — the sidebar must never block the UI. Keep the
      // previous tree visible if a poll fails transiently.
      setTree((prev) => prev ?? { rootChats: [], projects: [], automations: [] });
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

  const toggleNestedExpansion = useCallback((id: string) => {
    setExpandedNestedSet((prev) => {
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

  const openAutomation = useCallback(
    (automation: SidebarAutomation) => {
      navigate(`/automations/${automation.id}`);
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

  // ─── Build the unified, sorted, filtered, capped item list ─────────────
  const allItems: SidebarItem[] = useMemo(() => {
    if (!tree) return [];
    const items: SidebarItem[] = [];

    // Root chats — drop untitled before they enter the timeline.
    for (const c of tree.rootChats) {
      if (!isMeaningfulChat(c)) continue;
      items.push({
        kind: 'rootChat',
        id: c.id,
        recency: chatRecency(c),
        name: c.title || '',
        chat: c,
      });
    }

    // Projects — sort their nested chats up-front; the row component
    // consumes the already-ordered list when expanded.
    for (const p of tree.projects) {
      const sortedChats = [...p.chats]
        .filter((c) => isMeaningfulChat(c) || c.id === activeChatId)
        .sort((a, b) => chatRecency(b) - chatRecency(a));
      const projectWithSortedChats: SidebarProject = { ...p, chats: sortedChats };
      items.push({
        kind: 'project',
        id: p.id,
        recency: projectRecency(projectWithSortedChats),
        name: p.name,
        project: projectWithSortedChats,
      });
    }

    // Automations — already filtered to is_active by the server.
    for (const a of tree.automations) {
      items.push({
        kind: 'automation',
        id: a.id,
        recency: automationRecency(a),
        name: a.name,
        automation: a,
      });
    }

    return items;
  }, [tree, isMeaningfulChat, activeChatId]);

  const filteredItems = useMemo(() => {
    if (prefs.filterType === 'all') return allItems;
    if (prefs.filterType === 'chats') return allItems.filter((i) => i.kind === 'rootChat');
    if (prefs.filterType === 'projects') return allItems.filter((i) => i.kind === 'project');
    return allItems.filter((i) => i.kind === 'automation');
  }, [allItems, prefs.filterType]);

  const sortedItems = useMemo(() => {
    const arr = [...filteredItems];
    arr.sort((a, b) => {
      if (prefs.sortField === 'name') {
        return a.name.localeCompare(b.name);
      }
      return b.recency - a.recency;
    });

    // Active-project-pin: if the user is currently inside a project, hoist
    // its row to the top regardless of recency. Preserves the existing
    // "your active context is always visible first" affordance.
    if (activeProjectSlug) {
      const idx = arr.findIndex(
        (i) => i.kind === 'project' && i.project.slug === activeProjectSlug
      );
      if (idx > 0) {
        return [arr[idx], ...arr.slice(0, idx), ...arr.slice(idx + 1)];
      }
    }
    return arr;
  }, [filteredItems, prefs.sortField, activeProjectSlug]);

  const visibleItems = sortedItems.slice(0, TOP_LEVEL_LIMIT);
  const hiddenCount = sortedItems.length - visibleItems.length;

  const hasContent = sortedItems.length > 0;

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

  const showAll = useCallback(() => {
    // Per product direction: "Show all" routes to /chat and opens the
    // collapsed sessions panel inside it. Chat.tsx reads this state on
    // mount and flips its panel open.
    navigate('/chat', { state: { openSessionsPanel: true } });
  }, [navigate]);

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

      {/* Section header — small filter/sort affordance only. We deliberately
          skip a textual label to keep visual density low; the items below
          carry their own iconography that already reads as "your stuff". */}
      <div className="flex items-center justify-end pl-[7px] pr-[10px] mb-1 gap-1">
        <FilterSortMenu prefs={prefs} onChange={setPrefs} />
      </div>

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
          {visibleItems.map((item) => {
            if (item.kind === 'rootChat') {
              return (
                <ChatRow
                  key={`root-${item.id}`}
                  chat={item.chat}
                  nested={false}
                  active={activeChatId === item.id}
                  onClick={() => openChat(item.chat)}
                />
              );
            }
            if (item.kind === 'automation') {
              return (
                <AutomationRow
                  key={`automation-${item.id}`}
                  automation={item.automation}
                  onClick={() => openAutomation(item.automation)}
                />
              );
            }
            // project
            const project = item.project;
            const isOpen = !collapsedSet.has(project.id);
            const isActive = activeProjectSlug === project.slug;
            const projRunning = projectRunningCount(project);
            const isNestedExpanded = expandedNestedSet.has(project.id);
            const nestedToShow = isNestedExpanded
              ? project.chats
              : project.chats.slice(0, PROJECT_NESTED_LIMIT);
            const hiddenNested = project.chats.length - nestedToShow.length;
            return (
              <div key={`project-${project.id}`} className="flex flex-col gap-0.5">
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
                          <>
                            {nestedToShow.map((chat) => (
                              <ChatRow
                                key={chat.id}
                                chat={chat}
                                nested
                                active={activeChatId === chat.id}
                                onClick={() => openChat(chat, project.slug)}
                              />
                            ))}
                            {project.chats.length > PROJECT_NESTED_LIMIT && (
                              <button
                                type="button"
                                onClick={() => toggleNestedExpansion(project.id)}
                                className="flex items-center h-6 w-full pl-[29px] pr-[7px] gap-2 text-[11px] text-[var(--text-muted)] hover:text-[var(--sidebar-text)] hover:bg-[var(--sidebar-hover)] rounded transition-colors"
                              >
                                <span>
                                  {isNestedExpanded
                                    ? 'Show less'
                                    : `Show all (${project.chats.length})`}
                                </span>
                                {!isNestedExpanded && hiddenNested > 0 && (
                                  <span className="text-[10px] text-[var(--text-subtle)] tabular-nums">
                                    +{hiddenNested}
                                  </span>
                                )}
                              </button>
                            )}
                          </>
                        )}
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            );
          })}

          {/* Top-level "Show all" — routes to /chat and opens its sessions
              panel. Chat.tsx is what actually surfaces every thread; the
              sidebar timeline is only the top-N most recent. */}
          {hiddenCount > 0 && (
            <button
              type="button"
              onClick={showAll}
              className="group flex items-center h-7 w-full mt-0.5 pl-[7px] pr-[7px] gap-2 rounded-lg text-[var(--text-muted)] hover:text-[var(--sidebar-text)] hover:bg-[var(--sidebar-hover)] transition-colors"
            >
              <ArrowRight size={12} className="flex-shrink-0" />
              <span className="text-[12px] flex-1 text-left">Show all</span>
              <span className="text-[10px] text-[var(--text-subtle)] tabular-nums">
                +{hiddenCount}
              </span>
            </button>
          )}
        </div>
      )}
    </>
  );
}

// ─── FilterSortMenu ──────────────────────────────────────────────────────────

interface FilterSortMenuProps {
  prefs: TreePrefs;
  onChange: (next: TreePrefs) => void;
}

const FILTER_LABELS: Record<FilterType, string> = {
  all: 'All',
  chats: 'Threads',
  projects: 'Workspaces',
  automations: 'Automations',
};

const SORT_LABELS: Record<SortField, string> = {
  recency: 'Last activity',
  name: 'Name',
};

function FilterSortMenu({ prefs, onChange }: FilterSortMenuProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const isCustomized = prefs.filterType !== 'all' || prefs.sortField !== 'recency';

  return (
    <div ref={ref} className="relative">
      <Tooltip content="Filter & sort" side="top" delay={300}>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-label="Filter and sort threads"
          aria-expanded={open}
          className={`flex items-center justify-center h-5 w-5 rounded transition-colors ${
            isCustomized
              ? 'text-[var(--sidebar-text)] bg-[var(--sidebar-hover)]'
              : 'text-[var(--text-muted)] hover:text-[var(--sidebar-text)] hover:bg-[var(--sidebar-hover)]'
          }`}
        >
          <SlidersHorizontal size={12} />
        </button>
      </Tooltip>
      {open && (
        <div
          role="menu"
          className="absolute right-0 top-full mt-1 z-50 min-w-[180px] py-1 rounded-[var(--radius-medium)] border bg-[var(--sidebar-bg)] shadow-xl"
          style={{ borderColor: 'var(--sidebar-border)' }}
        >
          <div className="px-3 py-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--text-subtle)]">
            Sort
          </div>
          {(['recency', 'name'] as SortField[]).map((field) => (
            <button
              key={field}
              type="button"
              role="menuitemradio"
              aria-checked={prefs.sortField === field}
              onClick={() => {
                onChange({ ...prefs, sortField: field });
                setOpen(false);
              }}
              className={`w-full flex items-center gap-2 px-3 py-1.5 text-[12px] transition-colors ${
                prefs.sortField === field
                  ? 'text-[var(--sidebar-text)]'
                  : 'text-[var(--text-muted)] hover:text-[var(--sidebar-text)] hover:bg-[var(--sidebar-hover)]'
              }`}
            >
              <span className="flex-1 text-left">{SORT_LABELS[field]}</span>
              {prefs.sortField === field && <Check size={12} />}
            </button>
          ))}

          <div
            className="my-1 border-t"
            style={{ borderColor: 'var(--sidebar-border)' }}
          />

          <div className="px-3 py-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--text-subtle)]">
            Show
          </div>
          {(['all', 'chats', 'projects', 'automations'] as FilterType[]).map((t) => (
            <button
              key={t}
              type="button"
              role="menuitemradio"
              aria-checked={prefs.filterType === t}
              onClick={() => {
                onChange({ ...prefs, filterType: t });
                setOpen(false);
              }}
              className={`w-full flex items-center gap-2 px-3 py-1.5 text-[12px] transition-colors ${
                prefs.filterType === t
                  ? 'text-[var(--sidebar-text)]'
                  : 'text-[var(--text-muted)] hover:text-[var(--sidebar-text)] hover:bg-[var(--sidebar-hover)]'
              }`}
            >
              <span className="flex-1 text-left">{FILTER_LABELS[t]}</span>
              {prefs.filterType === t && <Check size={12} />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── ChatRow ─────────────────────────────────────────────────────────────────

interface ChatRowProps {
  chat: SidebarChat;
  nested: boolean;
  active: boolean;
  onClick: () => void;
}

/** Pick the row icon based on which surface the thread came from. Channel
 * icons use the platform's brand mark so a user can spot at-a-glance "this
 * is the Slack thread" vs the browser conversation. */
function chatRowIcon(platform: SidebarChatPlatform, isRunning: boolean) {
  if (isRunning) {
    return (
      <Loader2
        size={12}
        className="flex-shrink-0 animate-spin text-[var(--accent)]"
        aria-label="Agent running"
      />
    );
  }
  switch (platform) {
    case 'discord':
      return (
        <DiscordLogo
          size={12}
          weight="fill"
          className="flex-shrink-0 text-[var(--text-subtle)]"
        />
      );
    case 'slack':
      return (
        <SlackLogo
          size={12}
          weight="fill"
          className="flex-shrink-0 text-[var(--text-subtle)]"
        />
      );
    case 'telegram':
      return (
        <TelegramLogo
          size={12}
          weight="fill"
          className="flex-shrink-0 text-[var(--text-subtle)]"
        />
      );
    case 'whatsapp':
      return (
        <WhatsappLogo
          size={12}
          weight="fill"
          className="flex-shrink-0 text-[var(--text-subtle)]"
        />
      );
    case 'cli':
      return <Terminal size={12} className="flex-shrink-0 text-[var(--text-subtle)]" />;
    case 'signal':
    default:
      return (
        <MessageSquare size={12} className="flex-shrink-0 text-[var(--text-subtle)]" />
      );
  }
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
      {chatRowIcon(chat.platform, isRunning)}
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

// ─── AutomationRow ───────────────────────────────────────────────────────────

interface AutomationRowProps {
  automation: SidebarAutomation;
  onClick: () => void;
}

function AutomationRow({ automation, onClick }: AutomationRowProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={automation.name}
      className="group flex items-center h-7 w-full transition-colors rounded-lg pl-[7px] pr-[7px] gap-2 hover:bg-[var(--sidebar-hover)]"
    >
      <Workflow size={12} className="flex-shrink-0 text-[var(--text-subtle)]" />
      <span className="text-[13px] truncate flex-1 text-left text-[var(--text-muted)] group-hover:text-[var(--sidebar-text)] transition-colors">
        {automation.name}
      </span>
      <span className="text-[10px] text-[var(--text-subtle)] tabular-nums flex-shrink-0">
        {formatRelativeTime(automation.updated_at)}
      </span>
    </button>
  );
}
