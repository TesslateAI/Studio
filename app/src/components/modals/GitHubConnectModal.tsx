import { useState } from 'react';
import { GitBranch, X, Eye, EyeSlash } from '@phosphor-icons/react';
import { githubApi } from '../../lib/github-api';
import toast from 'react-hot-toast';

interface GitHubConnectModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

export function GitHubConnectModal({ isOpen, onClose, onSuccess }: GitHubConnectModalProps) {
  const [patToken, setPatToken] = useState('');
  const [showToken, setShowToken] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);

  if (!isOpen) return null;

  const handleConnect = async () => {
    if (!patToken.trim()) {
      toast.error('Please enter your GitHub Personal Access Token');
      return;
    }

    // Validate token format
    if (!patToken.startsWith('ghp_') && !patToken.startsWith('github_pat_')) {
      toast.error('Invalid token format. PAT should start with "ghp_" or "github_pat_"');
      return;
    }

    setIsConnecting(true);
    const loadingToast = toast.loading('Connecting to GitHub...');

    try {
      const result = await githubApi.connect(patToken);
      toast.success(`Connected as @${result.username}`, { id: loadingToast });
      setPatToken('');
      onSuccess();
      onClose();
    } catch (error: any) {
      const errorMessage = error.response?.data?.detail || 'Failed to connect to GitHub';
      toast.error(errorMessage, { id: loadingToast });
    } finally {
      setIsConnecting(false);
    }
  };

  const handleClose = () => {
    if (!isConnecting) {
      setPatToken('');
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
              <p className="text-sm text-gray-500">Link your GitHub account</p>
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

        {/* Instructions */}
        <div className="bg-blue-500/10 border border-blue-500/20 rounded-xl p-4 mb-6">
          <h3 className="text-sm font-semibold text-blue-400 mb-2">How to get your token:</h3>
          <ol className="text-sm text-gray-400 space-y-1 list-decimal list-inside">
            <li>Go to GitHub Settings → Developer settings → Personal access tokens</li>
            <li>Click "Generate new token (classic)"</li>
            <li>Select the "repo" scope (full control of repositories)</li>
            <li>Copy the token and paste it below</li>
          </ol>
          <a
            href="https://github.com/settings/tokens"
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-blue-400 hover:text-blue-300 inline-flex items-center gap-1 mt-2"
          >
            Open GitHub Settings →
          </a>
        </div>

        {/* Token Input */}
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-[var(--text)] mb-2">
              Personal Access Token
            </label>
            <div className="relative">
              <input
                type={showToken ? 'text' : 'password'}
                value={patToken}
                onChange={(e) => setPatToken(e.target.value)}
                className="w-full bg-white/5 border border-white/10 text-[var(--text)] px-4 py-3 pr-12 rounded-xl focus:outline-none focus:ring-2 focus:ring-purple-500 placeholder-gray-500 font-mono text-sm"
                placeholder="ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
                disabled={isConnecting}
                autoFocus
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !isConnecting) {
                    handleConnect();
                  }
                }}
              />
              <button
                type="button"
                onClick={() => setShowToken(!showToken)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-white transition-colors"
                disabled={isConnecting}
              >
                {showToken ? (
                  <EyeSlash className="w-5 h-5" />
                ) : (
                  <Eye className="w-5 h-5" />
                )}
              </button>
            </div>
            <p className="text-xs text-gray-500 mt-2">
              Your token is encrypted and stored securely. We never share it.
            </p>
          </div>

          {/* Actions */}
          <div className="flex gap-3 pt-2">
            <button
              onClick={handleConnect}
              disabled={isConnecting || !patToken.trim()}
              className="flex-1 bg-purple-500 hover:bg-purple-600 disabled:bg-gray-600 disabled:cursor-not-allowed text-white py-3 rounded-xl font-semibold transition-all"
            >
              {isConnecting ? 'Connecting...' : 'Connect GitHub'}
            </button>
            <button
              onClick={handleClose}
              disabled={isConnecting}
              className="flex-1 bg-white/5 border border-white/10 text-[var(--text)] py-3 rounded-xl font-semibold hover:bg-white/10 transition-all disabled:opacity-50"
            >
              Cancel
            </button>
          </div>
        </div>

        {/* Security Note */}
        <div className="mt-4 flex items-start gap-2 text-xs text-gray-500">
          <span className="mt-0.5">🔒</span>
          <p>
            Your GitHub token is encrypted at rest and never exposed in logs or API responses.
            You can revoke access anytime from your GitHub settings.
          </p>
        </div>
      </div>
    </div>
  );
}
