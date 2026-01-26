import { useState, useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Tooltip } from '../ui/Tooltip';
import {
  ArrowLeft,
  User,
  Settings,
  Shield,
  Cloud,
  Key,
  CreditCard,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';

interface SettingsSidebarProps {
  onClose?: () => void;
  showContent?: boolean;
}

interface NavItem {
  label: string;
  path: string;
  icon: typeof User;
}

interface NavSection {
  title: string;
  items: NavItem[];
}

const navSections: NavSection[] = [
  {
    title: 'ACCOUNT',
    items: [
      { label: 'Profile', path: '/settings/profile', icon: User },
      { label: 'Preferences', path: '/settings/preferences', icon: Settings },
      { label: 'Security', path: '/settings/security', icon: Shield },
    ],
  },
  {
    title: 'INTEGRATIONS',
    items: [
      { label: 'Deployment', path: '/settings/deployment', icon: Cloud },
      { label: 'API Keys', path: '/settings/api-keys', icon: Key },
    ],
  },
  {
    title: 'BILLING',
    items: [{ label: 'Subscription', path: '/settings/billing', icon: CreditCard }],
  },
];

export function SettingsSidebar({ onClose, showContent = true }: SettingsSidebarProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const [isExpanded, setIsExpanded] = useState(() => {
    const saved = localStorage.getItem('settingsSidebarExpanded');
    return saved !== null ? JSON.parse(saved) : true;
  });

  useEffect(() => {
    localStorage.setItem('settingsSidebarExpanded', JSON.stringify(isExpanded));
  }, [isExpanded]);

  const handleNavigation = (path: string) => {
    navigate(path);
    if (onClose) {
      onClose();
    }
  };

  const isActive = (path: string) => location.pathname === path;

  return (
    <motion.div
      initial={false}
      animate={{ width: isExpanded ? 192 : 48 }}
      transition={{
        type: 'spring',
        stiffness: 700,
        damping: 28,
        mass: 0.4,
      }}
      className="hidden md:flex flex-col h-screen bg-[var(--sidebar-bg)] border-r border-[var(--sidebar-border)] overflow-x-hidden"
    >
      {/* Back to app header */}
      <div
        className={`flex items-center h-12 flex-shrink-0 ${isExpanded ? 'px-3 gap-3' : 'justify-center'} border-b border-[var(--sidebar-border)] bg-[var(--sidebar-bg)]`}
      >
        {isExpanded ? (
          <button
            onClick={() => {
              navigate('/dashboard');
              if (onClose) onClose();
            }}
            className="flex items-center gap-2 text-[var(--sidebar-text)]/60 hover:text-[var(--sidebar-text)] transition-colors"
          >
            <ArrowLeft size={18} className="flex-shrink-0" />
            <span className="text-sm font-medium">Back to app</span>
          </button>
        ) : (
          <Tooltip content="Back to app" side="right" delay={200}>
            <button
              onClick={() => {
                navigate('/dashboard');
                if (onClose) onClose();
              }}
              className="flex items-center justify-center text-[var(--sidebar-text)]/60 hover:text-[var(--sidebar-text)] transition-colors"
            >
              <ArrowLeft size={18} />
            </button>
          </Tooltip>
        )}
      </div>

      <motion.div
        className="py-3 flex flex-col flex-1 overflow-y-auto overflow-x-hidden"
        initial={{ opacity: 0 }}
        animate={{ opacity: showContent ? 1 : 0 }}
        transition={{ duration: 0.4, ease: 'easeOut' }}
      >
        {/* Navigation sections */}
        {navSections.map((section, sectionIndex) => (
          <div key={section.title} className={sectionIndex > 0 ? 'mt-4' : ''}>
            {/* Section title - only show when expanded */}
            {isExpanded && (
              <div className="px-4 py-2 text-[10px] font-semibold text-[var(--sidebar-text)]/40 tracking-wider">
                {section.title}
              </div>
            )}

            {/* Section items */}
            <div className="flex flex-col gap-0.5">
              {section.items.map((item) => {
                const Icon = item.icon;
                return isExpanded ? (
                  <button
                    key={item.path}
                    onClick={() => handleNavigation(item.path)}
                    className={`group flex items-center h-9 transition-colors flex-shrink-0 gap-3 rounded-lg mx-2 px-3 ${
                      isActive(item.path) ? 'bg-[var(--sidebar-active)]' : 'hover:bg-[var(--sidebar-hover)]'
                    }`}
                  >
                    <Icon
                      size={18}
                      className={`transition-colors ${
                        isActive(item.path)
                          ? 'text-[var(--sidebar-text)]'
                          : 'text-[var(--sidebar-text)]/40 group-hover:text-[var(--sidebar-text)]'
                      }`}
                    />
                    <span className="text-sm font-medium text-[var(--sidebar-text)]">{item.label}</span>
                  </button>
                ) : (
                  <Tooltip key={item.path} content={item.label} side="right" delay={200}>
                    <button
                      onClick={() => handleNavigation(item.path)}
                      className={`group flex items-center justify-center h-9 transition-colors w-full flex-shrink-0 ${
                        isActive(item.path) ? 'bg-[var(--sidebar-active)]' : 'hover:bg-[var(--sidebar-hover)]'
                      }`}
                    >
                      <Icon
                        size={18}
                        className={`transition-colors ${
                          isActive(item.path)
                            ? 'text-[var(--sidebar-text)]'
                            : 'text-[var(--sidebar-text)]/40 group-hover:text-[var(--sidebar-text)]'
                        }`}
                      />
                    </button>
                  </Tooltip>
                );
              })}
            </div>
          </div>
        ))}

        {/* Spacer to push collapse button to bottom */}
        <div className="flex-1" />

        <div className="h-px bg-[var(--sidebar-border)] my-1 mx-2 flex-shrink-0" />

        {/* Collapse/Expand Toggle */}
        {isExpanded ? (
          <button
            onClick={() => setIsExpanded(false)}
            className="group flex items-center h-9 hover:bg-[var(--sidebar-hover)] transition-colors flex-shrink-0 gap-3 rounded-lg mx-2 px-3"
          >
            <ChevronLeft
              size={18}
              className="text-[var(--sidebar-text)]/40 group-hover:text-[var(--sidebar-text)] transition-colors"
            />
            <span className="text-sm font-medium text-[var(--sidebar-text)]">Collapse</span>
          </button>
        ) : (
          <Tooltip content="Expand" side="right" delay={200}>
            <button
              onClick={() => setIsExpanded(true)}
              className="group flex items-center justify-center h-9 hover:bg-[var(--sidebar-hover)] transition-colors w-full flex-shrink-0"
            >
              <ChevronRight
                size={18}
                className="text-[var(--sidebar-text)]/40 group-hover:text-[var(--sidebar-text)] transition-colors"
              />
            </button>
          </Tooltip>
        )}
      </motion.div>
    </motion.div>
  );
}

// Mobile version of the sidebar (always expanded, for drawer)
export function SettingsSidebarMobile({ onClose }: { onClose: () => void }) {
  const location = useLocation();
  const navigate = useNavigate();

  const handleNavigation = (path: string) => {
    navigate(path);
    onClose();
  };

  const isActive = (path: string) => location.pathname === path;

  return (
    <div className="flex flex-col h-full bg-[var(--sidebar-bg)] overflow-hidden">
      {/* Back to app header */}
      <div className="flex items-center h-12 flex-shrink-0 px-3 gap-3 border-b border-[var(--sidebar-border)] bg-[var(--sidebar-bg)]">
        <button
          onClick={() => {
            navigate('/dashboard');
            onClose();
          }}
          className="flex items-center gap-2 text-[var(--sidebar-text)]/60 hover:text-[var(--sidebar-text)] transition-colors min-h-[44px]"
        >
          <ArrowLeft size={18} className="flex-shrink-0" />
          <span className="text-sm font-medium">Back to app</span>
        </button>
      </div>

      <div className="py-3 flex flex-col flex-1 overflow-y-auto">
        {/* Navigation sections */}
        {navSections.map((section, sectionIndex) => (
          <div key={section.title} className={sectionIndex > 0 ? 'mt-4' : ''}>
            {/* Section title */}
            <div className="px-4 py-2 text-[10px] font-semibold text-[var(--sidebar-text)]/40 tracking-wider">
              {section.title}
            </div>

            {/* Section items */}
            <div className="flex flex-col gap-0.5">
              {section.items.map((item) => {
                const Icon = item.icon;
                return (
                  <button
                    key={item.path}
                    onClick={() => handleNavigation(item.path)}
                    className={`group flex items-center h-11 transition-colors flex-shrink-0 gap-3 rounded-lg mx-2 px-3 ${
                      isActive(item.path) ? 'bg-[var(--sidebar-active)]' : 'hover:bg-[var(--sidebar-hover)]'
                    }`}
                  >
                    <Icon
                      size={18}
                      className={`transition-colors ${
                        isActive(item.path)
                          ? 'text-[var(--sidebar-text)]'
                          : 'text-[var(--sidebar-text)]/40 group-hover:text-[var(--sidebar-text)]'
                      }`}
                    />
                    <span className="text-sm font-medium text-[var(--sidebar-text)]">{item.label}</span>
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
