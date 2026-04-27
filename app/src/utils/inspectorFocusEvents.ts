/**
 * Event bus for inspector-focus requests.
 *
 * The PublishAsAppDrawer's "Fix in inspector" button asks the canvas to
 * select a container by name and scroll the App Contract section to the
 * relevant editor row (action / connector). Wiring it as an EventTarget
 * mirrors :mod:`utils/nodeConfigEvents` and keeps PublishAsAppDrawer free
 * of canvas / panel imports — the drawer only knows the container name,
 * not the React Flow node id.
 *
 * Flow:
 *   1. PublishAsAppDrawer calls ``onJumpToInspector(target)``.
 *   2. ArchitectureView's handler closes the drawer, looks up the
 *      container id by name, and ``setSelectedContainer(...)``.
 *   3. After the panel mounts, ArchitectureView emits
 *      ``inspector-focus-request`` with the (resolved) target. The
 *      ContainerPropertiesPanel's effect listens for this event and
 *      scrolls the matching action / connector row into view.
 *
 * The bus is process-singleton so listeners can subscribe before the
 * emitter mounts (events with no subscribers are silently dropped, same
 * as ``EventTarget``).
 */

export type InspectorFocusKind = 'action' | 'connector';

export interface InspectorFocusRequest {
  /** Container id the panel is mounted for — listeners bail when this
   *  doesn't match their containerId. */
  containerId: string;
  /** What to focus inside the App Contract section. */
  kind: InspectorFocusKind;
  /** action_name when kind='action', connector_id when kind='connector'.
   *  Optional: when missing the panel just expands the section. */
  name?: string;
}

type InspectorFocusEventMap = {
  'inspector-focus-request': InspectorFocusRequest;
};

class InspectorFocusEventBus {
  private readonly target: EventTarget = new EventTarget();

  emit<K extends keyof InspectorFocusEventMap>(
    type: K,
    detail: InspectorFocusEventMap[K]
  ): void {
    this.target.dispatchEvent(new CustomEvent(type, { detail }));
  }

  on<K extends keyof InspectorFocusEventMap>(
    type: K,
    callback: (detail: InspectorFocusEventMap[K]) => void
  ): () => void {
    const handler = (event: Event) => {
      callback((event as CustomEvent<InspectorFocusEventMap[K]>).detail);
    };
    this.target.addEventListener(type, handler);
    return () => this.target.removeEventListener(type, handler);
  }
}

export const inspectorFocusEvents = new InspectorFocusEventBus();
