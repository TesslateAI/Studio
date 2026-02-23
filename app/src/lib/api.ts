import axios from 'axios';
import type { AgentChatRequest, AgentChatResponse, Agent, AgentCreate } from '../types/agent';
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
 * Authentication with fastapi-users:
 * - JWT Bearer tokens for API authentication
 * - Cookie-based OAuth authentication with CSRF protection
 * - No refresh tokens (tokens are long-lived)
 * - Redirect to login on 401 errors
 */

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

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    // If error is 401, redirect to login
    // BUT: Don't redirect for certain cases where 401 is expected
    if (error.response?.status === 401) {
      const isTasksApi = error.config?.url?.includes('/api/tasks/');
      const isMarketplacePage = window.location.pathname.startsWith('/marketplace');
      const isPreferencesApi = error.config?.url?.includes('/api/users/preferences');
      const isPasswordResetPage =
        window.location.pathname === '/forgot-password' ||
        window.location.pathname === '/reset-password';

      // Skip redirect for:
      // - Tasks API (transient errors during background operations)
      // - Marketplace pages (public access, 401 is expected for unauthenticated)
      // - Preferences API (optional, fails silently for unauthenticated)
      // - Password reset pages (public, no auth required)
      if (!isTasksApi && !isMarketplacePage && !isPreferencesApi && !isPasswordResetPage) {
        localStorage.removeItem('token');
        if (window.location.pathname !== '/login') {
          window.location.href = '/login';
        }
      }
      // For skipped cases, just reject the error without logging out/redirecting
    }

    // If error is 403 and mentions CSRF, refetch token and retry
    if (error.response?.status === 403 && error.response?.data?.detail?.includes('CSRF')) {
      await fetchCsrfToken();
      // Retry the request once with new CSRF token
      if (error.config && !error.config._retry) {
        error.config._retry = true;
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
    // Call both logout endpoints to clear all auth state
    // JWT logout clears the Bearer token mechanism
    // Cookie logout clears the httpOnly auth cookie (for OAuth users)
    try {
      await Promise.all([
        api.post('/api/auth/jwt/logout').catch(() => {}),
        api.post('/api/auth/cookie/logout').catch(() => {}),
      ]);
    } catch {
      // Ignore errors, we're logging out anyway
    }
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

export const projectsApi = {
  getAll: async () => {
    const response = await api.get('/api/projects/');
    return response.data;
  },
  create: async (
    name: string,
    description?: string,
    sourceType?: 'template' | 'github' | 'gitlab' | 'bitbucket' | 'base',
    repoUrl?: string,
    branch?: string,
    baseId?: string
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
    }

    const response = await api.post('/api/projects/', body);
    // Response now includes { project, task_id, status_endpoint }
    return response.data;
  },
  get: async (slug: string) => {
    const response = await api.get(`/api/projects/${slug}`);
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
  deleteFile: async (slug: string, filePath: string) => {
    const response = await api.delete(`/api/projects/${slug}/files`, {
      data: { file_path: filePath },
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
      ...completedTask.result,
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
    const response = await api.patch(`/api/projects/${slug}/containers/${containerId}/deployment-target`, {
      provider
    });
    return response.data;
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
  clearProjectMessages: async (projectId: string) => {
    const response = await api.delete(`/api/chat/${projectId}/messages`);
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
            try {
              const event = JSON.parse(jsonStr);
              onEvent(event);
            } catch (e) {
              console.error('Failed to parse SSE event:', e, jsonStr);
            }
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
  getAllBases: async (params?: {
    category?: string;
    pricing_type?: string;
    search?: string;
    sort?: string;
    page?: number;
    limit?: number;
  }) => {
    const queryParams = new URLSearchParams();
    if (params?.category) queryParams.append('category', params.category);
    if (params?.pricing_type) queryParams.append('pricing_type', params.pricing_type);
    if (params?.search) queryParams.append('search', params.search);
    if (params?.sort) queryParams.append('sort', params.sort);
    if (params?.page) queryParams.append('page', params.page.toString());
    if (params?.limit) queryParams.append('limit', params.limit.toString());

    const response = await api.get(`/api/marketplace/bases?${queryParams}`);
    return response.data;
  },

  getBaseDetails: async (slug: string) => {
    const response = await api.get(`/api/marketplace/bases/${slug}`);
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

export const agentsApi = {
  getAll: async (): Promise<Agent[]> => {
    const response = await api.get('/api/agents/');
    return response.data;
  },
  get: async (id: string): Promise<Agent> => {
    const response = await api.get(`/api/agents/${id}`);
    return response.data;
  },
  create: async (agent: AgentCreate): Promise<Agent> => {
    const response = await api.post('/api/agents/', agent);
    return response.data;
  },
  update: async (id: string, agent: Partial<AgentCreate>): Promise<Agent> => {
    const response = await api.put(`/api/agents/${id}`, agent);
    return response.data;
  },
  delete: async (id: string) => {
    const response = await api.delete(`/api/agents/${id}`);
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

// Add diagram generation to projectsApi
export const diagramApi = {
  // Generate architecture diagram for a project
  generateDiagram: async (slug: string, diagramType: 'mermaid' | 'c4_plantuml' = 'mermaid') => {
    const response = await api.post(`/api/projects/${slug}/generate-architecture-diagram`, null, {
      params: { diagram_type: diagramType },
    });
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
let appConfigCache: { app_domain: string; deployment_mode: string } | null = null;

export const configApi = {
  /**
   * Get app configuration (app_domain, deployment_mode)
   * Cached after first fetch
   */
  getConfig: async () => {
    if (appConfigCache) {
      return appConfigCache;
    }
    const response = await api.get('/api/config');
    appConfigCache = response.data;
    return appConfigCache;
  },

  /**
   * Get app_domain, with fallback to 'localhost'
   */
  getAppDomain: async (): Promise<string> => {
    const config = await configApi.getConfig();
    return config?.app_domain || 'localhost';
  },
};

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
  list: async (provider?: string) => {
    const response = await api.get('/api/deployment-credentials', {
      params: { provider },
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
    const { auth_url } = response.data;

    // Redirect to the OAuth provider
    window.location.href = auth_url;
    return response.data;
  },

  // Save manual credentials (alias for create for better semantics)
  saveManual: async (provider: string, credentials: Record<string, string>) => {
    // Extract the token field (different providers use different names)
    const tokenField = credentials.api_token || credentials.access_token || credentials.token;

    // Extract other fields as metadata
    const metadata: Record<string, string> = {};
    for (const [key, value] of Object.entries(credentials)) {
      if (!['api_token', 'access_token', 'token'].includes(key)) {
        metadata[key] = value;
      }
    }

    return deploymentCredentialsApi.create({
      provider,
      access_token: tokenField,
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
  deployAll: async (projectSlug: string): Promise<{
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
    const response = await api.get(`/api/deployments/deployments/${deploymentId}`);
    return response.data;
  },

  // Get deployment status
  getStatus: async (deploymentId: string) => {
    const response = await api.get(`/api/deployments/deployments/${deploymentId}/status`);
    return response.data;
  },

  // Get deployment logs
  getLogs: async (deploymentId: string) => {
    const response = await api.get(`/api/deployments/deployments/${deploymentId}/logs`);
    return response.data;
  },

  // Delete deployment
  delete: async (deploymentId: string) => {
    const response = await api.delete(`/api/deployments/deployments/${deploymentId}`);
    return response.data;
  },

  // Stream deployment progress (SSE)
  streamProgress: (
    deploymentId: string,
    onMessage: (data: Record<string, unknown>) => void,
    onError?: (error: Event) => void
  ) => {
    const eventSource = new EventSource(
      `${API_URL}/api/deployments/deployments/${deploymentId}/stream`,
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
// Project Snapshots API (Timeline - EBS VolumeSnapshots)
// =============================================================================

export interface Snapshot {
  id: string;
  project_id: string | null;
  snapshot_name: string;
  snapshot_type: 'hibernation' | 'manual';
  status: 'pending' | 'ready' | 'error' | 'deleted';
  label: string | null;
  volume_size_bytes: number | null;
  created_at: string;
  ready_at: string | null;
}

export interface SnapshotListResponse {
  snapshots: Snapshot[];
  total_count: number;
  max_snapshots: number;
}

export interface RestoreSnapshotResponse {
  success: boolean;
  message: string;
  snapshot_id: string;
  restored_from: string;
}

export const snapshotsApi = {
  // List all snapshots for a project (Timeline)
  list: async (projectId: string): Promise<SnapshotListResponse> => {
    const response = await api.get(`/api/projects/${projectId}/snapshots/`);
    return response.data;
  },

  // Get a specific snapshot
  get: async (projectId: string, snapshotId: string): Promise<Snapshot> => {
    const response = await api.get(`/api/projects/${projectId}/snapshots/${snapshotId}`);
    return response.data;
  },

  // Create a manual snapshot
  create: async (projectId: string, label?: string): Promise<Snapshot> => {
    const response = await api.post(`/api/projects/${projectId}/snapshots/`, { label });
    return response.data;
  },

  // Restore from a specific snapshot
  restore: async (projectId: string, snapshotId: string): Promise<RestoreSnapshotResponse> => {
    const response = await api.post(`/api/projects/${projectId}/snapshots/${snapshotId}/restore`);
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
 * Create a WebSocket connection for interactive terminal access
 * @param projectId - The project ID or slug
 * @returns WebSocket instance connected to the terminal endpoint
 */
export const createTerminalWebSocket = (projectId: string): WebSocket => {
  let wsUrl: string;
  if (API_URL) {
    wsUrl = API_URL.replace('http', 'ws');
  } else {
    // Use current location for WebSocket when no API_URL is set
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    wsUrl = `${protocol}//${window.location.host}`;
  }
  return new WebSocket(`${wsUrl}/api/projects/${projectId}/terminal`);
};

export default api;
