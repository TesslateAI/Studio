import { useRef, type ReactNode } from 'react';
import {
  Code as CodeIcon,
  Folders,
  Image as ImageIcon,
  Kanban as KanbanIcon,
  Monitor,
  PencilRuler,
  SlidersHorizontal,
  Terminal as TerminalIcon,
  TreeStructure,
  X,
} from '@phosphor-icons/react';
import type { TabInstance, ToolType } from '../../hooks/useToolDock';

export interface ToolTabMeta {
  id: ToolType;
  label: string;
  icon: ReactNode;
}

// eslint-disable-next-line react-refresh/only-export-components
export const TOOL_TAB_META: Record<ToolType, ToolTabMeta> = {
  architecture: {
    id: 'architecture',
    label: 'Architecture',
    icon: <TreeStructure size={13} weight="bold" />,
  },
  preview: {
    id: 'preview',
    label: 'Preview',
    icon: <Monitor size={13} weight="bold" />,
  },
  code: {
    id: 'code',
    label: 'Code',
    icon: <CodeIcon size={13} weight="bold" />,
  },
  design: {
    id: 'design',
    label: 'Design',
    icon: <PencilRuler size={13} weight="bold" />,
  },
  kanban: {
    id: 'kanban',
    label: 'Kanban',
    icon: <KanbanIcon size={13} weight="bold" />,
  },
  assets: {
    id: 'assets',
    label: 'Assets',
    icon: <ImageIcon size={13} weight="bold" />,
  },
  terminal: {
    id: 'terminal',
    label: 'Terminal',
    icon: <TerminalIcon size={13} weight="bold" />,
  },
  repository: {
    id: 'repository',
    label: 'Repository',
    icon: <Folders size={13} weight="bold" />,
  },
  'node-config': {
    id: 'node-config',
    label: 'Configure',
    icon: <SlidersHorizontal size={13} weight="bold" />,
  },
};

export type TabRenderer = (tab: TabInstance, indexWithinType: number) => ReactNode;

export interface ToolTabsPanelProps {
  tabs: TabInstance[];
  activeTabId: string | null;
  onFocus: (id: string) => void;
  onClose: (id: string) => void;
  renderers: Partial<Record<ToolType, TabRenderer>>;
  extraHeader?: ReactNode;
}

/**
 * VS Code-style tab strip with keep-alive content panel below.
 *
 * Tabs are keyed by instance id, so multiple tabs of the same `ToolType`
 * each get their own mounted React subtree with independent state.
 */
export function ToolTabsPanel({
  tabs,
  activeTabId,
  onFocus,
  onClose,
  renderers,
  extraHeader,
}: ToolTabsPanelProps) {
  // Every tab instance that has been rendered at least once stays mounted
  // until it's explicitly closed, preserving per-instance state.
  const mountedRef = useRef<Set<string>>(new Set());

  if (activeTabId) mountedRef.current.add(activeTabId);
  const liveIds = new Set(tabs.map((t) => t.id));
  mountedRef.current.forEach((id) => {
    if (!liveIds.has(id)) mountedRef.current.delete(id);
  });

  // For duplicate-type tabs, label them "Preview", "Preview 2", "Preview 3", …
  const typeSequence: Record<string, number> = {};
  const tabLabels: Record<string, string> = {};
  for (const t of tabs) {
    typeSequence[t.type] = (typeSequence[t.type] ?? 0) + 1;
    const seq = typeSequence[t.type];
    const base = TOOL_TAB_META[t.type].label;
    tabLabels[t.id] = seq === 1 ? base : `${base} ${seq}`;
  }

  const handleTabMouseDown = (e: React.MouseEvent, id: string) => {
    if (e.button === 1) {
      e.preventDefault();
      onClose(id);
    }
  };

  const tabById: Record<string, TabInstance> = {};
  for (const t of tabs) tabById[t.id] = t;

  return (
    <div className="w-full h-full flex flex-col overflow-hidden bg-[var(--bg)]">
      {/* Tab strip */}
      <div className="flex items-center h-8 border-b border-[var(--border)] bg-[var(--surface)] flex-shrink-0 overflow-x-auto">
        {tabs.map((tab) => {
          const meta = TOOL_TAB_META[tab.type];
          const isActive = activeTabId === tab.id;
          const label = tabLabels[tab.id];
          return (
            <div
              key={tab.id}
              role="tab"
              aria-selected={isActive}
              onClick={() => onFocus(tab.id)}
              onMouseDown={(e) => handleTabMouseDown(e, tab.id)}
              className={`group flex items-center gap-1.5 px-3 h-full text-[11px] cursor-pointer border-r border-[var(--border)] select-none transition-colors ${
                isActive
                  ? 'bg-[var(--bg)] text-[var(--text)]'
                  : 'text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-hover)]'
              }`}
            >
              <span className={`flex-shrink-0 ${isActive ? 'text-[var(--primary)]' : ''}`}>
                {meta.icon}
              </span>
              <span className="whitespace-nowrap">{label}</span>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onClose(tab.id);
                }}
                className={`w-4 h-4 flex items-center justify-center rounded hover:bg-[var(--surface-hover)] ${
                  isActive ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'
                }`}
                title={`Close ${label}`}
                aria-label={`Close ${label}`}
              >
                <X size={10} weight="bold" />
              </button>
            </div>
          );
        })}
        {extraHeader && <div className="ml-auto flex items-center pr-2">{extraHeader}</div>}
      </div>

      {/* Content — keep-alive, CSS hide/show */}
      <div className="flex-1 relative overflow-hidden">
        {Array.from(mountedRef.current).map((id) => {
          const tab = tabById[id];
          if (!tab) return null;
          const render = renderers[tab.type];
          if (!render) return null;
          const sameType = tabs.filter((t) => t.type === tab.type);
          const indexWithinType = sameType.findIndex((t) => t.id === tab.id);
          return (
            <div key={id} className={`absolute inset-0 ${activeTabId === id ? 'block' : 'hidden'}`}>
              {render(tab, indexWithinType)}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default ToolTabsPanel;
