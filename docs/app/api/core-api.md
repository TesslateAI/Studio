# Core API Setup

This document covers the Axios instance configuration, authentication flow, and foundational API modules.

## Axios Instance Configuration

**File**: `app/src/lib/api.ts`

### Base Configuration

```typescript
const API_URL = import.meta.env.VITE_API_URL || '';

const api = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  withCredentials: true, // Send cookies with requests (for OAuth cookie-based auth)
});
```

Key settings:
- `baseURL`: Configurable via `VITE_API_URL` environment variable
- `withCredentials: true`: Enables cookie transmission for OAuth sessions
- Default `Content-Type`: JSON for all requests

## Request Interceptor

The request interceptor handles authentication headers:

```typescript
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
```

### Authentication Priority

1. **JWT Token** (localStorage): Added as `Authorization: Bearer <token>` header
2. **CSRF Token** (memory): Added as `X-CSRF-Token` header for cookie-auth users

## Response Interceptor

The response interceptor handles error scenarios:

```typescript
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    // Handle 401 - redirect to login
    if (error.response?.status === 401) {
      const isTasksApi = error.config?.url?.includes('/api/tasks/');

      if (!isTasksApi) {
        localStorage.removeItem('token');
        if (window.location.pathname !== '/login') {
          window.location.href = '/login';
        }
      }
      // For tasks API, just reject without logout (transient errors)
    }

    // Handle 403 CSRF - refetch token and retry
    if (error.response?.status === 403 &&
        error.response?.data?.detail?.includes('CSRF')) {
      await fetchCsrfToken();
      if (error.config && !error.config._retry) {
        error.config._retry = true;
        return api.request(error.config);
      }
    }

    return Promise.reject(error);
  }
);
```

### Error Handling Behavior

| Status | Condition | Action |
|--------|-----------|--------|
| 401 | Non-task endpoint | Clear token, redirect to `/login` |
| 401 | Task endpoint | Reject error (no logout) |
| 403 | CSRF error | Refetch token, retry once |
| Other | - | Pass through to caller |

## CSRF Token Management

CSRF tokens protect against cross-site request forgery for cookie-based authentication:

```typescript
let csrfToken: string | null = null;

export const fetchCsrfToken = async () => {
  try {
    const response = await api.get('/api/auth/csrf');
    csrfToken = response.data.csrf_token;
  } catch (error) {
    console.error('Failed to fetch CSRF token:', error);
  }
};

// Called on app load
fetchCsrfToken();
```

## Authentication API (authApi)

Handles user authentication with fastapi-users:

```typescript
export const authApi = {
  // JWT Login - form-encoded credentials
  login: async (username: string, password: string) => {
    const formData = new URLSearchParams();
    formData.append('username', username);
    formData.append('password', password);
    const response = await api.post('/api/auth/jwt/login', formData, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    });
    return response.data;
  },

  // Register with optional referral tracking
  register: async (name: string, email: string, password: string) => {
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

  // Logout
  logout: async () => {
    try {
      await api.post('/api/auth/jwt/logout');
    } catch {
      // Ignore errors, we're logging out anyway
    }
    localStorage.removeItem('token');
  },

  // OAuth URL fetchers
  getGithubAuthUrl: async () => {
    const response = await api.get('/api/auth/github/authorize');
    return response.data.authorization_url;
  },

  getGoogleAuthUrl: async () => {
    const response = await api.get('/api/auth/google/authorize');
    return response.data.authorization_url;
  },
};
```

## Tasks API (tasksApi)

Manages background task tracking:

```typescript
export const tasksApi = {
  // Get single task status
  getStatus: async (taskId: string) => {
    const response = await api.get(`/api/tasks/${taskId}/status`);
    return response.data;
  },

  // Get all active tasks for user
  getActiveTasks: async () => {
    const response = await api.get('/api/tasks/user/active');
    return response.data;
  },

  // Poll until task completes
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
        // Timeout check
        if (Date.now() - startTime > timeout) {
          reject(new Error(`Task polling timeout after ${timeout}ms`));
          return;
        }

        // Max retries check
        if (retryCount >= maxRetries) {
          reject(new Error(`Task polling exceeded max retries (${maxRetries})`));
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
      };
      poll();
    });
  },
};
```

## Users API (usersApi)

User profile and preferences:

```typescript
export const usersApi = {
  getPreferences: async () => {
    const response = await api.get('/api/users/preferences');
    return response.data;
  },

  updatePreferences: async (data: { diagram_model?: string }) => {
    const response = await api.patch('/api/users/preferences', data);
    return response.data;
  },

  getProfile: async (): Promise<UserProfile> => {
    const response = await api.get('/api/users/profile');
    return response.data;
  },

  updateProfile: async (data: UserProfileUpdate): Promise<UserProfile> => {
    const response = await api.patch('/api/users/profile', data);
    return response.data;
  },
};
```

## Config API (configApi)

App configuration with caching:

```typescript
let appConfigCache: { app_domain: string; deployment_mode: string } | null = null;

export const configApi = {
  getConfig: async () => {
    if (appConfigCache) {
      return appConfigCache;
    }
    const response = await api.get('/api/config');
    appConfigCache = response.data;
    return appConfigCache;
  },

  getAppDomain: async (): Promise<string> => {
    const config = await configApi.getConfig();
    return config?.app_domain || 'localhost';
  },
};
```

## Billing API (billingApi)

Subscription and credits management:

```typescript
export const billingApi = {
  // Subscription
  getSubscription: async () => api.get('/api/billing/subscription').then(r => r.data),
  subscribe: async () => api.post('/api/billing/subscribe').then(r => r.data),
  cancelSubscription: async (atPeriodEnd = true) =>
    api.post('/api/billing/cancel', null, { params: { at_period_end: atPeriodEnd }}).then(r => r.data),
  renewSubscription: async () => api.post('/api/billing/renew').then(r => r.data),
  getCustomerPortal: async () => api.get('/api/billing/portal').then(r => r.data),

  // Credits
  getCreditsBalance: async () => api.get('/api/billing/credits').then(r => r.data),
  purchaseCredits: async (packageType: 'small' | 'medium' | 'large') =>
    api.post('/api/billing/credits/purchase', { package: packageType }).then(r => r.data),
  getCreditsHistory: async (limit = 50, offset = 0) =>
    api.get('/api/billing/credits/history', { params: { limit, offset }}).then(r => r.data),

  // Usage
  getUsage: async (startDate?: string, endDate?: string) =>
    api.get('/api/billing/usage', { params: { start_date: startDate, end_date: endDate }}).then(r => r.data),
  getUsageLogs: async (limit = 100, offset = 0, startDate?: string, endDate?: string) =>
    api.get('/api/billing/usage/logs', { params: { limit, offset, start_date: startDate, end_date: endDate }}).then(r => r.data),

  // Creator earnings
  getEarnings: async (startDate?: string, endDate?: string) =>
    api.get('/api/billing/earnings', { params: { start_date: startDate, end_date: endDate }}).then(r => r.data),
  connectStripe: async () => api.post('/api/billing/connect').then(r => r.data),

  // Deployment limits
  getDeploymentLimits: async () => api.get('/api/projects/deployment/limits').then(r => r.data),
};
```

## Secrets API (secretsApi)

API key management:

```typescript
export const secretsApi = {
  listApiKeys: async (provider?: string) => {
    const params = provider ? `?provider=${provider}` : '';
    const response = await api.get(`/api/secrets/api-keys${params}`);
    return response.data;
  },

  addApiKey: async (data: {
    provider: string;
    api_key: string;
    key_name?: string;
    auth_type?: string;
    provider_metadata?: Record<string, unknown>;
  }) => {
    const response = await api.post('/api/secrets/api-keys', data);
    return response.data;
  },

  updateApiKey: async (keyId: number, data: {
    api_key?: string;
    key_name?: string;
    provider_metadata?: Record<string, unknown>;
  }) => {
    const response = await api.put(`/api/secrets/api-keys/${keyId}`, data);
    return response.data;
  },

  deleteApiKey: async (keyId: number) => {
    const response = await api.delete(`/api/secrets/api-keys/${keyId}`);
    return response.data;
  },

  getApiKey: async (keyId: number, reveal = false) => {
    const response = await api.get(`/api/secrets/api-keys/${keyId}?reveal=${reveal}`);
    return response.data;
  },

  getProviders: async () => {
    const response = await api.get('/api/secrets/providers');
    return response.data;
  },
};
```

## WebSocket Helpers

```typescript
export const createWebSocket = (token: string) => {
  let wsUrl: string;
  if (API_URL) {
    wsUrl = API_URL.replace('http', 'ws');
  } else {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    wsUrl = `${protocol}//${window.location.host}`;
  }
  return new WebSocket(`${wsUrl}/api/chat/ws/${token}`);
};

export const createTerminalWebSocket = (projectId: string): WebSocket => {
  let wsUrl: string;
  if (API_URL) {
    wsUrl = API_URL.replace('http', 'ws');
  } else {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    wsUrl = `${protocol}//${window.location.host}`;
  }
  return new WebSocket(`${wsUrl}/api/projects/${projectId}/terminal`);
};
```
