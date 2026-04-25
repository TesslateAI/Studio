import { useEffect, useMemo, useRef } from 'react';
import { appRuntimeApi, appBillingApi } from '../../lib/api';

/**
 * IframeAppHost (WP-FE-F)
 *
 * Hosts a Tesslate App inside a sandboxed iframe and implements the
 * shell<->app postMessage protocol v1.
 *
 * Envelope: {v:1, kind:'request'|'response'|'event', id, topic, payload}
 *
 * Allowed request topics (this wave):
 *   - runtime.end_session
 *   - runtime.begin_invocation
 *   - runtime.end_invocation
 *   - billing.get_spend_summary
 *
 * Security:
 *   - `event.origin` is locked to the entrypoint's origin.
 *   - `api_key` is transmitted ONCE via the `shell.ready` event only and
 *     never logged or persisted.
 */
export interface IframeAppHostProps {
  entrypoint: string;
  appInstanceId: string;
  sessionId: string | null;
  apiKey: string | null;
  onEvent?: (event: unknown) => void;
}

type Envelope = {
  v: 1;
  kind: 'request' | 'response' | 'event';
  id: string;
  topic: string;
  payload: unknown;
};

type RequestTopic =
  | 'runtime.end_session'
  | 'runtime.begin_invocation'
  | 'runtime.end_invocation'
  | 'billing.get_spend_summary';

const ALLOWED_REQUESTS: ReadonlySet<RequestTopic> = new Set([
  'runtime.end_session',
  'runtime.begin_invocation',
  'runtime.end_invocation',
  'billing.get_spend_summary',
]);

function isEnvelope(data: unknown): data is Envelope {
  if (!data || typeof data !== 'object') return false;
  const d = data as Record<string, unknown>;
  return (
    d.v === 1 &&
    (d.kind === 'request' || d.kind === 'response' || d.kind === 'event') &&
    typeof d.id === 'string' &&
    typeof d.topic === 'string'
  );
}

function safeOrigin(entrypoint: string): string | null {
  try {
    return new URL(entrypoint).origin;
  } catch {
    return null;
  }
}

export function IframeAppHost({
  entrypoint,
  appInstanceId,
  sessionId,
  apiKey,
  onEvent,
}: IframeAppHostProps) {
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const allowedOrigin = useMemo(() => safeOrigin(entrypoint), [entrypoint]);

  // Keep latest values in refs for the listener without re-registering each tick.
  const sessionRef = useRef(sessionId);
  const apiKeyRef = useRef(apiKey);
  const onEventRef = useRef(onEvent);
  sessionRef.current = sessionId;
  apiKeyRef.current = apiKey;
  onEventRef.current = onEvent;

  useEffect(() => {
    if (!allowedOrigin) return undefined;

    const postResponse = (id: string, topic: string, payload: unknown) => {
      const frame = iframeRef.current;
      if (!frame || !frame.contentWindow) return;
      const envelope: Envelope = { v: 1, kind: 'response', id, topic, payload };
      frame.contentWindow.postMessage(envelope, allowedOrigin);
    };

    const handleRequest = async (env: Envelope) => {
      const topic = env.topic as RequestTopic;
      if (!ALLOWED_REQUESTS.has(topic)) {
        postResponse(env.id, env.topic, { error: 'topic_not_allowed' });
        return;
      }
      try {
        const currentSession = sessionRef.current;
        switch (topic) {
          case 'runtime.end_session': {
            if (!currentSession) {
              postResponse(env.id, env.topic, { error: 'no_active_session' });
              return;
            }
            await appRuntimeApi.deleteSession(currentSession);
            postResponse(env.id, env.topic, { ok: true });
            return;
          }
          case 'runtime.begin_invocation': {
            const result = await appRuntimeApi.createInvocation({
              app_instance_id: appInstanceId,
            });
            // Strip api_key from the response forwarded to the iframe.
            // The iframe uses the invocation via its existing session key.
            const { api_key: _apiKey, ...safe } = result;
            void _apiKey;
            postResponse(env.id, env.topic, safe);
            return;
          }
          case 'runtime.end_invocation': {
            const payload = env.payload as { session_id?: string } | null;
            const id = payload?.session_id ?? currentSession;
            if (!id) {
              postResponse(env.id, env.topic, { error: 'no_invocation_id' });
              return;
            }
            await appRuntimeApi.deleteInvocation(id);
            postResponse(env.id, env.topic, { ok: true });
            return;
          }
          case 'billing.get_spend_summary': {
            const summary = await appBillingApi.getSpendSummary();
            postResponse(env.id, env.topic, summary);
            return;
          }
        }
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'request_failed';
        postResponse(env.id, env.topic, { error: msg });
      }
    };

    const listener = (event: MessageEvent) => {
      if (event.origin !== allowedOrigin) return;
      if (!isEnvelope(event.data)) return;
      const env = event.data;
      if (env.kind === 'request') {
        void handleRequest(env);
      } else if (env.kind === 'event') {
        onEventRef.current?.(env);
      }
    };

    window.addEventListener('message', listener);
    return () => {
      window.removeEventListener('message', listener);
    };
  }, [allowedOrigin, appInstanceId]);

  // Send initial boot event once iframe loads OR when session becomes available.
  useEffect(() => {
    if (!allowedOrigin) return;
    const frame = iframeRef.current;
    if (!frame) return;
    const send = () => {
      if (!frame.contentWindow) return;
      const boot: Envelope = {
        v: 1,
        kind: 'event',
        id: `boot-${Date.now()}`,
        topic: 'shell.ready',
        payload: {
          session_id: sessionRef.current,
          api_key: apiKeyRef.current,
          app_instance_id: appInstanceId,
        },
      };
      frame.contentWindow.postMessage(boot, allowedOrigin);
    };
    // Fire once on mount; the iframe's own 'load' re-triggers it.
    const onLoad = () => send();
    frame.addEventListener('load', onLoad);
    // Also re-send when session/apiKey become set after load.
    send();
    return () => {
      frame.removeEventListener('load', onLoad);
    };
  }, [allowedOrigin, appInstanceId, sessionId, apiKey]);

  if (!allowedOrigin) {
    return (
      <div className="p-4 text-sm text-red-400" data-testid="iframe-host-error">
        Invalid app entrypoint URL.
      </div>
    );
  }

  return (
    <iframe
      ref={iframeRef}
      src={entrypoint}
      sandbox="allow-scripts allow-same-origin allow-forms"
      title="Tesslate App"
      className="w-full h-full border-0 rounded-xl bg-white"
      style={{ colorScheme: 'normal' }}
      data-testid="iframe-app-host"
    />
  );
}

export default IframeAppHost;
