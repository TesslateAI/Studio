/**
 * Types for Git Provider integration (GitHub, GitLab, Bitbucket)
 */

export type GitProvider = 'github' | 'gitlab' | 'bitbucket';

export interface ProviderInfo {
  name: GitProvider;
  display_name: string;
  icon: string;
  oauth_scopes: string;
  description: string;
}

export interface GitProviderCredentialStatus {
  connected: boolean;
  provider_username?: string;
  provider_email?: string;
  scope?: string;
}

export interface AllProvidersStatus {
  github: GitProviderCredentialStatus;
  gitlab: GitProviderCredentialStatus;
  bitbucket: GitProviderCredentialStatus;
}

export interface GitProviderRepository {
  id: string;
  name: string;
  full_name: string;
  description: string | null;
  clone_url: string;
  web_url: string;
  default_branch: string;
  private: boolean;
  updated_at: string | null;
  owner: string;
  provider: GitProvider;
  language?: string;
  stars_count?: number;
  forks_count?: number;
}

export interface GitProviderBranch {
  name: string;
  is_default: boolean;
  commit_sha: string;
  protected: boolean;
}

export interface OAuthAuthorizeResponse {
  authorization_url: string;
  state: string;
  provider: GitProvider;
}

export interface OAuthCallbackResponse {
  success: boolean;
  provider: GitProvider;
  provider_username: string;
  provider_email: string | null;
  message: string;
}

export interface RepositoriesResponse {
  repositories: GitProviderRepository[];
}

export interface BranchesResponse {
  branches: GitProviderBranch[];
}

export interface ProvidersListResponse {
  providers: ProviderInfo[];
}

// Helper to get provider display info
export const PROVIDER_CONFIG: Record<GitProvider, {
  displayName: string;
  icon: string;
  color: string;
  bgColor: string;
}> = {
  github: {
    displayName: 'GitHub',
    icon: 'github-logo',
    color: 'text-white',
    bgColor: 'bg-[#24292e]'
  },
  gitlab: {
    displayName: 'GitLab',
    icon: 'gitlab-logo',
    color: 'text-[#FC6D26]',
    bgColor: 'bg-[#FC6D26]/10'
  },
  bitbucket: {
    displayName: 'Bitbucket',
    icon: 'bitbucket-logo',
    color: 'text-[#0052CC]',
    bgColor: 'bg-[#0052CC]/10'
  }
};
