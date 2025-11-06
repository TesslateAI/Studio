import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { CheckCircle, XCircle, CircleNotch } from '@phosphor-icons/react';
import { marketplaceApi } from '../lib/api';

export default function MarketplaceSuccess() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [status, setStatus] = useState<'loading' | 'success' | 'error'>('loading');
  const [message, setMessage] = useState('');

  useEffect(() => {
    const verifyPurchase = async () => {
      const sessionId = searchParams.get('session_id');
      const agentSlug = searchParams.get('agent');

      if (!sessionId) {
        setStatus('error');
        setMessage('No session ID found. Please contact support if you were charged.');
        return;
      }

      try {
        // Verify the Stripe checkout session and add to library
        const response = await marketplaceApi.verifyPurchase(sessionId, agentSlug);

        if (response.success) {
          setStatus('success');
          setMessage('Agent added to your library!');
          // Redirect to library after 2 seconds
          setTimeout(() => {
            navigate('/library');
          }, 2000);
        } else {
          setStatus('error');
          setMessage('Failed to verify purchase. Please contact support.');
        }
      } catch (error: any) {
        console.error('Failed to verify purchase:', error);
        setStatus('error');
        setMessage(
          error.response?.data?.detail ||
          'Failed to verify purchase. Please contact support if you were charged.'
        );
      }
    };

    verifyPurchase();
  }, [searchParams, navigate]);

  return (
    <div className="min-h-screen flex items-center justify-center p-4" style={{ backgroundColor: 'var(--bg-dark)' }}>
      <div
        className="rounded-2xl shadow-2xl p-8 max-w-md w-full text-center"
        style={{
          backgroundColor: 'var(--surface)',
          border: '1px solid rgba(255, 107, 0, 0.2)'
        }}
      >
        {/* Icon */}
        <div className="mb-6 flex justify-center">
          {status === 'loading' && (
            <CircleNotch size={64} className="text-orange-500 animate-spin" weight="bold" />
          )}
          {status === 'success' && (
            <CheckCircle size={64} className="text-green-500" weight="fill" />
          )}
          {status === 'error' && (
            <XCircle size={64} className="text-red-500" weight="fill" />
          )}
        </div>

        {/* Title */}
        <h2 className="text-2xl font-bold mb-3" style={{ color: 'var(--text)' }}>
          {status === 'loading' && 'Verifying Your Purchase...'}
          {status === 'success' && 'Payment Successful!'}
          {status === 'error' && 'Payment Issue'}
        </h2>

        {/* Message */}
        <p className="mb-6" style={{ color: 'var(--text)' }}>
          {status === 'loading' && 'Please wait while we confirm your payment and add the agent to your library.'}
          {status === 'success' && message}
          {status === 'error' && message}
        </p>

        {/* Actions */}
        {status === 'success' && (
          <p className="text-sm" style={{ color: 'var(--text)', opacity: 0.6 }}>
            Redirecting to library...
          </p>
        )}

        {status === 'error' && (
          <div className="space-y-3">
            <button
              onClick={() => navigate('/library')}
              className="w-full px-6 py-3 bg-orange-500 hover:bg-orange-600 text-white rounded-lg transition font-medium"
            >
              Go to Library
            </button>
            <button
              onClick={() => navigate('/marketplace')}
              className="w-full px-6 py-3 text-white rounded-lg transition font-medium"
              style={{
                backgroundColor: 'rgba(255, 255, 255, 0.1)',
                ':hover': { backgroundColor: 'rgba(255, 255, 255, 0.15)' }
              }}
            >
              Back to Marketplace
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
