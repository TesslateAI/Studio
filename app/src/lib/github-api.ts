import api from './api';
import type {
  GitHubCredentialResponse,
  GitHubConnectRequest,
  GitHubRepositoryListResponse,
  CreateGitHubRepoRequest,
  GitHubRepository,
  GitHubBranchesResponse,
} from '../types/git';

/**
 * GitHub API Client
 * Handles GitHub authentication and repository operations
 */
export const githubApi = {
  /**
   * Connect to GitHub using a Personal Access Token
   */
  connect: async (patToken: string): Promise<GitHubCredentialResponse> => {
    const response = await api.post('/api/github/connect', {
      pat_token: patToken,
    } as GitHubConnectRequest);
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
