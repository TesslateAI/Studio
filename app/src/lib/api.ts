import axios from 'axios';
import type { AgentChatRequest, AgentChatResponse, Agent, AgentCreate } from '../types/agent';

const API_URL = import.meta.env.VITE_API_URL || '';

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
 * - Cookie-based authentication (for OAuth)
 * - CSRF protection for cookie-based POST requests
 * - No refresh tokens (tokens are long-lived)
 * - Redirect to login on 401 errors
 */

// Store CSRF token
let csrfToken: string | null = null;

// Fetch CSRF token from server
export const fetchCsrfToken = async () => {
  try {
    const response = await axios.get(`${API_URL}/api/auth/csrf`, {
      withCredentials: true,
    });
    csrfToken = response.data.csrf_token;
    return csrfToken;
  } catch (error) {
    console.error('Failed to fetch CSRF token:', error);
    return null;
  }
};

// Initialize CSRF token on module load
fetchCsrfToken();

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }

  // Add CSRF token for state-changing requests (if using cookie auth)
  if (!token && csrfToken && ['post', 'put', 'delete', 'patch'].includes(config.method?.toLowerCase() || '')) {
    config.headers['X-CSRF-Token'] = csrfToken;
  }

  return config;
});

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    // If error is 401, redirect to login
    if (error.response?.status === 401) {
      localStorage.removeItem('token');
      if (window.location.pathname !== '/login') {
        window.location.href = '/login';
      }
    }

    // If error is 403 and mentions CSRF, try to refetch CSRF token and retry
    if (error.response?.status === 403 && error.response?.data?.detail?.includes('CSRF')) {
      await fetchCsrfToken();
      // Retry the request once with new CSRF token
      if (csrfToken) {
        const config = error.config;
        config.headers['X-CSRF-Token'] = csrfToken;
        return api.request(config);
      }
    }

    return Promise.reject(error);
  }
);

export const authApi = {
  // Login with JWT bearer token (fastapi-users endpoint)
  login: async (username: string, password: string) => {
    const formData = new URLSearchParams();
    formData.append('username', username);
    formData.append('password', password);
    const response = await api.post('/api/auth/jwt/login', formData, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    });
    return response.data;
  },

  // Register new user (fastapi-users endpoint)
  register: async (name: string, username: string, email: string, password: string) => {
    // Check if there's a referrer in sessionStorage
    const referred_by = sessionStorage.getItem('referrer');

    const response = await api.post('/api/auth/register', {
      name,
      username,
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

  // Logout
  logout: async () => {
    try {
      await api.post('/api/auth/jwt/logout');
    } catch (error) {
      // Ignore errors, we're logging out anyway
    }
    localStorage.removeItem('token');
    csrfToken = null;
  },

  // Refresh CSRF token (call after OAuth login or on app init)
  refreshCsrfToken: async () => {
    return await fetchCsrfToken();
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
};

export const projectsApi = {
  getAll: async () => {
    const response = await api.get('/api/projects/');
    return response.data;
  },
  create: async (
    name: string,
    description?: string,
    sourceType?: 'template' | 'github' | 'base',
    githubRepoUrl?: string,
    githubBranch?: string,
    baseId?: string
  ) => {
    const body: any = {
      name,
      description,
      source_type: sourceType || 'template'
    };

    if (sourceType === 'github') {
      body.github_repo_url = githubRepoUrl;
      body.github_branch = githubBranch || 'main';
    } else if (sourceType === 'base') {
      body.base_id = baseId;
    }

    const response = await api.post('/api/projects/', body);
    return response.data;
  },
  get: async (slug: string) => {
    const response = await api.get(`/api/projects/${slug}`);
    return response.data;
  },
  delete: async (slug: string) => {
    const response = await api.delete(`/api/projects/${slug}`);
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
      content: content
    });
    return response.data;
  },
  getSettings: async (slug: string) => {
    const response = await api.get(`/api/projects/${slug}/settings`);
    return response.data;
  },
  updateSettings: async (slug: string, settings: any) => {
    const response = await api.patch(`/api/projects/${slug}/settings`, { settings });
    return response.data;
  },
  forkProject: async (id: string) => {
    const response = await api.post(`/api/projects/${id}/fork`);
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
    onEvent: (event: { type: string; data: any }) => void,
    signal?: AbortSignal
  ): Promise<void> => {
    const token = localStorage.getItem('token');

    // Build headers - support both Bearer token and cookie-based auth
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    };

    if (token) {
      // Use Bearer token authentication (regular login)
      headers['Authorization'] = `Bearer ${token}`;
    } else {
      // Use cookie-based authentication (OAuth login) with CSRF token
      if (!csrfToken) {
        await fetchCsrfToken();
      }
      if (csrfToken) {
        headers['X-CSRF-Token'] = csrfToken;
      }
    }

    const response = await fetch(`${API_URL}/api/chat/agent/stream`, {
      method: 'POST',
      headers,
      body: JSON.stringify(request),
      credentials: 'include', // Include cookies for cookie-based auth
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
};

export const marketplaceApi = {
  // Get all marketplace agents
  getAllAgents: async () => {
    const response = await api.get('/api/marketplace/agents');
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

  // Fork an open source agent
  forkAgent: async (agentId: string, customizations?: {
    name?: string;
    description?: string;
    system_prompt?: string;
    model?: string;
  }) => {
    const response = await api.post(`/api/marketplace/agents/${agentId}/fork`, customizations || {});
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
  updateAgent: async (agentId: string, data: {
    name?: string;
    description?: string;
    system_prompt?: string;
    model?: string;
  }) => {
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

  // Add custom OpenRouter model
  addCustomModel: async (data: {
    model_id: string;
    model_name: string;
    pricing_input?: number;
    pricing_output?: number;
  }) => {
    const response = await api.post('/api/marketplace/models/custom', data);
    return response.data;
  },

  // Delete custom model
  deleteCustomModel: async (modelId: number) => {
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

  purchaseBase: async (baseId: number) => {
    const response = await api.post(`/api/marketplace/bases/${baseId}/purchase`);
    return response.data;
  },

  getUserBases: async () => {
    const response = await api.get('/api/marketplace/my-bases');
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
    provider_metadata?: any;
  }) => {
    const response = await api.post('/api/secrets/api-keys', data);
    return response.data;
  },

  // Update API key
  updateApiKey: async (keyId: number, data: {
    api_key?: string;
    key_name?: string;
    provider_metadata?: any;
  }) => {
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
};

export const usersApi = {
  // Get user preferences
  getPreferences: async () => {
    const response = await api.get('/api/users/preferences');
    return response.data;
  },

  // Update user preferences
  updatePreferences: async (data: { diagram_model?: string }) => {
    const response = await api.patch('/api/users/preferences', data);
    return response.data;
  },
};

// Add diagram generation to projectsApi
export const diagramApi = {
  // Generate architecture diagram for a project
  generateDiagram: async (slug: string, diagramType: 'mermaid' | 'c4_plantuml' = 'mermaid') => {
    const response = await api.post(`/api/projects/${slug}/generate-architecture-diagram`, null, {
      params: { diagram_type: diagramType }
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

export default api;