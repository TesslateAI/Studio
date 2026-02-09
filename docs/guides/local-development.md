# Local Development Setup

This guide covers running Tesslate Studio services natively on your machine (without Docker for the app/backend). This is useful for faster iteration and debugging with breakpoints.

> **Looking for Docker setup?** See [Docker Setup from Scratch](docker-setup.md) — the easiest way to get started.

## Prerequisites

### Required Software

| Software | Version | Purpose |
|----------|---------|---------|
| Docker Desktop | Latest | Container runtime (for PostgreSQL + user project containers) |
| Node.js | 20+ | Frontend development |
| Python | 3.11+ | Backend development |
| Git | Latest | Version control |

### System Requirements

- 8GB RAM minimum (16GB recommended)
- 20GB free disk space
- Docker Desktop running with WSL 2 (Windows) or native (macOS/Linux)

## Clone and Install

### 1. Clone the Repository

```bash
git clone https://github.com/your-org/tesslate-studio.git
cd tesslate-studio
```

### 2. Install Backend Dependencies

```bash
cd orchestrator

# Create virtual environment
python -m venv .venv

# Activate virtual environment
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# Windows CMD:
.\.venv\Scripts\activate.bat
# macOS/Linux:
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"
```

### 3. Install Frontend Dependencies

```bash
cd app
npm install
```

## Environment Variables

### Root Environment (.env)

Copy the example config from the project root:

```bash
cp .env.example .env
```

Edit `.env` with required values:

```bash
# REQUIRED
SECRET_KEY=your-secret-key-here-change-this
DEPLOYMENT_MODE=docker

# Database (points to Docker postgres container)
POSTGRES_DB=tesslate_dev
POSTGRES_USER=tesslate_user
POSTGRES_PASSWORD=dev_password_change_me

# AI Configuration (required for agent features)
LITELLM_API_BASE=https://your-litellm-url.com/v1
LITELLM_MASTER_KEY=your-litellm-master-key
LITELLM_DEFAULT_MODELS=gpt-4o-mini

# Domain
APP_PROTOCOL=http
APP_DOMAIN=localhost
```

### Frontend Environment (app/.env)

For native frontend development (not through Docker/Traefik), point directly to the backend:

```bash
VITE_API_URL=http://localhost:8000
```

## Native Development Setup

### Start PostgreSQL via Docker

You still need PostgreSQL running in Docker:

```bash
docker compose up -d postgres
```

Verify it's healthy:

```bash
docker compose ps postgres
```

### Run Database Migrations

```bash
cd orchestrator
alembic upgrade head
```

## Running Services Natively

Run each service in a separate terminal:

### Terminal 1: PostgreSQL (Docker)

```bash
docker compose up -d postgres
```

### Terminal 2: Backend

```bash
cd orchestrator
source .venv/bin/activate  # or Windows: .\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Terminal 3: Frontend

```bash
cd app
npm run dev
```

## Accessing the Application

| Service | URL | Description |
|---------|-----|-------------|
| Frontend | http://localhost:5173 | Vite dev server |
| Backend API | http://localhost:8000 | REST API |
| API Docs | http://localhost:8000/docs | Swagger UI |
| PostgreSQL | localhost:5432 | Database (pgAdmin/DBeaver) |

## Development Workflow

### Making Backend Changes

1. Edit files in `orchestrator/app/`
2. Uvicorn auto-reloads (watch for "Reloading..." in terminal)
3. Check terminal output for errors

### Making Frontend Changes

1. Edit files in `app/src/`
2. Vite hot-reloads automatically
3. Check browser console for errors

### Database Schema Changes

See the [Database Migrations](database-migrations.md) guide.

### Running Tests

```bash
# Backend tests
cd orchestrator
pytest

# Frontend tests
cd app
npm test
```

## Common Development Tasks

### Reset Database

```bash
# Stop postgres
docker compose down

# Remove database volume
docker volume rm tesslate-postgres-dev-data

# Restart postgres
docker compose up -d postgres

# Re-run migrations
cd orchestrator && alembic upgrade head
```

### Access Database Shell

```bash
docker compose exec postgres psql -U tesslate_user -d tesslate_dev
```

## Directory Structure

```
tesslate-studio/
├── orchestrator/              # FastAPI backend
│   ├── app/
│   │   ├── main.py           # Application entry point
│   │   ├── config.py         # Settings and configuration
│   │   ├── models.py         # SQLAlchemy models
│   │   ├── schemas.py        # Pydantic schemas
│   │   ├── routers/          # API endpoints
│   │   ├── services/         # Business logic
│   │   └── agent/            # AI agent system
│   ├── alembic/              # Database migrations
│   ├── tests/                # Backend tests
│   └── Dockerfile            # Backend container
│
├── app/                      # React frontend
│   ├── src/
│   │   ├── pages/           # Page components
│   │   ├── components/      # Reusable components
│   │   └── lib/             # Utilities and API client
│   ├── public/              # Static assets
│   └── Dockerfile.prod      # Frontend container
│
├── docker compose.yml        # Local development setup
└── k8s/                     # Kubernetes manifests
```

## Next Steps

- [Docker Setup from Scratch](docker-setup.md) - Full Docker Compose setup (easier, recommended for most developers)
- [Minikube Setup](minikube-setup.md) - Test Kubernetes features locally
- [Adding Routers](adding-routers.md) - Create new API endpoints
- [Adding Agent Tools](adding-agent-tools.md) - Extend agent capabilities
- [Troubleshooting](troubleshooting.md) - Common issues and solutions
