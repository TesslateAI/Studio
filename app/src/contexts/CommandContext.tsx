/**
 * Command Context - Reliable Command Dispatching
 *
 * Replaces fragile CustomEvent dispatching with a context-based
 * command system that guarantees delivery and provides type safety.
 *
 * Features:
 * - Components register handlers for commands they own
 * - CommandPalette executes commands through context
 * - Commands fail gracefully with warnings if no handler registered
 * - No race conditions or missed events
 *
 * Usage:
 *
 * 1. Register handlers in components that own state:
 * ```tsx
 * function Project() {
 *   const [activeView, setActiveView] = useState('preview');
 *
 *   useCommandHandlers({
 *     switchView: setActiveView,
 *     togglePanel: (panel) => setActivePanel(prev => prev === panel ? null : panel),
 *   });
 * }
 * ```
 *
 * 2. Execute commands from CommandPalette:
 * ```tsx
 * function CommandPalette() {
 *   const { executeCommand, isCommandAvailable } = useCommands();
 *
 *   const handleSelect = () => {
 *     executeCommand('switchView', 'code');
 *   };
 * }
 * ```
 */

import {
  createContext,
  useContext,
  useCallback,
  useRef,
  useMemo,
  useEffect,
  type ReactNode,
} from 'react';

// =============================================================================
// Types
// =============================================================================

export type PanelType = 'github' | 'architecture' | 'notes' | 'settings' | 'marketplace' | null;

export type ViewType = 'preview' | 'code' | 'kanban' | 'assets' | 'terminal';

/**
 * All available command handlers that components can register
 */
export interface CommandHandlers {
  // Project view commands
  switchView: (view: ViewType) => void;
  togglePanel: (panel: Exclude<PanelType, null>) => void;
  refreshPreview: () => void;

  // Dashboard commands
  openCreateProject: () => void;

  // Chat commands
  focusChatInput: () => void;
  clearChat: () => void;

  // Editor commands
  saveFile: () => void;
  formatFile: () => void;
}

/**
 * Context value exposed to consumers
 */
interface CommandContextValue {
  /**
   * Register command handlers. Returns cleanup function.
   * Handlers are merged with existing handlers.
   */
  registerHandlers: (handlers: Partial<CommandHandlers>) => () => void;

  /**
   * Execute a command by name with arguments.
   * Returns true if handler was found and executed, false otherwise.
   */
  executeCommand: <K extends keyof CommandHandlers>(
    command: K,
    ...args: Parameters<CommandHandlers[K]>
  ) => boolean;

  /**
   * Check if a command has a registered handler.
   * Useful for showing/hiding commands in the palette.
   */
  isCommandAvailable: (command: keyof CommandHandlers) => boolean;

  /**
   * Get list of all currently available commands
   */
  getAvailableCommands: () => (keyof CommandHandlers)[];
}

// =============================================================================
// Context
// =============================================================================

const CommandContext = createContext<CommandContextValue | null>(null);

// =============================================================================
// Provider
// =============================================================================

interface CommandProviderProps {
  children: ReactNode;
}

export function CommandProvider({ children }: CommandProviderProps) {
  // Use ref to store handlers - avoids re-renders when handlers change
  const handlersRef = useRef<Partial<CommandHandlers>>({});

  /**
   * Register handlers from a component
   */
  const registerHandlers = useCallback((handlers: Partial<CommandHandlers>): (() => void) => {
    // Merge new handlers with existing
    handlersRef.current = { ...handlersRef.current, ...handlers };

    // Return cleanup function that removes these specific handlers
    return () => {
      const keys = Object.keys(handlers) as (keyof CommandHandlers)[];
      keys.forEach((key) => {
        // Only remove if it's the same handler that was registered
        if (handlersRef.current[key] === handlers[key]) {
          delete handlersRef.current[key];
        }
      });
    };
  }, []);

  /**
   * Execute a command by name
   */
  const executeCommand = useCallback(
    <K extends keyof CommandHandlers>(
      command: K,
      ...args: Parameters<CommandHandlers[K]>
    ): boolean => {
      const handler = handlersRef.current[command];

      if (handler) {
        try {
          // Cast to allow spreading args
          (handler as (...args: unknown[]) => void)(...args);
          return true;
        } catch (error) {
          console.error(`[Command] Error executing "${command}":`, error);
          return false;
        }
      }

      console.warn(
        `[Command] No handler registered for "${command}". ` +
          `Available commands: ${Object.keys(handlersRef.current).join(', ') || 'none'}`
      );
      return false;
    },
    []
  );

  /**
   * Check if a command is available
   */
  const isCommandAvailable = useCallback((command: keyof CommandHandlers): boolean => {
    return !!handlersRef.current[command];
  }, []);

  /**
   * Get list of available commands
   */
  const getAvailableCommands = useCallback((): (keyof CommandHandlers)[] => {
    return Object.keys(handlersRef.current) as (keyof CommandHandlers)[];
  }, []);

  const value = useMemo<CommandContextValue>(
    () => ({
      registerHandlers,
      executeCommand,
      isCommandAvailable,
      getAvailableCommands,
    }),
    [registerHandlers, executeCommand, isCommandAvailable, getAvailableCommands]
  );

  return <CommandContext.Provider value={value}>{children}</CommandContext.Provider>;
}

// =============================================================================
// Hooks
// =============================================================================

/**
 * Hook to access command context
 * Must be used within CommandProvider
 */
// eslint-disable-next-line react-refresh/only-export-components
export function useCommands(): CommandContextValue {
  const context = useContext(CommandContext);
  if (!context) {
    throw new Error('useCommands must be used within CommandProvider');
  }
  return context;
}

/**
 * Hook for components to register their command handlers
 * Automatically cleans up on unmount
 *
 * @param handlers - Object mapping command names to handler functions
 *
 * @example
 * ```tsx
 * function ProjectView() {
 *   const [activeView, setActiveView] = useState<ViewType>('preview');
 *   const [activePanel, setActivePanel] = useState<PanelType>(null);
 *
 *   useCommandHandlers({
 *     switchView: setActiveView,
 *     togglePanel: (panel) => {
 *       setActivePanel(prev => prev === panel ? null : panel);
 *     },
 *     refreshPreview: () => {
 *       iframeRef.current?.contentWindow?.location.reload();
 *     },
 *   });
 *
 *   // ... rest of component
 * }
 * ```
 */
// eslint-disable-next-line react-refresh/only-export-components
export function useCommandHandlers(handlers: Partial<CommandHandlers>): void {
  const { registerHandlers } = useCommands();

  useEffect(() => {
    // Register handlers and get cleanup function
    const cleanup = registerHandlers(handlers);

    // Cleanup on unmount or when handlers change
    return cleanup;
  }, [registerHandlers, handlers]);
}

/**
 * Hook that returns a function to execute a specific command
 * Useful when you need to call a command from event handlers
 *
 * @param command - The command name
 * @returns Function that executes the command with type-safe arguments
 *
 * @example
 * ```tsx
 * function MyButton() {
 *   const switchToCode = useCommandAction('switchView');
 *
 *   return (
 *     <button onClick={() => switchToCode('code')}>
 *       Switch to Code
 *     </button>
 *   );
 * }
 * ```
 */
// eslint-disable-next-line react-refresh/only-export-components
export function useCommandAction<K extends keyof CommandHandlers>(
  command: K
): (...args: Parameters<CommandHandlers[K]>) => boolean {
  const { executeCommand } = useCommands();

  return useCallback(
    (...args: Parameters<CommandHandlers[K]>) => {
      return executeCommand(command, ...args);
    },
    [executeCommand, command]
  );
}

// =============================================================================
// Exports
// =============================================================================

export { CommandContext };
export default CommandProvider;
