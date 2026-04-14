import { Sparkles } from 'lucide-react';
import VisualTab from './VisualTab';
import InspectorTab from './InspectorTab';
import { askAIAboutElement } from './designStore';
import type { ClassInfo, ElementInfo } from '../../../utils/classDetection';
import type { ElementData } from './DesignBridge';

export type InspectorTabId = 'visual' | 'inspector';

interface InspectorPanelProps {
  activeTab: InspectorTabId;
  onTabChange: (tab: InspectorTabId) => void;
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
}

const TABS: { id: InspectorTabId; label: string }[] = [
  { id: 'visual', label: 'VISUAL' },
  { id: 'inspector', label: 'INSPECTOR' },
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
        <div className="flex-1" />
        {selectedElement && (
          <button
            type="button"
            onClick={() =>
              askAIAboutElement({
                oid: selectedElement.oid,
                tagName: selectedElement.tagName,
                classList: selectedElement.classList,
                textContent: selectedElement.textContent,
                reactComponent: selectedElement.reactComponent,
              })
            }
            title="Ask AI about this element"
            className="mr-1 flex items-center gap-1 px-2 h-6 text-[10px] font-medium uppercase tracking-wider rounded transition-colors text-[var(--primary)] hover:bg-[var(--primary)]/10"
          >
            <Sparkles size={11} />
            Ask AI
          </button>
        )}
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
      </div>
    </div>
  );
}
