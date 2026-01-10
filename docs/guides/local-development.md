# Local Development Setup

This guide covers setting up Tesslate Studio for local development using Docker Compose.

## Prerequisites

### Required Software

| Software | Version | Purpose |
|----------|---------|---------|
| Docker Desktop | Latest | Container runtime |
| Node.js | 18+ | Frontend development |
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

### Backend Environment (.env)

Create `orchestrator/.env` with the following variables:

```bash
# Database
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/tesslate

# Security
SECRET_KEY=your-secret-key-here-change-in-production

# Application
APP_DOMAIN=studio.localhost
DEPLOYMENT_MODE=docker

# AI Configuration
LITELLM_API_KEY=your-openai-or-anthropic-key
LITELLM_DEFAULT_MODEL=gpt-4

# OAuth (optional for local dev)
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GITHUB_CLIENT_ID=
GITHUB_CLIENT_SECRET=

# Stripe (optional for local dev)
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
```

### Frontend Environment (.env)

Create `app/.env` with:

```bash
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000
```

## Docker Compose Setup

### 1. Start Services

From the project root:

```bash
docker-compose up -d
```

This starts:
- PostgreSQL database (port 5432)
- Traefik reverse proxy (port 80, 443)
- Backend API (port 8000)
- Frontend (port 3000)

### 2. Verify Services

```bash
# Check all containers are running
docker-compose ps

# View logs
docker-compose logs -f

# View specific service logs
docker-compose logs -f backend
docker-compose logs -f frontend
```

### 3. Initialize Database

The database tables are created automatically on first startup. To run migrations:

```bash
cd orchestrator
alembic upgrade head
```

## Running Without Docker

For faster development iteration, run services directly:

### Terminal 1: Database

```bash
docker-compose up -d postgres
```

### Terminal 2: Backend

```bash
cd orchestrator
source .venv/bin/activate  # or Windows equivalent
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
| Frontend | http://localhost:3000 | Main application |
| Backend API | http://localhost:8000 | REST API |
| API Docs | http://localhost:8000/docs | Swagger UI |
| Traefik Dashboard | http://localhost:8080 | Reverse proxy admin |

## Development Workflow

### Making Backend Changes

1. Edit files in `orchestrator/app/`
2. If using `--reload`, changes apply automatically
3. Check logs for errors: `docker-compose logs -f backend`

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
# Stop containers
docker-compose down

# Remove database volume
docker volume rm tesslate-studio_postgres-data

# Restart
docker-compose up -d
```

### Rebuild Images

```bash
# Rebuild all images
docker-compose build --no-cache

# Rebuild specific service
docker-compose build --no-cache backend
```

### View Container Shell

```bash
# Access backend container
docker-compose exec backend bash

# Access database
docker-compose exec postgres psql -U postgres -d tesslate
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
├── docker-compose.yml        # Local development setup
└── k8s/                     # Kubernetes manifests
```

## Next Steps

- [Minikube Setup](minikube-setup.md) - Test Kubernetes features locally
- [Adding Routers](adding-routers.md) - Create new API endpoints
- [Adding Agent Tools](adding-agent-tools.md) - Extend agent capabilities
- [Troubleshooting](troubleshooting.md) - Common issues and solutions
