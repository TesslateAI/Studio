/**
 * Design Store — shared state for the design view.
 *
 * Holds the project's oid → metadata index, queues CodeDiffRequests,
 * and maintains a transactional undo/redo stack. Implemented as a
 * vanilla store with a subscribe/notify pattern so any component can
 * subscribe via React's `useSyncExternalStore` without context plumbing.
 *
 * Responsibilities:
 *   - Load + cache the design index (GET /design/index).
 *   - Debounce + batch CodeDiffRequests, flush to POST /design/apply-diff.
 *   - Track undo/redo with action coalescing (consecutive style edits on
 *     the same oid within 500 ms merge into a single history entry).
 *   - Surface apply-diff errors so the UI can roll back / toast.
 */

import { useSyncExternalStore } from 'react';
import {
  designApi,
  type CodeDiffRequest,
  type DesignIndex,
  type DesignIndexEntry,
} from '../../../lib/api';

// ── Action types — one per user intent ────────────────────────────────

export type DesignAction =
  | {
      type: 'update-style';
      oid: string;
      /** Forward CSS patch — what we want after the action. */
      patch: Record<string, string | number | null>;
      /** Inverse CSS patch — what it was before. Used for undo. */
      inverse: Record<string, string | number | null>;
      /** Epoch ms when this action was recorded. */
      at: number;
    }
  | {
      type: 'update-class';
      oid: string;
      classes: string;
      inverseClasses: string;
      at: number;
    }
  | {
      type: 'set-text';
      oid: string;
      text: string;
      inverseText: string;
      at: number;
    }
  | {
      type: 'remove';
      oid: string;
      /** Snapshot of the element before removal, if available. */
      inverseInsert?: CodeDiffRequest['structure_changes'];
      at: number;
    };

export interface DesignSelectionEntry {
  oid: string;
  designId: string;
  tagName: string;
  classList: string[];
  textContent: string;
}

interface DesignStoreState {
  slug: string | null;
  index: DesignIndex;
  indexLoading: boolean;
  indexLoaded: boolean;
  indexError: string | null;
  past: DesignAction[];
  future: DesignAction[];
  /** Requests pending the next debounced flush, keyed by oid. */
  pendingByOid: Map<string, CodeDiffRequest>;
  flushing: boolean;
  lastError: string | null;
  /** Multi-select — set of oids currently highlighted in the canvas. */
  selectedOids: Set<string>;
  /** Full selection metadata keyed by oid, for quick lookup during
   *  delete / copy / group operations. */
  selectionInfo: Map<string, DesignSelectionEntry>;
  /** Clipboard — set by copy, consumed by paste. */
  clipboard: DesignSelectionEntry[];
}

const COALESCE_WINDOW_MS = 500;
const FLUSH_DEBOUNCE_MS = 250;
const MAX_HISTORY = 200;

let state: DesignStoreState = {
  slug: null,
  index: {},
  indexLoading: false,
  indexLoaded: false,
  indexError: null,
  past: [],
  future: [],
  pendingByOid: new Map(),
  flushing: false,
  lastError: null,
  selectedOids: new Set(),
  selectionInfo: new Map(),
  clipboard: [],
};

const listeners = new Set<() => void>();

function emit() {
  for (const l of listeners) l();
}

function setState(patch: Partial<DesignStoreState>) {
  state = { ...state, ...patch };
  emit();
}

function subscribe(l: () => void): () => void {
  listeners.add(l);
  return () => {
    listeners.delete(l);
  };
}

function getSnapshot(): DesignStoreState {
  return state;
}

// ── Public read hooks ─────────────────────────────────────────────────

export function useDesignStore<T>(selector: (s: DesignStoreState) => T): T {
  const snap = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  return selector(snap);
}

export function useDesignIndexEntry(oid: string | null | undefined): DesignIndexEntry | null {
  return useDesignStore((s) => (oid ? s.index[oid] ?? null : null));
}

export function useCanUndo(): boolean {
  return useDesignStore((s) => s.past.length > 0);
}

export function useCanRedo(): boolean {
  return useDesignStore((s) => s.future.length > 0);
}

// ── Initialization ────────────────────────────────────────────────────

/**
 * Bind the store to a project slug and load the index. Safe to call
 * multiple times with the same slug — it becomes a no-op after the
 * first load unless `force` is set.
 */
export async function bindSlug(slug: string, opts: { force?: boolean } = {}): Promise<void> {
  if (state.slug !== slug) {
    // Different project — reset everything.
    setState({
      slug,
      index: {},
      indexLoaded: false,
      indexLoading: false,
      indexError: null,
      past: [],
      future: [],
      pendingByOid: new Map(),
      flushing: false,
      lastError: null,
    });
  }
  if (state.indexLoaded && !opts.force) return;
  await refreshIndex();
}

export async function refreshIndex(): Promise<void> {
  const slug = state.slug;
  if (!slug) return;
  setState({ indexLoading: true, indexError: null });
  try {
    const resp = await designApi.getIndex(slug);
    setState({ index: resp.index, indexLoaded: true, indexLoading: false });
  } catch (err) {
    setState({
      indexLoading: false,
      indexError: err instanceof Error ? err.message : String(err),
    });
  }
}

/**
 * Trigger a full index rebuild (POST /design/index). This injects new
 * OIDs into any files that don't have them yet and updates the cache.
 */
export async function rebuildIndex(): Promise<void> {
  const slug = state.slug;
  if (!slug) return;
  setState({ indexLoading: true, indexError: null });
  try {
    const resp = await designApi.indexProject(slug);
    setState({ index: resp.index, indexLoaded: true, indexLoading: false });
  } catch (err) {
    setState({
      indexLoading: false,
      indexError: err instanceof Error ? err.message : String(err),
    });
  }
}

// ── History helpers ───────────────────────────────────────────────────

function pushHistory(action: DesignAction) {
  const past = [...state.past];
  const prev = past[past.length - 1];

  // Coalesce consecutive style edits on the same oid within the window.
  if (
    prev &&
    prev.type === 'update-style' &&
    action.type === 'update-style' &&
    prev.oid === action.oid &&
    action.at - prev.at < COALESCE_WINDOW_MS
  ) {
    const merged: DesignAction = {
      type: 'update-style',
      oid: action.oid,
      patch: { ...prev.patch, ...action.patch },
      // Inverse keeps the *earliest* original values — only fill keys
      // the inverse does not already have, so the first change wins.
      inverse: { ...action.inverse, ...prev.inverse },
      at: action.at,
    };
    past[past.length - 1] = merged;
  } else {
    past.push(action);
    if (past.length > MAX_HISTORY) past.shift();
  }

  setState({ past, future: [] });
}

// ── Request queue + flush ─────────────────────────────────────────────

let flushTimer: ReturnType<typeof setTimeout> | null = null;

function scheduleFlush() {
  if (flushTimer) clearTimeout(flushTimer);
  flushTimer = setTimeout(() => {
    flushTimer = null;
    void flushPending();
  }, FLUSH_DEBOUNCE_MS);
}

function mergeRequest(existing: CodeDiffRequest | undefined, incoming: CodeDiffRequest): CodeDiffRequest {
  if (!existing) return incoming;
  return {
    oid: incoming.oid,
    attributes: { ...(existing.attributes || {}), ...(incoming.attributes || {}) },
    override_classes: incoming.override_classes ?? existing.override_classes,
    style_patch: { ...(existing.style_patch || {}), ...(incoming.style_patch || {}) },
    text_content: incoming.text_content ?? existing.text_content,
    structure_changes: [
      ...(existing.structure_changes || []),
      ...(incoming.structure_changes || []),
    ],
    wrap_with: incoming.wrap_with ?? existing.wrap_with,
    remove: incoming.remove || existing.remove,
  };
}

function enqueue(req: CodeDiffRequest) {
  const pending = new Map(state.pendingByOid);
  pending.set(req.oid, mergeRequest(pending.get(req.oid), req));
  setState({ pendingByOid: pending });
  scheduleFlush();
}

export async function flushPending(): Promise<void> {
  const slug = state.slug;
  if (!slug) return;
  if (state.flushing) return;
  if (state.pendingByOid.size === 0) return;

  const requests = Array.from(state.pendingByOid.values());
  setState({ pendingByOid: new Map(), flushing: true, lastError: null });

  try {
    const resp = await designApi.applyDiff(slug, requests);
    if (resp.file_errors && resp.file_errors.length > 0) {
      setState({
        flushing: false,
        lastError: `write failed: ${resp.file_errors[0].error}`,
      });
      return;
    }
    if (resp.unknown_oids && resp.unknown_oids.length > 0) {
      // Index is stale — refresh it so future edits resolve.
      void refreshIndex();
    }
    setState({ flushing: false });
  } catch (err) {
    setState({
      flushing: false,
      lastError: err instanceof Error ? err.message : String(err),
    });
  }
}

// ── Public edit API ───────────────────────────────────────────────────

/**
 * Record a CSS style edit on an element. Applies immediately (live
 * runtime update is the caller's responsibility) and schedules a
 * debounced persist.
 *
 * @param oid      Stable data-oid of the target element.
 * @param patch    CSS properties to set. Use empty string or null to remove.
 * @param inverse  Previous values for the same keys (for undo).
 */
export function pushStyleEdit(
  oid: string,
  patch: Record<string, string | number | null>,
  inverse: Record<string, string | number | null>,
): void {
  if (!oid) return;
  pushHistory({ type: 'update-style', oid, patch, inverse, at: Date.now() });
  enqueue({ oid, style_patch: patch });
}

/**
 * Record a className edit on an element. `classes` is the full new
 * className string; the worker will tailwind-merge unless
 * `override_classes` is true.
 */
export function pushClassEdit(
  oid: string,
  classes: string,
  inverseClasses: string,
  overrideClasses = true,
): void {
  if (!oid) return;
  pushHistory({ type: 'update-class', oid, classes, inverseClasses, at: Date.now() });
  enqueue({
    oid,
    attributes: { className: classes },
    override_classes: overrideClasses,
  });
}

export function pushTextEdit(oid: string, text: string, inverseText: string): void {
  if (!oid) return;
  pushHistory({ type: 'set-text', oid, text, inverseText, at: Date.now() });
  enqueue({ oid, text_content: text });
}

export function pushRemove(oid: string): void {
  if (!oid) return;
  pushHistory({ type: 'remove', oid, at: Date.now() });
  enqueue({ oid, remove: true });
}

// ── Undo / redo ───────────────────────────────────────────────────────

function inverseRequest(action: DesignAction): CodeDiffRequest | null {
  switch (action.type) {
    case 'update-style':
      return { oid: action.oid, style_patch: action.inverse };
    case 'update-class':
      return {
        oid: action.oid,
        attributes: { className: action.inverseClasses },
        override_classes: true,
      };
    case 'set-text':
      return { oid: action.oid, text_content: action.inverseText };
    case 'remove':
      // We don't track the removed element's content yet — full
      // restore needs a proper snapshot. For now, undo of a remove
      // just refreshes the index and surfaces an error.
      return null;
  }
}

function forwardRequest(action: DesignAction): CodeDiffRequest | null {
  switch (action.type) {
    case 'update-style':
      return { oid: action.oid, style_patch: action.patch };
    case 'update-class':
      return {
        oid: action.oid,
        attributes: { className: action.classes },
        override_classes: true,
      };
    case 'set-text':
      return { oid: action.oid, text_content: action.text };
    case 'remove':
      return { oid: action.oid, remove: true };
  }
}

export async function undo(): Promise<DesignAction | null> {
  if (state.past.length === 0) return null;
  const action = state.past[state.past.length - 1];
  const req = inverseRequest(action);
  const past = state.past.slice(0, -1);
  const future = [action, ...state.future];
  setState({ past, future });
  if (req) {
    enqueue(req);
    // Flush synchronously so the UI sees the revert fast.
    await flushPending();
  }
  return action;
}

export async function redo(): Promise<DesignAction | null> {
  if (state.future.length === 0) return null;
  const action = state.future[0];
  const req = forwardRequest(action);
  const future = state.future.slice(1);
  const past = [...state.past, action];
  setState({ past, future });
  if (req) {
    enqueue(req);
    await flushPending();
  }
  return action;
}

// ── Selection management ─────────────────────────────────────────────

/**
 * Set or toggle the primary selection. Passing `{additive: true}` adds
 * the element to the existing set; otherwise it replaces.
 */
export function selectElement(
  entry: DesignSelectionEntry | null,
  opts: { additive?: boolean } = {},
): void {
  if (!entry) {
    setState({ selectedOids: new Set(), selectionInfo: new Map() });
    return;
  }
  const oid = entry.oid;
  if (!oid) return;
  if (opts.additive) {
    const nextOids = new Set(state.selectedOids);
    const nextInfo = new Map(state.selectionInfo);
    if (nextOids.has(oid)) {
      nextOids.delete(oid);
      nextInfo.delete(oid);
    } else {
      nextOids.add(oid);
      nextInfo.set(oid, entry);
    }
    setState({ selectedOids: nextOids, selectionInfo: nextInfo });
  } else {
    setState({
      selectedOids: new Set([oid]),
      selectionInfo: new Map([[oid, entry]]),
    });
  }
}

export function clearSelection(): void {
  setState({ selectedOids: new Set(), selectionInfo: new Map() });
}

/**
 * Delete every element in the current selection.
 */
export async function deleteSelected(): Promise<void> {
  if (state.selectedOids.size === 0) return;
  const oids = Array.from(state.selectedOids);
  for (const oid of oids) {
    pushHistory({ type: 'remove', oid, at: Date.now() });
    enqueue({ oid, remove: true });
  }
  clearSelection();
  await flushPending();
}

export function copySelection(): number {
  const entries = Array.from(state.selectionInfo.values());
  setState({ clipboard: entries });
  return entries.length;
}

/**
 * Paste the clipboard as children of the current primary selection.
 * If nothing is selected, paste as siblings of the first clipboard
 * element (no-op if its parent can't be resolved).
 *
 * Note: this uses the simplest possible insert — a fresh `<div>` with
 * the copied element's classes and text. It does NOT yet support
 * cloning nested children, because we don't track codeBlock snapshots
 * on the frontend. A future pass should pull the original source
 * subtree from the index and hand it to the worker verbatim.
 */
export async function pasteClipboard(): Promise<void> {
  if (state.clipboard.length === 0) return;
  const parentOid = Array.from(state.selectedOids)[0];
  if (!parentOid) return;
  const requests: CodeDiffRequest[] = state.clipboard.map((entry) => ({
    oid: parentOid,
    structure_changes: [
      {
        type: 'insert',
        location: 'append',
        element: {
          tag_name: entry.tagName,
          classes: entry.classList.join(' ') || undefined,
          text: entry.textContent || undefined,
        },
      },
    ],
  }));
  for (const req of requests) enqueue(req);
  await flushPending();
  // Refresh index so new oids show up.
  void rebuildIndex();
}

/**
 * Wrap the primary selected element in a new `<div>`. Multi-element
 * grouping would need the worker to collect N adjacent siblings and
 * splice them under a single wrapper — not yet implemented.
 */
export async function groupSelected(className = 'flex gap-2'): Promise<void> {
  if (state.selectedOids.size === 0) return;
  const firstOid = Array.from(state.selectedOids)[0];
  enqueue({
    oid: firstOid,
    wrap_with: { tag_name: 'div', classes: className },
  });
  await flushPending();
  void rebuildIndex();
}

// ── Selection-aware chat integration ─────────────────────────────────

/**
 * Dispatch a window event asking the chat to prefill its input with a
 * reference to the given element. ProjectPage listens and forwards the
 * prefill to ChatContainer.
 */
export function askAIAboutElement(element: {
  oid: string | null;
  tagName: string;
  classList: string[];
  textContent?: string;
  reactComponent?: { name: string; sourceFile?: string } | null;
}): void {
  if (typeof window === 'undefined') return;
  const entry = element.oid ? state.index[element.oid] : null;
  const parts: string[] = [];
  const label = element.oid ? `oid=${element.oid}` : 'selection';
  parts.push(`[${label}`);
  parts.push(`<${element.tagName}>`);
  if (entry?.path) parts.push(entry.path + (entry.start_line ? `:${entry.start_line}` : ''));
  else if (element.reactComponent?.sourceFile) parts.push(element.reactComponent.sourceFile);
  if (entry?.component) parts.push(`in ${entry.component}`);
  if (element.classList.length)
    parts.push('.' + element.classList.slice(0, 3).join('.'));
  parts.push(']');
  const reference = parts.join(' ');
  const text = element.textContent
    ? `${reference}\n"${element.textContent.slice(0, 120)}"\n\n`
    : `${reference}\n\n`;
  window.dispatchEvent(
    new CustomEvent('tesslate:design-ask-ai', {
      detail: {
        oid: element.oid,
        prefill: text,
        indexEntry: entry,
      },
    }),
  );
}

// ── Dev helpers (exposed on window for debugging) ─────────────────────

if (typeof window !== 'undefined') {
  (window as unknown as { __designStore?: unknown }).__designStore = {
    getState: () => state,
    rebuildIndex,
    refreshIndex,
    flushPending,
    undo,
    redo,
  };
}
