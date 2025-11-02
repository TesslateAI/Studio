import { useState, useRef, useEffect } from 'react';
import { X, Plus, CaretLeft, CaretRight, ArrowsClockwise } from '@phosphor-icons/react';

interface Tab {
  id: string;
  title: string;
  url: string;
}

interface BrowserPreviewProps {
  devServerUrl: string;
  devServerUrlWithAuth: string;
  currentPreviewUrl: string;
  onNavigateBack: () => void;
  onNavigateForward: () => void;
  onRefresh: () => void;
  onUrlChange: (url: string) => void;
}

export function BrowserPreview({
  devServerUrl,
  devServerUrlWithAuth,
  currentPreviewUrl,
  onNavigateBack,
  onNavigateForward,
  onRefresh,
  onUrlChange
}: BrowserPreviewProps) {
  const [tabs, setTabs] = useState<Tab[]>([
    { id: '1', title: 'Home', url: devServerUrl }
  ]);
  const [activeTabId, setActiveTabId] = useState('1');
  const iframeRefs = useRef<{ [key: string]: HTMLIFrameElement | null }>({});

  const activeTab = tabs.find(t => t.id === activeTabId);

  const addTab = () => {
    const newTab: Tab = {
      id: Date.now().toString(),
      title: 'New Tab',
      url: devServerUrl
    };
    setTabs([...tabs, newTab]);
    setActiveTabId(newTab.id);
  };

  const closeTab = (tabId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (tabs.length === 1) return; // Don't close last tab

    const newTabs = tabs.filter(t => t.id !== tabId);
    setTabs(newTabs);

    if (activeTabId === tabId) {
      // Switch to adjacent tab
      const closedIndex = tabs.findIndex(t => t.id === tabId);
      const newActiveTab = newTabs[Math.min(closedIndex, newTabs.length - 1)];
      setActiveTabId(newActiveTab.id);
    }
  };

  const updateTabTitle = (tabId: string, title: string) => {
    setTabs(tabs.map(t =>
      t.id === tabId ? { ...t, title } : t
    ));
  };

  // Listen for iframe URL changes
  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      if (event.data && event.data.type === 'url-change') {
        const url = event.data.url;
        onUrlChange(url);

        // Extract page title from URL or use default
        try {
          const urlObj = new URL(url);
          const pathParts = urlObj.pathname.split('/').filter(Boolean);
          const title = pathParts[pathParts.length - 1] || 'Home';
          updateTabTitle(activeTabId, title);
        } catch (error) {
          // Ignore URL parsing errors
        }
      }
    };

    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, [activeTabId]);

  return (
    <div className="w-full h-full flex flex-col">
      {/* Tab Bar */}
      <div className="bg-[var(--surface)] border-b border-white/10 flex items-center px-2">
        <div className="flex items-center gap-1 flex-1 overflow-x-auto">
          {tabs.map(tab => (
            <div
              key={tab.id}
              className={`
                group flex items-center gap-2 px-4 py-2 min-w-[150px] max-w-[200px] rounded-t-lg transition-colors cursor-pointer
                ${activeTabId === tab.id
                  ? 'bg-[var(--text)]/5 border-b-2 border-orange-500'
                  : 'hover:bg-[var(--text)]/5'
                }
              `}
            >
              <span
                className="text-xs truncate flex-1 text-[var(--text)]/80"
                onClick={() => setActiveTabId(tab.id)}
              >
                {tab.title}
              </span>
              {tabs.length > 1 && (
                <button
                  onClick={(e) => closeTab(tab.id, e)}
                  className="hover:bg-[var(--text)]/10 rounded p-0.5 transition-colors"
                  aria-label="Close tab"
                >
                  <X size={14} className="text-[var(--text)]/60 hover:text-[var(--text)]" />
                </button>
              )}
            </div>
          ))}
          <button
            onClick={addTab}
            className="p-2 hover:bg-[var(--text)]/10 rounded transition-colors"
            title="New tab"
          >
            <Plus size={16} className="text-[var(--text)]/60" />
          </button>
        </div>
      </div>

      {/* Browser Chrome */}
      <div className="bg-[var(--surface)] border-b border-white/10 p-2 md:p-3 flex items-center gap-2 md:gap-3">
        <div className="flex items-center gap-1">
          <button
            onClick={onNavigateBack}
            className="p-1.5 md:p-2 hover:bg-white/10 active:bg-white/20 rounded-lg transition-colors text-[var(--text)]/60 hover:text-[var(--text)]"
            title="Go back"
          >
            <CaretLeft size={18} weight="bold" />
          </button>
          <button
            onClick={onNavigateForward}
            className="p-1.5 md:p-2 hover:bg-white/10 active:bg-white/20 rounded-lg transition-colors text-[var(--text)]/60 hover:text-[var(--text)]"
            title="Go forward"
          >
            <CaretRight size={18} weight="bold" />
          </button>
        </div>
        <div className="hidden md:block flex-1">
          <div className="bg-[var(--text)]/5 rounded-lg px-4 py-2 text-sm text-[var(--text)]/60 font-mono flex items-center border border-[var(--border-color)] overflow-hidden">
            <span className="text-yellow-500 mr-2">🔒</span>
            <span className="text-[var(--text)]/80 truncate">{currentPreviewUrl || devServerUrl}</span>
          </div>
        </div>
        <button
          onClick={onRefresh}
          className="p-1.5 md:p-2 hover:bg-white/10 active:bg-white/20 rounded-lg transition-colors text-[var(--text)]/60 hover:text-[var(--text)] ml-auto"
          title="Refresh"
        >
          <ArrowsClockwise size={16} />
        </button>
      </div>

      {/* Preview iframes */}
      <div className="flex-1 bg-white relative">
        {tabs.map(tab => (
          <iframe
            key={tab.id}
            ref={(el) => { iframeRefs.current[tab.id] = el; }}
            id={`preview-iframe-${tab.id}`}
            src={tab.id === activeTabId ? devServerUrlWithAuth : tab.url}
            className={`w-full h-full ${tab.id === activeTabId ? 'block' : 'hidden'}`}
            sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals"
          />
        ))}
      </div>
    </div>
  );
}
