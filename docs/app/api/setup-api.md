# Setup API

The Setup API manages project configuration through `.tesslate/config.json`, providing both manual configuration and AI-powered project analysis.

**File**: `app/src/lib/api.ts`

## Setup API (setupApi)

### Get Config

Retrieves the existing `.tesslate/config.json` for a project:

```typescript
export const setupApi = {
  getConfig: async (slug: string): Promise<TesslateConfigResponse> => {
    const response = await api.get(`/api/projects/${slug}/setup-config`);
    return response.data;
  },
};
```

**Response** (`TesslateConfigResponse`):
```typescript
interface TesslateConfigResponse extends TesslateConfig {
  exists: boolean;  // Whether a config file was found
}
```

### Save Config

Saves the configuration and creates/updates containers to match:

```typescript
export const setupApi = {
  saveConfig: async (slug: string, config: TesslateConfig): Promise<SetupConfigSyncResponse> => {
    const response = await api.post(`/api/projects/${slug}/setup-config`, config);
    return response.data;
  },
};
```

**Request Body** (`TesslateConfig`):
```typescript
interface TesslateConfig {
  apps: Record<string, AppConfig>;           // App services (name -> config)
  infrastructure: Record<string, InfraConfig>; // Infrastructure services
  primaryApp: string;                         // Name of the primary app
}

interface AppConfig {
  directory: string;           // Working directory (e.g., ".", "frontend/")
  port: number | null;         // Port the app listens on
  start: string;               // Start command (e.g., "npm run dev -- --host 0.0.0.0")
  env: Record<string, string>; // Environment variables
  x?: number;                  // Graph X position (optional)
  y?: number;                  // Graph Y position (optional)
}

interface InfraConfig {
  image: string;   // Docker image (e.g., "postgres:16")
  port: number;    // Service port
  x?: number;      // Graph X position (optional)
  y?: number;      // Graph Y position (optional)
}
```

**Response** (`SetupConfigSyncResponse`):
```typescript
interface SetupConfigSyncResponse {
  container_ids: string[];           // All created container IDs
  primary_container_id: string | null; // ID of the primary app's container
}
```

### Analyze Project

Uses AI to scan the project and detect apps, frameworks, ports, and start commands:

```typescript
export const setupApi = {
  analyzeProject: async (slug: string): Promise<TesslateConfigResponse> => {
    const response = await api.post(`/api/projects/${slug}/analyze`);
    return response.data;
  },
};
```

Returns a `TesslateConfigResponse` with detected configuration. The `exists` field indicates whether an existing config was found (vs. AI-generated).

## Usage Example

```typescript
import { setupApi } from '../lib/api';
import type { TesslateConfig } from '../types/tesslateConfig';

// 1. Check for existing config
const existing = await setupApi.getConfig(slug);
if (existing.exists) {
  // Pre-populate form with existing config
}

// 2. Or analyze the project with AI
const analysis = await setupApi.analyzeProject(slug);
if (analysis.apps && Object.keys(analysis.apps).length > 0) {
  // Use detected config
}

// 3. Save config and create containers
const config: TesslateConfig = {
  apps: {
    frontend: { directory: '.', port: 3000, start: 'npm run dev', env: {} },
  },
  infrastructure: {
    postgres: { image: 'postgres:16', port: 5432 },
  },
  primaryApp: 'frontend',
};

const result = await setupApi.saveConfig(slug, config);
// result.primary_container_id -> navigate to builder with this container
```

## API Endpoints

```typescript
// Get existing config
GET /api/projects/{slug}/setup-config

// Save config (creates/updates containers)
POST /api/projects/{slug}/setup-config

// AI-powered project analysis
POST /api/projects/{slug}/analyze
```

## Type Definitions

Types are defined in `app/src/types/tesslateConfig.ts` and imported by both the `setupApi` module and the `ProjectSetup` page.

## Related Documentation

- **Project Setup Page**: `docs/app/pages/project-setup.md`
- **ServiceConfigForm Component**: `docs/app/components/CLAUDE.md`
- **Projects API**: `docs/app/api/projects-api.md`
