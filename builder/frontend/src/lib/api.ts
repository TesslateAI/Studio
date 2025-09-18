import axios from 'axios';

const API_URL = import.meta.env.VITE_API_URL || '';

const api = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

export const authApi = {
  login: async (username: string, password: string) => {
    const formData = new FormData();
    formData.append('username', username);
    formData.append('password', password);
    const response = await api.post('/api/auth/token', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
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