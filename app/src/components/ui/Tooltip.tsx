import { useState, ReactNode } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

interface TooltipProps {
  content: string;
  children: ReactNode;
  side?: 'top' | 'bottom' | 'left' | 'right';
  delay?: number;
}

export function Tooltip({ content, children, side = 'right', delay = 300 }: TooltipProps) {
  const [isVisible, setIsVisible] = useState(false);
  let timeoutId: ReturnType<typeof setTimeout>;

  const handleMouseEnter = () => {
    timeoutId = setTimeout(() => {
      setIsVisible(true);
    }, delay);
  };

  const handleMouseLeave = () => {
    clearTimeout(timeoutId);
    setIsVisible(false);
  };

  const getPosition = () => {
    switch (side) {
      case 'top':
        return { bottom: '100%', left: '50%', transform: 'translateX(-50%)', marginBottom: '8px' };
      case 'bottom':
        return { top: '100%', left: '50%', transform: 'translateX(-50%)', marginTop: '8px' };
      case 'left':
        return { right: '100%', top: '50%', transform: 'translateY(-50%)', marginRight: '8px' };
      case 'right':
        return { left: '100%', top: '0', marginLeft: '8px', marginTop: '7px' };
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

  return (
    <div
      className="relative inline-block"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      {children}
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
            className="absolute z-50 pointer-events-none whitespace-nowrap flex items-center"
            style={getPosition()}
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
    </div>
  );
}
