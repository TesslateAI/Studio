// Git and GitHub TypeScript Types

// GitHub Credential Types
export interface GitHubCredential {
  id: string;
  user_id: string;
  github_username: string | null;
  github_email: string | null;
  github_user_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface GitHubCredentialResponse {
  connected: boolean;
  github_username: string | null;
  github_email: string | null;
  auth_method: 'oauth';
  scope?: string | null;
}

// Git Repository Types
export interface GitRepository {
  id: string;
  project_id: string;
  user_id: string;
  repo_url: string;
  repo_name: string | null;
  repo_owner: string | null;
  default_branch: string;
  auth_method: 'oauth';
  last_sync_at: string | null;
  sync_status: 'synced' | 'ahead' | 'behind' | 'diverged' | 'error' | null;
  last_commit_sha: string | null;
  auto_push: boolean;
  auto_pull: boolean;
  created_at: string;
  updated_at: string;
}

export interface GitRepositoryResponse {
  id: string;
  project_id: string;
  repo_url: string;
  repo_name: string | null;
  repo_owner: string | null;
  default_branch: string;
  sync_status: string | null;
  last_commit_sha: string | null;
  auto_push: boolean;
  auto_pull: boolean;
}

// Git Status Types
export interface GitFileChange {
  file_path: string;
  status: 'M' | 'A' | 'D' | 'R' | 'U' | '??';
  staged: boolean;
}

export interface GitStatusResponse {
  branch: string;
  ahead: number;
  behind: number;
  staged_count: number;
  unstaged_count: number;
  untracked_count: number;
  has_conflicts: boolean;
  changes: GitFileChange[];
  remote_branch: string | null;
  last_commit: {
    sha: string;
    message: string;
    author: string;
    date: string;
  } | null;
}

// Git Commit Types
export interface GitCommitRequest {
  message: string;
  files?: string[];
}

export interface GitCommitResponse {
  success: boolean;
  sha: string;
  message: string;
}

export interface GitCommitInfo {
  sha: string;
  message: string;
  author: string;
  email: string;
  date: string;
  branch: string;
}

export interface GitHistoryResponse {
  commits: GitCommitInfo[];
  total: number;
}

// Git Push/Pull Types
export interface GitPushRequest {
  branch?: string;
  remote?: string;
  force?: boolean;
}

export interface GitPushResponse {
  success: boolean;
  message: string;
}

export interface GitPullRequest {
  branch?: string;
  remote?: string;
}

export interface GitPullResponse {
  success: boolean;
  message: string;
  conflicts?: string[];
  updated_files?: string[];
}

// Git Branch Types
export interface GitBranchInfo {
  name: string;
  current: boolean;
  remote: boolean;
}

export interface GitBranchesResponse {
  branches: GitBranchInfo[];
  current_branch: string;
}

export interface GitBranchRequest {
  name: string;
  checkout?: boolean;
}

export interface GitSwitchBranchRequest {
  branch: string;
}

// Git Clone/Init Types
export interface GitCloneRequest {
  repo_url: string;
  branch?: string;
}

export interface GitInitRequest {
  repo_url?: string;
}

// GitHub Repository Types
export interface GitHubRepository {
  id: string;
  name: string;
  full_name: string;
  description: string | null;
  private: boolean;
  html_url: string;
  clone_url: string;
  ssh_url: string;
  default_branch: string;
  created_at: string;
  updated_at: string;
  pushed_at: string | null;
}

export interface GitHubRepositoryListResponse {
  repositories: GitHubRepository[];
}

export interface CreateGitHubRepoRequest {
  name: string;
  description?: string;
  private?: boolean;
}

export interface GitHubBranchInfo {
  name: string;
  commit: {
    sha: string;
    url: string;
  };
  protected: boolean;
}

export interface GitHubBranchesResponse {
  branches: GitHubBranchInfo[];
}

// Diff Types
export interface GitDiffResponse {
  diff: string;
  files: Array<{
    file_path: string;
    additions: number;
    deletions: number;
    changes: string;
  }>;
}
