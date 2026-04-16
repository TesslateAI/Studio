/**
 * Opens an OAuth authorize URL in a popup and resolves when the callback
 * HTML posts a message back to the opener.
 *
 * Falls back to polling `getMcpOAuthStatus(flowId)` via `statusPoller` if
 * the postMessage never arrives (popup-blocker / cross-origin isolation).
 *
 * A 5-minute maximum timeout prevents the promise from hanging indefinitely
 * when postMessage is blocked and the popup never closes.
 */
export type OAuthPopupResult = {
  status: 'success' | 'error';
  configId?: string | null;
  message?: string;
};

export type StatusPoller = (flowId: string) => Promise<{
  status: 'pending' | 'success' | 'error' | 'unknown';
  config_id?: string | null;
  error?: string | null;
}>;

const MAX_OAUTH_TIMEOUT_MS = 5 * 60 * 1000; // 5 minutes

export async function runOAuthPopup(
  authorizeUrl: string,
  flowId: string,
  statusPoller?: StatusPoller
): Promise<OAuthPopupResult> {
  return new Promise((resolve, reject) => {
    const popup = window.open(
      authorizeUrl,
      'mcp-oauth',
      'width=620,height=740,resizable,scrollbars'
    );
    if (!popup) {
      reject(new Error('Popup blocked'));
      return;
    }

    const expectedOrigin = window.location.origin;
    let resolved = false;

    // Declared here so the max timeout can be cleared from cleanup.
    let maxTimeout: ReturnType<typeof setTimeout> | null = null;

    const cleanup = () => {
      window.removeEventListener('message', handler);
      clearInterval(closedPoll);
      if (statusInterval) clearInterval(statusInterval);
      if (maxTimeout) clearTimeout(maxTimeout);
    };

    const handler = (ev: MessageEvent) => {
      if (ev.origin !== expectedOrigin) return;
      const data = ev.data as
        | { type?: string; status?: string; config_id?: string; message?: string }
        | undefined;
      if (!data || data.type !== 'mcp-oauth') return;
      resolved = true;
      cleanup();
      resolve({
        status: data.status === 'success' ? 'success' : 'error',
        configId: data.config_id,
        message: data.message,
      });
    };

    window.addEventListener('message', handler);

    // Fallback: poll status endpoint every 1.5s.
    let statusInterval: ReturnType<typeof setInterval> | null = null;
    if (statusPoller) {
      statusInterval = setInterval(async () => {
        try {
          const s = await statusPoller(flowId);
          if (s.status === 'success' || s.status === 'error') {
            if (resolved) return;
            resolved = true;
            cleanup();
            try {
              popup.close();
            } catch {
              /* ignore */
            }
            resolve({
              status: s.status,
              configId: s.config_id,
              message: s.error ?? undefined,
            });
          }
        } catch {
          /* ignore transient errors */
        }
      }, 1500);
    }

    const closedPoll = setInterval(() => {
      if (popup.closed) {
        if (resolved) return;
        cleanup();
        reject(new Error('Popup closed before completion'));
      }
    }, 500);

    // Maximum timeout — if postMessage is blocked AND the popup never
    // closes (mobile browsers, cross-origin iframe embeds), the promise
    // would hang indefinitely without this.
    maxTimeout = setTimeout(() => {
      if (resolved) return;
      resolved = true;
      cleanup();
      try {
        popup.close();
      } catch {
        /* ignore */
      }
      reject(new Error('OAuth flow timed out'));
    }, MAX_OAUTH_TIMEOUT_MS);
  });
}
