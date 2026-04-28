/**
 * Keyboard shortcuts registry for OpenSail
 * Defines all keyboard shortcuts and palette commands across the application.
 *
 * Single source of truth: every entry that appears in the help modal, the
 * Cmd+K palette, or via direct `useHotkeys` call should be defined here.
 * Entries with `paletteOnly: true` have no keybinding and are surfaced only
 * in the palette (hidden from the help modal).
 */

export type AppContext =
  | 'global'
  | 'dashboard'
  | 'project'
  | 'project:preview'
  | 'project:code'
  | 'project:design'
  | 'project:architecture'
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
  /**
   * Search keywords for the palette (boosts fuzzy matching).
   */
  keywords?: string[];
  /**
   * If true, the entry only appears in the Cmd+K palette and is hidden
   * from the help modal. Used for actions that don't have a keybinding.
   */
  paletteOnly?: boolean;
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
 * All keyboard shortcuts and palette commands organized by category.
 *
 * Categories (in display order):
 *   1. General             — palette, help, theme, save/send, escape
 *   2. Navigation          — dashboard, marketplace, library, settings, chat, automations
 *   3. Project: Views      — ⌘1–8 view switcher
 *   4. Project: Lifecycle  — run, stop, restart, publish, fork, hibernate, overview, rename
 *   5. Project: Git        — commit, push, pull, branch ops
 *   6. Project: Snapshots  — create, restore, timeline
 *   7. Project: Code       — quick-open, file tree, find in files
 *   8. Project: Architecture — auto-layout, save/load config, fit view
 *   9. Project: Design     — undo/redo/copy/paste/group/delete on canvas
 *  10. Chat                — sessions, model, edit mode, focus, clear, attach
 *  11. Layout              — sidebars, zen
 *  12. Library             — palette jump-tos to library tabs and create flows
 *  13. Settings            — palette jump-tos to settings tabs
 *  14. Dashboard           — list/cards toggle, filters, search
 *  15. Marketplace         — search, filters
 *  16. Diagnostics         — debug info, container logs, restart container
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
        keywords: ['palette', 'menu', 'search', 'commands'],
      },
      {
        id: 'show-shortcuts',
        label: 'Show keyboard shortcuts',
        keys: ['?'],
        hotkey: 'shift+/',
        context: 'global',
        category: 'General',
        keywords: ['help', 'keys', 'hotkeys', 'bindings'],
      },
      {
        id: 'show-shortcuts-alt',
        label: 'Show keyboard shortcuts',
        keys: [modKey, '/'],
        hotkey: 'mod+/',
        context: 'global',
        category: 'General',
      },
      {
        id: 'show-all-commands',
        label: 'Show all commands…',
        keys: [],
        hotkey: '',
        context: 'global',
        category: 'General',
        paletteOnly: true,
        keywords: ['browse', 'list', 'every', 'all'],
      },
      {
        id: 'toggle-theme',
        label: 'Toggle theme',
        keys: [modKey, 'T'],
        hotkey: 'mod+t',
        context: 'global',
        category: 'General',
        keywords: ['dark', 'light', 'mode', 'appearance'],
      },
      {
        id: 'theme-pick',
        label: 'Pick theme preset…',
        keys: [],
        hotkey: '',
        context: 'global',
        category: 'General',
        paletteOnly: true,
        keywords: ['theme', 'color', 'preset', 'preferences'],
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
        keywords: ['home', 'projects', 'main'],
      },
      {
        id: 'go-marketplace',
        label: 'Go to Marketplace',
        keys: [modKey, 'M'],
        hotkey: 'mod+m',
        context: 'global',
        category: 'Navigation',
        keywords: ['store', 'agents', 'extensions', 'plugins', 'apps'],
      },
      {
        id: 'go-library',
        label: 'Go to Library',
        keys: [modKey, 'L'],
        hotkey: 'mod+l',
        context: 'global',
        category: 'Navigation',
        keywords: ['my agents', 'installed', 'api keys', 'models'],
      },
      {
        id: 'go-chat',
        label: 'Go to Chat',
        keys: [modKey, 'J'],
        hotkey: 'mod+j',
        context: 'global',
        category: 'Navigation',
        keywords: ['agent', 'conversation'],
      },
      {
        id: 'go-settings',
        label: 'Go to Settings',
        keys: [modKey, ','],
        hotkey: 'mod+comma',
        context: 'global',
        category: 'Navigation',
        keywords: ['preferences', 'profile', 'account'],
      },
      {
        id: 'go-automations',
        label: 'Go to Automations',
        keys: [],
        hotkey: '',
        context: 'global',
        category: 'Navigation',
        paletteOnly: true,
        keywords: ['cron', 'scheduled', 'tasks', 'workflows'],
      },
      {
        id: 'go-feedback',
        label: 'Go to Feedback',
        keys: [],
        hotkey: '',
        context: 'global',
        category: 'Navigation',
        paletteOnly: true,
      },
    ],
  },
  {
    title: 'Project: Views',
    shortcuts: [
      {
        id: 'view-architecture',
        label: 'Switch to Architecture',
        keys: [modKey, '1'],
        hotkey: 'mod+1',
        context: 'project',
        category: 'Project: Views',
        keywords: ['diagram', 'graph', 'containers', 'structure'],
      },
      {
        id: 'view-preview',
        label: 'Switch to Preview',
        keys: [modKey, '2'],
        hotkey: 'mod+2',
        context: 'project',
        category: 'Project: Views',
        keywords: ['browser', 'app', 'run'],
      },
      {
        id: 'view-code',
        label: 'Switch to Code',
        keys: [modKey, '3'],
        hotkey: 'mod+3',
        context: 'project',
        category: 'Project: Views',
        keywords: ['editor', 'files', 'source'],
      },
      {
        id: 'view-design',
        label: 'Switch to Design',
        keys: [modKey, '4'],
        hotkey: 'mod+4',
        context: 'project',
        category: 'Project: Views',
        keywords: ['canvas', 'visual', 'edit'],
      },
      {
        id: 'view-kanban',
        label: 'Switch to Kanban',
        keys: [modKey, '5'],
        hotkey: 'mod+5',
        context: 'project',
        category: 'Project: Views',
        keywords: ['tasks', 'board', 'issues'],
      },
      {
        id: 'view-assets',
        label: 'Switch to Assets',
        keys: [modKey, '6'],
        hotkey: 'mod+6',
        context: 'project',
        category: 'Project: Views',
        keywords: ['images', 'files', 'media', 'uploads'],
      },
      {
        id: 'view-terminal',
        label: 'Switch to Terminal',
        keys: [modKey, '7'],
        hotkey: 'mod+7',
        context: 'project',
        category: 'Project: Views',
        keywords: ['console', 'shell', 'cli'],
      },
      {
        id: 'view-repository',
        label: 'Switch to Repository',
        keys: [modKey, '8'],
        hotkey: 'mod+8',
        context: 'project',
        category: 'Project: Views',
        keywords: ['git', 'github', 'branch', 'commit'],
      },
      {
        id: 'refresh-preview',
        label: 'Refresh preview',
        keys: [modKey, 'R'],
        hotkey: 'mod+r',
        context: 'project',
        category: 'Project: Views',
        keywords: ['reload', 'update'],
      },
      {
        id: 'preview-back',
        label: 'Navigate back in preview',
        keys: [altKey, '←'],
        hotkey: 'alt+left',
        context: 'project:preview',
        category: 'Project: Views',
      },
      {
        id: 'preview-forward',
        label: 'Navigate forward in preview',
        keys: [altKey, '→'],
        hotkey: 'alt+right',
        context: 'project:preview',
        category: 'Project: Views',
      },
    ],
  },
  {
    title: 'Project: Lifecycle',
    shortcuts: [
      {
        id: 'project-run',
        label: 'Start environment',
        keys: [modKey, 'E'],
        hotkey: 'mod+e',
        context: 'project',
        category: 'Project: Lifecycle',
        keywords: ['run', 'start', 'launch', 'up'],
      },
      {
        id: 'project-stop',
        label: 'Stop environment',
        keys: [modKey, shiftKey, 'E'],
        hotkey: 'mod+shift+e',
        context: 'project',
        category: 'Project: Lifecycle',
        keywords: ['halt', 'kill', 'down'],
      },
      {
        id: 'project-restart',
        label: 'Restart environment',
        keys: [modKey, shiftKey, 'R'],
        hotkey: 'mod+shift+r',
        context: 'project',
        category: 'Project: Lifecycle',
        keywords: ['reload', 'reboot', 'cycle'],
      },
      {
        id: 'project-publish',
        label: 'Publish as App…',
        keys: [],
        hotkey: '',
        context: 'project',
        category: 'Project: Lifecycle',
        paletteOnly: true,
        keywords: ['ship', 'release', 'marketplace'],
      },
      {
        id: 'project-fork',
        label: 'Fork project…',
        keys: [],
        hotkey: '',
        context: 'project',
        category: 'Project: Lifecycle',
        paletteOnly: true,
        keywords: ['copy', 'duplicate', 'branch'],
      },
      {
        id: 'project-rename',
        label: 'Rename project…',
        keys: [],
        hotkey: '',
        context: 'project',
        category: 'Project: Lifecycle',
        paletteOnly: true,
      },
      {
        id: 'project-overview',
        label: 'Open project overview',
        keys: [],
        hotkey: '',
        context: 'project',
        category: 'Project: Lifecycle',
        paletteOnly: true,
        keywords: ['summary', 'about', 'details'],
      },
    ],
  },
  {
    title: 'Project: Git',
    shortcuts: [
      {
        id: 'git-status',
        label: 'Toggle Git panel',
        keys: [modKey, shiftKey, 'G'],
        hotkey: 'mod+shift+g',
        context: 'project',
        category: 'Project: Git',
        keywords: ['version control', 'commit', 'push'],
      },
      {
        id: 'git-commit',
        label: 'Commit changes…',
        keys: [],
        hotkey: '',
        context: 'project',
        category: 'Project: Git',
        paletteOnly: true,
        keywords: ['stage', 'message', 'save'],
      },
      {
        id: 'git-push',
        label: 'Push to remote',
        keys: [],
        hotkey: '',
        context: 'project',
        category: 'Project: Git',
        paletteOnly: true,
        keywords: ['upload', 'send'],
      },
      {
        id: 'git-pull',
        label: 'Pull from remote',
        keys: [],
        hotkey: '',
        context: 'project',
        category: 'Project: Git',
        paletteOnly: true,
        keywords: ['download', 'fetch', 'sync'],
      },
      {
        id: 'git-create-branch',
        label: 'Create branch…',
        keys: [],
        hotkey: '',
        context: 'project',
        category: 'Project: Git',
        paletteOnly: true,
      },
      {
        id: 'git-switch-branch',
        label: 'Switch branch…',
        keys: [],
        hotkey: '',
        context: 'project',
        category: 'Project: Git',
        paletteOnly: true,
        keywords: ['checkout'],
      },
      {
        id: 'git-discard-changes',
        label: 'Discard all changes…',
        keys: [],
        hotkey: '',
        context: 'project',
        category: 'Project: Git',
        paletteOnly: true,
        keywords: ['reset', 'revert', 'undo'],
      },
    ],
  },
  {
    title: 'Project: Snapshots',
    shortcuts: [
      {
        id: 'snapshot-create',
        label: 'Create snapshot…',
        keys: [],
        hotkey: '',
        context: 'project',
        category: 'Project: Snapshots',
        paletteOnly: true,
        keywords: ['save', 'checkpoint', 'backup', 'version'],
      },
      {
        id: 'snapshot-restore',
        label: 'Restore snapshot…',
        keys: [],
        hotkey: '',
        context: 'project',
        category: 'Project: Snapshots',
        paletteOnly: true,
        keywords: ['rollback', 'load', 'revert'],
      },
      {
        id: 'snapshot-timeline',
        label: 'Open timeline',
        keys: [],
        hotkey: '',
        context: 'project',
        category: 'Project: Snapshots',
        paletteOnly: true,
        keywords: ['history', 'versions'],
      },
    ],
  },
  {
    title: 'Project: Code',
    shortcuts: [
      {
        id: 'quick-open-file',
        label: 'Quick open file…',
        keys: [modKey, 'P'],
        hotkey: 'mod+p',
        context: 'project',
        category: 'Project: Code',
        keywords: ['file', 'open', 'find', 'goto', 'navigate'],
      },
      {
        id: 'code-toggle-tree',
        label: 'Toggle file tree',
        keys: [],
        hotkey: '',
        context: 'project:code',
        category: 'Project: Code',
        paletteOnly: true,
      },
    ],
  },
  {
    title: 'Project: Architecture',
    shortcuts: [
      {
        id: 'toggle-architecture',
        label: 'Toggle Architecture panel',
        keys: [modKey, shiftKey, 'A'],
        hotkey: 'mod+shift+a',
        context: 'project',
        category: 'Project: Architecture',
      },
      {
        id: 'arch-auto-layout',
        label: 'Auto-layout diagram',
        keys: [],
        hotkey: '',
        context: 'project',
        category: 'Project: Architecture',
        paletteOnly: true,
        keywords: ['arrange', 'organize', 'layout'],
      },
      {
        id: 'arch-fit-view',
        label: 'Fit diagram to view',
        keys: [],
        hotkey: '',
        context: 'project',
        category: 'Project: Architecture',
        paletteOnly: true,
        keywords: ['zoom', 'reset'],
      },
      {
        id: 'arch-save-config',
        label: 'Save architecture config',
        keys: [],
        hotkey: '',
        context: 'project',
        category: 'Project: Architecture',
        paletteOnly: true,
      },
      {
        id: 'arch-load-config',
        label: 'Load architecture config',
        keys: [],
        hotkey: '',
        context: 'project',
        category: 'Project: Architecture',
        paletteOnly: true,
      },
    ],
  },
  {
    title: 'Project: Design',
    shortcuts: [
      {
        id: 'design-undo',
        label: 'Undo design edit',
        keys: [modKey, 'Z'],
        hotkey: 'mod+z',
        context: 'project:design',
        category: 'Project: Design',
      },
      {
        id: 'design-redo',
        label: 'Redo design edit',
        keys: [modKey, shiftKey, 'Z'],
        hotkey: 'mod+shift+z',
        context: 'project:design',
        category: 'Project: Design',
      },
      {
        id: 'design-delete',
        label: 'Delete selected element',
        keys: ['⌫'],
        hotkey: 'backspace',
        context: 'project:design',
        category: 'Project: Design',
      },
      {
        id: 'design-copy',
        label: 'Copy selected element',
        keys: [modKey, 'C'],
        hotkey: 'mod+c',
        context: 'project:design',
        category: 'Project: Design',
      },
      {
        id: 'design-paste',
        label: 'Paste element',
        keys: [modKey, 'V'],
        hotkey: 'mod+v',
        context: 'project:design',
        category: 'Project: Design',
      },
      {
        id: 'design-group',
        label: 'Group (wrap in div)',
        keys: [modKey, 'G'],
        hotkey: 'mod+g',
        context: 'project:design',
        category: 'Project: Design',
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
        label: 'Focus agent input',
        keys: [modKey, shiftKey, 'C'],
        hotkey: 'mod+shift+c',
        context: 'project',
        category: 'Chat',
        keywords: ['compose', 'cursor', 'input'],
      },
      {
        id: 'chat-new-session',
        label: 'New chat session',
        keys: [modKey, shiftKey, 'J'],
        hotkey: 'mod+shift+j',
        context: 'project',
        category: 'Chat',
        keywords: ['new', 'create', 'thread', 'conversation'],
      },
      {
        id: 'chat-next-session',
        label: 'Next chat session',
        keys: [modKey, ']'],
        hotkey: 'mod+]',
        context: 'project',
        category: 'Chat',
      },
      {
        id: 'chat-prev-session',
        label: 'Previous chat session',
        keys: [modKey, '['],
        hotkey: 'mod+[',
        context: 'project',
        category: 'Chat',
      },
      {
        id: 'chat-stop-agent',
        label: 'Stop running agent',
        keys: [modKey, '.'],
        hotkey: 'mod+.',
        context: 'project',
        category: 'Chat',
        keywords: ['cancel', 'halt', 'abort', 'interrupt'],
      },
      {
        id: 'chat-switch-model',
        label: 'Switch model…',
        keys: [],
        hotkey: '',
        context: 'project',
        category: 'Chat',
        paletteOnly: true,
        keywords: ['llm', 'agent', 'change', 'select'],
      },
      {
        id: 'chat-toggle-edit-mode',
        label: 'Toggle edit mode',
        keys: [],
        hotkey: '',
        context: 'project',
        category: 'Chat',
        paletteOnly: true,
        keywords: ['ask', 'plan', 'agent'],
      },
      {
        id: 'chat-clear',
        label: 'Clear chat history',
        keys: [],
        hotkey: '',
        context: 'project',
        category: 'Chat',
        paletteOnly: true,
        keywords: ['reset', 'wipe', 'empty'],
      },
      {
        id: 'chat-rename-session',
        label: 'Rename current session…',
        keys: [],
        hotkey: '',
        context: 'project',
        category: 'Chat',
        paletteOnly: true,
      },
      {
        id: 'chat-delete-session',
        label: 'Delete current session…',
        keys: [],
        hotkey: '',
        context: 'project',
        category: 'Chat',
        paletteOnly: true,
      },
      {
        id: 'chat-attach-file',
        label: 'Attach file to chat',
        keys: [],
        hotkey: '',
        context: 'project',
        category: 'Chat',
        paletteOnly: true,
        keywords: ['upload', 'add'],
      },
    ],
  },
  {
    title: 'Layout',
    shortcuts: [
      {
        id: 'toggle-left-sidebar',
        label: 'Toggle chat sidebar',
        keys: [modKey, 'B'],
        hotkey: 'mod+b',
        context: 'project',
        category: 'Layout',
        keywords: ['hide', 'show', 'sidebar', 'chat'],
      },
      {
        id: 'toggle-right-sidebar',
        label: 'Toggle right panel',
        keys: [modKey, '\\'],
        hotkey: 'mod+\\',
        context: 'project',
        category: 'Layout',
        keywords: ['hide', 'show', 'panel'],
      },
      {
        id: 'toggle-zen-mode',
        label: 'Toggle zen mode',
        keys: [modKey, shiftKey, '\\'],
        hotkey: 'mod+shift+\\',
        context: 'project',
        category: 'Layout',
        keywords: ['focus', 'fullscreen', 'distraction-free'],
      },
      {
        id: 'toggle-notes',
        label: 'Toggle Notes panel',
        keys: [modKey, shiftKey, 'N'],
        hotkey: 'mod+shift+n',
        context: 'project',
        category: 'Layout',
      },
      {
        id: 'toggle-settings',
        label: 'Toggle Settings panel',
        keys: [modKey, shiftKey, 'S'],
        hotkey: 'mod+shift+s',
        context: 'project',
        category: 'Layout',
      },
    ],
  },
  {
    title: 'Library',
    shortcuts: [
      {
        id: 'lib-agents',
        label: 'Library: Agents',
        keys: [],
        hotkey: '',
        context: 'global',
        category: 'Library',
        paletteOnly: true,
        keywords: ['library', 'agents', 'browse'],
      },
      {
        id: 'lib-models',
        label: 'Library: Models',
        keys: [],
        hotkey: '',
        context: 'global',
        category: 'Library',
        paletteOnly: true,
        keywords: ['llm', 'providers'],
      },
      {
        id: 'lib-themes',
        label: 'Library: Themes',
        keys: [],
        hotkey: '',
        context: 'global',
        category: 'Library',
        paletteOnly: true,
        keywords: ['appearance', 'colors'],
      },
      {
        id: 'lib-skills',
        label: 'Library: Skills',
        keys: [],
        hotkey: '',
        context: 'global',
        category: 'Library',
        paletteOnly: true,
        keywords: ['marketplace'],
      },
      {
        id: 'lib-connectors',
        label: 'Library: Connectors',
        keys: [],
        hotkey: '',
        context: 'global',
        category: 'Library',
        paletteOnly: true,
        keywords: ['mcp', 'integrations'],
      },
      {
        id: 'lib-mcp-servers',
        label: 'Library: MCP Servers',
        keys: [],
        hotkey: '',
        context: 'global',
        category: 'Library',
        paletteOnly: true,
        keywords: ['model context protocol'],
      },
      {
        id: 'lib-create-agent',
        label: 'New agent…',
        keys: [],
        hotkey: '',
        context: 'global',
        category: 'Library',
        paletteOnly: true,
        keywords: ['create', 'new', 'add'],
      },
      {
        id: 'lib-create-skill',
        label: 'New skill…',
        keys: [],
        hotkey: '',
        context: 'global',
        category: 'Library',
        paletteOnly: true,
      },
      {
        id: 'lib-create-theme',
        label: 'New theme…',
        keys: [],
        hotkey: '',
        context: 'global',
        category: 'Library',
        paletteOnly: true,
      },
      {
        id: 'lib-create-model',
        label: 'New model configuration…',
        keys: [],
        hotkey: '',
        context: 'global',
        category: 'Library',
        paletteOnly: true,
      },
    ],
  },
  {
    title: 'Settings',
    shortcuts: [
      {
        id: 'settings-profile',
        label: 'Settings: Profile',
        keys: [],
        hotkey: '',
        context: 'global',
        category: 'Settings',
        paletteOnly: true,
        keywords: ['account', 'name', 'avatar'],
      },
      {
        id: 'settings-preferences',
        label: 'Settings: Preferences',
        keys: [],
        hotkey: '',
        context: 'global',
        category: 'Settings',
        paletteOnly: true,
        keywords: ['theme', 'appearance', 'general'],
      },
      {
        id: 'settings-security',
        label: 'Settings: Security',
        keys: [],
        hotkey: '',
        context: 'global',
        category: 'Settings',
        paletteOnly: true,
        keywords: ['password', '2fa'],
      },
      {
        id: 'settings-api-keys',
        label: 'Settings: API Keys',
        keys: [],
        hotkey: '',
        context: 'global',
        category: 'Settings',
        paletteOnly: true,
        keywords: ['tokens', 'external', 'auth'],
      },
      {
        id: 'settings-billing',
        label: 'Settings: Billing',
        keys: [],
        hotkey: '',
        context: 'global',
        category: 'Settings',
        paletteOnly: true,
        keywords: ['plan', 'subscription', 'credits', 'payment'],
      },
      {
        id: 'settings-channels',
        label: 'Settings: Channels',
        keys: [],
        hotkey: '',
        context: 'global',
        category: 'Settings',
        paletteOnly: true,
        keywords: ['slack', 'discord', 'telegram', 'messaging'],
      },
      {
        id: 'settings-schedules',
        label: 'Settings: Schedules',
        keys: [],
        hotkey: '',
        context: 'global',
        category: 'Settings',
        paletteOnly: true,
        keywords: ['cron', 'recurring', 'agents'],
      },
      {
        id: 'settings-connections',
        label: 'Settings: Connections',
        keys: [],
        hotkey: '',
        context: 'global',
        category: 'Settings',
        paletteOnly: true,
        keywords: ['oauth', 'linked', 'integrations'],
      },
      {
        id: 'settings-deployment',
        label: 'Settings: Deployment',
        keys: [],
        hotkey: '',
        context: 'global',
        category: 'Settings',
        paletteOnly: true,
        keywords: ['vercel', 'netlify', 'cloudflare', 'providers'],
      },
      {
        id: 'settings-team',
        label: 'Settings: Team',
        keys: [],
        hotkey: '',
        context: 'global',
        category: 'Settings',
        paletteOnly: true,
        keywords: ['workspace', 'organization'],
      },
      {
        id: 'settings-team-members',
        label: 'Settings: Team Members',
        keys: [],
        hotkey: '',
        context: 'global',
        category: 'Settings',
        paletteOnly: true,
        keywords: ['invite', 'members', 'roles'],
      },
      {
        id: 'settings-audit-log',
        label: 'Settings: Audit Log',
        keys: [],
        hotkey: '',
        context: 'global',
        category: 'Settings',
        paletteOnly: true,
        keywords: ['history', 'events', 'security'],
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
        keywords: ['new', 'create', 'project', 'app'],
      },
      {
        id: 'import-project',
        label: 'Import repository',
        keys: [modKey, 'I'],
        hotkey: 'mod+i',
        context: 'dashboard',
        category: 'Dashboard',
        keywords: ['github', 'clone', 'import'],
      },
      {
        id: 'dash-toggle-cards',
        label: 'Toggle cards / list view',
        keys: [],
        hotkey: '',
        context: 'dashboard',
        category: 'Dashboard',
        paletteOnly: true,
        keywords: ['layout', 'grid'],
      },
      {
        id: 'dash-focus-search',
        label: 'Focus project search',
        keys: [],
        hotkey: '',
        context: 'dashboard',
        category: 'Dashboard',
        paletteOnly: true,
        keywords: ['filter', 'find'],
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
      // Note: a "Toggle filters" entry was previously declared here but the
      // marketplace UI doesn't expose a hideable filter pane. Removed to keep
      // the help modal honest. Add it back if MarketplaceBrowse grows a
      // collapsible filter sidebar.
    ],
  },
  {
    title: 'Diagnostics',
    shortcuts: [
      {
        id: 'diag-copy-debug',
        label: 'Copy debug info to clipboard',
        keys: [],
        hotkey: '',
        context: 'global',
        category: 'Diagnostics',
        paletteOnly: true,
        keywords: ['support', 'bug', 'report'],
      },
      {
        id: 'diag-container-logs',
        label: 'View container logs',
        keys: [],
        hotkey: '',
        context: 'project',
        category: 'Diagnostics',
        paletteOnly: true,
        keywords: ['errors', 'output', 'docker'],
      },
      {
        id: 'diag-restart-container',
        label: 'Restart container',
        keys: [],
        hotkey: '',
        context: 'project',
        category: 'Diagnostics',
        paletteOnly: true,
        keywords: ['reload', 'reboot'],
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
  return getAllShortcuts().filter((shortcut) => shortcutMatchesContext(shortcut, context));
}

/**
 * Get shortcut groups filtered for a specific context.
 * Excludes paletteOnly entries — those are surfaced in the palette only.
 */
export function getShortcutGroupsForContext(context: AppContext): ShortcutGroup[] {
  return shortcutGroups
    .map((group) => ({
      ...group,
      shortcuts: group.shortcuts.filter(
        (shortcut) => !shortcut.paletteOnly && shortcutMatchesContext(shortcut, context)
      ),
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
 * Get context from pathname.
 * For project routes, the second arg can specify the active view to refine
 * the context (e.g. 'design' → 'project:design'). When omitted, returns the
 * generic 'project' context.
 */
export function getContextFromPath(pathname: string, activeView?: string): AppContext {
  if (pathname.startsWith('/project/')) {
    if (activeView === 'design') return 'project:design';
    if (activeView === 'code') return 'project:code';
    if (activeView === 'preview') return 'project:preview';
    if (activeView === 'kanban') return 'project:kanban';
    if (activeView === 'architecture') return 'project:architecture';
    return 'project';
  }
  if (pathname.startsWith('/marketplace')) return 'marketplace';
  if (pathname.startsWith('/library')) return 'library';
  if (pathname.startsWith('/settings')) return 'settings';
  if (pathname.startsWith('/chat')) return 'global';
  if (pathname === '/dashboard' || pathname === '/' || pathname === '/home') return 'dashboard';
  return 'global';
}

function shortcutMatchesContext(shortcut: ShortcutDefinition, context: AppContext): boolean {
  const contexts = Array.isArray(shortcut.context) ? shortcut.context : [shortcut.context];
  if (contexts.includes('global')) return true;
  if (contexts.includes(context)) return true;
  // A 'project' shortcut is also valid in any project sub-context.
  if (context.startsWith('project') && contexts.includes('project')) return true;
  return false;
}
