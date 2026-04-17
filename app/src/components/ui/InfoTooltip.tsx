import { useState, useRef, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { Info } from '@phosphor-icons/react';

interface InfoTooltipProps {
  children: ReactNode;
  size?: number;
  side?: 'top' | 'bottom';
}

/**
 * Info icon with a portal-rendered tooltip for rich help content.
 * Uses createPortal so it is never clipped by overflow containers.
 */
export function InfoTooltip({ children, size = 15, side = 'bottom' }: InfoTooltipProps) {
  const [visible, setVisible] = useState(false);
  const [pos, setPos] = useState({ top: 0, left: 0 });
  const triggerRef = useRef<HTMLDivElement>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const show = () => {
    timeoutRef.current = setTimeout(() => {
      if (!triggerRef.current) return;
      const rect = triggerRef.current.getBoundingClientRect();
      const offset = 8;
      setPos({
        top: side === 'bottom' ? rect.bottom + offset : rect.top - offset,
        left: rect.left + rect.width / 2,
      });
      setVisible(true);
    }, 200);
  };

  const hide = () => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    setVisible(false);
  };

  return (
    <>
      <div ref={triggerRef} className="inline-flex" onMouseEnter={show} onMouseLeave={hide}>
        <Info
          size={size}
          className="text-[var(--text)]/40 hover:text-[var(--text)]/70 transition-colors cursor-help"
          weight="fill"
        />
      </div>
      {visible &&
        createPortal(
          <div
            className="fixed z-[9999] pointer-events-none"
            style={{
              top: `${pos.top}px`,
              left: `${pos.left}px`,
              transform: side === 'bottom' ? 'translate(-50%, 0)' : 'translate(-50%, -100%)',
            }}
          >
            <div className="w-72 p-3 bg-[var(--surface)] border border-[var(--border,rgba(255,255,255,0.15))] rounded-lg shadow-2xl">
              <div className="text-xs text-[var(--text)]/80 leading-relaxed">{children}</div>
            </div>
          </div>,
          document.body
        )}
    </>
  );
}
