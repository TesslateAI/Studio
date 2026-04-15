import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';

/**
 * Tracks which Architecture nodes currently have a pending agent-driven
 * config prompt open. Consumed by ArchitectureView to render a pulsing ring.
 */
export interface NodeConfigPendingContextValue {
  isPending: (containerId: string) => boolean;
  markPending: (containerId: string) => void;
  clearPending: (containerId: string) => void;
}

const NodeConfigPendingContext = createContext<NodeConfigPendingContextValue | null>(null);

export function NodeConfigPendingProvider({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<Set<string>>(() => new Set());

  const isPending = useCallback(
    (containerId: string) => pending.has(containerId),
    [pending]
  );

  const markPending = useCallback((containerId: string) => {
    setPending((prev) => {
      if (prev.has(containerId)) return prev;
      const next = new Set(prev);
      next.add(containerId);
      return next;
    });
  }, []);

  const clearPending = useCallback((containerId: string) => {
    setPending((prev) => {
      if (!prev.has(containerId)) return prev;
      const next = new Set(prev);
      next.delete(containerId);
      return next;
    });
  }, []);

  const value = useMemo<NodeConfigPendingContextValue>(
    () => ({ isPending, markPending, clearPending }),
    [isPending, markPending, clearPending]
  );

  return (
    <NodeConfigPendingContext.Provider value={value}>
      {children}
    </NodeConfigPendingContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useNodeConfigPending(): NodeConfigPendingContextValue {
  const ctx = useContext(NodeConfigPendingContext);
  if (!ctx) {
    // Safe default: no-op when no provider is mounted (e.g. stand-alone tests).
    return {
      isPending: () => false,
      markPending: () => {},
      clearPending: () => {},
    };
  }
  return ctx;
}
