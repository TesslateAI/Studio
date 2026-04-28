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
  setPosition,
  setScale,
  useCanvasStore,
  zoomAt,
  zoomCentered,
} from './canvasStore';
import { SnapOverlay } from './SnapOverlay';

interface CanvasViewportProps {
  children: React.ReactNode;
  /** Intrinsic content width in canvas coords. Used to auto-center the
   *  frame so the iframe sits in the middle of the viewport instead of
   *  the top-left corner (its raw 0,0 origin). */
  contentWidth: number;
  contentHeight: number;
}

/** Window event that triggers a manual recenter (Toolbar dispatches it). */
export const RECENTER_CANVAS_EVENT = 'design:recenter-canvas';

/** Element id used by adaptRectToCanvas and anything that wants to
 *  read the current canvas transform matrix off the DOM. */
export const CANVAS_FRAME_ID = 'design-canvas-frame';

export const CanvasViewport: React.FC<CanvasViewportProps> = ({ children, contentWidth, contentHeight }) => {
  const containerRef = useRef<HTMLDivElement>(null);

  const scale = useCanvasStore((s) => s.scale);
  const position = useCanvasStore((s) => s.position);
  const isPanning = useCanvasStore((s) => s.isPanning);
  const slug = useCanvasStore((s) => s.slug);

  // Track whether the user has actively panned/zoomed. Until they have,
  // the viewport keeps re-centering on content/container size changes.
  const hasUserMovedRef = useRef(false);
  const scaleRef = useRef(scale);
  scaleRef.current = scale;
  const contentWRef = useRef(contentWidth);
  contentWRef.current = contentWidth;
  const contentHRef = useRef(contentHeight);
  contentHRef.current = contentHeight;

  // Reset auto-center tracking whenever the project (or breakpoint) changes
  // so the new content lands centered.
  useEffect(() => {
    hasUserMovedRef.current = false;
  }, [slug, contentWidth, contentHeight]);

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

  // ── Wheel: ctrl/cmd = zoom, otherwise pan (Figma-style trackpad) ──
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const handleWheel = (e: WheelEvent) => {
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        const rect = el.getBoundingClientRect();
        zoomAt(e.clientX, e.clientY, e.deltaY, { left: rect.left, top: rect.top });
        hasUserMovedRef.current = true;
        return;
      }
      // Trackpad two-finger scroll OR shift+wheel → pan. Mouse wheel
      // without modifier is also treated as vertical pan so users always
      // have a way to move the canvas without learning hotkeys.
      e.preventDefault();
      const dx = e.shiftKey && e.deltaX === 0 ? e.deltaY : e.deltaX;
      const dy = e.shiftKey && e.deltaX === 0 ? 0 : e.deltaY;
      setPosition({ x: positionRef.current.x - dx, y: positionRef.current.y - dy });
      hasUserMovedRef.current = true;
    };

    // Must be non-passive to call preventDefault.
    el.addEventListener('wheel', handleWheel, { passive: false });
    return () => el.removeEventListener('wheel', handleWheel);
  }, []);

  // ── Auto-center until the user moves the canvas ────────────────────
  const recenter = useCallback((opts?: { resetZoom?: boolean }) => {
    const el = containerRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const targetScale = opts?.resetZoom ? 1 : scaleRef.current;
    if (opts?.resetZoom && targetScale !== scaleRef.current) {
      setScale(1);
    }
    const w = contentWRef.current;
    const h = contentHRef.current;
    if (!w || !h || rect.width === 0 || rect.height === 0) return;
    setPosition({
      x: (rect.width - w * targetScale) / 2,
      y: (rect.height - h * targetScale) / 2,
    });
    if (opts?.resetZoom) hasUserMovedRef.current = false;
  }, []);

  // Initial + responsive auto-center while the user hasn't moved yet.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const tryCenter = () => {
      if (hasUserMovedRef.current) return;
      recenter();
    };
    tryCenter();
    const ro = new ResizeObserver(() => tryCenter());
    ro.observe(el);
    return () => ro.disconnect();
  }, [recenter]);

  // Re-center whenever content dimensions change (e.g. breakpoint switch),
  // even after the user has moved — switching viewport is an intentional
  // signal to re-frame.
  useEffect(() => {
    hasUserMovedRef.current = false;
    recenter();
  }, [contentWidth, contentHeight, recenter]);

  // External recenter request (Toolbar button → window event).
  useEffect(() => {
    const handler = () => recenter({ resetZoom: true });
    window.addEventListener(RECENTER_CANVAS_EVENT, handler);
    return () => window.removeEventListener(RECENTER_CANVAS_EVENT, handler);
  }, [recenter]);

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
    hasUserMovedRef.current = true;
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

  useHotkeys('0', () => recenter({ resetZoom: true }), { preventDefault: true }, [recenter]);
  useHotkeys(
    ['=', '+', 'shift+='],
    () => {
      hasUserMovedRef.current = true;
      zoomCentered(1.2, getViewportSize());
    },
    { preventDefault: true },
    [getViewportSize],
  );
  useHotkeys(
    ['-', '_'],
    () => {
      hasUserMovedRef.current = true;
      zoomCentered(1 / 1.2, getViewportSize());
    },
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
        onClick={() => recenter({ resetZoom: true })}
        className="absolute bottom-2 right-2 z-20 flex items-center gap-1.5 px-2 py-1 rounded-full text-[10px] font-medium backdrop-blur-sm border hover:opacity-90 transition-opacity"
        style={{
          background: 'color-mix(in srgb, var(--surface, #1e1e1e) 85%, transparent)',
          borderColor: 'var(--border)',
          color: 'var(--text-muted)',
        }}
        title="Recenter (0)"
      >
        <Maximize2 className="w-3 h-3" />
        <span>{zoomPct}%</span>
      </button>
    </div>
  );
};

export default CanvasViewport;
