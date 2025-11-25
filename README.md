# Tesslate Studio

AI-powered web application builder with natural language code generation and live preview. Deploy locally with Docker or scale to production with Kubernetes.

## 🎯 Quick Start

### Choose Your Deployment

**Local Development (Recommended for Beginners)**
```bash
# 1. Configure environment
cp .env.example .env
# Edit .env and set SECRET_KEY and LITELLM_MASTER_KEY

# 2. Start all services
docker compose up -d

# 3. Access at http://localhost
```

**Local Development (Fast Iteration)**
```bash
# Windows - starts native services + Traefik
scripts\start-all-with-traefik.bat

# Access at http://localhost:5173
```

**Production (Kubernetes)**
```bash
cd k8s
./scripts/deployment/deploy-all.sh

# Access at https://studio-test.tesslate.com
```

## 📚 Table of Contents

- [Features](#-features)
- [Architecture](#️-architecture)
- [Deployment Options](#-deployment-options)
- [Configuration](#-configuration)
- [Common Commands](#-common-commands)
- [Troubleshooting](#-troubleshooting)
- [Documentation](#-documentation)

## ✨ Features

- **AI-Powered Code Generation** - Natural language to React/Vite applications
- **Live Preview** - Real-time application preview with hot module replacement
- **Multi-User Support** - Isolated development environments per user/project
- **Dual Deployment** - Same codebase runs on Docker or Kubernetes
- **Agent Chat Mode** - Interactive AI assistance with streaming responses
- **Monaco Editor** - Full-featured code editor with syntax highlighting
- **Project Management** - Create, edit, and organize multiple projects
- **Template System** - Pre-configured React/Vite starter templates

## 🏗️ Architecture

### Deployment Modes

Tesslate Studio supports two deployment modes via `DEPLOYMENT_MODE` environment variable:

**Docker Mode** (Local Development)
- User projects run as Docker containers
- Traefik reverse proxy with subdomain routing
- URLs: `{project-slug}.localhost` (e.g., `my-app-k3x8n2.localhost`)
- Storage: Local file system
- **Browser:** Chrome or Firefox recommended (auto-resolves `*.localhost`)

**Kubernetes Mode** (Production)
- User projects run as K8s Pods/Deployments
- NGINX Ingress Controller with SSL
- URLs: `{project-slug}.studio-test.tesslate.com` (e.g., `my-app-k3x8n2.studio-test.tesslate.com`)
- Storage: Shared PVC with subPath isolation

### Services

```
┌─────────────────────────────────────────┐
│         Tesslate Studio                 │
├─────────────────────────────────────────┤
│                                         │
│  ┌──────────────┐  ┌─────────────┐    │
│  │ Orchestrator │  │  Frontend   │    │
│  │  (FastAPI)   │  │ (React+Vite)│    │
│  │              │  │             │    │
│  │ • Auth/JWT   │  │ • Monaco    │    │
│  │ • Projects   │  │ • Preview   │    │
│  │ • AI Agent   │  │ • Chat UI   │    │
│  │ • Container  │  │             │    │
│  │   Mgmt       │  │             │    │
│  └──────────────┘  └─────────────┘    │
│                                        │
│  ┌────────────────────────────────┐   │
│  │  User Dev Containers (Dynamic) │   │
│  │  • my-app-k3x8n2.localhost   │
│  │  • blog-cms-h7y2k1.localhost │
│  └────────────────────────────────┘   │
└────────────────────────────────────────┘
```

**1. Orchestrator** (`orchestrator/`)
- FastAPI backend with JWT authentication
- Project and file management
- Dual container orchestration (Docker/K8s)
- Built-in AI agent system with OpenAI/Anthropic integration
- Streaming chat with tool calling support
- SQLAlchemy ORM with SQLite/PostgreSQL

**2. Frontend** (`app/`)
- React + TypeScript + Vite
- Monaco Editor integration
- Real-time preview with live updates
- Agent chat interface with streaming
- Tailwind CSS styling

## 🚀 Deployment Options

### Comparison Matrix

| Feature | Docker Compose | Hybrid Mode | Kubernetes |
|---------|---------------|-------------|------------|
| Setup Complexity | ⭐ Low | ⭐⭐ Medium | ⭐⭐⭐ High |
| Hot Reload | 🐢 Slow | ⚡ Fast | N/A |
| Production Ready | ❌ No | ❌ No | ✅ Yes |
| Scalability | Limited | None | Excellent |
| Cost | Free | Free | $$$ |
| Best For | Testing | Development | Production |

### Option 1: Full Docker Compose (Simplest)

**Best for:** Quick setup, testing, beginners

```bash
# Start all services
docker compose up -d

# View logs
docker compose logs -f

# Stop services
docker compose down

# Rebuild after changes
docker compose up -d --build
```

**Access:**
- Frontend: http://localhost
- API: http://api.localhost
- Traefik Dashboard: http://traefik.localhost:8080
- User Projects: http://{project-slug}.localhost (subdomain routing)

**Advantages:**
- ✅ Single command to start
- ✅ Consistent environment
- ✅ Easy cleanup

**Disadvantages:**
- ❌ Slow hot reload
- ❌ Higher resource usage
- ❌ Not production-ready

### Option 2: Hybrid Mode (Fastest Development)

**Best for:** Active development with fast hot reload

**Windows:**
```bash
scripts\start-all-with-traefik.bat
```

**Manual Setup:**
```bash
# 1. Start Traefik (required for user containers)
docker compose up -d traefik

# 2. Start orchestrator
cd orchestrator
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 3. Start frontend
cd app
npm run dev
```

**Access:**
- Frontend: http://localhost:5173
- API: http://localhost:8000
- User Projects: http://{project-slug}.localhost (subdomain routing)

**Advantages:**
- ✅ Fastest hot reload
- ✅ Full debugging support
- ✅ Lower resource usage

**Disadvantages:**
- ❌ Multiple terminal windows
- ❌ Requires Traefik in Docker
- ❌ More manual setup

### Option 3: Kubernetes (Production)

**Best for:** Production deployment, auto-scaling, high availability

**Quick Deploy:**
```bash
cd k8s
cp .env.example .env
# Edit .env and add DOCR_TOKEN

./scripts/deployment/deploy-all.sh
```

**Management:**
```bash
# Use the management script
./scripts/manage-k8s.sh status
./scripts/manage-k8s.sh logs backend
./scripts/manage-k8s.sh restart backend
./scripts/manage-k8s.sh backup
./scripts/manage-k8s.sh update
```

**Access:**
- Frontend: https://studio-test.tesslate.com
- API: https://studio-test.tesslate.com/api
- User Projects: https://{project-slug}.studio-test.tesslate.com (subdomain routing)

**Advantages:**
- ✅ Auto-scaling (HPA)
- ✅ High availability
- ✅ Self-healing
- ✅ Rolling updates
- ✅ SSL/TLS certificates

**Disadvantages:**
- ❌ Complex setup
- ❌ Higher cost
- ❌ Requires K8s knowledge

**See:** [Detailed Kubernetes Guide](k8s/README.md)

## 🔧 Configuration

### Environment Variables

**Root `.env` (Docker Compose):**
```env
SECRET_KEY=your-secret-key-here-change-this-in-production
LITELLM_MASTER_KEY=your-litellm-master-key-here
LITELLM_API_BASE=http://localhost:4000/v1
```

**`orchestrator/.env` (Individual Services):**
```env
SECRET_KEY=your-secret-key-here
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/tesslate
DEPLOYMENT_MODE=docker  # or "kubernetes"
LITELLM_API_BASE=http://localhost:4000/v1
LITELLM_MASTER_KEY=your-litellm-master-key
OPENAI_API_BASE=http://localhost:4000/v1  # Points to LiteLLM proxy
OPENAI_MODEL=gpt-4  # Model available in your LiteLLM instance

# CORS and Security (optional - has sensible defaults)
CORS_ORIGINS=http://localhost:5173,http://localhost:3000
ALLOWED_HOSTS=localhost,*.localhost
```

**`k8s/.env` (Kubernetes):**
```env
DOCR_TOKEN=your-digitalocean-container-registry-token
```

**Kubernetes Secrets:**

Configure secrets in `k8s/manifests/security/app-secrets.yaml`:
```yaml
SECRET_KEY: <base64-encoded>
JWT_SECRET: <base64-encoded>
LITELLM_MASTER_KEY: <base64-encoded>
DATABASE_URL: <base64-encoded>
CORS_ORIGINS: "https://studio-test.tesslate.com,https://studio-demo.tesslate.com"
ALLOWED_HOSTS: "studio-test.tesslate.com,*.studio-test.tesslate.com"
```

> **Note**: To add new domains after deployment, simply update the secrets file and restart the deployments. No image rebuild needed!

### Service Ports

| Service | Docker | Hybrid | Kubernetes |
|---------|--------|--------|------------|
| Frontend | 5173 | 5173 | 80/443 |
| Orchestrator | 8000 | 8000 | 80/443 |
| Traefik | 80, 8080 | 80, 8080 | N/A |
| PostgreSQL | N/A | N/A | 5432 |

## ⚡ Common Commands

### Docker Compose

```bash
# Start all services
docker compose up -d

# View logs (all services)
docker compose logs -f

# View logs (specific service)
docker compose logs -f orchestrator

# Stop all services
docker compose down

# Rebuild after code changes
docker compose up -d --build

# Clean slate (removes data!)
docker compose down -v

# Check service status
docker compose ps
```

### Kubernetes

```bash
# Using the management script (recommended)
./scripts/manage-k8s.sh status        # View all resources
./scripts/manage-k8s.sh logs backend  # View logs
./scripts/manage-k8s.sh restart backend  # Restart service
./scripts/manage-k8s.sh scale backend 3  # Scale to 3 replicas
./scripts/manage-k8s.sh backup        # Backup database
./scripts/manage-k8s.sh update        # Build & deploy new images

# Or use kubectl directly
kubectl get pods -n tesslate
kubectl logs -f deployment/tesslate-backend -n tesslate
kubectl rollout restart deployment/tesslate-backend -n tesslate
kubectl get pods -n tesslate-user-environments
```

### Cleanup Scripts

```bash
# Local Docker development
python scripts/cleanup-local.py

# Kubernetes (production)
./scripts/cleanup-k8s.sh
```

## 🐛 Troubleshooting

### Docker Issues

**Problem: "Docker daemon is not running"**
```bash
# Windows/Mac: Start Docker Desktop
# Linux: sudo systemctl start docker
```

**Problem: "Network tesslate-network not found"**
```bash
docker network create tesslate-network
```

**Problem: "Port already in use"**
```bash
# Windows
netstat -ano | findstr :8000

# Linux/Mac
lsof -i :8000

# Kill the process or change port in .env
```

**Problem: "User containers not accessible" or "Subdomain not resolving"**
```bash
# 1. Use Chrome or Firefox (auto-resolve *.localhost subdomains)
# Other browsers may require DNS configuration

# 2. Check Traefik is running
docker ps | grep traefik

# 3. Check container exists
docker ps | grep tesslate

# 4. View Traefik dashboard for routing rules
# Open http://localhost:8080
# Look for Host(`{project-slug}.localhost`) rules

# 5. Test with curl using Host header
curl -H "Host: test.localhost" http://localhost/
```

### Kubernetes Issues

**Problem: "Pods not starting"**
```bash
kubectl get pods -n tesslate
kubectl describe pod <pod-name> -n tesslate
kubectl logs <pod-name> -n tesslate
```

**Problem: "Ingress not working"**
```bash
kubectl get ingress -n tesslate
kubectl describe ingress -n tesslate
nslookup studio-test.tesslate.com
```

**Problem: "Image pull errors"**
```bash
# Recreate registry secret
cd k8s
./scripts/deployment/setup-registry-auth.sh
```

### Database Issues

**Problem: "Database connection failed"**
```bash
# Docker mode - check PostgreSQL connection
docker compose ps postgres
docker compose logs postgres

# K8s mode - check PostgreSQL
kubectl get pods -n tesslate | grep postgres
kubectl logs postgres-0 -n tesslate
```

### Authentication Issues

**Problem: "Invalid token / JWT errors"**
```bash
# Verify SECRET_KEY is set and consistent
# Docker: check orchestrator/.env
# K8s: kubectl get secret tesslate-app-secrets -n tesslate -o yaml
```

## 📚 Documentation

### Project Documentation
- **[CLAUDE.md](CLAUDE.md)** - Developer guide and architecture
- **[Orchestrator API](orchestrator/README.md)** - Backend API docs
- **[Frontend App](app/README.md)** - React frontend docs

### Deployment Guides
- **[Kubernetes README](k8s/README.md)** - K8s overview
- **[Kubernetes Deployment](k8s/docs/KUBERNETES_DEPLOYMENT_GUIDE.md)** - Complete K8s guide
- **[K3s Deployment](k8s/docs/K3S_DEPLOYMENT_GUIDE.md)** - Lightweight K8s
- **[Production Strategy](k8s/docs/PRODUCTION_DEPLOYMENT_STRATEGY.md)** - Production planning
- **[Deployment Checklist](k8s/docs/DEPLOYMENT_CHECKLIST.md)** - Pre-deployment checklist

### Script Documentation
- **[Scripts README](scripts/README.md)** - Utility scripts guide

## 🏗️ Project Structure

```
tesslate-studio/
├── orchestrator/          # Backend orchestration service (FastAPI)
│   ├── app/              # Main application code
│   │   ├── main.py       # FastAPI application entry point
│   │   ├── routers/      # API route handlers
│   │   ├── models.py     # SQLAlchemy database models
│   │   ├── k8s_client.py # Kubernetes client manager
│   │   └── dev_server_manager.py # Container orchestration
│   └── template/         # React/Vite project template
├── app/                   # Frontend application (React + Vite)
│   ├── src/
│   │   ├── pages/        # Page components
│   │   ├── components/   # Reusable components
│   │   └── lib/          # API client and utilities
│   └── package.json
├── k8s/                  # Kubernetes configurations
│   ├── manifests/        # K8s resource definitions
│   ├── scripts/          # Deployment and management scripts
│   └── docs/             # K8s documentation
├── scripts/              # Utility scripts
│   ├── cleanup-local.py  # Docker cleanup
│   ├── cleanup-k8s.sh    # K8s cleanup
│   └── manage-k8s.sh     # K8s management
├── traefik/              # Traefik configuration (Docker mode)
├── docker-compose.yml     # Local development setup
├── docker-compose.prod.yml # Production Docker setup
└── README.md             # This file

Note: All AI functionality is handled directly by the orchestrator service with
      built-in support for OpenAI, Anthropic, and Cerebras models.
```

## 💡 Pro Tips

### Development Workflow
1. Use **Hybrid Mode** for active development (fast hot reload)
2. Test with **Full Docker** before deploying
3. Always use `.env` files (never commit secrets!)
4. Check logs in separate terminal windows

### Production Workflow
1. Use **Kubernetes** for production (scalable, reliable)
2. Setup monitoring and alerts
3. Enable automated backups
4. Use managed PostgreSQL database
5. Setup staging environment for testing

### Common Mistakes to Avoid
- ❌ Forgetting to start Traefik in Hybrid mode (user containers won't work!)
- ❌ Using browsers other than Chrome/Firefox for local dev (subdomain DNS may not work)
- ❌ Using weak `SECRET_KEY` in production
- ❌ Not setting `DEPLOYMENT_MODE` correctly
- ❌ Exposing `.env` files in version control
- ❌ Running SQLite in production (use PostgreSQL!)

## 🧪 Testing

```bash
# Kubernetes integration tests
cd k8s/scripts/testing
python test_k8s_integration.py
python test_user_environment_api.py
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Commit your changes (`git commit -m 'Add amazing feature'`)
5. Push to the branch (`git push origin feature/amazing-feature`)
6. Open a Pull Request

## 📄 License

MIT License - see LICENSE file for details

---

**Need Help?**
- Check the [Troubleshooting](#-troubleshooting) section above
- Review detailed guides in [Documentation](#-documentation)
- File an issue on GitHub
- Check server logs for detailed errors

**Happy Building! 🎉**
