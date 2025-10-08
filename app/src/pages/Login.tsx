import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { authApi } from '../lib/api';
import toast from 'react-hot-toast';
import { LogIn, Sun, Moon, Sparkles } from 'lucide-react';
import { useTheme } from '../theme/ThemeContext';

export default function Login() {
  const navigate = useNavigate();
  const { theme, toggleTheme } = useTheme();
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
    <div className="min-h-screen flex items-center justify-center px-4 relative overflow-hidden">
      {/* Theme toggle button */}
      <button
        onClick={toggleTheme}
        className="absolute top-6 right-6 w-12 h-12 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 flex items-center justify-center transition-all duration-300 hover:scale-105"
        aria-label="Toggle theme"
      >
        {theme === 'dark' ? (
          <Sun className="w-5 h-5 text-orange-400" />
        ) : (
          <Moon className="w-5 h-5 text-gray-600" />
        )}
      </button>

      {/* Decorative gradient blobs */}
      <div className="absolute top-0 left-0 w-96 h-96 bg-gradient-to-br from-[var(--primary)]/20 to-transparent rounded-full blur-3xl opacity-30 -translate-x-1/2 -translate-y-1/2" />
      <div className="absolute bottom-0 right-0 w-96 h-96 bg-gradient-to-br from-[var(--accent)]/20 to-transparent rounded-full blur-3xl opacity-30 translate-x-1/2 translate-y-1/2" />

      <div className="w-full max-w-md relative z-10">
        {/* Logo and title */}
        <div className="text-center mb-8 animate-in fade-in slide-in-from-top duration-700">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-gradient-to-br from-[var(--primary)] to-orange-600 mb-4 shadow-lg">
            <Sparkles className="w-8 h-8 text-white" />
          </div>
          <h1 className="font-heading text-4xl font-bold mb-2 bg-gradient-to-r from-[var(--primary)] to-orange-600 bg-clip-text text-transparent">
            Tesslate Studio
          </h1>
          <p className="text-[var(--text)]/60">Build amazing apps with AI</p>
        </div>

        {/* Glass morphism container */}
        <div className="backdrop-blur-xl bg-[var(--surface)]/50 border border-white/10 rounded-[var(--radius)] p-8 shadow-2xl animate-in fade-in slide-in-from-bottom duration-700">
          <h2 className="font-heading text-2xl font-bold text-[var(--text)] mb-6">
            Welcome back
          </h2>

          <form onSubmit={handleSubmit} className="space-y-5">
            <div className="space-y-2">
              <label className="block text-[var(--text)]/80 text-sm font-medium">
                Username
              </label>
              <input
                type="text"
                value={formData.username}
                onChange={(e) => setFormData({ ...formData, username: e.target.value })}
                className="w-full bg-white/5 border border-white/10 text-[var(--text)] px-4 py-3 rounded-xl focus:outline-none focus:ring-2 focus:ring-[var(--primary)]/50 focus:border-[var(--primary)]/50 transition-all duration-300"
                placeholder="Enter your username"
                required
                aria-label="Username"
              />
            </div>

            <div className="space-y-2">
              <label className="block text-[var(--text)]/80 text-sm font-medium">
                Password
              </label>
              <input
                type="password"
                value={formData.password}
                onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                className="w-full bg-white/5 border border-white/10 text-[var(--text)] px-4 py-3 rounded-xl focus:outline-none focus:ring-2 focus:ring-[var(--primary)]/50 focus:border-[var(--primary)]/50 transition-all duration-300"
                placeholder="Enter your password"
                required
                aria-label="Password"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-gradient-to-r from-[var(--primary)] to-orange-600 text-white py-3 px-4 rounded-xl hover:shadow-lg hover:shadow-[var(--primary)]/25 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2 font-semibold transition-all duration-300 hover:scale-[1.02] active:scale-[0.98]"
              aria-label={loading ? 'Logging in' : 'Login'}
            >
              {loading ? (
                <>
                  <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  Logging in...
                </>
              ) : (
                <>
                  <LogIn size={20} />
                  Login
                </>
              )}
            </button>
          </form>

          <div className="mt-6 pt-6 border-t border-white/10 text-center">
            <p className="text-[var(--text)]/60 text-sm">
              Don't have an account?{' '}
              <Link
                to="/register"
                className="text-[var(--primary)] hover:text-orange-600 font-semibold transition-colors duration-300"
              >
                Create one
              </Link>
            </p>
          </div>
        </div>

        <p className="text-center text-[var(--text)]/40 text-xs mt-6">
          By logging in, you agree to our Terms of Service and Privacy Policy
        </p>
      </div>
    </div>
  );
}