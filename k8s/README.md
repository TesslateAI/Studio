# Tesslate Studio Kubernetes Deployment

This directory contains all Kubernetes manifests and scripts for deploying Tesslate Studio to DigitalOcean Managed Kubernetes (DOKS).

## Directory Structure

```
k8s/
├── manifests/
│   ├── archived/           # Archived configs (k3s, local dev, local registry)
│   ├── base/               # Namespace and network policies
│   ├── core/               # Application deployments (backend, frontend, ingress)
│   ├── database/           # PostgreSQL deployment
│   ├── ingress/            # NGINX ingress configuration
│   ├── secrets/            # S3/Spaces credentials docs
│   ├── security/           # App secrets, RBAC, resource quotas
│   ├── storage/            # Dynamic storage class
│   └── user-environments/  # User dev environment namespace config
├── scripts/
│   ├── deployment/         # Production deployment scripts
│   ├── local-deployment/   # Local/self-hosted deployment scripts
│   ├── testing/            # Testing and validation scripts
│   ├── generate-secrets.sh # Secret generation script (Linux/macOS)
│   └── generate-secrets.bat # Secret generation script (Windows)
├── .env                    # DOCR token (not committed)
├── .env.example            # Environment template
└── README.md               # This file
```

## Quick Start (DigitalOcean)

### Prerequisites

- DigitalOcean account with Kubernetes cluster
- `doctl` and `kubectl` CLI tools installed
- Docker installed locally

### 1. Connect to Cluster

```bash
# Authenticate with DigitalOcean
doctl auth init

# Connect to cluster
doctl kubernetes cluster kubeconfig save tesslate-studio-nyc2

# Verify connection
kubectl get nodes
```

### 2. Configure Environment

```bash
cd k8s

# Copy environment template
cp .env.example .env

# Edit .env and add your DOCR token
# Get token from: https://cloud.digitalocean.com/account/api/tokens
```

### 3. Generate Secrets

```bash
# Linux/macOS
./scripts/generate-secrets.sh

# Windows
scripts\generate-secrets.bat
```

### 4. Deploy

```bash
cd scripts/deployment
./deploy-all.sh
```

This will:
1. Install NGINX Ingress Controller
2. Install cert-manager for SSL
3. Setup registry authentication
4. Build and push Docker images
5. Deploy PostgreSQL, backend, and frontend

## Production Configuration

| Setting | Value |
|---------|-------|
| **Cluster** | tesslate-studio-nyc2 (DigitalOcean NYC2) |
| **Registry** | registry.digitalocean.com/tesslate-container-registry-nyc3/ |
| **Namespace** | tesslate |
| **User Environments** | tesslate-user-environments |
| **Domain** | Configurable via APP_DOMAIN secret |

### Current Deployments

- **Backend**: 2 replicas, FastAPI on port 8000
- **Frontend**: 2 replicas, nginx serving React on port 80
- **PostgreSQL**: 1 replica on port 5432

### Storage

- **postgres-pvc**: 20Gi for PostgreSQL data
- **tesslate-projects-pvc**: 5Gi for user projects (DO Block Storage)

## Deployment Scripts

### Production (DigitalOcean)

```bash
cd k8s/scripts/deployment

./deploy-all.sh              # Full deployment
./build-push-images.sh       # Build and push images
./deploy-application.sh      # Deploy manifests only
./deploy-user-namespace.sh   # Setup user environments
./install-prerequisites.sh   # Install ingress + cert-manager
./setup-registry-auth.sh     # Configure DOCR authentication
./verify-deployment.sh       # Verify deployment status
./cleanup.sh                 # Remove all resources
```

### Local/Self-Hosted (k3s/kubeadm)

```bash
cd k8s/scripts/local-deployment

./setup-all.sh               # Full local setup
./k3s-setup-all.sh          # k3s-specific setup
./build-images.sh           # Build images locally
./deploy-tesslate.sh        # Deploy to local cluster
./manage-tesslate.sh        # Management utilities
```

## Common Commands

### View Status

```bash
# All resources
kubectl get all -n tesslate

# Pods with status
kubectl get pods -n tesslate -w

# Ingress and load balancer
kubectl get ingress -n tesslate
kubectl get svc -n ingress-nginx

# SSL certificates
kubectl get certificates -n tesslate
```

### View Logs

```bash
kubectl logs -f deployment/tesslate-backend -n tesslate
kubectl logs -f deployment/tesslate-frontend -n tesslate
kubectl logs deployment/postgres -n tesslate
```

### Restart Deployments

```bash
kubectl rollout restart deployment/tesslate-backend -n tesslate
kubectl rollout restart deployment/tesslate-frontend -n tesslate
```

### Scale

```bash
kubectl scale deployment tesslate-backend --replicas=3 -n tesslate
kubectl scale deployment tesslate-frontend --replicas=3 -n tesslate
```

### Database Operations

```bash
# Connect to PostgreSQL
kubectl exec -it deployment/postgres -n tesslate -- psql -U tesslate_user -d tesslate

# Backup
kubectl exec -n tesslate deployment/postgres -- \
  pg_dump -U tesslate_user tesslate > backup-$(date +%Y%m%d).sql
```

### Debug

```bash
# Describe pod for issues
kubectl describe pod <pod-name> -n tesslate

# Recent events
kubectl get events -n tesslate --sort-by='.lastTimestamp'

# Shell into pod
kubectl exec -it deployment/tesslate-backend -n tesslate -- /bin/bash
```

## Troubleshooting

### Pods Not Starting

```bash
kubectl describe pod <pod-name> -n tesslate
kubectl logs <pod-name> -n tesslate
```

### Image Pull Errors

```bash
# Recreate registry secret
cd k8s/scripts/deployment
./setup-registry-auth.sh
```

### Certificate Issues

```bash
kubectl describe certificate tesslate-domain-cert -n tesslate
kubectl logs -n cert-manager deployment/cert-manager
```

### Database Connection Failed

```bash
# Check postgres logs
kubectl logs deployment/postgres -n tesslate

# Verify secrets match
kubectl get secret postgres-secret -n tesslate -o yaml
kubectl get secret tesslate-app-secrets -n tesslate -o yaml | grep DATABASE_URL
```

## Architecture

### Namespaces

- **tesslate**: Main application (backend, frontend, database)
- **tesslate-user-environments**: Dynamic user development containers

### User Environments

User development environments are created dynamically by the backend:
- Unique deployments, services, and ingresses per user/project
- Subdomain routing: `{project-slug}.{domain}`
- Automatic cleanup via CronJob (every 30 minutes for idle environments)
- Resource quotas: 50 pods max, 20 CPU / 40GB RAM limits

### Ingress

- NGINX Ingress Controller with DigitalOcean Load Balancer
- SSL/TLS via Let's Encrypt (cert-manager)
- Wildcard certificate for user environments

## Documentation

- [DIGITALOCEAN_QUICKSTART.md](DIGITALOCEAN_QUICKSTART.md) - Fast deployment guide
- [DIGITALOCEAN_DEPLOYMENT_CHECKLIST.md](DIGITALOCEAN_DEPLOYMENT_CHECKLIST.md) - Detailed checklist
- [CLOUDFLARE_SETUP.md](CLOUDFLARE_SETUP.md) - Cloudflare DNS/SSL setup
- [DEPLOYMENT_SUMMARY.md](DEPLOYMENT_SUMMARY.md) - Deployment overview
- [scripts/deployment/README.md](scripts/deployment/README.md) - Script documentation
