import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { authApi } from '../lib/api';
import { PulsingGridSpinner } from '../components/PulsingGridSpinner';
import toast from 'react-hot-toast';

export default function Login() {
  const navigate = useNavigate();
  const [formData, setFormData] = useState({
    username: '',
    password: '',
  });
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);

    try {
      const response = await authApi.login(formData.username, formData.password);
      localStorage.setItem('token', response.access_token);

      // Store refresh token for automatic token renewal
      if (response.refresh_token) {
        localStorage.setItem('refreshToken', response.refresh_token);
      }

      toast.success('Logged in successfully!');
      navigate('/dashboard');
    } catch (error: any) {
      // Handle validation errors (array format from FastAPI/Pydantic)
      if (error.response?.data?.detail && Array.isArray(error.response.data.detail)) {
        const messages = error.response.data.detail.map((err: any) => err.msg).join(', ');
        toast.error(messages);
      } else if (typeof error.response?.data?.detail === 'string') {
        toast.error(error.response.data.detail);
      } else {
        toast.error('Login failed. Please try again.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      className="min-h-screen flex items-center justify-center p-4 sm:p-8"
      style={{
        backgroundColor: '#1a1a1a',
        backgroundImage: "url(\"data:image/svg+xml,%3Csvg width='6' height='6' viewBox='0 0 6 6' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='%233a3a3a' fill-opacity='0.4' fill-rule='evenodd'%3E%3Cpath d='M5 0h1L0 6V5zM6 5v1H5z'/%3E%3C/g%3E%3C/svg%3E\")"
      }}
    >
      {/* Centered floating container */}
      <div className="flex w-full max-w-6xl rounded-lg sm:rounded-xl lg:rounded-3xl overflow-hidden shadow-2xl border border-black/30 sm:border-2 lg:border-4 border-black/50">
        {/* Left side - Image */}
        <div
          className="hidden lg:block lg:w-1/2 bg-cover bg-center"
          style={{
            backgroundImage: 'url(https://images.unsplash.com/photo-1506905925346-21bda4d32df4?w=1200&q=80)'
          }}
        />

        {/* Right side - Form */}
        <div className="w-full lg:w-1/2 flex items-center justify-center p-4 sm:p-6 lg:p-16 bg-[#0a0a0a]">
        <div className="w-full max-w-md">
          <div className="mb-6 sm:mb-8">
            <h1 className="text-2xl sm:text-3xl font-bold text-white mb-2">
              Welcome back
            </h1>
            <p className="text-gray-400 text-xs sm:text-sm">
              Sign in to your account to continue building amazing apps
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-white text-sm font-medium mb-2">
                Username or Email
              </label>
              <input
                type="text"
                value={formData.username}
                onChange={(e) => setFormData({ ...formData, username: e.target.value })}
                className="w-full bg-transparent border border-gray-700 text-white px-3 py-2.5 sm:px-4 sm:py-3 rounded-lg focus:outline-none focus:ring-2 focus:ring-gray-600 focus:border-transparent transition-all placeholder:text-gray-500 text-sm sm:text-base"
                placeholder="Enter your username or email"
                required
              />
            </div>

            <div>
              <label className="block text-white text-sm font-medium mb-2">
                Password
              </label>
              <input
                type="password"
                value={formData.password}
                onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                className="w-full bg-transparent border border-gray-700 text-white px-3 py-2.5 sm:px-4 sm:py-3 rounded-lg focus:outline-none focus:ring-2 focus:ring-gray-600 focus:border-transparent transition-all placeholder:text-gray-500 text-sm sm:text-base"
                placeholder="Enter your password"
                required
              />
            </div>

            <p className="text-xs text-gray-500">
              Your security is our priority. Use a strong password to protect your account.
            </p>

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-[#FF6B00] text-white py-2.5 sm:py-3 px-4 rounded-lg hover:bg-[#ff7a1a] disabled:opacity-50 disabled:cursor-not-allowed font-semibold transition-all duration-300 hover:shadow-lg mt-4 sm:mt-6 text-sm sm:text-base"
            >
              {loading ? (
                <div className="flex items-center justify-center gap-2">
                  <PulsingGridSpinner size={18} />
                  <span className="text-sm sm:text-base">Signing in...</span>
                </div>
              ) : (
                'Sign In'
              )}
            </button>
          </form>

          <div className="mt-6 text-center">
            <p className="text-gray-400 text-sm">
              Don't have an account?{' '}
              <Link
                to="/register"
                className="text-white hover:text-gray-300 font-semibold transition-colors"
              >
                Sign Up
              </Link>
            </p>
          </div>

          <p className="text-center text-gray-600 text-xs mt-8">
            By signing in, you agree to our{' '}
            <span className="text-gray-500 hover:text-gray-400 cursor-pointer">Terms of Service</span>
            {' '}and{' '}
            <span className="text-gray-500 hover:text-gray-400 cursor-pointer">Privacy Policy</span>.
          </p>
        </div>
      </div>
      </div>
    </div>
  );
}
