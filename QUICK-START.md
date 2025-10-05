# Tesslate Studio - Quick Start Reference Card

One-page reference for getting started with Tesslate Studio.

## 🎯 Choose Your Deployment

### Local Development

**Option A: Full Docker** (Simplest - Recommended for beginners)
```bash
cp .env.example .env          # Configure secrets
docker compose up -d          # Start everything
```
Access: http://studio.localhost

**Option B: Hybrid Mode** (Fastest - Recommended for development)
```bash
scripts\start-all-with-traefik.bat   # Windows
```
Access: http://localhost:5173

### Production Deployment

**Option A: Docker Compose** (Single server)
```bash
docker compose -f docker-compose.prod.yml up -d
```

**Option B: Kubernetes** (Scalable)
```bash
cd k8s && ./scripts/deployment/deploy-all.sh
```

📚 **Detailed instructions:** See [DEPLOYMENT.md](DEPLOYMENT.md)

---

## ⚡ Common Commands

### Docker Compose Mode

```bash
# Start all services
docker compose up -d

# View logs
docker compose logs -f

# Stop all services
docker compose down

# Rebuild after code changes
docker compose up -d --build

# Clean slate (removes data!)
docker compose down -v
```

### Hybrid Mode (Windows)

```bash
# Start all services
scripts\start-all-with-traefik.bat

# Stop services
# 1. Close service windows
# 2. docker-compose down
```

### Kubernetes Mode

```bash
# Deploy application
cd k8s && ./scripts/deployment/deploy-all.sh

# View pods
kubectl get pods -n tesslate

# View logs
kubectl logs -f deployment/tesslate-backend -n tesslate

# Restart deployment
kubectl rollout restart deployment/tesslate-backend -n tesslate

# View user environments
kubectl get pods -n tesslate-user-environments
```

---

## 🔧 Configuration Quick Reference

### Required Environment Variables

**For Local Development (orchestrator/.env):**
```env
SECRET_KEY=your-secret-key-here
OPENAI_API_KEY=your-openai-api-key
DATABASE_URL=sqlite+aiosqlite:///./builder.db
DEPLOYMENT_MODE=docker
```

**For Production (Kubernetes secrets):**
```env
SECRET_KEY=strong-random-key
OPENAI_API_KEY=your-openai-api-key
DATABASE_URL=postgresql+asyncpg://user:pass@postgres:5432/tesslate
DEPLOYMENT_MODE=kubernetes
DEV_SERVER_BASE_URL=https://studio-test.tesslate.com
```

---

## 🌐 Access URLs

### Local Development (Full Docker)
- Frontend: http://studio.localhost
- API: http://api.localhost
- Traefik Dashboard: http://traefik.localhost:8080
- User Projects: http://user{id}-project{id}.localhost

### Local Development (Hybrid Mode)
- Frontend: http://localhost:5173
- API: http://localhost:8000
- AI Service: http://localhost:8001
- Traefik Dashboard: http://localhost:8080
- User Projects: http://user{id}-project{id}.localhost

### Production (Kubernetes)
- Frontend: https://studio-test.tesslate.com
- API: https://studio-test.tesslate.com/api
- User Projects: https://user{id}-project{id}.studio-test.tesslate.com

---

## 🐛 Troubleshooting Quick Fixes

### Docker Issues

**Problem: "Docker daemon is not running"**
```bash
# Start Docker Desktop (Windows/Mac)
# Or on Linux: sudo systemctl start docker
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

# Then kill the process or change port
```

**Problem: "Cannot connect to user dev container"**
```bash
# Check Traefik is running
docker ps | grep traefik

# Check container exists
docker ps | grep tesslate-dev

# View Traefik dashboard
# Open http://localhost:8080
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
cd k8s && ./scripts/deployment/setup-registry-auth.sh
```

### Database Issues

**Problem: "Database connection failed"**
```bash
# Docker mode - check file exists
ls orchestrator/builder.db

# K8s mode - check PostgreSQL
kubectl get pods -n tesslate | grep postgres
kubectl logs postgres-0 -n tesslate
```

### Authentication Issues

**Problem: "Invalid token / JWT errors"**
```bash
# Verify SECRET_KEY is set
# Docker: check orchestrator/.env
# K8s: kubectl get secret tesslate-app-secrets -n tesslate -o yaml

# Ensure same SECRET_KEY across all services
```

---

## 📦 Service Ports Reference

| Service | Docker Mode | Hybrid Mode | Production (K8s) |
|---------|-------------|-------------|------------------|
| Frontend | 5173 | 5173 | 80/443 (HTTPS) |
| Orchestrator | 8000 | 8000 | 80/443 (HTTPS) |
| AI Service | 8001 | 8001 | Internal only |
| Traefik | 80, 8080 | 80, 8080 | N/A (uses NGINX) |
| PostgreSQL | N/A (SQLite) | N/A (SQLite) | 5432 (internal) |

---

## 🎨 Project Structure Quick Map

```
tesslate-studio/
├── orchestrator/       # Backend API (FastAPI)
├── app/               # Frontend (React + Vite)
├── ai-service/        # AI code generation
├── k8s/               # Kubernetes configs
│   ├── manifests/     # K8s resource definitions
│   └── scripts/       # Deployment scripts
├── scripts/           # Quick start scripts
├── traefik/           # Traefik configs (Docker mode)
├── docker-compose.yml          # Local dev setup
├── docker-compose.prod.yml     # Production setup
├── DEPLOYMENT.md      # Complete deployment guide
└── QUICK-START.md     # This file
```

---

## 📚 Documentation Index

- **[README.md](README.md)** - Project overview and architecture
- **[DEPLOYMENT.md](DEPLOYMENT.md)** - Complete deployment guide with all options
- **[CLAUDE.md](CLAUDE.md)** - Developer guide for Claude Code
- **[k8s/README.md](k8s/README.md)** - Kubernetes deployment details
- **[orchestrator/README.md](orchestrator/README.md)** - Backend API docs
- **[app/README.md](app/README.md)** - Frontend docs

---

## 💡 Pro Tips

### Development Workflow
1. Use **Hybrid Mode** for active development (fast hot reload)
2. Test with **Full Docker** before deploying
3. Always use `.env` files (don't commit secrets!)
4. Check logs in separate terminal windows

### Production Workflow
1. Use **Kubernetes** for production (scalable, reliable)
2. Setup monitoring and alerts
3. Enable automated backups
4. Use managed PostgreSQL database
5. Setup staging environment for testing

### Common Mistakes to Avoid
- ❌ Forgetting to start Traefik in Hybrid mode (user containers won't work!)
- ❌ Using weak `SECRET_KEY` in production
- ❌ Not setting `DEPLOYMENT_MODE` correctly
- ❌ Exposing `.env` files in version control
- ❌ Running SQLite in production (use PostgreSQL!)

---

## 🚀 Next Steps After Setup

1. **Create admin user**
   ```bash
   # Local/Docker
   cd orchestrator && uv run python -m app.create_admin

   # K8s
   kubectl exec -it deployment/tesslate-backend -n tesslate -- python -m app.create_admin
   ```

2. **Test the system**
   - Register a user account
   - Create a new project
   - Test code generation
   - Verify preview works

3. **Configure for your needs**
   - Set up custom AI models
   - Configure custom templates
   - Set resource limits (K8s)
   - Enable monitoring (production)

---

## 🆘 Getting Help

- **Issues?** Check [DEPLOYMENT.md](DEPLOYMENT.md) troubleshooting section
- **Questions?** Review [README.md](README.md) and [CLAUDE.md](CLAUDE.md)
- **Bugs?** File an issue on GitHub
- **Need more help?** Check server logs for detailed errors

---

**Happy Building! 🎉**
