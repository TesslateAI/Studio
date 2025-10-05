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

Choose your deployment method based on your needs:

### Option 1: Full Docker (Simplest - Recommended for Beginners)

```bash
# 1. Configure environment
cp .env.example .env
# Edit .env and set SECRET_KEY and OPENAI_API_KEY

# 2. Start all services
docker compose up -d

# 3. Access at http://studio.localhost
```

**Access:**
- Frontend: http://studio.localhost
- Orchestrator API: http://api.localhost
- Traefik Dashboard: http://traefik.localhost:8080

### Option 2: Hybrid Mode (Fastest - Recommended for Development)

```bash
# Windows
scripts\start-all-with-traefik.bat

# Linux/Mac - coming soon (use Full Docker for now)
```

**Access:**
- Frontend: http://localhost:5173
- Orchestrator API: http://localhost:8000
- User Projects: http://user{id}-project{id}.localhost

### 📚 Need More Options?

See **[DEPLOYMENT.md](DEPLOYMENT.md)** for:
- ✅ Detailed setup instructions
- ✅ Production deployment (Docker Compose & Kubernetes)
- ✅ Networking architecture explained
- ✅ Troubleshooting guide
- ✅ Decision flowchart for choosing deployment method

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

For detailed deployment instructions, see **[DEPLOYMENT.md](DEPLOYMENT.md)**.

Quick links:
- **[Local Development](DEPLOYMENT.md#option-1-hybrid-mode-native--traefik-recommended-for-development)** - Fast iteration with hot reload
- **[Docker Compose](DEPLOYMENT.md#option-2-full-docker-compose-simplest-setup)** - Simple containerized setup
- **[Production (Single Server)](DEPLOYMENT.md#option-3-docker-compose-production-single-server)** - Docker Compose production
- **[Production (Scalable)](DEPLOYMENT.md#option-4-kubernetes-production-scalable)** - Kubernetes with auto-scaling

### Quick Production Deploy (Kubernetes)

```bash
cd k8s
cp .env.example .env  # Add DOCR_TOKEN
./scripts/deployment/deploy-all.sh
```

See [DEPLOYMENT.md](DEPLOYMENT.md) for complete setup instructions.

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