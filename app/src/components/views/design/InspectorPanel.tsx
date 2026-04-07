import React from 'react';
import { ChatContainer } from '../../chat/ChatContainer';
import VisualTab from './VisualTab';
import InspectorTab from './InspectorTab';
import type { ClassInfo, ElementInfo } from '../../../utils/classDetection';
import type { ElementData } from './DesignBridge';

interface InspectorPanelProps {
  activeTab: 'visual' | 'inspector' | 'ai';
  onTabChange: (tab: 'visual' | 'inspector' | 'ai') => void;
  // Visual tab
  cursorClasses: ClassInfo | null;
  editorRef: unknown;
  // Inspector tab
  selectedElement: ElementData | null;
  cursorElement: ElementInfo | null;
  // Style editing callbacks (sent to bridge for live preview)
  onStyleUpdate?: (designId: string, property: string, value: string) => void;
  onStyleRemove?: (designId: string, property: string) => void;
  onClassUpdate?: (designId: string, classes: string[]) => void;
  // AI tab
  chatProps: Record<string, unknown>;
}

const TABS: { id: 'visual' | 'inspector' | 'ai'; label: string }[] = [
  { id: 'visual', label: 'VISUAL' },
  { id: 'inspector', label: 'INSPECTOR' },
  { id: 'ai', label: 'AI' },
];

export default function InspectorPanel({
  activeTab,
  onTabChange,
  cursorClasses,
  editorRef,
  selectedElement,
  cursorElement,
  onStyleUpdate,
  onStyleRemove,
  onClassUpdate,
  chatProps,
}: InspectorPanelProps) {
  return (
    <div className="h-full flex flex-col overflow-hidden bg-[var(--bg)]">
      {/* Tab bar */}
      <div className="h-8 flex items-center border-b border-[var(--border)] shrink-0 px-1">
        {TABS.map(tab => (
          <button
            key={tab.id}
            onClick={() => onTabChange(tab.id)}
            className={`px-3 h-full text-[10px] font-medium uppercase tracking-wider transition-colors relative ${
              activeTab === tab.id
                ? 'text-[var(--text)]'
                : 'text-[var(--text-subtle)] hover:text-[var(--text-muted)]'
            }`}
          >
            {tab.label}
            {activeTab === tab.id && (
              <div className="absolute bottom-0 left-1 right-1 h-[2px] bg-[var(--primary)] rounded-full" />
            )}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-hidden min-h-0">
        {activeTab === 'visual' && (
          <VisualTab
            cursorClasses={cursorClasses}
            editorRef={editorRef}
            selectedElement={selectedElement}
            onClassUpdate={onClassUpdate}
          />
        )}

        {activeTab === 'inspector' && (
          <InspectorTab
            selectedElement={selectedElement}
            cursorElement={cursorElement}
            onStyleUpdate={onStyleUpdate}
            onStyleRemove={onStyleRemove}
            onSwitchToVisual={() => onTabChange('visual')}
          />
        )}

        {activeTab === 'ai' && (
          <ChatContainer
            {...(chatProps as React.ComponentProps<typeof ChatContainer>)}
            isDocked={true}
            viewContext="builder"
          />
        )}
      </div>
    </div>
  );
}
