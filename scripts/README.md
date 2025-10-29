# Tesslate Studio - Scripts Directory

This directory contains utility scripts for managing Tesslate Studio deployment, seeding data, and maintenance tasks.

## 📁 Directory Structure

```
scripts/
├── deployment/        # Local development and deployment scripts
├── litellm/          # LiteLLM integration and user key management
├── seed/             # Database seeding scripts for agents and bases
└── utilities/        # Maintenance and cleanup utilities
```

## 🚀 Quick Start

### Local Development
```bash
# Windows (Hybrid mode - recommended)
scripts\deployment\start-all-with-traefik.bat

# Windows (Legacy - without Traefik)
scripts\deployment\start-all.bat

# Unix (individual services)
./scripts/deployment/run-backend.sh    # Terminal 1
./scripts/deployment/run-frontend.sh   # Terminal 2

# Docker setup
scripts\deployment\setup-docker-dev.bat   # Windows
./scripts/deployment/setup-docker-dev.sh  # Unix

# Verify environment configuration
scripts\deployment\verify-env.bat         # Windows CMD
scripts\deployment\verify-env.ps1         # Windows PowerShell
python scripts/deployment/verify_env.py   # All platforms
```

### Initial Setup
```bash
# 1. Seed marketplace bases (Next.js, Vite+React+FastAPI, Vite+React+Go)
python scripts/seed/seed_marketplace_bases.py

# 2. Seed default agents (Stream Builder, Tesslate Agent, etc.)
python scripts/seed/seed_marketplace_agents.py

# 3. (Optional) Seed additional open source agents
python scripts/seed/seed_opensource_agents.py
```

## 📂 Script Categories

### deployment/ - Local Development & Deployment

**Startup Scripts:**

- **`start-all-with-traefik.bat`** (Windows) - ⭐ **RECOMMENDED**
  - Starts all services natively (orchestrator, frontend) + Traefik in Docker
  - Best for fast iteration and development
  - Requires: Python, Node.js, Docker Desktop
  - Usage: `scripts\deployment\start-all-with-traefik.bat`

- **`start-all.bat`** (Windows) - ⚠️ **LEGACY**
  - Starts services natively WITHOUT Traefik
  - User development containers won't work without Traefik
  - Use `start-all-with-traefik.bat` instead

- **`run-backend.sh`** (Unix)
  - Starts orchestrator backend service only
  - Usage: `./scripts/deployment/run-backend.sh`

- **`run-frontend.sh`** (Unix)
  - Starts frontend development server only
  - Usage: `./scripts/deployment/run-frontend.sh`

**Setup & Configuration:**

- **`setup-docker-dev.bat`** / **`setup-docker-dev.sh`**
  - Sets up Docker development environment
  - Creates necessary directories and network configurations
  - Usage: `scripts\deployment\setup-docker-dev.bat` (Windows)
  - Usage: `./scripts/deployment/setup-docker-dev.sh` (Unix)

- **`verify-env.bat`** / **`verify-env.ps1`** / **`verify_env.py`**
  - Validates environment configuration (.env file)
  - Checks required dependencies and settings
  - Displays current configuration
  - Usage: `scripts\deployment\verify-env.bat` (Windows CMD)
  - Usage: `scripts\deployment\verify-env.ps1` (Windows PowerShell)
  - Usage: `python scripts/deployment/verify_env.py` (All platforms)

**Docker Images:**

- **`build-dev-image.bat`** / **`build-dev-image.sh`**
  - Builds the development server Docker image for user project containers
  - Contains pre-installed dependencies (Node.js, Python, Go, etc.)
  - Options:
    - `--push`: Build and push to container registry
    - `--no-cache`: Force rebuild without cache
  - Usage: `scripts\deployment\build-dev-image.bat` (Windows)
  - Usage: `./scripts/deployment/build-dev-image.sh [--push] [--no-cache]` (Unix)

### litellm/ - LiteLLM Integration & User Key Management

- **`create_litellm_team.py`**
  - Creates the "internal" team in LiteLLM for access control
  - Required for users to access models (e.g., cerebras/qwen-3-coder-480b)
  - Usage: `python scripts/litellm/create_litellm_team.py`

- **`create_virtual_key_for_user.py`**
  - Creates a proper LiteLLM virtual key for a specific user
  - Sets up user budgets and model access
  - Usage: `python scripts/litellm/create_virtual_key_for_user.py <username>`

- **`create_key_direct.py`**
  - Lower-level script to create LiteLLM keys directly
  - Bypasses normal user creation flow
  - Usage: `python scripts/litellm/create_key_direct.py <username>`

### seed/ - Database Seeding Scripts

- **`seed_marketplace_bases.py`**
  - Seeds initial project templates/bases
  - Creates: Next.js 15, Vite+React+FastAPI, Vite+React+Go bases
  - Run this first to populate the marketplace with starter templates
  - Usage: `python scripts/seed/seed_marketplace_bases.py`

- **`seed_marketplace_agents.py`**
  - Seeds core marketplace agents
  - Creates: Stream Builder, Tesslate Agent, React Component Builder, API Integration Agent
  - Automatically adds Stream Builder to all existing users
  - Usage: `python scripts/seed/seed_marketplace_agents.py`

- **`seed_opensource_agents.py`**
  - Seeds additional open source agents
  - Creates: Code Analyzer, Documentation Writer, Refactoring Assistant, Test Generator, API Designer, DB Schema Designer
  - All agents are forkable and support model swapping
  - Usage: `python scripts/seed/seed_opensource_agents.py`

- **`delete_seeded_agents.py`**
  - Removes seeded marketplace agents and their user purchases
  - Useful for resetting the marketplace during development
  - Usage: `python scripts/seed/delete_seeded_agents.py`

### utilities/ - Maintenance & Debugging

- **`cleanup-local.py`**
  - Complete cleanup for local Docker development mode
  - Removes all containers, projects, files, and database entries
  - **WARNING**: Destructive operation - requires confirmation
  - Usage: `python scripts/utilities/cleanup-local.py`

- **`check_agents.py`**
  - Checks agent configuration and status in the database
  - Displays all agents, their active status, and user count
  - Useful for debugging marketplace agent issues
  - Usage: `python scripts/utilities/check_agents.py`

## 🎯 Common Workflows

### First Time Setup
```bash
# 1. Verify your environment configuration
python scripts/deployment/verify_env.py

# 2. Setup Docker environment
scripts\deployment\setup-docker-dev.bat  # Windows
./scripts/deployment/setup-docker-dev.sh # Unix

# 3. Start the application
scripts\deployment\start-all-with-traefik.bat  # Windows

# 4. Seed marketplace data (in separate terminal)
python scripts/seed/seed_marketplace_bases.py
python scripts/seed/seed_marketplace_agents.py
python scripts/seed/seed_opensource_agents.py  # Optional

# 5. (Optional) Setup LiteLLM team
python scripts/litellm/create_litellm_team.py
```

### Development Workflow
```bash
# Start development (Windows)
scripts\deployment\start-all-with-traefik.bat

# Start development (Unix - separate terminals)
./scripts/deployment/run-backend.sh
./scripts/deployment/run-frontend.sh

# Check agents
python scripts/utilities/check_agents.py
```

### Clean Slate Reset
```bash
# Complete local cleanup (removes everything)
python scripts/utilities/cleanup-local.py

# Re-seed marketplace
python scripts/seed/seed_marketplace_bases.py
python scripts/seed/seed_marketplace_agents.py
```

## 📚 More Information

- **Deployment Guide**: See `DEPLOYMENT.md` in the root directory
- **Docker Compose**: See `docker-compose.yml` for full Docker setup
- **Environment Setup**: Copy `.env.example` to `.env` and configure

## ⚠️ Important Notes

1. **Traefik is required** for user development containers, even in hybrid mode
2. **PostgreSQL** is used as the database in all deployment modes
3. **Run seeding scripts** after first setup to populate marketplace with agents and bases
4. **Cleanup operations are destructive** - they permanently remove data
5. **LiteLLM setup** is required for AI features to work properly
6. All Python scripts should be run from the project root directory

## 🔧 Troubleshooting

### Environment Issues
```bash
# Check your configuration
python scripts/deployment/verify_env.py
```

### Missing Agents in Marketplace
```bash
# Check what agents exist
python scripts/utilities/check_agents.py

# Re-seed agents if needed
python scripts/seed/seed_marketplace_agents.py
```

### LiteLLM Key Issues
```bash
# Create virtual key for a user
python scripts/litellm/create_virtual_key_for_user.py <username>
```
