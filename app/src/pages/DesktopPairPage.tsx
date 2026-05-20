/**
 * Cloud-side desktop pairing page (`/desktop/pair`).
 *
 * The Tesslate Studio desktop app opens this page in the system browser when
 * the user chooses "Sign in" in Settings → Cloud. The visitor authenticates
 * with their normal cloud account (PrivateRoute bounces anonymous visitors to
 * /login and back), authorizes the device, and the page hands a freshly
 * minted `tsk_` key back to the desktop via the `tesslate://` deep link.
 *
 * The raw key is returned by the API exactly once and only ever travels
 * through the deep link — it is never displayed.
 */

import { useCallback, useMemo, useState } from 'react';
import toast from 'react-hot-toast';
import { CheckCircle, CircleNotch, DeviceMobile } from '@phosphor-icons/react';
import { desktopPairApi } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';

function detectPlatform(): string {
  const ua = navigator.userAgent;
  if (/Mac OS X/.test(ua)) return 'macos';
  if (/Windows NT/.test(ua)) return 'windows';
  if (/Linux/.test(ua)) return 'linux';
  return 'unknown';
}

function defaultDeviceName(platform: string): string {
  switch (platform) {
    case 'macos':
      return 'My Mac';
    case 'windows':
      return 'My Windows PC';
    case 'linux':
      return 'My Linux PC';
    default:
      return 'My Computer';
  }
}

function extractDetail(err: unknown, fallback: string): string {
  const e = err as { response?: { data?: { detail?: unknown } }; message?: string };
  const detail = e?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  return e?.message ?? fallback;
}

export default function DesktopPairPage() {
  const { user } = useAuth();
  const platform = useMemo(detectPlatform, []);
  const [deviceName, setDeviceName] = useState(() => defaultDeviceName(platform));
  const [pairing, setPairing] = useState(false);
  const [done, setDone] = useState(false);
  // Held only to re-fire the deep link if the OS handoff didn't catch first
  // time. Never rendered.
  const [deepLink, setDeepLink] = useState<string | null>(null);

  const launchDeepLink = useCallback((link: string) => {
    window.location.href = link;
  }, []);

  const handleAuthorize = useCallback(async () => {
    const name = deviceName.trim();
    if (!name) {
      toast.error('Give this device a name');
      return;
    }
    setPairing(true);
    try {
      const result = await desktopPairApi.complete({
        device_name: name,
        device_platform: platform,
      });
      const link = `tesslate://auth/callback?token=${encodeURIComponent(result.token)}`;
      setDeepLink(link);
      setDone(true);
      launchDeepLink(link);
    } catch (err) {
      toast.error(extractDetail(err, 'Failed to authorize this device'));
    } finally {
      setPairing(false);
    }
  }, [deviceName, platform, launchDeepLink]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--bg)] p-6">
      <div className="w-full max-w-md p-6 bg-[var(--surface)] border border-[var(--border)] rounded-2xl">
        {done ? (
          <div className="text-center">
            <div className="w-14 h-14 rounded-2xl bg-emerald-500/10 flex items-center justify-center mx-auto mb-4">
              <CheckCircle size={30} weight="fill" className="text-emerald-400" />
            </div>
            <h1 className="text-base font-semibold text-[var(--text)] mb-2">Device authorized</h1>
            <p className="text-sm text-[var(--text-subtle)] mb-5">
              Return to Tesslate Studio — it should now be signed in. If it didn’t reopen
              automatically, use the button below.
            </p>
            <button
              onClick={() => deepLink && launchDeepLink(deepLink)}
              className="btn btn-filled w-full"
            >
              Reopen Tesslate Studio
            </button>
          </div>
        ) : (
          <>
            <div className="flex items-center gap-3 mb-5">
              <div className="w-11 h-11 rounded-xl bg-[var(--primary)]/10 flex items-center justify-center flex-shrink-0">
                <DeviceMobile size={22} className="text-[var(--primary)]" />
              </div>
              <div>
                <h1 className="text-base font-semibold text-[var(--text)]">
                  Pair Tesslate Studio Desktop
                </h1>
                <p className="text-xs text-[var(--text-subtle)]">
                  Authorizing as {user?.email ?? 'your account'}
                </p>
              </div>
            </div>

            <p className="text-sm text-[var(--text-subtle)] mb-4">
              This links the desktop app to your account so it can use your credits for AI, the
              cloud marketplace, and project sync. You can revoke it any time from Settings.
            </p>

            <label className="text-xs font-medium text-[var(--text)] block mb-1.5">
              Device name
            </label>
            <input
              type="text"
              value={deviceName}
              onChange={(e) => setDeviceName(e.target.value)}
              maxLength={200}
              className="w-full px-3 py-2 mb-5 bg-[var(--bg)] border border-[var(--border)] rounded-lg text-sm text-[var(--text)] placeholder:text-[var(--text-subtle)] focus:outline-none focus:border-[var(--primary)]"
            />

            <button
              onClick={handleAuthorize}
              disabled={pairing}
              className="btn btn-filled w-full flex items-center justify-center gap-2"
            >
              {pairing && <CircleNotch size={15} className="animate-spin" />}
              {pairing ? 'Authorizing...' : 'Authorize this device'}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
