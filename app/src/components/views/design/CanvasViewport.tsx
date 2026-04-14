/**
 * Canvas Viewport — pan/zoom container that wraps the design iframe.
 *
 * Mirrors Onlook's canvas container pattern: a full-size element that
 * hosts a single transformed child. All pointer/wheel interactions are
 * translated into store updates, and the SnapOverlay sits on top as a
 * non-interactive visual layer.
 *
 * Interactions:
 *   - ctrl/cmd + wheel:   pointer-anchored zoom
 *   - space + drag:       pan (grab cursor)
 *   - middle-button drag: pan (alternative)
 */

import React, { useCallback, useEffect, useMemo, useRef } from 'react';
import { useHotkeys } from 'react-hotkeys-hook';
import { Maximize2 } from 'lucide-react';
import {
  beginPan,
  clearSnapLines,
  endPan,
  resetCanvas,
  setPosition,
  useCanvasStore,
  zoomAt,
  zoomCentered,
} from './canvasStore';
import { SnapOverlay } from './SnapOverlay';

interface CanvasViewportProps {
  children: React.ReactNode;
}

/** Element id used by adaptRectToCanvas and anything that wants to
 *  read the current canvas transform matrix off the DOM. */
export const CANVAS_FRAME_ID = 'design-canvas-frame';

export const CanvasViewport: React.FC<CanvasViewportProps> = ({ children }) => {
  const containerRef = useRef<HTMLDivElement>(null);

  const scale = useCanvasStore((s) => s.scale);
  const position = useCanvasStore((s) => s.position);
  const isPanning = useCanvasStore((s) => s.isPanning);

  // Local refs so event handlers don't re-bind on every state change.
  const spaceDownRef = useRef(false);
  const panStateRef = useRef<{
    active: boolean;
    startX: number;
    startY: number;
    originX: number;
    originY: number;
    pointerId: number | null;
  }>({
    active: false,
    startX: 0,
    startY: 0,
    originX: 0,
    originY: 0,
    pointerId: null,
  });
  const positionRef = useRef(position);
  positionRef.current = position;

  // ── Wheel zoom ────────────────────────────────────────────────────
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const handleWheel = (e: WheelEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      zoomAt(e.clientX, e.clientY, e.deltaY, { left: rect.left, top: rect.top });
    };

    // Must be non-passive to call preventDefault.
    el.addEventListener('wheel', handleWheel, { passive: false });
    return () => el.removeEventListener('wheel', handleWheel);
  }, []);

  // ── Space key tracking (global so it works when the iframe has focus too) ──
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.code !== 'Space') return;
      // Ignore space-as-input inside form fields.
      const target = e.target as HTMLElement | null;
      if (target && ['INPUT', 'TEXTAREA'].includes(target.tagName)) return;
      if (target && target.isContentEditable) return;
      spaceDownRef.current = true;
      if (containerRef.current) containerRef.current.style.cursor = 'grab';
    };
    const handleKeyUp = (e: KeyboardEvent) => {
      if (e.code !== 'Space') return;
      spaceDownRef.current = false;
      if (!panStateRef.current.active && containerRef.current) {
        containerRef.current.style.cursor = '';
      }
    };
    const handleBlur = () => {
      spaceDownRef.current = false;
      if (!panStateRef.current.active && containerRef.current) {
        containerRef.current.style.cursor = '';
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    window.addEventListener('keyup', handleKeyUp);
    window.addEventListener('blur', handleBlur);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('keyup', handleKeyUp);
      window.removeEventListener('blur', handleBlur);
    };
  }, []);

  // ── Pan on pointer down ───────────────────────────────────────────
  const handlePointerDown = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    const isMiddleButton = e.button === 1;
    const isSpacePan = spaceDownRef.current && e.button === 0;
    if (!isMiddleButton && !isSpacePan) return;
    e.preventDefault();
    const el = containerRef.current;
    if (!el) return;
    try {
      el.setPointerCapture(e.pointerId);
    } catch {
      // Capture failures (older browsers) — pan still works via window listeners.
    }
    panStateRef.current = {
      active: true,
      startX: e.clientX,
      startY: e.clientY,
      originX: positionRef.current.x,
      originY: positionRef.current.y,
      pointerId: e.pointerId,
    };
    beginPan();
    clearSnapLines();
    el.style.cursor = 'grabbing';
  }, []);

  const handlePointerMove = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    const s = panStateRef.current;
    if (!s.active) return;
    const dx = e.clientX - s.startX;
    const dy = e.clientY - s.startY;
    setPosition({ x: s.originX + dx, y: s.originY + dy });
  }, []);

  const finishPan = useCallback((e?: React.PointerEvent<HTMLDivElement>) => {
    const s = panStateRef.current;
    if (!s.active) return;
    const el = containerRef.current;
    if (el && e && s.pointerId !== null) {
      try {
        el.releasePointerCapture(s.pointerId);
      } catch {
        // ignore
      }
    }
    panStateRef.current = { ...s, active: false, pointerId: null };
    endPan();
    if (el) {
      el.style.cursor = spaceDownRef.current ? 'grab' : '';
    }
  }, []);

  // Clean up a hanging pan state on unmount (e.g. unmount mid-drag).
  useEffect(() => {
    return () => {
      if (panStateRef.current.active) {
        panStateRef.current.active = false;
        endPan();
      }
    };
  }, []);

  // ── Keyboard shortcuts ────────────────────────────────────────────
  const getViewportSize = useCallback((): { width: number; height: number } => {
    const el = containerRef.current;
    if (!el) return { width: 0, height: 0 };
    const rect = el.getBoundingClientRect();
    return { width: rect.width, height: rect.height };
  }, []);

  useHotkeys('0', () => resetCanvas(), { preventDefault: true }, []);
  useHotkeys(
    ['=', '+', 'shift+='],
    () => zoomCentered(1.2, getViewportSize()),
    { preventDefault: true },
    [getViewportSize],
  );
  useHotkeys(
    ['-', '_'],
    () => zoomCentered(1 / 1.2, getViewportSize()),
    { preventDefault: true },
    [getViewportSize],
  );

  const frameStyle = useMemo<React.CSSProperties>(
    () => ({
      position: 'absolute',
      left: 0,
      top: 0,
      width: 0,
      height: 0,
      transformOrigin: '0 0',
      transform: `translate(${position.x}px, ${position.y}px) scale(${scale})`,
      willChange: 'transform',
    }),
    [position.x, position.y, scale],
  );

  const zoomPct = Math.round(scale * 100);

  return (
    <div
      ref={containerRef}
      className="relative w-full h-full overflow-hidden select-none"
      style={{
        background: 'var(--surface, #0b0b0b)',
        touchAction: 'none',
      }}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={finishPan}
      onPointerCancel={finishPan}
      onPointerLeave={(e) => {
        // Pointer capture should keep us receiving events, but if
        // capture isn't available, fall through to end the pan.
        if (panStateRef.current.pointerId === null) finishPan(e);
      }}
      data-panning={isPanning || undefined}
    >
      <div id={CANVAS_FRAME_ID} style={frameStyle}>
        {children}
      </div>

      {/* Snap guidelines — pointer-events none, sits above the frame. */}
      <SnapOverlay />

      <button
        type="button"
        onClick={() => resetCanvas()}
        className="absolute bottom-2 right-2 z-20 flex items-center gap-1.5 px-2 py-1 rounded-full text-[10px] font-medium backdrop-blur-sm border hover:opacity-90 transition-opacity"
        style={{
          background: 'color-mix(in srgb, var(--surface, #1e1e1e) 85%, transparent)',
          borderColor: 'var(--border)',
          color: 'var(--text-muted)',
        }}
        title="Reset zoom (0)"
      >
        <Maximize2 className="w-3 h-3" />
        <span>{zoomPct}%</span>
      </button>
    </div>
  );
};

export default CanvasViewport;
