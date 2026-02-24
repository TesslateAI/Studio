import { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Download, X } from '@phosphor-icons/react';
import { gitProvidersApi } from '../../../lib/git-providers-api';
import { gitApi } from '../../../lib/git-api';
import { ConfirmDialog } from '../ConfirmDialog';
import type { GitProvider, AllProvidersStatus, GitProviderRepository } from '../../../types/git-providers';
import toast from 'react-hot-toast';

import { useRepoResolver } from './useRepoResolver';
import { RepoUrlInput } from './RepoUrlInput';
import { RepoInfoCard } from './RepoInfoCard';
import { BranchSelector } from './BranchSelector';
import { BrowseReposSection } from './BrowseReposSection';
import { ConnectProviderInline } from './ConnectProviderInline';

interface RepoImportModalProps {
  isOpen: boolean;
  onClose: () => void;
  projectId?: number;
  onSuccess?: () => void;
  onCreateProject?: (provider: GitProvider, repoUrl: string, branch: string, projectName: string) => Promise<void>;
}

export function RepoImportModal({ isOpen, onClose, projectId, onSuccess, onCreateProject }: RepoImportModalProps) {
  const [repoUrl, setRepoUrl] = useState('');
  const [projectName, setProjectName] = useState('');
  const [isImporting, setIsImporting] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [providerStatus, setProviderStatus] = useState<AllProvidersStatus>({
    github: { connected: false },
    gitlab: { connected: false },
    bitbucket: { connected: false },
  });

  const isNewProjectMode = !projectId && !!onCreateProject;

  const { state: resolver, resolveUrl, selectRepo, selectBranch, retryAfterAuth, reset } =
    useRepoResolver(providerStatus);

  // Load provider status on open
  useEffect(() => {
    if (isOpen) {
      gitProvidersApi.getAllStatus().then(setProviderStatus).catch(console.error);
    }
  }, [isOpen]);

  // Resolve URL when it changes
  useEffect(() => {
    resolveUrl(repoUrl);
  }, [repoUrl, resolveUrl]);

  // Auto-fill project name from resolved repo
  useEffect(() => {
    if (resolver.repo && !projectName.trim()) {
      setProjectName(resolver.repo.name);
    }
  }, [resolver.repo]);

  const handleBrowseSelectRepo = useCallback(
    (repo: GitProviderRepository) => {
      setRepoUrl(repo.clone_url);
      setProjectName(repo.name);
      selectRepo(repo);
    },
    [selectRepo]
  );

  const handleClose = useCallback(() => {
    if (!isImporting) {
      setRepoUrl('');
      setProjectName('');
      reset();
      onClose();
    }
  }, [isImporting, onClose, reset]);

  const handleImportClick = () => {
    const finalRepoUrl = resolver.repo?.clone_url || repoUrl.trim();

    if (!finalRepoUrl) {
      toast.error('Please enter a repository URL');
      return;
    }

    if (isNewProjectMode) {
      let finalProjectName = projectName.trim();
      if (!finalProjectName) {
        const urlParts = finalRepoUrl.replace(/\.git$/, '').split('/');
        finalProjectName = urlParts[urlParts.length - 1] || 'imported-project';
      }
      if (!finalProjectName) {
        toast.error('Please enter a project name');
        return;
      }
    }

    // For existing projects, show confirmation before overriding files
    if (!isNewProjectMode) {
      setShowConfirm(true);
      return;
    }

    performImport();
  };

  const performImport = async () => {
    setShowConfirm(false);

    const finalRepoUrl = resolver.repo?.clone_url || repoUrl.trim();
    const finalBranch = resolver.selectedBranch?.name || 'main';
    const provider = resolver.provider || 'github';

    let finalProjectName = projectName.trim();
    if (!finalProjectName && isNewProjectMode) {
      const urlParts = finalRepoUrl.replace(/\.git$/, '').split('/');
      finalProjectName = urlParts[urlParts.length - 1] || 'imported-project';
    }

    setIsImporting(true);

    try {
      if (isNewProjectMode && onCreateProject) {
        await onCreateProject(provider, finalRepoUrl, finalBranch, finalProjectName);
        handleClose();
      } else if (projectId && onSuccess) {
        const loadingToast = toast.loading('Cloning repository...');
        try {
          await gitApi.clone(projectId, finalRepoUrl, finalBranch);
          toast.success('Repository cloned successfully!', { id: loadingToast });
          handleClose();
          onSuccess();
        } catch (error: unknown) {
          const errorMessage =
            (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
            'Failed to clone repository';
          toast.error(errorMessage, { id: loadingToast });
        }
      }
    } finally {
      setIsImporting(false);
    }
  };

  const canImport =
    repoUrl.trim().length > 0 &&
    !isImporting &&
    resolver.status !== 'detecting' &&
    resolver.status !== 'fetching-repo';

  if (!isOpen && !showConfirm) return null;

  return (
    <>
    <AnimatePresence>
      {isOpen && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
          className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-end sm:items-center justify-center p-0 sm:p-4 z-50"
          onClick={handleClose}
        >
          <motion.div
            initial={{ scale: 0.95, y: 20, opacity: 0 }}
            animate={{ scale: 1, y: 0, opacity: 1 }}
            exit={{ scale: 0.95, y: 20, opacity: 0 }}
            transition={{ type: 'spring', damping: 25, stiffness: 300 }}
            className="bg-[var(--surface)] p-4 sm:p-6 md:p-8 rounded-t-3xl sm:rounded-3xl w-full sm:max-w-2xl shadow-2xl border border-white/10 max-h-[85vh] sm:max-h-[90vh] overflow-hidden flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Drag handle (mobile) */}
            <div className="w-10 h-1 bg-white/20 rounded-full mx-auto mb-4 sm:hidden" />

            {/* Header */}
            <div className="flex items-center justify-between mb-5 sm:mb-6">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 sm:w-12 sm:h-12 bg-[rgba(var(--primary-rgb),0.15)] rounded-xl flex items-center justify-center">
                  <Download className="w-5 h-5 sm:w-6 sm:h-6 text-[var(--primary)]" weight="fill" />
                </div>
                <div>
                  <h2 className="font-heading text-lg sm:text-xl font-bold text-[var(--text)]">
                    {isNewProjectMode ? 'Import Repository' : 'Import Repository'}
                  </h2>
                  <p className="text-xs sm:text-sm text-gray-500">
                    Paste a URL and we'll handle the rest
                  </p>
                </div>
              </div>
              {!isImporting && (
                <button
                  onClick={handleClose}
                  className="text-gray-400 hover:text-white transition-colors p-2 min-h-[44px] min-w-[44px] flex items-center justify-center"
                >
                  <X className="w-5 h-5" />
                </button>
              )}
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto space-y-4 min-h-0">
              {/* URL Input */}
              <RepoUrlInput
                value={repoUrl}
                onChange={setRepoUrl}
                provider={resolver.provider}
                status={resolver.status}
                disabled={isImporting}
                autoFocus
              />

              {/* Repo Info Card */}
              <AnimatePresence mode="wait">
                {resolver.repo && (
                  <RepoInfoCard key={resolver.repo.full_name} repo={resolver.repo} />
                )}
              </AnimatePresence>

              {/* Connect Provider Inline (when auth needed) */}
              <AnimatePresence mode="wait">
                {resolver.needsAuth && resolver.provider && (
                  <ConnectProviderInline
                    key={resolver.provider}
                    provider={resolver.provider}
                    onConnected={retryAfterAuth}
                    onProviderStatusChange={setProviderStatus}
                  />
                )}
              </AnimatePresence>

              {/* Error message (non-auth errors) */}
              <AnimatePresence mode="wait">
                {resolver.status === 'error' && !resolver.needsAuth && resolver.error && (
                  <motion.p
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    className="text-sm text-red-400"
                  >
                    {resolver.error}
                  </motion.p>
                )}
              </AnimatePresence>

              {/* Branch Selector */}
              <AnimatePresence mode="wait">
                {(resolver.status === 'resolved' || resolver.status === 'fetching-branches') && (
                  <motion.div
                    initial={{ opacity: 0, y: -4 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -4 }}
                    transition={{ duration: 0.15 }}
                  >
                    <BranchSelector
                      branches={resolver.branches}
                      selected={resolver.selectedBranch}
                      onSelect={selectBranch}
                      disabled={isImporting}
                      loading={resolver.status === 'fetching-branches'}
                    />
                  </motion.div>
                )}
              </AnimatePresence>

              {/* Project Name Input (new project mode) */}
              {isNewProjectMode && (resolver.status === 'resolved' || repoUrl.trim()) && (
                <motion.div
                  initial={{ opacity: 0, y: -4 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.15 }}
                >
                  <label className="block text-sm font-medium text-[var(--text)] mb-2">
                    Project Name
                  </label>
                  <input
                    type="text"
                    value={projectName}
                    onChange={(e) => setProjectName(e.target.value)}
                    className="w-full bg-white/5 border border-white/10 text-[var(--text)] px-4 py-3 rounded-xl focus:outline-none focus:ring-2 focus:ring-[var(--primary)]/30 focus:border-[var(--primary)]/50 placeholder-gray-500 min-h-[44px]"
                    placeholder="my-project (auto-detected from repo)"
                    disabled={isImporting}
                  />
                </motion.div>
              )}

              {/* Browse Repos Section */}
              <BrowseReposSection
                providerStatus={providerStatus}
                onSelectRepo={handleBrowseSelectRepo}
                disabled={isImporting}
              />
            </div>

            {/* Actions */}
            <div className="flex flex-col sm:flex-row gap-3 pt-5 sm:pt-6 mt-4 sm:mt-6 border-t border-white/10">
              <button
                onClick={handleImportClick}
                disabled={!canImport}
                className="flex-1 bg-[var(--primary)] hover:bg-[var(--primary-hover)] disabled:bg-gray-600 disabled:cursor-not-allowed text-white py-3 rounded-xl font-semibold transition-all flex items-center justify-center gap-2 min-h-[44px] order-1 sm:order-1"
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
                className="flex-1 bg-white/5 border border-white/10 text-[var(--text)] py-3 rounded-xl font-semibold hover:bg-white/10 transition-all disabled:opacity-50 min-h-[44px] order-2 sm:order-2"
              >
                Cancel
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>

    <ConfirmDialog
      isOpen={showConfirm}
      onClose={() => setShowConfirm(false)}
      onConfirm={performImport}
      title="Override existing files?"
      message="Importing this repository will override all existing files in your project. Make sure to back up any unsaved work before proceeding."
      confirmText="Import anyway"
      cancelText="Cancel"
      variant="warning"
    />
    </>
  );
}

export default RepoImportModal;
