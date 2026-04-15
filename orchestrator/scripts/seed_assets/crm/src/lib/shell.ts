'use client';

// postMessage v1 shell client. Listens for `shell.ready` from window.parent
// (the Tesslate shell iframe host), then exposes begin/end invocation hooks.

export interface ShellHandshake {
  sessionId: string;
  apiKey: string | null;
  appInstanceId: string | null;
}

type ShellMsg =
  | { type: 'shell.ready'; session_id: string; api_key?: string | null; app_instance_id?: string | null }
  | { type: 'runtime.invocation.begun'; invocation_id: string }
  | { type: 'runtime.invocation.ended'; invocation_id: string };

let _parentOrigin: string | null = null;
let _handshake: ShellHandshake | null = null;
let _readyResolvers: Array<(h: ShellHandshake) => void> = [];

function resolveParentOrigin(): string | null {
  if (_parentOrigin) return _parentOrigin;
  try {
    if (document.referrer) {
      const u = new URL(document.referrer);
      _parentOrigin = u.origin;
      return _parentOrigin;
    }
  } catch {
    // ignore
  }
  return null;
}

function installListener() {
  if (typeof window === 'undefined') return;
  if ((window as any).__tesslate_shell_listener_installed) return;
  (window as any).__tesslate_shell_listener_installed = true;

  window.addEventListener('message', (ev) => {
    const expected = resolveParentOrigin();
    if (expected && ev.origin !== expected) return;
    const data = ev.data as ShellMsg | undefined;
    if (!data || typeof data !== 'object' || !('type' in data)) return;
    if (data.type === 'shell.ready') {
      _handshake = {
        sessionId: data.session_id,
        apiKey: data.api_key ?? null,
        appInstanceId: data.app_instance_id ?? null,
      };
      const pending = _readyResolvers;
      _readyResolvers = [];
      pending.forEach((fn) => fn(_handshake!));
    }
  });
}

export function readyPromise(): Promise<ShellHandshake> {
  installListener();
  if (_handshake) return Promise.resolve(_handshake);
  return new Promise((resolve) => _readyResolvers.push(resolve));
}

function postToParent(msg: Record<string, unknown>) {
  if (typeof window === 'undefined' || !window.parent) return;
  const origin = resolveParentOrigin();
  try {
    window.parent.postMessage(msg, origin ?? '*');
  } catch (e) {
    console.warn('[shell] postMessage failed', e);
  }
}

export function beginInvocation(): void {
  postToParent({ type: 'runtime.begin_invocation', ts: Date.now() });
}

export function endInvocation(): void {
  postToParent({ type: 'runtime.end_invocation', ts: Date.now() });
}

export function useShell() {
  // Not a React hook in the strict sense — a plain accessor callers can await.
  installListener();
  return {
    ready: readyPromise(),
    beginInvocation,
    endInvocation,
  };
}
