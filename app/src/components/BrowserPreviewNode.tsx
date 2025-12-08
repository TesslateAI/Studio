import { memo, useState, useCallback, useRef, useEffect } from 'react';
import { Handle, Position, type Node } from '@xyflow/react';
import {
  ArrowLeft,
  ArrowRight,
  House,
  ArrowClockwise,
  X,
  Globe,
  Link as LinkIcon,
  ArrowsOut,
  ArrowsIn
} from '@phosphor-icons/react';

interface BrowserPreviewNodeData extends Record<string, unknown> {
  connectedContainerId?: string;
  connectedContainerName?: string;
  connectedPort?: number;
  baseUrl?: string;
  onDelete?: (id: string) => void;
  onDisconnect?: (id: string) => void;
}

type BrowserPreviewNodeProps = Node<BrowserPreviewNodeData> & {
  id: string;
  data: BrowserPreviewNodeData;
};

// Custom comparison for memo
const arePropsEqual = (
  prevProps: BrowserPreviewNodeProps,
  nextProps: BrowserPreviewNodeProps
): boolean => {
  const prevData = prevProps.data;
  const nextData = nextProps.data;

  return (
    prevProps.id === nextProps.id &&
    prevData.connectedContainerId === nextData.connectedContainerId &&
    prevData.connectedContainerName === nextData.connectedContainerName &&
    prevData.connectedPort === nextData.connectedPort &&
    prevData.baseUrl === nextData.baseUrl
  );
};

const BrowserPreviewNodeComponent = ({ data, id }: BrowserPreviewNodeProps) => {
  const [currentPath, setCurrentPath] = useState('/');
  const [inputUrl, setInputUrl] = useState('/');
  const [history, setHistory] = useState<string[]>(['/']);
  const [historyIndex, setHistoryIndex] = useState(0);
  const [isExpanded, setIsExpanded] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const iframeRef = useRef<HTMLIFrameElement>(null);

  // Build the full URL based on connected container
  const getFullUrl = useCallback((path: string) => {
    if (!data.baseUrl) return '';
    const cleanPath = path.startsWith('/') ? path : `/${path}`;
    return `${data.baseUrl}${cleanPath}`;
  }, [data.baseUrl]);

  // Update input when path changes
  useEffect(() => {
    setInputUrl(currentPath);
  }, [currentPath]);

  const navigateTo = useCallback((path: string) => {
    const cleanPath = path.startsWith('/') ? path : `/${path}`;
    setCurrentPath(cleanPath);
    setIsLoading(true);

    // Add to history
    const newHistory = [...history.slice(0, historyIndex + 1), cleanPath];
    setHistory(newHistory);
    setHistoryIndex(newHistory.length - 1);
  }, [history, historyIndex]);

  const goBack = useCallback(() => {
    if (historyIndex > 0) {
      const newIndex = historyIndex - 1;
      setHistoryIndex(newIndex);
      setCurrentPath(history[newIndex]);
      setIsLoading(true);
    }
  }, [history, historyIndex]);

  const goForward = useCallback(() => {
    if (historyIndex < history.length - 1) {
      const newIndex = historyIndex + 1;
      setHistoryIndex(newIndex);
      setCurrentPath(history[newIndex]);
      setIsLoading(true);
    }
  }, [history, historyIndex]);

  const goHome = useCallback(() => {
    navigateTo('/');
  }, [navigateTo]);

  const refresh = useCallback(() => {
    setIsLoading(true);
    if (iframeRef.current) {
      iframeRef.current.src = iframeRef.current.src;
    }
  }, []);

  const handleUrlSubmit = useCallback((e: React.FormEvent) => {
    e.preventDefault();
    navigateTo(inputUrl);
  }, [inputUrl, navigateTo]);

  const handleIframeLoad = useCallback(() => {
    setIsLoading(false);
  }, []);

  const isConnected = !!data.connectedContainerId && !!data.baseUrl;

  return (
    <div
      className={`relative group ${isExpanded ? 'z-50' : ''}`}
      style={{ contain: 'layout style paint' }}
    >
      {/* Connection handle - connects FROM containers TO this browser */}
      <Handle
        type="target"
        position={Position.Left}
        className="!bg-blue-500 !w-3 !h-3 !border-2 !border-blue-300"
        id="preview-input"
      />

      {/* Browser window */}
      <div
        className={`bg-[#1a1a1a] rounded-xl overflow-hidden shadow-2xl border border-[#333] ${
          isExpanded ? 'w-[800px] h-[600px]' : 'w-[320px] h-[240px]'
        } transition-all duration-200`}
      >
        {/* Browser chrome / toolbar */}
        <div className="bg-[#252525] border-b border-[#333] px-2 py-1.5">
          {/* Window controls and title */}
          <div className="flex items-center justify-between mb-1.5">
            <div className="flex items-center gap-1.5">
              <button
                onClick={() => data.onDelete?.(id)}
                className="w-3 h-3 rounded-full bg-red-500 hover:bg-red-400 transition-colors"
                title="Close browser"
              />
              <button
                onClick={() => setIsExpanded(!isExpanded)}
                className="w-3 h-3 rounded-full bg-yellow-500 hover:bg-yellow-400 transition-colors"
                title={isExpanded ? 'Minimize' : 'Expand'}
              />
              <button
                onClick={() => setIsExpanded(!isExpanded)}
                className="w-3 h-3 rounded-full bg-green-500 hover:bg-green-400 transition-colors"
                title={isExpanded ? 'Minimize' : 'Expand'}
              />
            </div>
            <div className="flex-1 text-center">
              <span className="text-[10px] text-gray-400 truncate">
                {isConnected ? data.connectedContainerName : 'Browser Preview'}
              </span>
            </div>
            <div className="w-12" /> {/* Spacer for balance */}
          </div>

          {/* Navigation bar */}
          <div className="flex items-center gap-1">
            <button
              onClick={goBack}
              disabled={historyIndex <= 0}
              className="p-1 rounded hover:bg-[#333] disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              title="Back"
            >
              <ArrowLeft size={12} className="text-gray-400" />
            </button>
            <button
              onClick={goForward}
              disabled={historyIndex >= history.length - 1}
              className="p-1 rounded hover:bg-[#333] disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              title="Forward"
            >
              <ArrowRight size={12} className="text-gray-400" />
            </button>
            <button
              onClick={refresh}
              disabled={!isConnected}
              className="p-1 rounded hover:bg-[#333] disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              title="Refresh"
            >
              <ArrowClockwise size={12} className={`text-gray-400 ${isLoading ? 'animate-spin' : ''}`} />
            </button>
            <button
              onClick={goHome}
              disabled={!isConnected}
              className="p-1 rounded hover:bg-[#333] disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              title="Home"
            >
              <House size={12} className="text-gray-400" />
            </button>

            {/* URL bar */}
            <form onSubmit={handleUrlSubmit} className="flex-1 flex items-center">
              <div className="flex-1 flex items-center bg-[#1a1a1a] rounded px-2 py-0.5 gap-1">
                {isConnected ? (
                  <Globe size={10} className="text-green-500 flex-shrink-0" />
                ) : (
                  <LinkIcon size={10} className="text-gray-500 flex-shrink-0" />
                )}
                <input
                  type="text"
                  value={inputUrl}
                  onChange={(e) => setInputUrl(e.target.value)}
                  disabled={!isConnected}
                  placeholder={isConnected ? '/' : 'Connect a container...'}
                  className="flex-1 bg-transparent text-[10px] text-gray-300 outline-none placeholder-gray-500 min-w-0"
                />
              </div>
            </form>

            {/* Expand/collapse */}
            <button
              onClick={() => setIsExpanded(!isExpanded)}
              className="p-1 rounded hover:bg-[#333] transition-colors"
              title={isExpanded ? 'Minimize' : 'Expand'}
            >
              {isExpanded ? (
                <ArrowsIn size={12} className="text-gray-400" />
              ) : (
                <ArrowsOut size={12} className="text-gray-400" />
              )}
            </button>
          </div>
        </div>

        {/* Browser viewport */}
        <div className="relative bg-white" style={{ height: isExpanded ? 'calc(100% - 52px)' : 'calc(100% - 52px)' }}>
          {isConnected ? (
            <>
              {isLoading && (
                <div className="absolute inset-0 bg-white flex items-center justify-center z-10">
                  <div className="flex flex-col items-center gap-2">
                    <ArrowClockwise size={24} className="text-gray-400 animate-spin" />
                    <span className="text-xs text-gray-500">Loading...</span>
                  </div>
                </div>
              )}
              <iframe
                ref={iframeRef}
                src={getFullUrl(currentPath)}
                className="w-full h-full border-0"
                title={`Preview: ${data.connectedContainerName}`}
                onLoad={handleIframeLoad}
                sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
              />
            </>
          ) : (
            <div className="w-full h-full flex flex-col items-center justify-center bg-[#0a0a0a] text-center p-4">
              <Globe size={32} className="text-gray-600 mb-2" />
              <p className="text-xs text-gray-500 mb-1">No container connected</p>
              <p className="text-[10px] text-gray-600">
                Drag a connection from a container to this browser to preview it
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export const BrowserPreviewNode = memo(BrowserPreviewNodeComponent, arePropsEqual);
BrowserPreviewNode.displayName = 'BrowserPreviewNode';
