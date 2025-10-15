import { useState, useEffect } from 'react';
import {
  GitBranch,
  Download,
  CloudArrowUp,
  CloudArrowDown,
  GitCommit,
  Clock,
  Link as LinkIcon,
  LinkBreak,
  ArrowsClockwise,
  Warning,
  CheckCircle
} from '@phosphor-icons/react';
import { githubApi } from '../../lib/github-api';
import { gitApi } from '../../lib/git-api';
import { GitHubConnectModal, GitHubImportModal, GitCommitDialog } from '../modals';
import { GitHistoryViewer } from '../git/GitHistoryViewer';
import type { GitHubCredentialResponse, GitStatusResponse, GitRepositoryResponse } from '../../types/git';
import toast from 'react-hot-toast';

interface GitHubPanelProps {
  projectId: number;
}

type ActiveView = 'status' | 'history';

export function GitHubPanel({ projectId }: GitHubPanelProps) {
  // Connection state
  const [githubConnected, setGithubConnected] = useState(false);
  const [githubStatus, setGithubStatus] = useState<GitHubCredentialResponse | null>(null);
  const [repoConnected, setRepoConnected] = useState(false);
  const [repoInfo, setRepoInfo] = useState<GitRepositoryResponse | null>(null);

  // Git status
  const [gitStatus, setGitStatus] = useState<GitStatusResponse | null>(null);
  const [isLoadingStatus, setIsLoadingStatus] = useState(false);

  // Modal states
  const [showConnectModal, setShowConnectModal] = useState(false);
  const [showImportModal, setShowImportModal] = useState(false);
  const [showCommitDialog, setShowCommitDialog] = useState(false);

  // UI state
  const [activeView, setActiveView] = useState<ActiveView>('status');

  // Operation states
  const [isPushing, setIsPushing] = useState(false);
  const [isPulling, setIsPulling] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);

  useEffect(() => {
    checkGitHubConnection();
    checkRepositoryConnection();
  }, [projectId]);

  useEffect(() => {
    if (repoConnected) {
      loadGitStatus();
      const interval = setInterval(loadGitStatus, 30000); // Refresh every 30s
      return () => clearInterval(interval);
    }
  }, [repoConnected, projectId]);

  const checkGitHubConnection = async () => {
    try {
      const status = await githubApi.getStatus();
      setGithubConnected(status.connected);
      setGithubStatus(status);
    } catch (error) {
      setGithubConnected(false);
      setGithubStatus(null);
    }
  };

  const checkRepositoryConnection = async () => {
    try {
      const info = await gitApi.getRepositoryInfo(projectId);
      setRepoConnected(true);
      setRepoInfo(info);
    } catch (error) {
      setRepoConnected(false);
      setRepoInfo(null);
    }
  };

  const loadGitStatus = async () => {
    setIsLoadingStatus(true);
    try {
      const status = await gitApi.getStatus(projectId);
      setGitStatus(status);
    } catch (error) {
      console.error('Failed to load Git status:', error);
    } finally {
      setIsLoadingStatus(false);
    }
  };

  const handleDisconnectGitHub = async () => {
    if (!confirm('Disconnect GitHub account? You can reconnect anytime.')) return;

    try {
      await githubApi.disconnect();
      setGithubConnected(false);
      setGithubStatus(null);
      toast.success('GitHub disconnected');
    } catch (error) {
      toast.error('Failed to disconnect GitHub');
    }
  };

  const handleDisconnectRepo = async () => {
    if (!confirm('Disconnect repository? Local files will not be deleted.')) return;

    try {
      await gitApi.disconnect(projectId);
      setRepoConnected(false);
      setRepoInfo(null);
      setGitStatus(null);
      toast.success('Repository disconnected');
    } catch (error) {
      toast.error('Failed to disconnect repository');
    }
  };

  const handlePush = async () => {
    if (!gitStatus) return;

    setIsPushing(true);
    const loadingToast = toast.loading('Pushing to remote...');

    try {
      await gitApi.push(projectId, gitStatus.branch);
      toast.success('Pushed successfully!', { id: loadingToast });
      await loadGitStatus();
    } catch (error: any) {
      const errorMessage = error.response?.data?.detail || 'Failed to push';
      toast.error(errorMessage, { id: loadingToast });
    } finally {
      setIsPushing(false);
    }
  };

  const handlePull = async () => {
    if (!gitStatus) return;

    setIsPulling(true);
    const loadingToast = toast.loading('Pulling from remote...');

    try {
      const result = await gitApi.pull(projectId, gitStatus.branch);
      if (result.conflicts && result.conflicts.length > 0) {
        toast.error(`Conflicts detected in ${result.conflicts.length} file(s)`, { id: loadingToast });
      } else {
        toast.success(result.message || 'Pulled successfully!', { id: loadingToast });
      }
      await loadGitStatus();
    } catch (error: any) {
      const errorMessage = error.response?.data?.detail || 'Failed to pull';
      toast.error(errorMessage, { id: loadingToast });
    } finally {
      setIsPulling(false);
    }
  };

  const handleSync = async () => {
    if (!gitStatus) return;

    setIsSyncing(true);
    const loadingToast = toast.loading('Syncing with remote...');

    try {
      // Pull first, then push
      const pullResult = await gitApi.pull(projectId, gitStatus.branch);
      if (pullResult.conflicts && pullResult.conflicts.length > 0) {
        toast.error(`Conflicts detected. Resolve them before pushing.`, { id: loadingToast });
        return;
      }

      await gitApi.push(projectId, gitStatus.branch);
      toast.success('Synced successfully!', { id: loadingToast });
      await loadGitStatus();
    } catch (error: any) {
      const errorMessage = error.response?.data?.detail || 'Failed to sync';
      toast.error(errorMessage, { id: loadingToast });
    } finally {
      setIsSyncing(false);
    }
  };

  const getTotalChanges = () => {
    if (!gitStatus) return 0;
    return gitStatus.staged_count + gitStatus.unstaged_count + gitStatus.untracked_count;
  };

  const getSyncStatus = () => {
    if (!gitStatus) return null;
    if (gitStatus.ahead > 0 && gitStatus.behind > 0) {
      return { text: 'Diverged', color: 'text-yellow-400', icon: Warning };
    }
    if (gitStatus.ahead > 0) {
      return { text: `${gitStatus.ahead} ahead`, color: 'text-blue-400', icon: CloudArrowUp };
    }
    if (gitStatus.behind > 0) {
      return { text: `${gitStatus.behind} behind`, color: 'text-orange-400', icon: CloudArrowDown };
    }
    return { text: 'Up to date', color: 'text-green-400', icon: CheckCircle };
  };

  // Not connected to GitHub
  if (!githubConnected) {
    return (
      <>
        <div className="h-full flex flex-col items-center justify-center p-6">
          <div className="text-center max-w-md">
            <div className="w-20 h-20 bg-purple-500/20 rounded-2xl flex items-center justify-center mx-auto mb-6">
              <GitBranch className="w-10 h-10 text-purple-400" weight="fill" />
            </div>
            <h3 className="text-xl font-bold text-[var(--text)] mb-2">Connect to GitHub</h3>
            <p className="text-gray-400 mb-6">
              Link your GitHub account to enable version control, collaborate with others, and deploy your projects.
            </p>
            <button
              onClick={() => setShowConnectModal(true)}
              className="w-full py-3 bg-purple-500 hover:bg-purple-600 text-white rounded-xl font-semibold transition-all"
            >
              Connect GitHub Account
            </button>
          </div>
        </div>

        <GitHubConnectModal
          isOpen={showConnectModal}
          onClose={() => setShowConnectModal(false)}
          onSuccess={() => {
            checkGitHubConnection();
            checkRepositoryConnection();
          }}
        />
      </>
    );
  }

  // Connected to GitHub but no repository
  if (!repoConnected) {
    return (
      <>
        <div className="h-full overflow-y-auto">
          {/* GitHub Account Info */}
          <div className="p-6 border-b border-white/5">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 bg-purple-500/20 rounded-lg flex items-center justify-center">
                  <GitBranch className="w-5 h-5 text-purple-400" weight="fill" />
                </div>
                <div>
                  <div className="text-sm font-semibold text-[var(--text)]">
                    @{githubStatus?.github_username}
                  </div>
                  <div className="text-xs text-gray-500">GitHub Connected</div>
                </div>
              </div>
              <button
                onClick={handleDisconnectGitHub}
                className="text-xs text-red-400 hover:text-red-300 transition-colors"
              >
                Disconnect
              </button>
            </div>
          </div>

          {/* Repository Setup */}
          <div className="p-6">
            <h3 className="text-sm font-semibold text-gray-400 mb-4">SETUP REPOSITORY</h3>
            <div className="space-y-3">
              <button
                onClick={() => setShowImportModal(true)}
                className="w-full p-4 bg-white/5 hover:bg-white/8 border border-white/10 rounded-xl text-left transition-all group"
              >
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 bg-blue-500/20 rounded-lg flex items-center justify-center group-hover:bg-blue-500/30 transition-colors">
                    <Download className="w-5 h-5 text-blue-400" weight="fill" />
                  </div>
                  <div>
                    <div className="text-sm font-semibold text-white">Import from GitHub</div>
                    <div className="text-xs text-gray-500">Clone an existing repository</div>
                  </div>
                </div>
              </button>
            </div>
          </div>
        </div>

        <GitHubImportModal
          isOpen={showImportModal}
          onClose={() => setShowImportModal(false)}
          projectId={projectId}
          onSuccess={() => {
            checkRepositoryConnection();
          }}
        />
      </>
    );
  }

  // Repository connected
  const syncStatus = getSyncStatus();
  const totalChanges = getTotalChanges();

  return (
    <>
      <div className="h-full flex flex-col overflow-hidden">
        {/* GitHub Account Info */}
        <div className="p-4 border-b border-white/5 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 bg-purple-500/20 rounded-lg flex items-center justify-center">
              <GitBranch className="w-4 h-4 text-purple-400" weight="fill" />
            </div>
            <div>
              <div className="text-xs font-semibold text-[var(--text)]">@{githubStatus?.github_username}</div>
              <div className="text-xs text-gray-500">GitHub Connected</div>
            </div>
          </div>
        </div>

        {/* Repository Info */}
        <div className="p-4 border-b border-white/5">
          <div className="flex items-start justify-between mb-3">
            <div>
              <div className="text-sm font-semibold text-[var(--text)] mb-1">{repoInfo?.repo_name}</div>
              <div className="text-xs text-gray-500 font-mono">{repoInfo?.repo_url}</div>
            </div>
            <button
              onClick={handleDisconnectRepo}
              className="text-gray-400 hover:text-red-400 transition-colors p-1"
              title="Disconnect repository"
            >
              <LinkBreak className="w-4 h-4" />
            </button>
          </div>

          {/* Branch and Sync Status */}
          {gitStatus && (
            <div className="flex items-center gap-2">
              <div className="flex items-center gap-1 text-xs bg-white/5 px-2 py-1 rounded">
                <GitBranch className="w-3 h-3" />
                <span>{gitStatus.branch}</span>
              </div>
              {syncStatus && (
                <div className={`flex items-center gap-1 text-xs ${syncStatus.color}`}>
                  <syncStatus.icon className="w-3 h-3" />
                  <span>{syncStatus.text}</span>
                </div>
              )}
            </div>
          )}
        </div>

        {/* View Tabs */}
        <div className="flex border-b border-white/5">
          <button
            onClick={() => setActiveView('status')}
            className={`flex-1 py-2 text-sm font-medium transition-colors ${
              activeView === 'status'
                ? 'text-[var(--text)] border-b-2 border-blue-500'
                : 'text-gray-400 hover:text-[var(--text)]'
            }`}
          >
            Status
          </button>
          <button
            onClick={() => setActiveView('history')}
            className={`flex-1 py-2 text-sm font-medium transition-colors ${
              activeView === 'history'
                ? 'text-[var(--text)] border-b-2 border-blue-500'
                : 'text-gray-400 hover:text-[var(--text)]'
            }`}
          >
            History
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-hidden">
          {activeView === 'status' ? (
            <div className="h-full overflow-y-auto p-4 space-y-4">
              {/* Actions */}
              <div className="grid grid-cols-2 gap-2">
                <button
                  onClick={handlePull}
                  disabled={isPulling || isLoadingStatus}
                  className="flex items-center justify-center gap-2 py-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-sm font-medium transition-all disabled:opacity-50"
                >
                  <CloudArrowDown className="w-4 h-4" />
                  {isPulling ? 'Pulling...' : 'Pull'}
                </button>
                <button
                  onClick={handlePush}
                  disabled={isPushing || isLoadingStatus || totalChanges === 0}
                  className="flex items-center justify-center gap-2 py-2 bg-white/5 hover:bg-white/10 border border-white/10 rounded-lg text-sm font-medium transition-all disabled:opacity-50"
                >
                  <CloudArrowUp className="w-4 h-4" />
                  {isPushing ? 'Pushing...' : 'Push'}
                </button>
              </div>

              {/* Commit Button */}
              <button
                onClick={() => setShowCommitDialog(true)}
                disabled={isLoadingStatus || totalChanges === 0}
                className="w-full flex items-center justify-center gap-2 py-3 bg-green-500 hover:bg-green-600 disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded-xl font-semibold transition-all"
              >
                <GitCommit className="w-5 h-5" weight="fill" />
                Commit Changes ({totalChanges})
              </button>

              {/* Changes */}
              {gitStatus && (
                <div>
                  <h4 className="text-xs font-semibold text-gray-400 mb-2">CHANGES</h4>
                  {totalChanges === 0 ? (
                    <div className="text-sm text-gray-500 text-center py-4">No changes to commit</div>
                  ) : (
                    <div className="space-y-1">
                      {gitStatus.changes.slice(0, 10).map((change, index) => (
                        <div key={index} className="flex items-center gap-2 text-sm p-2 bg-white/5 rounded-lg">
                          <span className={`font-mono font-semibold ${
                            change.status === 'M' ? 'text-yellow-400' :
                            change.status === 'A' ? 'text-green-400' :
                            change.status === 'D' ? 'text-red-400' :
                            'text-gray-400'
                          }`}>
                            {change.status}
                          </span>
                          <span className="text-gray-300 truncate">{change.file_path}</span>
                        </div>
                      ))}
                      {gitStatus.changes.length > 10 && (
                        <div className="text-xs text-gray-500 text-center py-2">
                          +{gitStatus.changes.length - 10} more files
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}

              {/* Last Commit */}
              {gitStatus?.last_commit && (
                <div>
                  <h4 className="text-xs font-semibold text-gray-400 mb-2">LAST COMMIT</h4>
                  <div className="p-3 bg-white/5 rounded-lg">
                    <div className="text-sm text-[var(--text)] mb-1">{gitStatus.last_commit.message}</div>
                    <div className="text-xs text-gray-500">
                      {gitStatus.last_commit.author} • {gitStatus.last_commit.sha.substring(0, 7)}
                    </div>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="h-full p-4">
              <GitHistoryViewer projectId={projectId} />
            </div>
          )}
        </div>
      </div>

      <GitCommitDialog
        isOpen={showCommitDialog}
        onClose={() => setShowCommitDialog(false)}
        projectId={projectId}
        changes={gitStatus?.changes || []}
        onSuccess={() => {
          loadGitStatus();
        }}
      />
    </>
  );
}
