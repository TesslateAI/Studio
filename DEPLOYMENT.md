# Tesslate Studio Deployment Guide

Complete guide for deploying Tesslate Studio in different environments.

## 📋 Quick Decision Guide

```
┌─────────────────────────────────────────────────────────────┐
│ What are you trying to do?                                  │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
              ┌────────────┴────────────┐
              │                         │
         Development              Production
              │                         │
              ▼                         ▼
    ┌─────────────────┐      ┌──────────────────┐
    │ Fast iteration? │      │ Single server or │
    │    (hot reload) │      │   multi-server?  │
    └─────────────────┘      └──────────────────┘
          │     │                    │      │
        Yes    No                Single   Multi
          │     │                    │      │
          ▼     ▼                    ▼      ▼
      [HYBRID] [DOCKER]         [DOCKER]  [K8S]
```

### Quick Recommendations

- **🚀 Local Development (Fast)**: Use [Hybrid Mode](#option-1-hybrid-mode-native--traefik-recommended-for-development) - Native services + Traefik
- **🐳 Local Development (Simple)**: Use [Full Docker](#option-2-full-docker-compose-simplest-setup) - Everything containerized
- **📦 Production (Single Server)**: Use [Docker Compose Production](#option-3-docker-compose-production-single-server)
- **☸️ Production (Scalable)**: Use [Kubernetes](#option-4-kubernetes-production-scalable) - Cloud-native with auto-scaling

---

## 🏗️ Understanding the Architecture

### Deployment Modes

Tesslate Studio supports two deployment modes via `DEPLOYMENT_MODE` environment variable:

1. **Docker Mode** (`DEPLOYMENT_MODE=docker`)
   - User dev environments run as Docker containers
   - Uses Traefik reverse proxy for hostname-based routing
   - **Local dev**: `http://user{id}-project{id}.localhost`
   - **Production**: `https://user{id}-project{id}.yourdomain.com` (with wildcard DNS)
   - Storage: Volume mounts to `users/{user_id}/{project_id}/`

2. **Kubernetes Mode** (`DEPLOYMENT_MODE=kubernetes`)
   - User dev environments run as Kubernetes Pods/Deployments
   - Uses NGINX Ingress Controller with hostname-based routing
   - Routing: `https://user{id}-project{id}.studio-test.tesslate.com`
   - Storage: Shared PVC with subPath isolation

### Why Traefik is Required in Docker Mode

Even if you run main services natively (orchestrator, frontend, AI service), **Traefik must run in Docker** because:

```
┌──────────────────────────────────────────────────────────────┐
│ Native Services (on host)                                    │
│  • Orchestrator: localhost:8000                              │
│  • Frontend: localhost:5173                                  │
│  • AI Service: localhost:8001                                │
└──────────────────────────────────────────────────────────────┘
                           │
                           │ Creates user containers
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ Docker Network: tesslate-network                             │
│                                                               │
│  ┌──────────────┐    ┌───────────────────────────────────┐  │
│  │   Traefik    │───▶│  User Dev Containers (dynamic)    │  │
│  │  (required)  │    │  • user1-project5.localhost:5173  │  │
│  └──────────────┘    │  • user2-project8.localhost:5173  │  │
│                      │  • user3-project12.localhost:5173 │  │
│                      └───────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

**Why?**
- Multiple user projects need isolated containers
- Each needs unique hostname routing (`user1-project5.localhost`)
- Can't all bind to port 5173 simultaneously
- Traefik provides automatic service discovery and zero-port-conflict routing

---

## 📚 Deployment Options

## Option 1: Hybrid Mode (Native + Traefik) - Recommended for Development

**Best for:** Fast iteration with hot reload on main services while supporting user containers.

### Architecture
```
Host Machine:
  • Orchestrator (Python/FastAPI) - Native process on port 8000
  • Frontend (React/Vite) - Native process on port 5173
  • AI Service (Python/FastAPI) - Native process on port 8001

Docker:
  • Traefik - Reverse proxy for user dev containers
  • User Containers - Dynamically created as needed
```

### Prerequisites
- Docker Desktop running
- Python 3.11+
- Node.js 20+
- uv (Python package manager): `pip install uv`

### Setup Steps

1. **Configure environment**
   ```bash
   # In orchestrator directory
   cd orchestrator
   cp .env.example .env
   ```

   Edit `orchestrator/.env`:
   ```env
   SECRET_KEY=your-secret-key-here
   DATABASE_URL=sqlite+aiosqlite:///./builder.db
   DEPLOYMENT_MODE=docker
   OPENAI_API_KEY=your-openai-api-key
   ```

2. **Start services**
   ```bash
   # From root directory (Windows)
   scripts\start-all-with-traefik.bat

   # Or manually:
   # 1. Start Traefik
   docker compose up -d traefik

   # 2. Start orchestrator
   cd orchestrator && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

   # 3. Start AI service
   cd ai-service && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8001

   # 4. Start frontend
   cd app && npm run dev
   ```

3. **Access the application**
   - Frontend: http://localhost:5173
   - Orchestrator API: http://localhost:8000
   - AI Service: http://localhost:8001
   - Traefik Dashboard: http://localhost:8080
   - User Projects: http://user{id}-project{id}.localhost (auto-created)

### Advantages ✅
- Fastest hot reload for main services
- Full debugging capabilities (IDE breakpoints work)
- Lower resource usage
- Easy to modify and test code changes

### Disadvantages ❌
- Requires Traefik running in Docker
- More manual setup
- Need to manage multiple terminal windows

---

## Option 2: Full Docker Compose - Simplest Setup

**Best for:** Quick local testing without manual service management.

### Architecture
```
All services in Docker containers:
  • Traefik - Reverse proxy (port 80, 8080)
  • Orchestrator - Backend API
  • Frontend - React dev server
  • AI Service - Code generation service
  • User Containers - Dynamically created
```

### Prerequisites
- Docker Desktop running

### Setup Steps

1. **Configure environment**
   ```bash
   # In root directory
   cp .env.example .env
   ```

   Edit `.env`:
   ```env
   SECRET_KEY=your-secret-key-here
   OPENAI_API_KEY=your-openai-api-key
   ```

2. **Start all services**
   ```bash
   docker compose up -d
   ```

3. **View logs**
   ```bash
   # All services
   docker compose logs -f

   # Specific service
   docker compose logs -f orchestrator
   ```

4. **Access the application**
   - Frontend: http://studio.localhost
   - Orchestrator API: http://api.localhost
   - Traefik Dashboard: http://traefik.localhost:8080
   - User Projects: http://user{id}-project{id}.localhost

### Advantages ✅
- Single command to start everything
- Consistent environment (no "works on my machine")
- Easy to clean up (`docker compose down`)
- Matches production setup more closely

### Disadvantages ❌
- Slower hot reload (requires container rebuilds)
- Harder to debug (need to attach to containers)
- Higher resource usage
- Code changes need image rebuilds

### Useful Commands
```bash
# Stop all services
docker compose down

# Rebuild after code changes
docker compose up -d --build

# Remove all data (fresh start)
docker compose down -v

# Check service status
docker compose ps
```

---

## Option 3: Docker Compose Production (Single Server)

**Best for:** Production deployment on a single server or VPS.

### Architecture
```
Single Server:
  • Traefik - Reverse proxy with Let's Encrypt SSL
  • PostgreSQL - Production database
  • Orchestrator - Backend API
  • Frontend - Production build (nginx)
  • User Containers - Dynamically created
```

### Prerequisites
- Linux server (Ubuntu 22.04+ recommended)
- Docker and Docker Compose installed
- Domain name pointing to server IP
- Cloudflare account (optional, for DNS and DDoS protection)

### Setup Steps

1. **Configure domain DNS**
   ```
   A record: studio-demo.tesslate.com → YOUR_SERVER_IP
   ```

2. **Configure environment**
   ```bash
   cp .env.example .env
   cp docker-compose.prod.yml docker-compose.yml
   ```

   Edit `.env`:
   ```env
   SECRET_KEY=generate-strong-random-key-here
   POSTGRES_PASSWORD=generate-strong-db-password
   OPENAI_API_KEY=your-openai-api-key
   CF_DNS_API_TOKEN=your-cloudflare-token  # If using Cloudflare
   ```

3. **Deploy**
   ```bash
   # Start services
   docker compose -f docker-compose.prod.yml up -d

   # Check logs
   docker compose -f docker-compose.prod.yml logs -f
   ```

4. **Configure wildcard DNS** (for user dev containers)

   **Option A: Using Cloudflare (Recommended)**
   - Add DNS record: `*.studio-demo.tesslate.com` → Your server IP
   - Enable Cloudflare proxy (orange cloud)
   - SSL is handled automatically by Cloudflare

   **Option B: Using Let's Encrypt**
   - Traefik automatically obtains wildcard SSL certificates
   - Certificates stored in `traefik/acme.json`
   - Requires DNS challenge configuration

5. **Update environment configuration**
   ```bash
   # In .env file
   DEV_SERVER_BASE_URL=https://studio-demo.tesslate.com
   ```

6. **Access the application**
   - Frontend: https://studio-demo.tesslate.com
   - User Projects: https://user{id}-project{id}.studio-demo.tesslate.com

### Advantages ✅
- Simple deployment (single server)
- Automatic SSL certificates
- Lower cost than managed Kubernetes
- Easy to backup and restore

### Disadvantages ❌
- No auto-scaling
- Single point of failure
- Manual server management required
- Resource limits of single server

### Production Checklist
- [ ] Strong `SECRET_KEY` generated
- [ ] Strong `POSTGRES_PASSWORD` set
- [ ] Regular database backups configured
- [ ] Traefik dashboard secured or disabled
- [ ] Firewall configured (ports 80, 443, 22 only)
- [ ] Monitoring setup (logs, metrics)
- [ ] SSL certificates auto-renewing
- [ ] **Wildcard DNS configured**: `*.yourdomain.com` → server IP
- [ ] **Cloudflare or Let's Encrypt wildcard SSL** configured
- [ ] `DEV_SERVER_BASE_URL` set to production domain (e.g., `https://studio-demo.tesslate.com`)

---

## Option 4: Kubernetes Production (Scalable)

**Best for:** Production deployment with high availability, auto-scaling, and multi-region support.

### Architecture
```
Kubernetes Cluster (DigitalOcean):
  • NGINX Ingress Controller - L7 load balancing with SSL
  • PostgreSQL - Database (managed or in-cluster)
  • Orchestrator Deployment - Backend API (scalable)
  • Frontend Deployment - Production build (scalable)
  • User Deployments - Dynamically created (isolated namespaces)
  • Persistent Volume - Shared storage with subPath isolation
```

### Prerequisites
- Kubernetes cluster (DigitalOcean, AWS EKS, GCP GKE, or self-hosted)
- kubectl configured
- Container registry (DigitalOcean Container Registry or Docker Hub)
- Domain name with wildcard DNS

### Setup Steps

See detailed guides:
- [Full Deployment Guide](k8s/README.md)
- [DigitalOcean Kubernetes](k8s/docs/KUBERNETES_DEPLOYMENT_GUIDE.md)
- [K3s Lightweight Setup](k8s/docs/K3S_DEPLOYMENT_GUIDE.md)

**Quick Deploy (DigitalOcean):**

1. **Configure secrets**
   ```bash
   cd k8s
   cp .env.example .env
   # Edit .env and add DOCR_TOKEN from https://cloud.digitalocean.com/account/api/tokens

   cd manifests/security
   cp app-secrets.yaml.example app-secrets.yaml
   # Edit app-secrets.yaml with your values
   ```

2. **Deploy all resources**
   ```bash
   cd k8s
   ./scripts/deployment/deploy-all.sh
   ```

3. **Verify deployment**
   ```bash
   kubectl get all -n tesslate
   kubectl get all -n tesslate-user-environments
   kubectl get ingress -n tesslate
   ```

4. **Access the application**
   - Frontend: https://studio-test.tesslate.com
   - Backend API: https://studio-test.tesslate.com/api
   - User Projects: https://user{id}-project{id}.studio-test.tesslate.com

### Advantages ✅
- Auto-scaling (horizontal pod autoscaling)
- High availability (multi-replica deployments)
- Self-healing (automatic pod restarts)
- Rolling updates (zero-downtime deployments)
- Resource isolation (per-user limits)
- Professional monitoring and logging

### Disadvantages ❌
- Complex initial setup
- Higher cost (managed Kubernetes)
- Steeper learning curve
- Requires Kubernetes expertise

### Kubernetes Commands
```bash
# View all resources
kubectl get all -n tesslate

# Check pod logs
kubectl logs -f deployment/tesslate-backend -n tesslate

# Check user environments
kubectl get pods -n tesslate-user-environments

# Restart deployment
kubectl rollout restart deployment/tesslate-backend -n tesslate

# Scale deployment
kubectl scale deployment/tesslate-backend --replicas=3 -n tesslate

# View ingress
kubectl get ingress -n tesslate -o wide
```

---

## 🔧 Configuration Reference

### Environment Variables by Deployment Mode

#### Docker Mode (Local Development)
```env
# orchestrator/.env
DEPLOYMENT_MODE=docker
DATABASE_URL=sqlite+aiosqlite:///./builder.db
SECRET_KEY=your-secret-key
OPENAI_API_KEY=your-openai-api-key

# Dev Container URL Configuration (optional)
# Leave empty for local development (uses .localhost domains)
# DEV_SERVER_BASE_URL=
```

#### Docker Mode (Production with Wildcard DNS)
```env
# .env (for production Docker deployment)
DEPLOYMENT_MODE=docker
DATABASE_URL=postgresql+asyncpg://user:pass@postgres:5432/tesslate
SECRET_KEY=strong-random-key
OPENAI_API_KEY=your-openai-api-key

# REQUIRED: Set to your production domain
DEV_SERVER_BASE_URL=https://studio-demo.tesslate.com

# CORS configuration
CORS_ORIGINS=https://studio-demo.tesslate.com,https://*.studio-demo.tesslate.com
ALLOWED_HOSTS=studio-demo.tesslate.com,*.studio-demo.tesslate.com
```

#### Kubernetes Mode (Production)
```env
# k8s/manifests/security/app-secrets.yaml
DEPLOYMENT_MODE=kubernetes
DATABASE_URL=postgresql+asyncpg://user:pass@postgres:5432/tesslate
SECRET_KEY=strong-random-key
OPENAI_API_KEY=your-openai-api-key

# This setting is ignored in Kubernetes mode (always uses hostname routing)
# DEV_SERVER_BASE_URL=https://studio-test.tesslate.com
```

### Network Ports

| Service | Local Port | Docker Port | Production |
|---------|-----------|-------------|------------|
| Frontend | 5173 | 5173 | 80/443 (Ingress) |
| Orchestrator | 8000 | 8000 | 80/443 (Ingress) |
| AI Service | 8001 | 8001 | 8001 (Internal) |
| Traefik Dashboard | - | 8080 | N/A |
| PostgreSQL | - | 5432 | 5432 (Internal) |
| User Dev Containers | - | 5173 | 80/443 (Ingress) |

---

## 🐛 Troubleshooting

### Docker Mode Issues

**Problem:** "Docker daemon is not running"
```bash
# Solution: Start Docker Desktop
# Windows: Start Docker Desktop application
# Linux: sudo systemctl start docker
```

**Problem:** "Network tesslate-network not found"
```bash
# Solution: Create the network
docker network create tesslate-network
```

**Problem:** User containers not accessible
```bash
# Check Traefik is running
docker ps | grep traefik

# Check container logs
docker logs builder-dev-user1-project5

# Check Traefik dashboard
# Open http://localhost:8080 and verify routes

# Verify hostname resolution
# Local dev: http://user1-project5.localhost should work automatically
# Production: Verify DNS is configured correctly
nslookup user1-project5.yourdomain.com
```

**Problem:** "Failed to connect" or CORS errors in production
```bash
# Check DEV_SERVER_BASE_URL is set correctly
# In .env or orchestrator/.env:
echo $DEV_SERVER_BASE_URL  # Should show https://yourdomain.com

# Verify wildcard DNS is configured
nslookup user1-project5.yourdomain.com  # Should resolve to your server IP

# Check CORS configuration includes wildcard
# CORS_ORIGINS should include: https://yourdomain.com,https://*.yourdomain.com

# Verify Cloudflare proxy is enabled (orange cloud)
# Or that Let's Encrypt wildcard certificate is installed
```

**Problem:** Port already in use
```bash
# Find process using port (Windows)
netstat -ano | findstr :8000

# Find process using port (Linux/Mac)
lsof -i :8000

# Kill the process or change port in .env
```

### Kubernetes Mode Issues

**Problem:** Pods not starting
```bash
# Check pod status
kubectl get pods -n tesslate

# Check pod events
kubectl describe pod <pod-name> -n tesslate

# Check pod logs
kubectl logs <pod-name> -n tesslate
```

**Problem:** Ingress not routing
```bash
# Check ingress configuration
kubectl get ingress -n tesslate -o yaml

# Check NGINX Ingress Controller logs
kubectl logs -n ingress-nginx -l app.kubernetes.io/component=controller

# Verify DNS
nslookup studio-test.tesslate.com
```

**Problem:** Image pull errors
```bash
# Verify registry secret
kubectl get secret docr-secret -n tesslate

# Recreate registry secret
./k8s/scripts/deployment/setup-registry-auth.sh
```

### General Issues

**Problem:** Database connection errors
```bash
# Docker mode: Check database file exists
ls orchestrator/builder.db

# K8s mode: Check PostgreSQL pod
kubectl get pods -n tesslate | grep postgres
kubectl logs postgres-0 -n tesslate
```

**Problem:** Authentication errors
```bash
# Verify SECRET_KEY is set
# Docker mode: Check orchestrator/.env
# K8s mode: kubectl get secret tesslate-app-secrets -n tesslate -o yaml
```

---

## 📊 Comparison Matrix

| Feature | Hybrid | Full Docker | Docker Prod | Kubernetes |
|---------|--------|-------------|-------------|------------|
| Setup Complexity | Medium | Low | Medium | High |
| Hot Reload Speed | ⚡ Fast | 🐢 Slow | N/A | N/A |
| Resource Usage | Low | Medium | Medium | High |
| Scalability | None | None | Limited | Excellent |
| Production Ready | ❌ No | ❌ No | ✅ Yes | ✅ Yes |
| SSL/HTTPS | ❌ No | ❌ No | ✅ Yes | ✅ Yes |
| Auto-Scaling | ❌ No | ❌ No | ❌ No | ✅ Yes |
| High Availability | ❌ No | ❌ No | ❌ No | ✅ Yes |
| Cost | Free | Free | $ | $$$ |
| Best For | Development | Testing | Small prod | Enterprise |

---

## 🚀 Next Steps

After deployment:

1. **Create admin user**
   ```bash
   # Local/Docker mode
   cd orchestrator
   uv run python -m app.create_admin

   # K8s mode
   kubectl exec -it deployment/tesslate-backend -n tesslate -- python -m app.create_admin
   ```

2. **Test the system**
   - Register a user
   - Create a project
   - Test code generation
   - Verify preview works

3. **Configure monitoring** (Production only)
   - Setup log aggregation
   - Configure alerts
   - Setup backup automation

4. **Security hardening** (Production only)
   - Review firewall rules
   - Enable rate limiting
   - Setup WAF (Web Application Firewall)
   - Regular security updates

---

## 📖 Additional Resources

- [Main README](README.md) - Project overview
- [Orchestrator Documentation](orchestrator/README.md) - Backend API
- [Frontend Documentation](app/README.md) - React application
- [Kubernetes Guide](k8s/README.md) - Detailed K8s deployment
- [Contributing Guide](CONTRIBUTING.md) - Development guidelines

---

## 💡 Tips

### Development Best Practices
- Use **Hybrid mode** for active development
- Use **Full Docker** for testing deployment configurations
- Always test locally before deploying to production
- Keep `.env` files out of version control

### Production Best Practices
- Use **Kubernetes** for production workloads
- Enable database backups (automated)
- Use managed services when possible (PostgreSQL, Redis)
- Monitor resource usage and set alerts
- Implement proper logging and tracing
- Use staging environment for testing

### Cost Optimization
- **Development**: Use hybrid mode (no cloud costs)
- **Small projects**: Docker Compose on VPS ($5-20/month)
- **Growing projects**: Managed Kubernetes ($50-200/month)
- **Enterprise**: Multi-region K8s with autoscaling
