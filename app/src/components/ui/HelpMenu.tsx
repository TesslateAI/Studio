import { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Search,
  MessageCircle,
  FileText,
  Settings,
  Keyboard,
  ExternalLink,
  ChevronRight,
  Users,
  Smartphone,
  Activity,
} from 'lucide-react';
import { DiscordLogo } from '@phosphor-icons/react';
import { modKey } from '../../lib/keyboard-registry';

interface HelpMenuProps {
  isOpen: boolean;
  onClose: () => void;
  onOpenShortcuts: () => void;
  anchorRef: React.RefObject<HTMLButtonElement | null>;
}

export function HelpMenu({ isOpen, onClose, onOpenShortcuts, anchorRef }: HelpMenuProps) {
  const navigate = useNavigate();
  const menuRef = useRef<HTMLDivElement>(null);
  const moreMenuRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState({ top: 0, left: 0 });
  const [showMoreMenu, setShowMoreMenu] = useState(false);
  const [moreMenuPosition, setMoreMenuPosition] = useState({ top: 0, left: 0 });
  const moreButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (isOpen && anchorRef.current) {
      const rect = anchorRef.current.getBoundingClientRect();
      setPosition({
        top: rect.top - 8,
        left: rect.right + 8,
      });
    }
    // Reset more menu when main menu closes
    if (!isOpen) {
      setShowMoreMenu(false);
    }
  }, [isOpen, anchorRef]);

  useEffect(() => {
    if (showMoreMenu && moreButtonRef.current && menuRef.current) {
      const buttonRect = moreButtonRef.current.getBoundingClientRect();
      const menuRect = menuRef.current.getBoundingClientRect();
      setMoreMenuPosition({
        top: buttonRect.top,
        left: menuRect.right + 4,
      });
    }
  }, [showMoreMenu]);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      const target = event.target as Node;
      if (
        menuRef.current &&
        !menuRef.current.contains(target) &&
        anchorRef.current &&
        !anchorRef.current.contains(target) &&
        (!moreMenuRef.current || !moreMenuRef.current.contains(target))
      ) {
        onClose();
      }
    };

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose();
      }
    };

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
      document.addEventListener('keydown', handleEscape);
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [isOpen, onClose, anchorRef]);

  if (!isOpen) return null;

  const menuItems = [
    {
      icon: Search,
      label: 'Search for help...',
      onClick: () => {
        window.open('https://docs.tesslate.com', '_blank');
        onClose();
      },
    },
    {
      icon: MessageCircle,
      label: 'Contact us',
      onClick: () => {
        navigate('/feedback');
        onClose();
      },
    },
    {
      icon: FileText,
      label: 'Docs',
      external: true,
      onClick: () => {
        window.open('https://docs.tesslate.com', '_blank');
        onClose();
      },
    },
    {
      icon: Settings,
      label: 'Settings',
      shortcut: 'G then S',
      onClick: () => {
        navigate('/settings');
        onClose();
      },
    },
  ];

  const discordItem = {
    label: 'Discord Support',
    onClick: () => {
      window.open('https://discord.gg/WgXabcN2r2', '_blank');
      onClose();
    },
  };

  const moreMenuItems = [
    {
      icon: Keyboard,
      label: 'Shortcuts',
      shortcut: `${modKey} /`,
      onClick: () => {
        onOpenShortcuts();
        onClose();
      },
    },
    {
      icon: Users,
      label: 'Community',
      external: true,
      onClick: () => {
        window.open('https://discord.gg/WgXabcN2r2', '_blank');
        onClose();
      },
    },
    {
      icon: Smartphone,
      label: 'Mobile App',
      external: true,
      onClick: () => {
        window.open('https://tesslate.com/mobile', '_blank');
        onClose();
      },
    },
    {
      icon: Activity,
      label: 'System status',
      external: true,
      onClick: () => {
        window.open('https://status.tesslate.com', '_blank');
        onClose();
      },
    },
  ];

  const whatsNew = [
    {
      label: 'News',
      external: true,
      url: 'https://tesslate.com/news',
    },
    {
      label: 'Full changelog',
      external: true,
      url: 'https://tesslate.com/changelog',
    },
  ];

  return (
    <>
      {/* Main Menu */}
      <div
        ref={menuRef}
        className="fixed z-50 w-56 bg-[var(--surface)] border border-[var(--sidebar-border)] rounded-lg shadow-xl overflow-hidden"
        style={{ top: position.top, left: position.left, transform: 'translateY(-100%)' }}
      >
        {/* Main Menu Items */}
        <div className="p-1">
          {menuItems.map((item, index) => (
            <button
              key={index}
              onClick={item.onClick}
              className="w-full flex items-center gap-3 px-3 py-2 text-sm text-[var(--text)]/80 hover:text-[var(--text)] hover:bg-[var(--sidebar-hover)] rounded-md transition-colors"
            >
              <item.icon size={16} className="text-[var(--text)]/50" />
              <span className="flex-1 text-left">{item.label}</span>
              {item.external && <ExternalLink size={12} className="text-[var(--text)]/40" />}
              {item.shortcut && (
                <span className="text-xs text-[var(--text)]/40 font-mono">{item.shortcut}</span>
              )}
            </button>
          ))}
        </div>

        {/* Discord Support */}
        <div className="border-t border-[var(--sidebar-border)] p-1">
          <button
            onClick={discordItem.onClick}
            className="w-full flex items-center gap-3 px-3 py-2 text-sm text-[#5865F2] hover:text-white hover:bg-[#5865F2]/20 rounded-md transition-colors"
          >
            <DiscordLogo size={16} weight="fill" />
            <span className="flex-1 text-left">{discordItem.label}</span>
            <ExternalLink size={12} className="text-[var(--text)]/40" />
          </button>
        </div>

        {/* More Section */}
        <div className="border-t border-[var(--sidebar-border)] p-1">
          <button
            ref={moreButtonRef}
            onMouseEnter={() => setShowMoreMenu(true)}
            onClick={() => setShowMoreMenu(!showMoreMenu)}
            className={`w-full flex items-center gap-3 px-3 py-2 text-sm rounded-md transition-colors ${
              showMoreMenu
                ? 'bg-[var(--sidebar-hover)] text-[var(--text)]'
                : 'text-[var(--text)]/80 hover:text-[var(--text)] hover:bg-[var(--sidebar-hover)]'
            }`}
          >
            <span className="text-[var(--text)]/50">•••</span>
            <span className="flex-1 text-left">More</span>
            <ChevronRight size={14} className="text-[var(--text)]/40" />
          </button>
        </div>

        {/* What's New Section */}
        <div className="border-t border-[var(--sidebar-border)]">
          <div className="px-3 py-2">
            <span className="text-xs text-[var(--text)]/40 font-medium">What's new</span>
          </div>
          <div className="p-1 pt-0">
            {whatsNew.map((item, index) => (
              <button
                key={index}
                onClick={() => {
                  window.open(item.url, '_blank');
                  onClose();
                }}
                className="w-full flex items-center gap-3 px-3 py-2 text-sm text-[var(--text)]/80 hover:text-[var(--text)] hover:bg-[var(--sidebar-hover)] rounded-md transition-colors"
              >
                <span className="w-4 h-4 flex items-center justify-center text-[var(--text)]/30">
                  •
                </span>
                <span className="flex-1 text-left">{item.label}</span>
                {item.external && <ExternalLink size={12} className="text-[var(--text)]/40" />}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* More Submenu */}
      {showMoreMenu && (
        <div
          ref={moreMenuRef}
          className="fixed z-50 w-48 bg-[var(--surface)] border border-[var(--sidebar-border)] rounded-lg shadow-xl overflow-hidden"
          style={{ top: moreMenuPosition.top, left: moreMenuPosition.left }}
          onMouseLeave={() => setShowMoreMenu(false)}
        >
          <div className="p-1">
            {moreMenuItems.map((item, index) => (
              <button
                key={index}
                onClick={item.onClick}
                className="w-full flex items-center gap-3 px-3 py-2 text-sm text-[var(--text)]/80 hover:text-[var(--text)] hover:bg-[var(--sidebar-hover)] rounded-md transition-colors"
              >
                <item.icon size={16} className="text-[var(--text)]/50" />
                <span className="flex-1 text-left">{item.label}</span>
                {item.external && <ExternalLink size={12} className="text-[var(--text)]/40" />}
                {item.shortcut && (
                  <span className="text-xs text-[var(--text)]/40 font-mono">{item.shortcut}</span>
                )}
              </button>
            ))}
          </div>
        </div>
      )}
    </>
  );
}
