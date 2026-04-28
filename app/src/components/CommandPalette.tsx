import { useState, useEffect, useMemo, useCallback, type ReactNode } from 'react';
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
  PencilRuler,
  Play,
  Stop,
  ArrowClockwise,
  Rocket,
  GitFork,
  Camera,
  ClockCounterClockwise,
  PaintBrush,
  CaretCircleDoubleRight,
  CaretCircleDoubleLeft,
  Chat,
  ChatCircle,
  Robot,
  Eraser,
  Paperclip,
  Files,
  Tree,
  CornersOut,
  FloppyDisk,
  Upload,
  Download,
  Plug,
  Bug,
  ListBullets,
  ArrowSquareOut,
  Sliders,
  CreditCard,
  Key,
  Users,
  ShieldCheck,
  CalendarBlank,
  ListChecks,
  Bell,
  Sparkle,
  House,
  Question,
  Lightning,
  PencilSimple,
  Trash,
  ListMagnifyingGlass,
  Sun,
} from '@phosphor-icons/react';
import { useCommands, type CommandHandlers } from '../contexts/CommandContext';
import {
  shortcutGroups,
  getContextFromPath,
  modKey,
  type AppContext,
  type ShortcutDefinition,
} from '../lib/keyboard-registry';

interface CommandPaletteProps {
  onShowShortcuts?: () => void;
}

// ---------------------------------------------------------------------------
// Icon registry — keyed by shortcut id (falls back to a generic icon).
// ---------------------------------------------------------------------------

const ICONS: Record<string, ReactNode> = {
  // General
  'show-shortcuts': <Question size={18} weight="fill" />,
  'show-shortcuts-alt': <Question size={18} weight="fill" />,
  'show-all-commands': <ListBullets size={18} weight="fill" />,
  'toggle-theme': <Sun size={18} weight="fill" />,
  'theme-pick': <PaintBrush size={18} weight="fill" />,

  // Navigation
  'go-dashboard': <Folder size={18} weight="fill" />,
  'go-marketplace': <Storefront size={18} weight="fill" />,
  'go-library': <Books size={18} weight="fill" />,
  'go-chat': <ChatCircle size={18} weight="fill" />,
  'go-settings': <Gear size={18} weight="fill" />,
  'go-automations': <Lightning size={18} weight="fill" />,
  'go-feedback': <Bell size={18} weight="fill" />,

  // Project: Views
  'view-architecture': <TreeStructure size={18} weight="fill" />,
  'view-preview': <Desktop size={18} weight="fill" />,
  'view-code': <Code size={18} weight="fill" />,
  'view-design': <PencilRuler size={18} weight="fill" />,
  'view-kanban': <Kanban size={18} weight="fill" />,
  'view-assets': <Images size={18} weight="fill" />,
  'view-terminal': <Terminal size={18} weight="fill" />,
  'view-repository': <GitBranch size={18} weight="fill" />,
  'refresh-preview': <ArrowsClockwise size={18} weight="bold" />,
  'preview-back': <CaretCircleDoubleLeft size={18} weight="fill" />,
  'preview-forward': <CaretCircleDoubleRight size={18} weight="fill" />,

  // Project: Lifecycle
  'project-run': <Play size={18} weight="fill" />,
  'project-stop': <Stop size={18} weight="fill" />,
  'project-restart': <ArrowClockwise size={18} weight="bold" />,
  'project-publish': <Rocket size={18} weight="fill" />,
  'project-fork': <GitFork size={18} weight="fill" />,
  'project-rename': <PencilSimple size={18} weight="fill" />,
  'project-overview': <House size={18} weight="fill" />,

  // Project: Git
  'git-status': <GitBranch size={18} weight="fill" />,
  'git-commit': <FloppyDisk size={18} weight="fill" />,
  'git-push': <Upload size={18} weight="bold" />,
  'git-pull': <Download size={18} weight="bold" />,
  'git-create-branch': <GitBranch size={18} weight="fill" />,
  'git-switch-branch': <GitBranch size={18} weight="fill" />,
  'git-discard-changes': <Eraser size={18} weight="fill" />,

  // Project: Snapshots
  'snapshot-create': <Camera size={18} weight="fill" />,
  'snapshot-restore': <ClockCounterClockwise size={18} weight="fill" />,
  'snapshot-timeline': <Clock size={18} weight="fill" />,

  // Project: Code
  'quick-open-file': <Files size={18} weight="fill" />,
  'code-toggle-tree': <Tree size={18} weight="fill" />,

  // Project: Architecture
  'toggle-architecture': <TreeStructure size={18} weight="fill" />,
  'arch-auto-layout': <Sliders size={18} weight="fill" />,
  'arch-fit-view': <CornersOut size={18} weight="fill" />,
  'arch-save-config': <FloppyDisk size={18} weight="fill" />,
  'arch-load-config': <Upload size={18} weight="fill" />,

  // Project: Design
  'design-undo': <ArrowClockwise size={18} weight="fill" />,
  'design-redo': <ArrowClockwise size={18} weight="fill" />,
  'design-delete': <Trash size={18} weight="fill" />,
  'design-copy': <Files size={18} weight="fill" />,
  'design-paste': <Files size={18} weight="fill" />,
  'design-group': <PencilRuler size={18} weight="fill" />,

  // Chat
  'send-message': <Chat size={18} weight="fill" />,
  'focus-chat': <Chat size={18} weight="fill" />,
  'chat-new-session': <Plus size={18} weight="bold" />,
  'chat-next-session': <CaretCircleDoubleRight size={18} weight="fill" />,
  'chat-prev-session': <CaretCircleDoubleLeft size={18} weight="fill" />,
  'chat-stop-agent': <Stop size={18} weight="fill" />,
  'chat-switch-model': <Robot size={18} weight="fill" />,
  'chat-toggle-edit-mode': <PencilSimple size={18} weight="fill" />,
  'chat-clear': <Eraser size={18} weight="fill" />,
  'chat-rename-session': <PencilSimple size={18} weight="fill" />,
  'chat-delete-session': <Trash size={18} weight="fill" />,
  'chat-attach-file': <Paperclip size={18} weight="fill" />,

  // Layout
  'toggle-left-sidebar': <ListBullets size={18} weight="fill" />,
  'toggle-right-sidebar': <ListBullets size={18} weight="fill" />,
  'toggle-zen-mode': <Sparkle size={18} weight="fill" />,
  'toggle-notes': <Note size={18} weight="fill" />,
  'toggle-settings': <Gear size={18} weight="fill" />,

  // Library
  'lib-agents': <Robot size={18} weight="fill" />,
  'lib-models': <Robot size={18} weight="fill" />,
  'lib-themes': <PaintBrush size={18} weight="fill" />,
  'lib-skills': <Sparkle size={18} weight="fill" />,
  'lib-connectors': <Plug size={18} weight="fill" />,
  'lib-mcp-servers': <Plug size={18} weight="fill" />,
  'lib-create-agent': <Plus size={18} weight="bold" />,
  'lib-create-skill': <Plus size={18} weight="bold" />,
  'lib-create-theme': <Plus size={18} weight="bold" />,
  'lib-create-model': <Plus size={18} weight="bold" />,

  // Settings
  'settings-profile': <Users size={18} weight="fill" />,
  'settings-preferences': <Sliders size={18} weight="fill" />,
  'settings-security': <ShieldCheck size={18} weight="fill" />,
  'settings-api-keys': <Key size={18} weight="fill" />,
  'settings-billing': <CreditCard size={18} weight="fill" />,
  'settings-channels': <ChatCircle size={18} weight="fill" />,
  'settings-schedules': <CalendarBlank size={18} weight="fill" />,
  'settings-connections': <Plug size={18} weight="fill" />,
  'settings-deployment': <Rocket size={18} weight="fill" />,
  'settings-team': <Users size={18} weight="fill" />,
  'settings-team-members': <Users size={18} weight="fill" />,
  'settings-audit-log': <ListChecks size={18} weight="fill" />,

  // Dashboard
  'new-project': <Plus size={18} weight="bold" />,
  'import-project': <ArrowSquareOut size={18} weight="bold" />,
  'dash-toggle-cards': <ListBullets size={18} weight="fill" />,
  'dash-focus-search': <ListMagnifyingGlass size={18} weight="fill" />,

  // Marketplace
  'focus-search': <ListMagnifyingGlass size={18} weight="fill" />,
  'toggle-filters': <Sliders size={18} weight="fill" />,

  // Diagnostics
  'diag-copy-debug': <Bug size={18} weight="fill" />,
  'diag-container-logs': <Terminal size={18} weight="fill" />,
  'diag-restart-container': <ArrowClockwise size={18} weight="bold" />,
};

const DEFAULT_ICON = <Sparkle size={18} weight="fill" />;

// ---------------------------------------------------------------------------
// Action builder — maps a registry id to a concrete callable.
// ---------------------------------------------------------------------------

interface ActionDeps {
  navigate: (to: string) => void;
  executeCommand: <K extends keyof CommandHandlers>(
    command: K,
    ...args: Parameters<CommandHandlers[K]>
  ) => boolean;
  isCommandAvailable: (command: keyof CommandHandlers) => boolean;
  onShowShortcuts?: () => void;
  enterBrowseMode: () => void;
  closePalette: () => void;
}

/**
 * Resolve the action for a given registry id.
 *
 * If the resolver returns `null`, the entry is treated as not currently
 * actionable (e.g. requires a context handler that isn't registered) and
 * gets filtered out of the palette.
 */
function resolveAction(id: string, deps: ActionDeps): (() => void) | null {
  const { navigate, executeCommand, isCommandAvailable, onShowShortcuts, enterBrowseMode } = deps;

  const requiresHandler = (
    handler: keyof CommandHandlers,
    fn: () => void
  ): (() => void) | null => (isCommandAvailable(handler) ? fn : null);

  switch (id) {
    // General
    case 'show-shortcuts':
    case 'show-shortcuts-alt':
      return () => onShowShortcuts?.();
    case 'show-all-commands':
      return () => enterBrowseMode();
    case 'toggle-theme':
      // Handled by global hotkey; palette entry navigates to Preferences.
      return () => navigate('/settings/preferences');
    case 'theme-pick':
      return () => navigate('/settings/preferences');

    // Navigation
    case 'go-dashboard':
      return () => navigate('/dashboard');
    case 'go-marketplace':
      return () => navigate('/marketplace');
    case 'go-library':
      return () => navigate('/library');
    case 'go-chat':
      return () => navigate('/chat');
    case 'go-settings':
      return () => navigate('/settings');
    case 'go-automations':
      return () => navigate('/automations');
    case 'go-feedback':
      return () => navigate('/feedback');

    // Project: Views — require switchView handler (i.e. inside a project)
    case 'view-architecture':
      return requiresHandler('switchView', () => executeCommand('switchView', 'architecture'));
    case 'view-preview':
      return requiresHandler('switchView', () => executeCommand('switchView', 'preview'));
    case 'view-code':
      return requiresHandler('switchView', () => executeCommand('switchView', 'code'));
    case 'view-design':
      return requiresHandler('switchView', () => executeCommand('switchView', 'design'));
    case 'view-kanban':
      return requiresHandler('switchView', () => executeCommand('switchView', 'kanban'));
    case 'view-assets':
      return requiresHandler('switchView', () => executeCommand('switchView', 'assets'));
    case 'view-terminal':
      return requiresHandler('switchView', () => executeCommand('switchView', 'terminal'));
    case 'view-repository':
      return requiresHandler('switchView', () => executeCommand('switchView', 'repository'));
    case 'refresh-preview':
      return requiresHandler('refreshPreview', () => executeCommand('refreshPreview'));

    // Project: Lifecycle
    case 'project-run':
      return requiresHandler('runProject', () => executeCommand('runProject'));
    case 'project-stop':
      return requiresHandler('stopProject', () => executeCommand('stopProject'));
    case 'project-restart':
      return requiresHandler('restartProject', () => executeCommand('restartProject'));
    case 'project-publish':
      return requiresHandler('publishProject', () => executeCommand('publishProject'));
    case 'project-fork':
      return requiresHandler('forkProject', () => executeCommand('forkProject'));
    case 'project-rename':
      return requiresHandler('renameProject', () => executeCommand('renameProject'));
    case 'project-overview':
      return requiresHandler('openProjectOverview', () => executeCommand('openProjectOverview'));

    // Project: Git
    case 'git-status':
      return requiresHandler('togglePanel', () => executeCommand('togglePanel', 'github'));
    case 'git-commit':
      return requiresHandler('gitCommit', () => executeCommand('gitCommit'));
    case 'git-push':
      return requiresHandler('gitPush', () => executeCommand('gitPush'));
    case 'git-pull':
      return requiresHandler('gitPull', () => executeCommand('gitPull'));
    case 'git-create-branch':
      return requiresHandler('gitCreateBranch', () => executeCommand('gitCreateBranch'));
    case 'git-switch-branch':
      return requiresHandler('gitSwitchBranch', () => executeCommand('gitSwitchBranch'));
    case 'git-discard-changes':
      return requiresHandler('gitDiscardChanges', () => executeCommand('gitDiscardChanges'));

    // Project: Snapshots
    case 'snapshot-create':
      return requiresHandler('createSnapshot', () => executeCommand('createSnapshot'));
    case 'snapshot-restore':
      return requiresHandler('restoreSnapshot', () => executeCommand('restoreSnapshot'));
    case 'snapshot-timeline':
      return requiresHandler('openTimeline', () => executeCommand('openTimeline'));

    // Project: Code
    case 'quick-open-file':
      return requiresHandler('openQuickFile', () => executeCommand('openQuickFile'));
    case 'code-toggle-tree':
      return requiresHandler('toggleFileTree', () => executeCommand('toggleFileTree'));

    // Project: Architecture
    case 'toggle-architecture':
      return requiresHandler('togglePanel', () => executeCommand('togglePanel', 'architecture'));
    case 'arch-auto-layout':
      return requiresHandler('archAutoLayout', () => executeCommand('archAutoLayout'));
    case 'arch-fit-view':
      return requiresHandler('archFitView', () => executeCommand('archFitView'));
    case 'arch-save-config':
      return requiresHandler('archSaveConfig', () => executeCommand('archSaveConfig'));
    case 'arch-load-config':
      return requiresHandler('archLoadConfig', () => executeCommand('archLoadConfig'));

    // Chat
    case 'focus-chat':
      return requiresHandler('focusChatInput', () => executeCommand('focusChatInput'));
    case 'chat-new-session':
      return requiresHandler('newChatSession', () => executeCommand('newChatSession'));
    case 'chat-next-session':
      return requiresHandler('nextChatSession', () => executeCommand('nextChatSession'));
    case 'chat-prev-session':
      return requiresHandler('prevChatSession', () => executeCommand('prevChatSession'));
    case 'chat-stop-agent':
      return requiresHandler('stopAgent', () => executeCommand('stopAgent'));
    case 'chat-switch-model':
      return requiresHandler('switchModel', () => executeCommand('switchModel'));
    case 'chat-toggle-edit-mode':
      return requiresHandler('toggleEditMode', () => executeCommand('toggleEditMode'));
    case 'chat-clear':
      return requiresHandler('clearChat', () => executeCommand('clearChat'));
    case 'chat-rename-session':
      return requiresHandler('renameChatSession', () => executeCommand('renameChatSession'));
    case 'chat-delete-session':
      return requiresHandler('deleteChatSession', () => executeCommand('deleteChatSession'));
    case 'chat-attach-file':
      return requiresHandler('attachChatFile', () => executeCommand('attachChatFile'));

    // Layout
    case 'toggle-left-sidebar':
      return requiresHandler('toggleLeftSidebar', () => executeCommand('toggleLeftSidebar'));
    case 'toggle-right-sidebar':
      return requiresHandler('toggleRightSidebar', () => executeCommand('toggleRightSidebar'));
    case 'toggle-zen-mode':
      return requiresHandler('toggleZenMode', () => executeCommand('toggleZenMode'));
    case 'toggle-notes':
      return requiresHandler('togglePanel', () => executeCommand('togglePanel', 'notes'));
    case 'toggle-settings':
      return requiresHandler('togglePanel', () => executeCommand('togglePanel', 'settings'));

    // Library jump-tos
    case 'lib-agents':
      return () => navigate('/library?tab=agents');
    case 'lib-models':
      return () => navigate('/library?tab=models');
    case 'lib-themes':
      return () => navigate('/library?tab=themes');
    case 'lib-skills':
      return () => navigate('/library?tab=skills');
    case 'lib-connectors':
      return () => navigate('/library?tab=connectors');
    case 'lib-mcp-servers':
      return () => navigate('/library?tab=mcp');
    case 'lib-create-agent':
      return () => navigate('/library?tab=agents&new=1');
    case 'lib-create-skill':
      return () => navigate('/library?tab=skills&new=1');
    case 'lib-create-theme':
      return () => navigate('/library?tab=themes&new=1');
    case 'lib-create-model':
      return () => navigate('/library?tab=models&new=1');

    // Settings jump-tos
    case 'settings-profile':
      return () => navigate('/settings/profile');
    case 'settings-preferences':
      return () => navigate('/settings/preferences');
    case 'settings-security':
      return () => navigate('/settings/security');
    case 'settings-api-keys':
      return () => navigate('/settings/api-keys');
    case 'settings-billing':
      return () => navigate('/settings/team/billing');
    case 'settings-channels':
      // Channels moved to Library → Channels. Command ID stays stable so any
      // user-bound keyboard shortcut keeps working.
      return () => navigate('/library?tab=channels');
    case 'settings-schedules':
      return () => navigate('/settings/messaging/schedules');
    case 'settings-connections':
      return () => navigate('/settings/messaging');
    case 'settings-deployment':
      return () => navigate('/settings/deployment');
    case 'settings-team':
      return () => navigate('/settings/team');
    case 'settings-team-members':
      return () => navigate('/settings/team/members');
    case 'settings-audit-log':
      return () => navigate('/settings/team/audit-log');

    // Dashboard
    case 'new-project':
      return () => {
        navigate('/dashboard');
        // Defer so the dashboard mounts and registers its handler.
        setTimeout(() => executeCommand('openCreateProject'), 100);
      };
    case 'import-project':
      return () => navigate('/import');
    case 'dash-toggle-cards':
    case 'dash-focus-search':
      // Page-scoped — bound directly by Dashboard.tsx via useHotkeys.
      return null;

    // Marketplace
    case 'focus-search':
    case 'toggle-filters':
      // Page-scoped — bound directly by MarketplaceBrowse.tsx.
      return null;

    // Diagnostics
    case 'diag-copy-debug':
      return requiresHandler('copyDebugInfo', () => executeCommand('copyDebugInfo'));
    case 'diag-container-logs':
      return requiresHandler('viewContainerLogs', () => executeCommand('viewContainerLogs'));
    case 'diag-restart-container':
      return requiresHandler('restartContainer', () => executeCommand('restartContainer'));

    // Help — alt ID, falls through to onShowShortcuts
    default:
      return null;
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const RECENT_KEY = 'tesslate-recent-commands';
const FREQ_KEY = 'tesslate-frequent-commands';
const RECENT_LIMIT = 5;
const FREQUENT_LIMIT = 5;

function loadJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

export function CommandPalette({ onShowShortcuts }: CommandPaletteProps) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [browseAll, setBrowseAll] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const { executeCommand, isCommandAvailable } = useCommands();

  const [recent, setRecent] = useState<string[]>(() => loadJson(RECENT_KEY, []));
  const [frequency, setFrequency] = useState<Record<string, number>>(() =>
    loadJson(FREQ_KEY, {})
  );

  // Open with Cmd+K (overrides browser save dialog)
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
      if (open) setOpen(false);
    },
    { enableOnFormTags: ['INPUT', 'TEXTAREA', 'SELECT'] }
  );

  const currentContext: AppContext = useMemo(
    () => getContextFromPath(location.pathname),
    [location.pathname]
  );

  const recordUsage = useCallback((id: string) => {
    setRecent((prev) => {
      const next = [id, ...prev.filter((i) => i !== id)].slice(0, RECENT_LIMIT);
      localStorage.setItem(RECENT_KEY, JSON.stringify(next));
      return next;
    });
    setFrequency((prev) => {
      const next = { ...prev, [id]: (prev[id] ?? 0) + 1 };
      localStorage.setItem(FREQ_KEY, JSON.stringify(next));
      return next;
    });
  }, []);

  const enterBrowseMode = useCallback(() => {
    setBrowseAll(true);
    setSearch('');
  }, []);

  const closePalette = useCallback(() => {
    setOpen(false);
    setSearch('');
    setBrowseAll(false);
  }, []);

  // Build the resolvable command set from the registry. Any entry whose
  // action resolves to null (handler not registered, or page-scoped) is
  // omitted — keeps the palette honest about what's actionable right now.
  const allItems = useMemo(() => {
    const deps: ActionDeps = {
      navigate,
      executeCommand,
      isCommandAvailable,
      onShowShortcuts,
      enterBrowseMode,
      closePalette,
    };
    return shortcutGroups.flatMap((group) =>
      group.shortcuts
        .map((s) => ({ shortcut: s, action: resolveAction(s.id, deps) }))
        .filter((entry): entry is { shortcut: ShortcutDefinition; action: () => void } =>
          entry.action !== null
        )
    );
  }, [navigate, executeCommand, isCommandAvailable, onShowShortcuts, enterBrowseMode, closePalette]);

  // Filter by current context (unless in browse-all mode).
  const contextItems = useMemo(() => {
    if (browseAll) return allItems;
    return allItems.filter(({ shortcut }) => shortcutInContext(shortcut, currentContext));
  }, [allItems, browseAll, currentContext]);

  // Recent (most recently invoked, intersected with currently-actionable).
  const recentItems = useMemo(
    () =>
      recent
        .map((id) => contextItems.find((item) => item.shortcut.id === id))
        .filter(Boolean) as typeof contextItems,
    [recent, contextItems]
  );

  // Frequent (top by usage, excluding entries already in Recent).
  const frequentItems = useMemo(() => {
    const sorted = [...contextItems].sort(
      (a, b) => (frequency[b.shortcut.id] ?? 0) - (frequency[a.shortcut.id] ?? 0)
    );
    return sorted
      .filter(({ shortcut }) => (frequency[shortcut.id] ?? 0) > 1)
      .filter(({ shortcut }) => !recent.includes(shortcut.id))
      .slice(0, FREQUENT_LIMIT);
  }, [contextItems, frequency, recent]);

  // Group remaining items by category for display.
  const grouped = useMemo(() => {
    const groups: Record<string, typeof contextItems> = {};
    contextItems.forEach((item) => {
      const cat = item.shortcut.category;
      if (!groups[cat]) groups[cat] = [];
      groups[cat].push(item);
    });
    // Preserve registry order
    const order = shortcutGroups.map((g) => g.title);
    return order
      .filter((title) => groups[title]?.length)
      .map((title) => ({ title, items: groups[title] }));
  }, [contextItems]);

  const handleSelect = useCallback(
    (item: { shortcut: ShortcutDefinition; action: () => void }) => {
      recordUsage(item.shortcut.id);
      closePalette();
      // Defer so the close transition runs before navigation reflows.
      requestAnimationFrame(() => item.action());
    },
    [recordUsage, closePalette]
  );

  useEffect(() => {
    if (!open) {
      setSearch('');
      setBrowseAll(false);
    }
  }, [open]);

  return (
    <Command.Dialog
      open={open}
      onOpenChange={setOpen}
      label="Command Menu"
      className="fixed inset-0 z-[100]"
      filter={(value, search) => {
        const id = value.replace(/^(recent-|frequent-)/, '');
        const entry = allItems.find((i) => i.shortcut.id === id);
        if (!entry) return 0;
        const s = search.toLowerCase();
        const sc = entry.shortcut;
        if (sc.label.toLowerCase().includes(s)) return 1;
        if (sc.category.toLowerCase().includes(s)) return 0.7;
        if (sc.keywords?.some((k) => k.toLowerCase().includes(s))) return 0.5;
        if (sc.id.toLowerCase().includes(s)) return 0.3;
        return 0;
      }}
    >
      <VisuallyHidden.Root>
        <Dialog.Title>Command Menu</Dialog.Title>
      </VisuallyHidden.Root>
      <VisuallyHidden.Root>
        <Dialog.Description>
          Search for commands, navigate to pages, or trigger actions.
        </Dialog.Description>
      </VisuallyHidden.Root>

      <div
        className="fixed inset-0 bg-black/50 backdrop-blur-sm"
        onClick={() => setOpen(false)}
        aria-hidden="true"
      />

      <div className="fixed top-[15%] left-1/2 -translate-x-1/2 w-full max-w-xl px-4">
        <Command
          className="bg-[var(--surface)] border border-[var(--border)] rounded-[var(--radius)] overflow-hidden"
          loop
        >
          <div className="flex items-center gap-3 border-b border-[var(--border)] px-4">
            <MagnifyingGlass size={20} className="text-[var(--text-subtle)] shrink-0" />
            <Command.Input
              value={search}
              onValueChange={setSearch}
              placeholder={
                browseAll ? 'Browsing all commands…' : 'Type a command or search…'
              }
              className="flex-1 bg-transparent py-4 text-[var(--text)] text-base outline-none focus:outline-none focus-visible:outline-none focus:ring-0 focus:border-transparent placeholder:text-[var(--text-subtle)] border-none shadow-none"
              autoFocus
            />
            {browseAll && (
              <span className="hidden sm:inline-flex px-2 py-1 text-[10px] uppercase tracking-wider bg-[var(--surface-hover)] text-[var(--text-muted)] rounded-[var(--radius-small)]">
                All
              </span>
            )}
            {search && (
              <button
                onClick={() => setSearch('')}
                className="p-1 rounded-[var(--radius-small)] hover:bg-[var(--surface-hover)] transition-colors"
                aria-label="Clear search"
              >
                <X size={16} className="text-[var(--text-subtle)]" />
              </button>
            )}
            <kbd className="hidden sm:flex px-2 py-1 text-xs bg-[var(--surface-hover)] rounded-[var(--radius-small)] text-[var(--text-muted)] font-mono">
              ESC
            </kbd>
          </div>

          <Command.List className="max-h-[420px] overflow-y-auto p-2">
            <Command.Empty className="py-8 text-center text-[var(--text-subtle)]">
              No results found.
            </Command.Empty>

            {/* Recent — shown only when search is empty */}
            {recentItems.length > 0 && !search && (
              <Command.Group
                heading={
                  <span className="flex items-center gap-2 text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider px-2 py-2">
                    <Clock size={14} />
                    Recent
                  </span>
                }
              >
                {recentItems.map((item) => (
                  <PaletteRow
                    key={`recent-${item.shortcut.id}`}
                    item={item}
                    valuePrefix="recent-"
                    onSelect={handleSelect}
                  />
                ))}
              </Command.Group>
            )}

            {/* Frequent — shown only when search is empty and we have signal */}
            {frequentItems.length > 0 && !search && (
              <Command.Group
                heading={
                  <span className="flex items-center gap-2 text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider px-2 py-2">
                    <Sparkle size={14} />
                    Frequent
                  </span>
                }
              >
                {frequentItems.map((item) => (
                  <PaletteRow
                    key={`frequent-${item.shortcut.id}`}
                    item={item}
                    valuePrefix="frequent-"
                    onSelect={handleSelect}
                  />
                ))}
              </Command.Group>
            )}

            {grouped.map(({ title, items }) => (
              <Command.Group
                key={title}
                heading={
                  <span className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider px-2 py-2 inline-block">
                    {title}
                  </span>
                }
              >
                {items.map((item) => (
                  <PaletteRow key={item.shortcut.id} item={item} onSelect={handleSelect} />
                ))}
              </Command.Group>
            ))}
          </Command.List>

          <div className="flex items-center justify-between px-4 py-2.5 border-t border-[var(--border)] text-xs text-[var(--text-subtle)]">
            <div className="flex items-center gap-4">
              <span className="flex items-center gap-1.5">
                <kbd className="px-1.5 py-0.5 bg-[var(--surface-hover)] rounded-[var(--radius-small)] font-mono">↑</kbd>
                <kbd className="px-1.5 py-0.5 bg-[var(--surface-hover)] rounded-[var(--radius-small)] font-mono">↓</kbd>
                <span>Navigate</span>
              </span>
              <span className="flex items-center gap-1.5">
                <kbd className="px-1.5 py-0.5 bg-[var(--surface-hover)] rounded-[var(--radius-small)] font-mono">↵</kbd>
                <span>Select</span>
              </span>
            </div>
            <span className="flex items-center gap-1.5">
              <kbd className="px-1.5 py-0.5 bg-[var(--surface-hover)] rounded-[var(--radius-small)] font-mono">ESC</kbd>
              <span>Close</span>
            </span>
          </div>
        </Command>
      </div>
    </Command.Dialog>
  );
}

function shortcutInContext(shortcut: ShortcutDefinition, context: AppContext): boolean {
  const contexts = Array.isArray(shortcut.context) ? shortcut.context : [shortcut.context];
  if (contexts.includes('global')) return true;
  if (contexts.includes(context)) return true;
  if (context.startsWith('project') && contexts.includes('project')) return true;
  return false;
}

function PaletteRow({
  item,
  onSelect,
  valuePrefix = '',
}: {
  item: { shortcut: ShortcutDefinition; action: () => void };
  onSelect: (item: { shortcut: ShortcutDefinition; action: () => void }) => void;
  valuePrefix?: string;
}) {
  const { shortcut } = item;
  const icon = ICONS[shortcut.id] ?? DEFAULT_ICON;
  const showKeys = shortcut.keys.length > 0 && !shortcut.paletteOnly;

  return (
    <Command.Item
      value={`${valuePrefix}${shortcut.id}`}
      onSelect={() => onSelect(item)}
      className="flex items-center gap-3 px-3 py-2.5 rounded-[var(--radius-small)] cursor-pointer
                 text-[var(--text)] transition-colors
                 data-[selected=true]:bg-[var(--surface-hover)] data-[selected=true]:text-[var(--text)]"
    >
      <span className="shrink-0 w-6 h-6 flex items-center justify-center text-[var(--text-muted)] data-[selected=true]:text-[var(--text)]">
        {icon}
      </span>
      <span className="flex-1 truncate">{shortcut.label}</span>
      {showKeys && (
        <span className="flex items-center gap-1 shrink-0">
          {shortcut.keys.map((key, i) => (
            <kbd
              key={i}
              className="px-1.5 py-0.5 text-xs bg-[var(--surface-hover)] rounded-[var(--radius-small)] text-[var(--text-muted)] font-mono"
            >
              {key === modKey ? modKey : key}
            </kbd>
          ))}
        </span>
      )}
    </Command.Item>
  );
}

export default CommandPalette;
