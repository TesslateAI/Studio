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
      // Register the user
      await authApi.register(formData.name, formData.username, formData.email, formData.password);

      toast.success('Account created successfully!');

      // Auto-login after registration
      const loginResponse = await authApi.login(formData.email, formData.password);
      localStorage.setItem('token', loginResponse.access_token);

      navigate('/dashboard');
    } catch (error: any) {
      // Handle validation errors (array format from FastAPI/Pydantic)
      if (error.response?.data?.detail && Array.isArray(error.response.data.detail)) {
        const messages = error.response.data.detail.map((err: any) => err.msg).join(', ');
        toast.error(messages);
      } else if (typeof error.response?.data?.detail === 'string') {
        const errorMessage = error.response.data.detail;
        if (errorMessage === 'REGISTER_USER_ALREADY_EXISTS') {
          toast.error('Email or username already exists');
        } else {
          toast.error(errorMessage);
        }
      } else {
        toast.error('Registration failed. Please try again.');
      }
    } finally {
      setLoading(false);
    }
  };

  const handleGithubLogin = () => {
    // Redirect to GitHub OAuth
    window.location.href = authApi.getGithubAuthUrl();
  };

  const handleGoogleLogin = () => {
    // Redirect to Google OAuth
    window.location.href = authApi.getGoogleAuthUrl();
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

          {/* OAuth Divider */}
          <div className="mt-6 mb-6 flex items-center">
            <div className="flex-1 border-t border-gray-700"></div>
            <span className="px-4 text-gray-500 text-sm">Or sign up with</span>
            <div className="flex-1 border-t border-gray-700"></div>
          </div>

          {/* OAuth Buttons */}
          <div className="grid grid-cols-2 gap-3">
            <button
              onClick={handleGithubLogin}
              disabled={loading}
              className="flex items-center justify-center gap-2 bg-[#24292e] text-white py-2.5 px-4 rounded-lg hover:bg-[#2f363d] disabled:opacity-50 disabled:cursor-not-allowed font-medium transition-all duration-300 text-sm"
            >
              <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
                <path fillRule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z" clipRule="evenodd" />
              </svg>
              GitHub
            </button>

            <button
              onClick={handleGoogleLogin}
              disabled={loading}
              className="flex items-center justify-center gap-2 bg-white text-gray-800 py-2.5 px-4 rounded-lg hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed font-medium transition-all duration-300 text-sm border border-gray-300"
            >
              <svg className="w-5 h-5" viewBox="0 0 24 24">
                <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
                <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
                <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
                <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
              </svg>
              Google
            </button>
          </div>

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
