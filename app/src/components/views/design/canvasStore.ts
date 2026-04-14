/**
 * Canvas Store — pan/zoom state for the design view.
 *
 * Vanilla module-level store (subscribe/notify) consumed via
 * `useSyncExternalStore`. Mirrors Onlook's CanvasManager + SnapManager
 * but rewritten with the same patterns as `designStore.ts` so the
 * design view has no context/provider plumbing.
 *
 * Responsibilities:
 *   - Hold {position, scale, isPanning, snapLines} for the active project.
 *   - Clamp scale/position to safe bounds.
 *   - Pointer-anchored zoom math (world point under the cursor stays fixed).
 *   - Per-slug persistence to localStorage (300 ms debounced).
 *   - Provide `adaptRectToCanvas` helper mirroring Onlook's transform logic.
 */

import { useSyncExternalStore } from 'react';

// ── Types ─────────────────────────────────────────────────────────────

export interface CanvasPosition {
  x: number;
  y: number;
}

export interface Rect {
  top: number;
  left: number;
  width: number;
  height: number;
}

export type SnapOrientation = 'horizontal' | 'vertical';
export type SnapType = 'edge' | 'center';

export interface SnapLine {
  id: string;
  orientation: SnapOrientation;
  /** Position in canvas/world coordinates along the perpendicular axis. */
  position: number;
  /** Line extent start along the parallel axis (world coords). */
  start: number;
  /** Line extent end along the parallel axis (world coords). */
  end: number;
  type: SnapType;
}

interface CanvasStoreState {
  slug: string | null;
  position: CanvasPosition;
  scale: number;
  isPanning: boolean;
  snapLines: SnapLine[];
}

// ── Constants ─────────────────────────────────────────────────────────

export const CANVAS_MIN_SCALE = 0.1;
export const CANVAS_MAX_SCALE = 3;
export const CANVAS_MIN_POS = -10000;
export const CANVAS_MAX_POS = 10000;

/** Snap threshold in canvas (world) pixels. */
export const SNAP_THRESHOLD = 12;

const DEFAULT_STATE: Omit<CanvasStoreState, 'slug'> = {
  position: { x: 0, y: 0 },
  scale: 1,
  isPanning: false,
  snapLines: [],
};

const PERSIST_DEBOUNCE_MS = 300;
const STORAGE_PREFIX = 'design-canvas:';

// ── Module state ──────────────────────────────────────────────────────

let state: CanvasStoreState = {
  slug: null,
  ...DEFAULT_STATE,
};

const listeners = new Set<() => void>();

function emit(): void {
  for (const l of listeners) l();
}

function setState(patch: Partial<CanvasStoreState>): void {
  state = { ...state, ...patch };
  emit();
  schedulePersist();
}

function subscribe(l: () => void): () => void {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
}

function getSnapshot(): CanvasStoreState {
  return state;
}

// ── Clamping helpers ──────────────────────────────────────────────────

function clamp(v: number, lo: number, hi: number): number {
  if (Number.isNaN(v)) return lo;
  return v < lo ? lo : v > hi ? hi : v;
}

function clampScale(s: number): number {
  return clamp(s, CANVAS_MIN_SCALE, CANVAS_MAX_SCALE);
}

function clampPosition(p: CanvasPosition): CanvasPosition {
  return {
    x: clamp(p.x, CANVAS_MIN_POS, CANVAS_MAX_POS),
    y: clamp(p.y, CANVAS_MIN_POS, CANVAS_MAX_POS),
  };
}

// ── Persistence (debounced localStorage) ──────────────────────────────

let persistTimer: ReturnType<typeof setTimeout> | null = null;

function schedulePersist(): void {
  if (typeof window === 'undefined') return;
  if (!state.slug) return;
  if (persistTimer) clearTimeout(persistTimer);
  persistTimer = setTimeout(() => {
    persistTimer = null;
    writePersistedState();
  }, PERSIST_DEBOUNCE_MS);
}

function writePersistedState(): void {
  if (typeof window === 'undefined') return;
  const slug = state.slug;
  if (!slug) return;
  try {
    const payload = JSON.stringify({
      position: state.position,
      scale: state.scale,
    });
    window.localStorage.setItem(STORAGE_PREFIX + slug, payload);
  } catch {
    // Quota or serialization errors are non-fatal — canvas just won't persist.
  }
}

function readPersistedState(slug: string): { position: CanvasPosition; scale: number } | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(STORAGE_PREFIX + slug);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<{ position: CanvasPosition; scale: number }>;
    if (
      !parsed ||
      typeof parsed.scale !== 'number' ||
      !parsed.position ||
      typeof parsed.position.x !== 'number' ||
      typeof parsed.position.y !== 'number'
    ) {
      return null;
    }
    return {
      position: clampPosition(parsed.position),
      scale: clampScale(parsed.scale),
    };
  } catch {
    return null;
  }
}

// ── Public actions ────────────────────────────────────────────────────

export function bindSlug(slug: string): void {
  if (state.slug === slug) return;
  // Flush any pending persist for the previous slug before switching.
  if (persistTimer) {
    clearTimeout(persistTimer);
    persistTimer = null;
    writePersistedState();
  }
  const restored = readPersistedState(slug);
  state = {
    slug,
    position: restored?.position ?? { ...DEFAULT_STATE.position },
    scale: restored?.scale ?? DEFAULT_STATE.scale,
    isPanning: false,
    snapLines: [],
  };
  emit();
}

export function setPosition(p: CanvasPosition): void {
  setState({ position: clampPosition(p) });
}

export function setScale(s: number): void {
  setState({ scale: clampScale(s) });
}

/**
 * Zoom anchored at a client-space point so the world point under the
 * cursor stays fixed. `delta` is the raw wheel deltaY (negative = zoom
 * in). `viewportRect` is the bounding rect of the viewport container,
 * used to translate client coords into container-local coords.
 */
export function zoomAt(
  clientX: number,
  clientY: number,
  delta: number,
  viewportRect: { left: number; top: number },
): void {
  const prevScale = state.scale;
  // Exponential feel — matches typical design-tool zoom curves.
  const factor = Math.exp(-delta * 0.0015);
  const nextScale = clampScale(prevScale * factor);
  if (nextScale === prevScale) return;

  // Container-local coords of the cursor.
  const cx = clientX - viewportRect.left;
  const cy = clientY - viewportRect.top;

  // zoom is anchored at cursor — (cx, cy) stays fixed in world coords.
  // world = (client - pos) / scale  ⇒  pos_new = client - world * scale_new
  const worldX = (cx - state.position.x) / prevScale;
  const worldY = (cy - state.position.y) / prevScale;
  const nextPosition = clampPosition({
    x: cx - worldX * nextScale,
    y: cy - worldY * nextScale,
  });

  setState({ scale: nextScale, position: nextPosition });
}

/**
 * Zoom centered on the viewport itself (for keyboard +/- shortcuts).
 */
export function zoomCentered(factor: number, viewportRect: { width: number; height: number }): void {
  const prevScale = state.scale;
  const nextScale = clampScale(prevScale * factor);
  if (nextScale === prevScale) return;
  const cx = viewportRect.width / 2;
  const cy = viewportRect.height / 2;
  const worldX = (cx - state.position.x) / prevScale;
  const worldY = (cy - state.position.y) / prevScale;
  const nextPosition = clampPosition({
    x: cx - worldX * nextScale,
    y: cy - worldY * nextScale,
  });
  setState({ scale: nextScale, position: nextPosition });
}

export function resetCanvas(): void {
  setState({
    position: { ...DEFAULT_STATE.position },
    scale: DEFAULT_STATE.scale,
  });
}

export function beginPan(): void {
  if (state.isPanning) return;
  setState({ isPanning: true });
}

export function endPan(): void {
  if (!state.isPanning) return;
  setState({ isPanning: false });
}

export function setSnapLines(lines: SnapLine[]): void {
  setState({ snapLines: lines });
}

export function clearSnapLines(): void {
  if (state.snapLines.length === 0) return;
  setState({ snapLines: [] });
}

// ── React hooks ───────────────────────────────────────────────────────

export function useCanvasStore<T>(selector: (s: CanvasStoreState) => T): T {
  const snap = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  return selector(snap);
}

export function useCanvasTransform(): string {
  // Select primitives to keep referential equality stable — returning
  // a fresh object each render would make useSyncExternalStore loop.
  const x = useCanvasStore((s) => s.position.x);
  const y = useCanvasStore((s) => s.position.y);
  const scale = useCanvasStore((s) => s.scale);
  return `translate(${x}px, ${y}px) scale(${scale})`;
}

// ── Coordinate adapter ────────────────────────────────────────────────

/**
 * Adapt a rect in iframe-space coordinates to canvas (world) space,
 * applying the current canvas transform matrix. Mirrors Onlook's
 * `adaptRectToCanvas` — reads the computed CSS transform off the
 * element rather than the module state so it stays in sync with the
 * actual painted transform (the two can briefly diverge during CSS
 * transitions).
 *
 * @param rect       Rect in the source element's local coordinates.
 * @param frameEl    The element whose transform we want to apply (the
 *                   transformed child of CanvasViewport).
 * @param inverse    When true, converts canvas-space back to frame-space.
 */
export function adaptRectToCanvas(rect: Rect, frameEl: HTMLElement, inverse = false): Rect {
  if (typeof window === 'undefined') return rect;
  let matrix: DOMMatrix;
  try {
    matrix = new DOMMatrix(getComputedStyle(frameEl).transform);
  } catch {
    return rect;
  }
  const a = matrix.a || 1;
  const scale = inverse ? 1 / a : a;
  const tx = inverse ? -matrix.e / a : matrix.e;
  const ty = inverse ? -matrix.f / a : matrix.f;
  return {
    width: rect.width * scale,
    height: rect.height * scale,
    left: rect.left * scale + tx,
    top: rect.top * scale + ty,
  };
}

// ── Snap computation (MVP) ────────────────────────────────────────────

/**
 * Compute snap lines for a dragging rect against viewport edges and
 * center. Stub-quality for Phase 4 — Phase 5 drag logic will call this
 * with live drag rects. Threshold and rects are in canvas/world coords.
 */
export function computeSnapLines(dragRect: Rect, viewportRect: Rect): SnapLine[] {
  const lines: SnapLine[] = [];

  const dragLeft = dragRect.left;
  const dragRight = dragRect.left + dragRect.width;
  const dragTop = dragRect.top;
  const dragBottom = dragRect.top + dragRect.height;
  const dragCenterX = dragLeft + dragRect.width / 2;
  const dragCenterY = dragTop + dragRect.height / 2;

  const vpLeft = viewportRect.left;
  const vpRight = viewportRect.left + viewportRect.width;
  const vpTop = viewportRect.top;
  const vpBottom = viewportRect.top + viewportRect.height;
  const vpCenterX = vpLeft + viewportRect.width / 2;
  const vpCenterY = vpTop + viewportRect.height / 2;

  // Vertical lines (constant x).
  const verticalTargets: Array<{ drag: number; target: number; type: SnapType; id: string }> = [
    { drag: dragLeft, target: vpLeft, type: 'edge', id: 'vp-left' },
    { drag: dragRight, target: vpRight, type: 'edge', id: 'vp-right' },
    { drag: dragCenterX, target: vpCenterX, type: 'center', id: 'vp-center-x' },
  ];
  for (const t of verticalTargets) {
    if (Math.abs(t.drag - t.target) <= SNAP_THRESHOLD) {
      lines.push({
        id: `v-${t.id}`,
        orientation: 'vertical',
        position: t.target,
        start: Math.min(vpTop, dragTop) - 160,
        end: Math.max(vpBottom, dragBottom) + 160,
        type: t.type,
      });
    }
  }

  // Horizontal lines (constant y).
  const horizontalTargets: Array<{ drag: number; target: number; type: SnapType; id: string }> = [
    { drag: dragTop, target: vpTop, type: 'edge', id: 'vp-top' },
    { drag: dragBottom, target: vpBottom, type: 'edge', id: 'vp-bottom' },
    { drag: dragCenterY, target: vpCenterY, type: 'center', id: 'vp-center-y' },
  ];
  for (const t of horizontalTargets) {
    if (Math.abs(t.drag - t.target) <= SNAP_THRESHOLD) {
      lines.push({
        id: `h-${t.id}`,
        orientation: 'horizontal',
        position: t.target,
        start: Math.min(vpLeft, dragLeft) - 160,
        end: Math.max(vpRight, dragRight) + 160,
        type: t.type,
      });
    }
  }

  return lines;
}

// ── Dev helpers ───────────────────────────────────────────────────────

if (typeof window !== 'undefined') {
  (window as unknown as { __canvasStore?: unknown }).__canvasStore = {
    getState: () => state,
    resetCanvas,
    setPosition,
    setScale,
  };
}
