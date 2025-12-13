import { useState, useRef, ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'framer-motion';

interface TooltipProps {
  content: string;
  children: ReactNode;
  side?: 'top' | 'bottom' | 'left' | 'right';
  delay?: number;
}

export function Tooltip({ content, children, side = 'right', delay = 300 }: TooltipProps) {
  const [isVisible, setIsVisible] = useState(false);
  const [position, setPosition] = useState({ top: 0, left: 0 });
  const timeoutRef = useRef<ReturnType<typeof setTimeout>>();
  const triggerRef = useRef<HTMLDivElement>(null);

  const handleMouseEnter = () => {
    timeoutRef.current = setTimeout(() => {
      if (triggerRef.current) {
        const rect = triggerRef.current.getBoundingClientRect();
        updatePosition(rect);
      }
      setIsVisible(true);
    }, delay);
  };

  const handleMouseLeave = () => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }
    setIsVisible(false);
  };

  const updatePosition = (rect: DOMRect) => {
    const offset = 8;
    let top = 0;
    let left = 0;

    switch (side) {
      case 'top':
        top = rect.top - offset;
        left = rect.left + rect.width / 2;
        break;
      case 'bottom':
        top = rect.bottom + offset;
        left = rect.left + rect.width / 2;
        break;
      case 'left':
        top = rect.top + rect.height / 2;
        left = rect.left - offset;
        break;
      case 'right':
        top = rect.top + 7;
        left = rect.right + offset;
        break;
    }

    setPosition({ top, left });
  };

  const getTransform = () => {
    switch (side) {
      case 'top':
        return 'translate(-50%, -100%)';
      case 'bottom':
        return 'translate(-50%, 0)';
      case 'left':
        return 'translate(-100%, -50%)';
      case 'right':
        return 'translate(0, 0)';
    }
  };

  const getAnimationProps = () => {
    switch (side) {
      case 'top':
        return { initial: { opacity: 0, y: 3, scale: 0.95 }, animate: { opacity: 1, y: 0, scale: 1 } };
      case 'bottom':
        return { initial: { opacity: 0, y: -3, scale: 0.95 }, animate: { opacity: 1, y: 0, scale: 1 } };
      case 'left':
        return { initial: { opacity: 0, x: 3, scale: 0.95 }, animate: { opacity: 1, x: 0, scale: 1 } };
      case 'right':
        return { initial: { opacity: 0, x: -3, scale: 0.95 }, animate: { opacity: 1, x: 0, scale: 1 } };
    }
  };

  const tooltipContent = (
    <AnimatePresence>
      {isVisible && (
        <motion.div
          {...getAnimationProps()}
          exit={{ opacity: 0, scale: 0.95 }}
          transition={{
            type: 'spring',
            stiffness: 600,
            damping: 25,
            mass: 0.4,
          }}
          className="fixed z-[9999] pointer-events-none whitespace-nowrap flex items-center"
          style={{
            top: `${position.top}px`,
            left: `${position.left}px`,
            transform: getTransform(),
          }}
        >
          {/* Arrow - positioned before the tooltip box for right side */}
          {side === 'right' && (
            <div
              className="w-0 h-0 border-t-[6px] border-t-transparent border-b-[6px] border-b-transparent border-r-[6px] border-r-black"
              style={{ marginRight: '-1px' }}
            />
          )}

          <div className="bg-black rounded-md px-2.5 py-1.5 shadow-2xl">
            <span className="text-xs font-medium text-white">{content}</span>
          </div>

          {/* Arrow for other sides */}
          {side === 'left' && (
            <div
              className="w-0 h-0 border-t-[6px] border-t-transparent border-b-[6px] border-b-transparent border-l-[6px] border-l-black"
              style={{ marginLeft: '-1px' }}
            />
          )}
          {side === 'top' && (
            <div
              className="absolute w-0 h-0 border-l-[6px] border-l-transparent border-r-[6px] border-r-transparent border-t-[6px] border-t-black"
              style={{ bottom: '-5px', left: '50%', transform: 'translateX(-50%)' }}
            />
          )}
          {side === 'bottom' && (
            <div
              className="absolute w-0 h-0 border-l-[6px] border-l-transparent border-r-[6px] border-r-transparent border-b-[6px] border-b-black"
              style={{ top: '-5px', left: '50%', transform: 'translateX(-50%)' }}
            />
          )}
        </motion.div>
      )}
    </AnimatePresence>
  );

  return (
    <>
      <div
        ref={triggerRef}
        className="relative inline-block"
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
      >
        {children}
      </div>
      {createPortal(tooltipContent, document.body)}
    </>
  );
}
