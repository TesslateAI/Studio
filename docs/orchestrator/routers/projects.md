# Projects Router

**File**: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/routers/projects.py` (5142 lines)

The projects router is the largest and most complex router in OpenSail. It handles everything related to project management: CRUD operations, file management, container lifecycle, asset uploads, terminal access, and deployment.

## Overview

Projects are the core entity in OpenSail. Each project represents a web application that users build with AI assistance. Projects can be:
- Created from scratch (default Next.js template)
- Imported from Git repositories (GitHub, GitLab, Bitbucket)
- Created from marketplace bases (pre-built templates)
- Forked from existing projects

Projects support multiple containers (frontend, backend, database) which are orchestrated differently depending on deployment mode:
- **Docker mode**: Uses docker-compose with Traefik routing
- **Kubernetes mode**: Uses namespaces, PVCs, and NGINX Ingress

## Base Path

All endpoints are mounted at `/api/projects`

## Project CRUD Operations

### List Projects

```
GET /api/projects/
```

Returns all projects owned by the authenticated user.

**Response**: Array of Project objects with basic info (id, name, slug, created_at, etc.)

**Example**:
```json
[
  {
    "id": "uuid",
    "name": "My App",
    "slug": "my-app-x8k2n",
    "description": "E-commerce platform",
    "created_at": "2025-01-09T10:00:00Z",
    "containers": []
  }
]
```

### Create Project

```
POST /api/projects/
```

Creates a new project with a unique slug. Project setup happens in the background using TaskManager for progress tracking.

**Request Body** (`ProjectCreate` schema):
```json
{
  "name": "My New App",
  "description": "Optional description",
  "source_type": "base|github|gitlab|bitbucket",
  "base_id": "uuid-or-builtin",          // For source_type="base" (default)
  "github_repo_url": "https://...",      // For source_type="github" (legacy)
  "github_branch": "main",               // For source_type="github" (legacy)
  "git_repo_url": "https://...",         // For any Git provider (unified)
  "git_branch": "main"                   // For any Git provider (unified)
}
```

**Response**:
```json
{
  "project": {
    "id": "uuid",
    "slug": "my-new-app-k3x8n2",
    "name": "My New App",
    ...
  },
  "task_id": "setup-project-uuid"
}
```

**Background Process**:

The `_perform_project_setup()` function runs in the background:

1. **Create Directory** (5% progress)
   - Docker: Create filesystem directory at `/projects/user-id/project-id`
   - K8s: Directory creation deferred to container startup

2. **Handle Source Type**:
   - **Base** (10-90%): Clone marketplace base from cache or Git (default)
   - **Git Provider** (10-90%): Clone repository
     - K8s: Create namespace + PVC + file-manager pod, clone directly to PVC
     - Docker: Clone to filesystem

3. **Complete** (100%): Update project status in database

**Task Progress Tracking**:

Client polls `GET /api/tasks/{task_id}` to monitor progress:
```json
{
  "status": "in_progress",
  "progress": 50,
  "total": 100,
  "message": "Cloning repository...",
  "result": null
}
```

### Get Project Details

```
GET /api/projects/{project_slug}
```

Returns full project details including containers, files count, and settings.

**Response**: Complete Project object with relationships loaded

### Fork Project

```
POST /api/projects/{project_id}/fork
```

Creates a deep copy of an existing project. The forked project gets a new unique slug. Copies include:
- All project files
- All containers (status reset to "stopped", new container names generated)
- All container connections (IDs remapped to new containers)
- All browser previews (container IDs remapped)

Enforces the same tier-based project limit as `create_project()` via the shared `enforce_project_limit()` helper.

**Request Body**:
```json
{
  "name": "My Forked App"
}
```

**Response**: New Project object

This is useful for users who want to start from an existing project structure without modifying the original.

### Delete Project

```
DELETE /api/projects/{project_slug}
```

Permanently deletes a project and all associated resources:
- Database records (Project, ProjectFile, Container, Asset, Chat, etc.)
- Filesystem files (Docker mode)
- Kubernetes resources (namespace, PVC, pods, services, ingress)

**Response**:
```json
{
  "message": "Project deleted successfully"
}
```

## File Operations

### List Files

```
GET /api/projects/{project_slug}/files
```

Returns all files in the project with their content.

**Response**: Array of ProjectFile objects
```json
[
  {
    "id": "uuid",
    "project_id": "uuid",
    "file_path": "src/app/page.tsx",
    "content": "export default function Home() {...}",
    "created_at": "2025-01-09T10:00:00Z",
    "updated_at": "2025-01-09T11:00:00Z"
  }
]
```

**File Sync Behavior**:

- **Docker mode**: Files are read from filesystem, synced to database
- **K8s mode**: Files are read from database (source of truth), synced to PVC on container start

**Empty Directory Entries**:

Both Docker and K8s modes include placeholder entries for empty directories in the response. These entries have `file_path` ending with `/` and empty `content`:

```json
{
  "id": "uuid",
  "project_id": "uuid",
  "file_path": "src/components/",
  "content": "",
  "created_at": "2025-01-09T10:00:00Z",
  "updated_at": "2025-01-09T10:00:00Z"
}
```

The frontend CodeEditor uses this convention to render empty directories in the file tree. Excluded directories (node_modules, .git, .next, __pycache__, dist, build, .venv, venv, .cache, .turbo, coverage, .nyc_output) are never included — the exclusion list is kept in sync between Docker (`EXCLUDED_DIRS` in `docker.py`) and K8s (`read_files_recursive` in `projects.py`).

### Save File

```
POST /api/projects/{project_slug}/files/save
```

Saves a file's content to both database and filesystem (Docker) or just database (K8s).

**Request Body**:
```json
{
  "file_path": "src/app/page.tsx",
  "content": "export default function Home() {\n  return <div>Hello</div>\n}"
}
```

**Response**:
```json
{
  "message": "File saved successfully",
  "file": {
    "id": "uuid",
    "file_path": "src/app/page.tsx",
    ...
  }
}
```

**Behavior**:
- Creates new file if it doesn't exist
- Updates existing file if it does
- Docker mode: Writes to filesystem AND database
- K8s mode: Writes to database, file-manager pod syncs to PVC

**WebSocket Notification**:

After saving, broadcasts file update to all connected WebSocket clients (chat sessions) so the agent knows files changed.

## Container Management

Containers represent individual services in a project (frontend, backend, database, etc.). Each container can be started/stopped independently.

### List Containers

```
GET /api/projects/{project_slug}/containers
```

Returns all containers in the project.

**Response**: Array of Container objects with eager-loaded base info
```json
[
  {
    "id": "uuid",
    "name": "frontend",
    "image": "node:20-alpine",
    "port": 3000,
    "environment_variables": {"NODE_ENV": "development"},
    "status": "running|stopped|starting|error",
    "dev_url": "http://frontend.my-app-k3x8n2.localhost",
    "base_name": "Next.js 16",
    "icon": "nextjs-icon",
    "tech_stack": ["node:20-alpine"],
    "service_type": "container",
    "deployment_provider": null
  }
]
```

### Create Container

```
POST /api/projects/{project_slug}/containers
```

Adds a new container to the project. The container is not started automatically.

**Request Body** (`ContainerCreate` schema):
```json
{
  "name": "backend",
  "image": "node:20-alpine",
  "port": 8000,
  "command": "npm run dev",
  "environment_variables": {
    "DATABASE_URL": "postgresql://..."
  }
}
```

**Response**: New Container object

### Update Container

```
PATCH /api/projects/{project_slug}/containers/{container_id}
```

Updates container configuration. Container must be stopped to update.

**Request Body** (`ContainerUpdate` schema):
```json
{
  "port": 8080,
  "command": "npm start",
  "environment_variables": {...}
}
```

### Rename Container

```
POST /api/projects/{project_slug}/containers/{container_id}/rename
```

Changes the container's name. This affects the dev URL (subdomain).

**Request Body**:
```json
{
  "new_name": "api"
}
```

### Delete Container

```
DELETE /api/projects/{project_slug}/containers/{container_id}
```

Removes a container from the project. Container must be stopped first.

## Container Lifecycle

### Start Container

```
POST /api/projects/{project_slug}/containers/{container_id}/start
Status: 202 Accepted
```

Starts a single container. Returns immediately with 202 status; container startup happens asynchronously.

**Response**:
```json
{
  "message": "Container start initiated",
  "container_id": "uuid"
}
```

**Behind the Scenes**:

The orchestrator (Docker or K8s) handles the actual startup:

**Docker Mode**:
1. Generate `docker-compose.yml` from Container models
2. Run `docker-compose up -d {container-name}`
3. Connect container to Traefik network
4. Container accessible at `{container-name}.{project-slug}.localhost`

**Kubernetes Mode**:
1. Ensure project environment exists (namespace + PVC)
2. Create init container for file hydration (download from database to PVC)
3. Create main container (dev server) with PVC mounted
4. Create Service for container
5. Update Ingress with new route
6. Container accessible at `{container-name}.{project-slug}.{domain}`

**File Hydration (K8s)**:

The init container runs a Python script that:
- Fetches all project files from database via API
- Writes them to the PVC at `/app`
- Exits successfully, allowing main container to start

**Dev Server (K8s)**:

The main container runs `tesslate-devserver` image which:
- Detects project framework (Next.js, React, Vue, etc.)
- Runs appropriate dev command (`npm run dev`, etc.)
- Serves on configured port
- Watches for file changes

### Stop Container

```
POST /api/projects/{project_slug}/containers/{container_id}/stop
```

Stops a running container gracefully.

**Response**:
```json
{
  "message": "Container stopped successfully"
}
```

**Behind the Scenes**:
- Docker: `docker-compose stop {container-name}`
- K8s: Scales Deployment to 0 replicas (pod terminated, files preserved in PVC)

### Restart Container

```
POST /api/projects/{project_slug}/containers/{container_id}/restart
Status: 202 Accepted
```

Stops then starts the container. Useful for applying configuration changes.

### Start All Containers

```
POST /api/projects/{project_slug}/containers/start-all
```

Starts all containers in the project in parallel.

### Stop All Containers

```
POST /api/projects/{project_slug}/containers/stop-all
```

Stops all running containers in the project.

### Container Status

```
GET /api/projects/{project_slug}/containers/status
```

Gets real-time status of all containers from the orchestrator.

**Response**:
```json
{
  "containers": [
    {
      "id": "uuid",
      "name": "frontend",
      "status": "running",
      "uptime": "2h 35m",
      "cpu_usage": "5%",
      "memory_usage": "120MB"
    }
  ]
}
```

**Note**: Status is queried from Docker/K8s in real-time, not from database.

## Container Connections

Container connections define dependencies between containers. For example, a frontend container might depend on a backend container.

### List Connections

```
GET /api/projects/{project_slug}/containers/connections
```

Returns all container-to-container connections.

**Response**:
```json
[
  {
    "id": "uuid",
    "source_container_id": "uuid-frontend",
    "target_container_id": "uuid-backend",
    "connection_type": "api",
    "created_at": "2025-01-09T10:00:00Z"
  }
]
```

### Create Connection

```
POST /api/projects/{project_slug}/containers/connections
```

**Note**: The frontend `ProjectGraphCanvas.tsx` was updated to use this correct endpoint path (`/containers/connections`) instead of the previously incorrect `/connections`.

Creates a connection between two containers.

**Request Body**:
```json
{
  "source_container_id": "uuid",
  "target_container_id": "uuid",
  "connection_type": "api|database|cache|queue"
}
```

### Delete Connection

```
DELETE /api/projects/{project_slug}/containers/connections/{connection_id}
```

Removes a connection between containers.

## Browser Previews

Browser previews allow users to open multiple browser instances connected to different containers, useful for testing responsive design or multi-page apps.

### List Browser Previews

```
GET /api/projects/{project_slug}/browser-previews
```

Returns all browser preview configurations for the project.

### Create Browser Preview

```
POST /api/projects/{project_slug}/browser-previews
```

Creates a new browser preview instance.

**Request Body**:
```json
{
  "viewport_width": 1920,
  "viewport_height": 1080,
  "device_type": "desktop|mobile|tablet"
}
```

### Update Browser Preview

```
PATCH /api/projects/{project_slug}/browser-previews/{preview_id}
```

Updates viewport settings for a browser preview.

### Connect to Container

```
POST /api/projects/{project_slug}/browser-previews/{preview_id}/connect/{container_id}
```

Connects a browser preview to a specific container URL.

### Disconnect Browser Preview

```
POST /api/projects/{project_slug}/browser-previews/{preview_id}/disconnect
```

Disconnects the browser preview from its current container.

### Delete Browser Preview

```
DELETE /api/projects/{project_slug}/browser-previews/{preview_id}
```

Removes a browser preview instance.

## Asset Management

Assets are uploaded files (images, videos, fonts, etc.) stored separately from project source code.

### List Assets

```
GET /api/projects/{project_slug}/assets
```

Returns all uploaded assets with pagination.

**Query Parameters**:
- `directory` (optional): Filter by directory path
- `skip` (default: 0): Pagination offset
- `limit` (default: 50): Max results

**Response**:
```json
{
  "assets": [
    {
      "id": "uuid",
      "file_name": "logo.png",
      "file_path": "public/images/logo.png",
      "file_size": 45620,
      "mime_type": "image/png",
      "directory": "public/images",
      "uploaded_at": "2025-01-09T10:00:00Z"
    }
  ],
  "total": 25,
  "skip": 0,
  "limit": 50
}
```

### List Asset Directories

```
GET /api/projects/{project_slug}/assets/directories
```

Returns all unique directory paths containing assets.

**Response**:
```json
{
  "directories": [
    "public/images",
    "public/fonts",
    "assets/icons"
  ]
}
```

### Create Asset Directory

```
POST /api/projects/{project_slug}/assets/directories
```

Creates a new directory for organizing assets.

**Request Body**:
```json
{
  "path": "public/images/products"
}
```

### Upload Asset

```
POST /api/projects/{project_slug}/assets/upload
Content-Type: multipart/form-data
```

Uploads one or more files as project assets.

**Form Data**:
- `files`: File upload (single or multiple)
- `directory`: Target directory path (default: "public")

**Response**:
```json
{
  "message": "Uploaded 3 files successfully",
  "assets": [
    {
      "id": "uuid",
      "file_name": "photo.jpg",
      "file_path": "public/photo.jpg",
      "file_size": 102400,
      "mime_type": "image/jpeg"
    }
  ]
}
```

**Storage**:
- Files are stored in the database as binary data (`file_data` column)
- Also written to project filesystem (Docker) or PVC (K8s)
- Accessible via dev URL: `http://{container}.{project-slug}.{domain}/photo.jpg`

### Download Asset

```
GET /api/projects/{project_slug}/assets/{asset_id}/file
```

Downloads an asset file.

**Response**: Binary file with appropriate `Content-Type` header

### Rename Asset

```
PATCH /api/projects/{project_slug}/assets/{asset_id}/rename
```

Renames an asset file.

**Request Body**:
```json
{
  "new_name": "new-logo.png"
}
```

### Move Asset

```
PATCH /api/projects/{project_slug}/assets/{asset_id}/move
```

Moves an asset to a different directory.

**Request Body**:
```json
{
  "new_directory": "public/images/logos"
}
```

### Delete Asset

```
DELETE /api/projects/{project_slug}/assets/{asset_id}
```

Deletes an asset from the project.

## Setup Configuration

The setup configuration system manages `.tesslate/config.json`, a unified configuration file that defines how project containers are started. The startup command priority chain is:

1. **DB `startup_command`** on the Container model (highest priority)
2. **`.tesslate/config.json`** (unified config system)
3. **`TESSLATE.md`** (legacy)
4. **Generic fallback** (framework auto-detection)

### Read Setup Config

```
GET /api/projects/{project_slug}/setup-config
```

Reads `.tesslate/config.json` from the project filesystem (Docker) or PVC (K8s). Falls back to parsing `TESSLATE.md` if `config.json` does not exist.

**Response** (`TesslateConfigResponse`):
```json
{
  "exists": true,
  "apps": {
    "frontend": {
      "directory": ".",
      "port": 3000,
      "start": "npm install && npm run dev -- --host 0.0.0.0",
      "env": {"NODE_ENV": "development"},
      "x": 200,
      "y": 200
    }
  },
  "infrastructure": {
    "postgres": {
      "image": "postgres:16",
      "port": 5432,
      "x": 400,
      "y": 400
    }
  },
  "primaryApp": "frontend"
}
```

When no config is found, returns `{"exists": false, "apps": {}, "infrastructure": {}, "primaryApp": ""}`.

### Save Setup Config and Sync Containers

```
POST /api/projects/{project_slug}/setup-config
```

Writes `.tesslate/config.json` to the project filesystem/PVC and synchronizes Container records in the database. Creates new containers for apps/infrastructure defined in the config, updates existing ones, and deletes orphaned containers that are no longer present in the config.

**Request Body** (`TesslateConfigCreate`):
```json
{
  "apps": {
    "frontend": {
      "directory": ".",
      "port": 3000,
      "start": "npm install && npm run dev -- --host 0.0.0.0",
      "env": {}
    }
  },
  "infrastructure": {},
  "primaryApp": "frontend"
}
```

**Response** (`SetupConfigSyncResponse`):
```json
{
  "container_ids": ["uuid-1", "uuid-2"],
  "primary_container_id": "uuid-1"
}
```

**Validation**: All `start` commands are validated against a blocklist of dangerous patterns before saving.

**K8s Behavior**: Ensures the project environment (namespace + PVC + file-manager pod) exists before writing the config file. Waits up to 30 seconds for the file-manager pod to become ready.

### Analyze Project

```
POST /api/projects/{project_slug}/analyze
```

Uses an LLM to analyze the project's file tree and configuration files, then generates a `.tesslate/config.json` recommendation. Does not persist the config -- the client should call `POST /setup-config` with the result to save it.

**Response**: Same shape as `TesslateConfigResponse` with `exists: false`.

**Behavior**:
- Reads up to 500 files from the project file tree
- Reads up to 15 config files (package.json, requirements.txt, Dockerfile, etc.) capped at 20KB each
- Docker mode: walks the filesystem directly
- K8s mode: reads from PVC first, falls back to ProjectFile database records
- Raises 400 if no files are found in the project

## Project Settings

### Get Settings

```
GET /api/projects/{project_slug}/settings
```

Returns project configuration settings.

**Response**:
```json
{
  "name": "My App",
  "description": "E-commerce platform",
  "visibility": "private",
  "auto_deploy": false
}
```

### Update Settings

```
PATCH /api/projects/{project_slug}/settings
```

Updates project settings.

**Request Body**:
```json
{
  "name": "Updated Name",
  "description": "New description",
  "visibility": "public|private"
}
```

## WebSocket Endpoints

### Stream Container Logs

```
WebSocket: /api/projects/{project_slug}/logs/stream
```

Opens a WebSocket connection for streaming container logs in real-time.

**Query Parameters**:
- `container_id`: UUID of container to stream logs from

**Message Format**:
```json
{
  "type": "log",
  "container_id": "uuid",
  "timestamp": "2025-01-09T10:00:00Z",
  "level": "info|error|warn",
  "message": "Server started on port 3000"
}
```

**Client Usage**:
```javascript
const ws = new WebSocket(`ws://api/projects/${slug}/logs/stream?container_id=${id}`);
ws.onmessage = (event) => {
  const log = JSON.parse(event.data);
  console.log(log.message);
};
```

### Interactive Terminal

```
WebSocket: /api/projects/{project_slug}/terminal
```

Opens a WebSocket connection for interactive terminal access to a container.

**Query Parameters**:
- `container_id`: UUID of container to connect to

**Message Types**:

**Client → Server**:
```json
{
  "type": "input",
  "data": "ls -la\n"
}
```

**Server → Client**:
```json
{
  "type": "output",
  "data": "total 48\ndrwxr-xr-x  12 user  staff   384 Jan  9 10:00 .\n..."
}
```

**Behind the Scenes**:
- Docker mode: Runs `docker exec -it {container-name} /bin/sh`
- K8s mode: Uses Kubernetes API to exec into pod with PTY

**Client Usage**:
```javascript
const ws = new WebSocket(`ws://api/projects/${slug}/terminal?container_id=${id}`);

// Send command
ws.send(JSON.stringify({type: "input", data: "npm install\n"}));

// Receive output
ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  if (msg.type === "output") {
    terminal.write(msg.data);
  }
};
```

## Deployment Operations

### Deploy Project

```
POST /api/projects/{project_slug}/deploy
```

Deploys the project to its container environment (Docker Compose or Kubernetes).

**Response**:
```json
{
  "message": "Project deployed successfully",
  "containers": [
    {
      "name": "frontend",
      "status": "running",
      "url": "http://frontend.my-app-k3x8n2.localhost"
    }
  ]
}
```

This endpoint calls `start_all_containers()` internally.

### Undeploy Project

```
DELETE /api/projects/{project_slug}/deploy
```

Stops all containers and removes deployment resources.

**Response**:
```json
{
  "message": "Project undeployed successfully"
}
```

### Get Deployment Limits

```
GET /api/projects/deployment/limits
```

Returns the user's deployment limits based on their subscription tier.

**Response**:
```json
{
  "max_deploys": 5,
  "current_deploys": 2,
  "available": 3,
  "tier": "pro"
}
```

### Purchase Deployment Slot

```
POST /api/projects/deployment/purchase-slot
```

Allows users on free tier to purchase additional deployment slots (not implemented yet, placeholder).

## Admin Operations

These endpoints provide system-level control over project environments, primarily for managing Kubernetes resources and troubleshooting.

### Hibernate Project

```
POST /api/projects/{project_slug}/admin/hibernate
```

**(Superuser only)**

Puts a project into hibernation mode (Kubernetes only):
- Creates EBS VolumeSnapshots of all project PVCs (project-storage + service PVCs)
- Waits for snapshot readiness before proceeding
- Deletes the project namespace (cascades to all resources)
- Marks project as hibernated in the database
- On failure, rolls back environment_status to "active" and clears hibernated_at

**Response**:
```json
{
  "message": "Project hibernated successfully"
}
```

Hibernation saves resources for inactive projects.

### Get Admin Status

```
GET /api/projects/{project_slug}/admin/status
```

**(Superuser only)**

Returns detailed status of project infrastructure:
- Namespace existence
- PVC status
- Pod status
- Service endpoints
- Ingress configuration

**Response**:
```json
{
  "namespace": "proj-uuid",
  "namespace_exists": true,
  "pvc_exists": true,
  "pvc_status": "Bound",
  "pods": [
    {
      "name": "frontend-abc123",
      "status": "Running",
      "containers": ["dev-server"]
    }
  ],
  "services": [...],
  "ingress": {...}
}
```

### Update Environment Status

```
PATCH /api/projects/{project_slug}/admin/environment-status
```

**(Superuser only)**

Manually updates the project's environment status in the database.

**Request Body**:
```json
{
  "environment_status": "ready|creating|error|hibernated"
}
```

### Wake Project

```
POST /api/projects/{project_slug}/admin/wake
```

**(Superuser only)**

Wakes a hibernated project:
- Scales deployments back to 1 replica
- Restarts containers
- Marks project as ready

**Response**:
```json
{
  "message": "Project woken successfully"
}
```

### Reset Project Environment

```
POST /api/projects/{project_slug}/admin/reset
```

**(Superuser only)**

Completely resets the project's Kubernetes environment:
1. Deletes namespace (cascades to all resources)
2. Recreates namespace
3. Recreates PVC
4. Recreates file-manager pod
5. Re-syncs files from database to PVC

This is a "nuclear option" for fixing corrupted environments.

### Ensure Environment

```
POST /api/projects/{project_slug}/ensure-environment
```

Creates the project environment if it doesn't exist (K8s mode only):
- Creates namespace
- Creates PVC
- Creates file-manager pod
- Syncs files from database

Returns 200 if environment already exists, 201 if created.

**Response**:
```json
{
  "message": "Environment ready",
  "namespace": "proj-uuid",
  "created": false
}
```

## Dev Server URL

```
GET /api/projects/{project_slug}/dev-server-url
```

Returns the base dev server URL for the project. This is used by the frontend to construct container URLs.

**Response**:
```json
{
  "dev_server_url": "http://my-app-k3x8n2.localhost",         // Docker
  "dev_server_url": "http://my-app-k3x8n2.opensail.tesslate.com" // K8s
}
```

## Container Info

```
GET /api/projects/{project_slug}/container-info
```

Returns container configuration and status for display in the frontend.

**Response**:
```json
{
  "containers": [
    {
      "id": "uuid",
      "name": "frontend",
      "port": 3000,
      "status": "running",
      "url": "http://frontend.my-app-k3x8n2.localhost"
    }
  ]
}
```

## Key Functions

### get_project_by_slug()

Helper function used throughout the router to fetch projects and verify ownership:

```python
project = await get_project_by_slug(db, project_slug, current_user.id)
```

Raises HTTPException 404 if not found, 403 if not owned by user.

### _perform_project_setup()

Background task function that performs project initialization:
1. Creates project directory (Docker) or prepares database (K8s)
2. Clones from Git or copies template
3. Syncs files to database
4. Updates task progress throughout

Uses TaskManager for progress tracking visible to the frontend.

### enforce_project_limit()

Shared helper that checks if the user has reached their subscription tier's project limit. Used by both `create_project()` and `fork_project()`. Raises HTTP 403 if the limit is reached.

```python
await enforce_project_limit(current_user, db)
```

## Example Workflows

### Creating a Project from GitHub

1. **User submits create request**:
   ```
   POST /api/projects/
   {
     "name": "Imported App",
     "source_type": "github",
     "git_repo_url": "https://github.com/user/repo",
     "git_branch": "main"
   }
   ```

2. **Server creates project record**:
   - Generates unique slug: `imported-app-k3x8n2`
   - Creates database record with status "creating"
   - Returns project + task_id

3. **Background task runs**:
   - Fetches GitHub credentials
   - Clones repository
   - K8s: Creates namespace, PVC, file-manager pod, clones to PVC
   - Docker: Clones to filesystem
   - Updates task progress: 10%, 20%, 40%, 90%, 100%

4. **Client polls task status**:
   ```
   GET /api/tasks/setup-project-uuid
   ```

5. **Setup completes**:
   - Task status becomes "completed"
   - Project ready to start containers

### Starting a Container

1. **User clicks "Start" on frontend container**:
   ```
   POST /api/projects/my-app-k3x8n2/containers/{uuid}/start
   ```

2. **Server validates**:
   - Checks project ownership
   - Checks deployment limits
   - Returns 202 Accepted immediately

3. **Orchestrator starts container** (K8s example):
   - Ensures namespace exists
   - Ensures PVC exists
   - Creates Deployment with:
     - Init container: Hydrates files from database to PVC
     - Main container: Runs dev server on PVC
   - Creates Service
   - Updates Ingress with route

4. **Container becomes ready**:
   - Init container downloads ~100 files
   - Main container detects Next.js project
   - Runs `npm run dev`
   - Server listening on port 3000

5. **User accesses container**:
   - Frontend iframe loads `http://frontend.my-app-k3x8n2.opensail.tesslate.com`
   - NGINX Ingress routes to container service
   - User sees their app running

### Editing Files

1. **User edits file in Monaco Editor**:
   - Frontend calls:
     ```
     POST /api/projects/my-app-k3x8n2/files/save
     {
       "file_path": "src/app/page.tsx",
       "content": "..."
     }
     ```

2. **Server saves file**:
   - Writes to database (always)
   - Docker: Also writes to filesystem
   - K8s: Database is source of truth

3. **File-manager pod syncs** (K8s only):
   - Polls `/api/projects/{slug}/files` every 5 seconds
   - Compares timestamps
   - Downloads changed files
   - Writes to PVC

4. **Dev server hot-reloads**:
   - Detects file change
   - Rebuilds
   - Browser auto-refreshes

## Deployment Mode Differences

### Docker Mode

**Pros**:
- Simple local development
- Fast file access (bind mounts)
- Traefik auto-routing

**Cons**:
- Not scalable to production
- Containers share host resources
- Limited isolation

**File Storage**:
- Primary: Filesystem at `/projects/{user-id}/{project-id}`
- Secondary: Database (for backup/sync)

**Container URLs**:
- `{container-name}.{project-slug}.localhost`
- Traefik routes based on hostname

### Kubernetes Mode

**Pros**:
- Production-ready
- Strong isolation (namespaces, network policies)
- Horizontal scaling
- Persistent storage (PVCs)

**Cons**:
- More complex setup
- Slower file sync (hydration/dehydration)
- Requires cluster management

**File Storage**:
- Primary: Database (source of truth)
- Secondary: PVC (ephemeral, synced from database)
- S3 for persistence (optional S3 Sandwich pattern)

**Container URLs**:
- `{container-name}.{project-slug}.{domain}`
- NGINX Ingress routes based on hostname
- Requires wildcard DNS: `*.{domain}` → Ingress controller IP

**File Sync**:
- **Hydration**: Init container downloads files from API on startup
- **Runtime**: File-manager sidecar polls for changes every 5s
- **Dehydration**: PreStop hook uploads files to S3 before shutdown (if S3 enabled)

## Security Considerations

1. **Project Ownership**: All endpoints verify ownership via `get_project_by_slug()`
2. **File Path Validation**: File paths are sanitized to prevent directory traversal
3. **Asset Upload Limits**: Max 10MB per file, 50MB total per upload
4. **Container Isolation**:
   - Docker: Containers on separate network
   - K8s: Separate namespaces with NetworkPolicy
5. **Terminal Access**: WebSocket requires authentication, limited to project owner
6. **Admin Endpoints**: Superuser-only for hibernation, reset, etc.

## Performance Optimization

1. **File Sync**: Only changed files are synced in K8s mode
2. **Eager Loading**: Use `selectinload(Project.containers)` to avoid N+1 queries
3. **Background Tasks**: Long operations (setup, deployment) run async
4. **Pagination**: Asset listing supports skip/limit
5. **Caching**: Project settings cached in memory

## Related Files

- `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/orchestration/docker_compose_orchestrator.py` - Docker container management
- `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/orchestration/kubernetes_orchestrator.py` - K8s container management
- `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/task_manager.py` - Background task tracking
- `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/git_providers/` - Git provider integrations
- `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/utils/resource_naming.py` - Project path helpers
