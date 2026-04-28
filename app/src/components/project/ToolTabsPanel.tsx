import { useRef, type ReactNode } from 'react';
import {
  BookOpen,
  Clock,
  Code as CodeIcon,
  Gear,
  GithubLogo,
  Image as ImageIcon,
  Kanban as KanbanIcon,
  Monitor,
  PencilRuler,
  SlidersHorizontal,
  Terminal as TerminalIcon,
  TreeStructure,
  X,
} from '@phosphor-icons/react';
import {
  DragDropContext,
  Droppable,
  Draggable,
  type DropResult,
} from '@hello-pangea/dnd';
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
    icon: <GithubLogo size={13} weight="bold" />,
  },
  'node-config': {
    id: 'node-config',
    label: 'Configure',
    icon: <SlidersHorizontal size={13} weight="bold" />,
  },
  config: {
    id: 'config',
    label: 'Config',
    icon: <SlidersHorizontal size={13} weight="bold" />,
  },
  volume: {
    id: 'volume',
    label: 'Snapshots',
    icon: <Clock size={13} weight="bold" />,
  },
  notes: {
    id: 'notes',
    label: 'Notes',
    icon: <BookOpen size={13} weight="bold" />,
  },
  settings: {
    id: 'settings',
    label: 'Settings',
    icon: <Gear size={13} weight="bold" />,
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
  onReorder?: (fromIndex: number, toIndex: number) => void;
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
  onReorder,
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

  const tabById: Record<string, TabInstance> = {};
  for (const t of tabs) tabById[t.id] = t;

  const handleDragEnd = (result: DropResult) => {
    if (!result.destination) return;
    const from = result.source.index;
    const to = result.destination.index;
    if (from === to) return;
    onReorder?.(from, to);
  };

  return (
    <div className="w-full h-full flex flex-col overflow-hidden bg-[var(--bg)]">
      {/* Tab strip — Chrome-style: rounded top, active merges with panel below */}
      <div className="flex items-end gap-0.5 h-9 px-2 pt-1.5 bg-[var(--surface)] flex-shrink-0 overflow-x-auto overflow-y-hidden snap-x [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden">
        <DragDropContext onDragEnd={handleDragEnd}>
          <Droppable droppableId="tool-tabs" direction="horizontal">
            {(dropProvided) => (
              <div
                ref={dropProvided.innerRef}
                {...dropProvided.droppableProps}
                className="flex items-end gap-0.5 h-full"
              >
                {tabs.map((tab, index) => {
                  const meta = TOOL_TAB_META[tab.type];
                  const isActive = activeTabId === tab.id;
                  const label = tabLabels[tab.id];
                  return (
                    <Draggable key={tab.id} draggableId={tab.id} index={index}>
                      {(dragProvided, snapshot) => {
                        // The previous version of this component overrode `role`,
                        // `onMouseDown`, and `onClick` AFTER spreading
                        // dragHandleProps — JSX prop ordering meant our handlers
                        // won. @hello-pangea/dnd uses dragHandleProps' role and
                        // event hooks to wire HTML5 drag, so overriding them
                        // broke drop. Now we don't override; we only add what
                        // the library doesn't set, and suppress the focus click
                        // during drag/drop animation so a stale click doesn't
                        // re-focus the source tab after a successful drop.
                        const suppressClick = snapshot.isDragging || snapshot.isDropAnimating;
                        return (
                          <div
                            ref={dragProvided.innerRef}
                            {...dragProvided.draggableProps}
                            {...dragProvided.dragHandleProps}
                            aria-selected={isActive}
                            onAuxClick={(e) => {
                              if (e.button === 1) {
                                e.preventDefault();
                                onClose(tab.id);
                              }
                            }}
                            onClick={() => {
                              if (suppressClick) return;
                              onFocus(tab.id);
                            }}
                            className={`group relative flex items-center gap-1.5 px-3.5 h-full text-[11px] font-medium cursor-pointer select-none whitespace-nowrap snap-start rounded-t-lg transition-all duration-150 ${
                              isActive
                                ? 'bg-[var(--bg)] text-[var(--text)] mb-[-1px] pb-[1px] z-10'
                                : 'text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-hover)]'
                            } ${snapshot.isDragging ? 'shadow-lg' : ''}`}
                          >
                            <span
                              className={`flex-shrink-0 transition-colors ${isActive ? 'text-[var(--primary)]' : ''}`}
                            >
                              {meta.icon}
                            </span>
                            <span>{label}</span>
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                onClose(tab.id);
                              }}
                              onMouseDown={(e) => e.stopPropagation()}
                              onPointerDown={(e) => e.stopPropagation()}
                              className={`w-4 h-4 flex items-center justify-center rounded-full transition-opacity hover:bg-[var(--surface-hover)] ${
                                isActive ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'
                              }`}
                              title={`Close ${label}`}
                              aria-label={`Close ${label}`}
                            >
                              <X size={10} weight="bold" />
                            </button>
                          </div>
                        );
                      }}
                    </Draggable>
                  );
                })}
                {dropProvided.placeholder}
              </div>
            )}
          </Droppable>
        </DragDropContext>
        {extraHeader && <div className="ml-auto flex items-center pr-2 pb-1">{extraHeader}</div>}
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
