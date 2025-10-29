import { useState, useEffect } from 'react';
import { Download, X, GitBranch, MagnifyingGlass } from '@phosphor-icons/react';
import { githubApi } from '../../lib/github-api';
import { gitApi } from '../../lib/git-api';
import type { GitHubRepository } from '../../types/git';
import toast from 'react-hot-toast';

interface GitHubImportModalProps {
  isOpen: boolean;
  onClose: () => void;
  projectId: number;
  onSuccess: () => void;
}

type ImportMode = 'url' | 'list';

export function GitHubImportModal({ isOpen, onClose, projectId, onSuccess }: GitHubImportModalProps) {
  const [mode, setMode] = useState<ImportMode>('url');
  const [repoUrl, setRepoUrl] = useState('');
  const [branch, setBranch] = useState('main');
  const [repositories, setRepositories] = useState<GitHubRepository[]>([]);
  const [filteredRepos, setFilteredRepos] = useState<GitHubRepository[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedRepo, setSelectedRepo] = useState<GitHubRepository | null>(null);
  const [isImporting, setIsImporting] = useState(false);
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    if (isOpen && mode === 'list') {
      loadRepositories();
    }
  }, [isOpen, mode]);

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

  if (!isOpen) return null;

  const loadRepositories = async () => {
    setIsLoading(true);
    try {
      const repos = await githubApi.listRepositories();
      setRepositories(repos);
      setFilteredRepos(repos);
    } catch (error: any) {
      toast.error('Failed to load repositories. Make sure you connected GitHub first.');
      setMode('url');
    } finally {
      setIsLoading(false);
    }
  };

  const handleImport = async () => {
    let finalRepoUrl = repoUrl;
    let finalBranch = branch;

    if (mode === 'list') {
      if (!selectedRepo) {
        toast.error('Please select a repository');
        return;
      }
      finalRepoUrl = selectedRepo.clone_url;
      finalBranch = selectedRepo.default_branch;
    } else {
      if (!finalRepoUrl.trim()) {
        toast.error('Please enter a repository URL');
        return;
      }

      // Validate URL format
      if (!finalRepoUrl.includes('github.com')) {
        toast.error('Please enter a valid GitHub repository URL');
        return;
      }
    }

    setIsImporting(true);
    const loadingToast = toast.loading('Cloning repository...');

    try {
      await gitApi.clone(projectId, finalRepoUrl, finalBranch);
      toast.success('Repository cloned successfully!', { id: loadingToast });
      setRepoUrl('');
      setBranch('main');
      setSelectedRepo(null);
      onSuccess();
      onClose();
    } catch (error: any) {
      const errorMessage = error.response?.data?.detail || 'Failed to clone repository';
      toast.error(errorMessage, { id: loadingToast });
    } finally {
      setIsImporting(false);
    }
  };

  const handleClose = () => {
    if (!isImporting) {
      setRepoUrl('');
      setBranch('main');
      setSelectedRepo(null);
      setSearchQuery('');
      onClose();
    }
  };

  return (
    <div
      className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50"
      onClick={handleClose}
    >
      <div
        className="bg-[var(--surface)] p-8 rounded-3xl w-full max-w-2xl shadow-2xl border border-white/10 max-h-[90vh] overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 bg-blue-500/20 rounded-xl flex items-center justify-center">
              <Download className="w-6 h-6 text-blue-400" weight="fill" />
            </div>
            <div>
              <h2 className="font-heading text-2xl font-bold text-[var(--text)]">Import from GitHub</h2>
              <p className="text-sm text-gray-500">Clone an existing repository</p>
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

        {/* Mode Selector */}
        <div className="flex gap-2 mb-6">
          <button
            onClick={() => setMode('url')}
            className={`flex-1 py-2 px-4 rounded-lg font-medium transition-all ${
              mode === 'url'
                ? 'bg-blue-500 text-white'
                : 'bg-white/5 text-gray-400 hover:bg-white/10'
            }`}
            disabled={isImporting}
          >
            Enter URL
          </button>
          <button
            onClick={() => setMode('list')}
            className={`flex-1 py-2 px-4 rounded-lg font-medium transition-all ${
              mode === 'list'
                ? 'bg-blue-500 text-white'
                : 'bg-white/5 text-gray-400 hover:bg-white/10'
            }`}
            disabled={isImporting}
          >
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
                  placeholder="https://github.com/username/repository"
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
            </>
          ) : (
            <>
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
              <div className="space-y-2 max-h-96 overflow-y-auto">
                {isLoading ? (
                  <div className="text-center py-8">
                    <div className="animate-spin h-8 w-8 mx-auto mb-2 border-2 border-blue-500 border-t-transparent rounded-full" />
                    <p className="text-gray-400">Loading repositories...</p>
                  </div>
                ) : filteredRepos.length === 0 ? (
                  <div className="text-center py-8 text-gray-400">
                    {repositories.length === 0 ? 'No repositories found' : 'No matching repositories'}
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
                        <div className="flex-1">
                          <div className="flex items-center gap-2 mb-1">
                            <GitBranch className="w-4 h-4 text-gray-400" />
                            <span className="font-semibold text-[var(--text)]">{repo.full_name}</span>
                            {repo.private && (
                              <span className="text-xs bg-yellow-500/20 text-yellow-400 px-2 py-0.5 rounded">
                                Private
                              </span>
                            )}
                          </div>
                          {repo.description && (
                            <p className="text-sm text-gray-400 mb-2">{repo.description}</p>
                          )}
                          <div className="flex items-center gap-3 text-xs text-gray-500">
                            <span>Branch: {repo.default_branch}</span>
                            <span>•</span>
                            <span>Updated {new Date(repo.updated_at).toLocaleDateString()}</span>
                          </div>
                        </div>
                      </div>
                    </button>
                  ))
                )}
              </div>
            </>
          )}
        </div>

        {/* Actions */}
        <div className="flex gap-3 pt-6 mt-6 border-t border-white/10">
          <button
            onClick={handleImport}
            disabled={isImporting || (mode === 'url' && !repoUrl.trim()) || (mode === 'list' && !selectedRepo)}
            className="flex-1 bg-blue-500 hover:bg-blue-600 disabled:bg-gray-600 disabled:cursor-not-allowed text-white py-3 rounded-xl font-semibold transition-all"
          >
            {isImporting ? 'Importing...' : 'Import Repository'}
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
