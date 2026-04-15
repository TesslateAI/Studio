import { useState, useEffect, useRef, useCallback, type ComponentType } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate, useLocation } from 'react-router-dom';
import { Tooltip } from './Tooltip';
import { HelpMenu } from './HelpMenu';
import { motion } from 'framer-motion';
import {
  Home,
  FolderOpen,
  Boxes,
  BookOpen,
  PanelLeft,
  ChevronDown,
  ArrowUp,
  Cpu,
  Palette,
  Zap,
  Plug,
  Rocket,
  Clock,
} from 'lucide-react';
import { MoodyFace } from './MoodyFace';
import { User, CaretDown, Coins, CreditCard, Gear, SignOut, Plus, Package, SquaresFour } from '@phosphor-icons/react';
import { KeyboardShortcutsModal } from '../KeyboardShortcutsModal';
import { billingApi, chatApi, projectsApi, teamsApi } from '../../lib/api';
import toast from 'react-hot-toast';
import { useAuth } from '../../contexts/AuthContext';
import { useTeam } from '../../contexts/TeamContext';
import { modKey } from '../../lib/keyboard-registry';
import type { CreditBalanceResponse } from '../../types/billing';

interface NavigationSidebarProps {
  activePage:
    | 'home'
    | 'chat'
    | 'apps'
    | 'dashboard'
    | 'marketplace'
    | 'library'
    | 'feedback'
    | 'builder'
    | 'settings';
  showContent?: boolean;
  /** Render prop for injecting builder-specific items into the sidebar */
  builderSection?: (ctx: {
    isExpanded: boolean;
    navButtonClass: (active: boolean) => string;
    navButtonClassCollapsed: (active: boolean) => string;
    iconClass: (active: boolean) => string;
    labelClass: (active: boolean) => string;
    inactiveNavButton: string;
    inactiveNavButtonCollapsed: string;
    inactiveIconClass: string;
    inactiveLabelClass: string;
  }) => React.ReactNode;
  /** Called when the sidebar expanded state changes */
  onExpandedChange?: (expanded: boolean) => void;
  /** Force visible on all breakpoints (used by MobileMenu to bypass hidden md:flex) */
  forceVisible?: boolean;
}

// Recent activity item type
type RecentItem = {
  id: string;
  type: 'chat' | 'project';
  title: string;
  slug?: string;
  updatedAt: string;
};

function formatRelativeTime(dateStr: string): string {
  if (!dateStr) return '';
  const diffMs = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) return 'now';
  if (mins < 60) return `${mins}m`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d`;
  return new Date(dateStr).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

// Library sub-items for dropdown
// MoodyFace replaces the Agents icon — inherits color via currentColor,
// blinks gently on desktop, and respects prefers-reduced-motion.
type SidebarIconProps = { size?: number; className?: string };
const AgentFaceIcon = ({ size, className }: SidebarIconProps) => (
  <MoodyFace size={size ?? 14} className={className} animate />
);

const LIBRARY_ITEMS: Array<{
  key: string;
  label: string;
  icon: ComponentType<SidebarIconProps>;
}> = [
  { key: 'apps', label: 'Apps', icon: Boxes },
  { key: 'agents', label: 'Agents', icon: AgentFaceIcon },
  { key: 'bases', label: 'Bases', icon: Rocket },
  { key: 'skills', label: 'Skills', icon: Zap },
  { key: 'mcp_servers', label: 'Connectors', icon: Plug },
  { key: 'models', label: 'Models', icon: Cpu },
  { key: 'themes', label: 'Themes', icon: Palette },
];

export function NavigationSidebar({
  activePage,
  showContent = true,
  builderSection,
  onExpandedChange,
  forceVisible,
}: NavigationSidebarProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const [isExpanded, setIsExpanded] = useState(() => {
    const saved = localStorage.getItem('navigationSidebarExpanded');
    if (saved === null) return true;
    try {
      return JSON.parse(saved);
    } catch {
      return true;
    }
  });
  const [showShortcutsModal, setShowShortcutsModal] = useState(false);
  const [showHelpMenu, setShowHelpMenu] = useState(false);
  // Library flyout (#307 follow-up) — replaces the old inline collapsible.
  // Anchored to the Library button via getBoundingClientRect so it survives
  // the sidebar's overflow:hidden parent.
  const [libraryFlyout, setLibraryFlyout] = useState<{
    open: boolean;
    top: number;
    left: number;
  }>({ open: false, top: 0, left: 0 });
  const libraryButtonRef = useRef<HTMLDivElement>(null);
  const libraryFlyoutRef = useRef<HTMLDivElement>(null);
  const libraryCloseTimer = useRef<number | null>(null);

  const cancelLibraryClose = useCallback(() => {
    if (libraryCloseTimer.current !== null) {
      window.clearTimeout(libraryCloseTimer.current);
      libraryCloseTimer.current = null;
    }
  }, []);

  const openLibraryFlyout = useCallback(() => {
    cancelLibraryClose();
    const rect = libraryButtonRef.current?.getBoundingClientRect();
    if (!rect) return;
    setLibraryFlyout({
      open: true,
      top: rect.top,
      // 6px gap between sidebar edge and flyout to match the floating-panel feel.
      left: rect.right + 6,
    });
  }, [cancelLibraryClose]);

  const scheduleLibraryClose = useCallback(() => {
    cancelLibraryClose();
    libraryCloseTimer.current = window.setTimeout(() => {
      setLibraryFlyout((s) => ({ ...s, open: false }));
    }, 180);
  }, [cancelLibraryClose]);

  // Close on outside click / Escape.
  useEffect(() => {
    if (!libraryFlyout.open) return;
    const onClick = (e: MouseEvent) => {
      const t = e.target as Node;
      if (
        libraryButtonRef.current?.contains(t) ||
        libraryFlyoutRef.current?.contains(t)
      ) {
        return;
      }
      setLibraryFlyout((s) => ({ ...s, open: false }));
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setLibraryFlyout((s) => ({ ...s, open: false }));
    };
    document.addEventListener('mousedown', onClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [libraryFlyout.open]);

  // Reposition on window resize / scroll while open so the flyout
  // doesn't drift off the Library button.
  useEffect(() => {
    if (!libraryFlyout.open) return;
    const reposition = () => {
      const rect = libraryButtonRef.current?.getBoundingClientRect();
      if (!rect) return;
      setLibraryFlyout((s) => ({ ...s, top: rect.top, left: rect.right + 6 }));
    };
    window.addEventListener('resize', reposition);
    window.addEventListener('scroll', reposition, true);
    return () => {
      window.removeEventListener('resize', reposition);
      window.removeEventListener('scroll', reposition, true);
    };
  }, [libraryFlyout.open]);
  const [recentOpen, setRecentOpen] = useState(true);
  const [recentItems, setRecentItems] = useState<RecentItem[]>([]);
  const helpButtonRef = useRef<HTMLButtonElement>(null);
  const userDropdownRef = useRef<HTMLDivElement>(null);

  // Derive active library tab from URL
  const activeLibraryTab =
    activePage === 'library' ? new URLSearchParams(location.search).get('tab') || 'agents' : null;

  // Team + user profile state
  const { user, logout } = useAuth();
  const { activeTeam, teams, switchTeam, refreshTeams, can, teamSwitchKey } = useTeam();
  const canChat = can('chat.send');
  const subscriptionTier = activeTeam?.subscription_tier || 'free';
  const isPaidPlan = subscriptionTier !== 'free';
  const tierLabel = subscriptionTier.charAt(0).toUpperCase() + subscriptionTier.slice(1);
  const [showUserDropdown, setShowUserDropdown] = useState(false);
  const [creditBalance, setCreditBalance] = useState<CreditBalanceResponse | null>(null);
  const [imgError, setImgError] = useState(false);
  const [teamAvatarError, setTeamAvatarError] = useState(false);
  const [showCreateTeam, setShowCreateTeam] = useState(false);
  const [newTeamName, setNewTeamName] = useState('');
  const [creatingTeam, setCreatingTeam] = useState(false);
  const userName = user?.name || 'User';
  const totalCredits = creditBalance?.total_credits ?? 0;
  const avatarSrc = user?.avatar_url
    ? user.avatar_url
    : user?.id
      ? `https://api.dicebear.com/9.x/identicon/svg?seed=${user.id}`
      : null;

  useEffect(() => {
    setImgError(false);
  }, [avatarSrc]);
  useEffect(() => {
    setTeamAvatarError(false);
  }, [activeTeam?.avatar_url]);

  // Fetch credits
  useEffect(() => {
    billingApi
      .getCreditsBalance()
      .then(setCreditBalance)
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (showUserDropdown) {
      billingApi
        .getCreditsBalance()
        .then(setCreditBalance)
        .catch(() => {});
    }
  }, [showUserDropdown]);

  const handleCreditsUpdated = useCallback((e: Event) => {
    const detail = (e as CustomEvent).detail;
    if (typeof detail?.newBalance === 'number') {
      setCreditBalance((prev) => (prev ? { ...prev, total_credits: detail.newBalance } : prev));
    }
  }, []);

  useEffect(() => {
    window.addEventListener('credits-updated', handleCreditsUpdated);
    return () => window.removeEventListener('credits-updated', handleCreditsUpdated);
  }, [handleCreditsUpdated]);

  const handleCreateTeam = async () => {
    if (!newTeamName.trim()) return;
    setCreatingTeam(true);
    try {
      const slug = newTeamName
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-|-$/g, '');
      await teamsApi.create({ name: newTeamName.trim(), slug });
      await refreshTeams();
      setNewTeamName('');
      setShowCreateTeam(false);
      toast.success('Team created');
    } catch (error) {
      const err = error as { response?: { data?: { detail?: string } } };
      toast.error(err.response?.data?.detail || 'Failed to create team');
    } finally {
      setCreatingTeam(false);
    }
  };

  // Credit bar segments
  const GREY_SEGMENTS = [
    { key: 'daily_credits' as const, grey: 'rgba(255,255,255,0.06)' },
    { key: 'bundled_credits' as const, grey: 'rgba(255,255,255,0.10)' },
    { key: 'signup_bonus_credits' as const, grey: 'rgba(255,255,255,0.14)' },
  ];
  const capacity = creditBalance
    ? Math.max(creditBalance.monthly_allowance || 0, totalCredits, 1)
    : 1;
  const used = capacity - totalCredits;
  const usedPct = Math.min((used / capacity) * 100, 100);
  const greySegments = creditBalance
    ? GREY_SEGMENTS.map((s) => ({ ...s, value: creditBalance[s.key] || 0 })).filter(
        (s) => s.value > 0
      )
    : [];

  useEffect(() => {
    localStorage.setItem('navigationSidebarExpanded', JSON.stringify(isExpanded));
    onExpandedChange?.(isExpanded);
  }, [isExpanded, onExpandedChange]);

  // Fetch recent chats + projects for sidebar (refreshes on route change)
  useEffect(() => {
    let cancelled = false;
    Promise.all([
      chatApi.getUserSessions({ limit: 5 }).catch(() => ({ sessions: [] })),
      projectsApi.getAll().catch(() => []), // API returns all; sliced below
    ]).then(([chatData, projects]) => {
      if (cancelled) return;
      const chats: RecentItem[] = (
        (chatData as { sessions?: Array<Record<string, unknown>> }).sessions || []
      )
        .slice(0, 5)
        .map((s) => ({
          id: s.id as string,
          type: 'chat' as const,
          title: (s.title as string) || 'Untitled chat',
          updatedAt: (s.updated_at as string) || (s.created_at as string) || '',
        }));
      const projs: RecentItem[] = (projects as Array<Record<string, unknown>>)
        .map((p) => ({
          id: p.id as string,
          type: 'project' as const,
          title: (p.name as string) || 'Untitled project',
          slug: p.slug as string,
          updatedAt:
            (p.updated_at as string) || (p.created_at as string) || new Date(0).toISOString(),
        }))
        .sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime())
        .slice(0, 5);
      const merged = [...chats, ...projs]
        .sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime())
        .slice(0, 5);
      setRecentItems(merged);
    });
    return () => {
      cancelled = true;
    };
  }, [teamSwitchKey]); // Re-fetch when team changes

  const handleRecentClick = useCallback(
    (item: RecentItem) => {
      // Move clicked item to top immediately
      setRecentItems((prev) => {
        const key = `${item.type}-${item.id}`;
        const without = prev.filter((i) => `${i.type}-${i.id}` !== key);
        return [{ ...item, updatedAt: new Date().toISOString() }, ...without].slice(0, 5);
      });
      if (item.type === 'project') {
        navigate(`/project/${item.slug}/builder`);
      } else {
        navigate('/chat', { state: { sessionId: item.id } });
      }
    },
    [navigate]
  );

  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };

  // Shared button class for nav items — rounded-lg, 7px internal padding to keep icons at 18px from wall
  const navButtonClass = (isActive: boolean) =>
    `group flex items-center h-7 w-full transition-colors rounded-lg pl-[7px] pr-[7px] gap-3 ${
      isActive ? 'bg-[var(--sidebar-active)]' : 'hover:bg-[var(--sidebar-hover)]'
    }`;

  const navButtonClassCollapsed = (isActive: boolean) =>
    `group flex items-center justify-center h-7 w-full transition-colors rounded-lg ${
      isActive ? 'bg-[var(--sidebar-active)]' : 'hover:bg-[var(--sidebar-hover)]'
    }`;

  const inactiveNavButton =
    'group flex items-center h-7 w-full transition-colors rounded-lg pl-[7px] pr-[7px] gap-3 hover:bg-[var(--sidebar-hover)]';

  const inactiveNavButtonCollapsed =
    'group flex items-center justify-center h-7 w-full transition-colors rounded-lg hover:bg-[var(--sidebar-hover)]';

  const iconClass = (isActive: boolean) =>
    `transition-colors ${
      isActive
        ? 'text-[var(--sidebar-text)]'
        : 'text-[var(--text-subtle)] group-hover:text-[var(--sidebar-text)]'
    }`;

  const labelClass = (isActive: boolean) =>
    `text-[14px] font-medium transition-colors ${
      isActive
        ? 'text-[var(--sidebar-text)]'
        : 'text-[var(--text-muted)] group-hover:text-[var(--sidebar-text)]'
    }`;

  const inactiveIconClass =
    'text-[var(--text-subtle)] group-hover:text-[var(--sidebar-text)] transition-colors';

  const inactiveLabelClass =
    'text-[14px] font-medium text-[var(--text-muted)] group-hover:text-[var(--sidebar-text)] transition-colors';

  return (
    <motion.div
      initial={false}
      animate={{ width: isExpanded ? 244 : 48 }}
      transition={{
        duration: 0.25,
        ease: [0.22, 1, 0.36, 1],
      }}
      className={`${forceVisible ? 'flex' : 'hidden md:flex'} flex-col h-full bg-[var(--sidebar-bg)] overflow-x-hidden`}
    >
      {/* Team Switcher + Collapse toggle — top row */}
      <div
        ref={userDropdownRef}
        className={`flex-shrink-0 flex items-center gap-1 ${isExpanded ? '' : 'flex-col'}`}
        style={{ padding: '6px 11px 4px' }}
      >
        <Tooltip
          content={isExpanded ? 'Collapse sidebar' : 'Expand sidebar'}
          side="right"
          delay={200}
        >
          <button
            onClick={() => setIsExpanded(!isExpanded)}
            aria-label={isExpanded ? 'Collapse sidebar' : 'Expand sidebar'}
            className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-[var(--radius-small)] text-[var(--text-muted)] hover:bg-[var(--sidebar-hover)] hover:text-[var(--sidebar-text)] transition-colors"
          >
            <PanelLeft size={16} />
          </button>
        </Tooltip>
        <button
          onClick={() => setShowUserDropdown(!showUserDropdown)}
          className={`relative flex items-center h-10 rounded-[var(--radius-medium)] transition-colors ${isExpanded ? 'flex-1 min-w-0 gap-2.5 pl-[7px] pr-[7px]' : 'w-full justify-center'} ${
            showUserDropdown ? 'bg-[var(--sidebar-active)]' : 'hover:bg-[var(--sidebar-hover)]'
          }`}
          aria-label="Team menu"
        >
          {/* Team avatar */}
          {activeTeam?.avatar_url && !teamAvatarError ? (
            <img
              src={activeTeam.avatar_url}
              alt=""
              className="w-6 h-6 rounded-md object-cover flex-shrink-0"
              onError={() => setTeamAvatarError(true)}
            />
          ) : (
            <div className="w-6 h-6 rounded-md bg-[var(--primary)]/20 flex items-center justify-center text-[10px] font-bold text-[var(--primary)] flex-shrink-0">
              {activeTeam?.name?.charAt(0).toUpperCase() || 'T'}
            </div>
          )}
          {isExpanded && (
            <>
              <span className="text-xs font-medium text-[var(--sidebar-text)] truncate flex-1 text-left">
                {activeTeam?.name || 'Select Team'}
              </span>
              <CaretDown
                size={10}
                className={`text-[var(--text-subtle)] transition-transform flex-shrink-0 ${showUserDropdown ? 'rotate-180' : ''}`}
              />
            </>
          )}
        </button>

        {/* Team + User Dropdown — fixed position so it's not clipped by sidebar overflow */}
        {showUserDropdown && (
          <>
            <div
              className="fixed inset-0 z-40"
              onClick={() => {
                setShowUserDropdown(false);
                setShowCreateTeam(false);
                setNewTeamName('');
              }}
            />
            <div
              className="fixed w-56 max-h-[70vh] bg-[var(--surface)] border rounded-[var(--radius-medium)] z-50 overflow-y-auto overflow-x-hidden"
              style={{
                borderWidth: 'var(--border-width)',
                borderColor: 'var(--border-hover)',
                top: userDropdownRef.current
                  ? userDropdownRef.current.getBoundingClientRect().bottom + 2
                  : 52,
                left: userDropdownRef.current
                  ? userDropdownRef.current.getBoundingClientRect().left + 11
                  : 11,
                animation: 'team-dropdown-in 0.15s ease-out',
                transformOrigin: 'top left',
              }}
            >
              <div className="py-1">
                {/* Team list */}
                {teams.length > 0 && (
                  <>
                    <div className="px-3 py-1">
                      <span className="text-[10px] font-medium text-[var(--text-subtle)] uppercase tracking-wider">
                        Teams
                      </span>
                    </div>
                    {teams.map((team) => (
                      <button
                        key={team.slug}
                        onClick={async () => {
                          await switchTeam(team.slug);
                          setShowUserDropdown(false);
                          if (activePage === 'builder') navigate('/dashboard');
                        }}
                        className={`w-full flex items-center gap-2.5 px-3 py-1.5 transition-colors text-left ${
                          activeTeam?.slug === team.slug
                            ? 'bg-[var(--surface-hover)]'
                            : 'hover:bg-[var(--surface-hover)]'
                        }`}
                      >
                        {team.avatar_url ? (
                          <img
                            src={team.avatar_url}
                            alt=""
                            className="w-5 h-5 rounded-md object-cover flex-shrink-0"
                          />
                        ) : (
                          <div className="w-5 h-5 rounded-md bg-[var(--primary)]/20 flex items-center justify-center text-[9px] font-bold text-[var(--primary)] flex-shrink-0">
                            {team.name.charAt(0).toUpperCase()}
                          </div>
                        )}
                        <span
                          className={`text-[11px] truncate flex-1 ${
                            activeTeam?.slug === team.slug
                              ? 'font-medium text-[var(--text)]'
                              : 'text-[var(--text-muted)]'
                          }`}
                        >
                          {team.name}
                        </span>
                        {team.is_personal ? (
                          <span className="text-[9px] text-[#f89521] flex-shrink-0">Personal</span>
                        ) : team.role === 'admin' ? (
                          <span className="text-[9px] text-[var(--primary)] flex-shrink-0">
                            Admin
                          </span>
                        ) : team.role === 'editor' ? (
                          <span className="text-[9px] text-[var(--text)] flex-shrink-0">
                            Editor
                          </span>
                        ) : team.role === 'viewer' ? (
                          <span className="text-[9px] text-[var(--text-subtle)] flex-shrink-0">
                            Viewer
                          </span>
                        ) : null}
                      </button>
                    ))}
                    {/* Create Team */}
                    {!showCreateTeam ? (
                      <button
                        onClick={() => setShowCreateTeam(true)}
                        className="w-full flex items-center gap-2.5 px-3 py-1.5 hover:bg-[var(--surface-hover)] transition-colors text-left"
                      >
                        <div className="w-5 h-5 rounded-md border border-dashed border-[var(--border-hover)] flex items-center justify-center flex-shrink-0">
                          <Plus size={10} className="text-[var(--text-subtle)]" />
                        </div>
                        <span className="text-[11px] text-[var(--text-muted)]">Create Team</span>
                      </button>
                    ) : (
                      <div className="px-3 py-2 space-y-2">
                        <input
                          type="text"
                          value={newTeamName}
                          onChange={(e) => setNewTeamName(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') handleCreateTeam();
                            if (e.key === 'Escape') {
                              setShowCreateTeam(false);
                              setNewTeamName('');
                            }
                          }}
                          placeholder="Team name"
                          autoFocus
                          className="w-full px-2 py-1 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)] placeholder-[var(--text-subtle)]"
                        />
                        <div className="flex gap-1.5">
                          <button
                            onClick={handleCreateTeam}
                            disabled={creatingTeam || !newTeamName.trim()}
                            className="btn btn-filled btn-sm flex-1 disabled:opacity-50"
                          >
                            {creatingTeam ? 'Creating...' : 'Create'}
                          </button>
                          <button
                            onClick={() => {
                              setShowCreateTeam(false);
                              setNewTeamName('');
                            }}
                            className="btn btn-sm"
                          >
                            Cancel
                          </button>
                        </div>
                      </div>
                    )}

                    <div className="h-px bg-[var(--border)] mx-3 my-1" />
                  </>
                )}

                {/* Credits */}
                <button
                  onClick={() => {
                    setShowUserDropdown(false);
                    navigate('/settings/team/billing');
                  }}
                  className="w-full px-3 py-2 hover:bg-[var(--surface-hover)] transition-colors text-left"
                >
                  <div className="flex items-center gap-2">
                    <Coins size={14} className="text-[var(--primary)]" weight="fill" />
                    <div className="flex-1">
                      <div className="text-[11px] font-medium text-[var(--text)]">Credits</div>
                      <div className="text-[10px] text-[var(--text-muted)] tabular-nums">
                        {totalCredits.toLocaleString()} available
                      </div>
                    </div>
                  </div>
                  {creditBalance && (
                    <div className="flex h-1 rounded-full overflow-hidden mt-1.5 bg-[var(--border)]">
                      <div
                        className="h-full bg-[var(--primary)] transition-all duration-500 shrink-0"
                        style={{ width: `${usedPct}%` }}
                      />
                      {greySegments.map((seg) => (
                        <div
                          key={seg.key}
                          className="h-full transition-all duration-500"
                          style={{
                            width: `${(seg.value / capacity) * 100}%`,
                            backgroundColor: seg.grey,
                          }}
                        />
                      ))}
                    </div>
                  )}
                </button>

                <div className="h-px bg-[var(--border)] mx-3 my-0.5" />

                {/* User section */}
                <div className="px-3 py-1.5 flex items-center gap-2">
                  {avatarSrc && !imgError ? (
                    <img
                      src={avatarSrc}
                      alt=""
                      className="w-4 h-4 rounded-full object-cover flex-shrink-0"
                      referrerPolicy="no-referrer"
                      onError={() => setImgError(true)}
                    />
                  ) : (
                    <User
                      size={14}
                      className="text-[var(--text-subtle)] flex-shrink-0"
                      weight="fill"
                    />
                  )}
                  <span className="text-[10px] text-[var(--text-subtle)] truncate">{userName}</span>
                </div>

                <button
                  onClick={() => {
                    setShowUserDropdown(false);
                    navigate('/settings/team/billing');
                  }}
                  className="w-full flex items-center gap-2 px-3 py-1.5 hover:bg-[var(--surface-hover)] transition-colors text-left"
                >
                  <CreditCard size={14} className="text-[var(--text-subtle)]" />
                  <span className="text-[11px] text-[var(--text-muted)]">Subscriptions</span>
                </button>

                <button
                  onClick={() => {
                    setShowUserDropdown(false);
                    navigate('/settings');
                  }}
                  className="w-full flex items-center gap-2 px-3 py-1.5 hover:bg-[var(--surface-hover)] transition-colors text-left"
                >
                  <Gear size={14} className="text-[var(--text-subtle)]" />
                  <span className="text-[11px] text-[var(--text-muted)]">Settings</span>
                </button>

                <div className="h-px bg-[var(--border)] mx-3 my-0.5" />

                <button
                  onClick={() => {
                    setShowUserDropdown(false);
                    handleLogout();
                  }}
                  className="w-full flex items-center gap-2 px-3 py-1.5 hover:bg-[var(--surface-hover)] transition-colors text-left"
                >
                  <SignOut size={14} className="text-[var(--status-error)]" />
                  <span className="text-[11px] text-[var(--status-error)]">Logout</span>
                </button>
              </div>
            </div>
          </>
        )}
      </div>

      <motion.div
        className={`${activePage === 'builder' ? 'pt-0.5 pb-2' : 'py-2'} gap-0.5 flex flex-col flex-1 overflow-y-auto overflow-x-hidden`}
        style={isExpanded ? { paddingLeft: '11px', paddingRight: '11px' } : undefined}
        initial={{ opacity: 0 }}
        animate={{ opacity: showContent ? 1 : 0 }}
        transition={{ duration: 0.2, ease: 'easeOut' }}
      >
        {/* Standard Navigation Items — hidden in builder mode */}
        {activePage !== 'builder' && (
          <>
            <Tooltip content="Home" shortcut={`${modKey} H`} side="right" delay={200}>
              <button
                onClick={() => navigate('/home')}
                className={
                  isExpanded
                    ? navButtonClass(activePage === 'home')
                    : navButtonClassCollapsed(activePage === 'home')
                }
              >
                <Home size={16} className={iconClass(activePage === 'home')} />
                {isExpanded && <span className={labelClass(activePage === 'home')}>Home</span>}
              </button>
            </Tooltip>

            <Tooltip
              content={canChat ? 'Agents' : 'Agents (Restricted)'}
              shortcut={canChat ? `${modKey} J` : undefined}
              side="right"
              delay={200}
            >
              <button
                onClick={canChat ? () => navigate('/chat') : undefined}
                className={
                  isExpanded
                    ? navButtonClass(activePage === 'chat')
                    : navButtonClassCollapsed(activePage === 'chat')
                }
                style={!canChat ? { opacity: 0.35, cursor: 'not-allowed' } : undefined}
              >
                <MoodyFace size={16} animate className={iconClass(activePage === 'chat')} />
                {isExpanded && (
                  <span className={`${labelClass(activePage === 'chat')} flex items-center gap-1`}>
                    Agents
                    {!canChat && (
                      <span className="text-[9px] font-medium uppercase tracking-wider text-[var(--text-subtle)] opacity-60">
                        locked
                      </span>
                    )}
                  </span>
                )}
              </button>
            </Tooltip>

            <Tooltip content="Apps" side="right" delay={200}>
              <button
                onClick={() => navigate('/apps/installed')}
                className={
                  isExpanded
                    ? navButtonClass(activePage === 'apps')
                    : navButtonClassCollapsed(activePage === 'apps')
                }
              >
                <SquaresFour size={16} className={iconClass(activePage === 'apps')} />
                {isExpanded && (
                  <span className={labelClass(activePage === 'apps')}>Apps</span>
                )}
              </button>
            </Tooltip>

            <Tooltip content="Workspaces" shortcut={`${modKey} D`} side="right" delay={200}>
              <button
                onClick={() => navigate('/dashboard')}
                className={
                  isExpanded
                    ? navButtonClass(activePage === 'dashboard')
                    : navButtonClassCollapsed(activePage === 'dashboard')
                }
              >
                <FolderOpen size={16} className={iconClass(activePage === 'dashboard')} />
                {isExpanded && (
                  <span className={labelClass(activePage === 'dashboard')}>Workspaces</span>
                )}
              </button>
            </Tooltip>

            <Tooltip content="Marketplace" shortcut={`${modKey} M`} side="right" delay={200}>
              <button
                onClick={() => navigate('/marketplace?type=app')}
                className={
                  isExpanded
                    ? navButtonClass(activePage === 'marketplace')
                    : navButtonClassCollapsed(activePage === 'marketplace')
                }
              >
                <Package size={16} className={iconClass(activePage === 'marketplace')} />
                {isExpanded && (
                  <span className={labelClass(activePage === 'marketplace')}>Marketplace</span>
                )}
              </button>
            </Tooltip>

            {/* Library — flyout (#307 follow-up). Hover OR click opens a
                popover anchored to the right of the sidebar listing all
                library tabs; the sidebar itself never expands inline. */}
            <div
              ref={libraryButtonRef}
              onMouseEnter={openLibraryFlyout}
              onMouseLeave={scheduleLibraryClose}
            >
              {!isExpanded ? (
                <Tooltip content="Library" shortcut={`${modKey} L`} side="right" delay={200}>
                  <button
                    onClick={openLibraryFlyout}
                    className={navButtonClassCollapsed(activePage === 'library')}
                  >
                    <BookOpen size={16} className={iconClass(activePage === 'library')} />
                  </button>
                </Tooltip>
              ) : (
                <button
                  onClick={openLibraryFlyout}
                  className={navButtonClass(activePage === 'library')}
                >
                  <BookOpen
                    size={16}
                    className={`flex-shrink-0 ${iconClass(activePage === 'library')}`}
                  />
                  <span className={labelClass(activePage === 'library')}>Library</span>
                </button>
              )}
            </div>

            {/* Feedback and Docs moved to HelpMenu (sidebar "?" button) */}

            {/* Recent — collapsible, mixed chats + projects */}
            {recentItems.length > 0 &&
              (!isExpanded ? (
                <Tooltip content="Recent" side="right" delay={200}>
                  <button
                    onClick={() => {
                      setIsExpanded(true);
                      setRecentOpen(true);
                    }}
                    className={navButtonClassCollapsed(false)}
                  >
                    <Clock size={16} className={inactiveIconClass} />
                  </button>
                </Tooltip>
              ) : (
                <>
                  <div className="h-px bg-[var(--sidebar-border)] my-1 mx-3 flex-shrink-0" />
                  <button onClick={() => setRecentOpen(!recentOpen)} className={inactiveNavButton}>
                    <Clock size={16} className={`flex-shrink-0 ${inactiveIconClass}`} />
                    <span className={`${inactiveLabelClass} flex items-center gap-1`}>
                      Recent
                      <ChevronDown
                        size={10}
                        className={`transition-transform duration-200 text-[var(--text-subtle)] ${
                          recentOpen ? '' : '-rotate-90'
                        }`}
                      />
                    </span>
                  </button>
                  {recentOpen && (
                    <div className="flex flex-col gap-0.5 mt-0.5">
                      {recentItems.map((item) => (
                        <button
                          key={`${item.type}-${item.id}`}
                          onClick={() => handleRecentClick(item)}
                          className="group flex items-center h-7 w-full transition-colors rounded-lg pl-[7px] pr-[7px] gap-2 hover:bg-[var(--sidebar-hover)]"
                        >
                          <span className="text-[13px] text-[var(--text-muted)] group-hover:text-[var(--sidebar-text)] truncate flex-1 text-left transition-colors">
                            {item.title}
                          </span>
                          <span className="text-[10px] text-[var(--text-subtle)] tabular-nums flex-shrink-0">
                            {formatRelativeTime(item.updatedAt)}
                          </span>
                        </button>
                      ))}
                      <button
                        onClick={() => navigate('/dashboard')}
                        className="group flex items-center h-7 w-full transition-colors rounded-lg pl-[7px] pr-[7px] gap-2 hover:bg-[var(--sidebar-hover)]"
                      >
                        <span className="text-[11px] text-[var(--text-subtle)] group-hover:text-[var(--text-muted)] transition-colors">
                          See all →
                        </span>
                      </button>
                    </div>
                  )}
                </>
              ))}

            {/* Settings is accessed via user dropdown, not sidebar nav */}
          </>
        )}

        {/* Builder Section — injected when in builder view */}
        {builderSection && (
          <>
            <div className="h-px bg-[var(--sidebar-border)] my-0.5 mx-3 flex-shrink-0" />
            {builderSection({
              isExpanded,
              navButtonClass,
              navButtonClassCollapsed,
              iconClass,
              labelClass,
              inactiveNavButton,
              inactiveNavButtonCollapsed,
              inactiveIconClass,
              inactiveLabelClass,
            })}
          </>
        )}

        {/* Spacer to push bottom items down */}
        <div className="flex-1" />

        <div className="h-px bg-[var(--sidebar-border)] my-1.5 mx-3 flex-shrink-0" />

        {/* Help Button and Plan Badge */}
        {isExpanded ? (
          <div className="flex items-center gap-2 py-1 flex-shrink-0">
            <button
              ref={helpButtonRef}
              onClick={() => setShowHelpMenu(!showHelpMenu)}
              className={`group flex items-center justify-center w-8 h-8 rounded-full text-xs font-medium transition-colors ${
                showHelpMenu
                  ? 'bg-[var(--sidebar-active)] text-[var(--sidebar-text)]'
                  : 'bg-[var(--sidebar-hover)] hover:bg-[var(--sidebar-active)] text-[var(--text-muted)] hover:text-[var(--sidebar-text)]'
              }`}
            >
              ?
            </button>
            <button
              onClick={() => navigate('/settings/billing')}
              className={`flex-1 h-7 rounded-full text-xs font-medium transition-colors flex items-center justify-center gap-1.5 ${
                isPaidPlan
                  ? 'bg-orange-500/20 hover:bg-orange-500/30 text-orange-400 hover:text-orange-300'
                  : 'bg-[var(--sidebar-hover)] hover:bg-[var(--sidebar-active)] text-[var(--text-muted)] hover:text-[var(--sidebar-text)]'
              }`}
            >
              <ArrowUp size={12} strokeWidth={2} />
              {tierLabel} Plan
            </button>
          </div>
        ) : (
          <button
            ref={helpButtonRef}
            onClick={() => setShowHelpMenu(!showHelpMenu)}
            className={`group flex items-center justify-center h-9 w-full rounded-lg transition-colors flex-shrink-0 text-xs font-medium ${
              showHelpMenu
                ? 'bg-[var(--sidebar-active)] text-[var(--sidebar-text)]'
                : 'bg-[var(--sidebar-hover)] hover:bg-[var(--sidebar-active)] text-[var(--text-muted)] hover:text-[var(--sidebar-text)]'
            }`}
          >
            ?
          </button>
        )}
      </motion.div>

      {/* Help Menu */}
      <HelpMenu
        isOpen={showHelpMenu}
        onClose={() => setShowHelpMenu(false)}
        onOpenShortcuts={() => setShowShortcutsModal(true)}
        anchorRef={helpButtonRef}
      />

      {/* Keyboard Shortcuts Modal */}
      <KeyboardShortcutsModal
        open={showShortcutsModal}
        onClose={() => setShowShortcutsModal(false)}
      />

      {/* Library flyout — rendered via portal into document.body so it
          escapes the sidebar's animated motion.div (which sets a transform
          and traps even position:fixed children inside its containing
          block, then clips them with overflow-x-hidden).
          Entry animation is a gentle fade+slide (~220ms) so the popover
          doesn't snap in. */}
      {libraryFlyout.open &&
        createPortal(
          <motion.div
            ref={libraryFlyoutRef}
            onMouseEnter={cancelLibraryClose}
            onMouseLeave={scheduleLibraryClose}
            initial={{ opacity: 0, x: -6 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
            style={{
              position: 'fixed',
              top: libraryFlyout.top,
              left: libraryFlyout.left,
            }}
            className="z-50 w-56 bg-[var(--surface)] border border-[var(--border-hover)] rounded-[var(--radius-medium)] p-1.5 shadow-lg"
          >
            <div className="px-2 py-1 text-[10px] uppercase tracking-wider text-[var(--text-subtle)]">
              Library
            </div>
            {LIBRARY_ITEMS.map(({ key, label, icon: Icon }) => {
              const isActive = activeLibraryTab === key;
              return (
                <button
                  key={key}
                  onClick={() => {
                    navigate(`/library?tab=${key}`);
                    setLibraryFlyout((s) => ({ ...s, open: false }));
                  }}
                  className={`w-full text-left flex items-center gap-2 px-2 py-1.5 rounded-[var(--radius-small)] text-xs transition-colors ${
                    isActive
                      ? 'bg-[var(--surface-hover)] text-[var(--text)]'
                      : 'text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]'
                  }`}
                >
                  <Icon
                    size={14}
                    className={isActive ? 'text-[var(--text)]' : 'text-[var(--text-subtle)]'}
                  />
                  <span className="truncate">{label}</span>
                </button>
              );
            })}
          </motion.div>,
          document.body,
        )}
    </motion.div>
  );
}
