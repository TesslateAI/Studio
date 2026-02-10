# Keyboard Shortcuts & Command System

**Purpose**: This context provides guidance for working with the keyboard shortcuts registry, command palette, and command dispatch system in Tesslate Studio.

## When to Load This Context

Load this context when:
- Adding new keyboard shortcuts
- Modifying the command palette behavior
- Integrating new commands into pages
- Debugging keyboard shortcut issues
- Understanding the command dispatch architecture

## Key Files

| File | Purpose |
|------|---------|
| `app/src/lib/keyboard-registry.ts` | Central registry of all shortcuts with platform detection |
| `app/src/components/CommandPalette.tsx` | Cmd+K command palette UI using cmdk library |
| `app/src/components/KeyboardShortcutsModal.tsx` | "?" help modal showing all shortcuts |
| `app/src/contexts/CommandContext.tsx` | Command dispatch system replacing CustomEvent |

## Related Contexts

- **`docs/app/contexts/CLAUDE.md`**: Full CommandContext documentation with auth patterns
- **`docs/app/CLAUDE.md`**: Frontend overview and common patterns
- **`docs/app/pages/project-builder.md`**: Project page where most shortcuts are used

## Architecture

### Keyboard Registry

The keyboard registry (`keyboard-registry.ts`) is the single source of truth for all keyboard shortcuts in the application. It provides:

1. **Platform-Aware Display Keys**: Automatically shows correct modifier keys for Mac vs Windows/Linux
2. **Context-Aware Filtering**: Shortcuts are scoped to specific app contexts
3. **Centralized Definition**: All shortcuts defined in one place for consistency

```
┌─────────────────────────────────────────────────────────────────┐
│                    Keyboard Registry                             │
├─────────────────────────────────────────────────────────────────┤
│  ShortcutGroups[]                                               │
│  ├── General (command-palette, save-send, go-back, etc.)       │
│  ├── Navigation (dashboard, marketplace, library, settings)    │
│  ├── Dashboard (new-project, import-project)                   │
│  ├── Project Builder (view switching, panels, sidebars)        │
│  ├── Chat (send-message, focus-chat)                           │
│  └── Marketplace (focus-search, toggle-filters)                │
├─────────────────────────────────────────────────────────────────┤
│  Helper Functions                                               │
│  ├── getAllShortcuts() → ShortcutDefinition[]                  │
│  ├── getShortcutsForContext(ctx) → ShortcutDefinition[]        │
│  ├── getShortcutGroupsForContext(ctx) → ShortcutGroup[]        │
│  ├── findShortcutById(id) → ShortcutDefinition | undefined     │
│  └── getContextFromPath(pathname) → AppContext                 │
└─────────────────────────────────────────────────────────────────┘
```

### Context Types

```typescript
type AppContext =
  | 'global'           // Available everywhere
  | 'dashboard'        // Dashboard page only
  | 'project'          // Project builder page
  | 'project:preview'  // Project page, preview view active
  | 'project:code'     // Project page, code view active
  | 'project:kanban'   // Project page, kanban view active
  | 'project:chat'     // Project page, chat focused
  | 'marketplace'      // Marketplace pages
  | 'library'          // Library page
  | 'settings';        // Settings pages
```

### Command Context Pattern

The Command Context replaces fragile `CustomEvent` dispatching with a reliable, type-safe system:

```
┌─────────────────────┐     ┌─────────────────────┐
│   CommandPalette    │     │    Project Page     │
│                     │     │                     │
│  executeCommand() ──┼────►│  useCommandHandlers │
│                     │     │  - switchView       │
│  isCommandAvailable │     │  - togglePanel      │
│                     │     │  - refreshPreview   │
└─────────────────────┘     └─────────────────────┘
         │
         │  Commands execute
         │  through context
         ▼
┌─────────────────────┐
│  CommandContext     │
│                     │
│  handlersRef: {     │
│    switchView: fn,  │
│    togglePanel: fn, │
│    refreshPreview,  │
│  }                  │
└─────────────────────┘
```

**Why this pattern?**
- `CustomEvent` can be missed if listener registers after dispatch
- Context guarantees delivery when handler is registered
- Provides `isCommandAvailable()` to hide unavailable commands
- Type-safe: handler signatures enforced by TypeScript

### Key Functions

#### `getContextFromPath(pathname: string): AppContext`

Determines the current app context from the URL:

```typescript
getContextFromPath('/project/my-app')    // → 'project'
getContextFromPath('/marketplace')        // → 'marketplace'
getContextFromPath('/library')            // → 'library'
getContextFromPath('/settings')           // → 'settings'
getContextFromPath('/dashboard')          // → 'dashboard'
getContextFromPath('/')                   // → 'dashboard'
```

#### `getShortcutsForContext(context: AppContext): ShortcutDefinition[]`

Returns shortcuts relevant to a context (includes global shortcuts):

```typescript
const shortcuts = getShortcutsForContext('project');
// Returns: project shortcuts + global shortcuts
```

#### `getAllShortcuts(): ShortcutDefinition[]`

Returns all shortcuts as a flat array:

```typescript
const all = getAllShortcuts();
// Returns: every shortcut from all groups
```

## How to Add New Shortcuts

### Step 1: Add to Keyboard Registry

Add the shortcut definition to the appropriate group in `keyboard-registry.ts`:

```typescript
// In shortcutGroups array, find the relevant group
{
  title: 'Project Builder',
  shortcuts: [
    // ... existing shortcuts
    {
      id: 'my-new-shortcut',           // Unique identifier
      label: 'Do My Thing',            // User-visible label
      keys: [modKey, 'Y'],             // Display keys (uses platform vars)
      hotkey: 'mod+y',                 // react-hotkeys-hook format
      context: 'project',              // When shortcut is active
      category: 'Project Builder',     // For grouping in help modal
    },
  ],
},
```

### Step 2: Add Handler Type (if new command)

If this is a new command type, add it to `CommandContext.tsx`:

```typescript
export interface CommandHandlers {
  // ... existing handlers
  myNewCommand: (arg?: MyArgType) => void;
}
```

### Step 3: Register Handler in Component

In the component that owns the state:

```typescript
import { useCommandHandlers } from '../contexts/CommandContext';

function ProjectPage() {
  const [myState, setMyState] = useState('default');

  useCommandHandlers({
    myNewCommand: (arg) => {
      setMyState(arg ?? 'triggered');
    },
  });

  // ...
}
```

### Step 4: Add to Command Palette

Add the command to `CommandPalette.tsx`:

```typescript
const allCommands = useMemo<CommandItem[]>(() => {
  const commands: CommandItem[] = [
    // ... existing commands
    {
      id: 'my-new-shortcut',
      label: 'Do My Thing',
      icon: <MyIcon size={18} weight="fill" />,
      shortcut: [modKey, 'Y'],
      action: () => executeCommand('myNewCommand', optionalArg),
      context: 'project',
      keywords: ['thing', 'do', 'action'],  // For search
      group: 'Project',
    },
  ];
  return commands;
}, [/* deps */]);
```

### Step 5: Bind the Hotkey (if needed)

If the hotkey should work outside the command palette, use `react-hotkeys-hook`:

```typescript
import { useHotkeys } from 'react-hotkeys-hook';

useHotkeys(
  'mod+y',
  (e) => {
    e.preventDefault();
    executeCommand('myNewCommand');
  },
  {
    preventDefault: true,
    enableOnFormTags: false,  // Don't trigger in inputs
  }
);
```

## Shortcut Definition Structure

```typescript
interface ShortcutDefinition {
  id: string;              // Unique identifier (kebab-case)
  label: string;           // Human-readable label
  keys: string[];          // Display keys (e.g., ['⌘', 'K'])
  hotkey: string;          // react-hotkeys-hook format (e.g., 'mod+k')
  context: AppContext | AppContext[];  // Where shortcut is active
  category: string;        // Group name for help modal
  action?: () => void;     // Optional direct action
}
```

### Display Keys vs Hotkey Format

| Display Keys | Hotkey Format | Notes |
|--------------|---------------|-------|
| `[modKey, 'K']` | `'mod+k'` | Cmd on Mac, Ctrl on Windows |
| `[altKey, '←']` | `'alt+left'` | Option on Mac, Alt on Windows |
| `[shiftKey, 'G']` | `'shift+g'` | Same on all platforms |
| `['⌃', '↵']` | `'ctrl+enter'` | Ctrl+Enter (not mod) |
| `['?']` | `'shift+/'` | Question mark key |

## Common Issues and Troubleshooting

### Issue: Shortcut Not Working

**Symptom**: Pressing the keyboard shortcut does nothing

**Checklist**:
1. Is the component with `useCommandHandlers` mounted?
2. Is the context correct for the current page?
3. Is the hotkey binding registered with `useHotkeys`?
4. Is a form element (input/textarea) focused? Check `enableOnFormTags`

**Debug**:
```typescript
// Check if command handler is registered
const { isCommandAvailable, getAvailableCommands } = useCommands();
console.log('Available:', getAvailableCommands());
console.log('My command available:', isCommandAvailable('myCommand'));
```

### Issue: Command Palette Shows Command but It Doesn't Execute

**Symptom**: Command appears in palette but nothing happens when selected

**Solution**: Handler not registered. Ensure the owning component is mounted:

```typescript
// Handler is only available when ProjectPage is rendered
{activeRoute === 'project' && <ProjectPage />}

// Check console for warning:
// "[Command] No handler registered for 'switchView'"
```

### Issue: Shortcut Conflicts with Browser

**Symptom**: Browser handles the shortcut instead of the app

**Solution**: Use `preventDefault` in hotkey options:

```typescript
useHotkeys(
  'mod+s',  // Browser save
  (e) => {
    e.preventDefault();
    e.stopPropagation();
    handleSave();
  },
  { preventDefault: true }
);
```

### Issue: Shortcuts Triggering in Text Inputs

**Symptom**: Typing triggers shortcuts while in form fields

**Solution**: Disable in form tags or check active element:

```typescript
useHotkeys(
  'n',
  () => createNew(),
  {
    enableOnFormTags: false,  // Don't trigger in inputs
  }
);

// Or manually check:
useHotkeys('n', () => {
  if (['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName || '')) {
    return;
  }
  createNew();
});
```

### Issue: Platform-Specific Display Issues

**Symptom**: Wrong modifier key shown (Cmd on Windows, Ctrl on Mac)

**Solution**: Always use the platform variables from keyboard-registry:

```typescript
import { modKey, altKey, shiftKey } from '../lib/keyboard-registry';

// Correct
keys: [modKey, 'K']  // Shows ⌘ on Mac, Ctrl on Windows

// Wrong
keys: ['Ctrl', 'K']  // Always shows Ctrl
```

## File Organization

```
app/src/
├── lib/
│   └── keyboard-registry.ts    # Central shortcut definitions
├── components/
│   ├── CommandPalette.tsx      # Cmd+K palette using cmdk
│   └── KeyboardShortcutsModal.tsx  # "?" help modal
├── contexts/
│   └── CommandContext.tsx      # Command dispatch system
└── pages/
    └── Project.tsx             # Example: registers view/panel handlers
```

## Dependencies

| Package | Purpose |
|---------|---------|
| `cmdk` | Command palette UI (shadcn-based) |
| `react-hotkeys-hook` | Keyboard shortcut binding |
| `@radix-ui/react-dialog` | Modal accessibility |
| `@radix-ui/react-visually-hidden` | Screen reader support |

## Best Practices

### 1. Always Use Platform Variables

```typescript
// Good
keys: [modKey, shiftKey, 'G']

// Bad
keys: ['Ctrl', 'Shift', 'G']
```

### 2. Group Related Shortcuts

Keep shortcuts organized by category for the help modal:

```typescript
{
  title: 'My Feature',
  shortcuts: [
    { id: 'feature-action-1', category: 'My Feature', ... },
    { id: 'feature-action-2', category: 'My Feature', ... },
  ],
}
```

### 3. Provide Search Keywords

Add keywords to help users find commands:

```typescript
{
  id: 'toggle-git',
  label: 'Toggle Git Panel',
  keywords: ['version control', 'commit', 'push', 'github'],
  // ...
}
```

### 4. Clean Up Handlers

`useCommandHandlers` auto-cleans, but for manual registration:

```typescript
useEffect(() => {
  const cleanup = registerHandlers({ myCommand: handler });
  return cleanup;  // Important!
}, []);
```

### 5. Check Handler Availability Before Showing

Hide commands that can't execute:

```typescript
const contextCommands = allCommands.filter((cmd) => {
  const handlerName = commandToHandlerMap[cmd.id];
  if (handlerName) {
    return isCommandAvailable(handlerName);
  }
  return true;
});
```

## Quick Reference: Current Shortcuts

### Global (Available Everywhere)
| Shortcut | Action |
|----------|--------|
| `Cmd/Ctrl + K` | Open command palette |
| `?` | Show keyboard shortcuts |
| `Cmd/Ctrl + D` | Go to Dashboard |
| `Cmd/Ctrl + M` | Go to Marketplace |
| `Cmd/Ctrl + L` | Go to Library |
| `Cmd/Ctrl + ,` | Go to Settings |
| `Cmd/Ctrl + T` | Toggle theme |
| `Escape` | Go back / Close |

### Project Builder
| Shortcut | Action |
|----------|--------|
| `Cmd/Ctrl + 1-5` | Switch view (Preview/Code/Kanban/Assets/Terminal) |
| `Cmd/Ctrl + R` | Refresh preview |
| `Cmd/Ctrl + Shift + G` | Toggle Git panel |
| `Cmd/Ctrl + Shift + N` | Toggle Notes panel |
| `Cmd/Ctrl + Shift + S` | Toggle Settings panel |
| `Cmd/Ctrl + B` | Toggle left sidebar |
| `Cmd/Ctrl + .` | Toggle right sidebar |
| `Cmd/Ctrl + Shift + C` | Focus chat input |
| `Alt + Left/Right` | Navigate back/forward in preview |

### Dashboard
| Shortcut | Action |
|----------|--------|
| `Cmd/Ctrl + N` | Create new project |
| `Cmd/Ctrl + I` | Import repository |

### Marketplace
| Shortcut | Action |
|----------|--------|
| `/` | Focus search |
| `F` | Toggle filters |
