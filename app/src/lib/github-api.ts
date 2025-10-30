import api from './api';
import type {
  GitHubCredentialResponse,
  GitHubRepositoryListResponse,
  CreateGitHubRepoRequest,
  GitHubRepository,
  GitHubBranchesResponse,
} from '../types/git';

/**
 * GitHub API Client
 * Handles GitHub OAuth authentication and repository operations
 */
export const githubApi = {
  /**
   * Initiate GitHub OAuth flow
   */
  initiateOAuth: async (scope: string = 'repo user:email'): Promise<{ authorization_url: string; state: string }> => {
    const response = await api.get('/api/github/oauth/authorize', {
      params: { scope }
    });
    return response.data;
  },

  /**
   * Handle OAuth callback
   */
  handleOAuthCallback: async (code: string, state: string): Promise<any> => {
    const response = await api.get('/api/github/oauth/callback', {
      params: { code, state }
    });
    return response.data;
  },

  /**
   * Get GitHub connection status
   */
  getStatus: async (): Promise<GitHubCredentialResponse> => {
    const response = await api.get('/api/github/status');
    return response.data;
  },

  /**
   * Disconnect GitHub account
   */
  disconnect: async (): Promise<void> => {
    await api.delete('/api/github/disconnect');
  },

  /**
   * List user's GitHub repositories
   */
  listRepositories: async (): Promise<GitHubRepository[]> => {
    const response = await api.get<GitHubRepositoryListResponse>('/api/github/repositories');
    return response.data.repositories;
  },

  /**
   * Create a new GitHub repository
   */
  createRepository: async (
    name: string,
    description?: string,
    isPrivate: boolean = true
  ): Promise<GitHubRepository> => {
    const response = await api.post('/api/github/repositories', {
      name,
      description,
      private: isPrivate,
    } as CreateGitHubRepoRequest);
    return response.data;
  },

  /**
   * Get branches for a specific repository
   */
  getRepositoryBranches: async (
    owner: string,
    repo: string
  ): Promise<GitHubBranchesResponse> => {
    const response = await api.get(`/api/github/repositories/${owner}/${repo}/branches`);
    return response.data;
  },
};
