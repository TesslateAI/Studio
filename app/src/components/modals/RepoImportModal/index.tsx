import { useState, useEffect, useCallback } from 'react';
import {
  Download,
  X,
  GitBranch,
  MagnifyingGlass,
  GithubLogo,
  Link as LinkIcon,
  Check,
  Lock,
  Globe,
} from '@phosphor-icons/react';
import { gitProvidersApi } from '../../../lib/git-providers-api';
import { gitApi } from '../../../lib/git-api';
import type {
  GitProvider,
  GitProviderRepository,
  AllProvidersStatus,
} from '../../../types/git-providers';
import { PROVIDER_CONFIG } from '../../../types/git-providers';
import toast from 'react-hot-toast';

interface RepoImportModalProps {
  isOpen: boolean;
  onClose: () => void;
  // For importing into existing project
  projectId?: number;
  onSuccess?: () => void;
  // For creating new project
  onCreateProject?: (provider: GitProvider, repoUrl: string, branch: string, projectName: string) => Promise<void>;
}

type ImportMode = 'url' | 'browse';

// Provider icons
const ProviderIcon = ({ provider, size = 20 }: { provider: GitProvider; size?: number }) => {
  if (provider === 'github') {
    return <GithubLogo size={size} weight="fill" />;
  }
  // For GitLab and Bitbucket, use text-based icons for now
  if (provider === 'gitlab') {
    return (
      <div className="font-bold text-[#FC6D26]" style={{ fontSize: size * 0.7 }}>
        GL
      </div>
    );
  }
  if (provider === 'bitbucket') {
    return (
      <div className="font-bold text-[#0052CC]" style={{ fontSize: size * 0.7 }}>
        BB
      </div>
    );
  }
  return null;
};

export function RepoImportModal({ isOpen, onClose, projectId, onSuccess, onCreateProject }: RepoImportModalProps) {
  const [mode, setMode] = useState<ImportMode>('url');
  const [activeProvider, setActiveProvider] = useState<GitProvider>('github');
  const [repoUrl, setRepoUrl] = useState('');
  const [branch, setBranch] = useState('main');
  const [projectName, setProjectName] = useState('');

  // Determine if we're creating a new project or importing into existing
  const isNewProjectMode = !projectId && !!onCreateProject;
  const [repositories, setRepositories] = useState<GitProviderRepository[]>([]);
  const [filteredRepos, setFilteredRepos] = useState<GitProviderRepository[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedRepo, setSelectedRepo] = useState<GitProviderRepository | null>(null);
  const [isImporting, setIsImporting] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);
  const [providerStatus, setProviderStatus] = useState<AllProvidersStatus>({
    github: { connected: false },
    gitlab: { connected: false },
    bitbucket: { connected: false },
  });

  // Load provider status on mount
  useEffect(() => {
    if (isOpen) {
      loadProviderStatus();
    }
  }, [isOpen]);

  // Load repositories when switching to browse mode or changing provider
  useEffect(() => {
    if (isOpen && mode === 'browse' && providerStatus[activeProvider].connected) {
      loadRepositories();
    }
  }, [isOpen, mode, activeProvider, providerStatus]);

  // Filter repositories based on search
  useEffect(() => {
    if (searchQuery.trim() === '') {
      setFilteredRepos(repositories);
    } else {
      const query = searchQuery.toLowerCase();
      setFilteredRepos(
        repositories.filter(
          (repo) =>
            repo.name.toLowerCase().includes(query) ||
            repo.description?.toLowerCase().includes(query) ||
            repo.full_name.toLowerCase().includes(query)
        )
      );
    }
  }, [searchQuery, repositories]);

  // Auto-detect provider from URL
  useEffect(() => {
    if (mode === 'url' && repoUrl) {
      const detected = gitProvidersApi.detectProvider(repoUrl);
      if (detected && detected !== activeProvider) {
        setActiveProvider(detected);
      }
    }
  }, [repoUrl, mode]);

  const loadProviderStatus = async () => {
    try {
      const status = await gitProvidersApi.getAllStatus();
      setProviderStatus(status);
    } catch (error) {
      console.error('Failed to load provider status:', error);
    }
  };

  const loadRepositories = async () => {
    setIsLoading(true);
    setRepositories([]);
    setFilteredRepos([]);
    try {
      const repos = await gitProvidersApi.listRepositories(activeProvider);
      setRepositories(repos);
      setFilteredRepos(repos);
    } catch (error: unknown) {
      const message = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed to load repositories';
      toast.error(message);
      if (message.includes('not connected') || message.includes('expired')) {
        setMode('url');
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleConnect = async (provider: GitProvider) => {
    setIsConnecting(true);
    try {
      const { authorization_url } = await gitProvidersApi.initiateOAuth(provider);

      // Open in popup
      const width = 600;
      const height = 700;
      const left = window.screenX + (window.outerWidth - width) / 2;
      const top = window.screenY + (window.outerHeight - height) / 2;

      const popup = window.open(
        authorization_url,
        `${provider}-oauth`,
        `width=${width},height=${height},left=${left},top=${top}`
      );

      // Poll for popup close and refresh status
      const checkPopup = setInterval(async () => {
        if (popup?.closed) {
          clearInterval(checkPopup);
          setIsConnecting(false);
          await loadProviderStatus();
          // Check if now connected
          const newStatus = await gitProvidersApi.getStatus(provider);
          if (newStatus.connected) {
            toast.success(`${PROVIDER_CONFIG[provider].displayName} connected successfully!`);
            if (mode === 'browse') {
              await loadRepositories();
            }
          }
        }
      }, 500);

      // Timeout after 5 minutes
      setTimeout(() => {
        clearInterval(checkPopup);
        setIsConnecting(false);
      }, 5 * 60 * 1000);
    } catch (error: unknown) {
      setIsConnecting(false);
      const errorMessage = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed to initiate connection';
      toast.error(errorMessage);
    }
  };

  const handleImport = async () => {
    let finalRepoUrl = repoUrl;
    let finalBranch = branch;
    let finalProjectName = projectName;

    if (mode === 'browse') {
      if (!selectedRepo) {
        toast.error('Please select a repository');
        return;
      }
      finalRepoUrl = selectedRepo.clone_url;
      finalBranch = selectedRepo.default_branch;
      // Use repo name as project name if not specified
      if (!finalProjectName.trim()) {
        finalProjectName = selectedRepo.name;
      }
    } else {
      if (!finalRepoUrl.trim()) {
        toast.error('Please enter a repository URL');
        return;
      }
      // Extract repo name from URL if project name not specified
      if (!finalProjectName.trim() && isNewProjectMode) {
        const urlParts = finalRepoUrl.replace(/\.git$/, '').split('/');
        finalProjectName = urlParts[urlParts.length - 1] || 'imported-project';
      }
    }

    // Validate project name for new project mode
    if (isNewProjectMode && !finalProjectName.trim()) {
      toast.error('Please enter a project name');
      return;
    }

    setIsImporting(true);

    try {
      if (isNewProjectMode && onCreateProject) {
        // Creating new project from repository
        await onCreateProject(activeProvider, finalRepoUrl, finalBranch, finalProjectName);
        handleClose();
      } else if (projectId && onSuccess) {
        // Importing into existing project
        const loadingToast = toast.loading('Cloning repository...');
        try {
          await gitApi.clone(projectId, finalRepoUrl, finalBranch);
          toast.success('Repository cloned successfully!', { id: loadingToast });
          handleClose();
          onSuccess();
        } catch (error: unknown) {
          const errorMessage = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed to clone repository';
          toast.error(errorMessage, { id: loadingToast });
        }
      }
    } finally {
      setIsImporting(false);
    }
  };

  const handleClose = useCallback(() => {
    if (!isImporting) {
      setRepoUrl('');
      setBranch('main');
      setProjectName('');
      setSelectedRepo(null);
      setSearchQuery('');
      setRepositories([]);
      setFilteredRepos([]);
      onClose();
    }
  }, [isImporting, onClose]);

  if (!isOpen) return null;

  const currentProviderConnected = providerStatus[activeProvider].connected;
  const currentProviderConfig = PROVIDER_CONFIG[activeProvider];

  return (
    <div
      className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50"
      onClick={handleClose}
    >
      <div
        className="bg-[var(--surface)] p-8 rounded-3xl w-full max-w-3xl shadow-2xl border border-white/10 max-h-[90vh] overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 bg-blue-500/20 rounded-xl flex items-center justify-center">
              <Download className="w-6 h-6 text-blue-400" weight="fill" />
            </div>
            <div>
              <h2 className="font-heading text-2xl font-bold text-[var(--text)]">
                {isNewProjectMode ? 'Import from Repository' : 'Import Repository'}
              </h2>
              <p className="text-sm text-gray-500">
                {isNewProjectMode
                  ? 'Create a new project from GitHub, GitLab, or Bitbucket'
                  : 'Clone from GitHub, GitLab, or Bitbucket'}
              </p>
            </div>
          </div>
          {!isImporting && (
            <button
              onClick={handleClose}
              className="text-gray-400 hover:text-white transition-colors p-2"
            >
              <X className="w-5 h-5" />
            </button>
          )}
        </div>

        {/* Provider Tabs */}
        <div className="flex gap-2 mb-4">
          {(['github', 'gitlab', 'bitbucket'] as GitProvider[]).map((provider) => {
            const config = PROVIDER_CONFIG[provider];
            const status = providerStatus[provider];
            const isActive = activeProvider === provider;

            return (
              <button
                key={provider}
                onClick={() => {
                  setActiveProvider(provider);
                  setSelectedRepo(null);
                  setSearchQuery('');
                }}
                disabled={isImporting}
                className={`flex items-center gap-2 px-4 py-2 rounded-lg font-medium transition-all ${
                  isActive
                    ? 'bg-blue-500 text-white'
                    : 'bg-white/5 text-gray-400 hover:bg-white/10'
                }`}
              >
                <ProviderIcon provider={provider} size={18} />
                <span>{config.displayName}</span>
                {status.connected && (
                  <Check className="w-4 h-4 text-green-400" weight="bold" />
                )}
              </button>
            );
          })}
        </div>

        {/* Mode Selector */}
        <div className="flex gap-2 mb-6">
          <button
            onClick={() => setMode('url')}
            className={`flex items-center gap-2 flex-1 py-2 px-4 rounded-lg font-medium transition-all ${
              mode === 'url'
                ? 'bg-white/10 text-white border border-white/20'
                : 'bg-white/5 text-gray-400 hover:bg-white/10'
            }`}
            disabled={isImporting}
          >
            <LinkIcon className="w-4 h-4" />
            Enter URL
          </button>
          <button
            onClick={() => setMode('browse')}
            className={`flex items-center gap-2 flex-1 py-2 px-4 rounded-lg font-medium transition-all ${
              mode === 'browse'
                ? 'bg-white/10 text-white border border-white/20'
                : 'bg-white/5 text-gray-400 hover:bg-white/10'
            }`}
            disabled={isImporting}
          >
            <GitBranch className="w-4 h-4" />
            My Repositories
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto space-y-4">
          {mode === 'url' ? (
            <>
              {/* URL Input */}
              <div>
                <label className="block text-sm font-medium text-[var(--text)] mb-2">
                  Repository URL
                </label>
                <input
                  type="text"
                  value={repoUrl}
                  onChange={(e) => setRepoUrl(e.target.value)}
                  className="w-full bg-white/5 border border-white/10 text-[var(--text)] px-4 py-3 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500 placeholder-gray-500"
                  placeholder={`https://${activeProvider}.${activeProvider === 'bitbucket' ? 'org' : 'com'}/username/repository`}
                  disabled={isImporting}
                  autoFocus
                />
              </div>

              {/* Branch Input */}
              <div>
                <label className="block text-sm font-medium text-[var(--text)] mb-2">
                  Branch
                </label>
                <input
                  type="text"
                  value={branch}
                  onChange={(e) => setBranch(e.target.value)}
                  className="w-full bg-white/5 border border-white/10 text-[var(--text)] px-4 py-3 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500 placeholder-gray-500"
                  placeholder="main"
                  disabled={isImporting}
                />
              </div>

              {/* Project Name Input (only for new project mode) */}
              {isNewProjectMode && (
                <div>
                  <label className="block text-sm font-medium text-[var(--text)] mb-2">
                    Project Name
                  </label>
                  <input
                    type="text"
                    value={projectName}
                    onChange={(e) => setProjectName(e.target.value)}
                    className="w-full bg-white/5 border border-white/10 text-[var(--text)] px-4 py-3 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500 placeholder-gray-500"
                    placeholder="my-project (auto-detected from repo if empty)"
                    disabled={isImporting}
                  />
                </div>
              )}

              {/* Connection status hint */}
              {!currentProviderConnected && (
                <div className="bg-yellow-500/10 border border-yellow-500/20 rounded-xl p-4">
                  <p className="text-yellow-400 text-sm">
                    For private repositories, connect your {currentProviderConfig.displayName} account to authenticate.
                  </p>
                  <button
                    onClick={() => handleConnect(activeProvider)}
                    disabled={isConnecting}
                    className="mt-2 text-sm text-yellow-400 hover:text-yellow-300 underline"
                  >
                    {isConnecting ? 'Connecting...' : `Connect ${currentProviderConfig.displayName}`}
                  </button>
                </div>
              )}
            </>
          ) : (
            <>
              {/* Connected account or connect prompt */}
              {!currentProviderConnected ? (
                <div className="text-center py-12">
                  <div className={`w-16 h-16 mx-auto mb-4 rounded-full flex items-center justify-center ${currentProviderConfig.bgColor}`}>
                    <ProviderIcon provider={activeProvider} size={32} />
                  </div>
                  <h3 className="text-lg font-semibold text-[var(--text)] mb-2">
                    Connect {currentProviderConfig.displayName}
                  </h3>
                  <p className="text-gray-400 mb-4 max-w-sm mx-auto">
                    Connect your {currentProviderConfig.displayName} account to browse and import your repositories.
                  </p>
                  <button
                    onClick={() => handleConnect(activeProvider)}
                    disabled={isConnecting}
                    className="bg-blue-500 hover:bg-blue-600 disabled:bg-gray-600 text-white px-6 py-3 rounded-xl font-semibold transition-all flex items-center gap-2 mx-auto"
                  >
                    {isConnecting ? (
                      <>
                        <div className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full" />
                        Connecting...
                      </>
                    ) : (
                      <>
                        <ProviderIcon provider={activeProvider} size={20} />
                        Connect {currentProviderConfig.displayName}
                      </>
                    )}
                  </button>
                </div>
              ) : (
                <>
                  {/* Connected account info */}
                  <div className="flex items-center justify-between bg-white/5 rounded-xl px-4 py-3">
                    <div className="flex items-center gap-3">
                      <ProviderIcon provider={activeProvider} size={24} />
                      <div>
                        <p className="text-[var(--text)] font-medium">
                          {providerStatus[activeProvider].provider_username}
                        </p>
                        <p className="text-gray-400 text-sm">
                          {providerStatus[activeProvider].provider_email || 'Connected'}
                        </p>
                      </div>
                    </div>
                    <Check className="w-5 h-5 text-green-400" weight="bold" />
                  </div>

                  {/* Search */}
                  <div className="relative">
                    <MagnifyingGlass className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
                    <input
                      type="text"
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      className="w-full bg-white/5 border border-white/10 text-[var(--text)] pl-10 pr-4 py-3 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500 placeholder-gray-500"
                      placeholder="Search repositories..."
                      disabled={isImporting || isLoading}
                    />
                  </div>

                  {/* Repository List */}
                  <div className="space-y-2 max-h-80 overflow-y-auto">
                    {isLoading ? (
                      <div className="text-center py-8">
                        <div className="animate-spin h-8 w-8 mx-auto mb-2 border-2 border-blue-500 border-t-transparent rounded-full" />
                        <p className="text-gray-400">Loading repositories...</p>
                      </div>
                    ) : filteredRepos.length === 0 ? (
                      <div className="text-center py-8 text-gray-400">
                        {repositories.length === 0
                          ? 'No repositories found'
                          : 'No matching repositories'}
                      </div>
                    ) : (
                      filteredRepos.map((repo) => (
                        <button
                          key={repo.id}
                          onClick={() => setSelectedRepo(repo)}
                          disabled={isImporting}
                          className={`w-full text-left p-4 rounded-xl border transition-all ${
                            selectedRepo?.id === repo.id
                              ? 'bg-blue-500/20 border-blue-500'
                              : 'bg-white/5 border-white/10 hover:bg-white/10'
                          }`}
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2 mb-1">
                                <GitBranch className="w-4 h-4 text-gray-400 flex-shrink-0" />
                                <span className="font-semibold text-[var(--text)] truncate">
                                  {repo.full_name}
                                </span>
                                {repo.private ? (
                                  <span className="flex items-center gap-1 text-xs bg-yellow-500/20 text-yellow-400 px-2 py-0.5 rounded flex-shrink-0">
                                    <Lock className="w-3 h-3" />
                                    Private
                                  </span>
                                ) : (
                                  <span className="flex items-center gap-1 text-xs bg-green-500/20 text-green-400 px-2 py-0.5 rounded flex-shrink-0">
                                    <Globe className="w-3 h-3" />
                                    Public
                                  </span>
                                )}
                              </div>
                              {repo.description && (
                                <p className="text-sm text-gray-400 mb-2 line-clamp-2">
                                  {repo.description}
                                </p>
                              )}
                              <div className="flex items-center gap-3 text-xs text-gray-500">
                                <span>Branch: {repo.default_branch}</span>
                                {repo.updated_at && (
                                  <>
                                    <span>•</span>
                                    <span>
                                      Updated {new Date(repo.updated_at).toLocaleDateString()}
                                    </span>
                                  </>
                                )}
                                {repo.language && (
                                  <>
                                    <span>•</span>
                                    <span>{repo.language}</span>
                                  </>
                                )}
                              </div>
                            </div>
                          </div>
                        </button>
                      ))
                    )}
                  </div>
                </>
              )}
            </>
          )}
        </div>

        {/* Project Name Input for Browse Mode (only for new project mode) */}
        {isNewProjectMode && mode === 'browse' && selectedRepo && (
          <div className="pt-4">
            <label className="block text-sm font-medium text-[var(--text)] mb-2">
              Project Name
            </label>
            <input
              type="text"
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              className="w-full bg-white/5 border border-white/10 text-[var(--text)] px-4 py-3 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500 placeholder-gray-500"
              placeholder={selectedRepo.name}
              disabled={isImporting}
            />
            <p className="text-xs text-gray-500 mt-1">
              Leave empty to use "{selectedRepo.name}"
            </p>
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-3 pt-6 mt-6 border-t border-white/10">
          <button
            onClick={handleImport}
            disabled={
              isImporting ||
              (mode === 'url' && !repoUrl.trim()) ||
              (mode === 'browse' && !selectedRepo)
            }
            className="flex-1 bg-blue-500 hover:bg-blue-600 disabled:bg-gray-600 disabled:cursor-not-allowed text-white py-3 rounded-xl font-semibold transition-all flex items-center justify-center gap-2"
          >
            {isImporting ? (
              <>
                <div className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full" />
                {isNewProjectMode ? 'Creating Project...' : 'Importing...'}
              </>
            ) : (
              <>
                <Download className="w-5 h-5" />
                {isNewProjectMode ? 'Create Project' : 'Import Repository'}
              </>
            )}
          </button>
          <button
            onClick={handleClose}
            disabled={isImporting}
            className="flex-1 bg-white/5 border border-white/10 text-[var(--text)] py-3 rounded-xl font-semibold hover:bg-white/10 transition-all disabled:opacity-50"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

export default RepoImportModal;
