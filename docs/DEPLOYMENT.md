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
   - Uses Traefik reverse proxy with subdomain routing
   - Routing: `{project-slug}.studio.localhost` (e.g., `my-app-k3x8n2.studio.localhost`)
   - Storage: Volume mounts to `users/{user_id}/{project_id}/`
   - **Browser Requirement:** Chrome or Firefox recommended (auto-resolve `*.localhost`)

2. **Kubernetes Mode** (`DEPLOYMENT_MODE=kubernetes`)
   - User dev environments run as Kubernetes Pods/Deployments
   - Uses NGINX Ingress Controller with subdomain routing
   - Routing: `{project-slug}.studio-test.tesslate.com` (e.g., `my-app-k3x8n2.studio-test.tesslate.com`)
   - Storage: Shared PVC with subPath isolation

### Why Traefik is Required in Docker Mode

Even if you run main services natively (orchestrator, frontend), **Traefik must run in Docker** because:

```
┌──────────────────────────────────────────────────────────────┐
│ Native Services (on host)                                    │
│  • Orchestrator: localhost:8000 (includes built-in AI)       │
│  • Frontend: localhost:5173                                  │
└──────────────────────────────────────────────────────────────┘
                           │
                           │ Creates user containers
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ Docker Network: tesslate-network                             │
│                                                               │
│  ┌──────────────┐    ┌──────────────────────────────────────┐  │
│  │   Traefik    │───▶│  User Dev Containers (dynamic)       │  │
│  │  (required)  │    │  • my-app-k3x8n2.studio.localhost   │  │
│  └──────────────┘    │  • blog-cms-h7y2k1.studio.localhost │  │
│                      │  • todo-app-m9p3x5.studio.localhost │  │
│                      └──────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

**Why?**
- Multiple user projects need isolated containers
- Each needs unique subdomain routing (e.g., `my-app-k3x8n2.studio.localhost`)
- Can't all bind to port 5173 simultaneously
- Traefik provides automatic service discovery and zero-port-conflict subdomain routing
- **Note:** Chrome and Firefox auto-resolve `*.localhost` subdomains to 127.0.0.1

---

## 📚 Deployment Options

## Option 1: Hybrid Mode (Native + Traefik) - Recommended for Development

**Best for:** Fast iteration with hot reload on main services while supporting user containers.

### Architecture
```
Host Machine:
  • Orchestrator (Python/FastAPI) - Native process on port 8000 (includes built-in AI)
  • Frontend (React/Vite) - Native process on port 5173

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
   DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/tesslate
   DEPLOYMENT_MODE=docker
   LITELLM_MASTER_KEY=your-litellm-master-key
   LITELLM_API_BASE=http://localhost:4000/v1
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

   # 3. Start frontend
   cd app && npm run dev
   ```

3. **Access the application**
   - Frontend: http://localhost:5173
   - Orchestrator API: http://localhost:8000
   - Traefik Dashboard: http://localhost:8080
   - User Projects: http://{project-slug}.studio.localhost (subdomain routing)

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
  • Orchestrator - Backend API (includes built-in AI)
  • Frontend - React dev server
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
   LITELLM_MASTER_KEY=your-litellm-master-key
   LITELLM_API_BASE=http://localhost:4000/v1
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
   - User Projects: http://{project-slug}.studio.localhost (subdomain routing)

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
  • Traefik - Reverse proxy with Let's Encrypt SSL (via Cloudflare DNS challenge)
  • PostgreSQL - Production database
  • Orchestrator - Backend API
  • Frontend - Production build (nginx)
  • User Containers - Dynamically created with subdomain routing
```

### Prerequisites
- Linux server (Ubuntu 22.04+ recommended)
- Docker and Docker Compose installed
- Domain name (e.g., `studio-demo.tesslate.com`)
- Cloudflare account (required for wildcard SSL and subdomain routing)
- Server accessible on ports 80 and 443

### Architecture Explanation

This setup uses **subdomain-based routing** for user dev environments:
- Main app: `studio-demo.tesslate.com`
- User projects: `{project-slug}.studio-demo.tesslate.com` (e.g., `my-app-k3x8n2.studio-demo.tesslate.com`)

**Why Cloudflare DNS Challenge?**
- Supports wildcard SSL certificates (`*.studio-demo.tesslate.com`)
- No need to expose port 80 for ACME HTTP challenge
- Works behind firewalls and load balancers
- Automatic certificate renewal

---

### Setup Steps

#### 1. Cloudflare Configuration

**A. Add Your Domain to Cloudflare**

1. Log in to [Cloudflare Dashboard](https://dash.cloudflare.com/)
2. Click "Add a Site" and enter your domain (e.g., `tesslate.com`)
3. Follow the setup wizard to change your nameservers at your domain registrar
4. Wait for DNS propagation (can take up to 24 hours)

**B. Configure DNS Records**

In Cloudflare Dashboard → DNS → Records:

```
Type    Name                   Content          Proxy Status    TTL
─────────────────────────────────────────────────────────────────────
A       studio-demo            YOUR_SERVER_IP   DNS only        Auto
A       *.studio-demo          YOUR_SERVER_IP   DNS only        Auto
```

**Important Settings:**
- **Proxy Status**: Must be "DNS only" (gray cloud icon)
  - Orange cloud (proxied) breaks Traefik's Let's Encrypt DNS challenge
  - Turn off proxy after clicking the cloud icon
- **Wildcard Record**: The `*.studio-demo` record enables all subdomains to route to your server
- Replace `YOUR_SERVER_IP` with your server's public IP address

**C. Create Cloudflare API Token**

This token allows Traefik to create DNS TXT records for Let's Encrypt DNS challenge.

1. Go to [Cloudflare API Tokens](https://dash.cloudflare.com/profile/api-tokens)
2. Click "Create Token"
3. Use the "Edit zone DNS" template
4. Configure permissions:
   ```
   Permissions:
     Zone - DNS - Edit
     Zone - Zone - Read

   Zone Resources:
     Include - Specific zone - tesslate.com (or your domain)
   ```
5. Click "Continue to summary" → "Create Token"
6. **Copy the token immediately** (shown only once)
7. Save it securely for the next step

**D. Verify Cloudflare SSL/TLS Settings**

In Cloudflare Dashboard → SSL/TLS:

1. **SSL/TLS encryption mode**: Set to "Full (strict)"
   - This ensures end-to-end encryption
   - Requires valid SSL certificate on your server (Traefik will handle this)

2. **Edge Certificates**: Enable "Always Use HTTPS"

---

#### 2. Server Preparation

**A. Install Docker and Docker Compose**

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Add your user to docker group (optional)
sudo usermod -aG docker $USER
newgrp docker

# Install Docker Compose
sudo apt install docker-compose-plugin -y

# Verify installation
docker --version
docker compose version
```

**B. Configure Firewall**

```bash
# Allow SSH, HTTP, and HTTPS
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status
```

**C. Clone Repository**

```bash
cd /opt
sudo git clone https://github.com/TesslateAI/Studio.git
cd Studio
```

---

#### 3. Configure Environment

**A. Copy and Edit Environment File**

```bash
cp .env.example .env
nano .env
```

**B. Update Required Variables**

```env
# ============================================================================
# Production Configuration
# ============================================================================

# ----------------------------------------------------------------------------
# Required: Security Keys
# ----------------------------------------------------------------------------
SECRET_KEY=<generate-strong-random-key-here>
POSTGRES_PASSWORD=<generate-strong-db-password>

# Generate SECRET_KEY:
# python -c "import secrets; print(secrets.token_urlsafe(32))"

# ----------------------------------------------------------------------------
# Required: Domain Configuration
# ----------------------------------------------------------------------------
APP_DOMAIN=studio-demo.tesslate.com
APP_PROTOCOL=https
APP_PORT=80
APP_SECURE_PORT=443

# Base URL (automatically constructed)
APP_BASE_URL=${APP_PROTOCOL}://${APP_DOMAIN}

# CORS and Security
CORS_ORIGINS=${APP_BASE_URL}
ALLOWED_HOSTS=${APP_DOMAIN}

# ----------------------------------------------------------------------------
# Required: Cloudflare API Token
# ----------------------------------------------------------------------------
CF_DNS_API_TOKEN=<your-cloudflare-api-token-from-step-1c>

# ----------------------------------------------------------------------------
# Required: LiteLLM Configuration
# ----------------------------------------------------------------------------
LITELLM_API_BASE=https://your-litellm-proxy.com/v1
LITELLM_MASTER_KEY=<your-litellm-master-key>
LITELLM_DEFAULT_MODELS=gpt-5o-mini,gpt-3.5-turbo
LITELLM_TEAM_ID=default
LITELLM_EMAIL_DOMAIN=tesslate.com
LITELLM_INITIAL_BUDGET=10.0

# ----------------------------------------------------------------------------
# Optional: Traefik Dashboard Security
# ----------------------------------------------------------------------------
# Generate with: htpasswd -nb admin your-strong-password
# Default: admin:admin (CHANGE THIS!)
TRAEFIK_BASIC_AUTH=admin:$$2y$$10$$EIHbchqg0sjZLr9iZINqA.6Za7wPjGAVdTER2ob5whDLtHkkZSGbC

# ----------------------------------------------------------------------------
# Database Configuration
# ----------------------------------------------------------------------------
DATABASE_URL=postgresql+asyncpg://tesslate_user:${POSTGRES_PASSWORD}@postgres:5432/tesslate
POSTGRES_DB=tesslate
POSTGRES_USER=tesslate_user
# POSTGRES_PASSWORD already set above

# ----------------------------------------------------------------------------
# Deployment Mode
# ----------------------------------------------------------------------------
DEPLOYMENT_MODE=docker
```

**C. Configure Traefik Email for SSL Certificates**

Edit `traefik/traefik.prod.yml`:

```bash
nano traefik/traefik.prod.yml
```

Update the email address:
```yaml
certificatesResolvers:
  cloudflare:
    acme:
      email: admin@yourdomain.com  # Change this to your email
      storage: /etc/traefik/acme.json
      dnsChallenge:
        provider: cloudflare
        resolvers:
          - "1.1.1.1:53"
          - "8.8.8.8:53"
```

**D. Set Correct Permissions for acme.json**

```bash
chmod 600 traefik/acme.json
```

---

#### 4. Deploy Application

**A. Build and Start Services**

```bash
# Start all services
docker compose -f docker-compose.prod.yml up -d

# Check status
docker compose -f docker-compose.prod.yml ps

# View logs
docker compose -f docker-compose.prod.yml logs -f
```

**B. Monitor SSL Certificate Generation**

Watch Traefik logs for Let's Encrypt certificate generation:

```bash
docker compose -f docker-compose.prod.yml logs -f traefik
```

Look for:
```
time="..." level=info msg="Certificates obtained for domains [studio-demo.tesslate.com *.studio-demo.tesslate.com]"
```

This may take 1-2 minutes. Traefik will:
1. Request certificate from Let's Encrypt
2. Create DNS TXT record via Cloudflare API
3. Validate domain ownership
4. Download and store certificate in `traefik/acme.json`

**C. Verify Services are Running**

```bash
# Check all containers
docker ps

# Expected containers:
# - tesslate-traefik
# - tesslate-orchestrator
# - tesslate-app
# - tesslate-postgres

# Check health
docker compose -f docker-compose.prod.yml ps
```

---

#### 5. Create Admin User

```bash
# Enter orchestrator container
docker exec -it tesslate-orchestrator bash

# Create admin user
python -m app.create_admin

# Follow prompts to set email and password
# Exit container
exit
```

---

#### 6. Access and Verify

**A. Access the Application**
- Frontend: https://studio-demo.tesslate.com
- Traefik Dashboard: https://studio-demo.tesslate.com/traefik (requires basic auth)

**B. Test User Project Subdomain Routing**
1. Log in to the application
2. Create a new project
3. Access project preview at: `https://{project-slug}.studio-demo.tesslate.com`
   - Example: `https://my-app-k3x8n2.studio-demo.tesslate.com`

**C. Verify SSL Certificate**

```bash
# Check certificate details
echo | openssl s_client -connect studio-demo.tesslate.com:443 -servername studio-demo.tesslate.com 2>/dev/null | openssl x509 -noout -text

# Should show:
# - Issuer: Let's Encrypt
# - Subject Alternative Names: studio-demo.tesslate.com, *.studio-demo.tesslate.com
# - Valid for 90 days
```

---

#### 7. SSL Certificate Auto-Renewal

Traefik automatically renews Let's Encrypt certificates 30 days before expiration.

**Verify Auto-Renewal Configuration:**

Check `traefik/traefik.prod.yml`:
```yaml
certificatesResolvers:
  cloudflare:
    acme:
      email: admin@yourdomain.com
      storage: /etc/traefik/acme.json  # Persisted via volume mount
      dnsChallenge:
        provider: cloudflare
```

**Monitor Renewal:**
```bash
# Check certificate expiration
docker compose -f docker-compose.prod.yml logs traefik | grep -i "renew"

# View acme.json (certificates stored here)
cat traefik/acme.json | jq
```

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

**Security:**
- [ ] Strong `SECRET_KEY` generated (use `python -c "import secrets; print(secrets.token_urlsafe(32))"`)
- [ ] Strong `POSTGRES_PASSWORD` set (use `openssl rand -base64 32`)
- [ ] `TRAEFIK_BASIC_AUTH` changed from default (use `htpasswd -nb admin your-password`)
- [ ] Cloudflare API token permissions limited to specific zone
- [ ] Firewall configured (ports 80, 443, 22 only)
- [ ] SSH key-based authentication enabled (disable password auth)
- [ ] Regular security updates configured (`unattended-upgrades`)

**SSL/TLS:**
- [ ] Cloudflare DNS records set to "DNS only" (gray cloud)
- [ ] Wildcard DNS record configured (`*.studio-demo`)
- [ ] Cloudflare SSL/TLS mode set to "Full (strict)"
- [ ] Traefik email configured in `traefik/traefik.prod.yml`
- [ ] SSL certificates auto-renewing (check `acme.json` is persisted)
- [ ] Certificate expiration monitored

**Backup and Recovery:**
- [ ] Database backups automated (see [Database Backup Guide](#database-backup-guide))
- [ ] User project files backed up (`/opt/tesslate-studio/users/`)
- [ ] `.env` file backed up securely (contains secrets)
- [ ] `traefik/acme.json` backed up (contains SSL certificates)
- [ ] Backup restoration tested

**Monitoring:**
- [ ] Log aggregation configured (see [Logging Setup](#logging-setup))
- [ ] Disk space alerts configured
- [ ] Container health monitoring enabled
- [ ] Certificate expiration alerts configured
- [ ] Error rate monitoring configured

**Documentation:**
- [ ] Server access credentials documented
- [ ] Cloudflare account credentials documented
- [ ] Database credentials stored in password manager
- [ ] Disaster recovery plan documented
- [ ] On-call procedures documented

---

### Database Backup Guide

**Setup Automated Backups:**

```bash
# Create backup directory
sudo mkdir -p /opt/backups/tesslate-db

# Create backup script
sudo nano /opt/backups/backup-tesslate-db.sh
```

Add the following script:
```bash
#!/bin/bash
BACKUP_DIR="/opt/backups/tesslate-db"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/tesslate_backup_$TIMESTAMP.sql.gz"
POSTGRES_PASSWORD="your-postgres-password"  # Use same as .env

# Create backup
docker exec tesslate-postgres pg_dump -U tesslate_user tesslate | gzip > "$BACKUP_FILE"

# Keep only last 30 days of backups
find "$BACKUP_DIR" -name "tesslate_backup_*.sql.gz" -mtime +30 -delete

echo "Backup completed: $BACKUP_FILE"
```

Make executable and configure cron:
```bash
sudo chmod +x /opt/backups/backup-tesslate-db.sh

# Add to crontab (daily at 2 AM)
sudo crontab -e

# Add this line:
0 2 * * * /opt/backups/backup-tesslate-db.sh >> /var/log/tesslate-backup.log 2>&1
```

**Restore from Backup:**
```bash
# Stop application
cd /opt/tesslate-studio
docker compose -f docker-compose.prod.yml down

# Restore database
gunzip < /opt/backups/tesslate-db/tesslate_backup_20250124_020000.sql.gz | \
  docker exec -i tesslate-postgres psql -U tesslate_user tesslate

# Start application
docker compose -f docker-compose.prod.yml up -d
```

---

### Logging Setup

**Configure Log Rotation:**

Create `/etc/logrotate.d/tesslate`:
```
/var/lib/docker/containers/*/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}
```

**View Logs:**
```bash
# All services
docker compose -f docker-compose.prod.yml logs -f

# Specific service
docker compose -f docker-compose.prod.yml logs -f orchestrator
docker compose -f docker-compose.prod.yml logs -f traefik

# Last 100 lines
docker compose -f docker-compose.prod.yml logs --tail=100

# Filter by time
docker compose -f docker-compose.prod.yml logs --since="2025-01-24T10:00:00"

# Export logs
docker compose -f docker-compose.prod.yml logs > tesslate-logs-$(date +%Y%m%d).log
```

---

### Maintenance Tasks

**Weekly:**
```bash
# Check disk space
df -h

# Check Docker resource usage
docker system df

# Review logs for errors
docker compose -f docker-compose.prod.yml logs --since="7d" | grep -i error

# Check certificate expiration
docker compose -f docker-compose.prod.yml logs traefik | grep -i "certificate"
```

**Monthly:**
```bash
# Update system packages
sudo apt update && sudo apt upgrade -y

# Clean up unused Docker resources
docker system prune -a --volumes -f

# Verify backups
ls -lh /opt/backups/tesslate-db/

# Test backup restoration (on staging environment)
```

**Quarterly:**
```bash
# Review security updates
sudo apt list --upgradable

# Audit user access logs
docker compose -f docker-compose.prod.yml exec orchestrator python -m app.audit_logs

# Review Cloudflare firewall rules
# Visit: https://dash.cloudflare.com/

# Update dependencies
cd /opt/tesslate-studio
git pull
docker compose -f docker-compose.prod.yml build --no-cache
docker compose -f docker-compose.prod.yml up -d
```

---

### Scaling and Performance

**Increase Orchestrator Replicas:**

This is not directly supported in Docker Compose. For scaling, migrate to [Kubernetes deployment](#option-4-kubernetes-production-scalable).

**Optimize PostgreSQL:**

Edit `docker-compose.prod.yml` and add to postgres service:
```yaml
postgres:
  # ... existing config ...
  command:
    - "postgres"
    - "-c"
    - "max_connections=200"
    - "-c"
    - "shared_buffers=256MB"
    - "-c"
    - "effective_cache_size=1GB"
    - "-c"
    - "work_mem=16MB"
```

Restart:
```bash
docker compose -f docker-compose.prod.yml restart postgres
```

**Monitor Performance:**
```bash
# Check container stats
docker stats

# Check database connections
docker exec tesslate-postgres psql -U tesslate_user tesslate -c "SELECT count(*) FROM pg_stat_activity;"

# Check slow queries
docker exec tesslate-postgres psql -U tesslate_user tesslate -c "SELECT query, calls, mean_exec_time FROM pg_stat_statements ORDER BY mean_exec_time DESC LIMIT 10;"
```

---

### Upgrading to New Versions

**Standard Update Process:**

```bash
cd /opt/tesslate-studio

# Backup current state
docker compose -f docker-compose.prod.yml exec postgres pg_dump -U tesslate_user tesslate > backup_before_upgrade.sql
cp .env .env.backup

# Pull latest code
git fetch
git checkout main
git pull origin main

# Check for breaking changes
git log --oneline

# Rebuild images
docker compose -f docker-compose.prod.yml build --no-cache

# Restart services (brief downtime)
docker compose -f docker-compose.prod.yml down
docker compose -f docker-compose.prod.yml up -d

# Verify services
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f

# Test application
curl -I https://studio-demo.tesslate.com
```

**Rollback Procedure:**

```bash
# Stop services
docker compose -f docker-compose.prod.yml down

# Restore previous version
git checkout <previous-commit-hash>

# Restore environment
cp .env.backup .env

# Restore database (if needed)
cat backup_before_upgrade.sql | docker exec -i tesslate-postgres psql -U tesslate_user tesslate

# Rebuild and start
docker compose -f docker-compose.prod.yml build --no-cache
docker compose -f docker-compose.prod.yml up -d
```

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
   - User Projects: https://{project-slug}.studio-test.tesslate.com (subdomain routing)

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
DATABASE_URL=postgresql+asyncpg://user:password@postgres:5432/tesslate
SECRET_KEY=your-secret-key
LITELLM_MASTER_KEY=your-litellm-master-key
LITELLM_API_BASE=http://localhost:4000/v1
```

#### Kubernetes Mode (Production)
```env
# k8s/manifests/security/app-secrets.yaml
DEPLOYMENT_MODE=kubernetes
DATABASE_URL=postgresql+asyncpg://user:pass@postgres:5432/tesslate
SECRET_KEY=strong-random-key
DEV_SERVER_BASE_URL=https://studio-test.tesslate.com
LITELLM_MASTER_KEY=your-litellm-master-key
LITELLM_API_BASE=https://your-litellm-proxy.com/v1
```

### Network Ports

| Service | Local Port | Docker Port | Production |
|---------|-----------|-------------|------------|
| Frontend | 5173 | 5173 | 80/443 (Ingress) |
| Orchestrator | 8000 | 8000 | 80/443 (Ingress) |
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

**Problem:** User containers not accessible or subdomain not resolving
```bash
# Solution 1: Use Chrome or Firefox
# These browsers auto-resolve *.localhost subdomains to 127.0.0.1
# Other browsers may require DNS configuration

# Solution 2: Check Traefik is running
docker ps | grep traefik

# Solution 3: Check container logs
docker logs tesslate-{project-slug}

# Solution 4: Check Traefik dashboard
# Open http://localhost:8080 and verify Host() rules for subdomains

# Solution 5: Test with curl using Host header
curl -H "Host: test.studio.localhost" http://localhost/
```

**Problem:** Port already in use
```bash
# Find process using port (Windows)
netstat -ano | findstr :8000

# Find process using port (Linux/Mac)
lsof -i :8000

# Kill the process or change port in .env
```

---

### Production Docker / Cloudflare Issues

**Problem:** SSL certificate not generating / "Unable to obtain certificate"

**Symptoms:**
```
time="..." level=error msg="Unable to obtain ACME certificate for domains..."
time="..." level=error msg="Cloudflare API error"
```

**Solutions:**

1. **Verify Cloudflare API Token**
   ```bash
   # Test API token with curl
   curl -X GET "https://api.cloudflare.com/client/v4/user/tokens/verify" \
     -H "Authorization: Bearer YOUR_CF_DNS_API_TOKEN" \
     -H "Content-Type: application/json"

   # Should return: "status": "active"
   ```

2. **Check Token Permissions**
   - Go to [Cloudflare API Tokens](https://dash.cloudflare.com/profile/api-tokens)
   - Find your token and click "Edit"
   - Verify permissions:
     - `Zone - DNS - Edit`
     - `Zone - Zone - Read`
   - Verify zone resources include your domain

3. **Verify DNS Records**
   ```bash
   # Check DNS propagation
   nslookup studio-demo.tesslate.com
   nslookup subdomain.studio-demo.tesslate.com

   # Should resolve to your server IP
   ```

4. **Check Proxy Status in Cloudflare**
   - DNS records must be "DNS only" (gray cloud icon)
   - Orange cloud (proxied) breaks DNS challenge
   - Turn off proxy in Cloudflare Dashboard → DNS

5. **Verify Environment Variable**
   ```bash
   # Check if CF_DNS_API_TOKEN is set correctly
   docker compose -f docker-compose.prod.yml exec traefik env | grep CLOUDFLARE

   # Should show: CLOUDFLARE_DNS_API_TOKEN=your-token
   ```

6. **Check Traefik Configuration**
   ```bash
   # Verify traefik.prod.yml has correct provider
   cat traefik/traefik.prod.yml | grep -A 5 "dnsChallenge"

   # Should show:
   #   dnsChallenge:
   #     provider: cloudflare
   ```

7. **Check acme.json Permissions**
   ```bash
   ls -la traefik/acme.json
   # Should be: -rw------- (600 permissions)

   # Fix if needed:
   chmod 600 traefik/acme.json
   ```

8. **Clear Certificate Cache and Retry**
   ```bash
   # Stop services
   docker compose -f docker-compose.prod.yml down

   # Clear certificate storage
   echo '{}' > traefik/acme.json
   chmod 600 traefik/acme.json

   # Restart and watch logs
   docker compose -f docker-compose.prod.yml up -d
   docker compose -f docker-compose.prod.yml logs -f traefik
   ```

---

**Problem:** "Site can't be reached" / DNS not resolving

**Solutions:**

1. **Check DNS Propagation**
   ```bash
   # Check if DNS has propagated globally
   dig studio-demo.tesslate.com @1.1.1.1
   dig studio-demo.tesslate.com @8.8.8.8

   # Or use online tools:
   # https://www.whatsmydns.net/
   ```

2. **Verify Cloudflare Nameservers**
   ```bash
   # Check if domain is using Cloudflare nameservers
   dig NS tesslate.com

   # Should return Cloudflare nameservers (e.g., bob.ns.cloudflare.com)
   ```

3. **Check Firewall**
   ```bash
   # Verify ports are open
   sudo ufw status

   # Should show:
   # 80/tcp    ALLOW
   # 443/tcp   ALLOW
   ```

4. **Test Direct IP Access**
   ```bash
   # Test if server is accessible directly
   curl -I http://YOUR_SERVER_IP

   # If this works but domain doesn't, it's a DNS issue
   ```

---

**Problem:** Wildcard subdomain routing not working for user projects

**Symptoms:**
- Main app (studio-demo.tesslate.com) works
- User projects (my-app-k3x8n2.studio-demo.tesslate.com) show "404 Not Found"

**Solutions:**

1. **Verify Wildcard DNS Record in Cloudflare**
   ```bash
   # Test wildcard subdomain resolves
   nslookup random-subdomain.studio-demo.tesslate.com

   # Should resolve to your server IP
   ```

2. **Check Cloudflare DNS Records**
   - Must have: `A *.studio-demo YOUR_SERVER_IP` (DNS only)
   - If missing, add it in Cloudflare Dashboard → DNS

3. **Verify Wildcard SSL Certificate**
   ```bash
   # Check if Traefik obtained wildcard cert
   docker compose -f docker-compose.prod.yml logs traefik | grep -i "studio-demo"

   # Should see: "*.studio-demo.tesslate.com"
   ```

4. **Check Traefik Dashboard**
   - Open: https://studio-demo.tesslate.com/traefik
   - Check "HTTP Routers" section
   - Look for user container routers with subdomain rules

5. **Verify User Container Labels**
   ```bash
   # Check labels on user containers
   docker inspect tesslate-user1-project1 | grep -A 10 "Labels"

   # Should include Traefik labels with subdomain Host() rules
   ```

---

**Problem:** "SSL_ERROR_BAD_CERT_DOMAIN" or certificate warnings

**Solutions:**

1. **Check Certificate Domains**
   ```bash
   # View certificate details
   echo | openssl s_client -connect studio-demo.tesslate.com:443 -servername studio-demo.tesslate.com 2>/dev/null | openssl x509 -noout -text | grep -A 2 "Subject Alternative Name"

   # Should include:
   # DNS:studio-demo.tesslate.com
   # DNS:*.studio-demo.tesslate.com
   ```

2. **Verify Cloudflare SSL/TLS Mode**
   - Go to Cloudflare Dashboard → SSL/TLS
   - Must be "Full (strict)" mode
   - If set to "Flexible", change to "Full (strict)"

3. **Check Docker Compose TLS Configuration**
   ```bash
   # Verify labels in docker-compose.prod.yml
   grep -A 3 "tls.domains" docker-compose.prod.yml

   # Should show:
   # - "traefik.http.routers.app.tls.domains[0].main=${APP_DOMAIN}"
   # - "traefik.http.routers.app.tls.domains[0].sans=*.${APP_DOMAIN}"
   ```

4. **Force Certificate Regeneration**
   ```bash
   docker compose -f docker-compose.prod.yml down
   rm traefik/acme.json
   touch traefik/acme.json
   chmod 600 traefik/acme.json
   docker compose -f docker-compose.prod.yml up -d
   ```

---

**Problem:** Let's Encrypt rate limits hit

**Symptoms:**
```
time="..." level=error msg="too many certificates already issued for exact set of domains"
```

**Solutions:**

1. **Use Staging Server for Testing**

   Edit `traefik/traefik.prod.yml`:
   ```yaml
   certificatesResolvers:
     cloudflare:
       acme:
         caServer: https://acme-staging-v02.api.letsencrypt.org/directory  # Add this line
         email: admin@yourdomain.com
         storage: /etc/traefik/acme.json
         dnsChallenge:
           provider: cloudflare
   ```

2. **Wait for Rate Limit Reset**
   - Let's Encrypt limits: 50 certificates per registered domain per week
   - Wait 7 days or use staging server

3. **Check Current Rate Limits**
   - Visit: https://crt.sh/?q=%.studio-demo.tesslate.com
   - Shows all certificates issued for your domain

---

**Problem:** Traefik dashboard not accessible

**Solutions:**

1. **Verify Dashboard is Enabled**
   ```bash
   # Check traefik.prod.yml
   grep -A 2 "api:" traefik/traefik.prod.yml

   # Should show:
   # api:
   #   dashboard: true
   ```

2. **Check Basic Auth Credentials**
   ```bash
   # Generate new credentials
   htpasswd -nb admin your-new-password

   # Add to .env as TRAEFIK_BASIC_AUTH
   # Remember to escape $ as $$
   ```

3. **Test Basic Auth**
   ```bash
   curl -u admin:your-password https://studio-demo.tesslate.com/traefik/

   # Should return HTML, not 401 Unauthorized
   ```

4. **Check Docker Labels**
   ```bash
   docker inspect tesslate-traefik | grep -A 20 "Labels"

   # Should include dashboard router labels
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
# Docker mode: Check PostgreSQL connection
docker compose ps postgres
docker compose logs postgres

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
