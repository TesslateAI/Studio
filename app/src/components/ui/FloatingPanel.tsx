import { useState, useRef, useEffect, type ReactNode } from 'react';

interface FloatingPanelProps {
  title: string;
  icon?: ReactNode;
  children: ReactNode;
  isOpen: boolean;
  onClose: () => void;
  defaultPosition?: { x: number; y: number };
  defaultSize?: { width: number; height: number };
}

type DockPosition = 'left' | 'right' | 'top' | 'bottom' | null;

export function FloatingPanel({
  title,
  icon,
  children,
  isOpen,
  onClose,
  defaultPosition = { x: 100, y: 100 },
  defaultSize = { width: 400, height: 500 }
}: FloatingPanelProps) {
  const [position, setPosition] = useState(defaultPosition);
  const [size, setSize] = useState(defaultSize);
  const [isDragging, setIsDragging] = useState(false);
  const [isResizing, setIsResizing] = useState(false);
  const [dockPosition, setDockPosition] = useState<DockPosition>(null);
  const [dragOffset, setDragOffset] = useState({ x: 0, y: 0 });

  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isDragging && !isResizing) return;

    const handleMouseMove = (e: MouseEvent) => {
      if (isDragging && dockPosition === null) {
        const newX = e.clientX - dragOffset.x;
        const newY = e.clientY - dragOffset.y;
        setPosition({ x: newX, y: newY });

        // Check for dock zones
        const DOCK_THRESHOLD = 100;
        if (e.clientX < DOCK_THRESHOLD) {
          setDockPosition('left');
        } else if (window.innerWidth - e.clientX < DOCK_THRESHOLD) {
          setDockPosition('right');
        } else if (e.clientY < DOCK_THRESHOLD) {
          setDockPosition('top');
        } else if (window.innerHeight - e.clientY < DOCK_THRESHOLD) {
          setDockPosition('bottom');
        } else {
          setDockPosition(null);
        }
      } else if (isResizing) {
        const newWidth = Math.max(300, e.clientX - position.x);
        const newHeight = Math.max(200, e.clientY - position.y);
        setSize({ width: newWidth, height: newHeight });
      }
    };

    const handleMouseUp = () => {
      if (isDragging && dockPosition) {
        // Apply docking
        applyDock(dockPosition);
      }
      setIsDragging(false);
      setIsResizing(false);
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDragging, isResizing, dragOffset, position, dockPosition]);

  const handleDragStart = (e: React.MouseEvent) => {
    if (dockPosition) {
      setDockPosition(null);
      setPosition(defaultPosition);
      setSize(defaultSize);
    }
    const rect = panelRef.current?.getBoundingClientRect();
    if (rect) {
      setDragOffset({
        x: e.clientX - rect.left,
        y: e.clientY - rect.top
      });
    }
    setIsDragging(true);
  };

  const handleResizeStart = (e: React.MouseEvent) => {
    e.stopPropagation();
    setIsResizing(true);
  };

  const applyDock = (dock: DockPosition) => {
    // Docking logic would set position and size based on dock position
    // For now, simplified
  };

  if (!isOpen) return null;

  const isDocked = dockPosition !== null;
  const panelStyle = isDocked
    ? getDockStyle(dockPosition)
    : {
        left: `${position.x}px`,
        top: `${position.y}px`,
        width: `${size.width}px`,
        height: `${size.height}px`
      };

  return (
    <>
      {/* Dock indicator */}
      {isDragging && dockPosition && (
        <div
          className={`
            fixed bg-[rgba(255,107,0,0.2)] border-2 border-dashed border-[var(--primary)]
            pointer-events-none opacity-100 transition-opacity duration-200 rounded-lg z-[1000]
            ${getDockIndicatorClass(dockPosition)}
          `}
        />
      )}

      {/* Floating panel */}
      <div
        ref={panelRef}
        className={`
          floating-panel fixed flex flex-col
          bg-[rgba(30,30,30,0.98)] backdrop-blur-xl
          border border-white/20 rounded-lg
          shadow-lg overflow-hidden
          transition-all duration-300
          z-[200]
          ${isDocked ? 'resize-none rounded-none h-screen' : 'min-w-[300px] min-h-[200px]'}
        `}
        style={panelStyle}
      >
        {/* Drag handle */}
        <div
          className="panel-drag-handle h-10 bg-black/20 border-b border-white/10 cursor-move select-none flex items-center justify-between px-3 rounded-t-lg"
          onMouseDown={handleDragStart}
        >
          <div className="flex items-center gap-2">
            {icon && <span className="text-orange-500">{icon}</span>}
            <span className="text-sm font-semibold text-white">{title}</span>
          </div>
          <button
            onClick={onClose}
            className="panel-close p-1 hover:bg-white/10 rounded text-gray-400 hover:text-white transition-colors"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Panel content */}
        <div className="panel-content flex-1 overflow-y-auto">
          {children}
        </div>

        {/* Resize handle */}
        {!isDocked && (
          <div
            className="resize-handle absolute bottom-0 right-0 w-5 h-5 cursor-nwse-resize z-10 after:content-[''] after:absolute after:bottom-1 after:right-1 after:w-2.5 after:h-2.5 after:border-r-2 after:border-b-2 after:border-white/30"
            onMouseDown={handleResizeStart}
          />
        )}
      </div>
    </>
  );
}

function getDockStyle(dock: DockPosition): React.CSSProperties {
  switch (dock) {
    case 'left':
      return { left: 0, top: 0, width: '400px', height: '100vh' };
    case 'right':
      return { right: 0, top: 0, width: '400px', height: '100vh' };
    case 'top':
      return { left: 0, top: 0, width: '100vw', height: '300px' };
    case 'bottom':
      return { left: 0, bottom: 0, width: '100vw', height: '300px' };
    default:
      return {};
  }
}

function getDockIndicatorClass(dock: DockPosition): string {
  switch (dock) {
    case 'left':
      return 'left-0 top-0 w-[100px] h-screen';
    case 'right':
      return 'right-0 top-0 w-[100px] h-screen';
    case 'top':
      return 'top-0 left-[100px] right-[100px] h-[100px]';
    case 'bottom':
      return 'bottom-0 left-[100px] right-[100px] h-[100px]';
    default:
      return '';
  }
}
