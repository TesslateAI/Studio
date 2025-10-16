import { useState } from 'react';
import { GitBranch, X, ArrowSquareOut } from '@phosphor-icons/react';
import { githubApi } from '../../lib/github-api';
import { PulsingGridSpinner } from '../PulsingGridSpinner';
import toast from 'react-hot-toast';

interface GitHubConnectModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

export function GitHubConnectModal({ isOpen, onClose, onSuccess }: GitHubConnectModalProps) {
  const [isConnecting, setIsConnecting] = useState(false);

  if (!isOpen) return null;

  const handleOAuthConnect = async () => {
    setIsConnecting(true);

    try {
      // Store current page for redirect after OAuth
      const currentPath = window.location.pathname;
      sessionStorage.setItem('github_oauth_return', currentPath);

      // Get OAuth authorization URL from backend
      const { authorization_url } = await githubApi.initiateOAuth();

      // Redirect to GitHub OAuth page
      window.location.href = authorization_url;
    } catch (error: any) {
      const detail = error.response?.data?.detail;
      const errorMessage = typeof detail === 'string' ? detail : (error.message || 'Failed to initiate GitHub OAuth');
      toast.error(errorMessage);
      setIsConnecting(false);
    }
  };

  const handleClose = () => {
    if (!isConnecting) {
      onClose();
    }
  };

  return (
    <div
      className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50"
      onClick={handleClose}
    >
      <div
        className="bg-[var(--surface)] p-8 rounded-3xl w-full max-w-md shadow-2xl border border-white/10"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 bg-purple-500/20 rounded-xl flex items-center justify-center">
              <GitBranch className="w-6 h-6 text-purple-400" weight="fill" />
            </div>
            <div>
              <h2 className="font-heading text-2xl font-bold text-[var(--text)]">Connect GitHub</h2>
              <p className="text-sm text-gray-500">Authorize Tesslate Studio</p>
            </div>
          </div>
          {!isConnecting && (
            <button
              onClick={handleClose}
              className="text-gray-400 hover:text-white transition-colors p-2"
            >
              <X className="w-5 h-5" />
            </button>
          )}
        </div>

        {/* OAuth Benefits */}
        <div className="bg-purple-500/10 border border-purple-500/20 rounded-xl p-4 mb-6">
          <h3 className="text-sm font-semibold text-purple-400 mb-3">What you'll get:</h3>
          <ul className="space-y-2 text-sm text-gray-300">
            <li className="flex items-start gap-2">
              <span className="text-purple-400 mt-0.5">✓</span>
              <span>Access to all your repositories</span>
            </li>
            <li className="flex items-start gap-2">
              <span className="text-purple-400 mt-0.5">✓</span>
              <span>Push and pull code changes</span>
            </li>
            <li className="flex items-start gap-2">
              <span className="text-purple-400 mt-0.5">✓</span>
              <span>Create new repositories</span>
            </li>
            <li className="flex items-start gap-2">
              <span className="text-purple-400 mt-0.5">✓</span>
              <span>Manage branches and commits</span>
            </li>
          </ul>
        </div>

        {/* OAuth Permissions */}
        <div className="bg-blue-500/10 border border-blue-500/20 rounded-xl p-4 mb-6">
          <h3 className="text-sm font-semibold text-blue-400 mb-2">Required permissions:</h3>
          <div className="flex flex-wrap gap-2">
            <span className="px-2 py-1 bg-blue-500/20 text-blue-300 text-xs rounded-lg font-mono">
              repo
            </span>
            <span className="px-2 py-1 bg-blue-500/20 text-blue-300 text-xs rounded-lg font-mono">
              user:email
            </span>
          </div>
          <p className="text-xs text-gray-500 mt-2">
            We only request the minimum permissions needed to sync your code.
          </p>
        </div>

        {/* Connect Button */}
        <button
          onClick={handleOAuthConnect}
          disabled={isConnecting}
          className="w-full bg-gradient-to-r from-purple-500 to-purple-600 hover:from-purple-600 hover:to-purple-700 disabled:from-gray-600 disabled:to-gray-700 disabled:cursor-not-allowed text-white py-3 rounded-xl font-semibold transition-all flex items-center justify-center gap-2 group"
        >
          {isConnecting ? (
            <>
              <PulsingGridSpinner size={20} />
              <span>Redirecting to GitHub...</span>
            </>
          ) : (
            <>
              <GitBranch className="w-5 h-5" weight="bold" />
              <span>Connect with GitHub</span>
              <ArrowSquareOut className="w-4 h-4 opacity-60 group-hover:opacity-100 transition-opacity" />
            </>
          )}
        </button>

        {/* Security Note */}
        <div className="mt-6 flex items-start gap-2 text-xs text-gray-500">
          <span className="mt-0.5">🔒</span>
          <div>
            <p>Your connection is secured with OAuth 2.0</p>
            <p className="mt-1">
              You can revoke access anytime from your{' '}
              <a
                href="https://github.com/settings/applications"
                target="_blank"
                rel="noopener noreferrer"
                className="text-blue-400 hover:text-blue-300 underline"
              >
                GitHub settings
              </a>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}