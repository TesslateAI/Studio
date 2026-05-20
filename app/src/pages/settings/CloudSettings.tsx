/**
 * Tesslate Cloud settings (desktop shell only).
 *
 * Tesslate Studio desktop runs fully offline with a local account — no login
 * required. Signing in to a Tesslate Cloud account is optional and unlocks:
 *   - LLM calls billed to the account's credits (proxied through the cloud
 *     backend; the internal LiteLLM is never exposed to the desktop)
 *   - the cloud marketplace catalog
 *   - project sync
 *
 * This page also lets self-hosters point the desktop at a non-default cloud
 * endpoint before pairing.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import toast from 'react-hot-toast';
import { CheckCircle, CloudSlash, Globe, SignOut, CircleNotch } from '@phosphor-icons/react';
import { desktopApi, type DesktopAuthStatus } from '../../lib/api';
import { SettingsSection } from '../../components/settings';
import { LoadingSpinner } from '../../components/PulsingGridSpinner';
import { ConfirmDialog } from '../../components/modals/ConfirmDialog';

// Tauri invoke shim — avoids a hard @tauri-apps/api dependency, matching the
// pattern in components/desktop/TitleBar.tsx.
function tauriInvoke(): ((cmd: string, args?: Record<string, unknown>) => Promise<unknown>) | undefined {
  return (
    window as unknown as Record<string, unknown> & {
      __TAURI_INTERNALS__?: {
        invoke: (cmd: string, args?: Record<string, unknown>) => Promise<unknown>;
      };
    }
  ).__TAURI_INTERNALS__?.invoke;
}

function extractDetail(err: unknown, fallback: string): string {
  const e = err as { response?: { data?: { detail?: unknown } }; message?: string };
  const detail = e?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  return e?.message ?? fallback;
}

export default function CloudSettings() {
  const [status, setStatus] = useState<DesktopAuthStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [urlInput, setUrlInput] = useState('');
  const [savingUrl, setSavingUrl] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [confirmSignOut, setConfirmSignOut] = useState(false);
  // True once the user clicked "Sign in" — drives a short status poll so the
  // UI flips to "connected" when the deep-link callback lands the token.
  const pollingRef = useRef(false);

  const refresh = useCallback(async (syncInput: boolean) => {
    try {
      const data = await desktopApi.getAuthStatus();
      setStatus(data);
      if (syncInput) setUrlInput(data.cloud_url);
      return data;
    } catch (err) {
      toast.error(extractDetail(err, 'Failed to read cloud status'));
      return null;
    }
  }, []);

  useEffect(() => {
    void (async () => {
      await refresh(true);
      setLoading(false);
    })();
  }, [refresh]);

  // While the browser pairing flow is open, poll so the page reflects the
  // token the deep-link handler persists out-of-band.
  useEffect(() => {
    const id = window.setInterval(() => {
      if (pollingRef.current) void refresh(false);
    }, 3000);
    return () => window.clearInterval(id);
  }, [refresh]);

  const handleSignIn = useCallback(async () => {
    if (!status) return;
    const invoke = tauriInvoke();
    if (!invoke) {
      toast.error('Sign-in is only available in the desktop app');
      return;
    }
    try {
      await invoke('open_external_url', { url: `${status.cloud_url}/desktop/pair` });
      pollingRef.current = true;
      toast('Complete sign-in in your browser, then return here', { icon: '🌐' });
    } catch (err) {
      toast.error(extractDetail(err, 'Could not open the browser'));
    }
  }, [status]);

  const handleSignOut = useCallback(async () => {
    setConfirmSignOut(false);
    setSigningOut(true);
    try {
      await desktopApi.signOut();
      pollingRef.current = false;
      await refresh(false);
      toast.success('Signed out of Tesslate Cloud');
    } catch (err) {
      toast.error(extractDetail(err, 'Sign-out failed'));
    } finally {
      setSigningOut(false);
    }
  }, [refresh]);

  const handleSaveUrl = useCallback(async () => {
    const trimmed = urlInput.trim();
    if (!trimmed) return;
    setSavingUrl(true);
    try {
      const { cloud_url } = await desktopApi.setCloudUrl(trimmed);
      setUrlInput(cloud_url);
      await refresh(false);
      toast.success('Cloud endpoint updated');
    } catch (err) {
      toast.error(extractDetail(err, 'Invalid cloud URL'));
    } finally {
      setSavingUrl(false);
    }
  }, [urlInput, refresh]);

  const handleResetUrl = useCallback(async () => {
    setSavingUrl(true);
    try {
      const { cloud_url } = await desktopApi.clearCloudUrl();
      setUrlInput(cloud_url);
      await refresh(false);
      toast.success('Reverted to the default cloud endpoint');
    } catch (err) {
      toast.error(extractDetail(err, 'Failed to reset cloud URL'));
    } finally {
      setSavingUrl(false);
    }
  }, [refresh]);

  if (loading || !status) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--bg)]">
        <LoadingSpinner message="Loading cloud status..." size={60} />
      </div>
    );
  }

  const paired = status.paired;
  const isCustomEndpoint = status.cloud_url !== status.default_cloud_url;
  const urlDirty = urlInput.trim() !== status.cloud_url;

  return (
    <>
      <SettingsSection
        title="Tesslate Cloud"
        description="Tesslate Studio works fully offline with a local account. Sign in to a Tesslate Cloud account only when you want to use your account credits for AI, the cloud marketplace, or project sync."
      >
        {/* Pairing status */}
        <div className="p-4 bg-[var(--surface)] border border-[var(--border)] rounded-xl">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-start gap-3 min-w-0">
              <div
                className={`w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0 ${
                  paired ? 'bg-emerald-500/10' : 'bg-white/5'
                }`}
              >
                {paired ? (
                  <CheckCircle size={20} weight="fill" className="text-emerald-400" />
                ) : (
                  <CloudSlash size={20} className="text-[var(--text-subtle)]" />
                )}
              </div>
              <div className="min-w-0">
                <h3 className="text-sm font-semibold text-[var(--text)]">
                  {paired ? 'Connected to Tesslate Cloud' : 'Not connected'}
                </h3>
                <p className="text-xs text-[var(--text-subtle)] mt-0.5">
                  {paired
                    ? 'AI requests for built-in models are billed to your account credits.'
                    : 'Sign in to use your account credits, or keep working offline with your own API keys.'}
                </p>
              </div>
            </div>
            {paired ? (
              <button
                onClick={() => setConfirmSignOut(true)}
                disabled={signingOut}
                className="btn btn-sm flex items-center gap-1.5 flex-shrink-0 text-red-400 hover:bg-red-500/10"
              >
                {signingOut ? (
                  <CircleNotch size={13} className="animate-spin" />
                ) : (
                  <SignOut size={13} />
                )}
                Sign out
              </button>
            ) : (
              <button
                onClick={handleSignIn}
                className="btn btn-filled btn-sm flex items-center gap-1.5 flex-shrink-0"
              >
                Sign in
              </button>
            )}
          </div>
        </div>

        {!paired && (
          <div className="p-3 bg-blue-500/10 border border-blue-500/20 rounded-xl">
            <p className="text-xs text-blue-400">
              No account? Tesslate Studio still works — add a provider key under{' '}
              <span className="font-semibold">Library → API Keys</span> or set{' '}
              <code className="font-mono">OPENAI_API_KEY</code> in your environment to bring your
              own LLM.
            </p>
          </div>
        )}

        {/* Cloud endpoint */}
        <div>
          <h3 className="text-sm font-semibold text-[var(--text)] flex items-center gap-2 mb-1">
            <Globe size={16} />
            Cloud endpoint
          </h3>
          <p className="text-[11px] text-[var(--text-subtle)] mb-3">
            The Tesslate Cloud server the desktop pairs with. Leave the default unless you run a
            self-hosted cloud.
          </p>
          <div className="flex items-center gap-2">
            <input
              type="url"
              value={urlInput}
              onChange={(e) => setUrlInput(e.target.value)}
              disabled={paired || savingUrl}
              placeholder={status.default_cloud_url}
              className="flex-1 px-3 py-2 bg-[var(--bg)] border border-[var(--border)] rounded-lg text-sm text-[var(--text)] placeholder:text-[var(--text-subtle)] focus:outline-none focus:border-[var(--primary)] disabled:opacity-60"
              maxLength={512}
            />
            <button
              onClick={handleSaveUrl}
              disabled={paired || savingUrl || !urlDirty}
              className="btn btn-filled btn-sm flex-shrink-0"
            >
              {savingUrl ? 'Saving...' : 'Save'}
            </button>
            {isCustomEndpoint && (
              <button
                onClick={handleResetUrl}
                disabled={paired || savingUrl}
                className="btn btn-sm flex-shrink-0"
              >
                Reset
              </button>
            )}
          </div>
          {paired && (
            <p className="text-[11px] text-[var(--text-subtle)] mt-2">
              Sign out before changing the cloud endpoint.
            </p>
          )}
        </div>
      </SettingsSection>

      <ConfirmDialog
        isOpen={confirmSignOut}
        onClose={() => setConfirmSignOut(false)}
        onConfirm={handleSignOut}
        title="Sign out of Tesslate Cloud"
        message="The desktop will stop using your account credits and cloud marketplace. Your local projects and settings are unaffected. You can sign in again at any time."
        confirmText="Sign out"
        variant="warning"
      />
    </>
  );
}
