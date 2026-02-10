import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { authApi } from '../lib/api';
import { PulsingGridSpinner } from '../components/PulsingGridSpinner';
import { TesslateLogo } from '../components/ui/TesslateLogo';

export default function ForgotPassword() {
  const [email, setEmail] = useState('');
  const [loading, setLoading] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);

    try {
      await authApi.forgotPassword(email);
      setSubmitted(true);
    } catch {
      // Always show success to avoid leaking whether the email exists
      setSubmitted(true);
    } finally {
      setLoading(false);
    }
  };

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
            <h1 className="text-3xl sm:text-4xl font-bold text-gray-900 mb-3">
              Reset your password
            </h1>
            <p className="text-gray-600 text-sm leading-relaxed">
              {submitted
                ? "If an account exists with that email, we've sent a password reset link."
                : "Enter your email address and we'll send you a link to reset your password."}
            </p>
          </div>

          {submitted ? (
            <div className="space-y-6">
              {/* Success state */}
              <div className="bg-gray-50 border border-gray-200 rounded-xl p-4 text-center">
                <svg
                  className="w-12 h-12 mx-auto mb-3 text-gray-400"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={1.5}
                    d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"
                  />
                </svg>
                <p className="text-gray-700 text-sm font-medium">Check your email</p>
                <p className="text-gray-500 text-xs mt-1">
                  We sent a reset link to <strong>{email}</strong>
                </p>
              </div>

              <div className="text-center">
                <Link
                  to="/login"
                  className="text-black hover:text-gray-700 font-semibold transition-colors text-sm underline"
                >
                  Back to sign in
                </Link>
              </div>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full bg-gray-50 border border-gray-200 text-gray-900 px-4 py-3 rounded-xl focus:outline-none focus:ring-2 focus:ring-gray-900 focus:border-transparent transition-all placeholder:text-gray-400 text-sm"
                  placeholder="Email address"
                  required
                  autoComplete="email"
                  maxLength={254}
                  autoFocus
                />
              </div>

              <button
                type="submit"
                disabled={loading}
                className="w-full bg-black text-white py-3.5 px-4 rounded-xl hover:bg-gray-800 disabled:opacity-50 disabled:cursor-not-allowed font-semibold transition-all duration-200 text-sm mt-2"
              >
                {loading ? (
                  <div className="flex items-center justify-center gap-2">
                    <PulsingGridSpinner size={18} />
                    <span>Sending...</span>
                  </div>
                ) : (
                  'Send reset link'
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
          )}
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
            Don't worry,
            <br />
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-orange-400 to-orange-600">
              we've got you.
            </span>
          </h2>
          <p className="text-gray-400 text-lg">
            We'll help you get back into your account in no time.
          </p>
        </div>
      </div>
    </div>
  );
}
