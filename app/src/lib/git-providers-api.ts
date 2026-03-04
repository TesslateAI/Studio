/**
 * Git Providers API Client
 *
 * Unified API client for GitHub, GitLab, and Bitbucket integration.
 */
import api from './api';
import type {
  GitProvider,
  GitProviderCredentialStatus,
  AllProvidersStatus,
  GitProviderRepository,
  GitProviderBranch,
  OAuthAuthorizeResponse,
  OAuthCallbackResponse,
  ProviderInfo,
} from '../types/git-providers';

export const gitProvidersApi = {
  /**
   * List all available Git providers
   */
  listProviders: async (): Promise<ProviderInfo[]> => {
    const response = await api.get('/api/git-providers/');
    return response.data.providers;
  },

  /**
   * Get connection status for all providers
   */
  getAllStatus: async (): Promise<AllProvidersStatus> => {
    const response = await api.get('/api/git-providers/status');
    return response.data;
  },

  /**
   * Get connection status for a specific provider
   */
  getStatus: async (provider: GitProvider): Promise<GitProviderCredentialStatus> => {
    const response = await api.get(`/api/git-providers/${provider}/status`);
    return response.data;
  },

  /**
   * Initiate OAuth flow for a provider
   * Returns the authorization URL to redirect the user to
   */
  initiateOAuth: async (provider: GitProvider, scope?: string): Promise<OAuthAuthorizeResponse> => {
    const params = scope ? { scope } : {};
    const response = await api.get(`/api/git-providers/${provider}/oauth/authorize`, { params });
    return response.data;
  },

  /**
   * Handle OAuth callback
   * This is typically called by the callback page component
   */
  handleOAuthCallback: async (
    provider: GitProvider,
    code: string,
    state: string
  ): Promise<OAuthCallbackResponse> => {
    const response = await api.get(`/api/git-providers/${provider}/oauth/callback`, {
      params: { code, state }
    });
    return response.data;
  },

  /**
   * Disconnect a provider
   */
  disconnect: async (provider: GitProvider): Promise<{ message: string }> => {
    const response = await api.delete(`/api/git-providers/${provider}/disconnect`);
    return response.data;
  },

  /**
   * List repositories from a provider
   */
  listRepositories: async (provider: GitProvider): Promise<GitProviderRepository[]> => {
    const response = await api.get(`/api/git-providers/${provider}/repositories`);
    return response.data.repositories;
  },

  /**
   * Get repository information
   */
  getRepository: async (
    provider: GitProvider,
    owner: string,
    repo: string
  ): Promise<GitProviderRepository> => {
    const response = await api.get(`/api/git-providers/${provider}/repositories/${owner}/${repo}`);
    return response.data;
  },

  /**
   * List branches for a repository
   */
  listBranches: async (
    provider: GitProvider,
    owner: string,
    repo: string
  ): Promise<GitProviderBranch[]> => {
    const response = await api.get(
      `/api/git-providers/${provider}/repositories/${owner}/${repo}/branches`
    );
    return response.data.branches;
  },

  /**
   * Connect to a provider (opens OAuth popup)
   */
  connect: async (provider: GitProvider): Promise<void> => {
    const { authorization_url } = await gitProvidersApi.initiateOAuth(provider);

    // Open OAuth in a popup window
    const width = 600;
    const height = 700;
    const left = window.screenX + (window.outerWidth - width) / 2;
    const top = window.screenY + (window.outerHeight - height) / 2;

    const popup = window.open(
      authorization_url,
      `${provider}-oauth`,
      `width=${width},height=${height},left=${left},top=${top},toolbar=no,menubar=no,scrollbars=yes`
    );

    // Return a promise that resolves when the popup closes
    return new Promise((resolve, reject) => {
      const checkClosed = setInterval(() => {
        if (popup?.closed) {
          clearInterval(checkClosed);
          // The callback page should have handled the OAuth response
          resolve();
        }
      }, 500);

      // Timeout after 5 minutes
      setTimeout(() => {
        clearInterval(checkClosed);
        popup?.close();
        reject(new Error('OAuth timeout'));
      }, 5 * 60 * 1000);
    });
  },

  /**
   * Detect provider from repository URL
   */
  detectProvider: (url: string): GitProvider | null => {
    const lowerUrl = url.toLowerCase();
    if (lowerUrl.includes('github.com')) return 'github';
    if (lowerUrl.includes('gitlab.com') || lowerUrl.includes('gitlab')) return 'gitlab';
    if (lowerUrl.includes('bitbucket.org') || lowerUrl.includes('bitbucket')) return 'bitbucket';
    return null;
  },

  /**
   * Parse repository URL to extract owner and repo
   */
  parseRepoUrl: (url: string): { owner: string; repo: string } | null => {
    // HTTPS patterns
    const httpsPattern = /https?:\/\/[^/]+\/([^/]+)\/([^/]+?)(?:\.git)?$/;
    // SSH patterns
    const sshPattern = /git@[^:]+:([^/]+)\/([^/]+?)(?:\.git)?$/;

    let match = url.match(httpsPattern);
    if (match) {
      return { owner: match[1], repo: match[2] };
    }

    match = url.match(sshPattern);
    if (match) {
      return { owner: match[1], repo: match[2] };
    }

    return null;
  }
};

export default gitProvidersApi;
