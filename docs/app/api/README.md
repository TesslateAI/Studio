# OpenSail API Client

The frontend API client provides a centralized, type-safe interface for all backend communication. It handles authentication, CSRF protection, error handling, and provides domain-specific API modules.

## Architecture Overview

```
app/src/lib/
├── api.ts          # Main API client (1317 lines)
│   ├── Axios instance configuration
│   ├── Authentication interceptors
│   ├── CSRF token management
│   ├── Domain-specific API modules
│   └── WebSocket helpers
└── git-api.ts      # Git operations API
    └── Version control operations
```

## Core Features

### Axios Configuration

The API client uses Axios with cookie credentials enabled for OAuth-based authentication:

```typescript
const api = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  withCredentials: true, // Send cookies with requests
});
```

### Authentication Methods

The client supports two authentication methods:

1. **JWT Bearer Tokens** - Stored in localStorage, added via Authorization header
2. **Cookie-based OAuth** - Session cookies with CSRF token protection

### Request Interceptor

Automatically adds authentication headers to all requests:

```typescript
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }

  // Add CSRF token for state-changing operations when using cookie auth
  if (['post', 'put', 'delete', 'patch'].includes(config.method?.toLowerCase() || '')) {
    if (csrfToken && !token) {
      config.headers['X-CSRF-Token'] = csrfToken;
    }
  }

  return config;
});
```

### Response Interceptor

Handles 401 errors and CSRF token refresh:

- **401 errors**: Redirects to login (except for task polling endpoints)
- **403 CSRF errors**: Automatically refetches token and retries request

## API Modules

| Module | Purpose | Documentation |
|--------|---------|---------------|
| `authApi` | Login, register, OAuth | [core-api.md](./core-api.md) |
| `projectsApi` | Project CRUD, files, containers | [projects-api.md](./projects-api.md) |
| `chatApi` | Agent chat, streaming, approvals | [chat-api.md](./chat-api.md) |
| `gitApi` | Git operations | [git-api.md](./git-api.md) |
| `tasksApi` | Background task tracking | [core-api.md](./core-api.md) |
| `marketplaceApi` | Agents, bases, skills, MCP servers, purchases | [core-api.md](./core-api.md) |
| `billingApi` | Subscriptions, credits | [core-api.md](./core-api.md) |
| `assetsApi` | Asset management | [projects-api.md](./projects-api.md) |
| `deploymentsApi` | External deployments | [core-api.md](./core-api.md) |
| `secretsApi` | API keys management | [core-api.md](./core-api.md) |
| `setupApi` | Project setup config, analysis | [setup-api.md](./setup-api.md) |

## WebSocket Connections

Two WebSocket helpers are provided:

### Chat WebSocket
```typescript
export const createWebSocket = (token: string) => {
  return new WebSocket(`${wsUrl}/api/chat/ws/${token}`);
};
```

### Terminal WebSocket
```typescript
export const createTerminalWebSocket = (projectId: string): WebSocket => {
  return new WebSocket(`${wsUrl}/api/projects/${projectId}/terminal`);
};
```

## Helper Functions

### getAuthHeaders()

Builds authentication headers for native `fetch()` calls (used for SSE streaming):

```typescript
export const getAuthHeaders = (additionalHeaders?: Record<string, string>): Record<string, string> => {
  const token = localStorage.getItem('token');
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...additionalHeaders,
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  } else if (csrfToken) {
    headers['X-CSRF-Token'] = csrfToken;
  }

  return headers;
};
```

### fetchCsrfToken()

Fetches CSRF token from backend on app load:

```typescript
export const fetchCsrfToken = async () => {
  const response = await api.get('/api/auth/csrf');
  csrfToken = response.data.csrf_token;
};
```

## Error Handling

The API client handles errors at the interceptor level:

1. **401 Unauthorized**: Clears token and redirects to `/login`
2. **403 CSRF Invalid**: Refetches token and retries request once
3. **Network Errors**: Passed through for component-level handling

## Environment Configuration

The API URL is configured via environment variable:

```typescript
const API_URL = import.meta.env.VITE_API_URL || '';
```

When empty, requests use relative URLs (same origin).

## Related Documentation

- [Core API Setup](./core-api.md) - Axios configuration details
- [Projects API](./projects-api.md) - Project and file operations
- [Chat API](./chat-api.md) - Agent streaming and approvals
- [Git API](./git-api.md) - Version control operations
