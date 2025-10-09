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
  register: async (username: string, email: string, password: string) => {
    const response = await api.post('/api/auth/register', {
      username,
      email,
      password,
    });
    return response.data;
  },
};

export const projectsApi = {
  getAll: async () => {
    const response = await api.get('/api/projects/');
    return response.data;
  },
  create: async (name: string, description?: string) => {
    const response = await api.post('/api/projects/', { name, description });
    return response.data;
  },
  get: async (id: number) => {
    const response = await api.get(`/api/projects/${id}`);
    return response.data;
  },
  delete: async (id: number) => {
    const response = await api.delete(`/api/projects/${id}`);
    return response.data;
  },
  getFiles: async (id: number) => {
    const response = await api.get(`/api/projects/${id}/files`);
    return response.data;
  },
  getDevServerUrl: async (id: number) => {
    const response = await api.get(`/api/projects/${id}/dev-server-url`);
    return response.data;
  },
  restartDevServer: async (id: number) => {
    const response = await api.post(`/api/projects/${id}/restart-dev-container`);
    return response.data;
  },
  saveFile: async (id: number, filePath: string, content: string) => {
    const response = await api.post(`/api/projects/${id}/files/save`, {
      file_path: filePath,
      content: content
    });
    return response.data;
  },
};

export const chatApi = {
  create: async (projectId?: number) => {
    const response = await api.post('/api/chat/', { project_id: projectId });
    return response.data;
  },
  getAll: async () => {
    const response = await api.get('/api/chat/');
    return response.data;
  },
  getProjectMessages: async (projectId: number) => {
    const response = await api.get(`/api/chat/${projectId}/messages`);
    return response.data;
  },
  sendAgentMessage: async (request: AgentChatRequest): Promise<AgentChatResponse> => {
    const response = await api.post('/api/chat/agent', request);
    return response.data;
  },
};

export const agentsApi = {
  getAll: async (): Promise<Agent[]> => {
    const response = await api.get('/api/agents/');
    return response.data;
  },
  get: async (id: number): Promise<Agent> => {
    const response = await api.get(`/api/agents/${id}`);
    return response.data;
  },
  create: async (agent: AgentCreate): Promise<Agent> => {
    const response = await api.post('/api/agents/', agent);
    return response.data;
  },
  update: async (id: number, agent: Partial<AgentCreate>): Promise<Agent> => {
    const response = await api.put(`/api/agents/${id}`, agent);
    return response.data;
  },
  delete: async (id: number) => {
    const response = await api.delete(`/api/agents/${id}`);
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