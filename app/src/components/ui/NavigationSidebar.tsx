import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Tooltip } from './Tooltip';
import { HelpMenu } from './HelpMenu';
import { motion } from 'framer-motion';
import {
  FolderOpen,
  Store,
  Settings,
  BookOpen,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  FileText,
  MessageCircle,
  ArrowUp,
  Cpu,
  Palette,
  Zap,
  Plug,
  Rocket,
  Package,
} from 'lucide-react';
import { User, CaretDown, Coins, CreditCard, Gear, SignOut } from '@phosphor-icons/react';
import { KeyboardShortcutsModal } from '../KeyboardShortcutsModal';
import { billingApi } from '../../lib/api';
import { useAuth } from '../../contexts/AuthContext';
import { modKey } from '../../lib/keyboard-registry';
import type { CreditBalanceResponse } from '../../types/billing';

interface NavigationSidebarProps {
  activePage: 'dashboard' | 'marketplace' | 'library' | 'feedback' | 'builder' | 'settings';
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

// Library sub-items for dropdown
const LIBRARY_ITEMS = [
  { key: 'agents', label: 'Agents', icon: Package },
  { key: 'bases', label: 'Bases', icon: Rocket },
  { key: 'skills', label: 'Skills', icon: Zap },
  { key: 'mcp_servers', label: 'MCP Servers', icon: Plug },
  { key: 'models', label: 'Models', icon: Cpu },
  { key: 'themes', label: 'Themes', icon: Palette },
] as const;

export function NavigationSidebar({ activePage, showContent = true, builderSection, onExpandedChange, forceVisible }: NavigationSidebarProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const [isExpanded, setIsExpanded] = useState(() => {
    const saved = localStorage.getItem('navigationSidebarExpanded');
    return saved !== null ? JSON.parse(saved) : true;
  });
  const [subscriptionTier, setSubscriptionTier] = useState<string>('free');
  const [showShortcutsModal, setShowShortcutsModal] = useState(false);
  const [showHelpMenu, setShowHelpMenu] = useState(false);
  const [libraryOpen, setLibraryOpen] = useState(() => activePage === 'library');
  const helpButtonRef = useRef<HTMLButtonElement>(null);
  const userDropdownRef = useRef<HTMLDivElement>(null);

  // Auto-expand Library dropdown when navigating to library
  useEffect(() => {
    if (activePage === 'library') setLibraryOpen(true);
  }, [activePage]);

  // Derive active library tab from URL
  const activeLibraryTab = activePage === 'library'
    ? (new URLSearchParams(location.search).get('tab') || 'agents')
    : null;

  const isPaidPlan = subscriptionTier !== 'free';
  const tierLabel = subscriptionTier.charAt(0).toUpperCase() + subscriptionTier.slice(1);

  // User profile state
  const { user } = useAuth();
  const [showUserDropdown, setShowUserDropdown] = useState(false);
  const [creditBalance, setCreditBalance] = useState<CreditBalanceResponse | null>(null);
  const [imgError, setImgError] = useState(false);
  const userName = user?.name || 'User';
  const totalCredits = creditBalance?.total_credits ?? 0;
  const avatarSrc = user?.avatar_url
    ? user.avatar_url
    : user?.id
      ? `https://api.dicebear.com/9.x/identicon/svg?seed=${user.id}`
      : null;

  useEffect(() => { setImgError(false); }, [avatarSrc]);

  // Fetch credits
  useEffect(() => {
    billingApi.getCreditsBalance().then(setCreditBalance).catch(() => {});
  }, []);

  useEffect(() => {
    if (showUserDropdown) {
      billingApi.getCreditsBalance().then(setCreditBalance).catch(() => {});
    }
  }, [showUserDropdown]);

  const handleCreditsUpdated = useCallback((e: Event) => {
    const detail = (e as CustomEvent).detail;
    if (typeof detail?.newBalance === 'number') {
      setCreditBalance((prev) => prev ? { ...prev, total_credits: detail.newBalance } : prev);
    }
  }, []);

  useEffect(() => {
    window.addEventListener('credits-updated', handleCreditsUpdated);
    return () => window.removeEventListener('credits-updated', handleCreditsUpdated);
  }, [handleCreditsUpdated]);

  // Credit bar segments
  const GREY_SEGMENTS = [
    { key: 'daily_credits' as const, grey: 'rgba(255,255,255,0.06)' },
    { key: 'bundled_credits' as const, grey: 'rgba(255,255,255,0.10)' },
    { key: 'signup_bonus_credits' as const, grey: 'rgba(255,255,255,0.14)' },
  ];
  const capacity = creditBalance ? Math.max(creditBalance.monthly_allowance || 0, totalCredits, 1) : 1;
  const used = capacity - totalCredits;
  const usedPct = Math.min((used / capacity) * 100, 100);
  const greySegments = creditBalance
    ? GREY_SEGMENTS.map((s) => ({ ...s, value: creditBalance[s.key] || 0 })).filter((s) => s.value > 0)
    : [];

  useEffect(() => {
    localStorage.setItem('navigationSidebarExpanded', JSON.stringify(isExpanded));
    onExpandedChange?.(isExpanded);
  }, [isExpanded, onExpandedChange]);

  useEffect(() => {
    // Check subscription status
    const checkSubscription = async () => {
      try {
        const subscription = await billingApi.getSubscription();
        setSubscriptionTier(subscription.tier || 'free');
      } catch (error) {
        console.error('Failed to check subscription:', error);
      }
    };
    checkSubscription();
  }, []);

  const logout = () => {
    localStorage.removeItem('token');
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
    `text-xs font-medium transition-colors ${
      isActive
        ? 'text-[var(--sidebar-text)]'
        : 'text-[var(--text-muted)] group-hover:text-[var(--sidebar-text)]'
    }`;

  const inactiveIconClass =
    'text-[var(--text-subtle)] group-hover:text-[var(--sidebar-text)] transition-colors';

  const inactiveLabelClass =
    'text-xs font-medium text-[var(--text-muted)] group-hover:text-[var(--sidebar-text)] transition-colors';

  // Sub-item styles for Library dropdown children
  // Sub-items indented under Library parent
  const subItemClass = (isActive: boolean) =>
    `group flex items-center h-7 w-full transition-colors rounded-lg pl-[26px] pr-[7px] gap-2.5 ${
      isActive ? 'bg-[var(--sidebar-active)]' : 'hover:bg-[var(--sidebar-hover)]'
    }`;

  const subItemIconClass = (isActive: boolean) =>
    `transition-colors flex-shrink-0 ${
      isActive
        ? 'text-[var(--sidebar-text)]'
        : 'text-[var(--text-subtle)] group-hover:text-[var(--sidebar-text)]'
    }`;

  const subItemLabelClass = (isActive: boolean) =>
    `text-[11px] font-medium transition-colors ${
      isActive
        ? 'text-[var(--sidebar-text)]'
        : 'text-[var(--text-muted)] group-hover:text-[var(--sidebar-text)]'
    }`;

  return (
    <motion.div
      initial={false}
      animate={{ width: isExpanded ? 244 : 48 }}
      transition={{
        duration: 0.25,
        ease: [0.22, 1, 0.36, 1],
      }}
      className={`${forceVisible ? 'flex' : 'hidden md:flex'} flex-col h-screen bg-[var(--sidebar-bg)] overflow-x-hidden`}
    >
      {/* User Profile Area — replaces logo */}
      <div ref={userDropdownRef} className="flex-shrink-0" style={{ paddingTop: '6px' }}>
        <button
          onClick={() => setShowUserDropdown(!showUserDropdown)}
          className={`relative flex items-center h-10 rounded-[var(--radius-medium)] transition-colors ${isExpanded ? 'gap-2.5 mx-2' : 'justify-center mx-1'} ${
            showUserDropdown
              ? 'bg-[var(--sidebar-active)]'
              : 'hover:bg-[var(--sidebar-hover)]'
          }`}
          style={isExpanded ? { paddingLeft: '10px', paddingRight: '8px' } : undefined}
          aria-label="User menu"
        >
          {avatarSrc && !imgError ? (
            <img
              src={avatarSrc}
              alt=""
              className="w-6 h-6 rounded-full object-cover flex-shrink-0"
              referrerPolicy="no-referrer"
              onError={() => setImgError(true)}
            />
          ) : (
            <User size={18} className="text-[var(--text-muted)] flex-shrink-0" weight="fill" />
          )}
          {isExpanded && (
            <>
              <span className="text-xs font-medium text-[var(--sidebar-text)] truncate flex-1 text-left">{userName}</span>
              <CaretDown
                size={10}
                className={`text-[var(--text-subtle)] transition-transform flex-shrink-0 ${showUserDropdown ? 'rotate-180' : ''}`}
              />
            </>
          )}
        </button>

        {/* User Dropdown Menu — fixed position so it's not clipped by sidebar overflow */}
        {showUserDropdown && (
          <>
            <div className="fixed inset-0 z-40" onClick={() => setShowUserDropdown(false)} />
            <div
              className="fixed w-52 bg-[var(--surface)] border rounded-[var(--radius-medium)] z-50 overflow-hidden"
              style={{
                borderWidth: 'var(--border-width)',
                borderColor: 'var(--border-hover)',
                top: userDropdownRef.current ? userDropdownRef.current.getBoundingClientRect().bottom + 4 : 52,
                left: userDropdownRef.current ? userDropdownRef.current.getBoundingClientRect().left : 8,
              }}
            >
              <div className="py-1">
                {/* Credits */}
                <button
                  onClick={() => { setShowUserDropdown(false); navigate('/settings/billing'); }}
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
                      <div className="h-full bg-[var(--primary)] transition-all duration-500 shrink-0" style={{ width: `${usedPct}%` }} />
                      {greySegments.map((seg) => (
                        <div key={seg.key} className="h-full transition-all duration-500" style={{ width: `${(seg.value / capacity) * 100}%`, backgroundColor: seg.grey }} />
                      ))}
                    </div>
                  )}
                </button>

                <div className="h-px bg-[var(--border)] mx-3 my-0.5" />

                <button
                  onClick={() => { setShowUserDropdown(false); navigate('/settings/billing'); }}
                  className="w-full flex items-center gap-2 px-3 py-1.5 hover:bg-[var(--surface-hover)] transition-colors text-left"
                >
                  <CreditCard size={14} className="text-[var(--text-subtle)]" />
                  <span className="text-[11px] text-[var(--text-muted)]">Subscriptions</span>
                </button>

                <button
                  onClick={() => { setShowUserDropdown(false); navigate('/settings'); }}
                  className="w-full flex items-center gap-2 px-3 py-1.5 hover:bg-[var(--surface-hover)] transition-colors text-left"
                >
                  <Gear size={14} className="text-[var(--text-subtle)]" />
                  <span className="text-[11px] text-[var(--text-muted)]">Settings</span>
                </button>

                <div className="h-px bg-[var(--border)] mx-3 my-0.5" />

                <button
                  onClick={() => { setShowUserDropdown(false); logout(); }}
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
            <Tooltip content="Projects" shortcut={`${modKey} D`} side="right" delay={200}>
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
                  <span className={labelClass(activePage === 'dashboard')}>Projects</span>
                )}
              </button>
            </Tooltip>

            <Tooltip content="Marketplace" shortcut={`${modKey} M`} side="right" delay={200}>
              <button
                onClick={() => navigate('/marketplace')}
                className={
                  isExpanded
                    ? navButtonClass(activePage === 'marketplace')
                    : navButtonClassCollapsed(activePage === 'marketplace')
                }
              >
                <Store size={16} className={iconClass(activePage === 'marketplace')} />
                {isExpanded && (
                  <span className={labelClass(activePage === 'marketplace')}>Marketplace</span>
                )}
              </button>
            </Tooltip>

            {/* Library — collapsible dropdown */}
            {!isExpanded ? (
              <Tooltip content="Library" shortcut={`${modKey} L`} side="right" delay={200}>
                <button
                  onClick={() => {
                    setIsExpanded(true);
                    setLibraryOpen(true);
                  }}
                  className={navButtonClassCollapsed(activePage === 'library')}
                >
                  <BookOpen size={16} className={iconClass(activePage === 'library')} />
                </button>
              </Tooltip>
            ) : (
              <>
                <button
                  onClick={() => setLibraryOpen(!libraryOpen)}
                  className={navButtonClass(activePage === 'library')}
                >
                  <BookOpen size={16} className={`flex-shrink-0 ${iconClass(activePage === 'library')}`} />
                  <span className={`${labelClass(activePage === 'library')} flex items-center gap-1`}>
                    Library
                    <ChevronDown
                      size={10}
                      className={`transition-transform duration-200 text-[var(--text-subtle)] ${
                        libraryOpen ? '' : '-rotate-90'
                      }`}
                    />
                  </span>
                </button>

                {/* Library sub-items */}
                {libraryOpen && (
                  <div className="flex flex-col gap-0.5 mt-0.5">
                    {LIBRARY_ITEMS.map(({ key, label, icon: Icon }) => (
                      <button
                        key={key}
                        onClick={() => navigate(`/library?tab=${key}`)}
                        className={subItemClass(activeLibraryTab === key)}
                      >
                        <Icon size={14} className={subItemIconClass(activeLibraryTab === key)} />
                        <span className={subItemLabelClass(activeLibraryTab === key)}>{label}</span>
                      </button>
                    ))}
                  </div>
                )}
              </>
            )}

            <Tooltip content="Feedback" side="right" delay={200}>
              <button
                onClick={() => navigate('/feedback')}
                className={
                  isExpanded
                    ? navButtonClass(activePage === 'feedback')
                    : navButtonClassCollapsed(activePage === 'feedback')
                }
              >
                <MessageCircle size={16} className={iconClass(activePage === 'feedback')} />
                {isExpanded && (
                  <span className={labelClass(activePage === 'feedback')}>Feedback</span>
                )}
              </button>
            </Tooltip>

            <Tooltip content="Documentation" side="right" delay={200}>
              <a
                href="https://docs.tesslate.com"
                target="_blank"
                rel="noopener noreferrer"
                className={isExpanded ? inactiveNavButton : inactiveNavButtonCollapsed}
              >
                <FileText size={16} className={inactiveIconClass} />
                {isExpanded && (
                  <span className={inactiveLabelClass}>Documentation</span>
                )}
              </a>
            </Tooltip>

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
              className={`group flex items-center justify-center w-7 h-7 rounded-full border text-xs font-medium transition-colors ${
                showHelpMenu
                  ? 'bg-[var(--sidebar-active)] border-[var(--text-muted)] text-[var(--sidebar-text)]'
                  : 'border-[var(--sidebar-border)] hover:border-[var(--text-muted)] hover:bg-[var(--sidebar-hover)] text-[var(--text-muted)] hover:text-[var(--sidebar-text)]'
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
              {tierLabel}
            </button>
          </div>
        ) : (
          <button
            ref={helpButtonRef}
            onClick={() => setShowHelpMenu(!showHelpMenu)}
            className={`group flex items-center justify-center h-8 w-full transition-colors flex-shrink-0 text-xs font-medium ${
              showHelpMenu
                ? 'bg-[var(--sidebar-hover)] text-[var(--sidebar-text)]'
                : 'hover:bg-[var(--sidebar-hover)] text-[var(--text-muted)] hover:text-[var(--sidebar-text)]'
            }`}
          >
            ?
          </button>
        )}

        {/* Collapse/Expand Toggle */}
        <Tooltip content={isExpanded ? 'Collapse' : 'Expand'} side="right" delay={200}>
          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className={isExpanded ? inactiveNavButton : inactiveNavButtonCollapsed}
          >
            {isExpanded ? (
              <ChevronLeft size={16} className={inactiveIconClass} />
            ) : (
              <ChevronRight size={16} className={inactiveIconClass} />
            )}
            {isExpanded && (
              <span className={inactiveLabelClass}>Collapse</span>
            )}
          </button>
        </Tooltip>
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
    </motion.div>
  );
}
