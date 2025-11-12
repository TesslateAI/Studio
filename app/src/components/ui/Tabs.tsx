import { type ReactNode } from 'react';

export interface Tab {
  id: string;
  label: string;
  icon?: ReactNode;
}

interface TabsProps {
  tabs: Tab[];
  activeTab: string;
  onTabChange: (tabId: string) => void;
  className?: string;
}

export function Tabs({ tabs, activeTab, onTabChange, className = '' }: TabsProps) {
  return (
    <div className={`w-full border-b border-white/10 bg-[#0a0a0a] ${className}`}>
      {/* Horizontal scrollable tabs container - mobile responsive */}
      <div className="overflow-x-auto scrollbar-thin scrollbar-thumb-white/20 scrollbar-track-transparent">
        <div className="flex gap-2 min-w-max sm:min-w-0 px-3 py-2">
          {tabs.map((tab) => {
            const isActive = activeTab === tab.id;

            return (
              <button
                key={tab.id}
                onClick={() => onTabChange(tab.id)}
                className={`
                  flex items-center gap-2 px-3 py-1.5
                  text-xs font-medium
                  transition-all duration-200
                  whitespace-nowrap rounded-lg
                  border
                  ${
                    isActive
                      ? 'text-[var(--text)] bg-white/10 border-white/20'
                      : 'text-[var(--text)]/60 hover:text-[var(--text)] hover:bg-white/5 border-white/10 hover:border-white/15'
                  }
                `}
              >
                {tab.icon}
                <span>{tab.label}</span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
