/**
 * First-run setup choice (desktop shell only).
 *
 * Tesslate Studio desktop auto-provisions a local account, so the app is
 * usable immediately — but the user still has to tell it how to reach an LLM.
 * This dialog surfaces that choice exactly once: sign in to Tesslate Cloud,
 * bring your own provider keys, or skip. The "completed" flag is persisted by
 * the sidecar (`/api/desktop/first-run`) so it never reappears.
 *
 * Renders nothing outside the Tauri shell or once the choice has been made.
 */

import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { CloudCheck, Key, ArrowRight } from '@phosphor-icons/react';
import { desktopApi } from '../../lib/api';
import { useAuth } from '../../contexts/AuthContext';

const IS_TAURI = '__TAURI_INTERNALS__' in window || '__TAURI__' in window;

export function FirstRunDialog() {
  const { isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!IS_TAURI || !isAuthenticated) return;
    let cancelled = false;
    void (async () => {
      try {
        const { completed } = await desktopApi.getFirstRun();
        if (!cancelled && !completed) setShow(true);
      } catch {
        // Sidecar unreachable or non-desktop — skip onboarding silently.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isAuthenticated]);

  const dismiss = useCallback(
    async (destination?: string) => {
      setBusy(true);
      try {
        await desktopApi.completeFirstRun();
      } catch {
        // Best-effort — closing the dialog locally is enough for this session.
      } finally {
        setShow(false);
        setBusy(false);
        if (destination) navigate(destination);
      }
    },
    [navigate]
  );

  if (!show) return null;

  return (
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center bg-black/50 p-6"
      role="dialog"
      aria-modal="true"
      aria-label="Welcome to Tesslate Studio"
    >
      <div className="w-full max-w-md p-6 bg-[var(--surface)] border border-[var(--border)] rounded-2xl">
        <h1 className="text-base font-semibold text-[var(--text)] mb-1">
          Welcome to Tesslate Studio
        </h1>
        <p className="text-sm text-[var(--text-subtle)] mb-5">
          You’re ready to build — pick how the AI should connect. You can change this any time in
          Settings.
        </p>

        <div className="space-y-2.5">
          <button
            onClick={() => dismiss('/settings/cloud')}
            disabled={busy}
            className="w-full text-left p-3.5 bg-[var(--bg)] border border-[var(--border)] rounded-xl hover:border-[var(--primary)] transition-colors flex items-center gap-3 disabled:opacity-60"
          >
            <div className="w-9 h-9 rounded-lg bg-[var(--primary)]/10 flex items-center justify-center flex-shrink-0">
              <CloudCheck size={18} className="text-[var(--primary)]" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-semibold text-[var(--text)]">
                Sign in to Tesslate Cloud
              </div>
              <div className="text-xs text-[var(--text-subtle)]">
                Use your account credits, marketplace, and sync.
              </div>
            </div>
            <ArrowRight size={15} className="text-[var(--text-subtle)] flex-shrink-0" />
          </button>

          <button
            onClick={() => dismiss('/settings/api-keys')}
            disabled={busy}
            className="w-full text-left p-3.5 bg-[var(--bg)] border border-[var(--border)] rounded-xl hover:border-[var(--primary)] transition-colors flex items-center gap-3 disabled:opacity-60"
          >
            <div className="w-9 h-9 rounded-lg bg-white/5 flex items-center justify-center flex-shrink-0">
              <Key size={18} className="text-[var(--text-muted)]" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-semibold text-[var(--text)]">Use my own API keys</div>
              <div className="text-xs text-[var(--text-subtle)]">
                Bring your own OpenAI, Anthropic, or other provider key.
              </div>
            </div>
            <ArrowRight size={15} className="text-[var(--text-subtle)] flex-shrink-0" />
          </button>
        </div>

        <div className="flex justify-end mt-5">
          <button onClick={() => dismiss()} disabled={busy} className="btn btn-sm">
            Skip for now
          </button>
        </div>
      </div>
    </div>
  );
}
