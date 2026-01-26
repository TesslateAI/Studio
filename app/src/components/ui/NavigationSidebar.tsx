import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Tooltip } from './Tooltip';
import { HelpMenu } from './HelpMenu';
import toast from 'react-hot-toast';
import { motion } from 'framer-motion';
import {
  FolderOpen,
  Store,
  Package,
  Settings,
  BookOpen,
  LogOut,
  ChevronLeft,
  ChevronRight,
  FileText,
  MessageCircle,
  ArrowUp
} from 'lucide-react';
import { KeyboardShortcutsModal } from '../KeyboardShortcutsModal';
import { billingApi } from '../../lib/api';
import { modKey } from '../../lib/keyboard-registry';

interface NavigationSidebarProps {
  activePage: 'dashboard' | 'marketplace' | 'library' | 'feedback';
  showContent?: boolean;
}

export function NavigationSidebar({ activePage, showContent = true }: NavigationSidebarProps) {
  const navigate = useNavigate();
  const [isExpanded, setIsExpanded] = useState(() => {
    const saved = localStorage.getItem('navigationSidebarExpanded');
    return saved !== null ? JSON.parse(saved) : true;
  });
  const [isPremium, setIsPremium] = useState(false);
  const [loadingSubscription, setLoadingSubscription] = useState(true);
  const [showShortcutsModal, setShowShortcutsModal] = useState(false);
  const [showHelpMenu, setShowHelpMenu] = useState(false);
  const helpButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    localStorage.setItem('navigationSidebarExpanded', JSON.stringify(isExpanded));
  }, [isExpanded]);

  useEffect(() => {
    // Check subscription status
    const checkSubscription = async () => {
      try {
        const subscription = await billingApi.getSubscription();
        setIsPremium(subscription.tier === 'pro');
      } catch (error) {
        console.error('Failed to check subscription:', error);
      } finally {
        setLoadingSubscription(false);
      }
    };
    checkSubscription();
  }, []);

  const logout = () => {
    localStorage.removeItem('token');
    navigate('/login');
  };

  // Shared button class for nav items
  const navButtonClass = (isActive: boolean) =>
    `group flex items-center h-9 w-full transition-colors rounded-lg px-3 gap-3 ${
      isActive ? 'bg-[var(--sidebar-active)]' : 'hover:bg-[var(--sidebar-hover)]'
    }`;

  const navButtonClassCollapsed = (isActive: boolean) =>
    `group flex items-center justify-center h-9 w-full transition-colors ${
      isActive ? 'bg-[var(--sidebar-active)]' : 'hover:bg-[var(--sidebar-hover)]'
    }`;

  const inactiveNavButton =
    'group flex items-center h-9 w-full transition-colors rounded-lg px-3 gap-3 hover:bg-[var(--sidebar-hover)]';

  const inactiveNavButtonCollapsed =
    'group flex items-center justify-center h-9 w-full transition-colors hover:bg-[var(--sidebar-hover)]';

  const iconClass = (isActive: boolean) =>
    `transition-colors ${
      isActive
        ? 'text-[var(--sidebar-text)]'
        : 'text-[var(--sidebar-text)]/40 group-hover:text-[var(--sidebar-text)]'
    }`;

  const inactiveIconClass =
    'text-[var(--sidebar-text)]/40 group-hover:text-[var(--sidebar-text)] transition-colors';

  return (
    <motion.div
      initial={false}
      animate={{ width: isExpanded ? 192 : 48 }}
      transition={{
        type: 'spring',
        stiffness: 700,
        damping: 28,
        mass: 0.4
      }}
      className="hidden md:flex flex-col h-screen bg-[var(--sidebar-bg)] border-r border-[var(--sidebar-border)] overflow-x-hidden"
    >
      {/* Tesslate Logo */}
      <div
        className={`flex items-center h-12 flex-shrink-0 ${isExpanded ? 'px-3 gap-3' : 'justify-center'} border-b border-[var(--sidebar-border)] bg-[var(--sidebar-bg)]`}
      >
        <svg className="w-5 h-5 text-[var(--primary)] flex-shrink-0" viewBox="0 0 161.9 126.66">
          <path
            d="m13.45,46.48h54.06c10.21,0,16.68-10.94,11.77-19.89l-9.19-16.75c-2.36-4.3-6.87-6.97-11.77-6.97H22.41c-4.95,0-9.5,2.73-11.84,7.09L1.61,26.71c-4.79,8.95,1.69,19.77,11.84,19.77Z"
            fill="currentColor"
          />
          <path
            d="m61.05,119.93l26.95-46.86c5.09-8.85-1.17-19.91-11.37-20.12l-19.11-.38c-4.9-.1-9.47,2.48-11.91,6.73l-17.89,31.12c-2.47,4.29-2.37,9.6.25,13.8l10.05,16.13c5.37,8.61,17.98,8.39,23.04-.41Z"
            fill="currentColor"
          />
          <path
            d="m148.46,0h-54.06c-10.21,0-16.68,10.94-11.77,19.89l9.19,16.75c2.36,4.3,6.87,6.97,11.77,6.97h35.9c4.95,0,9.5-2.73,11.84-7.09l8.97-16.75C165.08,10.82,158.6,0,148.46,0Z"
            fill="currentColor"
          />
        </svg>
        {isExpanded && <span className="text-lg font-bold text-[var(--sidebar-text)]">Tesslate</span>}
      </div>

      <motion.div
        className={`py-3 gap-1 flex flex-col flex-1 overflow-y-auto overflow-x-hidden ${isExpanded ? 'px-2' : ''}`}
        initial={{ opacity: 0 }}
        animate={{ opacity: showContent ? 1 : 0 }}
        transition={{ duration: 0.4, ease: 'easeOut' }}
      >
        {/* Navigation Items */}
        <Tooltip content="Projects" shortcut={`${modKey} D`} side="right" delay={200}>
          <button
            onClick={() => navigate('/dashboard')}
            className={isExpanded ? navButtonClass(activePage === 'dashboard') : navButtonClassCollapsed(activePage === 'dashboard')}
          >
            <FolderOpen size={18} className={iconClass(activePage === 'dashboard')} />
            {isExpanded && <span className="text-sm font-medium text-[var(--sidebar-text)]">Projects</span>}
          </button>
        </Tooltip>

        <Tooltip content="Marketplace" shortcut={`${modKey} M`} side="right" delay={200}>
          <button
            onClick={() => navigate('/marketplace')}
            className={isExpanded ? navButtonClass(activePage === 'marketplace') : navButtonClassCollapsed(activePage === 'marketplace')}
          >
            <Store size={18} className={iconClass(activePage === 'marketplace')} />
            {isExpanded && <span className="text-sm font-medium text-[var(--sidebar-text)]">Marketplace</span>}
          </button>
        </Tooltip>

        <Tooltip content="Library" shortcut={`${modKey} L`} side="right" delay={200}>
          <button
            onClick={() => navigate('/library')}
            className={isExpanded ? navButtonClass(activePage === 'library') : navButtonClassCollapsed(activePage === 'library')}
          >
            <BookOpen size={18} className={iconClass(activePage === 'library')} />
            {isExpanded && <span className="text-sm font-medium text-[var(--sidebar-text)]">Library</span>}
          </button>
        </Tooltip>

        <Tooltip content="Feedback" side="right" delay={200}>
          <button
            onClick={() => navigate('/feedback')}
            className={isExpanded ? navButtonClass(activePage === 'feedback') : navButtonClassCollapsed(activePage === 'feedback')}
          >
            <MessageCircle size={18} className={iconClass(activePage === 'feedback')} />
            {isExpanded && <span className="text-sm font-medium text-[var(--sidebar-text)]">Feedback</span>}
          </button>
        </Tooltip>

        <Tooltip content="Components" side="right" delay={200}>
          <button
            onClick={() => toast('Components library coming soon!')}
            className={isExpanded ? inactiveNavButton : inactiveNavButtonCollapsed}
          >
            <Package size={18} className={inactiveIconClass} />
            {isExpanded && <span className="text-sm font-medium text-[var(--sidebar-text)]">Components</span>}
          </button>
        </Tooltip>

        <Tooltip content="Documentation" side="right" delay={200}>
          <a
            href="https://docs.tesslate.com"
            target="_blank"
            rel="noopener noreferrer"
            className={isExpanded ? inactiveNavButton : inactiveNavButtonCollapsed}
          >
            <FileText size={18} className={inactiveIconClass} />
            {isExpanded && <span className="text-sm font-medium text-[var(--sidebar-text)]">Documentation</span>}
          </a>
        </Tooltip>

        <div className="h-px bg-[var(--sidebar-border)] my-1 flex-shrink-0" />

        <Tooltip content="Settings" shortcut={`${modKey} ,`} side="right" delay={200}>
          <button
            onClick={() => navigate('/settings')}
            className={isExpanded ? inactiveNavButton : inactiveNavButtonCollapsed}
          >
            <Settings size={18} className={inactiveIconClass} />
            {isExpanded && <span className="text-sm font-medium text-[var(--sidebar-text)]">Settings</span>}
          </button>
        </Tooltip>

        <Tooltip content="Logout" side="right" delay={200}>
          <button
            onClick={logout}
            className={isExpanded ? inactiveNavButton : inactiveNavButtonCollapsed}
          >
            <LogOut size={18} className={inactiveIconClass} />
            {isExpanded && <span className="text-sm font-medium text-[var(--sidebar-text)]">Logout</span>}
          </button>
        </Tooltip>

        {/* Spacer to push bottom items down */}
        <div className="flex-1" />

        <div className="h-px bg-[var(--sidebar-border)] my-1 flex-shrink-0" />

        {/* Help Button and Plan Badge */}
        {isExpanded ? (
          <div className="flex items-center gap-2 py-1 flex-shrink-0">
            <button
              ref={helpButtonRef}
              onClick={() => setShowHelpMenu(!showHelpMenu)}
              className={`group flex items-center justify-center w-8 h-8 rounded-full border text-sm font-medium transition-colors ${
                showHelpMenu
                  ? 'bg-[var(--sidebar-text)]/10 border-[var(--sidebar-text)]/40 text-[var(--sidebar-text)]'
                  : 'border-[var(--sidebar-text)]/20 hover:border-[var(--sidebar-text)]/40 hover:bg-[var(--sidebar-text)]/10 text-[var(--sidebar-text)]/60 hover:text-[var(--sidebar-text)]'
              }`}
            >
              ?
            </button>
            <button
              onClick={() => navigate('/billing/plans')}
              className="flex-1 h-8 rounded-full bg-[var(--sidebar-hover)] hover:bg-[var(--sidebar-active)] text-[var(--sidebar-text)]/70 hover:text-[var(--sidebar-text)] text-sm font-medium transition-colors flex items-center justify-center gap-1.5"
            >
              <ArrowUp size={14} strokeWidth={2} />
              {isPremium ? 'Pro plan' : 'Free plan'}
            </button>
          </div>
        ) : (
          <button
            ref={helpButtonRef}
            onClick={() => setShowHelpMenu(!showHelpMenu)}
            className={`group flex items-center justify-center h-9 w-full transition-colors flex-shrink-0 text-sm font-medium ${
              showHelpMenu
                ? 'bg-[var(--sidebar-hover)] text-[var(--sidebar-text)]'
                : 'hover:bg-[var(--sidebar-hover)] text-[var(--sidebar-text)]/40 hover:text-[var(--sidebar-text)]'
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
              <ChevronLeft size={18} className={inactiveIconClass} />
            ) : (
              <ChevronRight size={18} className={inactiveIconClass} />
            )}
            {isExpanded && <span className="text-sm font-medium text-[var(--sidebar-text)]">Collapse</span>}
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
      <KeyboardShortcutsModal open={showShortcutsModal} onClose={() => setShowShortcutsModal(false)} />
    </motion.div>
  );
}
