import axios from 'axios';
import type { AgentChatRequest, AgentChatResponse, Agent, AgentCreate } from '../types/agent';

const API_URL = import.meta.env.VITE_API_URL || '';

const api = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

/**
 * Token refresh implementation following best practices:
 * 1. Attempt to refresh token on 401 errors
 * 2. Automatically refresh before token expires (proactive)
 * 3. Only logout if refresh fails
 */

let isRefreshing = false;
let refreshSubscribers: ((token: string) => void)[] = [];

const subscribeTokenRefresh = (callback: (token: string) => void) => {
  refreshSubscribers.push(callback);
};

const onTokenRefreshed = (token: string) => {
  refreshSubscribers.forEach((callback) => callback(token));
  refreshSubscribers = [];
};

const refreshAccessToken = async (): Promise<string | null> => {
  const refreshToken = localStorage.getItem('refreshToken');
  if (!refreshToken) {
    return null;
  }

  try {
    const response = await axios.post(`${API_URL}/api/auth/refresh`, {
      refresh_token: refreshToken,
    });

    const { access_token, refresh_token: newRefreshToken } = response.data;

    // Store new tokens
    localStorage.setItem('token', access_token);
    if (newRefreshToken) {
      localStorage.setItem('refreshToken', newRefreshToken);
    }

    return access_token;
  } catch (error) {
    // Refresh failed - clear tokens and logout
    localStorage.removeItem('token');
    localStorage.removeItem('refreshToken');
    return null;
  }
};

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;

    // If error is 401 and we haven't tried to refresh yet
    if (error.response?.status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        // Wait for the ongoing refresh to complete
        return new Promise((resolve) => {
          subscribeTokenRefresh((token: string) => {
            originalRequest.headers.Authorization = `Bearer ${token}`;
            resolve(api(originalRequest));
          });
        });
      }

      originalRequest._retry = true;
      isRefreshing = true;

      try {
        const newToken = await refreshAccessToken();

        if (newToken) {
          isRefreshing = false;
          onTokenRefreshed(newToken);
          originalRequest.headers.Authorization = `Bearer ${newToken}`;
          return api(originalRequest);
        } else {
          // Refresh failed - redirect to login
          isRefreshing = false;
          window.location.href = '/login';
          return Promise.reject(error);
        }
      } catch (refreshError) {
        isRefreshing = false;
        window.location.href = '/login';
        return Promise.reject(refreshError);
      }
    }

    return Promise.reject(error);
  }
);

export const authApi = {
  login: async (username: string, password: string) => {
    const formData = new URLSearchParams();
    formData.append('username', username);
    formData.append('password', password);
    const response = await api.post('/api/auth/token', formData, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    });
    return response.data;
  },
  register: async (name: string, username: string, email: string, password: string) => {
    // Check if there's a referrer in sessionStorage
    const referred_by = sessionStorage.getItem('referrer');

    const response = await api.post('/api/auth/register', {
      name,
      username,
      email,
      password,
      referred_by: referred_by || undefined,
    });
    return response.data;
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
  sendAgentMessage: async (request: AgentChatRequest): Promise<AgentChatResponse> => {
    const response = await api.post('/api/chat/agent', request);
    return response.data;
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

  // Add custom model from any provider
  addCustomModel: async (data: {
    model_id: string;
    model_name: string;
    provider: string;  // openrouter, ollama, lmstudio, llamacpp, custom
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

  // Fetch available models from a provider's API
  fetchModels: async (provider: string, baseUrl?: string) => {
    const response = await api.post('/api/marketplace/models/fetch', {
      provider,
      base_url: baseUrl
    });
    return response.data; // { models: [], count: number, provider: string }
  },

  // Import multiple models at once from a provider
  importBatchModels: async (data: {
    provider: string;
    models: Array<{ model_id?: string; id?: string; model_name?: string; name?: string; [key: string]: any }>;
  }) => {
    const response = await api.post('/api/marketplace/models/import-batch', data);
    return response.data; // { imported: number, skipped: number, total: number }
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
  generateDiagram: async (slug: string) => {
    const response = await api.post(`/api/projects/${slug}/generate-architecture-diagram`);
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