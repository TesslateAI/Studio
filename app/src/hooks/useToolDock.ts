import { useCallback, useEffect, useMemo, useState } from 'react';

export type ToolType =
  | 'architecture'
  | 'preview'
  | 'code'
  | 'design'
  | 'kanban'
  | 'assets'
  | 'terminal';

export const TOOL_TYPES: ToolType[] = [
  'architecture',
  'preview',
  'code',
  'design',
  'kanban',
  'assets',
  'terminal',
];

export interface TabInstance {
  id: string;
  type: ToolType;
}

export interface DockState {
  tabs: TabInstance[];
  activeTabId: string | null;
}

const DEFAULT_STATE: DockState = {
  tabs: [],
  activeTabId: null,
};

const storageKey = (slug: string | undefined) =>
  slug ? `tesslate-dock-${slug}` : null;

function isToolType(value: unknown): value is ToolType {
  return typeof value === 'string' && (TOOL_TYPES as string[]).includes(value);
}

function sanitize(raw: unknown): DockState {
  if (!raw || typeof raw !== 'object') return DEFAULT_STATE;
  const r = raw as Record<string, unknown>;
  const rawTabs = Array.isArray(r.tabs) ? r.tabs : [];
  const tabs: TabInstance[] = [];
  for (const t of rawTabs) {
    if (!t || typeof t !== 'object') continue;
    const tt = t as Record<string, unknown>;
    const type = tt.type;
    const id = tt.id;
    if (isToolType(type) && typeof id === 'string' && id.length > 0) {
      tabs.push({ id, type });
    }
  }
  const activeTabId =
    typeof r.activeTabId === 'string' && tabs.some((t) => t.id === r.activeTabId)
      ? (r.activeTabId as string)
      : (tabs[tabs.length - 1]?.id ?? null);
  return { tabs, activeTabId };
}

function loadInitial(slug: string | undefined): DockState {
  if (typeof window === 'undefined') return DEFAULT_STATE;
  const key = storageKey(slug);
  if (!key) return DEFAULT_STATE;
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return DEFAULT_STATE;
    return sanitize(JSON.parse(raw));
  } catch {
    return DEFAULT_STATE;
  }
}

let tabIdCounter = 0;
function makeTabId(type: ToolType): string {
  tabIdCounter += 1;
  return `${type}-${Date.now().toString(36)}-${tabIdCounter}`;
}

export interface UseToolDockResult {
  state: DockState;
  isOpen: boolean;
  /** Focus the first tab of this type, or create a new tab if none exists. */
  openTool: (type: ToolType) => void;
  /** Always create a new tab of this type (⇧-click / "new tab" affordance). */
  openToolNew: (type: ToolType) => void;
  /** Close a specific tab instance. */
  closeTab: (id: string) => void;
  /** Close every tab of a given type. */
  closeType: (type: ToolType) => void;
  /** Focus an existing tab instance. */
  focusTab: (id: string) => void;
  closeAll: () => void;
  /** Count of open instances for a given type. */
  countOf: (type: ToolType) => number;
  /** Is at least one tab of this type open? */
  hasType: (type: ToolType) => boolean;
  /** Is the currently focused tab of this type? */
  isActiveType: (type: ToolType) => boolean;
}

export function useToolDock(slug: string | undefined): UseToolDockResult {
  const [state, setState] = useState<DockState>(() => loadInitial(slug));

  useEffect(() => {
    setState(loadInitial(slug));
  }, [slug]);

  useEffect(() => {
    const key = storageKey(slug);
    if (!key) return;
    try {
      window.localStorage.setItem(key, JSON.stringify(state));
    } catch {
      // ignore quota errors
    }
  }, [slug, state]);

  const openTool = useCallback((type: ToolType) => {
    setState((prev) => {
      const existing = prev.tabs.find((t) => t.type === type);
      if (existing) {
        if (prev.activeTabId === existing.id) return prev;
        return { ...prev, activeTabId: existing.id };
      }
      const tab: TabInstance = { id: makeTabId(type), type };
      return { tabs: [...prev.tabs, tab], activeTabId: tab.id };
    });
  }, []);

  const openToolNew = useCallback((type: ToolType) => {
    setState((prev) => {
      const tab: TabInstance = { id: makeTabId(type), type };
      return { tabs: [...prev.tabs, tab], activeTabId: tab.id };
    });
  }, []);

  const closeTab = useCallback((id: string) => {
    setState((prev) => {
      if (!prev.tabs.some((t) => t.id === id)) return prev;
      const idx = prev.tabs.findIndex((t) => t.id === id);
      const tabs = prev.tabs.filter((t) => t.id !== id);
      let activeTabId = prev.activeTabId;
      if (prev.activeTabId === id) {
        activeTabId = tabs[Math.max(0, idx - 1)]?.id ?? tabs[0]?.id ?? null;
      }
      return { tabs, activeTabId };
    });
  }, []);

  const closeType = useCallback((type: ToolType) => {
    setState((prev) => {
      const tabs = prev.tabs.filter((t) => t.type !== type);
      const activeTabId = tabs.some((t) => t.id === prev.activeTabId)
        ? prev.activeTabId
        : (tabs[tabs.length - 1]?.id ?? null);
      return { tabs, activeTabId };
    });
  }, []);

  const focusTab = useCallback((id: string) => {
    setState((prev) => {
      if (!prev.tabs.some((t) => t.id === id)) return prev;
      if (prev.activeTabId === id) return prev;
      return { ...prev, activeTabId: id };
    });
  }, []);

  const closeAll = useCallback(() => {
    setState({ tabs: [], activeTabId: null });
  }, []);

  const countOf = useCallback(
    (type: ToolType) => state.tabs.filter((t) => t.type === type).length,
    [state]
  );

  const hasType = useCallback(
    (type: ToolType) => state.tabs.some((t) => t.type === type),
    [state]
  );

  const isActiveType = useCallback(
    (type: ToolType) => {
      const active = state.tabs.find((t) => t.id === state.activeTabId);
      return active?.type === type;
    },
    [state]
  );

  const isOpen = state.tabs.length > 0;

  return useMemo(
    () => ({
      state,
      isOpen,
      openTool,
      openToolNew,
      closeTab,
      closeType,
      focusTab,
      closeAll,
      countOf,
      hasType,
      isActiveType,
    }),
    [
      state,
      isOpen,
      openTool,
      openToolNew,
      closeTab,
      closeType,
      focusTab,
      closeAll,
      countOf,
      hasType,
      isActiveType,
    ]
  );
}
