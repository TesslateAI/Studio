import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  CaretDown,
  MagnifyingGlass,
  GitBranch,
  Lock,
  Globe,
  GithubLogo,
  CircleNotch,
  Check,
} from '@phosphor-icons/react';
import { gitProvidersApi } from '../../../lib/git-providers-api';
import type { GitProvider, GitProviderRepository, AllProvidersStatus } from '../../../types/git-providers';
import { PROVIDER_CONFIG } from '../../../types/git-providers';
import toast from 'react-hot-toast';

interface BrowseReposSectionProps {
  providerStatus: AllProvidersStatus;
  onSelectRepo: (repo: GitProviderRepository) => void;
  disabled?: boolean;
}

export function BrowseReposSection({
  providerStatus,
  onSelectRepo,
  disabled = false,
}: BrowseReposSectionProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [activeProvider, setActiveProvider] = useState<GitProvider | null>(null);
  const [repositories, setRepositories] = useState<GitProviderRepository[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  // Find connected providers
  const connectedProviders = (Object.keys(providerStatus) as GitProvider[]).filter(
    (p) => providerStatus[p].connected
  );

  // Auto-select first connected provider
  useEffect(() => {
    if (isExpanded && connectedProviders.length > 0 && !activeProvider) {
      setActiveProvider(connectedProviders[0]);
    }
  }, [isExpanded, connectedProviders.length]);

  // Fetch repos when provider changes
  useEffect(() => {
    if (isExpanded && activeProvider && providerStatus[activeProvider].connected) {
      loadRepositories(activeProvider);
    }
  }, [activeProvider, isExpanded]);

  const loadRepositories = async (provider: GitProvider) => {
    setIsLoading(true);
    setRepositories([]);
    try {
      const repos = await gitProvidersApi.listRepositories(provider);
      setRepositories(repos);
    } catch (error: unknown) {
      const message =
        (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        'Failed to load repositories';
      toast.error(message);
    } finally {
      setIsLoading(false);
    }
  };

  const filteredRepos = searchQuery.trim()
    ? repositories.filter(
        (repo) =>
          repo.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
          repo.full_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
          repo.description?.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : repositories;

  if (connectedProviders.length === 0) return null;

  return (
    <div className="border-t border-white/5 pt-3">
      <button
        type="button"
        onClick={() => setIsExpanded(!isExpanded)}
        disabled={disabled}
        className="w-full flex items-center justify-between py-2 text-sm text-gray-400 hover:text-gray-300 transition-colors min-h-[44px] disabled:opacity-50"
      >
        <span>Or browse your repositories</span>
        <CaretDown
          className={`w-4 h-4 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
        />
      </button>

      <AnimatePresence>
        {isExpanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="space-y-3 pb-2">
              {/* Provider pills */}
              <div className="flex gap-2">
                {connectedProviders.map((provider) => {
                  const config = PROVIDER_CONFIG[provider];
                  const isActive = activeProvider === provider;

                  return (
                    <button
                      key={provider}
                      type="button"
                      onClick={() => {
                        setActiveProvider(provider);
                        setSearchQuery('');
                      }}
                      disabled={disabled}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-all min-h-[32px] ${
                        isActive
                          ? 'bg-[var(--primary)]/15 text-[var(--primary)] border border-[var(--primary)]/30'
                          : 'bg-white/5 text-gray-400 hover:bg-white/10 border border-transparent'
                      }`}
                    >
                      {provider === 'github' ? (
                        <GithubLogo size={14} weight="fill" />
                      ) : provider === 'gitlab' ? (
                        <span className="font-bold text-[#FC6D26]" style={{ fontSize: 10 }}>GL</span>
                      ) : (
                        <span className="font-bold text-[#0052CC]" style={{ fontSize: 10 }}>BB</span>
                      )}
                      {config.displayName}
                      <Check size={12} weight="bold" className="text-green-400" />
                    </button>
                  );
                })}
              </div>

              {activeProvider && (
                <>
                  {/* Search */}
                  <div className="relative">
                    <MagnifyingGlass className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
                    <input
                      type="text"
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      className="w-full bg-white/5 border border-white/10 text-[var(--text)] text-sm pl-9 pr-4 py-2.5 rounded-xl focus:outline-none focus:ring-2 focus:ring-[var(--primary)]/30 placeholder-gray-500 min-h-[44px]"
                      placeholder="Search repositories..."
                      disabled={disabled || isLoading}
                    />
                  </div>

                  {/* Repository list */}
                  <div className="max-h-60 overflow-y-auto space-y-1.5 rounded-xl">
                    {isLoading ? (
                      <div className="text-center py-6">
                        <CircleNotch className="w-6 h-6 mx-auto mb-2 text-[var(--primary)] animate-spin" />
                        <p className="text-sm text-gray-500">Loading repositories...</p>
                      </div>
                    ) : filteredRepos.length === 0 ? (
                      <div className="text-center py-6 text-sm text-gray-500">
                        {repositories.length === 0 ? 'No repositories found' : 'No matching repositories'}
                      </div>
                    ) : (
                      filteredRepos.map((repo) => (
                        <button
                          key={repo.id}
                          type="button"
                          onClick={() => onSelectRepo(repo)}
                          disabled={disabled}
                          className="w-full text-left p-3 rounded-xl border border-white/5 bg-white/[0.02] hover:bg-white/5 hover:border-white/10 transition-all min-h-[44px]"
                        >
                          <div className="flex items-center gap-2 mb-0.5">
                            <GitBranch className="w-3.5 h-3.5 text-gray-500 flex-shrink-0" />
                            <span className="font-medium text-sm text-[var(--text)] truncate">
                              {repo.full_name}
                            </span>
                            {repo.private ? (
                              <Lock size={10} className="text-yellow-500 flex-shrink-0" />
                            ) : (
                              <Globe size={10} className="text-green-500 flex-shrink-0" />
                            )}
                          </div>
                          {repo.description && (
                            <p className="text-xs text-gray-500 truncate ml-5.5">
                              {repo.description}
                            </p>
                          )}
                        </button>
                      ))
                    )}
                  </div>
                </>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
