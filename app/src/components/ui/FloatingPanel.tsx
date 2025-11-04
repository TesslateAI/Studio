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
type ResizeDirection = 'se' | 'sw' | 'ne' | 'nw' | 'n' | 's' | 'e' | 'w';

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
  const [resizeDirection, setResizeDirection] = useState<ResizeDirection>('se');
  const [dockHoverPosition, setDockHoverPosition] = useState<DockPosition>(null);
  const [actualDockPosition, setActualDockPosition] = useState<DockPosition>(null);

  const panelRef = useRef<HTMLDivElement>(null);
  const dragStartRef = useRef({ x: 0, y: 0, panelX: 0, panelY: 0 });
  const resizeStartRef = useRef({ x: 0, y: 0, width: 0, height: 0, panelX: 0, panelY: 0 });

  useEffect(() => {
    if (!isDragging && !isResizing) return;

    const handleMouseMove = (e: MouseEvent) => {
      if (isDragging && panelRef.current) {
        // Calculate new position with bounds checking
        const deltaX = e.clientX - dragStartRef.current.x;
        const deltaY = e.clientY - dragStartRef.current.y;

        let newX = dragStartRef.current.panelX + deltaX;
        let newY = dragStartRef.current.panelY + deltaY;

        // Clamp to viewport with some padding
        const minX = -size.width + 100; // Allow dragging mostly off-screen but keep 100px visible
        const maxX = window.innerWidth - 100;
        const minY = 0; // Don't allow dragging above viewport
        const maxY = window.innerHeight - 40; // Keep title bar visible

        newX = Math.max(minX, Math.min(maxX, newX));
        newY = Math.max(minY, Math.min(maxY, newY));

        // Apply transform directly for smooth dragging
        requestAnimationFrame(() => {
          if (panelRef.current) {
            panelRef.current.style.transform = `translate(${newX - dragStartRef.current.panelX}px, ${newY - dragStartRef.current.panelY}px)`;
          }
        });

        // Check for dock zones
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
        const deltaX = e.clientX - resizeStartRef.current.x;
        const deltaY = e.clientY - resizeStartRef.current.y;

        let newWidth = resizeStartRef.current.width;
        let newHeight = resizeStartRef.current.height;
        let newX = resizeStartRef.current.panelX;
        let newY = resizeStartRef.current.panelY;

        // Calculate new dimensions based on resize direction
        const dir = resizeDirection;

        // East: drag right to expand, left to shrink
        if (dir.includes('e')) {
          newWidth = Math.max(300, resizeStartRef.current.width + deltaX);
        }

        // West: drag left to expand, right to shrink
        if (dir.includes('w')) {
          const proposedWidth = Math.max(300, resizeStartRef.current.width - deltaX);
          const actualDelta = proposedWidth - resizeStartRef.current.width;
          newWidth = proposedWidth;
          newX = resizeStartRef.current.panelX - actualDelta;
        }

        // South: drag down to expand, up to shrink
        if (dir.includes('s')) {
          newHeight = Math.max(200, resizeStartRef.current.height + deltaY);
        }

        // North: drag up to expand, down to shrink
        if (dir.includes('n')) {
          const proposedHeight = Math.max(200, resizeStartRef.current.height - deltaY);
          const actualDelta = proposedHeight - resizeStartRef.current.height;
          newHeight = proposedHeight;
          newY = resizeStartRef.current.panelY - actualDelta;
        }

        // Apply resize directly to DOM
        requestAnimationFrame(() => {
          if (panelRef.current) {
            panelRef.current.style.width = `${newWidth}px`;
            panelRef.current.style.height = `${newHeight}px`;
            panelRef.current.style.left = `${newX}px`;
            panelRef.current.style.top = `${newY}px`;
          }
        });
      }
    };

    const handleMouseUp = (e: MouseEvent) => {
      if (isDragging && panelRef.current) {
        // Calculate final position
        const deltaX = e.clientX - dragStartRef.current.x;
        const deltaY = e.clientY - dragStartRef.current.y;

        let newX = dragStartRef.current.panelX + deltaX;
        let newY = dragStartRef.current.panelY + deltaY;

        // Clamp to viewport
        const minX = -size.width + 100;
        const maxX = window.innerWidth - 100;
        const minY = 0;
        const maxY = window.innerHeight - 40;

        newX = Math.max(minX, Math.min(maxX, newX));
        newY = Math.max(minY, Math.min(maxY, newY));

        // Reset transform
        panelRef.current.style.transform = '';

        // Apply docking or update position
        if (dockHoverPosition) {
          setActualDockPosition(dockHoverPosition);
          setDockHoverPosition(null);
        } else {
          setPosition({ x: newX, y: newY });
        }
      } else if (isResizing && panelRef.current) {
        // Commit resize to state
        const rect = panelRef.current.getBoundingClientRect();
        setSize({ width: rect.width, height: rect.height });
        setPosition({ x: rect.left, y: rect.top });
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
  }, [isDragging, isResizing, size, dockHoverPosition, resizeDirection]);

  const handleDragStart = (e: React.MouseEvent) => {
    // Disable dragging on mobile
    if (window.innerWidth < 768) return;

    const rect = panelRef.current?.getBoundingClientRect();
    if (!rect) return;

    dragStartRef.current = {
      x: e.clientX,
      y: e.clientY,
      panelX: rect.left,
      panelY: rect.top
    };

    // If docked, undock and restore to a floating position
    if (actualDockPosition !== null) {
      setPosition(defaultPosition);
      setSize(defaultSize);
      setActualDockPosition(null);
      setTimeout(() => {
        const rect = panelRef.current?.getBoundingClientRect();
        if (rect) {
          dragStartRef.current.panelX = rect.left;
          dragStartRef.current.panelY = rect.top;
        }
      }, 0);
    }

    setIsDragging(true);
  };

  const handleResizeStart = (e: React.MouseEvent, direction: ResizeDirection) => {
    e.stopPropagation();

    const rect = panelRef.current?.getBoundingClientRect();
    if (!rect) return;

    resizeStartRef.current = {
      x: e.clientX,
      y: e.clientY,
      width: rect.width,
      height: rect.height,
      panelX: rect.left,
      panelY: rect.top
    };

    setResizeDirection(direction);
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

  // On mobile, override with empty object (fullscreen handled by CSS)
  const mobileStyleOverride = window.innerWidth < 768 ? {} : panelStyle;

  return (
    <>
      {/* Dock indicator - only show during drag when hovering over dock zone (desktop only) */}
      {isDragging && dockHoverPosition && window.innerWidth >= 768 && (
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
          shadow-2xl overflow-hidden
          z-[200]
          ${theme === 'dark'
            ? 'bg-[rgba(30,30,30,0.98)] md:border-white/20'
            : 'bg-[rgba(248,249,250,0.98)] md:border-black/10'
          }
          ${isDocked ? 'resize-none rounded-none h-screen' : 'md:min-w-[300px] md:min-h-[200px]'}
          ${isDragging || isResizing ? 'cursor-grabbing transition-none select-none' : 'transition-all duration-200'}

          md:border md:rounded-lg
          max-md:inset-0 max-md:w-full max-md:h-full max-md:border-0 max-md:rounded-none
        `}
        style={{
          ...mobileStyleOverride,
          userSelect: isDragging || isResizing ? 'none' : 'auto'
        }}
      >
        {/* Drag handle */}
        <div
          className={`panel-drag-handle h-10 border-b select-none flex items-center justify-between px-3 md:rounded-t-lg md:cursor-grab ${
            theme === 'dark'
              ? 'bg-black/20 border-white/10'
              : 'bg-white/40 border-black/5'
          } ${isDragging ? 'md:cursor-grabbing' : ''} max-md:cursor-default`}
          onMouseDown={handleDragStart}
        >
          <div className="flex items-center gap-2">
            {icon && <span className="text-orange-500">{icon}</span>}
            <span className={`text-sm font-semibold ${theme === 'dark' ? 'text-white' : 'text-black'}`}>{title}</span>
          </div>
          <button
            onClick={onClose}
            className={`panel-close rounded transition-colors p-1 md:p-1 max-md:p-2 ${
              theme === 'dark'
                ? 'hover:bg-white/10 active:bg-white/20 text-gray-400 hover:text-white'
                : 'hover:bg-black/5 active:bg-black/10 text-gray-600 hover:text-black'
            }`}
          >
            <svg className="w-5 h-5 md:w-4 md:h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Panel content */}
        <div className="panel-content flex-1 overflow-y-auto">
          {children}
        </div>

        {/* Resize handles - Desktop only */}
        {!isDocked && (
          <>
            {/* Corner handles */}
            <div
              className="hidden md:block absolute bottom-0 right-0 w-4 h-4 cursor-nwse-resize z-10"
              onMouseDown={(e) => handleResizeStart(e, 'se')}
            >
              <div className={`absolute bottom-0.5 right-0.5 w-2.5 h-2.5 border-r-2 border-b-2 ${
                theme === 'dark' ? 'border-white/30' : 'border-black/20'
              }`} />
            </div>
            <div
              className="hidden md:block absolute bottom-0 left-0 w-4 h-4 cursor-nesw-resize z-10"
              onMouseDown={(e) => handleResizeStart(e, 'sw')}
            />
            <div
              className="hidden md:block absolute top-0 right-0 w-4 h-4 cursor-nesw-resize z-10"
              onMouseDown={(e) => handleResizeStart(e, 'ne')}
            />
            <div
              className="hidden md:block absolute top-0 left-0 w-4 h-4 cursor-nwse-resize z-10"
              onMouseDown={(e) => handleResizeStart(e, 'nw')}
            />

            {/* Edge handles */}
            <div
              className="hidden md:block absolute top-0 left-4 right-4 h-1 cursor-ns-resize z-10"
              onMouseDown={(e) => handleResizeStart(e, 'n')}
            />
            <div
              className="hidden md:block absolute bottom-0 left-4 right-4 h-1 cursor-ns-resize z-10"
              onMouseDown={(e) => handleResizeStart(e, 's')}
            />
            <div
              className="hidden md:block absolute top-4 bottom-4 left-0 w-1 cursor-ew-resize z-10"
              onMouseDown={(e) => handleResizeStart(e, 'w')}
            />
            <div
              className="hidden md:block absolute top-4 bottom-4 right-0 w-1 cursor-ew-resize z-10"
              onMouseDown={(e) => handleResizeStart(e, 'e')}
            />
          </>
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
