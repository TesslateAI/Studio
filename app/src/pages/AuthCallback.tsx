import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { githubApi } from '../lib/github-api';
import { LoadingSpinner } from '../components/PulsingGridSpinner';
import { CheckCircle, XCircle } from '@phosphor-icons/react';
import toast from 'react-hot-toast';

/**
 * OAuth Callback Handler Page
 * This page handles the OAuth callback from GitHub after user authorization
 */
export default function AuthCallback() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [status, setStatus] = useState<'processing' | 'success' | 'error'>('processing');
  const [message, setMessage] = useState('Processing GitHub authorization...');
  const [errorDetail, setErrorDetail] = useState<string | null>(null);

  useEffect(() => {
    handleOAuthCallback();
  }, []);

  const handleOAuthCallback = async () => {
    // Get code and state from URL parameters
    const code = searchParams.get('code');
    const state = searchParams.get('state');
    const error = searchParams.get('error');
    const errorDescription = searchParams.get('error_description');

    // Check for GitHub errors
    if (error) {
      setStatus('error');
      setMessage('GitHub authorization failed');
      setErrorDetail(errorDescription || error);
      toast.error(`GitHub authorization failed: ${errorDescription || error}`);

      // Redirect after delay
      setTimeout(() => {
        navigate('/dashboard');
      }, 3000);
      return;
    }

    // Validate required parameters
    if (!code || !state) {
      setStatus('error');
      setMessage('Invalid authorization response');
      setErrorDetail('Missing authorization code or state parameter');
      toast.error('Invalid authorization response from GitHub');

      setTimeout(() => {
        navigate('/dashboard');
      }, 3000);
      return;
    }

    try {
      // Exchange code for token via backend
      const result = await githubApi.handleOAuthCallback(code, state);

      if (result.success) {
        setStatus('success');
        setMessage(`Successfully connected as @${result.github_username}`);
        toast.success(`Connected GitHub account: @${result.github_username}`);

        // Get the return URL from session storage (if set)
        const returnTo = sessionStorage.getItem('github_oauth_return');
        sessionStorage.removeItem('github_oauth_return');

        // Redirect to the appropriate page
        setTimeout(() => {
          navigate(returnTo || '/dashboard');
        }, 2000);
      } else {
        throw new Error(result.message || 'Failed to complete OAuth flow');
      }
    } catch (error: any) {
      setStatus('error');
      setMessage('Failed to connect GitHub account');
      setErrorDetail(error.message || 'Unknown error occurred');
      toast.error(`Failed to connect GitHub: ${error.message}`);

      setTimeout(() => {
        navigate('/dashboard');
      }, 3000);
    }
  };

  const getStatusIcon = () => {
    switch (status) {
      case 'success':
        return <CheckCircle className="w-16 h-16 text-green-500" weight="fill" />;
      case 'error':
        return <XCircle className="w-16 h-16 text-red-500" weight="fill" />;
      default:
        return <LoadingSpinner size={80} />;
    }
  };

  const getStatusColor = () => {
    switch (status) {
      case 'success':
        return 'text-green-500';
      case 'error':
        return 'text-red-500';
      default:
        return 'text-[var(--text)]';
    }
  };

  return (
    <div className="min-h-screen bg-[var(--background)] flex items-center justify-center p-4">
      <div className="max-w-md w-full">
        <div className="bg-[var(--surface)] rounded-3xl p-8 shadow-2xl border border-white/10">
          {/* Status Icon */}
          <div className="flex justify-center mb-6">
            {getStatusIcon()}
          </div>

          {/* Status Message */}
          <h2 className={`text-2xl font-heading font-bold text-center mb-2 ${getStatusColor()}`}>
            {status === 'processing' ? 'Connecting to GitHub' :
             status === 'success' ? 'Connected Successfully!' :
             'Connection Failed'}
          </h2>

          {/* Detail Message */}
          <p className="text-center text-[var(--text)]/60 mb-4">
            {message}
          </p>

          {/* Error Detail (if any) */}
          {errorDetail && (
            <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 mt-4">
              <p className="text-sm text-red-400">{errorDetail}</p>
            </div>
          )}

          {/* Loading/Status Text */}
          {status === 'processing' && (
            <p className="text-xs text-center text-[var(--text)]/40 mt-4">
              Please wait while we complete the authorization...
            </p>
          )}

          {status === 'success' && (
            <p className="text-xs text-center text-green-400 mt-4">
              Redirecting you back to your project...
            </p>
          )}

          {status === 'error' && (
            <div className="mt-6 text-center">
              <button
                onClick={() => navigate('/dashboard')}
                className="px-6 py-2 bg-[var(--primary)] text-white rounded-xl hover:opacity-90 transition-opacity"
              >
                Return to Dashboard
              </button>
            </div>
          )}
        </div>

        {/* GitHub OAuth Info */}
        <div className="text-center mt-6">
          <p className="text-xs text-[var(--text)]/40">
            GitHub OAuth integration by Tesslate Studio
          </p>
        </div>
      </div>
    </div>
  );
}