import { useState, useRef, useEffect, useCallback, type ReactNode } from 'react';
import { useTheme } from '../../theme/ThemeContext';

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
  const { theme } = useTheme();
  const [position, setPosition] = useState(defaultPosition);
  const [size, setSize] = useState(defaultSize);
  const [isDragging, setIsDragging] = useState(false);
  const [isResizing, setIsResizing] = useState(false);
  const [dockHoverPosition, setDockHoverPosition] = useState<DockPosition>(null); // Preview only
  const [actualDockPosition, setActualDockPosition] = useState<DockPosition>(null); // Actually docked
  const [dragOffset, setDragOffset] = useState({ x: 0, y: 0 });

  const panelRef = useRef<HTMLDivElement>(null);
  const dragStartPosRef = useRef({ x: 0, y: 0 });

  useEffect(() => {
    if (!isDragging && !isResizing) return;

    const handleMouseMove = (e: MouseEvent) => {
      if (isDragging && panelRef.current) {
        // Use CSS transform for smooth dragging - no React state updates
        const newX = e.clientX - dragOffset.x;
        const newY = e.clientY - dragOffset.y;

        // Apply transform directly to DOM
        panelRef.current.style.transform = `translate(${newX - dragStartPosRef.current.x}px, ${newY - dragStartPosRef.current.y}px)`;
        panelRef.current.style.willChange = 'transform';

        // Check for dock zones - only for preview (this is lightweight)
        const DOCK_THRESHOLD = 80;
        let newDockHover: DockPosition = null;

        if (e.clientX < DOCK_THRESHOLD) {
          newDockHover = 'left';
        } else if (window.innerWidth - e.clientX < DOCK_THRESHOLD) {
          newDockHover = 'right';
        } else if (e.clientY < DOCK_THRESHOLD) {
          newDockHover = 'top';
        } else if (window.innerHeight - e.clientY < DOCK_THRESHOLD) {
          newDockHover = 'bottom';
        }

        if (newDockHover !== dockHoverPosition) {
          setDockHoverPosition(newDockHover);
        }
      } else if (isResizing && panelRef.current) {
        const newWidth = Math.max(300, e.clientX - position.x);
        const newHeight = Math.max(200, e.clientY - position.y);
        panelRef.current.style.width = `${newWidth}px`;
        panelRef.current.style.height = `${newHeight}px`;
      }
    };

    const handleMouseUp = (e: MouseEvent) => {
      if (isDragging && panelRef.current) {
        // Calculate final position
        const newX = e.clientX - dragOffset.x;
        const newY = e.clientY - dragOffset.y;

        // Reset transform
        panelRef.current.style.transform = '';
        panelRef.current.style.willChange = 'auto';

        // Only apply docking on mouse up if hovering over dock zone
        if (dockHoverPosition) {
          setActualDockPosition(dockHoverPosition);
        } else {
          // Update position state for next drag
          setPosition({ x: newX, y: newY });
        }
        setDockHoverPosition(null);
      } else if (isResizing && panelRef.current) {
        // Commit resize to state
        const rect = panelRef.current.getBoundingClientRect();
        setSize({ width: rect.width, height: rect.height });
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
  }, [isDragging, isResizing, dragOffset, position, dockHoverPosition]);

  const handleDragStart = (e: React.MouseEvent) => {
    // Calculate offset based on current position
    const rect = panelRef.current?.getBoundingClientRect();
    if (rect) {
      setDragOffset({
        x: e.clientX - rect.left,
        y: e.clientY - rect.top
      });

      // Store the starting position for transform calculations
      dragStartPosRef.current = { x: rect.left, y: rect.top };
    }

    // If docked, undock and restore to a floating position
    if (actualDockPosition !== null) {
      setPosition(defaultPosition);
      setSize(defaultSize);
      setActualDockPosition(null);
      // Update drag start ref after undocking
      setTimeout(() => {
        const rect = panelRef.current?.getBoundingClientRect();
        if (rect) {
          dragStartPosRef.current = { x: rect.left, y: rect.top };
        }
      }, 0);
    }

    setIsDragging(true);
  };

  const handleResizeStart = (e: React.MouseEvent) => {
    e.stopPropagation();
    setIsResizing(true);
  };

  if (!isOpen) return null;

  const isDocked = actualDockPosition !== null;
  const panelStyle = isDocked
    ? getDockStyle(actualDockPosition)
    : {
        left: `${position.x}px`,
        top: `${position.y}px`,
        width: `${size.width}px`,
        height: `${size.height}px`
      };

  return (
    <>
      {/* Dock indicator - only show during drag when hovering over dock zone */}
      {isDragging && dockHoverPosition && (
        <div
          className={`
            fixed bg-orange-500/20 border-2 border-dashed border-orange-500
            pointer-events-none z-[999] rounded-lg
            transition-all duration-150
            ${getDockIndicatorClass(dockHoverPosition)}
          `}
        />
      )}

      {/* Floating panel */}
      <div
        ref={panelRef}
        className={`
          floating-panel fixed flex flex-col
          backdrop-blur-xl
          border rounded-lg
          shadow-2xl overflow-hidden
          z-[200]
          ${theme === 'dark'
            ? 'bg-[rgba(30,30,30,0.98)] border-white/20'
            : 'bg-[rgba(248,249,250,0.98)] border-black/10'
          }
          ${isDocked ? 'resize-none rounded-none h-screen' : 'min-w-[300px] min-h-[200px]'}
          ${isDragging || isResizing ? 'cursor-grabbing transition-none select-none' : 'transition-all duration-200'}
        `}
        style={{
          ...panelStyle,
          userSelect: isDragging || isResizing ? 'none' : 'auto'
        }}
      >
        {/* Drag handle */}
        <div
          className={`panel-drag-handle h-10 border-b select-none flex items-center justify-between px-3 rounded-t-lg ${
            theme === 'dark'
              ? 'bg-black/20 border-white/10'
              : 'bg-white/40 border-black/5'
          } ${isDragging ? 'cursor-grabbing' : 'cursor-grab'}`}
          onMouseDown={handleDragStart}
        >
          <div className="flex items-center gap-2">
            {icon && <span className="text-orange-500">{icon}</span>}
            <span className={`text-sm font-semibold ${theme === 'dark' ? 'text-white' : 'text-black'}`}>{title}</span>
          </div>
          <button
            onClick={onClose}
            className={`panel-close p-1 rounded transition-colors ${
              theme === 'dark'
                ? 'hover:bg-white/10 text-gray-400 hover:text-white'
                : 'hover:bg-black/5 text-gray-600 hover:text-black'
            }`}
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
            className={`resize-handle absolute bottom-0 right-0 w-5 h-5 cursor-nwse-resize z-10 after:content-[''] after:absolute after:bottom-1 after:right-1 after:w-2.5 after:h-2.5 after:border-r-2 after:border-b-2 ${
              theme === 'dark' ? 'after:border-white/30' : 'after:border-black/20'
            }`}
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
      return 'left-0 top-0 w-[80px] h-screen';
    case 'right':
      return 'right-0 top-0 w-[80px] h-screen';
    case 'top':
      return 'top-0 left-[80px] right-[80px] h-[80px]';
    case 'bottom':
      return 'bottom-0 left-[80px] right-[80px] h-[80px]';
    default:
      return '';
  }
}
