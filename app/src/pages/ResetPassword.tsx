import React, { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { authApi } from '../lib/api';
import { PulsingGridSpinner } from '../components/PulsingGridSpinner';
import { TesslateLogo } from '../components/ui/TesslateLogo';
import toast from 'react-hot-toast';

export default function ResetPassword() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token');

  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (password !== confirmPassword) {
      toast.error('Passwords do not match');
      return;
    }

    if (password.length < 6) {
      toast.error('Password must be at least 6 characters');
      return;
    }

    if (!token) {
      toast.error('Invalid or missing reset token');
      return;
    }

    setLoading(true);

    try {
      await authApi.resetPassword(token, password);
      toast.success('Password reset successfully! Please sign in.');
      navigate('/login');
    } catch (error: unknown) {
      const err = error as { response?: { data?: { detail?: string } } };
      if (typeof err.response?.data?.detail === 'string') {
        const detail = err.response.data.detail;
        if (detail === 'RESET_PASSWORD_BAD_TOKEN') {
          toast.error('This reset link has expired or is invalid. Please request a new one.');
        } else if (detail === 'RESET_PASSWORD_INVALID_PASSWORD') {
          toast.error('Password does not meet requirements');
        } else {
          toast.error(detail);
        }
      } else {
        toast.error('Failed to reset password. Please try again.');
      }
    } finally {
      setLoading(false);
    }
  };

  // No token in URL
  if (!token) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-white p-6">
        <div className="text-center max-w-md">
          <h1 className="text-2xl font-bold text-gray-900 mb-4">Invalid reset link</h1>
          <p className="text-gray-600 text-sm mb-6">
            This password reset link is invalid or has expired. Please request a new one.
          </p>
          <Link
            to="/forgot-password"
            className="inline-block bg-black text-white py-3 px-6 rounded-xl hover:bg-gray-800 font-semibold transition-all duration-200 text-sm"
          >
            Request new link
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex">
      {/* Left side - White form section */}
      <div className="w-full lg:w-1/2 bg-white flex items-center justify-center p-6 sm:p-12">
        <div className="w-full max-w-md">
          {/* Logo */}
          <div className="mb-8">
            <div className="w-12 h-12 flex items-center justify-center">
              <TesslateLogo width={48} height={38} className="text-black" />
            </div>
          </div>

          {/* Heading */}
          <div className="mb-8">
            <h1 className="text-3xl sm:text-4xl font-bold text-gray-900 mb-3">Set new password</h1>
            <p className="text-gray-600 text-sm leading-relaxed">
              Enter your new password below. It must be at least 6 characters long.
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full bg-gray-50 border border-gray-200 text-gray-900 px-4 py-3 rounded-xl focus:outline-none focus:ring-2 focus:ring-gray-900 focus:border-transparent transition-all placeholder:text-gray-400 text-sm"
                placeholder="New password"
                required
                autoComplete="new-password"
                minLength={6}
                maxLength={72}
                autoFocus
              />
            </div>

            <div>
              <input
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                className="w-full bg-gray-50 border border-gray-200 text-gray-900 px-4 py-3 rounded-xl focus:outline-none focus:ring-2 focus:ring-gray-900 focus:border-transparent transition-all placeholder:text-gray-400 text-sm"
                placeholder="Confirm new password"
                required
                autoComplete="new-password"
                minLength={6}
                maxLength={72}
              />
            </div>

            {password && confirmPassword && password !== confirmPassword && (
              <p className="text-red-500 text-xs">Passwords do not match</p>
            )}

            <button
              type="submit"
              disabled={loading || !password || !confirmPassword}
              className="w-full bg-black text-white py-3.5 px-4 rounded-xl hover:bg-gray-800 disabled:opacity-50 disabled:cursor-not-allowed font-semibold transition-all duration-200 text-sm mt-2"
            >
              {loading ? (
                <div className="flex items-center justify-center gap-2">
                  <PulsingGridSpinner size={18} />
                  <span>Resetting...</span>
                </div>
              ) : (
                'Reset password'
              )}
            </button>

            <div className="text-center mt-6">
              <Link
                to="/login"
                className="text-gray-600 hover:text-gray-900 text-sm transition-colors"
              >
                Back to sign in
              </Link>
            </div>
          </form>
        </div>
      </div>

      {/* Right side - Dark hero section */}
      <div
        className="hidden lg:flex lg:w-1/2 items-center justify-center p-12 relative overflow-hidden"
        style={{
          background: 'linear-gradient(180deg, #0a0a0f 0%, #1a1a2e 50%, #16213e 100%)',
        }}
      >
        {/* Starry background effect */}
        <div
          className="absolute inset-0"
          style={{
            backgroundImage: `
            radial-gradient(2px 2px at 20% 30%, white, transparent),
            radial-gradient(2px 2px at 60% 70%, white, transparent),
            radial-gradient(1px 1px at 50% 50%, white, transparent),
            radial-gradient(1px 1px at 80% 10%, white, transparent),
            radial-gradient(2px 2px at 90% 60%, white, transparent),
            radial-gradient(1px 1px at 33% 80%, white, transparent),
            radial-gradient(1px 1px at 70% 40%, white, transparent)
          `,
            backgroundSize: '200% 200%',
            backgroundPosition: '0% 0%, 100% 100%, 50% 50%, 0% 100%, 100% 0%, 33% 100%, 70% 40%',
            opacity: 0.5,
          }}
        ></div>

        <div className="relative z-10 max-w-lg text-center">
          <h2 className="text-4xl sm:text-5xl font-bold text-white mb-6 leading-tight">
            Almost there,
            <br />
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-orange-400 to-orange-600">
              just one step.
            </span>
          </h2>
          <p className="text-gray-400 text-lg">
            Choose a strong password to keep your account secure.
          </p>
        </div>
      </div>
    </div>
  );
}
