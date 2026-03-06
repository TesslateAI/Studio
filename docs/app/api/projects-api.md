# Projects API

The Projects API manages project lifecycle, file operations, container management, and asset handling.

**File**: `app/src/lib/api.ts`

## Projects API (projectsApi)

### Project CRUD Operations

```typescript
export const projectsApi = {
  // List all user's projects
  getAll: async () => {
    const response = await api.get('/api/projects/');
    return response.data;
  },

  // Create a new project
  create: async (
    name: string,
    description?: string,
    sourceType?: 'base' | 'github' | 'gitlab' | 'bitbucket',
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
      source_type: sourceType || 'base'
    };

    if (sourceType === 'github') {
      // Legacy GitHub support
      body.github_repo_url = repoUrl;
      body.github_branch = branch || 'main';
    } else if (sourceType === 'gitlab' || sourceType === 'bitbucket') {
      // Unified git provider support
      body.git_repo_url = repoUrl;
      body.git_branch = branch || 'main';
    } else if (sourceType === 'base') {
      body.base_id = baseId;
    }

    const response = await api.post('/api/projects/', body);
    // Response: { project, task_id, status_endpoint }
    return response.data;
  },

  // Get single project by slug
  get: async (slug: string) => {
    const response = await api.get(`/api/projects/${slug}`);
    return response.data;
  },

  // Delete project (returns task_id)
  delete: async (slug: string) => {
    const response = await api.delete(`/api/projects/${slug}`);
    // Response: { task_id, status_endpoint }
    return response.data;
  },

  // Fork a project
  forkProject: async (id: string) => {
    const response = await api.post(`/api/projects/${id}/fork`);
    return response.data;
  },

  // Get/update project settings
  getSettings: async (slug: string) => {
    const response = await api.get(`/api/projects/${slug}/settings`);
    return response.data;
  },

  updateSettings: async (slug: string, settings: Record<string, unknown>) => {
    const response = await api.patch(`/api/projects/${slug}/settings`, { settings });
    return response.data;
  },
};
```

### Project Source Types

| Source Type | Description | Required Fields |
|-------------|-------------|-----------------|
| `base` | Use marketplace base (default) | `base_id` |
| `github` | Clone from GitHub | `github_repo_url`, `github_branch` |
| `gitlab` | Clone from GitLab | `git_repo_url`, `git_branch` |
| `bitbucket` | Clone from Bitbucket | `git_repo_url`, `git_branch` |

### File Operations

```typescript
export const projectsApi = {
  // Get project file tree
  getFiles: async (slug: string) => {
    const response = await api.get(`/api/projects/${slug}/files`);
    return response.data;
  },

  // Save file content
  saveFile: async (slug: string, filePath: string, content: string) => {
    const response = await api.post(`/api/projects/${slug}/files/save`, {
      file_path: filePath,
      content: content
    });
    return response.data;
  },

  // Delete file
  deleteFile: async (slug: string, filePath: string) => {
    const response = await api.delete(`/api/projects/${slug}/files`, {
      data: { file_path: filePath }
    });
    return response.data;
  },
};
```

### Container Lifecycle

```typescript
export const projectsApi = {
  // Get dev server URL
  getDevServerUrl: async (slug: string) => {
    const response = await api.get(`/api/projects/${slug}/dev-server-url`);
    return response.data;
  },

  // Start dev container (returns task_id)
  startDevContainer: async (slug: string) => {
    const response = await api.post(`/api/projects/${slug}/start-dev-container`);
    // Response: { task_id, status_endpoint }
    return response.data;
  },

  // Restart dev server
  restartDevServer: async (slug: string) => {
    const response = await api.post(`/api/projects/${slug}/restart-dev-container`);
    return response.data;
  },

  // Stop dev server
  stopDevServer: async (slug: string) => {
    const response = await api.post(`/api/projects/${slug}/stop-dev-container`);
    return response.data;
  },

  // Get container status
  getContainerStatus: async (slug: string) => {
    const response = await api.get(`/api/projects/${slug}/container-status`);
    return response.data;
  },
};
```

### Multi-Container Management

For projects with multiple containers (frontend, backend, database):

```typescript
export const projectsApi = {
  // List all containers
  getContainers: async (slug: string) => {
    const response = await api.get(`/api/projects/${slug}/containers`);
    return response.data;
  },

  // Get runtime status of all containers
  getContainersRuntimeStatus: async (slug: string) => {
    const response = await api.get(`/api/projects/${slug}/containers/status`);
    return response.data;
  },

  // Start all containers
  startAllContainers: async (slug: string) => {
    const response = await api.post(`/api/projects/${slug}/containers/start-all`);
    return response.data;
  },

  // Stop all containers
  stopAllContainers: async (slug: string) => {
    const response = await api.post(`/api/projects/${slug}/containers/stop-all`);
    return response.data;
  },

  // Start specific container (with task polling)
  startContainer: async (slug: string, containerId: string) => {
    const response = await api.post(`/api/projects/${slug}/containers/${containerId}/start`);
    const { task_id, already_started } = response.data;

    if (already_started) {
      console.log('[Container Start] Reusing existing task:', task_id);
    }

    // Poll until complete
    const completedTask = await tasksApi.pollUntilComplete(task_id);

    if (completedTask.status !== 'completed') {
      throw new Error(completedTask.error || 'Container start failed');
    }

    return {
      ...completedTask.result,
      message: response.data.message,
      task_id
    };
  },

  // Stop specific container
  stopContainer: async (slug: string, containerId: string) => {
    const response = await api.post(`/api/projects/${slug}/containers/${containerId}/stop`);
    return response.data;
  },
};
```

## Assets API (assetsApi)

Manages uploaded assets (images, fonts, etc.) within projects.

```typescript
export const assetsApi = {
  // List asset directories
  listDirectories: async (projectSlug: string) => {
    const response = await api.get(`/api/projects/${projectSlug}/assets/directories`);
    return response.data;
  },

  // Create new directory
  createDirectory: async (projectSlug: string, path: string) => {
    const response = await api.post(`/api/projects/${projectSlug}/assets/directories`, { path });
    return response.data;
  },

  // List assets, optionally filtered by directory
  listAssets: async (projectSlug: string, directory?: string) => {
    const params = directory ? `?directory=${encodeURIComponent(directory)}` : '';
    const response = await api.get(`/api/projects/${projectSlug}/assets${params}`);
    return response.data;
  },

  // Upload asset with progress callback
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

  // Get asset file URL (for display)
  getAssetUrl: (projectSlug: string, assetId: string) => {
    return `${API_URL}/api/projects/${projectSlug}/assets/${assetId}/file`;
  },

  // Delete asset
  deleteAsset: async (projectSlug: string, assetId: string) => {
    const response = await api.delete(`/api/projects/${projectSlug}/assets/${assetId}`);
    return response.data;
  },

  // Rename asset
  renameAsset: async (projectSlug: string, assetId: string, new_filename: string) => {
    const response = await api.patch(`/api/projects/${projectSlug}/assets/${assetId}/rename`, {
      new_filename,
    });
    return response.data;
  },

  // Move asset to different directory
  moveAsset: async (projectSlug: string, assetId: string, directory: string) => {
    const response = await api.patch(`/api/projects/${projectSlug}/assets/${assetId}/move`, {
      directory,
    });
    return response.data;
  },
};
```

## Diagram API (diagramApi)

Generates architecture diagrams for projects:

```typescript
export const diagramApi = {
  generateDiagram: async (slug: string, diagramType: 'mermaid' | 'c4_plantuml' = 'mermaid') => {
    const response = await api.post(`/api/projects/${slug}/generate-architecture-diagram`, null, {
      params: { diagram_type: diagramType }
    });
    return response.data;
  },
};
```

## Usage Examples

### Creating a Project from GitHub

```typescript
// Create project from GitHub repo
const result = await projectsApi.create(
  'my-app',
  'My description',
  'github',
  'https://github.com/user/repo',
  'main'
);

// Poll for completion
const task = await tasksApi.pollUntilComplete(result.task_id);
console.log('Project created:', task.result);
```

### Starting Containers

```typescript
// Start dev container
const { task_id } = await projectsApi.startDevContainer(slug);
await tasksApi.pollUntilComplete(task_id);

// Get dev server URL
const { url } = await projectsApi.getDevServerUrl(slug);
```

### Uploading Assets

```typescript
// Upload with progress tracking
await assetsApi.uploadAsset(
  projectSlug,
  file,
  '/public/images',
  (progress) => {
    console.log(`Upload progress: ${progress}%`);
  }
);
```

### File Operations

```typescript
// Save file
await projectsApi.saveFile(slug, 'src/App.tsx', newContent);

// Get file tree
const files = await projectsApi.getFiles(slug);
```
