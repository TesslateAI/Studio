import { useState, useRef, useEffect } from 'react';
import {
  X,
  Plus,
  CaretLeft,
  CaretRight,
  ArrowsClockwise,
  DeviceMobile,
  Monitor,
  LockSimple,
} from '@phosphor-icons/react';
import { ContainerLoadingOverlay } from './ContainerLoadingOverlay';
import { PreviewPortPicker, type PreviewableContainer } from './PreviewPortPicker';
import type { ContainerStartupStatus } from '../hooks/useContainerStartup';

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
  // New props for container startup state
  containerStatus?: ContainerStartupStatus;
  startupPhase?: string;
  startupProgress?: number;
  startupMessage?: string;
  startupLogs?: string[];
  startupError?: string;
  onRetryStart?: () => void;
  // Preview port picker props
  previewableContainers?: PreviewableContainer[];
  selectedPreviewContainerId?: string | null;
  onPreviewContainerSwitch?: (container: PreviewableContainer) => void;
}

export function BrowserPreview({
  devServerUrl,
  devServerUrlWithAuth,
  currentPreviewUrl,
  onNavigateBack,
  onNavigateForward,
  onRefresh,
  onUrlChange,
  containerStatus,
  startupPhase = '',
  startupProgress = 0,
  startupMessage = '',
  startupLogs = [],
  startupError,
  onRetryStart,
  previewableContainers = [],
  selectedPreviewContainerId = null,
  onPreviewContainerSwitch,
}: BrowserPreviewProps) {
  // Determine if we should show the loading overlay
  const showLoadingOverlay =
    containerStatus === 'starting' ||
    containerStatus === 'health_checking' ||
    containerStatus === 'error';

  // Viewport mode for mobile preview
  const [viewportMode, setViewportMode] = useState<'desktop' | 'mobile'>('desktop');

  const [tabs, setTabs] = useState<Tab[]>([{ id: '1', title: 'Home', url: devServerUrl }]);
  const [activeTabId, setActiveTabId] = useState('1');
  const iframeRefs = useRef<{ [key: string]: HTMLIFrameElement | null }>({});

  const addTab = () => {
    const newTab: Tab = {
      id: Date.now().toString(),
      title: 'New Tab',
      url: devServerUrl,
    };
    setTabs([...tabs, newTab]);
    setActiveTabId(newTab.id);
  };

  const closeTab = (tabId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (tabs.length === 1) return; // Don't close last tab

    const newTabs = tabs.filter((t) => t.id !== tabId);
    setTabs(newTabs);

    if (activeTabId === tabId) {
      // Switch to adjacent tab
      const closedIndex = tabs.findIndex((t) => t.id === tabId);
      const newActiveTab = newTabs[Math.min(closedIndex, newTabs.length - 1)];
      setActiveTabId(newActiveTab.id);
    }
  };

  const updateTabTitle = (tabId: string, title: string) => {
    setTabs(tabs.map((t) => (t.id === tabId ? { ...t, title } : t)));
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
        } catch {
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
      <div className="h-9 bg-[var(--surface)] border-b border-[var(--border)] flex items-center px-1.5 flex-shrink-0">
        <div className="flex items-center gap-0.5 flex-1 overflow-x-auto scrollbar-none">
          {tabs.map((tab) => (
            <div
              key={tab.id}
              onClick={() => setActiveTabId(tab.id)}
              className={`
                group flex items-center gap-1.5 px-3 h-7 min-w-[120px] max-w-[180px] rounded-[var(--radius-small)] transition-colors cursor-pointer
                ${
                  activeTabId === tab.id
                    ? 'bg-[var(--surface-hover)] text-[var(--text)]'
                    : 'text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]'
                }
              `}
            >
              <span className="text-[11px] truncate flex-1">
                {tab.title}
              </span>
              {tabs.length > 1 && (
                <button
                  onClick={(e) => closeTab(tab.id, e)}
                  className="opacity-0 group-hover:opacity-100 hover:bg-[var(--surface)] rounded p-0.5 transition-all flex-shrink-0"
                  aria-label="Close tab"
                >
                  <X size={11} className="text-[var(--text-subtle)]" />
                </button>
              )}
            </div>
          ))}
          <button
            onClick={addTab}
            className="btn btn-icon btn-sm"
            title="New tab"
          >
            <Plus size={14} />
          </button>
        </div>
      </div>

      {/* Browser Chrome */}
      <div className="h-10 bg-[var(--surface)] border-b border-[var(--border)] px-2 flex items-center gap-1.5 flex-shrink-0">
        {/* Navigation */}
        <div className="flex items-center gap-0.5">
          <button
            onClick={onNavigateBack}
            className="btn btn-icon btn-sm"
            title="Go back"
          >
            <CaretLeft size={14} weight="bold" />
          </button>
          <button
            onClick={onNavigateForward}
            className="btn btn-icon btn-sm"
            title="Go forward"
          >
            <CaretRight size={14} weight="bold" />
          </button>
        </div>

        {/* URL bar */}
        <div className="hidden md:flex flex-1 items-center gap-1.5 h-7 bg-[var(--bg)] border border-[var(--border)] rounded-full px-3 min-w-0">
          <LockSimple size={11} weight="bold" className="text-[var(--text-subtle)] flex-shrink-0" />
          <span className="text-[11px] text-[var(--text-muted)] font-mono truncate">
            {currentPreviewUrl || devServerUrl}
          </span>
        </div>

        {/* Right controls */}
        <div className="flex items-center gap-0.5 ml-auto">
          {onPreviewContainerSwitch && (
            <PreviewPortPicker
              containers={previewableContainers}
              selectedContainerId={selectedPreviewContainerId}
              onSelect={onPreviewContainerSwitch}
            />
          )}
          <button
            onClick={onRefresh}
            className="btn btn-icon btn-sm"
            title="Refresh"
          >
            <ArrowsClockwise size={14} />
          </button>
          <button
            onClick={() => setViewportMode(viewportMode === 'desktop' ? 'mobile' : 'desktop')}
            className={`btn btn-icon btn-sm ${viewportMode === 'mobile' ? 'btn-active text-[var(--primary)]' : ''}`}
            title={viewportMode === 'desktop' ? 'Switch to mobile view' : 'Switch to desktop view'}
          >
            {viewportMode === 'desktop' ? <DeviceMobile size={14} /> : <Monitor size={14} />}
          </button>
        </div>
      </div>

      {/* Preview area - either loading overlay or iframes */}
      <div
        className={`flex-1 relative overflow-auto ${viewportMode === 'mobile' ? 'bg-[var(--bg)] flex items-center justify-center' : 'bg-white'}`}
      >
        {showLoadingOverlay ? (
          <ContainerLoadingOverlay
            phase={startupPhase}
            progress={startupProgress}
            message={startupMessage}
            logs={startupLogs}
            error={startupError}
            onRetry={onRetryStart}
          />
        ) : (
          <div
            className={
              viewportMode === 'mobile'
                ? 'w-[375px] h-[667px] border border-[var(--border)] rounded-[var(--radius)] overflow-hidden flex-shrink-0 bg-white'
                : 'w-full h-full'
            }
          >
            {tabs.map((tab) => (
              <iframe
                key={tab.id}
                ref={(el) => {
                  iframeRefs.current[tab.id] = el;
                }}
                id={`preview-iframe-${tab.id}`}
                src={tab.id === activeTabId ? devServerUrlWithAuth : tab.url}
                className={`w-full h-full ${tab.id === activeTabId ? 'block' : 'hidden'}`}
                sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals"
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
