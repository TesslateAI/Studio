import api from './api';
import type {
  GitRepositoryResponse,
  GitStatusResponse,
  GitCommitRequest,
  GitCommitResponse,
  GitPushRequest,
  GitPushResponse,
  GitPullRequest,
  GitPullResponse,
  GitHistoryResponse,
  GitBranchesResponse,
  GitBranchRequest,
  GitSwitchBranchRequest,
  GitCloneRequest,
  GitInitRequest,
  GitDiffResponse,
} from '../types/git';

/**
 * Git Operations API Client
 * Handles all Git version control operations for projects
 */
export const gitApi = {
  /**
   * Initialize a Git repository for a project
   */
  init: async (projectId: number, repoUrl?: string): Promise<GitRepositoryResponse> => {
    const response = await api.post(`/api/projects/${projectId}/git/init`, {
      repo_url: repoUrl,
    } as GitInitRequest);
    return response.data;
  },

  /**
   * Clone a GitHub repository into a project
   */
  clone: async (projectId: number, repoUrl: string, branch?: string): Promise<GitRepositoryResponse> => {
    const response = await api.post(`/api/projects/${projectId}/git/clone`, {
      repo_url: repoUrl,
      branch: branch || 'main',
    } as GitCloneRequest);
    return response.data;
  },

  /**
   * Get Git status for a project
   */
  getStatus: async (projectId: number): Promise<GitStatusResponse> => {
    const response = await api.get(`/api/projects/${projectId}/git/status`);
    return response.data;
  },

  /**
   * Create a commit
   */
  commit: async (projectId: number, message: string, files?: string[]): Promise<GitCommitResponse> => {
    const response = await api.post(`/api/projects/${projectId}/git/commit`, {
      message,
      files,
    } as GitCommitRequest);
    return response.data;
  },

  /**
   * Push commits to remote
   */
  push: async (
    projectId: number,
    branch?: string,
    remote?: string,
    force?: boolean
  ): Promise<GitPushResponse> => {
    const response = await api.post(`/api/projects/${projectId}/git/push`, {
      branch,
      remote,
      force,
    } as GitPushRequest);
    return response.data;
  },

  /**
   * Pull changes from remote
   */
  pull: async (projectId: number, branch?: string, remote?: string): Promise<GitPullResponse> => {
    const response = await api.post(`/api/projects/${projectId}/git/pull`, {
      branch,
      remote,
    } as GitPullRequest);
    return response.data;
  },

  /**
   * Get commit history
   */
  getCommitHistory: async (projectId: number, limit: number = 50): Promise<GitHistoryResponse> => {
    const response = await api.get(`/api/projects/${projectId}/git/commits`, {
      params: { limit },
    });
    return response.data;
  },

  /**
   * List branches
   */
  getBranches: async (projectId: number): Promise<GitBranchesResponse> => {
    const response = await api.get(`/api/projects/${projectId}/git/branches`);
    return response.data;
  },

  /**
   * Create a new branch
   */
  createBranch: async (
    projectId: number,
    name: string,
    checkout: boolean = false
  ): Promise<void> => {
    await api.post(`/api/projects/${projectId}/git/branches`, {
      name,
      checkout,
    } as GitBranchRequest);
  },

  /**
   * Switch to a different branch
   */
  switchBranch: async (projectId: number, branch: string): Promise<void> => {
    await api.put(`/api/projects/${projectId}/git/branches/switch`, {
      branch,
    } as GitSwitchBranchRequest);
  },

  /**
   * Get repository info
   */
  getRepositoryInfo: async (projectId: number): Promise<GitRepositoryResponse> => {
    const response = await api.get(`/api/projects/${projectId}/git/info`);
    return response.data;
  },

  /**
   * Disconnect repository from project
   */
  disconnect: async (projectId: number): Promise<void> => {
    await api.delete(`/api/projects/${projectId}/git/disconnect`);
  },

  /**
   * Get diff for uncommitted changes
   */
  getDiff: async (projectId: number, filePath?: string): Promise<GitDiffResponse> => {
    const response = await api.get(`/api/projects/${projectId}/git/diff`, {
      params: filePath ? { file_path: filePath } : undefined,
    });
    return response.data;
  },
};
