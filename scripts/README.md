# Tesslate Studio - Scripts Directory

This directory contains utility scripts for managing Tesslate Studio in different deployment modes.

## 📁 Directory Structure

```
scripts/
├── deployment/        # Local development and deployment scripts
├── kubernetes/        # Kubernetes management and operations
├── database/          # Database migrations and schema updates
├── litellm/          # LiteLLM integration and user management
└── utilities/        # Testing and maintenance utilities
```

## 🚀 Quick Start

### Local Development
```bash
# Windows (Hybrid mode - recommended)
scripts/deployment/start-all-with-traefik.bat

# Unix (individual services)
./scripts/deployment/run-backend.sh    # Terminal 1
./scripts/deployment/run-frontend.sh   # Terminal 2

# Docker setup
./scripts/deployment/setup-docker-dev.bat   # Windows
./scripts/deployment/setup-docker-dev.sh    # Unix
```

### Kubernetes Production
```bash
# Deploy complete application
./scripts/kubernetes/manage-k8s.sh deploy

# Check status
./scripts/kubernetes/manage-k8s.sh status

# View logs
./scripts/kubernetes/manage-k8s.sh logs backend

# Update after code changes
./scripts/kubernetes/manage-k8s.sh update
```

## 📂 Script Categories

### deployment/ - Local Development & Deployment

- **`start-all-with-traefik.bat`** (Windows)
  - Starts all services natively (orchestrator, frontend, AI service) + Traefik in Docker
  - Best for fast iteration and development
  - Requires: Python, Node.js, Docker Desktop
  - Usage: `scripts/deployment/start-all-with-traefik.bat`

- **`start-all.bat`** (Windows) - ⚠️ **LEGACY**
  - Starts services natively WITHOUT Traefik
  - User containers won't work without Traefik
  - Use `start-all-with-traefik.bat` instead

- **`run-backend.sh`** (Unix)
  - Starts orchestrator service only
  - Usage: `./scripts/deployment/run-backend.sh`

- **`run-frontend.sh`** (Unix)
  - Starts frontend development server only
  - Usage: `./scripts/deployment/run-frontend.sh`

- **`setup-docker-dev.bat`** / **`setup-docker-dev.sh`**
  - Sets up Docker development environment
  - Creates necessary directories and configurations
  - Usage: `scripts/deployment/setup-docker-dev.bat` (Windows)
  - Usage: `./scripts/deployment/setup-docker-dev.sh` (Unix)

- **`verify-env.bat`** / **`verify-env.ps1`** / **`verify_env.py`**
  - Validates environment configuration
  - Checks required dependencies and settings
  - Usage: `scripts/deployment/verify-env.bat` (Windows CMD)
  - Usage: `scripts/deployment/verify-env.ps1` (Windows PowerShell)
  - Usage: `python scripts/deployment/verify_env.py` (All platforms)

### kubernetes/ - Production Kubernetes Management

- **`manage-k8s.sh`** (Unix)
  - Complete Kubernetes management script
  - Commands: status, logs, restart, scale, backup, restore, deploy, update
  - Usage: `./scripts/kubernetes/manage-k8s.sh [command]`
  - Examples:
    ```bash
    ./scripts/kubernetes/manage-k8s.sh status        # View all resources
    ./scripts/kubernetes/manage-k8s.sh logs backend  # View backend logs
    ./scripts/kubernetes/manage-k8s.sh restart backend  # Restart backend
    ./scripts/kubernetes/manage-k8s.sh backup        # Backup database
    ./scripts/kubernetes/manage-k8s.sh update        # Build & deploy new images
    ```

- **`cleanup-k8s.sh`** (Unix)
  - Kubernetes cleanup script
  - Options:
    1. Clean user environments only (safe)
    2. Clean everything including database (destructive)
  - Usage: `./scripts/kubernetes/cleanup-k8s.sh`

### database/ - Database Migrations

- **`create_marketplace_tables.py`**
  - Creates marketplace database tables
  - Sets up agent marketplace schema
  - Usage: `python scripts/database/create_marketplace_tables.py`

- **`add_marketplace_columns.py`**
  - Adds marketplace-related columns to existing tables
  - Usage: `python scripts/database/add_marketplace_columns.py`

- **`add_name_column.py`**
  - Adds name column to database tables
  - Usage: `python scripts/database/add_name_column.py`

### litellm/ - LiteLLM Integration

- **`create_litellm_team.py`**
  - Creates LiteLLM team/access group
  - Usage: `python scripts/litellm/create_litellm_team.py`

- **`setup_user_litellm.py`**
  - Sets up LiteLLM virtual keys for users
  - Initializes user budgets and permissions
  - Usage: `python scripts/litellm/setup_user_litellm.py`

- **`migrate_litellm_keys.py`**
  - Migrates existing LiteLLM keys to new format
  - Usage: `python scripts/litellm/migrate_litellm_keys.py`

- **`update_litellm_models.py`**
  - Updates available LiteLLM models
  - Usage: `python scripts/litellm/update_litellm_models.py`

- **`update_litellm_team.py`**
  - Updates LiteLLM team configuration
  - Usage: `python scripts/litellm/update_litellm_team.py`

### utilities/ - Testing & Maintenance

- **`cleanup-local.py`** (All platforms)
  - Complete cleanup for local Docker development
  - Removes all containers, projects, and database data
  - Usage: `python scripts/utilities/cleanup-local.py`

- **`test_all_endpoints.sh`** (Unix)
  - Tests all API endpoints
  - Validates API functionality
  - Usage: `./scripts/utilities/test_all_endpoints.sh`

- **`check_agents.py`**
  - Checks agent configuration and status
  - Usage: `python scripts/utilities/check_agents.py`

## 🧹 Cleanup

### Local (Docker)
```bash
python scripts/utilities/cleanup-local.py
```

### Production (Kubernetes)
```bash
./scripts/kubernetes/cleanup-k8s.sh
# Choose option 1 (user envs only) or 2 (complete reset)
```

## 📚 More Information

- **Deployment Guide**: See `DEPLOYMENT.md` in the root directory
- **Kubernetes Setup**: See `k8s/` directory for manifests and deployment scripts
- **Docker Compose**: See `docker-compose.yml` for full Docker setup

## ⚠️ Important Notes

1. **Traefik is required** for user development containers, even in hybrid mode
2. **PostgreSQL** is used in all deployment modes (Docker and Kubernetes)
3. Always use **`scripts/kubernetes/manage-k8s.sh`** for production operations (not kubectl directly)
4. **Backup before cleanup** - cleanups are destructive and irreversible!
5. **Script paths have changed** - all scripts are now organized into subdirectories by category

## 🔨 Building Docker Images

### Dev Server Image
The development server image contains pre-installed dependencies for user project containers:

```bash
# Build for local development
./scripts/deployment/build-dev-image.sh

# Build and push to DigitalOcean Container Registry (production)
./scripts/deployment/build-dev-image.sh --push

# Force rebuild without cache
./scripts/deployment/build-dev-image.sh --no-cache

# Windows
scripts\deployment\build-dev-image.bat --push
```

This image is used by both Docker (local) and Kubernetes (production) deployment modes.
