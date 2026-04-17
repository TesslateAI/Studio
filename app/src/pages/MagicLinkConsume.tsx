import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { authApi } from '../lib/api';
import { useAuth } from '../contexts/AuthContext';
import { useTheme } from '../theme/ThemeContext';
import { PulsingGridSpinner } from '../components/PulsingGridSpinner';
import { TesslateLogo } from '../components/ui/TesslateLogo';
import toast from 'react-hot-toast';

/**
 * Handles /auth/magic?token=... — the URL embedded in magic-link emails.
 *
 * IMPORTANT: this page does NOT auto-consume the token on mount. Email
 * security scanners (Gmail Safelinks, Outlook ATP, Slack unfurl, etc.)
 * pre-fetch URLs with GET/HEAD to check for phishing. If we consumed on
 * mount, scanners would consume the single-use token before the real user
 * ever clicked, and the user would be greeted with "invalid or expired".
 *
 * Instead we render a "Continue signing in" button that POSTs the token on
 * click. Scanners don't execute JS or synthesize clicks, so the token stays
 * fresh until the user deliberately proceeds. The backend route is also POST
 * so even a curious scanner that did run JS would be blocked at the network
 * layer.
 */
const REDIRECT_KEY = 'magic_link_redirect';

export default function MagicLinkConsume() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { checkAuth } = useAuth();
  const { refreshUserTheme } = useTheme();
  const token = params.get('token');
  const [status, setStatus] = useState<'idle' | 'loading' | 'error'>(token ? 'idle' : 'error');

  // Guard against double-consume (React strict-mode double-invoke, or user
  // double-clicking the button). Single-use tokens 401 on the second call.
  const consumedRef = useRef(false);

  const handleContinue = async () => {
    if (!token || consumedRef.current) return;
    consumedRef.current = true;
    setStatus('loading');
    try {
      const response = await authApi.magicLinkConsume(token);
      localStorage.setItem('token', response.access_token);
      await checkAuth({ force: true });
      refreshUserTheme();
      toast.success('Signed in');
      // Honor the pre-login redirect if the user was bounced from a
      // protected route. Stashed by Login.tsx before sending the link.
      const redirect = sessionStorage.getItem(REDIRECT_KEY);
      sessionStorage.removeItem(REDIRECT_KEY);
      navigate(redirect && redirect.startsWith('/') ? redirect : '/home', {
        replace: true,
      });
    } catch {
      // Backend 401 = token invalid, expired, or already used.
      // Allow the user to retry-by-going-back rather than hard-failing.
      consumedRef.current = false;
      setStatus('error');
    }
  };

  // If there is no token in the URL at all, we've already set status=error
  // in useState init. No other effects fire on mount — the entire consume
  // flow is button-driven.
  useEffect(() => {
    if (!token) setStatus('error');
  }, [token]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-white p-6">
      <div className="w-full max-w-md text-center">
        <div className="mb-8 flex justify-center">
          <TesslateLogo width={48} height={38} className="text-black" />
        </div>

        {status === 'idle' && (
          <div className="space-y-6">
            <div className="space-y-2">
              <h1 className="text-2xl font-bold text-gray-900">Sign in to Tesslate</h1>
              <p className="text-gray-600 text-sm">
                You requested a sign-in link. Click the button below to continue.
              </p>
            </div>
            <button
              onClick={handleContinue}
              className="w-full bg-black text-white py-3.5 px-4 rounded-xl hover:bg-gray-800 font-semibold transition-all duration-200 text-sm"
            >
              Continue signing in
            </button>
            <p className="text-gray-400 text-xs">
              Didn&#39;t request this? You can safely close this tab.
            </p>
          </div>
        )}

        {status === 'loading' && (
          <div className="flex flex-col items-center gap-4">
            <PulsingGridSpinner size={32} />
            <p className="text-gray-600 text-sm">Signing you in...</p>
          </div>
        )}

        {status === 'error' && (
          <div className="space-y-4">
            <h1 className="text-2xl font-bold text-gray-900">
              This sign-in link is invalid or has expired
            </h1>
            <p className="text-gray-600 text-sm">
              Links expire after 10 minutes and can only be used once. Please request a new one.
            </p>
            <Link
              to="/login"
              className="inline-block bg-black text-white py-3 px-6 rounded-xl hover:bg-gray-800 font-semibold transition-all duration-200 text-sm"
            >
              Back to sign in
            </Link>
          </div>
        )}
      </div>
    </div>
  );
}
