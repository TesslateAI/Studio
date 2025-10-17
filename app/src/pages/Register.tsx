import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { authApi } from '../lib/api';
import { PulsingGridSpinner } from '../components/PulsingGridSpinner';
import toast from 'react-hot-toast';

export default function Register() {
  const navigate = useNavigate();
  const [formData, setFormData] = useState({
    name: '',
    username: '',
    email: '',
    password: '',
    confirmPassword: '',
  });
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (formData.password !== formData.confirmPassword) {
      toast.error('Passwords do not match');
      return;
    }

    setLoading(true);

    try {
      const response = await authApi.register(formData.name, formData.username, formData.email, formData.password);

      // Store tokens from registration (auto-login)
      localStorage.setItem('token', response.access_token);
      if (response.refresh_token) {
        localStorage.setItem('refreshToken', response.refresh_token);
      }

      toast.success('Account created successfully!');
      navigate('/dashboard');
    } catch (error: any) {
      // Handle validation errors (array format from FastAPI/Pydantic)
      if (error.response?.data?.detail && Array.isArray(error.response.data.detail)) {
        const messages = error.response.data.detail.map((err: any) => err.msg).join(', ');
        toast.error(messages);
      } else if (typeof error.response?.data?.detail === 'string') {
        toast.error(error.response.data.detail);
      } else {
        toast.error('Registration failed. Please try again.');
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
            backgroundImage: 'url(https://images.unsplash.com/photo-1441974231531-c6227db76b6e?w=1200&q=80)'
          }}
        />

        {/* Right side - Form */}
        <div className="w-full lg:w-1/2 flex items-center justify-center p-4 sm:p-6 lg:p-16 bg-[#0a0a0a]">
        <div className="w-full max-w-md">
          <div className="mb-6 sm:mb-8">
            <h1 className="text-2xl sm:text-3xl font-bold text-white mb-2">
              Create your account
            </h1>
            <p className="text-gray-400 text-xs sm:text-sm">
              Experience next-generation artificial intelligence tools designed to boost productivity and automate tasks.
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-white text-sm font-medium mb-2">
                Full Name*
              </label>
              <input
                type="text"
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                className="w-full bg-transparent border border-gray-700 text-white px-3 py-2.5 sm:px-4 sm:py-3 rounded-lg focus:outline-none focus:ring-2 focus:ring-gray-600 focus:border-transparent transition-all placeholder:text-gray-500"
                placeholder="Andrew Gonzales"
                required
              />
            </div>

            <div>
              <label className="block text-white text-sm font-medium mb-2">
                Username*
              </label>
              <input
                type="text"
                value={formData.username}
                onChange={(e) => setFormData({ ...formData, username: e.target.value })}
                className="w-full bg-transparent border border-gray-700 text-white px-3 py-2.5 sm:px-4 sm:py-3 rounded-lg focus:outline-none focus:ring-2 focus:ring-gray-600 focus:border-transparent transition-all placeholder:text-gray-500"
                placeholder="andrewg"
                required
              />
            </div>

            <div>
              <label className="block text-white text-sm font-medium mb-2">
                Email Address*
              </label>
              <input
                type="email"
                value={formData.email}
                onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                className="w-full bg-transparent border border-gray-700 text-white px-3 py-2.5 sm:px-4 sm:py-3 rounded-lg focus:outline-none focus:ring-2 focus:ring-gray-600 focus:border-transparent transition-all placeholder:text-gray-500"
                placeholder="andrew@example.com"
                required
              />
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 sm:gap-4">
              <div>
                <label className="block text-white text-sm font-medium mb-2">
                  Password*
                </label>
                <input
                  type="password"
                  value={formData.password}
                  onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                  className="w-full bg-transparent border border-gray-700 text-white px-3 py-2.5 sm:px-4 sm:py-3 rounded-lg focus:outline-none focus:ring-2 focus:ring-gray-600 focus:border-transparent transition-all placeholder:text-gray-500"
                  placeholder="•••••••"
                  required
                  minLength={6}
                />
              </div>

              <div>
                <label className="block text-white text-sm font-medium mb-2">
                  Confirm*
                </label>
                <input
                  type="password"
                  value={formData.confirmPassword}
                  onChange={(e) => setFormData({ ...formData, confirmPassword: e.target.value })}
                  className="w-full bg-transparent border border-gray-700 text-white px-3 py-2.5 sm:px-4 sm:py-3 rounded-lg focus:outline-none focus:ring-2 focus:ring-gray-600 focus:border-transparent transition-all placeholder:text-gray-500"
                  placeholder="•••••••"
                  required
                  minLength={6}
                />
              </div>
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
                  <span className="text-sm sm:text-base">Creating account...</span>
                </div>
              ) : (
                'Create Account'
              )}
            </button>
          </form>

          <div className="mt-6 text-center">
            <p className="text-gray-400 text-sm">
              Already have an account?{' '}
              <Link
                to="/login"
                className="text-white hover:text-gray-300 font-semibold transition-colors"
              >
                Sign in instead
              </Link>
            </p>
          </div>

          <p className="text-center text-gray-600 text-xs mt-8">
            By signing up, you agree to our{' '}
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
