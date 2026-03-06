import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { Command } from 'cmdk';
import { useHotkeys } from 'react-hotkeys-hook';
import { useLocation, useNavigate } from 'react-router-dom';
import * as Dialog from '@radix-ui/react-dialog';
import * as VisuallyHidden from '@radix-ui/react-visually-hidden';
import {
  MagnifyingGlass,
  Folder,
  Storefront,
  Books,
  Gear,
  Sun,
  Moon,
  Plus,
  ArrowsClockwise,
  Clock,
  Desktop,
  Code,
  Kanban,
  Images,
  Terminal,
  GitBranch,
  Note,
  TreeStructure,
  X,
} from '@phosphor-icons/react';
import { useTheme } from '../theme/ThemeContext';
import { useCommands } from '../contexts/CommandContext';
import { getContextFromPath, modKey, type AppContext } from '../lib/keyboard-registry';

interface CommandItem {
  id: string;
  label: string;
  icon: React.ReactNode;
  shortcut?: string[];
  action: () => void;
  context?: AppContext | AppContext[];
  keywords?: string[];
  group: string;
}

interface CommandPaletteProps {
  onShowShortcuts?: () => void;
}

export function CommandPalette({ onShowShortcuts }: CommandPaletteProps) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const location = useLocation();
  const navigate = useNavigate();
  const { theme, toggleTheme } = useTheme();
  const { executeCommand, isCommandAvailable } = useCommands();

  // Track recent items in localStorage
  const [recentItems, setRecentItems] = useState<string[]>(() => {
    try {
      const saved = localStorage.getItem('tesslate-recent-commands');
      return saved ? JSON.parse(saved) : [];
    } catch {
      return [];
    }
  });

  // Open with Cmd+K (overrides browser)
  useHotkeys(
    'mod+k',
    (e) => {
      e.preventDefault();
      e.stopPropagation();
      setOpen(true);
    },
    {
      preventDefault: true,
      enableOnFormTags: ['INPUT', 'TEXTAREA', 'SELECT'],
    }
  );

  // Close with Escape
  useHotkeys(
    'escape',
    () => {
      if (open) {
        setOpen(false);
      }
    },
    {
      enableOnFormTags: ['INPUT', 'TEXTAREA', 'SELECT'],
    }
  );

  // Get current context
  const currentContext = useMemo(() => getContextFromPath(location.pathname), [location.pathname]);

  // Track recent usage
  const addToRecent = useCallback((id: string) => {
    setRecentItems((prev) => {
      const updated = [id, ...prev.filter((i) => i !== id)].slice(0, 5);
      localStorage.setItem('tesslate-recent-commands', JSON.stringify(updated));
      return updated;
    });
  }, []);

  // Define all commands
  const allCommands = useMemo<CommandItem[]>(() => {
    const commands: CommandItem[] = [
      // Navigation
      {
        id: 'go-dashboard',
        label: 'Go to Dashboard',
        icon: <Folder size={18} weight="fill" />,
        shortcut: [modKey, 'D'],
        action: () => navigate('/dashboard'),
        context: 'global',
        keywords: ['home', 'projects', 'main'],
        group: 'Navigation',
      },
      {
        id: 'go-marketplace',
        label: 'Go to Marketplace',
        icon: <Storefront size={18} weight="fill" />,
        shortcut: [modKey, 'M'],
        action: () => navigate('/marketplace'),
        context: 'global',
        keywords: ['store', 'agents', 'extensions', 'plugins'],
        group: 'Navigation',
      },
      {
        id: 'go-library',
        label: 'Go to Library',
        icon: <Books size={18} weight="fill" />,
        shortcut: [modKey, 'L'],
        action: () => navigate('/library'),
        context: 'global',
        keywords: ['my agents', 'installed', 'api keys', 'models'],
        group: 'Navigation',
      },
      {
        id: 'go-settings',
        label: 'Go to Settings',
        icon: <Gear size={18} weight="fill" />,
        shortcut: [modKey, ','],
        action: () => navigate('/settings'),
        context: 'global',
        keywords: ['preferences', 'profile', 'account'],
        group: 'Navigation',
      },

      // Actions
      {
        id: 'toggle-theme',
        label: theme === 'dark' ? 'Switch to Light Mode' : 'Switch to Dark Mode',
        icon: theme === 'dark' ? <Sun size={18} weight="fill" /> : <Moon size={18} weight="fill" />,
        shortcut: [modKey, 'T'],
        action: toggleTheme,
        context: 'global',
        keywords: ['dark', 'light', 'mode', 'appearance'],
        group: 'Actions',
      },
      {
        id: 'show-shortcuts',
        label: 'Show Keyboard Shortcuts',
        icon: <span className="text-lg font-mono">?</span>,
        shortcut: ['?'],
        action: () => {
          setOpen(false);
          onShowShortcuts?.();
        },
        context: 'global',
        keywords: ['help', 'keys', 'hotkeys', 'bindings'],
        group: 'Actions',
      },

      // Dashboard actions
      {
        id: 'new-project',
        label: 'Create New Project',
        icon: <Plus size={18} weight="bold" />,
        shortcut: [modKey, 'N'],
        action: () => {
          navigate('/dashboard');
          // Use command context for reliable delivery
          setTimeout(() => executeCommand('openCreateProject'), 100);
        },
        context: 'dashboard',
        keywords: ['new', 'create', 'project', 'app'],
        group: 'Dashboard',
      },

      // Project actions (only show when in project context)
      {
        id: 'view-preview',
        label: 'Switch to Preview',
        icon: <Desktop size={18} weight="fill" />,
        shortcut: [modKey, '1'],
        action: () => executeCommand('switchView', 'preview'),
        context: 'project',
        keywords: ['browser', 'app', 'run'],
        group: 'Project',
      },
      {
        id: 'view-code',
        label: 'Switch to Code',
        icon: <Code size={18} weight="fill" />,
        shortcut: [modKey, '2'],
        action: () => executeCommand('switchView', 'code'),
        context: 'project',
        keywords: ['editor', 'files', 'source'],
        group: 'Project',
      },
      {
        id: 'view-kanban',
        label: 'Switch to Kanban',
        icon: <Kanban size={18} weight="fill" />,
        shortcut: [modKey, '3'],
        action: () => executeCommand('switchView', 'kanban'),
        context: 'project',
        keywords: ['tasks', 'board', 'issues'],
        group: 'Project',
      },
      {
        id: 'view-assets',
        label: 'Switch to Assets',
        icon: <Images size={18} weight="fill" />,
        shortcut: [modKey, '4'],
        action: () => executeCommand('switchView', 'assets'),
        context: 'project',
        keywords: ['images', 'files', 'media'],
        group: 'Project',
      },
      {
        id: 'view-terminal',
        label: 'Switch to Terminal',
        icon: <Terminal size={18} weight="fill" />,
        shortcut: [modKey, '5'],
        action: () => executeCommand('switchView', 'terminal'),
        context: 'project',
        keywords: ['console', 'shell', 'cli'],
        group: 'Project',
      },
      {
        id: 'refresh-preview',
        label: 'Refresh Preview',
        icon: <ArrowsClockwise size={18} weight="bold" />,
        shortcut: [modKey, 'R'],
        action: () => executeCommand('refreshPreview'),
        context: 'project',
        keywords: ['reload', 'update'],
        group: 'Project',
      },
      {
        id: 'toggle-git',
        label: 'Toggle Git Panel',
        icon: <GitBranch size={18} weight="fill" />,
        shortcut: [modKey, '⇧', 'G'],
        action: () => executeCommand('togglePanel', 'github'),
        context: 'project',
        keywords: ['version control', 'commit', 'push'],
        group: 'Project',
      },
      {
        id: 'toggle-notes',
        label: 'Toggle Notes Panel',
        icon: <Note size={18} weight="fill" />,
        shortcut: [modKey, '⇧', 'N'],
        action: () => executeCommand('togglePanel', 'notes'),
        context: 'project',
        keywords: ['memo', 'scratch'],
        group: 'Project',
      },
      {
        id: 'toggle-architecture',
        label: 'Toggle Architecture Panel',
        icon: <TreeStructure size={18} weight="fill" />,
        shortcut: [modKey, '⇧', 'A'],
        action: () => executeCommand('togglePanel', 'architecture'),
        context: 'project',
        keywords: ['diagram', 'structure'],
        group: 'Project',
      },
    ];

    return commands;
  }, [navigate, theme, toggleTheme, onShowShortcuts, executeCommand]);

  // Map command IDs to their CommandContext handler names
  const commandToHandlerMap: Record<string, string> = useMemo(
    () => ({
      'view-preview': 'switchView',
      'view-code': 'switchView',
      'view-kanban': 'switchView',
      'view-assets': 'switchView',
      'view-terminal': 'switchView',
      'refresh-preview': 'refreshPreview',
      'toggle-git': 'togglePanel',
      'toggle-notes': 'togglePanel',
      'toggle-architecture': 'togglePanel',
      'new-project': 'openCreateProject',
    }),
    []
  );

  // Filter commands for current context and handler availability
  const contextCommands = useMemo(() => {
    return allCommands.filter((cmd) => {
      // Check context match
      let contextMatch = true;
      if (cmd.context) {
        if (Array.isArray(cmd.context)) {
          contextMatch = cmd.context.includes(currentContext) || cmd.context.includes('global');
        } else {
          contextMatch = cmd.context === currentContext || cmd.context === 'global';
        }
      }
      if (!contextMatch) return false;

      // For commands that require handlers, check if handler is available
      // This prevents showing project commands when not in a project
      const handlerName = commandToHandlerMap[cmd.id];
      if (handlerName && cmd.context === 'project') {
        return isCommandAvailable(handlerName as keyof typeof commandToHandlerMap);
      }

      return true;
    });
  }, [allCommands, currentContext, isCommandAvailable, commandToHandlerMap]);

  // Get recent commands
  const recentCommands = useMemo(() => {
    return recentItems
      .map((id) => contextCommands.find((cmd) => cmd.id === id))
      .filter(Boolean) as CommandItem[];
  }, [recentItems, contextCommands]);

  // Group commands
  const groupedCommands = useMemo(() => {
    const groups: Record<string, CommandItem[]> = {};
    contextCommands.forEach((cmd) => {
      if (!groups[cmd.group]) {
        groups[cmd.group] = [];
      }
      groups[cmd.group].push(cmd);
    });
    return groups;
  }, [contextCommands]);

  // Handle command selection
  const handleSelect = useCallback(
    (command: CommandItem) => {
      addToRecent(command.id);
      setOpen(false);
      setSearch('');
      command.action();
    },
    [addToRecent]
  );

  // Reset search when closing
  useEffect(() => {
    if (!open) {
      setSearch('');
    }
  }, [open]);

  return (
    <Command.Dialog
      open={open}
      onOpenChange={setOpen}
      label="Command Menu"
      className="fixed inset-0 z-[100]"
      filter={(value, search) => {
        // Custom filter that includes keywords
        // Strip "recent-" prefix to find the actual command
        const cmdId = value.startsWith('recent-') ? value.slice(7) : value;
        const cmd = allCommands.find((c) => c.id === cmdId);
        if (!cmd) return 0;
        const searchLower = search.toLowerCase();
        if (cmd.label.toLowerCase().includes(searchLower)) return 1;
        if (cmd.keywords?.some((k) => k.toLowerCase().includes(searchLower))) return 0.5;
        return 0;
      }}
    >
      {/* Accessibility: Hidden title and description for screen readers */}
      <VisuallyHidden.Root>
        <Dialog.Title>Command Menu</Dialog.Title>
      </VisuallyHidden.Root>
      <VisuallyHidden.Root>
        <Dialog.Description>
          Search for commands, navigate to pages, or toggle settings
        </Dialog.Description>
      </VisuallyHidden.Root>

      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/50 backdrop-blur-sm"
        onClick={() => setOpen(false)}
        aria-hidden="true"
      />

      {/* Modal */}
      <div className="fixed top-[15%] left-1/2 -translate-x-1/2 w-full max-w-xl px-4">
        <Command
          className="bg-[var(--surface)] border border-white/10 rounded-xl shadow-2xl overflow-hidden"
          loop
        >
          {/* Search Input */}
          <div className="flex items-center gap-3 border-b border-white/10 px-4">
            <MagnifyingGlass size={20} className="text-white/40 shrink-0" />
            <Command.Input
              value={search}
              onValueChange={setSearch}
              placeholder="Type a command or search..."
              className="flex-1 bg-transparent py-4 text-white text-base outline-none focus-visible:outline-none placeholder-white/40"
              autoFocus
            />
            {search && (
              <button
                onClick={() => setSearch('')}
                className="p-1 rounded hover:bg-white/10 transition-colors"
                aria-label="Clear search"
              >
                <X size={16} className="text-white/40" />
              </button>
            )}
            <kbd className="hidden sm:flex px-2 py-1 text-xs bg-white/10 rounded text-white/50 font-mono">
              ESC
            </kbd>
          </div>

          {/* Results */}
          <Command.List className="max-h-[400px] overflow-y-auto p-2">
            <Command.Empty className="py-8 text-center text-white/40">
              No results found.
            </Command.Empty>

            {/* Recent */}
            {recentCommands.length > 0 && !search && (
              <Command.Group
                heading={
                  <span className="flex items-center gap-2 text-xs font-medium text-white/50 uppercase tracking-wider px-2 py-2">
                    <Clock size={14} />
                    Recent
                  </span>
                }
              >
                {recentCommands.map((cmd) => (
                  <CommandItem
                    key={`recent-${cmd.id}`}
                    command={cmd}
                    onSelect={handleSelect}
                    valuePrefix="recent-"
                  />
                ))}
              </Command.Group>
            )}

            {/* Grouped commands */}
            {Object.entries(groupedCommands).map(([group, commands]) => (
              <Command.Group
                key={group}
                heading={
                  <span className="text-xs font-medium text-white/50 uppercase tracking-wider px-2 py-2">
                    {group}
                  </span>
                }
              >
                {commands.map((cmd) => (
                  <CommandItem key={cmd.id} command={cmd} onSelect={handleSelect} />
                ))}
              </Command.Group>
            ))}
          </Command.List>

          {/* Footer */}
          <div className="flex items-center justify-between px-4 py-2.5 border-t border-white/10 text-xs text-white/40">
            <div className="flex items-center gap-4">
              <span className="flex items-center gap-1.5">
                <kbd className="px-1.5 py-0.5 bg-white/10 rounded font-mono">↑</kbd>
                <kbd className="px-1.5 py-0.5 bg-white/10 rounded font-mono">↓</kbd>
                <span>Navigate</span>
              </span>
              <span className="flex items-center gap-1.5">
                <kbd className="px-1.5 py-0.5 bg-white/10 rounded font-mono">↵</kbd>
                <span>Select</span>
              </span>
            </div>
            <span className="flex items-center gap-1.5">
              <kbd className="px-1.5 py-0.5 bg-white/10 rounded font-mono">ESC</kbd>
              <span>Close</span>
            </span>
          </div>
        </Command>
      </div>
    </Command.Dialog>
  );
}

// Individual command item component
function CommandItem({
  command,
  onSelect,
  valuePrefix = '',
}: {
  command: CommandItem;
  onSelect: (cmd: CommandItem) => void;
  valuePrefix?: string;
}) {
  return (
    <Command.Item
      value={`${valuePrefix}${command.id}`}
      onSelect={() => onSelect(command)}
      className="flex items-center gap-3 px-3 py-2.5 rounded-lg cursor-pointer
                 text-white/80 transition-colors
                 data-[selected=true]:bg-[var(--primary)] data-[selected=true]:text-white"
    >
      <span className="shrink-0 w-6 h-6 flex items-center justify-center text-white/60 data-[selected=true]:text-white">
        {command.icon}
      </span>
      <span className="flex-1 truncate">{command.label}</span>
      {command.shortcut && (
        <span className="flex items-center gap-1 shrink-0">
          {command.shortcut.map((key, i) => (
            <kbd
              key={i}
              className="px-1.5 py-0.5 text-xs bg-white/10 rounded text-white/50 font-mono"
            >
              {key}
            </kbd>
          ))}
        </span>
      )}
    </Command.Item>
  );
}

export default CommandPalette;
