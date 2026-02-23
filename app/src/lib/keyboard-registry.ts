/**
 * Keyboard shortcuts registry for Tesslate Studio
 * Defines all keyboard shortcuts across the application
 */

export type AppContext =
  | 'global'
  | 'dashboard'
  | 'project'
  | 'project:preview'
  | 'project:code'
  | 'project:kanban'
  | 'project:chat'
  | 'marketplace'
  | 'library'
  | 'settings';

export interface ShortcutDefinition {
  id: string;
  label: string;
  keys: string[]; // Display keys like ['⌘', 'K']
  hotkey: string; // react-hotkeys-hook format like 'mod+k'
  context: AppContext | AppContext[];
  category: string;
  action?: () => void; // Optional - can be set dynamically
}

export interface ShortcutGroup {
  title: string;
  shortcuts: ShortcutDefinition[];
}

// Display helpers for different platforms
export const isMac =
  typeof navigator !== 'undefined' && /Mac|iPod|iPhone|iPad/.test(navigator.platform);

export const modKey = isMac ? '⌘' : 'Ctrl';
export const altKey = isMac ? '⌥' : 'Alt';
export const shiftKey = '⇧';

/**
 * All keyboard shortcuts organized by category
 */
export const shortcutGroups: ShortcutGroup[] = [
  {
    title: 'General',
    shortcuts: [
      {
        id: 'command-palette',
        label: 'Open command menu',
        keys: [modKey, 'K'],
        hotkey: 'mod+k',
        context: 'global',
        category: 'General',
      },
      {
        id: 'save-send',
        label: 'Save / Send',
        keys: ['⌃', '↵'],
        hotkey: 'ctrl+enter',
        context: 'global',
        category: 'General',
      },
      {
        id: 'go-back',
        label: 'Go back / Close',
        keys: ['Esc'],
        hotkey: 'escape',
        context: 'global',
        category: 'General',
      },
      {
        id: 'enter-item',
        label: 'Enter focused item',
        keys: ['Space'],
        hotkey: 'space',
        context: ['project', 'dashboard'],
        category: 'General',
      },
      {
        id: 'show-shortcuts',
        label: 'Show keyboard shortcuts',
        keys: ['?'],
        hotkey: 'shift+/',
        context: 'global',
        category: 'General',
      },
      {
        id: 'show-shortcuts-alt',
        label: 'Show keyboard shortcuts',
        keys: [modKey, '/'],
        hotkey: 'ctrl+/',
        context: 'global',
        category: 'General',
      },
    ],
  },
  {
    title: 'Navigation',
    shortcuts: [
      {
        id: 'go-dashboard',
        label: 'Go to Dashboard',
        keys: [modKey, 'D'],
        hotkey: 'mod+d',
        context: 'global',
        category: 'Navigation',
      },
      {
        id: 'go-marketplace',
        label: 'Go to Marketplace',
        keys: [modKey, 'M'],
        hotkey: 'mod+m',
        context: 'global',
        category: 'Navigation',
      },
      {
        id: 'go-library',
        label: 'Go to Library',
        keys: [modKey, 'L'],
        hotkey: 'mod+l',
        context: 'global',
        category: 'Navigation',
      },
      {
        id: 'go-settings',
        label: 'Go to Settings',
        keys: [modKey, ','],
        hotkey: 'mod+comma',
        context: 'global',
        category: 'Navigation',
      },
      {
        id: 'toggle-theme',
        label: 'Toggle theme',
        keys: [modKey, 'T'],
        hotkey: 'mod+t',
        context: 'global',
        category: 'Navigation',
      },
    ],
  },
  {
    title: 'Dashboard',
    shortcuts: [
      {
        id: 'new-project',
        label: 'Create new project',
        keys: [modKey, 'N'],
        hotkey: 'mod+n',
        context: 'dashboard',
        category: 'Dashboard',
      },
      {
        id: 'import-project',
        label: 'Import repository',
        keys: [modKey, 'I'],
        hotkey: 'mod+i',
        context: 'dashboard',
        category: 'Dashboard',
      },
    ],
  },
  {
    title: 'Project Builder',
    shortcuts: [
      {
        id: 'view-preview',
        label: 'Switch to Preview',
        keys: [modKey, '1'],
        hotkey: 'mod+1',
        context: 'project',
        category: 'Project Builder',
      },
      {
        id: 'view-code',
        label: 'Switch to Code',
        keys: [modKey, '2'],
        hotkey: 'mod+2',
        context: 'project',
        category: 'Project Builder',
      },
      {
        id: 'view-kanban',
        label: 'Switch to Kanban',
        keys: [modKey, '3'],
        hotkey: 'mod+3',
        context: 'project',
        category: 'Project Builder',
      },
      {
        id: 'view-assets',
        label: 'Switch to Assets',
        keys: [modKey, '4'],
        hotkey: 'mod+4',
        context: 'project',
        category: 'Project Builder',
      },
      {
        id: 'view-terminal',
        label: 'Switch to Terminal',
        keys: [modKey, '5'],
        hotkey: 'mod+5',
        context: 'project',
        category: 'Project Builder',
      },
      {
        id: 'refresh-preview',
        label: 'Refresh preview',
        keys: [modKey, 'R'],
        hotkey: 'mod+r',
        context: 'project',
        category: 'Project Builder',
      },
      {
        id: 'toggle-git',
        label: 'Toggle Git panel',
        keys: [modKey, shiftKey, 'G'],
        hotkey: 'mod+shift+g',
        context: 'project',
        category: 'Project Builder',
      },
      {
        id: 'toggle-notes',
        label: 'Toggle Notes panel',
        keys: [modKey, shiftKey, 'N'],
        hotkey: 'mod+shift+n',
        context: 'project',
        category: 'Project Builder',
      },
      {
        id: 'toggle-settings',
        label: 'Toggle Settings panel',
        keys: [modKey, shiftKey, 'S'],
        hotkey: 'mod+shift+s',
        context: 'project',
        category: 'Project Builder',
      },
      {
        id: 'toggle-architecture',
        label: 'Toggle Architecture panel',
        keys: [modKey, shiftKey, 'A'],
        hotkey: 'mod+shift+a',
        context: 'project',
        category: 'Project Builder',
      },
      {
        id: 'toggle-left-sidebar',
        label: 'Toggle left sidebar',
        keys: [modKey, 'B'],
        hotkey: 'mod+b',
        context: 'project',
        category: 'Project Builder',
      },
      {
        id: 'toggle-right-sidebar',
        label: 'Toggle right sidebar',
        keys: [modKey, '.'],
        hotkey: 'mod+.',
        context: 'project',
        category: 'Project Builder',
      },
      {
        id: 'preview-back',
        label: 'Navigate back in preview',
        keys: [altKey, '←'],
        hotkey: 'alt+left',
        context: 'project:preview',
        category: 'Project Builder',
      },
      {
        id: 'preview-forward',
        label: 'Navigate forward in preview',
        keys: [altKey, '→'],
        hotkey: 'alt+right',
        context: 'project:preview',
        category: 'Project Builder',
      },
    ],
  },
  {
    title: 'Chat',
    shortcuts: [
      {
        id: 'send-message',
        label: 'Send message',
        keys: ['⌃', '↵'],
        hotkey: 'ctrl+enter',
        context: 'project:chat',
        category: 'Chat',
      },
      {
        id: 'focus-chat',
        label: 'Focus chat input',
        keys: [modKey, shiftKey, 'C'],
        hotkey: 'mod+shift+c',
        context: 'project',
        category: 'Chat',
      },
    ],
  },
  {
    title: 'Marketplace',
    shortcuts: [
      {
        id: 'focus-search',
        label: 'Focus search',
        keys: ['/'],
        hotkey: '/',
        context: 'marketplace',
        category: 'Marketplace',
      },
      {
        id: 'toggle-filters',
        label: 'Toggle filters',
        keys: ['F'],
        hotkey: 'f',
        context: 'marketplace',
        category: 'Marketplace',
      },
    ],
  },
];

/**
 * Get all shortcuts flattened into a single array
 */
export function getAllShortcuts(): ShortcutDefinition[] {
  return shortcutGroups.flatMap((group) => group.shortcuts);
}

/**
 * Get shortcuts for a specific context
 */
export function getShortcutsForContext(context: AppContext): ShortcutDefinition[] {
  return getAllShortcuts().filter((shortcut) => {
    if (Array.isArray(shortcut.context)) {
      return shortcut.context.includes(context) || shortcut.context.includes('global');
    }
    return shortcut.context === context || shortcut.context === 'global';
  });
}

/**
 * Get shortcut groups filtered for a specific context
 */
export function getShortcutGroupsForContext(context: AppContext): ShortcutGroup[] {
  return shortcutGroups
    .map((group) => ({
      ...group,
      shortcuts: group.shortcuts.filter((shortcut) => {
        if (Array.isArray(shortcut.context)) {
          return shortcut.context.includes(context) || shortcut.context.includes('global');
        }
        return shortcut.context === context || shortcut.context === 'global';
      }),
    }))
    .filter((group) => group.shortcuts.length > 0);
}

/**
 * Find a shortcut by its ID
 */
export function findShortcutById(id: string): ShortcutDefinition | undefined {
  return getAllShortcuts().find((s) => s.id === id);
}

/**
 * Get context from pathname
 */
export function getContextFromPath(pathname: string): AppContext {
  if (pathname.startsWith('/project/')) return 'project';
  if (pathname.startsWith('/marketplace')) return 'marketplace';
  if (pathname.startsWith('/library')) return 'library';
  if (pathname.startsWith('/settings')) return 'settings';
  if (pathname === '/dashboard' || pathname === '/') return 'dashboard';
  return 'global';
}
