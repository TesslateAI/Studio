import { memo, useState, useCallback, useRef, useEffect } from 'react';
import { Handle, Position, type Node } from '@xyflow/react';
import {
  ArrowLeft,
  ArrowRight,
  House,
  ArrowClockwise,
  Globe,
  Link as LinkIcon,
  ArrowsOut,
  ArrowsIn,
} from '@phosphor-icons/react';

interface BrowserPreviewNodeData extends Record<string, unknown> {
  connectedContainerId?: string;
  connectedContainerName?: string;
  connectedPort?: number;
  getContainerUrl?: (containerId: string) => string;
  onDelete?: (id: string) => void;
  onDisconnect?: (id: string) => void;
}

// Resize handle positions
type ResizeHandle = 'n' | 's' | 'e' | 'w' | 'ne' | 'nw' | 'se' | 'sw';

const MIN_WIDTH = 280;
const MIN_HEIGHT = 200;
const MAX_WIDTH = 1200;
const MAX_HEIGHT = 900;

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
    prevData.connectedPort === nextData.connectedPort
  );
};

const BrowserPreviewNodeComponent = ({ data, id }: BrowserPreviewNodeProps) => {
  const [currentPath, setCurrentPath] = useState('/');
  const [inputUrl, setInputUrl] = useState('/');
  const [history, setHistory] = useState<string[]>(['/']);
  const [historyIndex, setHistoryIndex] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const iframeRef = useRef<HTMLIFrameElement>(null);

  // Resize state
  const [size, setSize] = useState({ width: 320, height: 240 });
  const [isResizing, setIsResizing] = useState(false);
  const resizeRef = useRef<{
    startX: number;
    startY: number;
    startWidth: number;
    startHeight: number;
    handle: ResizeHandle;
  } | null>(null);

  // Resolve base URL from runtime status via callback
  const baseUrl =
    data.connectedContainerId && data.getContainerUrl
      ? data.getContainerUrl(data.connectedContainerId)
      : '';

  const getFullUrl = useCallback(
    (path: string) => {
      if (!baseUrl) return '';
      const cleanPath = path.startsWith('/') ? path : `/${path}`;
      return `${baseUrl}${cleanPath}`;
    },
    [baseUrl]
  );

  // Update input when path changes
  useEffect(() => {
    setInputUrl(currentPath);
  }, [currentPath]);

  const navigateTo = useCallback(
    (path: string) => {
      const cleanPath = path.startsWith('/') ? path : `/${path}`;
      setCurrentPath(cleanPath);
      setIsLoading(true);

      // Add to history
      const newHistory = [...history.slice(0, historyIndex + 1), cleanPath];
      setHistory(newHistory);
      setHistoryIndex(newHistory.length - 1);
    },
    [history, historyIndex]
  );

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
      // Force refresh by reloading with timestamp
      const currentSrc = iframeRef.current.src;
      iframeRef.current.src = currentSrc.includes('?')
        ? currentSrc
        : `${currentSrc}?t=${Date.now()}`;
    }
  }, []);

  const handleUrlSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      navigateTo(inputUrl);
    },
    [inputUrl, navigateTo]
  );

  const handleIframeLoad = useCallback(() => {
    setIsLoading(false);
  }, []);

  // Resize handlers
  const handleResizeStart = useCallback(
    (e: React.MouseEvent, handle: ResizeHandle) => {
      e.preventDefault();
      e.stopPropagation();
      setIsResizing(true);
      resizeRef.current = {
        startX: e.clientX,
        startY: e.clientY,
        startWidth: size.width,
        startHeight: size.height,
        handle,
      };
    },
    [size]
  );

  useEffect(() => {
    if (!isResizing) return;

    const handleMouseMove = (e: MouseEvent) => {
      if (!resizeRef.current) return;

      const { startX, startY, startWidth, startHeight, handle } = resizeRef.current;
      const deltaX = e.clientX - startX;
      const deltaY = e.clientY - startY;

      let newWidth = startWidth;
      let newHeight = startHeight;

      // Calculate new dimensions based on which handle is being dragged
      if (handle.includes('e')) {
        newWidth = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, startWidth + deltaX));
      }
      if (handle.includes('w')) {
        newWidth = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, startWidth - deltaX));
      }
      if (handle.includes('s')) {
        newHeight = Math.min(MAX_HEIGHT, Math.max(MIN_HEIGHT, startHeight + deltaY));
      }
      if (handle.includes('n')) {
        newHeight = Math.min(MAX_HEIGHT, Math.max(MIN_HEIGHT, startHeight - deltaY));
      }

      setSize({ width: newWidth, height: newHeight });
    };

    const handleMouseUp = () => {
      setIsResizing(false);
      resizeRef.current = null;
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isResizing]);

  const isConnected = !!data.connectedContainerId && !!baseUrl;

  return (
    <div className="relative group" style={{ contain: 'layout style' }}>
      {/* Connection handle - connects FROM containers TO this browser */}
      <Handle
        type="target"
        position={Position.Left}
        className="!bg-blue-500 !w-3 !h-3 !border-2 !border-blue-300"
        id="preview-input"
      />

      {/* Browser window */}
      <div
        className="bg-[#1a1a1a] rounded-xl overflow-hidden shadow-2xl border border-[#333]"
        style={{ width: size.width, height: size.height }}
      >
        {/* Resize handles */}
        {/* Edge handles */}
        <div
          className="nodrag nopan absolute top-0 left-2 right-2 h-2 cursor-n-resize hover:bg-blue-500/30 z-10"
          onMouseDown={(e) => handleResizeStart(e, 'n')}
        />
        <div
          className="nodrag nopan absolute bottom-0 left-2 right-2 h-2 cursor-s-resize hover:bg-blue-500/30 z-10"
          onMouseDown={(e) => handleResizeStart(e, 's')}
        />
        <div
          className="nodrag nopan absolute left-0 top-2 bottom-2 w-2 cursor-w-resize hover:bg-blue-500/30 z-10"
          onMouseDown={(e) => handleResizeStart(e, 'w')}
        />
        <div
          className="nodrag nopan absolute right-0 top-2 bottom-2 w-2 cursor-e-resize hover:bg-blue-500/30 z-10"
          onMouseDown={(e) => handleResizeStart(e, 'e')}
        />
        {/* Corner handles */}
        <div
          className="nodrag nopan absolute top-0 left-0 w-3 h-3 cursor-nw-resize hover:bg-blue-500/30 z-20"
          onMouseDown={(e) => handleResizeStart(e, 'nw')}
        />
        <div
          className="nodrag nopan absolute top-0 right-0 w-3 h-3 cursor-ne-resize hover:bg-blue-500/30 z-20"
          onMouseDown={(e) => handleResizeStart(e, 'ne')}
        />
        <div
          className="nodrag nopan absolute bottom-0 left-0 w-3 h-3 cursor-sw-resize hover:bg-blue-500/30 z-20"
          onMouseDown={(e) => handleResizeStart(e, 'sw')}
        />
        <div
          className="nodrag nopan absolute bottom-0 right-0 w-3 h-3 cursor-se-resize hover:bg-blue-500/30 z-20"
          onMouseDown={(e) => handleResizeStart(e, 'se')}
        />
        {/* Browser chrome / toolbar */}
        <div className="bg-[#252525] border-b border-[#333] px-2 py-1.5">
          {/* Window controls and title — drag handle */}
          <div className="browser-drag-handle flex items-center justify-between mb-1.5 cursor-grab active:cursor-grabbing">
            <div className="nodrag nopan flex items-center gap-1.5">
              <button
                onClick={() => data.onDelete?.(id)}
                className="w-3 h-3 rounded-full bg-red-500 hover:bg-red-400 transition-colors"
                title="Close browser"
              />
              <button
                onClick={() => setSize({ width: 320, height: 240 })}
                className="w-3 h-3 rounded-full bg-yellow-500 hover:bg-yellow-400 transition-colors"
                title="Reset to default size"
              />
              <button
                onClick={() => setSize({ width: 800, height: 600 })}
                className="w-3 h-3 rounded-full bg-green-500 hover:bg-green-400 transition-colors"
                title="Expand to large size"
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
          <div className="nodrag nopan flex items-center gap-1">
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
              <ArrowClockwise
                size={12}
                className={`text-gray-400 ${isLoading ? 'animate-spin' : ''}`}
              />
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
              onClick={() =>
                setSize((prev) =>
                  prev.width >= 600 ? { width: 320, height: 240 } : { width: 800, height: 600 }
                )
              }
              className="p-1 rounded hover:bg-[#333] transition-colors"
              title={size.width >= 600 ? 'Minimize' : 'Expand'}
            >
              {size.width >= 600 ? (
                <ArrowsIn size={12} className="text-gray-400" />
              ) : (
                <ArrowsOut size={12} className="text-gray-400" />
              )}
            </button>
          </div>
        </div>

        {/* Browser viewport */}
        <div className="nodrag nopan relative bg-white" style={{ height: 'calc(100% - 52px)' }}>
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

      {/* Interaction overlay during resize — prevents iframe from swallowing mouse events */}
      {isResizing && <div className="fixed inset-0 z-[9999]" />}
    </div>
  );
};

export const BrowserPreviewNode = memo(BrowserPreviewNodeComponent, arePropsEqual);
BrowserPreviewNode.displayName = 'BrowserPreviewNode';
