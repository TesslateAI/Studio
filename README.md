# Tesslate Studio

AI-powered web application builder with dual-deployment architecture supporting both Docker and Kubernetes environments.

## 🏗️ Project Structure

```
tesslate-studio/
├── orchestrator/          # Backend orchestration service (FastAPI)
│   ├── app/              # Main application code with dual deployment support
│   └── backend/          # Legacy backend code (deprecated)
├── app/                   # Frontend application (React + Vite + TypeScript)
├── ai-service/           # AI code generation service (FastAPI)
├── k8s/                  # Kubernetes deployment configurations and scripts
│   ├── manifests/        # K8s manifests (base, core, database, security, etc.)
│   ├── scripts/          # Deployment and management scripts
│   └── docs/             # Kubernetes deployment documentation
├── traefik/              # Traefik reverse proxy configuration (Docker mode)
└── docker-compose.yml    # Local development setup with Traefik
```

## 🚀 Quick Start

### Prerequisites
- Docker & Docker Compose
- Node.js 20+
- Python 3.11+
- uv (Python package manager)

### Local Development (Docker Mode)

1. **Configure environment:**
```bash
# Copy and configure root .env for Docker Compose
cp .env.example .env
# Edit .env and set SECRET_KEY and OPENAI_API_KEY
```

2. **Start all services:**
```bash
docker compose up -d
```

3. **Access services:**
- Frontend: http://studio.localhost
- Orchestrator API: http://api.localhost
- AI Service: http://ai.localhost
- Traefik Dashboard: http://traefik.localhost:8080

### Individual Service Development

For development without Docker Compose:

**Orchestrator Service:**
```bash
cd orchestrator
cp .env.example .env  # Configure SECRET_KEY, DATABASE_URL, OPENAI_API_KEY
uv sync
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Frontend Application:**
```bash
cd app
cp .env.example .env  # Configure VITE_API_URL (usually empty for proxy)
npm install
npm run dev
```

**AI Service:**
```bash
cd ai-service
uv sync
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

## 🏛️ Architecture

### Dual-Deployment Architecture

Tesslate Studio supports two deployment modes configured via `DEPLOYMENT_MODE` environment variable:

**Docker Mode (default):**
- Local development with Docker containers and Traefik routing
- Each user project runs in its own container
- File storage: `users/{user_id}/projects/{project_id}/`
- Routing: `user{id}-project{id}.localhost`

**Kubernetes Mode:**
- Production deployment with Kubernetes Deployments and Ingress
- Pod-based isolation with shared PVC storage
- HTTPS routing with Let's Encrypt certificates
- Horizontal scaling and resource management

### Services

1. **Orchestrator** (`orchestrator/app/`)
   - User authentication and authorization (JWT)
   - Project and file management
   - Dual container management (Docker + Kubernetes)
   - AI agent system with tool calling
   - Database persistence (SQLAlchemy + SQLite/PostgreSQL)

2. **Frontend Application** (`app/`)
   - React + TypeScript SPA
   - Monaco Editor for code editing
   - Real-time project preview with live updates
   - Agent chat mode with streaming support
   - Tailwind CSS for styling

3. **AI Service** (`ai-service/`)
   - Code generation with OpenAI/Anthropic
   - Template-based project scaffolding
   - Chat interface with streaming support
   - Code refactoring and explanation

## 🔧 Configuration

### Environment Variables

**Root `.env` (Docker Compose quick start):**
```env
SECRET_KEY=your-secret-key-here-change-this-in-production
OPENAI_API_KEY=your-openai-api-key-here
# Optional: ANTHROPIC_API_KEY, DATABASE_URL, DEPLOYMENT_MODE
```

**orchestrator/.env** (individual service development):
```env
SECRET_KEY=your-secret-key-here-change-this-in-production
DATABASE_URL=sqlite+aiosqlite:///./builder.db
DEPLOYMENT_MODE=docker  # or "kubernetes"
OPENAI_API_KEY=your-openai-api-key-here
OPENAI_API_BASE=https://api.openai.com/v1
OPENAI_MODEL=gpt-4
# For K8s mode: DEV_SERVER_BASE_URL=https://your-domain.com
```

**app/.env** (usually empty for Docker mode):
```env
VITE_API_URL=  # Empty uses proxy or same-domain routing
```

**k8s/.env** (Kubernetes deployment):
```env
DOCR_TOKEN=your-digitalocean-container-registry-token
# Application secrets go in k8s/manifests/security/app-secrets.yaml
```

See `.env.example` files in each directory for complete documentation.

## 📦 Deployment

### Docker Compose (Local Development)

```bash
# 1. Configure environment
cp .env.example .env
# Edit .env and set SECRET_KEY and OPENAI_API_KEY

# 2. Start all services
docker compose up -d

# 3. Access at http://studio.localhost
```

### Kubernetes (Production)

**Prerequisites:**
- Kubernetes cluster (kubeadm or k3s)
- kubectl configured
- Domain with DNS pointing to cluster
- DigitalOcean Container Registry (or alternative)

**Quick Deploy:**
```bash
cd k8s

# 1. Configure secrets
cp .env.example .env
# Edit .env and set DOCR_TOKEN

cp manifests/security/app-secrets.yaml.example manifests/security/app-secrets.yaml
# Edit app-secrets.yaml with your SECRET_KEY, OPENAI_API_KEY, etc.

# 2. Deploy all resources
./scripts/deployment/deploy-all.sh
```

**Alternative - Deploy to new single server:**
```bash
# k3s (recommended - faster and lighter)
sudo ./k8s/scripts/local-deployment/k3s-setup-all.sh <SERVER_IP>

# OR kubeadm (full Kubernetes)
sudo ./k8s/scripts/local-deployment/setup-all.sh <SERVER_IP>
```

See [k8s/README.md](k8s/README.md) and [k8s/docs/](k8s/docs/) for detailed deployment guides.

## 🧪 Testing

```bash
# Kubernetes integration tests
cd k8s/scripts/testing
python test_k8s_integration.py
python test_user_environment_api.py
```

## 📚 Documentation

### Project Documentation
- [Development Guide](CLAUDE.md) - Dual-deployment architecture overview
- [Orchestrator API](orchestrator/README.md) - Backend API documentation
- [Frontend Application](app/README.md) - React frontend documentation
- [AI Service](ai-service/README.md) - AI service documentation

### Kubernetes Deployment
- [Kubernetes README](k8s/README.md) - K8s deployment overview
- [Deployment Guide](k8s/docs/KUBERNETES_DEPLOYMENT_GUIDE.md) - Complete deployment instructions
- [K3s Guide](k8s/docs/K3S_DEPLOYMENT_GUIDE.md) - Lightweight K8s deployment
- [Production Strategy](k8s/docs/PRODUCTION_DEPLOYMENT_STRATEGY.md) - Production deployment planning
- [Deployment Checklist](k8s/docs/DEPLOYMENT_CHECKLIST.md) - Pre-deployment checklist

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## 📄 License

MIT License - see LICENSE file for details