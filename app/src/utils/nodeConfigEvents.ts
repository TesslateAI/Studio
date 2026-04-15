/**
 * Event bus for agent-driven node-config events.
 *
 * `useAgentChat` emits these when it sees the corresponding SSE event; the
 * ProjectPage listener is responsible for opening/closing dock tabs and
 * updating the pending-config context. This keeps `useAgentChat` free of
 * UI dependencies (toasts, query client, dock state).
 */

import type {
  ArchitectureNodeAddedEvent,
  NodeConfigCancelledEvent,
  NodeConfigResumedEvent,
  SecretRotatedEvent,
  UserInputRequiredEvent,
} from '../types/nodeConfig';

/** Client-originated request to open the direct-edit config tab for a container. */
export interface OpenConfigTabRequest {
  projectId: string;
  containerId: string;
  containerName: string;
}

export type NodeConfigEventMap = {
  'architecture-node-added': ArchitectureNodeAddedEvent;
  'user-input-required': UserInputRequiredEvent;
  'node-config-resumed': NodeConfigResumedEvent;
  'node-config-cancelled': NodeConfigCancelledEvent;
  'secret-rotated': SecretRotatedEvent;
  'open-config-tab-request': OpenConfigTabRequest;
};

class NodeConfigEventBus {
  private readonly target: EventTarget = new EventTarget();

  emit<K extends keyof NodeConfigEventMap>(
    type: K,
    detail: NodeConfigEventMap[K]
  ): void {
    this.target.dispatchEvent(new CustomEvent(type, { detail }));
  }

  on<K extends keyof NodeConfigEventMap>(
    type: K,
    callback: (detail: NodeConfigEventMap[K]) => void
  ): () => void {
    const handler = (event: Event) => {
      callback((event as CustomEvent<NodeConfigEventMap[K]>).detail);
    };
    this.target.addEventListener(type, handler);
    return () => this.target.removeEventListener(type, handler);
  }
}

export const nodeConfigEvents = new NodeConfigEventBus();
