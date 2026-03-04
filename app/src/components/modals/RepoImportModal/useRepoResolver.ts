import { useState, useRef, useCallback } from 'react';
import { gitProvidersApi } from '../../../lib/git-providers-api';
import type {
  GitProvider,
  GitProviderRepository,
  GitProviderBranch,
  AllProvidersStatus,
} from '../../../types/git-providers';

export type ResolverStatus =
  | 'idle'
  | 'detecting'
  | 'fetching-repo'
  | 'fetching-branches'
  | 'resolved'
  | 'error';

export interface ResolverState {
  status: ResolverStatus;
  provider: GitProvider | null;
  owner: string | null;
  repoName: string | null;
  repo: GitProviderRepository | null;
  branches: GitProviderBranch[];
  selectedBranch: GitProviderBranch | null;
  error: string | null;
  needsAuth: boolean;
}

const initialState: ResolverState = {
  status: 'idle',
  provider: null,
  owner: null,
  repoName: null,
  repo: null,
  branches: [],
  selectedBranch: null,
  error: null,
  needsAuth: false,
};

export function useRepoResolver(providerStatus: AllProvidersStatus) {
  const [state, setState] = useState<ResolverState>(initialState);
  const abortRef = useRef<AbortController | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    if (debounceRef.current) clearTimeout(debounceRef.current);
    setState(initialState);
  }, []);

  const fetchRepoAndBranches = useCallback(
    async (provider: GitProvider, owner: string, repo: string, signal: AbortSignal) => {
      // Check if provider is connected
      const isConnected = providerStatus[provider]?.connected;

      setState((prev) => ({
        ...prev,
        status: 'fetching-repo',
        provider,
        owner,
        repoName: repo,
        error: null,
        needsAuth: false,
      }));

      try {
        const repoData = await gitProvidersApi.getRepository(provider, owner, repo);
        if (signal.aborted) return;

        setState((prev) => ({
          ...prev,
          status: 'fetching-branches',
          repo: repoData,
        }));

        const branches = await gitProvidersApi.listBranches(provider, owner, repo);
        if (signal.aborted) return;

        const defaultBranch = branches.find((b) => b.is_default) || branches[0] || null;

        setState((prev) => ({
          ...prev,
          status: 'resolved',
          branches,
          selectedBranch: defaultBranch,
        }));
      } catch (error: unknown) {
        if (signal.aborted) return;

        const err = error as { response?: { status?: number; data?: { detail?: string } } };
        const status = err?.response?.status;
        const detail = err?.response?.data?.detail || 'Failed to fetch repository';

        if (status === 401 || status === 403 || !isConnected) {
          setState((prev) => ({
            ...prev,
            status: 'error',
            error: `Connect your ${provider} account to access this repository`,
            needsAuth: true,
          }));
        } else if (status === 404) {
          setState((prev) => ({
            ...prev,
            status: 'error',
            error: 'Repository not found. Check the URL and try again.',
            needsAuth: false,
          }));
        } else {
          setState((prev) => ({
            ...prev,
            status: 'error',
            error: detail,
            needsAuth: false,
          }));
        }
      }
    },
    [providerStatus]
  );

  const resolveUrl = useCallback(
    (url: string) => {
      // Cancel any pending requests
      abortRef.current?.abort();
      if (debounceRef.current) clearTimeout(debounceRef.current);

      if (!url.trim()) {
        setState(initialState);
        return;
      }

      // Detect provider
      const provider = gitProvidersApi.detectProvider(url);
      if (!provider) {
        setState({
          ...initialState,
          status: 'detecting',
        });
        return;
      }

      // Parse owner/repo
      const parsed = gitProvidersApi.parseRepoUrl(url);
      if (!parsed) {
        setState({
          ...initialState,
          status: 'detecting',
          provider,
        });
        return;
      }

      // Debounce the API call
      debounceRef.current = setTimeout(() => {
        const controller = new AbortController();
        abortRef.current = controller;
        fetchRepoAndBranches(provider, parsed.owner, parsed.repo, controller.signal);
      }, 500);
    },
    [fetchRepoAndBranches]
  );

  const selectRepo = useCallback(
    (repo: GitProviderRepository) => {
      abortRef.current?.abort();
      if (debounceRef.current) clearTimeout(debounceRef.current);

      const controller = new AbortController();
      abortRef.current = controller;

      setState({
        ...initialState,
        status: 'fetching-repo',
        provider: repo.provider,
        owner: repo.owner,
        repoName: repo.name,
        repo,
      });

      // Fetch branches directly since we already have the repo
      (async () => {
        try {
          setState((prev) => ({ ...prev, status: 'fetching-branches' }));
          const branches = await gitProvidersApi.listBranches(
            repo.provider,
            repo.owner,
            repo.name
          );
          if (controller.signal.aborted) return;

          const defaultBranch = branches.find((b) => b.is_default) || branches[0] || null;
          setState((prev) => ({
            ...prev,
            status: 'resolved',
            branches,
            selectedBranch: defaultBranch,
          }));
        } catch {
          if (controller.signal.aborted) return;
          // Even if branches fail, mark as resolved with the repo data
          setState((prev) => ({
            ...prev,
            status: 'resolved',
            branches: [],
            selectedBranch: null,
          }));
        }
      })();
    },
    []
  );

  const selectBranch = useCallback((branch: GitProviderBranch) => {
    setState((prev) => ({ ...prev, selectedBranch: branch }));
  }, []);

  const retryAfterAuth = useCallback(() => {
    if (state.provider && state.owner && state.repoName) {
      const controller = new AbortController();
      abortRef.current = controller;
      fetchRepoAndBranches(state.provider, state.owner, state.repoName, controller.signal);
    }
  }, [state.provider, state.owner, state.repoName, fetchRepoAndBranches]);

  return {
    state,
    resolveUrl,
    selectRepo,
    selectBranch,
    retryAfterAuth,
    reset,
  };
}
