// Event system for connection changes
// Allows components to react when edges/connections are added or removed

type ConnectionEventType = 'connection-created' | 'connection-deleted';

interface ConnectionEventDetail {
  type: ConnectionEventType;
  sourceContainerId?: string;
  targetContainerId?: string;
  timestamp: number;
}

class ConnectionEventBus {
  private eventTarget: EventTarget;

  constructor() {
    this.eventTarget = new EventTarget();
  }

  emit(type: ConnectionEventType, sourceContainerId?: string, targetContainerId?: string) {
    const event = new CustomEvent<ConnectionEventDetail>('connection-change', {
      detail: {
        type,
        sourceContainerId,
        targetContainerId,
        timestamp: Date.now(),
      },
    });
    this.eventTarget.dispatchEvent(event);
  }

  on(callback: (detail: ConnectionEventDetail) => void) {
    const handler = (event: Event) => {
      const customEvent = event as CustomEvent<ConnectionEventDetail>;
      callback(customEvent.detail);
    };
    this.eventTarget.addEventListener('connection-change', handler);
    return () => this.eventTarget.removeEventListener('connection-change', handler);
  }
}

export const connectionEvents = new ConnectionEventBus();
