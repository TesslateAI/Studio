import axios from 'axios';
import type { AgentChatRequest, AgentChatResponse, Agent } from '../types/agent';
import type {
  BillingConfig,
  SubscriptionResponse,
  CheckoutSessionResponse,
  CreditStatusResponse,
  VerifyCheckoutResponse,
  CreditBalanceResponse,
  CreditPackage,
  CreditPurchaseHistoryResponse,
  UsageSummaryResponse,
  UsageLogsResponse,
  TransactionsResponse,
  CreatorEarningsResponse,
  CustomerPortalResponse,
  StripeConnectResponse,
} from '../types/billing';
import type {
  TesslateConfig,
  TesslateConfigResponse,
  SetupConfigSyncResponse,
  ConfigSyncSaveResponse,
} from '../types/tesslateConfig';
import type {
  ContainerConfigResponse,
  NodeConfigMode,
  RevealSecretResponse,
  SubmittedValues,
} from '../types/nodeConfig';
import { config } from '../config';

const API_URL = config.API_URL;

const api = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  withCredentials: true, // Send cookies with requests (for OAuth cookie-based auth)
});

/**
 * Authentication:
 * - Short-lived JWT access tokens (15 min) for API authentication
 * - Long-lived refresh tokens (14 days) as httpOnly cookie for session persistence
 * - Cookie-based OAuth authentication with CSRF protection
 * - 401 interceptor triggers refresh-then-retry via cookie
 */

/**
 * Revoke the server-side session (refresh token + auth cookies).
 * Best-effort — errors are swallowed since we always clear local state regardless.
 */
export async function revokeServerSession(): Promise<void> {
  try {
    await axios.post(`${API_URL}/api/auth/logout`, {}, { withCredentials: true });
  } catch {
    // Best-effort — server may be unreachable or session already expired
  }
}

// CSRF token management
let csrfToken: string | null = null;

export const fetchCsrfToken = async () => {
  try {
    const response = await api.get('/api/auth/csrf');
    csrfToken = response.data.csrf_token;
  } catch (error) {
    console.error('Failed to fetch CSRF token:', error);
  }
};

// Call fetchCsrfToken on app load
fetchCsrfToken();

/**
 * Helper to build auth headers for fetch() calls
 * Supports both JWT Bearer tokens and cookie-based OAuth authentication
 */
export const getAuthHeaders = (
  additionalHeaders?: Record<string, string>
): Record<string, string> => {
  const token = localStorage.getItem('token');
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...additionalHeaders,
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  } else if (csrfToken) {
    // Add CSRF token for cookie-based auth (OAuth users)
    headers['X-CSRF-Token'] = csrfToken;
  }

  return headers;
};

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }

  // Add CSRF token for state-changing operations when using cookie auth
  if (['post', 'put', 'delete', 'patch'].includes(config.method?.toLowerCase() || '')) {
    if (csrfToken && !token) {
      // Only add CSRF token if we're using cookie-based auth (no Bearer token)
      config.headers['X-CSRF-Token'] = csrfToken;
    }
  }

  return config;
});

// =============================================================================
// Token Refresh Queue (single-flight pattern)
// =============================================================================

let isRefreshing = false;
let refreshSubscribers: Array<{
  resolve: (token: string | null) => void;
  reject: (error: unknown) => void;
}> = [];

function onRefreshComplete(token: string | null) {
  refreshSubscribers.forEach((sub) => sub.resolve(token));
  refreshSubscribers = [];
}

function onRefreshError(error: unknown) {
  refreshSubscribers.forEach((sub) => sub.reject(error));
  refreshSubscribers = [];
}

/**
 * Attempt to refresh the auth token.
 * Uses raw axios to avoid triggering the 401 interceptor recursively.
 */
async function refreshAuthToken(): Promise<string | null> {
  const response = await axios.post(`${API_URL}/api/auth/refresh`, {}, { withCredentials: true });

  const newToken: string | null = response.data?.access_token ?? null;
  if (newToken) {
    // Update localStorage so Bearer header is set on future API calls.
    // NOTE: localStorage.setItem automatically fires 'storage' events in OTHER tabs.
    // We do NOT dispatchEvent here to avoid triggering AuthContext's handleStorageChange
    // on the same tab (which would cause an unnecessary /api/users/me call).
    localStorage.setItem('token', newToken);
  }
  return newToken;
}

// =============================================================================
// Response Interceptor — refresh-then-retry on 401
// =============================================================================

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;

    // Handle 401 — attempt token refresh before logging out
    if (error.response?.status === 401 && originalRequest) {
      // Never retry the refresh endpoint itself (prevent recursion)
      if (originalRequest.url?.includes('/api/auth/refresh')) {
        return Promise.reject(error);
      }

      // Never retry a request that already retried (prevent infinite loop)
      if (originalRequest._authRetry) {
        return Promise.reject(error);
      }

      // Skip refresh for endpoints where 401 is expected/normal
      const isMarketplacePage = window.location.pathname.startsWith('/marketplace');
      const isPreferencesApi = originalRequest.url?.includes('/api/users/preferences');
      const isGitProvidersApi = originalRequest.url?.includes('/api/git-providers/');
      const isPasswordResetPage =
        window.location.pathname === '/forgot-password' ||
        window.location.pathname === '/reset-password';
      // Login-flow endpoints: 401 here means "bad code / expired link / wrong creds",
      // NOT "session expired". Attempting a refresh is pointless (no session exists yet)
      // and the resulting redirect to /login hides the real error from the user.
      const isLoginFlowApi =
        originalRequest.url?.includes('/api/auth/login') ||
        originalRequest.url?.includes('/api/auth/2fa/') ||
        originalRequest.url?.includes('/api/auth/magic-link/');

      if (
        isMarketplacePage ||
        isPreferencesApi ||
        isGitProvidersApi ||
        isPasswordResetPage ||
        isLoginFlowApi
      ) {
        return Promise.reject(error);
      }

      // If a refresh is already in progress, queue this request
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          refreshSubscribers.push({
            resolve: (token) => {
              originalRequest._authRetry = true;
              if (token) {
                originalRequest.headers['Authorization'] = `Bearer ${token}`;
              }
              resolve(api.request(originalRequest));
            },
            reject,
          });
        });
      }

      // Start a single refresh
      isRefreshing = true;

      try {
        const newToken = await refreshAuthToken();
        isRefreshing = false;
        onRefreshComplete(newToken);

        // Retry the original request with the new token
        originalRequest._authRetry = true;
        if (newToken) {
          originalRequest.headers['Authorization'] = `Bearer ${newToken}`;
        }
        return api.request(originalRequest);
      } catch (refreshError) {
        isRefreshing = false;
        onRefreshError(refreshError);

        // Refresh failed — actually log the user out
        localStorage.removeItem('token');
        if (window.location.pathname !== '/login') {
          window.location.href = '/login';
        }
        return Promise.reject(refreshError);
      }
    }

    // If error is 403 and mentions CSRF, refetch token and retry
    if (error.response?.status === 403 && error.response?.data?.detail?.includes('CSRF')) {
      await fetchCsrfToken();
      // Retry the request once with new CSRF token
      if (error.config && !error.config._csrfRetry) {
        error.config._csrfRetry = true;
        return api.request(error.config);
      }
    }

    return Promise.reject(error);
  }
);

export const authApi = {
  // Login with email 2FA (custom endpoint — always returns temp_token + requires_2fa)
  login: async (username: string, password: string) => {
    const formData = new URLSearchParams();
    formData.append('username', username);
    formData.append('password', password);
    const response = await api.post('/api/auth/login', formData, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    });
    return response.data;
  },

  // Verify 2FA code during login (returns JWT access_token on success)
  verify2fa: async (tempToken: string, code: string) => {
    const response = await api.post('/api/auth/2fa/verify', {
      temp_token: tempToken,
      code,
    });
    return response.data;
  },

  // Resend 2FA code during login
  resend2faCode: async (tempToken: string) => {
    const formData = new URLSearchParams();
    formData.append('temp_token', tempToken);
    const response = await api.post('/api/auth/2fa/resend', formData, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    });
    return response.data;
  },

  // Request a magic-link sign-in email. Always returns {ok: true} from server.
  magicLinkRequest: async (email: string) => {
    const response = await api.post('/api/auth/magic-link/request', { email });
    return response.data;
  },

  // Consume a clicked magic-link token. POST (not GET) to prevent email
  // security scanners from preflight-consuming the single-use token.
  magicLinkConsume: async (token: string) => {
    const response = await api.post('/api/auth/magic-link/consume', { token });
    return response.data;
  },

  // Verify a 6-digit magic-link code entered manually.
  magicLinkVerify: async (email: string, code: string) => {
    const response = await api.post('/api/auth/magic-link/verify', { email, code });
    return response.data;
  },

  // Register new user (fastapi-users endpoint)
  register: async (name: string, email: string, password: string) => {
    // Check if there's a referrer in sessionStorage
    const referred_by = sessionStorage.getItem('referrer');

    const response = await api.post('/api/auth/register', {
      name,
      email,
      password,
      referral_code: referred_by || undefined,
    });
    return response.data;
  },

  // Get current user info
  getCurrentUser: async () => {
    const response = await api.get('/api/users/me');
    return response.data;
  },

  // Logout - clears both JWT token and cookie auth
  logout: async () => {
    await revokeServerSession();
    localStorage.removeItem('token');
  },

  // OAuth endpoints - Fetch the authorization URL from the backend
  getGithubAuthUrl: async () => {
    const response = await api.get('/api/auth/github/authorize');
    return response.data.authorization_url;
  },

  getGoogleAuthUrl: async () => {
    const response = await api.get('/api/auth/google/authorize');
    return response.data.authorization_url;
  },

  // Password reset
  forgotPassword: async (email: string) => {
    const response = await api.post('/api/auth/forgot-password', { email });
    return response.data;
  },

  resetPassword: async (token: string, password: string) => {
    const response = await api.post('/api/auth/reset-password', { token, password });
    return response.data;
  },

  /**
   * Silently refresh the auth token.
   * Delegates to the module-level refreshAuthToken (shared with the 401 interceptor).
   */
  refreshToken: async (): Promise<void> => {
    await refreshAuthToken();
  },
};

export const tasksApi = {
  getStatus: async (taskId: string) => {
    const response = await api.get(`/api/tasks/${taskId}/status`);
    return response.data;
  },
  getActiveTasks: async () => {
    const response = await api.get('/api/tasks/user/active');
    return response.data;
  },
  pollUntilComplete: async (
    taskId: string,
    interval = 1000,
    maxRetries = 300,
    timeout = 300000
  ): Promise<{ status: string; error?: string; result?: unknown }> => {
    return new Promise((resolve, reject) => {
      let retryCount = 0;
      const startTime = Date.now();

      const poll = async () => {
        try {
          // Check timeout
          if (Date.now() - startTime > timeout) {
            reject(new Error(`Task polling timeout after ${timeout}ms for task ${taskId}`));
            return;
          }

          // Check max retries
          if (retryCount >= maxRetries) {
            reject(
              new Error(`Task polling exceeded max retries (${maxRetries}) for task ${taskId}`)
            );
            return;
          }

          retryCount++;
          const task = await tasksApi.getStatus(taskId);

          if (task.status === 'completed') {
            resolve(task);
          } else if (task.status === 'failed' || task.status === 'cancelled') {
            reject(new Error(task.error || 'Task failed'));
          } else {
            setTimeout(poll, interval);
          }
        } catch (error) {
          reject(error);
        }
      };
      poll();
    });
  },
};

// ---------------------------------------------------------------------------
// Git / Repository panel response shapes
// ---------------------------------------------------------------------------

export interface GitAuthor {
  login: string | null;
  avatar_url: string | null;
  name: string | null;
  email: string | null;
  date: string | null;
}

export interface GitCommit {
  sha: string;
  short_sha: string;
  message: string;
  title: string;
  html_url: string | null;
  parents: string[];
  author: GitAuthor;
  committer: GitAuthor;
  files_changed: number | null;
}

// 'local' = repo has no GitHub remote; payload comes from local `git`.
// Tabs render the same shape but hide GitHub-specific affordances.
export type GitApiStatus = 'ready' | 'local' | 'no_remote' | 'error';

export interface GitCommitsResponse {
  status: GitApiStatus;
  message?: string;
  owner?: string;
  repo?: string;
  branch?: string | null;
  html_url?: string;
  commits?: GitCommit[];
}

export interface GitBranchSummary {
  name: string;
  is_default: boolean;
  protected: boolean;
  sha: string | null;
  html_url: string | null;
  ahead_by: number | null;
  behind_by: number | null;
}

export interface GitBranchesResponse {
  status: GitApiStatus;
  message?: string;
  owner?: string;
  repo?: string;
  default_branch?: string;
  html_url?: string;
  branches?: GitBranchSummary[];
}

export interface GitContributor {
  login: string | null;
  avatar_url: string | null;
  contributions: number | null;
  html_url: string | null;
}

export interface GitOpenPull {
  number: number;
  title: string;
  html_url: string | null;
  user: { login: string | null; avatar_url: string | null } | null;
  created_at: string | null;
  draft: boolean | null;
}

export interface GitRepoInfoResponse {
  status: GitApiStatus;
  message?: string;
  owner?: string;
  repo?: string;
  html_url?: string;
  description?: string | null;
  default_branch?: string;
  stars?: number | null;
  watchers?: number | null;
  forks?: number | null;
  open_issues?: number | null;
  pushed_at?: string | null;
  updated_at?: string | null;
  created_at?: string | null;
  is_private?: boolean | null;
  topics?: string[];
  contributors?: GitContributor[];
  open_pulls?: GitOpenPull[];
  open_pulls_count?: number;
}

export const projectsApi = {
  getAll: async (teamSlug?: string) => {
    const params = teamSlug ? { team: teamSlug } : {};
    const response = await api.get('/api/projects/', { params });
    return response.data;
  },
  getMyRole: async (projectSlug: string): Promise<{ role: string | null }> => {
    const response = await api.get(`/api/projects/${projectSlug}/my-role`);
    return response.data;
  },
  create: async (
    name: string,
    description?: string,
    sourceType?: 'template' | 'github' | 'gitlab' | 'bitbucket' | 'base',
    repoUrl?: string,
    branch?: string,
    baseId?: string,
    baseVersion?: string
  ) => {
    const body: {
      name: string;
      description?: string;
      source_type: string;
      github_repo_url?: string;
      github_branch?: string;
      git_repo_url?: string;
      git_branch?: string;
      base_id?: string;
      base_version?: string;
    } = {
      name,
      description,
      source_type: sourceType || 'base',
    };

    if (sourceType === 'github') {
      // Legacy GitHub support
      body.github_repo_url = repoUrl;
      body.github_branch = branch || 'main';
    } else if (sourceType === 'gitlab' || sourceType === 'bitbucket') {
      // New unified git provider support
      body.git_repo_url = repoUrl;
      body.git_branch = branch || 'main';
    } else if (sourceType === 'base') {
      body.base_id = baseId;
      if (baseVersion) {
        body.base_version = baseVersion;
      }
    }

    const response = await api.post('/api/projects/', body);
    // Response now includes { project, task_id, status_endpoint }
    return response.data;
  },
  get: async (slug: string) => {
    const response = await api.get(`/api/projects/${slug}`);
    return response.data;
  },
  setProjectKind: async (slug: string, kind: 'workspace' | 'app_source') => {
    const response = await api.patch(`/api/projects/${slug}/project-kind`, {
      project_kind: kind,
    });
    return response.data;
  },
  delete: async (slug: string) => {
    const response = await api.delete(`/api/projects/${slug}`);
    // Response now includes { task_id, status_endpoint }
    return response.data;
  },
  getFiles: async (slug: string) => {
    const response = await api.get(`/api/projects/${slug}/files`);
    return response.data;
  },
  getFileTree: async (slug: string, containerDir?: string) => {
    const params = containerDir ? { container_dir: containerDir } : {};

    const poll = async (
      retries: number
    ): Promise<
      Array<{
        path: string;
        name: string;
        is_dir: boolean;
        size: number;
        mod_time: number;
      }>
    > => {
      const response = await api.get(`/api/projects/${slug}/files/tree`, { params });
      const data = response.data;

      // Envelope response: {status, files, message}
      if (data && typeof data === 'object' && 'status' in data) {
        if (data.status === 'restoring' && retries > 0) {
          await new Promise((r) => setTimeout(r, 3000));
          return poll(retries - 1);
        }
        if (data.status === 'unavailable') {
          throw new Error(data.message || 'Project storage is unavailable');
        }
        return data.files || [];
      }

      // Backward compat: plain array (Docker mode)
      if (Array.isArray(data)) {
        return data;
      }

      return [];
    };

    return poll(20);
  },
  getGitTree: async (slug: string, branch?: string) => {
    const params: Record<string, string> = {};
    if (branch) params.branch = branch;
    const response = await api.get(`/api/projects/${slug}/git/tree`, { params });
    return response.data as {
      status: string;
      source: 'github' | 'local';
      owner: string | null;
      repo: string | null;
      branch: string | null;
      sha: string | null;
      truncated: boolean;
      html_url: string | null;
      files: Array<{
        path: string;
        name: string;
        is_dir: boolean;
        size: number;
        mod_time: number;
        sha?: string;
      }>;
    };
  },
  getGitCommits: async (
    slug: string,
    opts?: { branch?: string; limit?: number; includeStats?: boolean }
  ): Promise<GitCommitsResponse> => {
    const params: Record<string, string | number | boolean> = {};
    if (opts?.branch) params.branch = opts.branch;
    if (typeof opts?.limit === 'number') params.limit = opts.limit;
    if (opts?.includeStats) params.include_stats = true;
    const response = await api.get(`/api/projects/${slug}/git/commits`, { params });
    return response.data as GitCommitsResponse;
  },
  getGitBranches: async (slug: string): Promise<GitBranchesResponse> => {
    const response = await api.get(`/api/projects/${slug}/git/branches`);
    return response.data as GitBranchesResponse;
  },
  getGitRepoInfo: async (slug: string): Promise<GitRepoInfoResponse> => {
    const response = await api.get(`/api/projects/${slug}/git/repo-info`);
    return response.data as GitRepoInfoResponse;
  },
  getFileContent: async (slug: string, path: string, containerDir?: string) => {
    const params: Record<string, string> = { path };
    if (containerDir) params.container_dir = containerDir;
    const response = await api.get(`/api/projects/${slug}/files/content`, { params });
    const data = response.data;

    // Envelope response
    if (data && typeof data === 'object' && 'status' in data) {
      if (data.status === 'restoring') {
        throw new Error(data.message || 'Project storage is being restored');
      }
      if (data.status === 'unavailable') {
        throw new Error(data.message || 'Project storage is unavailable');
      }
      // Strip status envelope for ready response
      const { status: _s, message: _m, ...rest } = data;
      return rest as { path: string; content: string; size: number };
    }

    return data as { path: string; content: string; size: number };
  },
  getFileContentBatch: async (slug: string, paths: string[], containerDir?: string) => {
    const params = containerDir ? { container_dir: containerDir } : {};
    const response = await api.post(
      `/api/projects/${slug}/files/content/batch`,
      { paths },
      { params }
    );
    const data = response.data;

    // Envelope response
    if (data && typeof data === 'object' && 'status' in data) {
      if (data.status === 'restoring') {
        throw new Error(data.message || 'Project storage is being restored');
      }
      if (data.status === 'unavailable') {
        throw new Error(data.message || 'Project storage is unavailable');
      }
    }

    return data as {
      files: Array<{ path: string; content: string; size: number }>;
      errors: string[];
    };
  },
  getDevServerUrl: async (slug: string) => {
    const response = await api.get(`/api/projects/${slug}/dev-server-url`);
    return response.data;
  },
  startDevContainer: async (slug: string) => {
    const response = await api.post(`/api/projects/${slug}/start-dev-container`);
    // Response now includes { task_id, status_endpoint }
    return response.data;
  },
  restartDevServer: async (slug: string) => {
    const response = await api.post(`/api/projects/${slug}/restart-dev-container`);
    return response.data;
  },
  stopDevServer: async (slug: string) => {
    const response = await api.post(`/api/projects/${slug}/stop-dev-container`);
    return response.data;
  },
  getContainerStatus: async (slug: string) => {
    const response = await api.get(`/api/projects/${slug}/container-status`);
    return response.data;
  },
  saveFile: async (slug: string, filePath: string, content: string) => {
    const response = await api.post(`/api/projects/${slug}/files/save`, {
      file_path: filePath,
      content: content,
    });
    return response.data;
  },
  deleteFile: async (slug: string, filePath: string, isDirectory = false) => {
    const response = await api.delete(`/api/projects/${slug}/files`, {
      data: { file_path: filePath, is_directory: isDirectory },
    });
    return response.data;
  },
  renameFile: async (slug: string, oldPath: string, newPath: string) => {
    const response = await api.post(`/api/projects/${slug}/files/rename`, {
      old_path: oldPath,
      new_path: newPath,
    });
    return response.data;
  },
  createDirectory: async (slug: string, dirPath: string) => {
    const response = await api.post(`/api/projects/${slug}/files/mkdir`, {
      dir_path: dirPath,
    });
    return response.data;
  },
  getSettings: async (slug: string) => {
    const response = await api.get(`/api/projects/${slug}/settings`);
    return response.data;
  },
  updateSettings: async (slug: string, settings: Record<string, unknown>) => {
    const response = await api.patch(`/api/projects/${slug}/settings`, { settings });
    return response.data;
  },
  exportAsTemplate: async (
    slug: string,
    data: {
      name: string;
      description: string;
      category: string;
      visibility?: string;
      icon?: string;
      tags?: string[];
      tech_stack?: string[];
      features?: string[];
      long_description?: string;
    }
  ) => {
    const response = await api.post(`/api/projects/${slug}/export-template`, data);
    return response.data;
  },
  forkProject: async (id: string) => {
    const response = await api.post(`/api/projects/${id}/fork`);
    return response.data;
  },
  hibernateProject: async (slug: string) => {
    const response = await api.post(`/api/projects/${slug}/hibernate`);
    return response.data;
  },
  getContainers: async (slug: string) => {
    const response = await api.get(`/api/projects/${slug}/containers`);
    return response.data;
  },
  getContainersRuntimeStatus: async (slug: string) => {
    const response = await api.get(`/api/projects/${slug}/containers/status`);
    return response.data;
  },
  startAllContainers: async (slug: string) => {
    const response = await api.post(`/api/projects/${slug}/containers/start-all`);
    return response.data;
  },
  stopAllContainers: async (slug: string) => {
    const response = await api.post(`/api/projects/${slug}/containers/stop-all`);
    return response.data;
  },
  startContainer: async (slug: string, containerId: string) => {
    const response = await api.post(`/api/projects/${slug}/containers/${containerId}/start`);
    const data = response.data;

    // FAST PATH: Container already running (Docker mode returns task_id: null)
    if (data.already_running && data.url) {
      return {
        url: data.url,
        container_name: data.container_name,
        message: data.message,
        task_id: null,
        already_running: true,
      };
    }

    const { task_id, already_started } = data;

    if (already_started) {
      console.log('[Container Start] Reusing existing task:', task_id);
    }

    const completedTask = await tasksApi.pollUntilComplete(task_id);

    if (completedTask.status !== 'completed') {
      throw new Error(completedTask.error || 'Container start failed');
    }

    return {
      ...(completedTask.result ?? {}),
      message: data.message,
      task_id,
    };
  },
  stopContainer: async (slug: string, containerId: string) => {
    const response = await api.post(`/api/projects/${slug}/containers/${containerId}/stop`);
    return response.data;
  },
  getContainersStatus: async (slug: string) => {
    const response = await api.get(`/api/projects/${slug}/containers/status`);
    return response.data;
  },
  downloadTesslateFolder: async (slug: string): Promise<Blob> => {
    const response = await api.get(`/api/projects/${slug}/download-tesslate`, {
      responseType: 'blob',
    });
    return response.data;
  },
  checkContainerHealth: async (
    slug: string,
    containerId: string
  ): Promise<{ healthy: boolean; status_code?: number; url?: string; error?: string }> => {
    try {
      const response = await api.get(`/api/projects/${slug}/containers/${containerId}/health`);
      return response.data;
    } catch (error) {
      return {
        healthy: false,
        error: error instanceof Error ? error.message : 'Health check failed',
      };
    }
  },
  assignDeploymentTarget: async (slug: string, containerId: string, provider: string | null) => {
    const response = await api.patch(
      `/api/projects/${slug}/containers/${containerId}/deployment-target`,
      {
        provider,
      }
    );
    return response.data;
  },
};

// ── Design view: OID indexing & AST code write-back ─────────────────────

export interface DesignIndexEntry {
  path: string;
  tag_name: string;
  start_line: number | null;
  start_col: number | null;
  end_line: number | null;
  end_col: number | null;
  component: string | null;
  dynamic_type: 'array' | 'conditional' | null;
}

export interface DesignIndex {
  [oid: string]: DesignIndexEntry;
}

export interface CodeDiffStructureChange {
  type: 'insert';
  location?: 'append' | 'prepend' | number;
  element: {
    tag_name: string;
    classes?: string;
    text?: string;
    oid?: string;
    attributes?: Record<string, string | number | boolean | null>;
    self_closing?: boolean;
  };
}

export interface CodeDiffRequest {
  oid: string;
  /** Generic JSX attributes (className, id, aria-*, data-*). */
  attributes?: Record<string, string | number | boolean | null>;
  /** When true, className is replaced wholesale instead of tailwind-merged. */
  override_classes?: boolean;
  /** CSS properties to merge into the element's `style={{...}}` prop.
   *  Keys are CSS (kebab-case) and will be converted to JSX camelCase.
   *  Empty/null values remove the key. */
  style_patch?: Record<string, string | number | null>;
  text_content?: string | null;
  structure_changes?: CodeDiffStructureChange[];
  /** Wrap this element in a new parent (group action). */
  wrap_with?: {
    tag_name: string;
    classes?: string;
    oid?: string;
  };
  remove?: boolean;
}

export const designApi = {
  /**
   * Scan the project source, inject data-oid attributes, and build the
   * oid → metadata index. Idempotent. Should be called the first time a
   * user opens the design view for a project.
   */
  indexProject: async (slug: string) => {
    const response = await api.post(`/api/projects/${slug}/design/index`);
    return response.data as {
      index: DesignIndex;
      file_count: number;
      modified_count: number;
      read_errors: string[];
      file_errors: Array<{ path: string; error: string }>;
    };
  },

  /**
   * Return the cached design index. Fast — reads .tesslate/design-index.json.
   */
  getIndex: async (slug: string) => {
    const response = await api.get(`/api/projects/${slug}/design/index`);
    return response.data as { index: DesignIndex };
  },

  /**
   * Apply a batch of CodeDiffRequests to the project source. The server
   * resolves each oid to its source file via the index, groups the
   * requests per file, and runs the AST worker.
   */
  applyDiff: async (slug: string, requests: CodeDiffRequest[]) => {
    const response = await api.post(`/api/projects/${slug}/design/apply-diff`, {
      requests,
    });
    return response.data as {
      modified: string[];
      unknown_oids: string[];
      read_errors: string[];
      file_errors: Array<{ path: string; error: string }>;
    };
  },
};

export const chatApi = {
  create: async (projectId?: string) => {
    const response = await api.post('/api/chat/', { project_id: projectId });
    return response.data;
  },
  getAll: async () => {
    const response = await api.get('/api/chat/');
    return response.data;
  },
  getProjectMessages: async (projectId: string) => {
    const response = await api.get(`/api/chat/${projectId}/messages`);
    return response.data;
  },
  clearProjectMessages: async (projectId: string, chatId?: string) => {
    const response = await api.delete(`/api/chat/${projectId}/messages`, {
      params: chatId ? { chat_id: chatId } : undefined,
    });
    return response.data;
  },
  sendAgentMessage: async (request: AgentChatRequest): Promise<AgentChatResponse> => {
    const response = await api.post('/api/chat/agent', request);
    return response.data;
  },
  sendAgentMessageStreaming: async (
    request: AgentChatRequest,
    onEvent: (event: { type: string; data: Record<string, unknown> }) => void,
    signal?: AbortSignal
  ): Promise<void> => {
    const response = await fetch(`${API_URL}/api/chat/agent/stream`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify(request),
      credentials: 'include', // Include cookies for OAuth-based authentication
      signal, // Pass abort signal
    });

    // Handle 401 by redirecting to login
    if (response.status === 401) {
      localStorage.removeItem('token');
      window.location.href = '/login';
      throw new Error('Authentication required');
    }

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error('Response body is not readable');
    }

    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();

        if (done) break;

        // Decode chunk and add to buffer
        buffer += decoder.decode(value, { stream: true });

        // Process complete lines (SSE format: "data: {JSON}\n\n")
        const lines = buffer.split('\n\n');
        buffer = lines.pop() || ''; // Keep incomplete line in buffer

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const jsonStr = line.slice(6); // Remove "data: " prefix
            let event;
            try {
              event = JSON.parse(jsonStr);
            } catch (e) {
              console.error('Failed to parse SSE event:', e, jsonStr);
              continue;
            }
            // Call onEvent outside the try/catch so errors thrown by the
            // callback (e.g. agent error events) propagate to the caller
            // instead of being swallowed as JSON parse errors.
            onEvent(event);
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
  },
  sendApprovalResponse: async (
    approvalId: string,
    response: 'allow_once' | 'allow_all' | 'stop'
  ): Promise<void> => {
    await api.post('/api/chat/agent/approval', {
      approval_id: approvalId,
      response: response,
    });
  },

  // Cancel a running agent task
  cancelAgentTask: async (taskId: string) => {
    const response = await api.post(`/api/chat/agent/cancel/${taskId}`);
    return response.data;
  },

  // Force-cancel a stuck agent and release the chat lock
  forceCancelAgent: async (chatId: string) => {
    const response = await api.post(`/api/chat/agent/force-cancel?chat_id=${chatId}`);
    return response.data;
  },

  // Check for active agent task on a project (optionally scoped to a chat session)
  getActiveTask: async (projectId: string, chatId?: string) => {
    const params: Record<string, string> = { project_id: projectId };
    if (chatId) params.chat_id = chatId;
    const response = await api.get('/api/chat/agent/active', { params });
    return response.data;
  },

  // List ALL active agent tasks across a project's chat sessions.
  // Powers the sidebar's live run-state dots and cold-start reconnect.
  getActiveTasksInProject: async (
    projectId: string
  ): Promise<{ tasks: { task_id: string; chat_id: string; title: string | null }[] }> => {
    const response = await api.get('/api/chat/agent/active-in-project', {
      params: { project_id: projectId },
    });
    return response.data;
  },

  // Subscribe to agent events (SSE) for reconnection
  subscribeToTask: (taskId: string, lastEventId?: string) => {
    const params = lastEventId ? `?last_event_id=${lastEventId}` : '';
    const url = `${API_URL}/api/chat/agent/events/${taskId}${params}`;
    return new EventSource(url, { withCredentials: true });
  },

  // Multiplexed SSE for every active chat in a project — one connection.
  // Used as a fallback when the client has too many per-task streams open
  // (browsers cap SSE to ~6 per origin).
  subscribeToProject: (projectId: string) => {
    const url = `${API_URL}/api/chat/agent/stream-project?project_id=${encodeURIComponent(
      projectId
    )}`;
    return new EventSource(url, { withCredentials: true });
  },

  // List chat sessions for a project
  getProjectSessions: async (projectId: string) => {
    const response = await api.get(`/api/chat/${projectId}/sessions`);
    return response.data;
  },

  // Update a chat session
  updateChatSession: async (chatId: string, data: { title?: string; status?: string }) => {
    const response = await api.patch(`/api/chat/${chatId}/update`, data);
    return response.data;
  },

  // Get messages for a specific chat session
  getSessionMessages: async (projectId: string, chatId?: string) => {
    const params = chatId ? { chat_id: chatId } : {};
    const response = await api.get(`/api/chat/${projectId}/messages`, { params });
    return response.data;
  },

  // List standalone (project-less) chat sessions
  getUserSessions: async (params?: { limit?: number; offset?: number }) => {
    const response = await api.get('/api/chat/sessions', { params });
    return response.data;
  },

  // Update a chat's connected project
  updateChatProject: async (chatId: string, projectId: string | null) => {
    const response = await api.patch(`/api/chat/${chatId}/project`, { project_id: projectId });
    return response.data;
  },

  // Get messages for a standalone chat session
  getStandaloneMessages: async (chatId: string) => {
    const response = await api.get(`/api/chat/session/${chatId}/messages`);
    return response.data;
  },

  deleteChat: async (chatId: string) => {
    const response = await api.delete(`/api/chat/${chatId}`);
    return response.data;
  },

  undoLastExchange: async (
    chatId: string
  ): Promise<{
    success: boolean;
    removed_count: number;
    removed_ids: string[];
    last_user_message: string | null;
    files_reverted?: boolean;
  }> => {
    const response = await api.post(`/api/chat/${chatId}/undo`);
    return response.data;
  },

  compactChat: async (
    chatId: string
  ): Promise<{
    success: boolean;
    before_count?: number;
    after_count?: number;
    summary?: string;
    detail?: string;
  }> => {
    const response = await api.post(`/api/chat/${chatId}/compact`);
    return response.data;
  },

  // Debug: List available tools (admin only)
  debugListTools: async (): Promise<
    Array<{
      name: string;
      description: string;
      parameters: Record<string, unknown>;
      category: string;
    }>
  > => {
    const response = await api.get('/api/chat/debug/tools');
    return response.data;
  },

  // Debug: Execute a tool directly (admin only)
  debugExecuteTool: async (
    projectId: number | string,
    toolName: string,
    parameters: Record<string, unknown>
  ): Promise<{ success: boolean; tool: string; result?: unknown; error?: string }> => {
    const response = await api.post('/api/chat/debug/tool-execute', {
      project_id: projectId,
      tool_name: toolName,
      parameters,
    });
    return response.data;
  },
};

export interface SidebarChat {
  id: string;
  title: string;
  status: string;
  origin: string;
  project_id: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface SidebarProject {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  visibility: string | null;
  runtime: string | null;
  created_at: string | null;
  updated_at: string | null;
  latest_activity_at: string | null;
  chats: SidebarChat[];
}

export interface SidebarTreeResponse {
  rootChats: SidebarChat[];
  projects: SidebarProject[];
}

export const sidebarApi = {
  /** Single-round-trip fetch for the left-nav tree (projects + their chats + root chats). */
  getTree: async (
    opts: {
      projectLimit?: number;
      rootChatLimit?: number;
      chatsPerProject?: number;
    } = {}
  ): Promise<SidebarTreeResponse> => {
    const params: Record<string, number> = {};
    if (opts.projectLimit !== undefined) params.project_limit = opts.projectLimit;
    if (opts.rootChatLimit !== undefined) params.root_chat_limit = opts.rootChatLimit;
    if (opts.chatsPerProject !== undefined) params.chats_per_project = opts.chatsPerProject;
    const response = await api.get('/api/sidebar/tree', { params });
    return response.data as SidebarTreeResponse;
  },
};

export const nodeConfigApi = {
  /** Submit form values for a pending agent `user_input_required`. */
  submit: async (inputId: string, values: SubmittedValues): Promise<void> => {
    await api.post(`/api/chat/node-config/${inputId}/submit`, { values });
  },

  /** Cancel a pending agent `user_input_required`. */
  cancel: async (inputId: string): Promise<void> => {
    await api.post(`/api/chat/node-config/${inputId}/cancel`);
  },

  /** Fetch current config (schema + values) for a container. */
  getContainerConfig: async (
    projectId: string,
    containerId: string
  ): Promise<ContainerConfigResponse> => {
    const response = await api.get(`/api/projects/${projectId}/containers/${containerId}/config`);
    return response.data;
  },

  /** Apply a direct (non-agent) edit to a container's config. */
  patchContainerConfig: async (
    projectId: string,
    containerId: string,
    body: {
      values: SubmittedValues;
      overrides?: Record<string, unknown>;
      preset?: string;
      mode?: NodeConfigMode;
    }
  ): Promise<void> => {
    await api.patch(`/api/projects/${projectId}/containers/${containerId}/config`, body);
  },

  /** Reveal the plaintext of a single encrypted secret (user-scoped). */
  revealSecret: async (
    projectId: string,
    containerId: string,
    key: string
  ): Promise<RevealSecretResponse> => {
    const response = await api.post(
      `/api/projects/${projectId}/containers/${containerId}/secrets/${encodeURIComponent(
        key
      )}/reveal`
    );
    return response.data;
  },
};

export interface ScopeOption {
  value: string;
  label: string;
  category: string;
}

export const externalApi = {
  // API key management
  createKey: async (data: {
    name: string;
    scopes?: string[];
    project_ids?: string[];
    expires_in_days?: number;
  }) => {
    const response = await api.post('/api/external/keys', data);
    return response.data;
  },

  listKeys: async () => {
    const response = await api.get('/api/external/keys');
    return response.data;
  },

  deleteKey: async (keyId: string) => {
    const response = await api.delete(`/api/external/keys/${keyId}`);
    return response.data;
  },

  listScopes: async (): Promise<ScopeOption[]> => {
    const response = await api.get('/api/external/keys/scopes');
    return response.data;
  },
};

export const marketplaceApi = {
  // Get all marketplace agents with optional filtering and request cancellation
  getAllAgents: async (
    params?: {
      category?: string;
      pricing_type?: string;
      search?: string;
      sort?: string;
      page?: number;
      limit?: number;
    },
    options?: { signal?: AbortSignal }
  ) => {
    const queryParams = new URLSearchParams();
    if (params?.category) queryParams.append('category', params.category);
    if (params?.pricing_type) queryParams.append('pricing_type', params.pricing_type);
    if (params?.search) queryParams.append('search', params.search);
    if (params?.sort) queryParams.append('sort', params.sort);
    if (params?.page) queryParams.append('page', params.page.toString());
    if (params?.limit) queryParams.append('limit', params.limit.toString());

    const queryString = queryParams.toString();
    const response = await api.get(
      `/api/marketplace/agents${queryString ? `?${queryString}` : ''}`,
      { signal: options?.signal }
    );
    return response.data;
  },

  // Get user's purchased agents
  getMyAgents: async () => {
    const response = await api.get('/api/marketplace/my-agents');
    return response.data;
  },

  // Get agents that are currently added to a specific project
  getProjectAgents: async (projectId: string): Promise<Agent[]> => {
    const response = await api.get(`/api/marketplace/projects/${projectId}/agents`);
    return response.data.agents || [];
  },

  // Purchase/add agent to account
  purchaseAgent: async (agentId: string) => {
    const response = await api.post(`/api/marketplace/agents/${agentId}/purchase`);
    return response.data;
  },

  // Get agent details including system prompt
  getAgentDetails: async (slug: string) => {
    const response = await api.get(`/api/marketplace/agents/${slug}`);
    return response.data;
  },

  // Get related agents (recommendations based on co-installs)
  getRelatedAgents: async (slug: string, limit: number = 6) => {
    const response = await api.get(`/api/marketplace/agents/${slug}/related`, {
      params: { limit },
    });
    return response.data.related_agents || [];
  },

  // Fork an open source agent
  forkAgent: async (
    agentId: string,
    customizations?: {
      name?: string;
      description?: string;
      system_prompt?: string;
      model?: string;
    }
  ) => {
    const response = await api.post(
      `/api/marketplace/agents/${agentId}/fork`,
      customizations || {}
    );
    return response.data;
  },

  // Create a custom agent from scratch
  createCustomAgent: async (data: {
    name: string;
    description: string;
    system_prompt: string;
    mode: string;
    agent_type: string;
    model: string;
  }) => {
    const response = await api.post('/api/marketplace/agents/create', data);
    return response.data;
  },

  // Update a custom/forked agent
  updateAgent: async (
    agentId: string,
    data: {
      name?: string;
      description?: string;
      system_prompt?: string;
      model?: string;
      tools?: string[];
      tool_configs?: Record<string, { description?: string; examples?: string[] }>;
      avatar_url?: string | null;
      config?: Record<string, unknown>;
    }
  ) => {
    const response = await api.patch(`/api/marketplace/agents/${agentId}`, data);
    return response.data;
  },

  // Toggle agent enabled/disabled status
  toggleAgent: async (agentId: string, enabled: boolean) => {
    const response = await api.post(`/api/marketplace/agents/${agentId}/toggle?enabled=${enabled}`);
    return response.data;
  },

  // Remove agent from library
  removeFromLibrary: async (agentId: string) => {
    const response = await api.delete(`/api/marketplace/agents/${agentId}/library`);
    return response.data;
  },

  // Permanently delete a custom/forked agent
  deleteCustomAgent: async (agentId: string) => {
    const response = await api.delete(`/api/marketplace/agents/${agentId}`);
    return response.data;
  },

  // Verify Stripe purchase and add to library
  verifyPurchase: async (sessionId: string, agentSlug?: string) => {
    const response = await api.post('/api/marketplace/verify-purchase', {
      session_id: sessionId,
      agent_slug: agentSlug,
    });
    return response.data;
  },

  // Get available models from LITELLM_DEFAULT_MODELS
  getAvailableModels: async () => {
    const response = await api.get('/api/marketplace/models');
    return response.data;
  },

  // Select a model for an agent in user's library
  selectAgentModel: async (agentId: string, model: string) => {
    const response = await api.post(`/api/marketplace/agents/${agentId}/select-model`, { model });
    return response.data;
  },

  // Add custom model to a provider
  addCustomModel: async (data: {
    model_id: string;
    model_name: string;
    provider?: string;
    pricing_input?: number;
    pricing_output?: number;
  }) => {
    const response = await api.post('/api/marketplace/models/custom', data);
    return response.data;
  },

  // Delete custom model
  deleteCustomModel: async (modelId: string) => {
    const response = await api.delete(`/api/marketplace/models/custom/${modelId}`);
    return response.data;
  },

  // Publish agent to community marketplace
  publishAgent: async (agentId: number) => {
    const response = await api.post(`/api/marketplace/agents/${agentId}/publish`);
    return response.data;
  },

  // Unpublish agent from community marketplace
  unpublishAgent: async (agentId: number) => {
    const response = await api.post(`/api/marketplace/agents/${agentId}/unpublish`);
    return response.data;
  },

  // Bases endpoints
  getAllBases: async (
    params?: {
      category?: string;
      pricing_type?: string;
      search?: string;
      sort?: string;
      page?: number;
      limit?: number;
    },
    options?: { signal?: AbortSignal }
  ) => {
    const queryParams = new URLSearchParams();
    if (params?.category) queryParams.append('category', params.category);
    if (params?.pricing_type) queryParams.append('pricing_type', params.pricing_type);
    if (params?.search) queryParams.append('search', params.search);
    if (params?.sort) queryParams.append('sort', params.sort);
    if (params?.page) queryParams.append('page', params.page.toString());
    if (params?.limit) queryParams.append('limit', params.limit.toString());

    const response = await api.get(`/api/marketplace/bases?${queryParams}`, {
      signal: options?.signal,
    });
    return response.data;
  },

  getBaseDetails: async (slug: string) => {
    const response = await api.get(`/api/marketplace/bases/${slug}`);
    return response.data;
  },

  getBaseVersions: async (slug: string) => {
    const response = await api.get(`/api/marketplace/bases/${slug}/versions`);
    return response.data;
  },

  purchaseBase: async (baseId: string) => {
    const response = await api.post(`/api/marketplace/bases/${baseId}/purchase`);
    return response.data;
  },

  getUserBases: async () => {
    const response = await api.get('/api/marketplace/my-bases');
    return response.data;
  },

  submitBase: async (data: {
    name: string;
    description: string;
    git_repo_url: string;
    category: string;
    default_branch?: string;
    visibility?: string;
    long_description?: string;
    icon?: string;
    tags?: string[];
    features?: string[];
    tech_stack?: string[];
  }) => {
    const response = await api.post('/api/marketplace/bases/submit', data);
    return response.data;
  },

  updateBase: async (baseId: string, data: Record<string, unknown>) => {
    const response = await api.patch(`/api/marketplace/bases/${baseId}`, data);
    return response.data;
  },

  setBaseVisibility: async (baseId: string, visibility: 'private' | 'public') => {
    const response = await api.patch(`/api/marketplace/bases/${baseId}/visibility`, { visibility });
    return response.data;
  },

  deleteBase: async (baseId: string) => {
    const response = await api.delete(`/api/marketplace/bases/${baseId}`);
    return response.data;
  },

  getMyCreatedBases: async () => {
    const response = await api.get('/api/marketplace/my-created-bases');
    return response.data;
  },

  // Get user's agent subscriptions
  getUserSubscriptions: async () => {
    const response = await api.get('/api/marketplace/subscriptions');
    return response.data;
  },

  // Cancel an agent subscription
  cancelAgentSubscription: async (subscriptionId: string) => {
    const response = await api.post(`/api/marketplace/subscriptions/${subscriptionId}/cancel`);
    return response.data;
  },

  // Renew a cancelled agent subscription
  renewAgentSubscription: async (subscriptionId: string) => {
    const response = await api.post(`/api/marketplace/subscriptions/${subscriptionId}/renew`);
    return response.data;
  },

  // Get reviews for an agent
  getAgentReviews: async (agentId: string, params?: { page?: number; limit?: number }) => {
    const queryParams = new URLSearchParams();
    if (params?.page) queryParams.append('page', params.page.toString());
    if (params?.limit) queryParams.append('limit', params.limit.toString());
    const response = await api.get(`/api/marketplace/agents/${agentId}/reviews?${queryParams}`);
    return response.data;
  },

  // Create or update a review for an agent
  createAgentReview: async (agentId: string, rating: number, comment?: string) => {
    const queryParams = new URLSearchParams();
    queryParams.append('rating', rating.toString());
    if (comment) queryParams.append('comment', comment);
    const response = await api.post(`/api/marketplace/agents/${agentId}/review?${queryParams}`);
    return response.data;
  },

  // Delete user's review for an agent
  deleteAgentReview: async (agentId: string) => {
    const response = await api.delete(`/api/marketplace/agents/${agentId}/review`);
    return response.data;
  },

  // Get reviews for a base
  getBaseReviews: async (baseId: string, params?: { page?: number; limit?: number }) => {
    const queryParams = new URLSearchParams();
    if (params?.page) queryParams.append('page', params.page.toString());
    if (params?.limit) queryParams.append('limit', params.limit.toString());
    const response = await api.get(`/api/marketplace/bases/${baseId}/reviews?${queryParams}`);
    return response.data;
  },

  // Create or update a review for a base
  createBaseReview: async (baseId: string, rating: number, comment?: string) => {
    const queryParams = new URLSearchParams();
    queryParams.append('rating', rating.toString());
    if (comment) queryParams.append('comment', comment);
    const response = await api.post(`/api/marketplace/bases/${baseId}/review?${queryParams}`);
    return response.data;
  },

  // Delete user's review for a base
  deleteBaseReview: async (baseId: string) => {
    const response = await api.delete(`/api/marketplace/bases/${baseId}/review`);
    return response.data;
  },

  // Subagent management
  getSubagents: async (agentId: string) => {
    const response = await api.get(`/api/marketplace/agents/${agentId}/subagents`);
    return response.data;
  },

  createSubagent: async (
    agentId: string,
    data: {
      name: string;
      description: string;
      system_prompt: string;
      tools?: string[];
      model?: string;
    }
  ) => {
    const response = await api.post(`/api/marketplace/agents/${agentId}/subagents`, data);
    return response.data;
  },

  updateSubagent: async (
    agentId: string,
    subagentId: string,
    data: {
      name?: string;
      description?: string;
      system_prompt?: string;
      tools?: string[];
      model?: string;
    }
  ) => {
    const response = await api.patch(
      `/api/marketplace/agents/${agentId}/subagents/${subagentId}`,
      data
    );
    return response.data;
  },

  deleteSubagent: async (agentId: string, subagentId: string) => {
    const response = await api.delete(`/api/marketplace/agents/${agentId}/subagents/${subagentId}`);
    return response.data;
  },

  // Theme marketplace endpoints
  getMarketplaceThemes: async (params?: {
    category?: string;
    mode?: string;
    pricing?: string;
    search?: string;
    sort?: string;
    page?: number;
    limit?: number;
  }) => {
    const queryParams = new URLSearchParams();
    if (params?.category) queryParams.append('category', params.category);
    if (params?.mode) queryParams.append('mode', params.mode);
    if (params?.pricing) queryParams.append('pricing', params.pricing);
    if (params?.search) queryParams.append('search', params.search);
    if (params?.sort) queryParams.append('sort', params.sort);
    if (params?.page) queryParams.append('page', params.page.toString());
    if (params?.limit) queryParams.append('limit', params.limit.toString());
    const response = await api.get(`/api/marketplace/themes?${queryParams}`);
    return response.data;
  },

  getThemeDetail: async (slug: string) => {
    const response = await api.get(`/api/marketplace/themes/${slug}`);
    return response.data;
  },

  getUserLibraryThemes: async () => {
    const response = await api.get('/api/marketplace/my-themes');
    return response.data;
  },

  addThemeToLibrary: async (themeId: string) => {
    const response = await api.post(`/api/marketplace/themes/${themeId}/add`);
    return response.data;
  },

  removeThemeFromLibrary: async (themeId: string) => {
    const response = await api.delete(`/api/marketplace/themes/${themeId}/remove`);
    return response.data;
  },

  toggleTheme: async (themeId: string, enabled: boolean) => {
    const response = await api.post(`/api/marketplace/themes/${themeId}/toggle`, { enabled });
    return response.data;
  },

  createCustomTheme: async (data: {
    name: string;
    description?: string;
    mode?: string;
    theme_json: Record<string, unknown>;
    icon?: string;
    category?: string;
    tags?: string[];
  }) => {
    const response = await api.post('/api/marketplace/themes/create', data);
    return response.data;
  },

  updateTheme: async (themeId: string, data: Record<string, unknown>) => {
    const response = await api.patch(`/api/marketplace/themes/${themeId}`, data);
    return response.data;
  },

  deleteTheme: async (themeId: string) => {
    const response = await api.delete(`/api/marketplace/themes/${themeId}`);
    return response.data;
  },

  publishTheme: async (themeId: string) => {
    const response = await api.post(`/api/marketplace/themes/${themeId}/publish`);
    return response.data;
  },

  unpublishTheme: async (themeId: string) => {
    const response = await api.post(`/api/marketplace/themes/${themeId}/unpublish`);
    return response.data;
  },

  forkTheme: async (themeId: string, data?: Record<string, unknown>) => {
    const response = await api.post(`/api/marketplace/themes/${themeId}/fork`, data || {});
    return response.data;
  },

  // Skills marketplace endpoints
  getAllSkills: async (
    params?: {
      category?: string;
      pricing_type?: string;
      search?: string;
      sort?: string;
      page?: number;
      limit?: number;
    },
    options?: { signal?: AbortSignal }
  ) => {
    const queryParams = new URLSearchParams();
    if (params?.category) queryParams.append('category', params.category);
    if (params?.pricing_type) queryParams.append('pricing_type', params.pricing_type);
    if (params?.search) queryParams.append('search', params.search);
    if (params?.sort) queryParams.append('sort', params.sort);
    if (params?.page) queryParams.append('page', params.page.toString());
    if (params?.limit) queryParams.append('limit', params.limit.toString());

    const queryString = queryParams.toString();
    const response = await api.get(
      `/api/marketplace/skills${queryString ? `?${queryString}` : ''}`,
      { signal: options?.signal }
    );
    return response.data;
  },

  // MCP Servers marketplace endpoints
  getAllMcpServers: async (
    params?: {
      category?: string;
      pricing_type?: string;
      search?: string;
      sort?: string;
      page?: number;
      limit?: number;
    },
    options?: { signal?: AbortSignal }
  ) => {
    const queryParams = new URLSearchParams();
    if (params?.category) queryParams.append('category', params.category);
    if (params?.pricing_type) queryParams.append('pricing_type', params.pricing_type);
    if (params?.search) queryParams.append('search', params.search);
    if (params?.sort) queryParams.append('sort', params.sort);
    if (params?.page) queryParams.append('page', params.page.toString());
    if (params?.limit) queryParams.append('limit', params.limit.toString());
    const query = queryParams.toString();
    const response = await api.get(`/api/marketplace/mcp-servers${query ? `?${query}` : ''}`, {
      signal: options?.signal,
    });
    return response.data;
  },

  getMcpServerDetails: async (slug: string) => {
    const response = await api.get(`/api/marketplace/mcp-servers/${slug}`);
    return response.data;
  },

  // MCP install/manage (separate from marketplace browse)
  installMcpServer: async (
    marketplaceAgentId: string,
    credentials?: Record<string, string>,
    opts?: { scope_level?: 'user' | 'project'; project_id?: string }
  ) => {
    const response = await api.post('/api/mcp/install', {
      marketplace_agent_id: marketplaceAgentId,
      credentials: credentials || {},
      scope_level: opts?.scope_level ?? 'user',
      project_id: opts?.project_id,
    });
    return response.data;
  },

  getInstalledMcpServers: async (params?: { project_id?: string }) => {
    const response = await api.get('/api/mcp/installed', { params });
    return response.data;
  },

  uninstallMcpServer: async (configId: string) => {
    await api.delete(`/api/mcp/installed/${configId}`);
  },

  testMcpServer: async (configId: string) => {
    const response = await api.post(`/api/mcp/installed/${configId}/test`);
    return response.data;
  },

  assignMcpToAgent: async (configId: string, agentId: string) => {
    const response = await api.post(`/api/mcp/installed/${configId}/assign/${agentId}`);
    return response.data;
  },

  unassignMcpFromAgent: async (configId: string, agentId: string) => {
    await api.delete(`/api/mcp/installed/${configId}/assign/${agentId}`);
  },

  // Returns the agent ids that have this connector currently assigned —
  // used by the Library 'Add to Agent' multi-toggle dropdown.
  getConnectorAgents: async (configId: string) => {
    const response = await api.get(`/api/mcp/installed/${configId}/agents`);
    return response.data as string[];
  },

  getAgentMcpServers: async (agentId: string) => {
    const response = await api.get(`/api/mcp/agent/${agentId}/servers`);
    return response.data;
  },

  updateMcpServer: async (
    configId: string,
    data: {
      credentials?: Record<string, string>;
      enabled_capabilities?: string[];
      is_active?: boolean;
    }
  ) => {
    const response = await api.patch(`/api/mcp/installed/${configId}`, data);
    return response.data;
  },

  discoverMcpServer: async (configId: string) => {
    const response = await api.post(`/api/mcp/installed/${configId}/discover`);
    return response.data;
  },

  // MCP OAuth Connectors (issue #287) --------------------------------------
  getMcpCatalog: async () => {
    const response = await api.get('/api/mcp/catalog');
    return response.data as Array<{
      id: string;
      slug: string;
      name: string;
      description: string;
      icon?: string | null;
      icon_url?: string | null;
      category?: string | null;
      config: Record<string, unknown>;
    }>;
  },

  startMcpOAuth: async (body: {
    marketplace_agent_slug?: string;
    server_url?: string;
    registration_method: 'dcr' | 'byo' | 'platform_app';
    // Team-scope install was dropped in #307 — the backend 400s "team".
    scope_level?: 'user' | 'project';
    project_id?: string;
    byo_client_id?: string;
    byo_client_secret?: string;
    scope?: string;
  }) => {
    const response = await api.post('/api/mcp/oauth/start', body);
    return response.data as { authorize_url: string; flow_id: string };
  },

  getMcpOAuthStatus: async (flowId: string) => {
    const response = await api.get(`/api/mcp/oauth/status/${flowId}`);
    return response.data as {
      status: 'pending' | 'success' | 'error' | 'unknown';
      config_id?: string | null;
      error?: string | null;
    };
  },

  updateMcpDisabledTools: async (configId: string, disabledTools: string[]) => {
    const response = await api.patch(`/api/mcp/installed/${configId}/tools`, {
      disabled_tools: disabledTools,
    });
    return response.data;
  },

  overrideMcpForProject: async (configId: string, projectId: string) => {
    const response = await api.post(`/api/mcp/installed/${configId}/override`, {
      project_id: projectId,
    });
    return response.data as {
      id: string;
      parent_config_id: string;
      project_id: string;
      scope_level: string;
    };
  },

  removeProjectMcpOverride: async (configId: string) => {
    await api.delete(`/api/mcp/installed/${configId}/override`);
  },

  reconnectMcp: async (configId: string) => {
    const response = await api.post(`/api/mcp/installed/${configId}/reconnect`);
    return response.data as { authorize_url: string; flow_id: string };
  },

  // Sign out of a connector — clears stored tokens/creds but keeps the
  // install + tool permissions + agent assignments so the user can
  // reconnect without re-attaching everything.
  disconnectMcp: async (configId: string) => {
    await api.post(`/api/mcp/installed/${configId}/disconnect`);
  },

  getSkillDetails: async (slug: string) => {
    const response = await api.get(`/api/marketplace/skills/${slug}`);
    return response.data;
  },

  purchaseSkill: async (skillId: string) => {
    const response = await api.post(`/api/marketplace/skills/${skillId}/purchase`);
    return response.data;
  },

  installSkillOnAgent: async (skillId: string, agentId: string) => {
    const response = await api.post(`/api/marketplace/skills/${skillId}/install`, {
      agent_id: agentId,
    });
    return response.data;
  },

  uninstallSkillFromAgent: async (skillId: string, agentId: string) => {
    const response = await api.delete(`/api/marketplace/skills/${skillId}/install/${agentId}`);
    return response.data;
  },

  getAgentSkills: async (agentId: string) => {
    const response = await api.get(`/api/marketplace/agents/${agentId}/skills`);
    return response.data;
  },
};

// Creator/Author profile API
export const creatorsApi = {
  // Get creator public profile
  getProfile: async (userId: string) => {
    const response = await api.get(`/api/creators/${userId}`);
    return response.data;
  },

  // Get creator public profile by @username
  getProfileByUsername: async (username: string) => {
    const response = await api.get(`/api/creators/by-username/${encodeURIComponent(username)}`);
    return response.data;
  },

  // Check username availability
  checkUsername: async (
    username: string
  ): Promise<{ available: boolean; reason: string | null }> => {
    const response = await api.get(`/api/creators/check-username/${encodeURIComponent(username)}`);
    return response.data;
  },

  // Get creator's published agents (paginated)
  getCreatorAgents: async (userId: string, params?: { page?: number; limit?: number }) => {
    const queryParams = new URLSearchParams();
    if (params?.page) queryParams.append('page', params.page.toString());
    if (params?.limit) queryParams.append('limit', params.limit.toString());
    const response = await api.get(`/api/creators/${userId}/agents?${queryParams}`);
    return response.data;
  },

  // Get creator stats
  getCreatorStats: async (userId: string) => {
    const response = await api.get(`/api/creators/${userId}/stats`);
    return response.data;
  },
};

export const secretsApi = {
  // List all API keys
  listApiKeys: async (provider?: string) => {
    const params = provider ? `?provider=${provider}` : '';
    const response = await api.get(`/api/secrets/api-keys${params}`);
    return response.data;
  },

  // Add new API key
  addApiKey: async (data: {
    provider: string;
    api_key: string;
    key_name?: string;
    auth_type?: string;
    base_url?: string;
    provider_metadata?: Record<string, unknown>;
  }) => {
    const response = await api.post('/api/secrets/api-keys', data);
    return response.data;
  },

  // Update API key
  updateApiKey: async (
    keyId: number,
    data: {
      api_key?: string;
      key_name?: string;
      base_url?: string;
      provider_metadata?: Record<string, unknown>;
    }
  ) => {
    const response = await api.put(`/api/secrets/api-keys/${keyId}`, data);
    return response.data;
  },

  // Delete API key
  deleteApiKey: async (keyId: number) => {
    const response = await api.delete(`/api/secrets/api-keys/${keyId}`);
    return response.data;
  },

  // Get specific API key with optional reveal
  getApiKey: async (keyId: number, reveal: boolean = false) => {
    const response = await api.get(`/api/secrets/api-keys/${keyId}?reveal=${reveal}`);
    return response.data;
  },

  // List supported providers
  getProviders: async () => {
    const response = await api.get('/api/secrets/providers');
    return response.data;
  },

  // === Custom Provider Methods ===

  // List user's custom providers
  listCustomProviders: async () => {
    const response = await api.get('/api/secrets/providers/custom');
    return response.data;
  },

  // Create a custom provider
  createCustomProvider: async (data: {
    name: string;
    slug: string;
    base_url: string;
    api_type?: string;
    default_headers?: Record<string, string>;
    available_models?: string[];
  }) => {
    const response = await api.post('/api/secrets/providers/custom', data);
    return response.data;
  },

  // Update a custom provider
  updateCustomProvider: async (
    providerId: string,
    data: {
      name?: string;
      base_url?: string;
      api_type?: string;
      default_headers?: Record<string, string>;
      available_models?: string[];
    }
  ) => {
    const response = await api.put(`/api/secrets/providers/custom/${providerId}`, data);
    return response.data;
  },

  // Delete a custom provider
  deleteCustomProvider: async (providerId: string) => {
    const response = await api.delete(`/api/secrets/providers/custom/${providerId}`);
    return response.data;
  },

  // Get model preferences (disabled models list)
  getModelPreferences: async () => {
    const response = await api.get('/api/secrets/model-preferences');
    return response.data;
  },

  // Toggle a model on/off
  toggleModel: async (modelId: string, enabled: boolean) => {
    const response = await api.put('/api/secrets/model-preferences', {
      model_id: modelId,
      enabled,
    });
    return response.data;
  },
};

export interface UserProfile {
  id: string;
  email: string;
  username?: string;
  name?: string;
  avatar_url?: string;
  bio?: string;
  twitter_handle?: string;
  github_username?: string;
  website_url?: string;
}

export interface UserProfileUpdate {
  username?: string;
  name?: string;
  avatar_url?: string;
  bio?: string;
  twitter_handle?: string;
  github_username?: string;
  website_url?: string;
}

export type ChatPosition = 'left' | 'center' | 'right';

export interface UserPreferences {
  diagram_model?: string | null;
  theme_preset?: string | null;
  chat_position?: ChatPosition | null;
}

export const usersApi = {
  // Get user preferences
  getPreferences: async (): Promise<UserPreferences> => {
    const response = await api.get('/api/users/preferences');
    return response.data;
  },

  // Update user preferences
  updatePreferences: async (data: {
    diagram_model?: string;
    theme_preset?: string;
    chat_position?: ChatPosition;
  }) => {
    const response = await api.patch('/api/users/preferences', data);
    return response.data;
  },

  // Get user profile
  getProfile: async (): Promise<UserProfile> => {
    const response = await api.get('/api/users/profile');
    return response.data;
  },

  // Update user profile
  updateProfile: async (data: UserProfileUpdate): Promise<UserProfile> => {
    const response = await api.patch('/api/users/profile', data);
    return response.data;
  },
};

// ============================================================================
// Themes API (public, no auth required)
// ============================================================================

export interface ThemeColors {
  primary: string;
  primaryHover: string;
  primaryRgb: string;
  accent: string;
  background: string;
  surface: string;
  surfaceHover: string;
  text: string;
  textMuted: string;
  textSubtle: string;
  border: string;
  borderHover: string;
  sidebar: {
    background: string;
    text: string;
    border: string;
    hover: string;
    active: string;
  };
  input: {
    background: string;
    border: string;
    borderFocus: string;
    text: string;
    placeholder: string;
  };
  scrollbar: {
    thumb: string;
    thumbHover: string;
    track: string;
  };
  code: {
    inlineBackground: string;
    inlineText: string;
    blockBackground: string;
    blockBorder: string;
    blockText: string;
  };
  status: {
    error: string;
    errorRgb: string;
    success: string;
    successRgb: string;
    warning: string;
    warningRgb: string;
    info: string;
    infoRgb: string;
    purple?: string;
    purpleRgb?: string;
  };
  shadow: {
    small: string;
    medium: string;
    large: string;
  };
}

export interface ThemeTypography {
  fontFamily: string;
  fontFamilyMono: string;
  fontSizeBase: string;
  lineHeight: string;
  fontFamilyHeading?: string;
}

export interface ThemeSpacing {
  radiusSmall: string;
  radiusMedium: string;
  radiusLarge: string;
  radiusXl: string;
}

export interface ThemeAnimation {
  durationFast: string;
  durationNormal: string;
  durationSlow: string;
  easing: string;
}

export interface Theme {
  id: string;
  name: string;
  mode: 'dark' | 'light';
  author?: string;
  version?: string;
  description?: string;
  colors: ThemeColors;
  typography: ThemeTypography;
  spacing: ThemeSpacing;
  animation: ThemeAnimation;
  /**
   * When true, all border CSS variables resolve to transparent. Lets
   * any theme adopt the no-border treatment without rewriting every
   * color value. Toggleable from the theme editor.
   */
  borderless?: boolean;
}

export interface ThemeListItem {
  id: string;
  name: string;
  mode: 'dark' | 'light';
  author?: string;
  description?: string;
}

export const themesApi = {
  // List all themes (lightweight)
  list: async (): Promise<ThemeListItem[]> => {
    const response = await api.get('/api/themes');
    return response.data;
  },

  // List all themes with full data
  listFull: async (): Promise<Theme[]> => {
    const response = await api.get('/api/themes/full');
    return response.data;
  },

  // Get a single theme by ID
  get: async (themeId: string): Promise<Theme> => {
    const response = await api.get(`/api/themes/${themeId}`);
    return response.data;
  },

  // Get default theme for a mode
  getDefault: async (mode: 'dark' | 'light'): Promise<Theme> => {
    const response = await api.get(`/api/themes/default/${mode}`);
    return response.data;
  },
};

export const setupApi = {
  getConfig: async (slug: string): Promise<TesslateConfigResponse> => {
    const response = await api.get(`/api/projects/${slug}/setup-config`);
    return response.data;
  },

  saveConfig: async (slug: string, config: TesslateConfig): Promise<SetupConfigSyncResponse> => {
    const response = await api.post(`/api/projects/${slug}/setup-config`, config);
    return response.data;
  },

  analyzeProject: async (slug: string, model?: string): Promise<TesslateConfigResponse> => {
    const params = model ? { model } : {};
    const response = await api.post(`/api/projects/${slug}/analyze`, null, { params });
    return response.data;
  },
};

export const configSyncApi = {
  save: async (slug: string): Promise<ConfigSyncSaveResponse> => {
    const response = await api.post(`/api/projects/${slug}/sync-config`);
    return response.data;
  },

  load: async (slug: string, config: TesslateConfig): Promise<SetupConfigSyncResponse> => {
    const response = await api.post(`/api/projects/${slug}/setup-config`, config);
    return response.data;
  },
};

export const assetsApi = {
  // List all directories that contain assets
  listDirectories: async (projectSlug: string) => {
    const response = await api.get(`/api/projects/${projectSlug}/assets/directories`);
    return response.data;
  },

  // Create a new asset directory
  createDirectory: async (projectSlug: string, path: string) => {
    const response = await api.post(`/api/projects/${projectSlug}/assets/directories`, { path });
    return response.data;
  },

  // List all assets, optionally filtered by directory
  listAssets: async (projectSlug: string, directory?: string) => {
    const params = directory ? `?directory=${encodeURIComponent(directory)}` : '';
    const response = await api.get(`/api/projects/${projectSlug}/assets${params}`);
    return response.data;
  },

  // Upload an asset file
  uploadAsset: async (
    projectSlug: string,
    file: File,
    directory: string,
    onProgress?: (progress: number) => void
  ) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('directory', directory);

    const response = await api.post(`/api/projects/${projectSlug}/assets/upload`, formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
      onUploadProgress: (progressEvent) => {
        if (onProgress && progressEvent.total) {
          const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total);
          onProgress(percentCompleted);
        }
      },
    });
    return response.data;
  },

  // Get asset file URL
  getAssetUrl: (projectSlug: string, assetId: string) => {
    return `${API_URL}/api/projects/${projectSlug}/assets/${assetId}/file`;
  },

  // Delete an asset
  deleteAsset: async (projectSlug: string, assetId: string) => {
    const response = await api.delete(`/api/projects/${projectSlug}/assets/${assetId}`);
    return response.data;
  },

  // Rename an asset
  renameAsset: async (projectSlug: string, assetId: string, new_filename: string) => {
    const response = await api.patch(`/api/projects/${projectSlug}/assets/${assetId}/rename`, {
      new_filename,
    });
    return response.data;
  },

  // Move asset to a different directory
  moveAsset: async (projectSlug: string, assetId: string, directory: string) => {
    const response = await api.patch(`/api/projects/${projectSlug}/assets/${assetId}/move`, {
      directory,
    });
    return response.data;
  },
};

// ============================================================================
// App Configuration API
// ============================================================================

// Cache app config to avoid repeated fetches
// ============================================================================
// Billing & Subscription API
// ============================================================================

export const billingApi = {
  // Get public billing configuration
  getConfig: async (): Promise<BillingConfig> => {
    const response = await api.get('/api/billing/config');
    return response.data;
  },

  // Subscription management
  getSubscription: async (): Promise<SubscriptionResponse> => {
    const response = await api.get('/api/billing/subscription');
    return response.data;
  },

  subscribe: async (
    tier: 'basic' | 'pro' | 'ultra' = 'pro',
    billingInterval: 'monthly' | 'annual' = 'monthly'
  ): Promise<CheckoutSessionResponse> => {
    const response = await api.post('/api/billing/subscribe', {
      tier,
      billing_interval: billingInterval,
    });
    return response.data;
  },

  // Get credit status for low balance warning
  getCreditStatus: async (): Promise<CreditStatusResponse> => {
    const response = await api.get('/api/billing/credits/status');
    return response.data;
  },

  verifyCheckout: async (sessionId: string): Promise<VerifyCheckoutResponse> => {
    const response = await api.post('/api/billing/verify-checkout', {
      session_id: sessionId,
    });
    return response.data;
  },

  cancelSubscription: async (
    atPeriodEnd: boolean = true
  ): Promise<{ success: boolean; message: string }> => {
    const response = await api.post(`/api/billing/cancel`, null, {
      params: { at_period_end: atPeriodEnd },
    });
    return response.data;
  },

  renewSubscription: async (): Promise<{ success: boolean; message: string }> => {
    const response = await api.post('/api/billing/renew');
    return response.data;
  },

  getCustomerPortal: async (): Promise<CustomerPortalResponse> => {
    const response = await api.get('/api/billing/portal');
    return response.data;
  },

  // Credits management
  getCreditsBalance: async (): Promise<CreditBalanceResponse> => {
    const response = await api.get('/api/billing/credits');
    return response.data;
  },

  purchaseCredits: async (packageType: CreditPackage): Promise<CheckoutSessionResponse> => {
    const response = await api.post('/api/billing/credits/purchase', {
      package: packageType,
    });
    return response.data;
  },

  getCreditsHistory: async (
    limit: number = 50,
    offset: number = 0
  ): Promise<CreditPurchaseHistoryResponse> => {
    const response = await api.get('/api/billing/credits/history', {
      params: { limit, offset },
    });
    return response.data;
  },

  // Usage tracking
  getUsage: async (startDate?: string, endDate?: string): Promise<UsageSummaryResponse> => {
    const response = await api.get('/api/billing/usage', {
      params: { start_date: startDate, end_date: endDate },
    });
    return response.data;
  },

  syncUsage: async (
    startDate?: string
  ): Promise<{ success: boolean; logs_synced: number; message: string }> => {
    const response = await api.post('/api/billing/usage/sync', {
      start_date: startDate,
    });
    return response.data;
  },

  getUsageLogs: async (
    limit: number = 100,
    offset: number = 0,
    startDate?: string,
    endDate?: string
  ): Promise<UsageLogsResponse> => {
    const response = await api.get('/api/billing/usage/logs', {
      params: { limit, offset, start_date: startDate, end_date: endDate },
    });
    return response.data;
  },

  // Transactions
  getTransactions: async (
    limit: number = 50,
    offset: number = 0
  ): Promise<TransactionsResponse> => {
    const response = await api.get('/api/billing/transactions', {
      params: { limit, offset },
    });
    return response.data;
  },

  // Creator earnings
  getEarnings: async (startDate?: string, endDate?: string): Promise<CreatorEarningsResponse> => {
    const response = await api.get('/api/billing/earnings', {
      params: { start_date: startDate, end_date: endDate },
    });
    return response.data;
  },

  connectStripe: async (): Promise<StripeConnectResponse> => {
    const response = await api.post('/api/billing/connect');
    return response.data;
  },

  // Deployment management
  getDeploymentLimits: async () => {
    const response = await api.get('/api/projects/deployment/limits');
    return response.data;
  },

  deployProject: async (projectSlug: string) => {
    const response = await api.post(`/api/projects/${projectSlug}/deploy`);
    return response.data;
  },

  undeployProject: async (projectSlug: string) => {
    const response = await api.delete(`/api/projects/${projectSlug}/deploy`);
    return response.data;
  },

  purchaseDeploySlot: async () => {
    const response = await api.post('/api/projects/deployment/purchase-slot');
    return response.data;
  },
};

// ============================================================================
// Feedback System API
// ============================================================================

// ============================================================================
// Deployment Credentials API
// ============================================================================

export const deploymentCredentialsApi = {
  // Get available deployment providers
  getProviders: async () => {
    const response = await api.get('/api/deployment-credentials/providers');
    return response.data;
  },

  // List user's connected credentials
  list: async (provider?: string, projectId?: string) => {
    const response = await api.get('/api/deployment-credentials', {
      params: { provider, project_id: projectId },
    });
    return response.data;
  },

  // Add new credential
  create: async (data: {
    provider: string;
    access_token: string;
    metadata?: Record<string, unknown>;
    project_id?: string;
  }) => {
    const response = await api.post('/api/deployment-credentials', data);
    return response.data;
  },

  // Update credential
  update: async (
    credentialId: string,
    data: {
      access_token?: string;
      metadata?: Record<string, unknown>;
    }
  ) => {
    const response = await api.put(`/api/deployment-credentials/${credentialId}`, data);
    return response.data;
  },

  // Delete credential
  delete: async (credentialId: string) => {
    const response = await api.delete(`/api/deployment-credentials/${credentialId}`);
    return response.data;
  },

  // Test credential validity
  test: async (credentialId: string) => {
    const response = await api.post(`/api/deployment-credentials/test/${credentialId}`);
    return response.data;
  },

  // Start OAuth flow (redirects to provider)
  startOAuth: async (provider: string, projectId?: string) => {
    const params = new URLSearchParams();
    if (projectId) {
      params.append('project_id', projectId);
    }
    const query = params.toString() ? `?${params.toString()}` : '';

    // Make authenticated API call to get OAuth URL
    const response = await api.get(`/api/deployment-oauth/${provider}/authorize${query}`);
    return response.data;
  },

  // Save manual credentials (alias for create for better semantics)
  saveManual: async (provider: string, credentials: Record<string, string>) => {
    // Maps each provider's primary secret field to access_token for storage.
    // Must stay in sync with PROVIDER_CREDENTIAL_SCHEMA.token_alias in
    // orchestrator/app/routers/deployment_credentials.py
    const tokenFieldNames = [
      'api_token',
      'access_token',
      'token',
      'api_key',
      'client_secret',
      'service_account_json',
      'aws_access_key_id',
    ];
    // Extract the first matching token field
    const tokenField = tokenFieldNames.reduce<string | undefined>(
      (found, key) => found || credentials[key],
      undefined
    );

    // Extract other fields as metadata
    const metadata: Record<string, string> = {};
    for (const [key, value] of Object.entries(credentials)) {
      if (!tokenFieldNames.includes(key)) {
        metadata[key] = value;
      }
    }

    return deploymentCredentialsApi.create({
      provider,
      access_token: tokenField!,
      metadata: Object.keys(metadata).length > 0 ? metadata : undefined,
    });
  },
};

// ============================================================================
// Deployment API
// ============================================================================

export const deploymentsApi = {
  // Trigger a new deployment
  deploy: async (
    projectSlug: string,
    data: {
      provider: string;
      deployment_mode?: 'source' | 'pre-built';
      custom_domain?: string;
      env_vars?: Record<string, string>;
      build_command?: string;
      framework?: string;
    }
  ) => {
    const response = await api.post(`/api/deployments/${projectSlug}/deploy`, data);
    return response.data;
  },

  // Deploy all containers with deployment targets
  deployAll: async (
    projectSlug: string
  ): Promise<{
    total: number;
    deployed: number;
    failed: number;
    skipped: number;
    results: Array<{
      container_id: string;
      container_name: string;
      provider: string;
      status: 'success' | 'failed' | 'skipped';
      deployment_id?: string;
      deployment_url?: string;
      error?: string;
    }>;
  }> => {
    const response = await api.post(`/api/deployments/${projectSlug}/deploy-all`);
    return response.data;
  },

  // Deploy a single container to its assigned provider
  deployContainer: async (
    projectSlug: string,
    containerId: string
  ): Promise<{
    id: string;
    project_id: string;
    user_id: string;
    provider: string;
    deployment_id: string | null;
    deployment_url: string | null;
    status: string;
    logs: string[] | null;
    error: string | null;
    created_at: string;
    updated_at: string;
    completed_at: string | null;
  }> => {
    const response = await api.post(
      `/api/deployments/${projectSlug}/containers/${containerId}/deploy`
    );
    return response.data;
  },

  // List project deployments
  listProjectDeployments: async (
    projectSlug: string,
    params?: {
      provider?: string;
      status?: string;
      limit?: number;
      offset?: number;
    }
  ) => {
    const response = await api.get(`/api/deployments/${projectSlug}/deployments`, {
      params,
    });
    return response.data;
  },

  // Get deployment details
  get: async (deploymentId: string) => {
    const response = await api.get(`/api/deployments/deployment/${deploymentId}`);
    return response.data;
  },

  // Get deployment status
  getStatus: async (deploymentId: string) => {
    const response = await api.get(`/api/deployments/deployment/${deploymentId}/status`);
    return response.data;
  },

  // Get deployment logs
  getLogs: async (deploymentId: string) => {
    const response = await api.get(`/api/deployments/deployment/${deploymentId}/logs`);
    return response.data;
  },

  // Delete deployment
  delete: async (deploymentId: string) => {
    const response = await api.delete(`/api/deployments/deployment/${deploymentId}`);
    return response.data;
  },

  // Deploy via container-push (AWS App Runner, GCP Cloud Run, Azure, Fly, DO)
  deployContainerPush: async (
    projectSlug: string,
    data: {
      provider: string;
      container_id?: string;
      port?: number;
      cpu?: string;
      memory?: string;
      region?: string;
      env_vars?: Record<string, string>;
    }
  ): Promise<{
    id: string;
    project_id: string;
    provider: string;
    deployment_id: string | null;
    deployment_url: string | null;
    status: string;
    logs: string[] | null;
    error: string | null;
    created_at: string;
    updated_at: string;
    completed_at: string | null;
  }> => {
    const response = await api.post(`/api/deployments/${projectSlug}/deploy-container`, data);
    return response.data;
  },

  // Export project image (Docker Hub, GHCR, Download)
  exportProject: async (
    projectSlug: string,
    data: {
      provider: string;
      container_id?: string;
      image_name?: string;
      tag?: string;
    }
  ): Promise<{
    id: string;
    project_id: string;
    provider: string;
    status: string;
    image_ref: string | null;
    pull_command: string | null;
    download_url: string | null;
    logs: string[] | null;
    error: string | null;
    created_at: string;
    completed_at: string | null;
  }> => {
    const response = await api.post(`/api/deployments/${projectSlug}/export`, data);
    return response.data;
  },

  // Stream deployment progress (SSE)
  streamProgress: (
    deploymentId: string,
    onMessage: (data: Record<string, unknown>) => void,
    onError?: (error: Event) => void
  ) => {
    const eventSource = new EventSource(
      `${API_URL}/api/deployments/deployment/${deploymentId}/stream`,
      { withCredentials: true }
    );

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        onMessage(data);
      } catch (error) {
        console.error('Failed to parse SSE message:', error);
      }
    };

    eventSource.onerror = (error) => {
      if (onError) {
        onError(error);
      }
      eventSource.close();
    };

    return eventSource;
  },
};

// ============================================================================
// Deployment Targets API (New Node-Based UX)
// ============================================================================

// Types for deployment targets
export interface DeploymentTargetProviderInfo {
  display_name: string;
  icon: string;
  color: string;
  types: string[];
  frameworks: string[];
  supports_serverless: boolean;
  supports_static: boolean;
  supports_fullstack: boolean;
  deployment_mode: string;
  auth_type: 'oauth' | 'token' | 'none';
}

export interface DeploymentTargetConnectedContainer {
  id: string;
  name: string;
  container_type?: string;
  framework?: string;
  status?: string;
}

export interface DeploymentTargetDeploymentHistory {
  id: string;
  version?: string;
  status: 'success' | 'failed' | 'deploying' | 'pending' | 'building';
  deployment_url?: string;
  container_id?: string;
  container_name?: string;
  created_at: string;
  completed_at?: string;
}

export interface DeploymentTarget {
  id: string;
  project_id: string;
  provider: string;
  environment: 'production' | 'staging' | 'preview';
  name?: string;
  position_x: number;
  position_y: number;
  is_connected: boolean;
  credential_id?: string;
  provider_info: DeploymentTargetProviderInfo;
  connected_containers: DeploymentTargetConnectedContainer[];
  deployment_history: DeploymentTargetDeploymentHistory[];
  created_at: string;
  updated_at: string;
}

export interface DeploymentTargetProvider {
  slug: string;
  display_name: string;
  icon: string;
  color: string;
  types: string[];
  frameworks: string[];
  supports_serverless: boolean;
  supports_static: boolean;
  supports_fullstack: boolean;
  deployment_mode: string;
  is_connected: boolean;
}

export const deploymentTargetsApi = {
  // List all deployment targets for a project
  list: async (projectSlug: string): Promise<DeploymentTarget[]> => {
    const response = await api.get(`/api/projects/${projectSlug}/deployment-targets`);
    return response.data;
  },

  // Get a specific deployment target
  get: async (projectSlug: string, targetId: string): Promise<DeploymentTarget> => {
    const response = await api.get(`/api/projects/${projectSlug}/deployment-targets/${targetId}`);
    return response.data;
  },

  // Create a new deployment target
  create: async (
    projectSlug: string,
    data: {
      provider: string;
      environment?: string;
      name?: string;
      position_x?: number;
      position_y?: number;
    }
  ): Promise<DeploymentTarget> => {
    const response = await api.post(`/api/projects/${projectSlug}/deployment-targets`, data);
    return response.data;
  },

  // Update a deployment target (position, name, environment)
  update: async (
    projectSlug: string,
    targetId: string,
    data: {
      environment?: string;
      name?: string;
      position_x?: number;
      position_y?: number;
    }
  ): Promise<DeploymentTarget> => {
    const response = await api.patch(
      `/api/projects/${projectSlug}/deployment-targets/${targetId}`,
      data
    );
    return response.data;
  },

  // Delete a deployment target
  delete: async (
    projectSlug: string,
    targetId: string
  ): Promise<{ status: string; id: string }> => {
    const response = await api.delete(
      `/api/projects/${projectSlug}/deployment-targets/${targetId}`
    );
    return response.data;
  },

  // Connect a container to a deployment target
  connect: async (
    projectSlug: string,
    targetId: string,
    containerId: string
  ): Promise<{
    status: string;
    container_id: string;
    target_id: string;
    container_name: string;
    provider: string;
  }> => {
    const response = await api.post(
      `/api/projects/${projectSlug}/deployment-targets/${targetId}/connect/${containerId}`
    );
    return response.data;
  },

  // Disconnect a container from a deployment target
  disconnect: async (
    projectSlug: string,
    targetId: string,
    containerId: string
  ): Promise<{ status: string; container_id: string; target_id: string }> => {
    const response = await api.delete(
      `/api/projects/${projectSlug}/deployment-targets/${targetId}/disconnect/${containerId}`
    );
    return response.data;
  },

  // Validate if a container can connect to a deployment target
  validate: async (
    projectSlug: string,
    targetId: string,
    containerId: string
  ): Promise<{ allowed: boolean; reason: string }> => {
    const response = await api.get(
      `/api/projects/${projectSlug}/deployment-targets/${targetId}/validate/${containerId}`
    );
    return response.data;
  },

  // Deploy all connected containers to a deployment target
  deploy: async (
    projectSlug: string,
    targetId: string,
    data?: {
      env_vars?: Record<string, string>;
      build_command?: string;
    }
  ): Promise<{
    target_id: string;
    provider: string;
    version: string;
    total: number;
    success: number;
    failed: number;
    results: Array<{
      container_id: string;
      container_name: string;
      status: 'success' | 'failed';
      deployment_id: string;
      deployment_url?: string;
      error?: string;
    }>;
  }> => {
    const response = await api.post(
      `/api/projects/${projectSlug}/deployment-targets/${targetId}/deploy`,
      data || {}
    );
    return response.data;
  },

  // Get deployment history for a target
  getHistory: async (
    projectSlug: string,
    targetId: string,
    params?: { limit?: number; offset?: number }
  ): Promise<DeploymentTargetDeploymentHistory[]> => {
    const response = await api.get(
      `/api/projects/${projectSlug}/deployment-targets/${targetId}/history`,
      { params }
    );
    return response.data;
  },

  // Rollback to a previous deployment
  rollback: async (
    projectSlug: string,
    targetId: string,
    deploymentId: string
  ): Promise<{
    status: string;
    target_id: string;
    deployment_id: string;
    rollback_to_version: string;
    message: string;
  }> => {
    const response = await api.post(
      `/api/projects/${projectSlug}/deployment-targets/${targetId}/rollback/${deploymentId}`
    );
    return response.data;
  },

  // List all available deployment providers
  listProviders: async (projectSlug: string): Promise<DeploymentTargetProvider[]> => {
    const response = await api.get(`/api/projects/${projectSlug}/deployment-targets/providers`);
    return response.data;
  },

  // Start OAuth flow for a deployment target
  startOAuth: async (
    projectSlug: string,
    targetId: string
  ): Promise<{ oauth_url?: string; auth_url?: string; error?: string }> => {
    // Get the target to determine provider and auth_type from provider_info
    const target = await deploymentTargetsApi.get(projectSlug, targetId);
    const provider = target.provider;

    // Check auth_type from provider_info (driven by backend PROVIDER_CAPABILITIES)
    if (target.provider_info?.auth_type !== 'oauth') {
      return {
        error: `${provider} does not support OAuth. Please configure credentials manually.`,
      };
    }

    // Call the existing OAuth authorize endpoint
    const response = await api.get(`/api/deployment-oauth/${provider}/authorize`);
    return { oauth_url: response.data.auth_url };
  },
};

export const feedbackApi = {
  // List all feedback posts
  list: async (params?: {
    type?: 'bug' | 'suggestion';
    status?: string;
    sort?: 'upvotes' | 'date' | 'comments';
    limit?: number;
    offset?: number;
  }) => {
    const response = await api.get('/api/feedback', { params });
    return response.data;
  },

  // Get single feedback post with comments
  get: async (feedbackId: string) => {
    const response = await api.get(`/api/feedback/${feedbackId}`);
    return response.data;
  },

  // Create new feedback post
  create: async (data: { type: 'bug' | 'suggestion'; title: string; description: string }) => {
    const response = await api.post('/api/feedback', data);
    return response.data;
  },

  // Update feedback status (admin only)
  updateStatus: async (feedbackId: string, status: string) => {
    const response = await api.patch(`/api/feedback/${feedbackId}`, { status });
    return response.data;
  },

  // Delete feedback post
  delete: async (feedbackId: string) => {
    const response = await api.delete(`/api/feedback/${feedbackId}`);
    return response.data;
  },

  // Toggle upvote on feedback
  toggleUpvote: async (feedbackId: string) => {
    const response = await api.post(`/api/feedback/${feedbackId}/upvote`);
    return response.data;
  },

  // Add comment to feedback
  addComment: async (feedbackId: string, content: string) => {
    const response = await api.post(`/api/feedback/${feedbackId}/comments`, { content });
    return response.data;
  },
};

// =============================================================================
// Project Snapshots API (CAS checkpoints via btrfs Hub)
// =============================================================================

export interface Snapshot {
  hash: string;
  parent: string;
  prev: string; // chronologically previous snapshot (unlike parent which skips for consolidations)
  role: string;
  label: string;
  ts: string; // ISO timestamp
  consolidation?: boolean;
}

export interface TimelineBranch {
  name: string;
  display_name: string;
  hash: string; // tip hash
  is_current: boolean;
  checkpoint_count: number;
}

export interface TimelineGraphResponse {
  head: string;
  branches: TimelineBranch[];
  snapshots: Snapshot[];
}

export interface SnapshotListResponse {
  snapshots: Snapshot[];
  volume_id: string;
}

export interface SnapshotCreateResponse {
  hash: string;
  label: string;
  volume_id: string;
}

export interface SnapshotRestoreResponse {
  success: boolean;
  message: string;
  restored_hash: string;
  node: string;
}

export const snapshotsApi = {
  list: async (projectId: string): Promise<SnapshotListResponse> => {
    const response = await api.get(`/api/projects/${projectId}/snapshots/`);
    return response.data;
  },

  create: async (projectId: string, label?: string): Promise<SnapshotCreateResponse> => {
    const response = await api.post(`/api/projects/${projectId}/snapshots/`, { label });
    return response.data;
  },

  restore: async (projectId: string, snapshotHash: string): Promise<SnapshotRestoreResponse> => {
    const response = await api.post(`/api/projects/${projectId}/snapshots/${snapshotHash}/restore`);
    return response.data;
  },

  graph: async (projectId: string): Promise<TimelineGraphResponse> => {
    const response = await api.get(`/api/projects/${projectId}/snapshots/graph`);
    return response.data;
  },

  createBranch: async (
    projectId: string,
    name: string
  ): Promise<{ name: string; display_name: string }> => {
    const response = await api.post(`/api/projects/${projectId}/snapshots/branches`, { name });
    return response.data;
  },
};

// ------------------------------------------------------------------
// Volume Health & Recovery
// ------------------------------------------------------------------

export interface VolumeStatus {
  status: 'healthy' | 'restoring' | 'unreachable' | 'unavailable' | 'no_volume';
  node?: string;
  volume_id?: string;
  message?: string;
  recoverable?: boolean;
}

export interface VolumeRecoverResponse {
  status: string;
  node: string;
  action: string;
  restored_hash: string | null;
}

export const volumeApi = {
  status: async (projectSlug: string): Promise<VolumeStatus> => {
    const response = await api.get(`/api/projects/${projectSlug}/volume/status`);
    return response.data;
  },

  recover: async (projectSlug: string, targetHash?: string): Promise<VolumeRecoverResponse> => {
    const response = await api.post(`/api/projects/${projectSlug}/volume/recover`, {
      ...(targetHash ? { target_hash: targetHash } : {}),
    });
    return response.data;
  },
};

export const createWebSocket = (token: string) => {
  let wsUrl: string;
  if (API_URL) {
    wsUrl = API_URL.replace('http', 'ws');
  } else {
    // Use current location for WebSocket when no API_URL is set
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    wsUrl = `${protocol}//${window.location.host}`;
  }
  return new WebSocket(`${wsUrl}/api/chat/ws/${token}`);
};

/**
 * Fetch available terminal targets for a project
 */
export const getTerminalTargets = async (projectSlug: string) => {
  const response = await api.get(`/api/terminal/${projectSlug}/targets`);
  return response.data;
};

/**
 * Create an authenticated WebSocket connection for terminal v2
 */
export const createTerminalWebSocket = (
  projectSlug: string,
  targetId: string,
  token: string
): WebSocket => {
  let wsUrl: string;
  if (API_URL) {
    wsUrl = API_URL.replace('http', 'ws');
  } else {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    wsUrl = `${protocol}//${window.location.host}`;
  }
  const params = new URLSearchParams({ token, target: targetId });
  return new WebSocket(`${wsUrl}/api/terminal/${projectSlug}/connect?${params}`);
};

/**
 * Create a WebSocket connection for streaming container logs
 * @param projectSlug - The project slug
 * @returns WebSocket instance connected to the log stream endpoint
 */
export const createLogStreamWebSocket = (projectSlug: string): WebSocket => {
  let wsUrl: string;
  if (API_URL) {
    wsUrl = API_URL.replace('http', 'ws');
  } else {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    wsUrl = `${protocol}//${window.location.host}`;
  }
  return new WebSocket(`${wsUrl}/api/projects/${projectSlug}/logs/stream`);
};

// ── Teams & RBAC ──────────────────────────────────────────────────────────

export interface Team {
  id: string;
  name: string;
  slug: string;
  avatar_url: string | null;
  is_personal: boolean;
  created_by_id: string;
  subscription_tier: string;
  total_credits: number;
  daily_credits: number;
  bundled_credits: number;
  purchased_credits: number;
  signup_bonus_credits: number;
  deployed_projects_count: number;
  support_tier: string;
  created_at: string;
}

export interface TeamList {
  id: string;
  name: string;
  slug: string;
  avatar_url: string | null;
  is_personal: boolean;
  subscription_tier: string;
  role: string | null;
}

export interface TeamMember {
  id: string;
  user_id: string;
  role: string;
  is_active: boolean;
  joined_at: string;
  user_name: string | null;
  user_email: string | null;
  user_avatar_url: string | null;
}

export interface TeamInvitation {
  id: string;
  email: string;
  role: string;
  invite_type: string;
  token: string;
  expires_at: string;
  accepted_at: string | null;
  revoked_at: string | null;
  max_uses: number | null;
  use_count: number;
  created_at: string;
}

export interface InviteDetail {
  team_name: string;
  team_slug: string;
  team_avatar_url: string | null;
  role: string;
  invite_type: string;
  expires_at: string;
  is_valid: boolean;
}

export interface ProjectMember {
  id: string;
  user_id: string;
  role: string;
  is_active: boolean;
  created_at: string;
  user_name: string | null;
  user_email: string | null;
}

export interface AuditLogEntry {
  id: string;
  team_id: string;
  project_id: string | null;
  user_id: string;
  action: string;
  resource_type: string;
  resource_id: string | null;
  details: Record<string, unknown> | null;
  ip_address: string | null;
  created_at: string;
}

export const teamsApi = {
  async list(): Promise<TeamList[]> {
    const response = await api.get('/api/teams/');
    return response.data;
  },
  async get(slug: string): Promise<Team> {
    const response = await api.get(`/api/teams/${slug}`);
    return response.data;
  },
  async create(data: { name: string; slug: string }): Promise<Team> {
    const response = await api.post('/api/teams', data);
    return response.data;
  },
  async update(
    slug: string,
    data: Partial<{ name: string; slug: string; avatar_url: string | null }>
  ): Promise<Team> {
    const response = await api.patch(`/api/teams/${slug}`, data);
    return response.data;
  },
  async delete(slug: string) {
    await api.delete(`/api/teams/${slug}`);
  },
  async switch(slug: string) {
    const response = await api.post(`/api/teams/${slug}/switch`);
    return response.data;
  },

  // Members
  async listMembers(slug: string): Promise<TeamMember[]> {
    const response = await api.get(`/api/teams/${slug}/members`);
    return response.data;
  },
  async inviteByEmail(slug: string, data: { email: string; role: string }) {
    const response = await api.post(`/api/teams/${slug}/members/invite`, data);
    return response.data;
  },
  async createInviteLink(
    slug: string,
    data: { role: string; max_uses?: number; expires_in_days?: number }
  ): Promise<TeamInvitation> {
    const response = await api.post(`/api/teams/${slug}/members/link`, data);
    return response.data;
  },
  async removeMember(slug: string, userId: string) {
    await api.delete(`/api/teams/${slug}/members/${userId}`);
  },
  async updateMemberRole(slug: string, userId: string, data: { role: string }) {
    await api.patch(`/api/teams/${slug}/members/${userId}`, data);
  },
  async leave(slug: string) {
    await api.post(`/api/teams/${slug}/leave`);
  },

  // Invitations
  async listInvitations(slug: string): Promise<TeamInvitation[]> {
    const response = await api.get(`/api/teams/${slug}/invitations`);
    return response.data;
  },
  async revokeInvitation(slug: string, id: string) {
    await api.delete(`/api/teams/${slug}/invitations/${id}`);
  },
  async acceptInvite(token: string) {
    const response = await api.post(`/api/teams/invitations/${token}/accept`);
    return response.data;
  },
  async getInviteDetails(token: string): Promise<InviteDetail> {
    const response = await api.get(`/api/teams/invitations/${token}`);
    return response.data;
  },

  // Billing
  async getTeamBilling(slug: string) {
    const response = await api.get(`/api/teams/${slug}/billing`);
    return response.data;
  },

  // Audit log
  async getAuditLog(
    slug: string,
    params?: Record<string, string | number>
  ): Promise<AuditLogEntry[]> {
    const response = await api.get(`/api/teams/${slug}/audit-log`, { params });
    return response.data;
  },
  async getProjectAuditLog(
    teamSlug: string,
    projectSlug: string,
    params?: Record<string, string | number>
  ): Promise<AuditLogEntry[]> {
    const response = await api.get(`/api/teams/${teamSlug}/projects/${projectSlug}/audit-log`, {
      params,
    });
    return response.data;
  },

  // Project Members
  async listProjectMembers(teamSlug: string, projectSlug: string) {
    const response = await api.get(`/api/teams/${teamSlug}/projects/${projectSlug}/members`);
    return response.data;
  },
  async addProjectMember(teamSlug: string, projectSlug: string, userId: string, role: string) {
    const response = await api.post(`/api/teams/${teamSlug}/projects/${projectSlug}/members`, {
      user_id: userId,
      role,
    });
    return response.data;
  },
  async updateProjectMemberRole(
    teamSlug: string,
    projectSlug: string,
    userId: string,
    role: string
  ) {
    const response = await api.patch(
      `/api/teams/${teamSlug}/projects/${projectSlug}/members/${userId}`,
      { role }
    );
    return response.data;
  },
  async removeProjectMember(teamSlug: string, projectSlug: string, userId: string) {
    await api.delete(`/api/teams/${teamSlug}/projects/${projectSlug}/members/${userId}`);
  },
  async updateProjectVisibility(
    teamSlug: string,
    projectSlug: string,
    visibility: 'team' | 'private'
  ) {
    const response = await api.patch(`/api/teams/${teamSlug}/projects/${projectSlug}/visibility`, {
      visibility,
    });
    return response.data;
  },
};

// ============================================================================
// Communication Protocol v2 — Gateway, Channels, Schedules
// ============================================================================

export interface PlatformIdentity {
  id: string;
  platform: string;
  platform_user_id: string;
  platform_username: string | null;
  is_verified: boolean;
  paired_at: string | null;
  created_at: string;
}

export interface GatewayStatus {
  shard: number | null;
  adapters: number | null;
  active_sessions: number | null;
  heartbeat: string | null;
  status: string;
}

export interface PlatformInfo {
  platform: string;
  display_name: string;
  supports_gateway: boolean;
  setup_notes: string;
}

export interface ChannelConfig {
  id: string;
  channel_type: string;
  name: string;
  project_id: string | null;
  default_agent_id: string | null;
  is_active: boolean;
  webhook_url: string;
  created_at: string;
  updated_at: string;
}

export interface AgentSchedule {
  id: string;
  project_id: string;
  name: string;
  cron_expression: string;
  normalized_cron: string;
  prompt_template: string;
  timezone: string;
  deliver: string;
  is_active: boolean;
  repeat: number | null;
  runs_completed: number;
  last_run_at: string | null;
  next_run_at: string | null;
  last_status: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

export const gatewayApi = {
  async getStatus(): Promise<GatewayStatus> {
    const response = await api.get('/api/gateway/status');
    return response.data;
  },
  async getPlatforms(): Promise<PlatformInfo[]> {
    const response = await api.get('/api/gateway/platforms');
    return response.data;
  },
  async reload() {
    await api.post('/api/gateway/reload');
  },
  async listIdentities(): Promise<PlatformIdentity[]> {
    const response = await api.get('/api/gateway/identities');
    return response.data;
  },
  async verifyPairing(platform: string, code: string) {
    const response = await api.post('/api/gateway/pair/verify', { platform, pairing_code: code });
    return response.data;
  },
  async unlinkIdentity(id: string) {
    await api.delete(`/api/gateway/identities/${id}`);
  },
};

export const channelsApi = {
  async list(): Promise<ChannelConfig[]> {
    const response = await api.get('/api/channels/configs');
    return response.data;
  },
  async create(data: {
    channel_type: string;
    name: string;
    credentials: Record<string, string>;
    project_id?: string;
    default_agent_id?: string;
  }): Promise<ChannelConfig> {
    const response = await api.post('/api/channels/configs', data);
    return response.data;
  },
  async update(
    id: string,
    data: Partial<{
      name: string;
      credentials: Record<string, string>;
      default_agent_id: string;
      is_active: boolean;
    }>
  ): Promise<ChannelConfig> {
    const response = await api.patch(`/api/channels/configs/${id}`, data);
    return response.data;
  },
  async deactivate(id: string) {
    await api.delete(`/api/channels/configs/${id}`);
  },
  async test(id: string, jid: string) {
    const response = await api.post(`/api/channels/configs/${id}/test`, { jid });
    return response.data;
  },
};

export const schedulesApi = {
  async list(projectId?: string): Promise<AgentSchedule[]> {
    const params = projectId ? `?project_id=${projectId}` : '';
    const response = await api.get(`/api/schedules${params}`);
    return response.data;
  },
  async create(data: {
    project_id: string;
    name: string;
    schedule: string;
    prompt_template: string;
    deliver?: string;
  }): Promise<AgentSchedule> {
    const response = await api.post('/api/schedules', data);
    return response.data;
  },
  async update(
    id: string,
    data: Partial<{
      name: string;
      schedule: string;
      prompt_template: string;
      deliver: string;
    }>
  ): Promise<AgentSchedule> {
    const response = await api.patch(`/api/schedules/${id}`, data);
    return response.data;
  },
  async remove(id: string) {
    await api.delete(`/api/schedules/${id}`);
  },
  async pause(id: string) {
    const response = await api.post(`/api/schedules/${id}/pause`);
    return response.data;
  },
  async resume(id: string) {
    const response = await api.post(`/api/schedules/${id}/resume`);
    return response.data;
  },
  async trigger(id: string) {
    const response = await api.post(`/api/schedules/${id}/trigger`);
    return response.data;
  },
};

// =============================================================================
// Feature Flags
// =============================================================================

export interface FeatureFlagsResponse {
  env: string;
  flags: Record<string, boolean>;
}

// Always fetch fresh flags. On success, cache the result as a fallback
// for future failures. On error, return the last known good value (or empty).
let _lastGoodFlags: FeatureFlagsResponse = { env: '', flags: {} };

function _fetchFlags(): Promise<FeatureFlagsResponse> {
  try {
    const req = api.get('/api/feature-flags');
    if (!req || typeof req.then !== 'function') {
      // api.get is mocked in tests and may return undefined — don't crash
      // the module at import time.
      return Promise.resolve(_lastGoodFlags);
    }
    return req
      .then((r) => {
        _lastGoodFlags = r.data as FeatureFlagsResponse;
        return _lastGoodFlags;
      })
      .catch(() => _lastGoodFlags);
  } catch {
    return Promise.resolve(_lastGoodFlags);
  }
}

// Prefetch at module load — fires alongside CSRF token fetch, before React mounts.
_fetchFlags();

export const featureFlagsApi = {
  getFlags: (): Promise<FeatureFlagsResponse> => _fetchFlags(),
};

// =============================================================================
// ===== Tesslate Apps =====
// =============================================================================
//
// API client for the Tesslate Apps marketplace (Wave 3 backend).
//
// All mutations go through the shared `api` axios instance which already
// handles Bearer-token auth AND (for cookie-based OAuth sessions) attaches
// the X-CSRF-Token header via the request interceptor above. Do NOT add CSRF
// plumbing here — the interceptor on lines ~95-110 is authoritative.
//
// Endpoint routers (prefix → router):
//   /api/marketplace-apps   marketplace_apps.py
//   /api/app-versions       app_versions.py
//   /api/app-installs       app_installs.py
//   /api/apps/runtime       app_runtime.py
//   /api/apps/billing       app_billing.py
//   /api/app-submissions    app_submissions.py
//   /api/app-yanks          app_yanks.py
//   /api/admin-marketplace  admin_marketplace.py
//   /api/app-bundles        app_bundles.py
// =============================================================================

// --- Shared types -----------------------------------------------------------

export type ForkableMode = 'true' | 'restricted' | 'no';
export type AppVisibility = 'public' | 'unlisted' | 'private' | string;
export type AppState = 'draft' | 'review' | 'approved' | 'yanked' | string;
export type ApprovalState = 'draft' | 'pending' | 'approved' | 'rejected' | 'yanked' | string;
export type InstallState = 'installed' | 'running' | 'stopped' | 'uninstalled' | string;
export type UpdatePolicy = 'manual' | 'minor' | 'patch' | string;
export type YankSeverity = 'low' | 'medium' | 'critical' | string;
export type WalletType = 'installer' | 'creator' | 'platform';
export type SpendDimension = string;

export interface Paginated<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

// --- Marketplace Apps -------------------------------------------------------

export interface MarketplaceApp {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  category: string | null;
  icon_ref: string | null;
  forkable: ForkableMode;
  forked_from: string | null;
  visibility: AppVisibility;
  state: AppState;
  reputation: Record<string, unknown>;
  creator_user_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface AppVersionSummary {
  id: string;
  app_id: string;
  version: string;
  manifest_schema_version: string;
  manifest_hash: string;
  bundle_hash: string | null;
  approval_state: ApprovalState;
  yanked_at: string | null;
  yanked_reason: string | null;
  yanked_is_critical: boolean;
  published_at: string | null;
  created_at: string;
}

export interface AppVersionDetail extends AppVersionSummary {
  manifest_json: Record<string, unknown> | null;
  feature_set_hash: string;
  required_features: string[];
}

export interface CompatReport {
  compatible: boolean;
  missing_features: string[];
  unsupported_manifest_schema: boolean;
  upgrade_required: boolean;
  server_manifest_schemas: string[];
  server_feature_set_hash: string;
}

export interface ListAppsParams {
  q?: string;
  category?: string;
  creator_user_id?: string;
  limit?: number;
  offset?: number;
}

export const marketplaceAppsApi = {
  async list(params: ListAppsParams = {}): Promise<Paginated<MarketplaceApp>> {
    const response = await api.get('/api/marketplace-apps', { params });
    return response.data;
  },
  async get(appId: string): Promise<MarketplaceApp> {
    const response = await api.get(`/api/marketplace-apps/${appId}`);
    return response.data;
  },
  async listVersions(
    appId: string,
    params: { limit?: number; offset?: number } = {}
  ): Promise<Paginated<AppVersionSummary>> {
    const response = await api.get(`/api/marketplace-apps/${appId}/versions`, { params });
    return response.data;
  },
  async fork(
    appId: string,
    body: { source_app_version_id: string; new_slug: string; new_name: string; team_id?: string }
  ): Promise<MarketplaceApp & { project_id?: string | null; project_slug?: string | null }> {
    const response = await api.post(`/api/marketplace-apps/${appId}/fork`, body);
    return response.data;
  },
};

// --- App Versions -----------------------------------------------------------

export interface PublishRequest {
  project_id: string;
  manifest: string | Record<string, unknown>;
  app_id?: string | null;
}

export interface PublishResult {
  app_id: string;
  app_version_id: string;
  version: string;
  bundle_hash: string;
  manifest_hash: string;
  submission_id: string;
}

export const appVersionsApi = {
  async publish(body: PublishRequest): Promise<PublishResult> {
    const response = await api.post('/api/app-versions/publish', body);
    return response.data;
  },
  async get(appVersionId: string): Promise<AppVersionDetail> {
    const response = await api.get(`/api/app-versions/${appVersionId}`);
    return response.data;
  },
  async compat(appVersionId: string): Promise<CompatReport> {
    const response = await api.get(`/api/app-versions/${appVersionId}/compat`);
    return response.data;
  },
};

// --- App Installs -----------------------------------------------------------

export interface InstallRequest {
  app_version_id: string;
  team_id: string;
  wallet_mix_consent?: Record<string, unknown>;
  mcp_consents?: Record<string, unknown>[];
  update_policy?: UpdatePolicy;
}

export interface InstallResult {
  app_instance_id: string;
  project_id: string | null;
  volume_id: string;
  node_name: string;
}

export interface AppInstance {
  id: string;
  app_id: string;
  app_version_id: string;
  project_id: string | null;
  state: InstallState;
  update_policy: UpdatePolicy;
  volume_id: string | null;
  installed_at: string | null;
  uninstalled_at: string | null;
  created_at: string;
  app_slug: string | null;
  app_name: string | null;
  app_version: string | null;
}

export interface UninstallResult {
  app_instance_id: string;
  state: InstallState;
  uninstalled_at: string;
}

export interface AppContainerConnectionRow {
  source: string;
  target: string;
  connector_type: string | null;
}

export interface AppContainerRow {
  id: string;
  name: string;
  directory: string | null;
  image: string | null;
  container_type: string;
  kind: 'base' | 'service' | string;
  port: number | null;
  status: string;
  is_primary: boolean;
  connections: AppContainerConnectionRow[];
}

export interface AppScheduleDetailRow {
  id: string;
  name: string;
  trigger_kind: string;
  cron_expression: string | null;
  next_run_at: string | null;
  last_run_at: string | null;
  is_active: boolean;
}

export interface AppInstanceDetail extends AppInstance {
  project_slug: string | null;
  primary_container_id: string | null;
  compute_model: 'always-on' | 'job-only' | string | null;
  containers: AppContainerRow[];
  schedules: AppScheduleDetailRow[];
}

export const appInstallsApi = {
  async install(body: InstallRequest): Promise<InstallResult> {
    const response = await api.post('/api/app-installs/install', body);
    return response.data;
  },
  async listMine(
    params: { limit?: number; offset?: number } = {}
  ): Promise<Paginated<AppInstance>> {
    const response = await api.get('/api/app-installs/mine', { params });
    return response.data;
  },
  async getDetail(appInstanceId: string): Promise<AppInstanceDetail> {
    const response = await api.get(`/api/app-installs/${appInstanceId}`);
    return response.data;
  },
  async uninstall(appInstanceId: string): Promise<UninstallResult> {
    const response = await api.post(`/api/app-installs/${appInstanceId}/uninstall`);
    return response.data;
  },
};

// --- App Runtime Status (lifecycle for installed-app pods) -----------------

export type AppRuntimeState = 'stopped' | 'starting' | 'running' | 'error' | 'job_only';

export interface AppRuntimeContainer {
  id: string;
  name: string;
  status: string;
  url: string | null;
}

export interface AppRuntimeStatus {
  state: AppRuntimeState;
  primary_url: string | null;
  project_id: string;
  project_slug: string;
  containers: AppRuntimeContainer[];
}

export const appRuntimeStatusApi = {
  async getRuntime(appInstanceId: string): Promise<AppRuntimeStatus> {
    const response = await api.get(`/api/app-installs/${appInstanceId}/runtime`);
    return response.data;
  },
  async start(appInstanceId: string): Promise<AppRuntimeStatus> {
    const response = await api.post(`/api/app-installs/${appInstanceId}/start`);
    return response.data;
  },
  async stop(appInstanceId: string): Promise<AppRuntimeStatus> {
    const response = await api.post(`/api/app-installs/${appInstanceId}/stop`);
    return response.data;
  },
  async listSchedules(appInstanceId: string): Promise<AppScheduleRow[]> {
    const response = await api.get(`/api/app-installs/${appInstanceId}/schedules`);
    return response.data;
  },
  async patchSchedule(
    appInstanceId: string,
    scheduleId: string,
    body: { enabled?: boolean }
  ): Promise<AppScheduleRow> {
    const response = await api.patch(
      `/api/app-installs/${appInstanceId}/schedules/${scheduleId}`,
      body
    );
    return response.data;
  },
  async runSchedule(
    appInstanceId: string,
    scheduleId: string,
    payload: Record<string, unknown> = {}
  ): Promise<{ event_id: string; status: string }> {
    const response = await api.post(
      `/api/app-installs/${appInstanceId}/schedules/${scheduleId}/trigger`,
      payload
    );
    return response.data;
  },
};

export interface AppScheduleRow {
  id: string;
  name: string;
  cron: string | null;
  trigger_kind: string;
  last_run_at: string | null;
  last_status: string | null;
  enabled: boolean;
}

// --- App Runtime (sessions + invocations) -----------------------------------

export interface SessionRequest {
  app_instance_id: string;
  budget_usd?: number;
  ttl_seconds?: number;
}

export interface SessionHandle {
  session_id: string;
  app_instance_id: string;
  litellm_key_id: string;
  api_key: string;
  budget_usd: number;
  ttl_seconds: number;
}

export const appRuntimeApi = {
  async createSession(body: SessionRequest): Promise<SessionHandle> {
    const response = await api.post('/api/apps/runtime/sessions', body);
    return response.data;
  },
  async deleteSession(sessionId: string): Promise<void> {
    await api.delete(`/api/apps/runtime/sessions/${sessionId}`);
  },
  async createInvocation(body: SessionRequest): Promise<SessionHandle> {
    const response = await api.post('/api/apps/runtime/invocations', body);
    return response.data;
  },
  async deleteInvocation(sessionId: string): Promise<void> {
    await api.delete(`/api/apps/runtime/invocations/${sessionId}`);
  },
};

// --- App Billing (wallets, ledger, spend) -----------------------------------

export interface WalletSnapshot {
  id: string;
  owner_type: WalletType;
  owner_user_id: string | null;
  balance_usd: number;
  currency?: string;
  created_at?: string;
  updated_at?: string;
  [key: string]: unknown;
}

export interface LedgerEntry {
  id: string;
  wallet_id: string;
  entry_type: string;
  amount_usd: number;
  reference_type: string | null;
  reference_id: string | null;
  meta: Record<string, unknown>;
  created_at: string;
}

export interface SpendEntry {
  id: string;
  app_instance_id: string | null;
  session_id: string | null;
  installer_user_id: string | null;
  dimension: SpendDimension;
  payer: string;
  payer_user_id: string | null;
  amount_usd: number;
  litellm_key_id: string | null;
  usage_log_id: string | null;
  settled: boolean;
  settled_at: string | null;
  meta: Record<string, unknown>;
  created_at: string;
}

export interface SpendSummary {
  total_usd_30d: number;
  total_usd_7d: number;
  total_usd_24h: number;
  total_settled_usd: number;
  total_unsettled_usd: number;
  per_dimension: Record<string, number>;
  per_app: Array<{ app_instance_id: string | null; amount_usd: number }>;
}

export interface LedgerQuery {
  wallet_type?: WalletType;
  limit?: number;
  offset?: number;
  since?: string;
}

export interface SpendQuery {
  app_instance_id?: string;
  dimension?: SpendDimension;
  settled?: boolean;
  since?: string;
  limit?: number;
  offset?: number;
}

export const appBillingApi = {
  async getInstallerWallet(): Promise<WalletSnapshot> {
    const response = await api.get('/api/apps/billing/wallet');
    return response.data;
  },
  async getCreatorWallet(): Promise<WalletSnapshot> {
    const response = await api.get('/api/apps/billing/wallet/creator');
    return response.data;
  },
  async getLedger(params: LedgerQuery = {}): Promise<Paginated<LedgerEntry>> {
    const response = await api.get('/api/apps/billing/wallet/ledger', { params });
    return response.data;
  },
  async getSpend(params: SpendQuery = {}): Promise<Paginated<SpendEntry>> {
    const response = await api.get('/api/apps/billing/spend', { params });
    return response.data;
  },
  async getSpendSummary(): Promise<SpendSummary> {
    const response = await api.get('/api/apps/billing/spend/summary');
    return response.data;
  },
  async recordSpend(body: {
    app_instance_id: string;
    installer_user_id: string;
    dimension: SpendDimension;
    amount_usd: number;
    session_id?: string;
    litellm_key_id?: string;
    usage_log_id?: string;
    is_byok?: boolean;
    meta?: Record<string, unknown>;
  }): Promise<{ spend_record_id: string; payer: string; amount_usd: number; dimension: string }> {
    const response = await api.post('/api/apps/billing/spend/record', body);
    return response.data;
  },
  async getPlatformWallet(): Promise<WalletSnapshot & { recent_ledger: LedgerEntry[] }> {
    const response = await api.get('/api/apps/billing/wallet/admin/platform');
    return response.data;
  },
};

// --- App Submissions --------------------------------------------------------

export interface Submission {
  id: string;
  app_version_id: string;
  submitter_user_id: string | null;
  stage: string;
  decision: string;
  reviewer_user_id: string | null;
  decision_notes: string | null;
}

export interface SubmissionCheck {
  id: string;
  submission_id: string;
  stage: string;
  check_name: string;
  status: string;
  details: Record<string, unknown>;
}

export interface SubmissionDetail extends Submission {
  checks: SubmissionCheck[];
}

export interface ScanRunResult {
  submission: SubmissionDetail;
  result: Record<string, unknown>;
}

export const appSubmissionsApi = {
  async list(
    params: {
      stage?: string;
      reviewer_user_id?: string;
      limit?: number;
      offset?: number;
    } = {}
  ): Promise<Paginated<Submission>> {
    const response = await api.get('/api/app-submissions/', { params });
    return response.data;
  },
  async get(submissionId: string): Promise<SubmissionDetail> {
    const response = await api.get(`/api/app-submissions/${submissionId}`);
    return response.data;
  },
  async advance(
    submissionId: string,
    body: { to_stage: string; decision_notes?: string }
  ): Promise<Submission> {
    const response = await api.post(`/api/app-submissions/${submissionId}/advance`, body);
    return response.data;
  },
  async recordCheck(
    submissionId: string,
    body: {
      stage: string;
      check_name: string;
      status: string;
      details?: Record<string, unknown>;
    }
  ): Promise<{ check_id: string }> {
    const response = await api.post(`/api/app-submissions/${submissionId}/checks`, body);
    return response.data;
  },
  async runStage1Scan(submissionId: string): Promise<ScanRunResult> {
    const response = await api.post(`/api/app-submissions/${submissionId}/scan/stage1`);
    return response.data;
  },
  async runStage2Eval(submissionId: string): Promise<ScanRunResult> {
    const response = await api.post(`/api/app-submissions/${submissionId}/scan/stage2`);
    return response.data;
  },
};

// --- App Yanks --------------------------------------------------------------

export interface YankRequest {
  id: string;
  app_version_id: string;
  requester_user_id: string | null;
  severity: YankSeverity;
  reason: string;
  status: string;
  primary_admin_id: string | null;
  secondary_admin_id: string | null;
}

export interface YankApproveResult {
  status: string;
  needs_second_admin: boolean;
  primary_admin_id: string | null;
  secondary_admin_id: string | null;
}

export const appYanksApi = {
  async create(body: {
    app_version_id: string;
    severity: YankSeverity;
    reason: string;
  }): Promise<{ yank_request_id: string }> {
    const response = await api.post('/api/app-yanks/', body);
    return response.data;
  },
  async approve(yankRequestId: string): Promise<YankApproveResult> {
    const response = await api.post(`/api/app-yanks/${yankRequestId}/approve`);
    return response.data;
  },
  async reject(yankRequestId: string, note?: string): Promise<{ status: string }> {
    const response = await api.post(`/api/app-yanks/${yankRequestId}/reject`, { note });
    return response.data;
  },
  async appeal(yankRequestId: string, reason: string): Promise<{ appeal_id: string }> {
    const response = await api.post(`/api/app-yanks/${yankRequestId}/appeal`, { reason });
    return response.data;
  },
  async list(
    params: { limit?: number; offset?: number; status?: string } = {}
  ): Promise<Paginated<YankRequest>> {
    const response = await api.get('/api/app-yanks/', { params });
    return response.data;
  },
};

// --- Admin Marketplace ------------------------------------------------------

export interface SubmissionQueueItem {
  submission_id: string;
  app_version_id: string;
  app_id: string;
  app_name: string | null;
  version: string | null;
  stage: string;
  sla_deadline_at: string | null;
  stage_entered_at: string | null;
  check_count: number;
}

export interface YankQueueItem {
  id: string;
  app_version_id: string;
  severity: YankSeverity;
  status: string;
  reason: string;
  created_at: string | null;
}

export interface AdminStats {
  apps_total: number;
  apps_approved: number;
  apps_pending: number;
  yanks_pending: number;
  submissions_in_flight: number;
  monitoring_runs_24h: number;
}

export const adminMarketplaceApi = {
  async getQueue(
    params: { limit?: number; offset?: number } = {}
  ): Promise<{ items: SubmissionQueueItem[]; limit: number; offset: number }> {
    const response = await api.get('/api/admin-marketplace/queue', { params });
    return response.data;
  },
  async getYankQueue(
    params: { limit?: number; offset?: number } = {}
  ): Promise<{ items: YankQueueItem[]; limit: number; offset: number }> {
    const response = await api.get('/api/admin-marketplace/yank-queue', { params });
    return response.data;
  },
  async getStats(): Promise<AdminStats> {
    const response = await api.get('/api/admin-marketplace/stats');
    return response.data;
  },
  async startMonitoringRun(body: {
    app_version_id: string;
    kind: string;
  }): Promise<{ run_id: string }> {
    const response = await api.post('/api/admin-marketplace/monitoring/runs', body);
    return response.data;
  },
  async finishMonitoringRun(
    runId: string,
    body: { status: string; findings?: Record<string, unknown> }
  ): Promise<void> {
    await api.patch(`/api/admin-marketplace/monitoring/runs/${runId}`, body);
  },
  async recordAdversarialRun(body: {
    suite_id: string;
    app_version_id: string;
    score?: number;
    findings?: Record<string, unknown>;
  }): Promise<{ run_id: string }> {
    const response = await api.post('/api/admin-marketplace/adversarial/runs', body);
    return response.data;
  },
  async adjustReputation(
    userId: string,
    body: {
      delta_score?: number;
      delta_approvals?: number;
      delta_yanks?: number;
      delta_critical_yanks?: number;
    }
  ): Promise<void> {
    await api.post(`/api/admin-marketplace/reputation/${userId}`, body);
  },
};

// --- App Bundles ------------------------------------------------------------

export interface BundleItem {
  app_version_id: string;
  order_index: number;
  default_enabled: boolean;
  required: boolean;
}

export interface BundleDetail {
  id: string;
  slug: string;
  display_name: string;
  status: string;
  consolidated_manifest_hash: string | null;
  items: BundleItem[];
}

export interface BundleListItem {
  id: string;
  slug: string;
  display_name: string;
  status: string;
  owner_user_id: string | null;
}

export interface BundleInstallItemRequest {
  app_version_id: string;
  wallet_mix_consent?: Record<string, unknown>;
  mcp_consents?: Record<string, unknown>[];
}

export interface BundleInstallResult {
  succeeded: Array<{
    app_version_id: string;
    app_instance_id: string;
    project_id: string;
  }>;
  failed: Array<{ app_version_id: string; error: string }>;
  note: string | null;
}

export const appBundlesApi = {
  async list(
    params: {
      owner_user_id?: string;
      status?: string;
      limit?: number;
      offset?: number;
    } = {}
  ): Promise<Paginated<BundleListItem>> {
    const response = await api.get('/api/app-bundles', { params });
    return response.data;
  },
  async get(bundleId: string): Promise<BundleDetail> {
    const response = await api.get(`/api/app-bundles/${bundleId}`);
    return response.data;
  },
  async create(body: {
    slug: string;
    display_name: string;
    items: Array<{
      app_version_id: string;
      order_index?: number;
      default_enabled?: boolean;
      required?: boolean;
    }>;
    summary?: string;
    description?: string;
  }): Promise<{ bundle_id: string }> {
    const response = await api.post('/api/app-bundles', body);
    return response.data;
  },
  async publish(bundleId: string): Promise<void> {
    await api.post(`/api/app-bundles/${bundleId}/publish`);
  },
  async yank(bundleId: string, reason: string): Promise<void> {
    await api.post(`/api/app-bundles/${bundleId}/yank`, { reason });
  },
  async install(
    bundleId: string,
    body: { team_id: string; installs: BundleInstallItemRequest[] }
  ): Promise<BundleInstallResult> {
    const response = await api.post(`/api/app-bundles/${bundleId}/install`, body);
    return response.data;
  },
};

// =============================================================================
// ===== /Tesslate Apps =====
// =============================================================================

// =============================================================================
// ===== Automations (Phase 1) =====
// =============================================================================
//
// HTTP client for the Automation Runtime. Endpoint shapes mirror
// ``orchestrator/app/schemas_automations.py`` — see the matching
// ``app/src/types/automations.ts`` types.
//
// Auth: relies on the same Bearer / cookie/CSRF flow the rest of the file uses
// via the shared `api` axios instance. No special handling here.
// =============================================================================

import type {
  AppActionListResponse,
  ApprovalRequest,
  ApprovalResponse,
  AutomationDefinitionIn,
  AutomationDefinitionOut,
  AutomationDefinitionSummary,
  AutomationDefinitionUpdate,
  AutomationRunArtifactOut,
  AutomationRunDetail,
  AutomationRunRequest,
  AutomationRunResponse,
  AutomationRunSummary,
} from '../types/automations';

export interface ListAutomationsParams {
  is_active?: boolean;
  workspace_scope?: string;
  team_id?: string;
  limit?: number;
  offset?: number;
}

export interface ListRunsParams {
  status?: string;
  limit?: number;
  offset?: number;
}

export const automationsApi = {
  async list(params?: ListAutomationsParams): Promise<AutomationDefinitionSummary[]> {
    const qs = new URLSearchParams();
    if (params?.is_active !== undefined) qs.append('is_active', String(params.is_active));
    if (params?.workspace_scope) qs.append('workspace_scope', params.workspace_scope);
    if (params?.team_id) qs.append('team_id', params.team_id);
    if (params?.limit !== undefined) qs.append('limit', String(params.limit));
    if (params?.offset !== undefined) qs.append('offset', String(params.offset));
    const suffix = qs.toString() ? `?${qs.toString()}` : '';
    const response = await api.get(`/api/automations${suffix}`);
    return response.data;
  },

  async create(payload: AutomationDefinitionIn): Promise<AutomationDefinitionOut> {
    const response = await api.post('/api/automations', payload);
    return response.data;
  },

  async get(id: string): Promise<AutomationDefinitionOut> {
    const response = await api.get(`/api/automations/${id}`);
    return response.data;
  },

  async update(
    id: string,
    payload: AutomationDefinitionUpdate
  ): Promise<AutomationDefinitionOut> {
    const response = await api.patch(`/api/automations/${id}`, payload);
    return response.data;
  },

  /**
   * Soft-delete by default (sets is_active=false). Pass `hard=true` to
   * fully remove a definition that has zero runs (server returns 409 if
   * any runs exist).
   */
  async remove(id: string, hard = false): Promise<{ status: string; id: string; hard: boolean }> {
    const suffix = hard ? '?hard=true' : '';
    const response = await api.delete(`/api/automations/${id}${suffix}`);
    return response.data;
  },

  async run(id: string, payload?: AutomationRunRequest): Promise<AutomationRunResponse> {
    const response = await api.post(`/api/automations/${id}/run`, payload ?? {});
    return response.data;
  },

  async listRuns(
    id: string,
    params?: ListRunsParams
  ): Promise<AutomationRunSummary[]> {
    const qs = new URLSearchParams();
    if (params?.status) qs.append('status', params.status);
    if (params?.limit !== undefined) qs.append('limit', String(params.limit));
    if (params?.offset !== undefined) qs.append('offset', String(params.offset));
    const suffix = qs.toString() ? `?${qs.toString()}` : '';
    const response = await api.get(`/api/automations/${id}/runs${suffix}`);
    return response.data;
  },

  async getRun(id: string, runId: string): Promise<AutomationRunDetail> {
    const response = await api.get(`/api/automations/${id}/runs/${runId}`);
    return response.data;
  },

  async listRunArtifacts(id: string, runId: string): Promise<AutomationRunArtifactOut[]> {
    const response = await api.get(`/api/automations/${id}/runs/${runId}/artifacts`);
    return response.data;
  },

  /**
   * URL of the artifact-download endpoint. The endpoint either streams
   * inline content or 307-redirects to a signed S3 URL — easiest for the
   * UI to just open it in a new tab / treat it as a link target.
   */
  artifactDownloadUrl(id: string, runId: string, artifactId: string): string {
    return `${API_URL}/api/automations/${id}/runs/${runId}/artifacts/${artifactId}`;
  },

  /**
   * HITL approval surface. Phase 2 ships these endpoints alongside the
   * Wave 2A response handler:
   *
   * - ``GET /api/automations/approvals/pending`` — cross-automation list
   *   for the badge + ApprovalsPage.
   * - ``GET /api/automations/{id}/approvals/{request_id}`` — single
   *   request fetch (drawer hydration).
   * - ``POST /api/automations/{id}/approvals/{request_id}/respond`` —
   *   submit a resolution. Owned by Wave 2A; this client just calls it.
   */
  approvals: {
    /** Cross-automation pending list. Used by the badge + ApprovalsPage. */
    async listPending(): Promise<ApprovalRequest[]> {
      const response = await api.get('/api/automations/approvals/pending');
      // Backend may shape this as either a bare list or { items: [...] }.
      const data = response.data;
      if (Array.isArray(data)) return data as ApprovalRequest[];
      if (Array.isArray(data?.items)) return data.items as ApprovalRequest[];
      return [];
    },

    /** Pending count — convenience wrapper for the sidebar badge. */
    async pendingCount(): Promise<number> {
      try {
        const list = await this.listPending();
        return list.length;
      } catch {
        return 0;
      }
    },

    /** Single approval fetch — drawer hydration. */
    async get(automationId: string, requestId: string): Promise<ApprovalRequest> {
      const response = await api.get(
        `/api/automations/${automationId}/approvals/${requestId}`
      );
      return response.data;
    },

    /** Submit a resolution (allow/deny/request_changes). */
    async respond(
      automationId: string,
      requestId: string,
      payload: ApprovalResponse
    ): Promise<ApprovalRequest> {
      const response = await api.post(
        `/api/automations/${automationId}/approvals/${requestId}/respond`,
        payload
      );
      return response.data;
    },
  },
};

export const appActionsApi = {
  /** GET /api/apps/{app_instance_id}/actions — read-only listing. */
  async list(appInstanceId: string): Promise<AppActionListResponse> {
    const response = await api.get(`/api/apps/${appInstanceId}/actions`);
    return response.data;
  },
};

// =============================================================================
// ===== /Automations =====
// =============================================================================

export default api;
