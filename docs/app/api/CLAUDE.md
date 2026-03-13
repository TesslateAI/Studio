# API Client Context for Claude

## Key Files

| File | Purpose |
|------|---------|
| `app/src/lib/api.ts` | Main API client with all modules |
| `app/src/lib/git-api.ts` | Git operations API |
| `app/src/types/agent.ts` | Agent type definitions |
| `app/src/types/git.ts` | Git type definitions |

## Quick Reference

### API Module Pattern

All API modules follow this pattern:

```typescript
export const exampleApi = {
  getAll: async () => {
    const response = await api.get('/api/examples/');
    return response.data;
  },

  create: async (data: CreateData) => {
    const response = await api.post('/api/examples/', data);
    return response.data;
  },

  get: async (id: string) => {
    const response = await api.get(`/api/examples/${id}`);
    return response.data;
  },

  update: async (id: string, data: UpdateData) => {
    const response = await api.patch(`/api/examples/${id}`, data);
    return response.data;
  },

  delete: async (id: string) => {
    const response = await api.delete(`/api/examples/${id}`);
    return response.data;
  },
};
```

### Adding New Endpoints

1. Add the method to the appropriate API module in `api.ts`
2. Use the shared `api` axios instance
3. Return `response.data` directly
4. Add TypeScript types if needed

Example:
```typescript
// In api.ts, inside an existing API module:
export const projectsApi = {
  // ... existing methods ...

  newEndpoint: async (slug: string, data: NewData) => {
    const response = await api.post(`/api/projects/${slug}/new-endpoint`, data);
    return response.data;
  },
};
```

### Streaming Endpoints (SSE)

For Server-Sent Events, use native `fetch()` with `getAuthHeaders()`:

```typescript
const response = await fetch(`${API_URL}/api/endpoint/stream`, {
  method: 'POST',
  headers: getAuthHeaders(),
  body: JSON.stringify(request),
  credentials: 'include',
  signal, // AbortSignal for cancellation
});

const reader = response.body?.getReader();
const decoder = new TextDecoder();
let buffer = '';

while (true) {
  const { done, value } = await reader.read();
  if (done) break;

  buffer += decoder.decode(value, { stream: true });
  const lines = buffer.split('\n\n');
  buffer = lines.pop() || '';

  for (const line of lines) {
    if (line.startsWith('data: ')) {
      const event = JSON.parse(line.slice(6));
      onEvent(event);
    }
  }
}
```

### WebSocket Connections

```typescript
// For chat WebSocket
const ws = createWebSocket(token);

// For terminal WebSocket
const ws = createTerminalWebSocket(projectId);
```

## Common Patterns

### Task Polling

Many operations return a `task_id` for background processing:

```typescript
const { task_id } = await projectsApi.create(name);
const result = await tasksApi.pollUntilComplete(task_id);
```

### Error Handling

The interceptor handles auth errors. For component-level errors:

```typescript
try {
  const data = await projectsApi.get(slug);
} catch (error) {
  if (axios.isAxiosError(error)) {
    // Handle specific error codes
    if (error.response?.status === 404) {
      // Not found
    }
  }
}
```

### File Operations with Projects

```typescript
// Save file
await projectsApi.saveFile(slug, filePath, content);

// Delete file
await projectsApi.deleteFile(slug, filePath);

// Get all files
const files = await projectsApi.getFiles(slug);
```

## API Module Summary

| Module | Endpoint Prefix | Primary Operations |
|--------|-----------------|-------------------|
| `authApi` | `/api/auth/` | Login, register, OAuth |
| `projectsApi` | `/api/projects/` | CRUD, files, containers |
| `chatApi` | `/api/chat/` | Messages, streaming, approvals |
| `gitApi` | `/api/projects/{id}/git/` | Version control |
| `tasksApi` | `/api/tasks/` | Background task status |
| `marketplaceApi` | `/api/marketplace/` | Agents, bases, skills, MCP servers, reviews |
| `billingApi` | `/api/billing/` | Subscriptions, credits |
| `assetsApi` | `/api/projects/{slug}/assets/` | File uploads |
| `deploymentsApi` | `/api/deployments/` | External deploys |
| `secretsApi` | `/api/secrets/` | API keys |
| `usersApi` | `/api/users/` | Profile, preferences |
| `configApi` | `/api/config` | App configuration |
| `setupApi` | `/api/projects/{slug}/` | Setup config, project analysis |

## Type Definitions Location

- Agent types: `app/src/types/agent.ts`
- Git types: `app/src/types/git.ts`
- TesslateConfig types: `app/src/types/tesslateConfig.ts`
- Inline types: `app/src/lib/api.ts` (UserProfile, etc.)
