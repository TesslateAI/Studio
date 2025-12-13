import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { LoadingSpinner } from '../components/PulsingGridSpinner';
import { XCircle } from '@phosphor-icons/react';
import toast from 'react-hot-toast';

/**
 * OAuth Login Callback Handler Page
 * This page handles the OAuth callback for user authentication (GitHub/Google login)
 * Different from AuthCallback.tsx which handles GitHub repo integration
 */
export default function OAuthLoginCallback() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [status, setStatus] = useState<'processing' | 'success' | 'error'>('processing');
  const [message, setMessage] = useState('Completing sign in...');
  const [errorDetail, setErrorDetail] = useState<string | null>(null);

  useEffect(() => {
    handleOAuthCallback();
  }, []);

  const handleOAuthCallback = async () => {
    // Check for errors in URL
    const error = searchParams.get('error');
    const errorDescription = searchParams.get('error_description');

    if (error) {
      setStatus('error');
      setMessage('Authentication failed');
      setErrorDetail(errorDescription || error);
      toast.error(`Authentication failed: ${errorDescription || error}`);

      setTimeout(() => {
        navigate('/login');
      }, 3000);
      return;
    }

    // Check for token in URL (some OAuth providers pass it directly)
    const accessToken = searchParams.get('access_token') || searchParams.get('token');

    if (accessToken) {
      // Store token and redirect to dashboard immediately
      localStorage.setItem('token', accessToken);
      navigate('/dashboard', { state: { fromLogin: true } });
      return;
    }

    // If no token and no error, the backend should have set a cookie
    // Try to verify we're authenticated by checking if we can access a protected endpoint
    try {
      // Import api from lib to use configured axios instance with credentials
      const { authApi } = await import('../lib/api');
      const user = await authApi.getCurrentUser();

      // Successfully authenticated via cookie - redirect immediately
      navigate('/dashboard', { state: { fromLogin: true } });
    } catch (err: any) {
      setStatus('error');
      setMessage('Failed to complete sign in');
      setErrorDetail(err.message || 'Unable to verify authentication');
      toast.error('Failed to complete sign in');

      setTimeout(() => {
        navigate('/login');
      }, 3000);
    }
  };

  const getStatusIcon = () => {
    if (status === 'error') {
      return <XCircle className="w-16 h-16 text-red-500" weight="fill" />;
    }
    return <LoadingSpinner size={80} />;
  };

  const getStatusColor = () => {
    return status === 'error' ? 'text-red-500' : 'text-white';
  };

  return (
    <div className="min-h-screen bg-[#1a1a1a] flex items-center justify-center p-4">
      <div className="max-w-md w-full">
        <div className="bg-[#0a0a0a] rounded-3xl p-8 shadow-2xl border border-gray-800">
          {/* Status Icon */}
          <div className="flex justify-center mb-6">
            {getStatusIcon()}
          </div>

          {/* Status Message */}
          <h2 className={`text-2xl font-bold text-center mb-2 ${getStatusColor()}`}>
            {status === 'error' ? 'Sign In Failed' : 'Signing You In'}
          </h2>

          {/* Detail Message */}
          <p className="text-center text-gray-400 mb-4">
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
            <p className="text-xs text-center text-gray-500 mt-4">
              Please wait while we complete the sign in process...
            </p>
          )}

          {status === 'error' && (
            <div className="mt-6 text-center">
              <button
                onClick={() => navigate('/login')}
                className="px-6 py-2 bg-[#FF6B00] text-white rounded-xl hover:bg-[#ff7a1a] transition-colors"
              >
                Back to Login
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
