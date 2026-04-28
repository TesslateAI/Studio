import { useState, useEffect } from 'react';
import {
  GitBranch,
  Download,
  CloudArrowUp,
  CloudArrowDown,
  GitCommit,
  LinkBreak,
  Warning,
  CheckCircle,
} from '@phosphor-icons/react';
import { githubApi } from '../../lib/github-api';
import { gitApi } from '../../lib/git-api';
import { GitHubConnectModal, GitHubImportModal, GitCommitDialog, ConfirmDialog } from '../modals';
import { GitHistoryViewer } from '../git/GitHistoryViewer';
import type {
  GitHubCredentialResponse,
  GitStatusResponse,
  GitRepositoryResponse,
} from '../../types/git';
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
  const [showDisconnectGithubDialog, setShowDisconnectGithubDialog] = useState(false);
  const [showDisconnectRepoDialog, setShowDisconnectRepoDialog] = useState(false);

  // UI state
  const [activeView, setActiveView] = useState<ActiveView>('status');

  // Operation states
  const [isPushing, setIsPushing] = useState(false);
  const [isPulling, setIsPulling] = useState(false);

  // Branch management
  const [showBranchMenu, setShowBranchMenu] = useState(false);
  const [branches, setBranches] = useState<Array<{ name: string }>>([]);
  const [newBranchName, setNewBranchName] = useState('');
  const [showNewBranchInput, setShowNewBranchInput] = useState(false);
  const [isSwitchingBranch, setIsSwitchingBranch] = useState(false);

  useEffect(() => {
    checkGitHubConnection();
    checkRepositoryConnection();
  }, [projectId]);

  useEffect(() => {
    if (repoConnected) {
      loadGitStatus();
      loadBranches();
      const interval = setInterval(loadGitStatus, 30000);
      return () => clearInterval(interval);
    }
  }, [repoConnected, projectId]);

  const checkGitHubConnection = async () => {
    try {
      const status = await githubApi.getStatus();
      setGithubConnected(status.connected);
      setGithubStatus(status);
    } catch {
      setGithubConnected(false);
      setGithubStatus(null);
    }
  };

  const checkRepositoryConnection = async () => {
    try {
      const info = await gitApi.getRepositoryInfo(projectId);
      setRepoConnected(!!info);
      setRepoInfo(info);
    } catch {
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

  const handleDisconnectGitHub = () => {
    setShowDisconnectGithubDialog(true);
  };

  const confirmDisconnectGitHub = async () => {
    setShowDisconnectGithubDialog(false);
    try {
      await githubApi.disconnect();
      setGithubConnected(false);
      setGithubStatus(null);
      toast.success('GitHub disconnected');
    } catch {
      toast.error('Failed to disconnect GitHub');
    }
  };

  const handleDisconnectRepo = () => {
    setShowDisconnectRepoDialog(true);
  };

  const confirmDisconnectRepo = async () => {
    setShowDisconnectRepoDialog(false);
    try {
      await gitApi.disconnect(projectId);
      setRepoConnected(false);
      setRepoInfo(null);
      setGitStatus(null);
      toast.success('Repository disconnected');
    } catch {
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
    } catch (error: unknown) {
      const axiosError = error as { response?: { data?: { detail?: string } } };
      const detail = axiosError.response?.data?.detail;
      const errorMessage = typeof detail === 'string' ? detail : 'Failed to push';
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
        toast.error(`Conflicts detected in ${result.conflicts.length} file(s)`, {
          id: loadingToast,
        });
      } else {
        toast.success(result.message || 'Pulled successfully!', { id: loadingToast });
      }
      await loadGitStatus();
    } catch (error: unknown) {
      const axiosError = error as { response?: { data?: { detail?: string } } };
      const detail = axiosError.response?.data?.detail;
      const errorMessage = typeof detail === 'string' ? detail : 'Failed to pull';
      toast.error(errorMessage, { id: loadingToast });
    } finally {
      setIsPulling(false);
    }
  };

  const getTotalChanges = () => {
    if (!gitStatus) return 0;
    return gitStatus.staged_count + gitStatus.unstaged_count + gitStatus.untracked_count;
  };

  const loadBranches = async () => {
    try {
      const branchesData = await gitApi.getBranches(projectId);
      setBranches(branchesData.branches);
    } catch (error) {
      console.error('Failed to load branches:', error);
    }
  };

  const handleSwitchBranch = async (branchName: string) => {
    if (branchName === gitStatus?.branch) {
      setShowBranchMenu(false);
      return;
    }
    setIsSwitchingBranch(true);
    const loadingToast = toast.loading(`Switching to ${branchName}...`);
    try {
      await gitApi.switchBranch(projectId, branchName);
      toast.success(`Switched to ${branchName}`, { id: loadingToast });
      setShowBranchMenu(false);
      await loadGitStatus();
    } catch (error: unknown) {
      const axiosError = error as { response?: { data?: { detail?: string } } };
      const detail = axiosError.response?.data?.detail;
      const errorMessage = typeof detail === 'string' ? detail : 'Failed to switch branch';
      toast.error(errorMessage, { id: loadingToast });
    } finally {
      setIsSwitchingBranch(false);
    }
  };

  const handleCreateBranch = async () => {
    if (!newBranchName.trim()) {
      toast.error('Branch name is required');
      return;
    }
    const loadingToast = toast.loading('Creating new branch...');
    try {
      await gitApi.createBranch(projectId, newBranchName.trim(), true);
      toast.success(`Created and switched to ${newBranchName}`, { id: loadingToast });
      setNewBranchName('');
      setShowNewBranchInput(false);
      setShowBranchMenu(false);
      await loadGitStatus();
      await loadBranches();
    } catch (error: unknown) {
      const axiosError = error as { response?: { data?: { detail?: string } } };
      const detail = axiosError.response?.data?.detail;
      const errorMessage = typeof detail === 'string' ? detail : 'Failed to create branch';
      toast.error(errorMessage, { id: loadingToast });
    }
  };

  const getSyncStatus = () => {
    if (!gitStatus) return null;
    if (gitStatus.ahead > 0 && gitStatus.behind > 0) {
      return { text: 'Diverged', color: 'var(--status-warning)', icon: Warning };
    }
    if (gitStatus.ahead > 0) {
      return { text: `${gitStatus.ahead} ahead`, color: 'var(--text-muted)', icon: CloudArrowUp };
    }
    if (gitStatus.behind > 0) {
      return { text: `${gitStatus.behind} behind`, color: 'var(--status-warning)', icon: CloudArrowDown };
    }
    return { text: 'Up to date', color: 'var(--status-success)', icon: CheckCircle };
  };

  // Not connected to GitHub
  if (!githubConnected) {
    return (
      <>
        <div className="h-full flex items-center justify-center p-8">
          <div className="text-center max-w-md">
            <div className="mb-6 flex justify-center">
              <div className="w-16 h-16 rounded-[var(--radius)] bg-[var(--surface-hover)] border border-[var(--border)] flex items-center justify-center">
                <GitBranch size={28} className="text-[var(--text-muted)]" weight="bold" />
              </div>
            </div>
            <h3 className="text-base font-semibold text-[var(--text)] mb-2">Connect to GitHub</h3>
            <p className="text-xs text-[var(--text-muted)] leading-relaxed">
              Link your GitHub account to enable version control, collaborate with others, and
              deploy your projects.
            </p>
            <div className="mt-6 pt-6 border-t border-[var(--border)]">
              <button onClick={() => setShowConnectModal(true)} className="btn btn-filled w-full">
                Connect GitHub Account
              </button>
            </div>
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
          <div className="p-4 border-b border-[var(--border)]">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 bg-[var(--surface-hover)] border border-[var(--border)] rounded-[var(--radius-medium)] flex items-center justify-center">
                  <GitBranch size={14} className="text-[var(--text-muted)]" weight="bold" />
                </div>
                <div>
                  <div className="text-xs font-semibold text-[var(--text)]">
                    @{githubStatus?.github_username}
                  </div>
                  <div className="text-[10px] text-[var(--text-subtle)]">GitHub Connected</div>
                </div>
              </div>
              <button onClick={handleDisconnectGitHub} className="btn btn-sm btn-danger">
                Disconnect
              </button>
            </div>
          </div>

          {/* Repository Setup */}
          <div className="p-4">
            <div className="text-[10px] font-medium uppercase tracking-wider text-[var(--text-subtle)] mb-2">
              Setup Repository
            </div>
            <button
              onClick={() => setShowImportModal(true)}
              className="w-full p-3 bg-[var(--surface-hover)] hover:bg-[var(--surface)] border border-[var(--border)] hover:border-[var(--border-hover)] rounded-[var(--radius)] text-left transition-colors group"
            >
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 bg-[var(--surface)] border border-[var(--border)] rounded-[var(--radius-medium)] flex items-center justify-center">
                  <Download size={14} className="text-[var(--text-muted)]" weight="bold" />
                </div>
                <div>
                  <div className="text-xs font-semibold text-[var(--text)]">Import from GitHub</div>
                  <div className="text-[10px] text-[var(--text-subtle)]">
                    Clone an existing repository
                  </div>
                </div>
              </div>
            </button>
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
    <div className="h-full overflow-y-auto">
      {/* GitHub Account Info */}
      <div className="px-4 py-3 border-b border-[var(--border)] flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 bg-[var(--surface-hover)] border border-[var(--border)] rounded-[var(--radius-small)] flex items-center justify-center">
            <GitBranch size={12} className="text-[var(--text-muted)]" weight="bold" />
          </div>
          <div>
            <div className="text-xs font-semibold text-[var(--text)]">
              @{githubStatus?.github_username}
            </div>
            <div className="text-[10px] text-[var(--text-subtle)]">GitHub Connected</div>
          </div>
        </div>
      </div>

      {/* Repository Info */}
      <div className="px-4 py-3 border-b border-[var(--border)]">
        <div className="flex items-start justify-between mb-3">
          <div className="min-w-0 flex-1 mr-2">
            <div className="text-xs font-semibold text-[var(--text)] mb-0.5 truncate">
              {repoInfo?.repo_name}
            </div>
            <div className="text-[10px] text-[var(--text-subtle)] font-mono truncate">
              {repoInfo?.repo_url}
            </div>
          </div>
          <button
            onClick={handleDisconnectRepo}
            className="text-[var(--text-subtle)] hover:text-[var(--status-error)] transition-colors p-1 shrink-0"
            title="Disconnect repository"
          >
            <LinkBreak size={14} weight="bold" />
          </button>
        </div>

        {/* Branch and Sync Status */}
        {gitStatus && (
          <div className="flex items-center gap-2">
            {/* Branch Selector */}
            <div className="relative">
              <button
                onClick={() => setShowBranchMenu(!showBranchMenu)}
                className="flex items-center gap-1.5 text-[11px] bg-[var(--surface-hover)] hover:bg-[var(--surface)] border border-[var(--border)] hover:border-[var(--border-hover)] px-2 py-1 rounded-[var(--radius-small)] transition-colors text-[var(--text)]"
              >
                <GitBranch size={11} weight="bold" />
                <span>{gitStatus.branch}</span>
                <span className="text-[var(--text-subtle)]">▾</span>
              </button>

              {/* Branch Dropdown Menu */}
              {showBranchMenu && (
                <div className="absolute top-full left-0 mt-1 w-64 bg-[var(--surface)] border border-[var(--border-hover)] rounded-[var(--radius-medium)] z-50 max-h-64 overflow-hidden flex flex-col p-1.5">
                  {/* Current Branch */}
                  <div className="p-2 border-b border-[var(--border)] mb-1">
                    <div className="text-[10px] uppercase tracking-wide text-[var(--text-subtle)] mb-0.5">
                      Current Branch
                    </div>
                    <div className="text-xs font-semibold text-[var(--text)]">
                      {gitStatus.branch}
                    </div>
                  </div>

                  {/* Branches List */}
                  <div className="overflow-y-auto flex-1">
                    {branches.map((branch) => (
                      <button
                        key={branch.name}
                        onClick={() => handleSwitchBranch(branch.name)}
                        disabled={isSwitchingBranch || branch.name === gitStatus.branch}
                        className={`w-full text-left px-2.5 py-1.5 text-xs rounded-[var(--radius-small)] transition-colors ${
                          branch.name === gitStatus.branch
                            ? 'bg-[var(--surface-hover)] text-[var(--text)] cursor-default'
                            : 'hover:bg-[var(--surface-hover)] text-[var(--text-muted)] hover:text-[var(--text)]'
                        } ${isSwitchingBranch ? 'opacity-50' : ''}`}
                      >
                        <div className="flex items-center gap-2">
                          <GitBranch size={11} weight="bold" />
                          <span>{branch.name}</span>
                          {branch.name === gitStatus.branch && (
                            <span className="ml-auto text-[10px]">✓</span>
                          )}
                        </div>
                      </button>
                    ))}
                  </div>

                  {/* Create New Branch */}
                  <div className="p-1.5 border-t border-[var(--border)] mt-1">
                    {!showNewBranchInput ? (
                      <button
                        onClick={() => setShowNewBranchInput(true)}
                        className="w-full text-left px-2.5 py-1.5 text-xs text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface-hover)] rounded-[var(--radius-small)] transition-colors"
                      >
                        + Create new branch
                      </button>
                    ) : (
                      <div className="space-y-2">
                        <input
                          type="text"
                          value={newBranchName}
                          onChange={(e) => setNewBranchName(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') handleCreateBranch();
                            if (e.key === 'Escape') {
                              setShowNewBranchInput(false);
                              setNewBranchName('');
                            }
                          }}
                          placeholder="new-branch-name"
                          className="w-full px-2 py-1 bg-[var(--bg)] border border-[var(--border)] text-[var(--text)] rounded-[var(--radius-small)] text-xs focus:outline-none focus:border-[var(--border-hover)]"
                          autoFocus
                        />
                        <div className="flex gap-1">
                          <button onClick={handleCreateBranch} className="btn btn-sm btn-primary flex-1">
                            Create
                          </button>
                          <button
                            onClick={() => {
                              setShowNewBranchInput(false);
                              setNewBranchName('');
                            }}
                            className="btn btn-sm flex-1"
                          >
                            Cancel
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>

            {syncStatus && (
              <div
                className="flex items-center gap-1 text-[11px]"
                style={{ color: syncStatus.color }}
              >
                <syncStatus.icon size={11} weight="bold" />
                <span>{syncStatus.text}</span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* View Tabs */}
      <div className="flex border-b border-[var(--border)]">
        <button
          onClick={() => setActiveView('status')}
          className={`flex-1 py-2 text-[11px] font-medium transition-colors ${
            activeView === 'status'
              ? 'text-[var(--text)] border-b-2 border-[var(--primary)]'
              : 'text-[var(--text-muted)] hover:text-[var(--text)]'
          }`}
        >
          Status
        </button>
        <button
          onClick={() => setActiveView('history')}
          className={`flex-1 py-2 text-[11px] font-medium transition-colors ${
            activeView === 'history'
              ? 'text-[var(--text)] border-b-2 border-[var(--primary)]'
              : 'text-[var(--text-muted)] hover:text-[var(--text)]'
          }`}
        >
          History
        </button>
      </div>

      {/* Content */}
      {activeView === 'status' ? (
        <div className="p-4 space-y-3">
          {/* Actions */}
          <div className="grid grid-cols-2 gap-2">
            <button
              onClick={handlePull}
              disabled={isPulling || isLoadingStatus}
              className="btn flex items-center justify-center gap-1.5"
              style={isPulling || isLoadingStatus ? { opacity: 0.4, cursor: 'not-allowed' } : undefined}
            >
              <CloudArrowDown size={13} weight="bold" />
              {isPulling ? 'Pulling…' : 'Pull'}
            </button>
            <button
              onClick={handlePush}
              disabled={isPushing || isLoadingStatus}
              className="btn flex items-center justify-center gap-1.5"
              style={isPushing || isLoadingStatus ? { opacity: 0.4, cursor: 'not-allowed' } : undefined}
            >
              <CloudArrowUp size={13} weight="bold" />
              {isPushing ? 'Pushing…' : 'Push'}
            </button>
          </div>

          {/* Commit Button */}
          <button
            onClick={() => setShowCommitDialog(true)}
            disabled={isLoadingStatus || totalChanges === 0}
            className="btn btn-filled w-full flex items-center justify-center gap-1.5"
            style={
              isLoadingStatus || totalChanges === 0
                ? { opacity: 0.4, cursor: 'not-allowed' }
                : undefined
            }
          >
            <GitCommit size={13} weight="bold" />
            Commit Changes ({totalChanges})
          </button>

          {/* Changes */}
          {gitStatus && (
            <div>
              <div className="text-[10px] font-medium uppercase tracking-wider text-[var(--text-subtle)] mb-2">
                Changes
              </div>
              {totalChanges === 0 ? (
                <div className="text-xs text-[var(--text-subtle)] text-center py-4">
                  No changes to commit
                </div>
              ) : (
                <div className="space-y-1">
                  {gitStatus.changes.slice(0, 10).map((change, index) => {
                    const statusColor =
                      change.status === 'M'
                        ? 'var(--status-warning)'
                        : change.status === 'A'
                          ? 'var(--status-success)'
                          : change.status === 'D'
                            ? 'var(--status-error)'
                            : 'var(--text-subtle)';
                    return (
                      <div
                        key={index}
                        className="flex items-center gap-2 text-xs px-2 py-1.5 bg-[var(--surface-hover)] border border-[var(--border)] rounded-[var(--radius-small)]"
                      >
                        <span
                          className="font-mono font-semibold shrink-0 text-[10px] w-3 text-center"
                          style={{ color: statusColor }}
                        >
                          {change.status}
                        </span>
                        <span className="text-[var(--text-muted)] truncate">
                          {change.file_path}
                        </span>
                      </div>
                    );
                  })}
                  {gitStatus.changes.length > 10 && (
                    <div className="text-[10px] text-[var(--text-subtle)] text-center py-2">
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
              <div className="text-[10px] font-medium uppercase tracking-wider text-[var(--text-subtle)] mb-2">
                Last Commit
              </div>
              <div className="px-3 py-2 bg-[var(--surface-hover)] border border-[var(--border)] rounded-[var(--radius-small)]">
                <div className="text-xs text-[var(--text)] mb-1">
                  {gitStatus.last_commit.message}
                </div>
                <div className="text-[10px] text-[var(--text-subtle)]">
                  {gitStatus.last_commit.author} • {gitStatus.last_commit.sha.substring(0, 7)}
                </div>
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="p-4">
          <GitHistoryViewer projectId={projectId} />
        </div>
      )}

      <GitCommitDialog
        isOpen={showCommitDialog}
        onClose={() => setShowCommitDialog(false)}
        projectId={projectId}
        changes={gitStatus?.changes || []}
        onSuccess={() => {
          loadGitStatus();
        }}
      />

      <ConfirmDialog
        isOpen={showDisconnectGithubDialog}
        onClose={() => setShowDisconnectGithubDialog(false)}
        onConfirm={confirmDisconnectGitHub}
        title="Disconnect GitHub"
        message="Are you sure you want to disconnect your GitHub account? You can reconnect anytime."
        confirmText="Disconnect"
        cancelText="Cancel"
        variant="warning"
      />

      <ConfirmDialog
        isOpen={showDisconnectRepoDialog}
        onClose={() => setShowDisconnectRepoDialog(false)}
        onConfirm={confirmDisconnectRepo}
        title="Disconnect Repository"
        message="Are you sure you want to disconnect this repository? Your local files will not be deleted."
        confirmText="Disconnect"
        cancelText="Cancel"
        variant="warning"
      />
    </div>
  );
}
