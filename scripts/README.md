# Tesslate Studio - Scripts Directory

This directory contains utility scripts for managing Tesslate Studio in different deployment modes.

## 📁 Script Overview

### Local Development (Docker Mode)

- **`start-all-with-traefik.bat`** (Windows)
  - Starts all services natively (orchestrator, frontend, AI service) + Traefik in Docker
  - Best for fast iteration and development
  - Requires: Python, Node.js, Docker Desktop

- **`start-all.bat`** (Windows) - ⚠️ **LEGACY**
  - Starts services natively WITHOUT Traefik
  - User containers won't work without Traefik
  - Use `start-all-with-traefik.bat` instead

- **`run-backend.sh`** (Unix)
  - Starts orchestrator service only
  - Usage: `./scripts/run-backend.sh`

- **`run-frontend.sh`** (Unix)
  - Starts frontend development server only
  - Usage: `./scripts/run-frontend.sh`

- **`cleanup-local.py`** (All platforms)
  - Complete cleanup for local Docker development
  - Removes all containers, projects, and database data
  - Usage: `python scripts/cleanup-local.py`

### Production (Kubernetes Mode)

- **`manage-k8s.sh`** (Unix)
  - Complete Kubernetes management script
  - Commands: status, logs, restart, scale, backup, restore, deploy, update
  - Usage: `./scripts/manage-k8s.sh [command]`
  - Examples:
    ```bash
    ./scripts/manage-k8s.sh status        # View all resources
    ./scripts/manage-k8s.sh logs backend  # View backend logs
    ./scripts/manage-k8s.sh restart backend  # Restart backend
    ./scripts/manage-k8s.sh backup        # Backup database
    ./scripts/manage-k8s.sh update        # Build & deploy new images
    ```

- **`cleanup-k8s.sh`** (Unix)
  - Kubernetes cleanup script
  - Options:
    1. Clean user environments only (safe)
    2. Clean everything including database (destructive)
  - Usage: `./scripts/cleanup-k8s.sh`

## 🚀 Quick Start

### Local Development
```bash
# Windows (Hybrid mode - recommended)
scripts/start-all-with-traefik.bat

# Unix (individual services)
./scripts/run-backend.sh    # Terminal 1
./scripts/run-frontend.sh   # Terminal 2
```

### Kubernetes Production
```bash
# Deploy complete application
./scripts/manage-k8s.sh deploy

# Check status
./scripts/manage-k8s.sh status

# View logs
./scripts/manage-k8s.sh logs backend

# Update after code changes
./scripts/manage-k8s.sh update
```

## 🧹 Cleanup

### Local (Docker)
```bash
python scripts/cleanup-local.py
```

### Production (Kubernetes)
```bash
./scripts/cleanup-k8s.sh
# Choose option 1 (user envs only) or 2 (complete reset)
```

## 📚 More Information

- **Deployment Guide**: See `DEPLOYMENT.md` in the root directory
- **Kubernetes Setup**: See `k8s/` directory for manifests and deployment scripts
- **Docker Compose**: See `docker-compose.yml` for full Docker setup

## ⚠️ Important Notes

1. **Traefik is required** for user development containers, even in hybrid mode
2. **PostgreSQL** is used in Kubernetes, **SQLite** in local development
3. Always use **`manage-k8s.sh`** for production operations (not kubectl directly)
4. **Backup before cleanup** - cleanups are destructive and irreversible!
