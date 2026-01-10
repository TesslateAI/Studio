# Dockerfile Documentation

Docker image definitions for Tesslate Studio.

## Backend (orchestrator/Dockerfile)

**Location**: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/Dockerfile`

**Base**: `python:3.11-slim`

**Installed**:
- gcc, git, curl (build tools)
- Docker CLI (for container management)
- Python dependencies via uv

**Layers**:
1. Install system packages + Docker CLI
2. Copy pyproject.toml
3. Install Python packages with uv
4. Copy application code
5. Expose port 8000
6. CMD: uvicorn with --reload

**Key Feature**: Docker-in-Docker support (mounts /var/run/docker.sock)

## Frontend (app/Dockerfile.prod)

**Location**: `c:/Users/Smirk/Downloads/Tesslate-Studio/app/Dockerfile.prod`

**Multi-stage Build**:

**Stage 1: Builder**
- Base: `node:20-alpine`
- Install dependencies: `npm install --force`
- Build: `npx vite build`
- Output: `dist/` directory

**Stage 2: Production**
- Base: `nginx:alpine`
- Copy built assets from stage 1
- Configure NGINX for SPA routing
- Expose port 80

**Build Args**:
- `VITE_API_URL`: API endpoint (baked into bundle)
- `VITE_PUBLIC_POSTHOG_KEY`: Analytics key

**NGINX Config**: try_files for SPA, cache control for assets

## Devserver (orchestrator/Dockerfile.devserver)

**Location**: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/Dockerfile.devserver`

**Purpose**: Universal dev environment for user projects

**Base**: `node:20-alpine`

**Installed**:
- Node.js 20 + npm
- Python 3 + pip
- Go + Air (hot reload)
- git, curl, bash, tmux
- zip/unzip (for S3 ops)

**Pre-installed Dependencies** (from template):
- Vite, React, TypeScript
- ESLint, Tailwind
- FastAPI, Uvicorn (Python)

**Features**:
- Multi-language support (Node, Python, Go)
- Pre-cached npm packages (fast startup)
- Non-root user (uid 1000)
- Health check

**Working Directory**: `/template` (copied to /workspace at runtime)

## Build Commands

### Local Development

```bash
# Backend (hot reload via docker-compose)
docker-compose up -d --build orchestrator

# Frontend (hot reload via docker-compose)
docker-compose up -d --build app

# Devserver (for user containers)
docker build -t tesslate-devserver:latest -f orchestrator/Dockerfile.devserver orchestrator/
```

### Production (AWS ECR)

```bash
# Login
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com

# Backend
docker build --no-cache -t tesslate-backend:latest -f orchestrator/Dockerfile orchestrator/
docker tag tesslate-backend:latest <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend:latest
docker push <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend:latest

# Frontend
docker build --no-cache -t tesslate-frontend:latest -f app/Dockerfile.prod app/
docker tag tesslate-frontend:latest <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-frontend:latest
docker push <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-frontend:latest

# Devserver
docker build --no-cache -t tesslate-devserver:latest -f orchestrator/Dockerfile.devserver orchestrator/
docker tag tesslate-devserver:latest <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-devserver:latest
docker push <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-devserver:latest
```

### Minikube

```bash
# CRITICAL: Delete old image first
minikube -p tesslate ssh -- docker rmi -f tesslate-backend:latest

# Build
docker build --no-cache -t tesslate-backend:latest -f orchestrator/Dockerfile orchestrator/

# Load into Minikube
minikube -p tesslate image load tesslate-backend:latest
```

## Best Practices

1. **Always use --no-cache**: Ensures code changes are included
2. **Multi-stage builds**: Frontend uses builder pattern for smaller images
3. **Layer caching**: Copy package files before code for better caching
4. **Non-root user**: Devserver runs as uid 1000
5. **Health checks**: All images include health check commands
6. **Minimal base images**: Alpine Linux for smaller size

## Optimization Tips

### Reduce Backend Image Size

Current: ~1.5GB (includes Docker CLI)

Improvements:
- Use Alpine instead of Debian Slim (~500MB savings)
- Multi-stage build (build deps in stage 1)
- .dockerignore for unused files

### Reduce Devserver Image Size

Current: ~1.2GB (includes Node, Python, Go + deps)

Improvements:
- Separate images per language (devserver-node, devserver-python, devserver-go)
- Install language-specific deps at runtime
- Use smaller base (distroless for production)

### Faster Builds

- Use BuildKit: `DOCKER_BUILDKIT=1 docker build ...`
- Layer caching: Don't change package files
- Multi-platform builds: `docker buildx build --platform linux/amd64,linux/arm64`

## Related Documentation

- [README.md](README.md): Docker overview
- [docker-compose.md](docker-compose.md): Compose configuration
