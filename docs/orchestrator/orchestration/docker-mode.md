# Docker Mode - Docker Compose Orchestration

**File**: `orchestrator/app/services/orchestration/docker.py`

Docker mode uses **Docker Compose** to manage user projects locally. Each project gets its own `docker-compose.yml` file, isolated network, and Traefik routing for clean `*.localhost` URLs.

## Overview

Docker mode is designed for **local development**. It provides fast iteration cycles, simple debugging, and direct filesystem access for file operations. The orchestrator has direct access to project files via a shared volume, eliminating the need for container exec operations.

**Key Features**:
- Dynamic `docker-compose.yml` generation from database models
- Project-specific Docker networks for isolation
- Traefik auto-discovery via labels
- Shared volume with subpath isolation (secure)
- Direct filesystem access (fast file operations)
- Two-tier cleanup (pause → delete)

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   Orchestrator Container                    │
│  - FastAPI backend                                          │
│  - Volume: /projects (shared with user containers)          │
│  - DockerOrchestrator has direct filesystem access          │
└─────────────────────────────────────────────────────────────┘
                    │
                    │ mounts
                    ▼
┌─────────────────────────────────────────────────────────────┐
│         Docker Volume: tesslate-projects-data               │
│  /projects/                                                 │
│    ├── my-app-abc123/           ← Project 1                 │
│    │   ├── frontend/             ← Container subdir         │
│    │   │   ├── package.json                                │
│    │   │   └── src/                                        │
│    │   └── backend/              ← Container subdir         │
│    │       ├── package.json                                │
│    │       └── src/                                        │
│    └── another-proj-xyz456/      ← Project 2                │
│        └── ... (project files)                              │
└─────────────────────────────────────────────────────────────┘
                    │
                    │ mounts (with subpath)
                    ▼
┌─────────────────────────────────────────────────────────────┐
│              User Project Containers                        │
│  my-app-abc123-frontend:                                    │
│    - Volume: /projects/my-app-abc123 → /app (subpath)      │
│    - Working dir: /app/frontend                             │
│    - Network: tesslate-my-app-abc123                        │
│    - Labels: Traefik routing config                         │
│                                                             │
│  my-app-abc123-backend:                                     │
│    - Volume: /projects/my-app-abc123 → /app (subpath)      │
│    - Working dir: /app/backend                              │
│    - Network: tesslate-my-app-abc123                        │
│    - Labels: Traefik routing config                         │
└─────────────────────────────────────────────────────────────┘
                    │
                    │ connects to
                    ▼
┌─────────────────────────────────────────────────────────────┐
│                    Traefik Container                        │
│  - Watches Docker API for container labels                 │
│  - Auto-configures routes                                  │
│  - Routes: *.localhost → user containers                   │
└─────────────────────────────────────────────────────────────┘
```

## Volume Architecture: Subpath Isolation

**Critical Security Feature**: Each project is isolated using Docker Compose's `volume.subpath` feature (v2.23.0+):

```yaml
# Generated docker-compose.yml
services:
  frontend:
    image: tesslate-devserver:latest
    working_dir: /app/frontend
    volumes:
      - type: volume
        source: tesslate-projects-data
        target: /app
        volume:
          subpath: my-app-abc123  # ← ISOLATION: Container only sees this project
```

**Why subpath instead of bind mounts?**
- ✅ **Security**: Projects can't see each other's files
- ✅ **Portability**: Works in Docker-in-Docker (CI/CD)
- ✅ **Performance**: Better than bind mounts on Windows/macOS
- ❌ **Limitation**: Requires Docker Compose v2.23.0+

**Fallback: Bind Mounts**
If `USE_DOCKER_VOLUMES=false`, the orchestrator falls back to bind mounts:
```yaml
volumes:
  - /host/path/users/user-id/project-id:/app
```
This is less secure (requires careful path sanitization) but works on older Docker versions.

## Traefik Integration

Each container gets Traefik labels for automatic routing:

```yaml
labels:
  traefik.enable: 'true'
  traefik.docker.network: 'tesslate-regional-traefik-network'
  traefik.http.routers.my-app-abc123-frontend.rule: 'Host(`my-app-abc123-frontend.localhost`)'
  traefik.http.services.my-app-abc123-frontend.loadbalancer.server.port: '3000'
```

**URL Pattern**: `{project-slug}-{container-name}.localhost`

**Example URLs**:
- Frontend: `http://my-app-abc123-frontend.localhost`
- Backend: `http://my-app-abc123-backend.localhost`

**Regional Traefik**: For scalability, the orchestrator uses a regional Traefik manager that distributes projects across multiple Traefik instances. Each Traefik handles a subset of projects to avoid hitting Docker's network limit (32 networks per container).

## File Operations

### Direct Filesystem Access

The orchestrator has **direct access** to project files via the shared volume:

```python
async def read_file(self, user_id, project_id, container_name, file_path, ...):
    project_path = self.projects_path / project_slug  # /projects/my-app-abc123
    full_path = project_path / file_path

    async with aiofiles.open(full_path, 'r') as f:
        return await f.read()
```

**Advantages**:
- ⚡ **Fast**: No container exec overhead
- 🔧 **Simple**: Standard Python file I/O
- 🐛 **Easy debugging**: Can inspect files directly on host

**Contrast with Kubernetes**: In K8s mode, file operations require `kubectl exec` into the file-manager pod, which is slower but necessary for remote clusters.

### File Organization

Multi-container projects use subdirectories:

```
/projects/my-app-abc123/
├── frontend/
│   ├── package.json
│   ├── src/
│   └── TESSLATE.md
└── backend/
    ├── package.json
    ├── src/
    └── TESSLATE.md
```

Single-container projects omit the subdirectory:

```
/projects/simple-app-xyz456/
├── package.json
├── src/
└── TESSLATE.md
```

## Project Lifecycle

### 1. Project Setup

When a project is created:

```python
# 1. Create project directory
await orchestrator.ensure_project_directory(project_slug)
# Creates: /projects/my-app-abc123/

# 2. Copy base template files (if using marketplace base)
await orchestrator.copy_base_to_project(
    base_slug="next-js-15",
    project_slug="my-app-abc123",
    target_subdir="frontend"  # For multi-container
)
# Copies from: /app/base-cache/next-js-15/ → /projects/my-app-abc123/frontend/
```

### 2. Starting Containers

```python
result = await orchestrator.start_project(project, containers, connections, user_id, db)
```

**Steps**:
1. **Generate docker-compose.yml**:
   - Service per container
   - Volumes with subpath isolation
   - Project-specific network
   - Traefik labels
   - Environment variables
   - Dependencies (`depends_on`)

2. **Write compose file**:
   ```bash
   docker-compose-projects/my-app-abc123.yml
   ```

3. **Run docker-compose**:
   ```bash
   docker compose -f docker-compose-projects/my-app-abc123.yml -p my-app-abc123 up -d
   ```

4. **Connect Traefik to project network**:
   ```bash
   docker network connect tesslate-my-app-abc123 tesslate-traefik
   ```

5. **Return container URLs**:
   ```json
   {
     "status": "running",
     "containers": {
       "frontend": "http://my-app-abc123-frontend.localhost",
       "backend": "http://my-app-abc123-backend.localhost"
     }
   }
   ```

### 3. Stopping Containers

```python
await orchestrator.stop_project(project_slug, project_id, user_id)
```

**Steps**:
1. Run `docker compose down`
2. Disconnect Traefik from project network
3. Clean up activity tracking

**Important**: Files persist in `/projects/{slug}/` after stopping. Only the containers are removed.

### 4. Restarting Containers

```python
result = await orchestrator.restart_project(project, containers, connections, user_id, db)
```

Internally calls `stop_project()` then `start_project()`.

## Compose File Generation

The orchestrator dynamically generates `docker-compose.yml` from database models:

### Base Container Example

```yaml
services:
  frontend:
    image: tesslate-devserver:latest
    container_name: my-app-abc123-frontend
    user: '1000:1000'  # Non-root
    working_dir: /app/frontend
    networks:
      - tesslate-my-app-abc123
      - tesslate-regional-traefik-network
    volumes:
      - type: volume
        source: tesslate-projects-data
        target: /app
        volume:
          subpath: my-app-abc123
    environment:
      PROJECT_ID: 'd4f6e8a2-...'
      CONTAINER_ID: 'b7c9d1e3-...'
      PORT: '3000'
    labels:
      traefik.enable: 'true'
      traefik.http.routers.my-app-abc123-frontend.rule: 'Host(`my-app-abc123-frontend.localhost`)'
      traefik.http.services.my-app-abc123-frontend.loadbalancer.server.port: '3000'
    command: 'npm run dev'
    restart: unless-stopped
    extra_hosts:
      # Security: Block access to internal services
      - 'tesslate-orchestrator:127.0.0.1'
      - 'tesslate-postgres:127.0.0.1'

networks:
  tesslate-my-app-abc123:
    driver: bridge
    name: tesslate-my-app-abc123
  tesslate-regional-traefik-network:
    external: true

volumes:
  tesslate-projects-data:
    external: true
    name: tesslate-projects-data
```

### Service Container Example (Postgres)

```yaml
services:
  database:
    image: postgres:16-alpine
    container_name: my-app-abc123-database
    networks:
      - tesslate-my-app-abc123
    volumes:
      - my-app-abc123-postgres-data:/var/lib/postgresql/data
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: myapp
    labels:
      traefik.enable: 'false'
    restart: unless-stopped

volumes:
  my-app-abc123-postgres-data:
    name: my-app-abc123-postgres-data
```

## Startup Commands: TESSLATE.md Integration

The orchestrator reads `TESSLATE.md` from project files to determine:
- **Port**: Which port the dev server listens on
- **Startup command**: How to start the dev server

**Example TESSLATE.md**:
```markdown
# Next.js 15 Template

## Configuration

- **Port**: 3000
- **Start Command**: `npm run dev`
```

**Parsing**:
```python
from orchestrator.app.services.base_config_parser import get_base_config_from_volume

base_config = await get_base_config_from_volume(project_slug)
port = base_config.port  # 3000
command = base_config.start_command  # "npm run dev"
```

**Fallback**: If no `TESSLATE.md` exists, uses defaults:
- Port: `3000`
- Command: `npm run dev` or `python app.py` (based on file detection)

## Networking & Isolation

### Project-Specific Networks

Each project gets its own Docker network:

```yaml
networks:
  tesslate-my-app-abc123:
    driver: bridge
    name: tesslate-my-app-abc123
```

**Isolation**: Containers in different projects cannot communicate directly. Only containers in the same project can reach each other.

**Inter-Container Communication**:
```javascript
// Frontend can reach backend on project network
fetch('http://backend:8000/api/data')
```

The `backend` hostname resolves via Docker DNS within the project network.

### Traefik Network

All project containers also connect to the Traefik network for routing:

```yaml
networks:
  - tesslate-my-app-abc123            # Project network (inter-container)
  - tesslate-regional-traefik-network  # Traefik network (public routing)
```

### Security: Blocking Internal Services

User containers get host overrides to prevent accessing internal infrastructure:

```yaml
extra_hosts:
  - 'tesslate-orchestrator:127.0.0.1'
  - 'tesslate-postgres:127.0.0.1'
  - 'tesslate-redis:127.0.0.1'
```

This ensures malicious code in user projects cannot access the orchestrator's database or backend services.

## Command Execution

The orchestrator can execute commands inside running containers:

```python
output = await orchestrator.execute_command(
    user_id=user_id,
    project_id=project_id,
    container_name="frontend",
    command=["npm", "install"],
    timeout=120,
    working_dir="."
)
```

**Implementation**:
```python
# Build Docker container name
service_name = self._sanitize_service_name(container_name)
docker_container = f"{project_slug}-{service_name}"

# Execute via docker exec
exec_cmd = ['docker', 'exec', '-w', f'/app/{working_dir}', docker_container] + command
process = await asyncio.create_subprocess_exec(*exec_cmd, ...)
stdout, stderr = await process.communicate()
```

## Activity Tracking & Cleanup

Docker mode uses **in-memory activity tracking** (single orchestrator instance):

```python
# Track activity
self.activity_tracker[project_key] = time.time()

# Cleanup idle projects
async def cleanup_idle_environments(self, idle_timeout_minutes=30):
    current_time = time.time()
    for project_key, last_activity in self.activity_tracker.items():
        if current_time - last_activity > (idle_timeout_minutes * 60):
            # Clean up project
```

**Two-Tier Cleanup** (future enhancement):
1. **Tier 1** (30 min idle): Scale containers to 0 replicas (pause)
2. **Tier 2** (2 hours idle): Delete containers entirely

Currently only Tier 2 is implemented.

## Debugging

### View Generated Compose File

```bash
cat docker-compose-projects/my-app-abc123.yml
```

### Check Container Status

```bash
docker ps | grep my-app-abc123
```

### View Logs

```bash
docker logs my-app-abc123-frontend
docker logs my-app-abc123-frontend --follow
```

### Inspect Networks

```bash
docker network ls | grep tesslate
docker network inspect tesslate-my-app-abc123
```

### Check Project Files

```bash
# From host (if using bind mounts)
ls users/user-id/project-id/

# From shared volume
docker run --rm -v tesslate-projects-data:/data alpine ls /data/my-app-abc123
```

### Traefik Routing

```bash
# Check Traefik dashboard
open http://localhost:8080

# Verify Traefik is connected to project network
docker inspect tesslate-traefik | grep tesslate-my-app-abc123
```

## Common Issues

### Container Won't Start

**Problem**: `docker compose up` fails

**Debugging**:
1. Check compose file syntax: `docker compose -f ... config`
2. View error: `docker compose -f ... up` (without `-d`)
3. Check image exists: `docker images | grep tesslate-devserver`

### Files Not Found

**Problem**: Container can't find project files

**Debugging**:
1. Check volume exists: `docker volume ls | grep tesslate-projects-data`
2. Verify files exist: `docker run --rm -v tesslate-projects-data:/data alpine ls /data/{slug}`
3. Check subpath is correct in compose file
4. Ensure orchestrator created project directory: `/projects/{slug}/`

### Traefik Not Routing

**Problem**: `*.localhost` URLs return 404

**Debugging**:
1. Check Traefik is running: `docker ps | grep traefik`
2. Verify Traefik is connected to project network:
   ```bash
   docker network inspect tesslate-my-app-abc123 | grep traefik
   ```
3. Check container labels:
   ```bash
   docker inspect my-app-abc123-frontend | grep traefik
   ```
4. View Traefik dashboard: `http://localhost:8080`

### Port Conflicts

**Problem**: Container fails to bind port

**Solution**: Docker mode should not expose ports directly (only via Traefik). Check compose file doesn't have conflicting `ports:` entries.

## Advantages & Limitations

### Advantages

✅ **Fast iteration**: Quick startup, no cluster overhead
✅ **Simple debugging**: Standard Docker commands, direct file access
✅ **Easy local setup**: Just Docker and Docker Compose
✅ **Direct filesystem access**: Fast file operations for AI agent

### Limitations

❌ **Single machine**: Cannot scale horizontally
❌ **No hibernation**: Projects consume resources when idle (no S3 sandwich)
❌ **Activity tracking**: In-memory only (doesn't survive orchestrator restart)
❌ **Security**: Less isolated than Kubernetes NetworkPolicy

## Configuration

Key environment variables for Docker mode:

```bash
# Deployment mode
DEPLOYMENT_MODE=docker

# Volume configuration
USE_DOCKER_VOLUMES=true  # Use volumes vs bind mounts

# Traefik
TRAEFIK_NETWORK=tesslate-regional-traefik-network
```

## Next Steps

- Compare with [kubernetes-mode.md](./kubernetes-mode.md) for production deployment
- See [base.py](../../../orchestrator/app/services/orchestration/base.py) for full interface
- Review [factory.py](../../../orchestrator/app/services/orchestration/factory.py) for mode selection logic
