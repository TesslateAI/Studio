import { useState } from 'react';
import { CardSurface } from '../cards/CardSurface';
import IframeAppHost from './IframeAppHost';
import AppPreviewOverlay from './AppPreviewOverlay';
import { useIframeHealth } from '../../hooks/useIframeHealth';

export interface Surface {
  kind: 'ui' | 'chat' | 'scheduled' | 'triggered' | 'mcp-tool';
  entrypoint?: string;
  name?: string;
  description?: string;
}

export interface WorkspaceSurfaceProps {
  surface: Surface | undefined;
  appInstanceId: string;
  sessionId: string | null;
  apiKey: string | null;
  /** App display name, used for friendlier overlay copy. */
  appName?: string;
  /**
   * Project slug + primary container id of the running app. When both are
   * provided AND the surface is `ui`, we run the same backend health check
   * as the project builder preview pane: the iframe stays unmounted (with
   * an overlay shown) until the container responds 2xx/3xx, then mounts
   * with a fresh React `key` so the user sees the app load cleanly instead
   * of a flash of 404/503. When omitted (legacy callers, tests), the
   * iframe mounts immediately as before.
   */
  projectSlug?: string | null;
  primaryContainerId?: string | null;
}

/**
 * Renders the primary surface of a running app. For `ui` this is a sandboxed
 * iframe. For `chat` it's a simple text column. For backgroundish surfaces
 * (scheduled/triggered/mcp-tool) it's a read-only summary card.
 */
export function WorkspaceSurface({
  surface,
  appInstanceId,
  sessionId,
  apiKey,
  appName,
  projectSlug,
  primaryContainerId,
}: WorkspaceSurfaceProps) {
  const [chatInput, setChatInput] = useState('');
  const [chatLog, setChatLog] = useState<{ role: 'user' | 'system'; text: string }[]>([]);

  const healthEnabled = Boolean(
    surface?.kind === 'ui' && surface.entrypoint && projectSlug && primaryContainerId
  );
  const health = useIframeHealth({
    enabled: healthEnabled,
    projectSlug: projectSlug ?? null,
    containerId: primaryContainerId ?? null,
  });

  if (!surface) {
    return (
      <CardSurface variant="standard" disableHoverLift>
        <div className="text-sm text-[var(--muted)]">
          This app version declares no surfaces.
        </div>
      </CardSurface>
    );
  }

  if (surface.kind === 'ui' && surface.entrypoint) {
    // When the health check is enabled but not yet healthy, render the
    // overlay in place of the iframe so the user never sees the raw
    // browser error page for an installing dep server. When the check
    // is disabled (no slug/container), fall back to the legacy direct
    // iframe mount.
    if (healthEnabled && health.phase !== 'healthy') {
      return (
        <div className="h-full min-h-[60vh]">
          <AppPreviewOverlay
            phase={health.phase}
            appName={appName}
            statusCode={health.statusCode}
            error={health.error}
          />
        </div>
      );
    }
    return (
      <div className="h-full min-h-[60vh]">
        <IframeAppHost
          // Bump key on first transition to healthy so the iframe mounts
          // fresh (cache-busted by React) right when the URL is known to
          // serve 2xx — this is the equivalent of the builder pane's
          // refresh-on-ready behavior.
          key={`app-host-${health.reloadToken}`}
          entrypoint={surface.entrypoint}
          appInstanceId={appInstanceId}
          sessionId={sessionId}
          apiKey={apiKey}
        />
      </div>
    );
  }

  if (surface.kind === 'chat') {
    const hasSession = sessionId !== null;
    return (
      <CardSurface variant="standard" disableHoverLift className="h-full">
        <div className="flex-1 overflow-auto space-y-2 mb-3" data-testid="chat-log">
          {chatLog.length === 0 ? (
            <div className="text-xs text-[var(--muted)]">
              Start a session and send a message to use this app.
            </div>
          ) : (
            chatLog.map((m, i) => (
              <div key={i} className="text-sm">
                <span className="text-[var(--muted)] text-xs mr-2">{m.role}</span>
                {m.text}
              </div>
            ))
          )}
        </div>
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (!chatInput.trim()) return;
            setChatLog((log) => [...log, { role: 'user', text: chatInput.trim() }]);
            setChatInput('');
          }}
        >
          <input
            value={chatInput}
            onChange={(e) => setChatInput(e.target.value)}
            disabled={!hasSession}
            placeholder={hasSession ? 'Type a message…' : 'Start a session to chat'}
            className="flex-1 px-3 py-2 rounded-lg bg-[var(--surface-hover)] border border-[var(--border)] text-sm text-[var(--text)] placeholder:text-[var(--muted)] focus:outline-none focus:border-[var(--primary)]"
          />
          <button
            type="submit"
            disabled={!hasSession || !chatInput.trim()}
            className="px-3 py-2 rounded-lg bg-[var(--primary)] text-white text-xs font-semibold disabled:opacity-40 transition"
          >
            Send
          </button>
        </form>
      </CardSurface>
    );
  }

  return (
    <CardSurface variant="standard" disableHoverLift>
      <div className="text-sm text-[var(--muted)] uppercase tracking-wide mb-1">
        {surface.kind} surface
      </div>
      <div className="font-heading text-lg text-[var(--text)] mb-1">
        {surface.name ?? 'Background surface'}
      </div>
      <div className="text-sm text-[var(--muted)]">
        {surface.description ??
          'This surface runs in the background and has no interactive UI.'}
      </div>
    </CardSurface>
  );
}

export default WorkspaceSurface;
