# Tesslate Studio Infrastructure Documentation

This directory contains comprehensive documentation for Tesslate Studio's infrastructure, covering deployment modes, container orchestration, and cloud provisioning.

## Overview

Tesslate Studio supports two deployment modes:

1. **Docker Compose** (Local Development)
   - Traefik for routing (`*.localhost`)
   - Local PostgreSQL database
   - Direct filesystem access for projects
   - Fast iteration with live reloading

2. **Kubernetes** (Production)
   - Per-project namespace isolation
   - S3 Sandwich pattern for hibernation
   - NGINX Ingress with TLS
   - Network policies for security
   - Resource quotas and RBAC

## Directory Structure

```
infrastructure/
├── README.md                    # This file
├── CLAUDE.md                    # Agent context for infrastructure work
├── kubernetes/                  # Kubernetes configuration
│   ├── README.md
│   ├── CLAUDE.md
│   ├── base/                    # Base manifests
│   │   ├── README.md
│   │   └── CLAUDE.md
│   ├── overlays/                # Environment-specific configs
│   │   ├── README.md
│   │   ├── CLAUDE.md
│   │   ├── minikube.md          # Local development
│   │   └── aws.md               # AWS EKS production
│   ├── rbac.md                  # RBAC configuration
│   ├── network-policies.md      # Network security
│   └── s3-sandwich.md           # Hibernation pattern
├── docker/                      # Docker configuration
│   ├── README.md
│   ├── CLAUDE.md
│   ├── docker-compose.md        # Local development
│   └── dockerfiles.md           # Image definitions
└── terraform/                   # Infrastructure as Code
    ├── README.md
    ├── CLAUDE.md
    ├── eks.md                   # EKS cluster
    ├── ecr.md                   # Container registry
    └── s3.md                    # Project storage
```

## Key Concepts

### Deployment Modes

**Docker Mode** (`DEPLOYMENT_MODE=docker`)
- Used for local development on developer machines
- Projects run in Docker containers on `tesslate-network`
- Traefik routes `{container}.localhost` to containers
- Projects stored at `./orchestrator/users/{user_id}/projects/{slug}/`

**Kubernetes Mode** (`DEPLOYMENT_MODE=kubernetes`)
- Used for Minikube local testing and AWS EKS production
- Each project gets isolated namespace: `proj-{uuid}`
- Projects stored in S3 with ephemeral PVC caching (S3 Sandwich)
- NGINX Ingress routes `{container}.{project}.{domain}` to services

### S3 Sandwich Pattern

Kubernetes deployments use an ephemeral storage pattern:

1. **Hydration** (Init Container): Download project from S3 to PVC on startup
2. **Runtime**: Fast local I/O on block storage
3. **Dehydration** (PreStop Hook): Upload project back to S3 before shutdown
4. **Cleanup** (CronJob): Hibernate idle environments after timeout

This provides:
- Fast local I/O during development
- Persistent storage in S3
- Cost savings by deleting idle PVCs
- Quick restoration when user returns

### Network Isolation

Production Kubernetes uses namespace-per-project with NetworkPolicies:

- **Default Deny**: All ingress blocked by default in project namespaces
- **Explicit Allow**: Only NGINX Ingress can reach project containers
- **Platform Isolation**: User projects cannot reach `tesslate` namespace
- **Internet Access**: Projects can reach external APIs (npm, pip, etc.)

### Image Registry

**Minikube**: Uses local images loaded via `minikube image load`
- Images: `tesslate-backend:latest`, `tesslate-frontend:latest`, `tesslate-devserver:latest`
- Pull policy: `Never` (always use local image)

**AWS EKS**: Uses Amazon ECR
- Registry: `<AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com`
- Images: `{registry}/tesslate-{backend,frontend,devserver}:latest`
- Pull policy: `Always` (always check for updates)

## Quick Start

### Local Development (Docker)

```bash
# Start all services
docker-compose up -d

# Access frontend
http://localhost

# Access backend API
http://localhost/api

# User projects
http://{container}.localhost
```

### Local Testing (Minikube)

```bash
# Start cluster
minikube start -p tesslate --driver=docker

# Build and load images
docker build -t tesslate-backend:latest -f orchestrator/Dockerfile orchestrator/
minikube -p tesslate image load tesslate-backend:latest

# Deploy
kubectl apply -k k8s/overlays/minikube

# Access (requires tunnel or port-forward)
minikube -p tesslate tunnel
```

### Production (AWS EKS)

```bash
# Login to ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com

# Build and push
docker build --no-cache -t tesslate-backend:latest -f orchestrator/Dockerfile orchestrator/
docker tag tesslate-backend:latest <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend:latest
docker push <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend:latest

# Deploy
kubectl apply -k k8s/overlays/aws

# Force pod restart
kubectl delete pod -n tesslate -l app=tesslate-backend
```

## Container Images

### tesslate-backend
**File**: `orchestrator/Dockerfile`
**Purpose**: FastAPI orchestrator that manages projects, containers, and AI agents
**Base**: `python:3.11-slim`
**Key Dependencies**: Docker CLI (for Docker mode), uvicorn, SQLAlchemy, Kubernetes client

### tesslate-frontend
**File**: `app/Dockerfile.prod`
**Purpose**: React frontend served via NGINX
**Base**: `node:20-alpine` (build), `nginx:alpine` (runtime)
**Build**: Vite builds static assets, NGINX serves with SPA routing

### tesslate-devserver
**File**: `orchestrator/Dockerfile.devserver`
**Purpose**: User project development environment
**Base**: `node:20-alpine`
**Included**: Node.js 20, Python 3, Go, git, npm/pip/go tools
**Pre-installed**: Vite, React, TypeScript, ESLint, Tailwind (from template)

## Infrastructure Components

### Core Services (Kubernetes `tesslate` namespace)

- **tesslate-backend**: Orchestrator API (Port 8000)
- **tesslate-frontend**: React UI (Port 80)
- **postgres**: PostgreSQL database (Port 5432)
- **dev-environment-cleanup**: CronJob for hibernation (every 2 minutes)

### User Project Namespace (`proj-{uuid}`)

Each user project gets:
- **Namespace**: Isolated network and resources
- **PVC**: Ephemeral block storage (5Gi gp3)
- **Deployment**: Dev server container(s)
- **Service**: ClusterIP for internal routing
- **Ingress**: HTTPS routing via NGINX
- **NetworkPolicy**: Allow ingress from NGINX only

### Ingress Routing

**Platform** (`tesslate` namespace):
```
https://your-domain.com/      → tesslate-frontend-service:80
https://your-domain.com/api/* → tesslate-backend-service:8000
```

**User Projects** (`proj-*` namespaces):
```
https://{container}.{project-slug}.your-domain.com → {container}-service:3000
```

Example:
```
https://frontend.my-app-k3x8n2.your-domain.com → frontend-service:3000 (in proj-{uuid})
```

## Configuration

### Environment Variables (Backend)

**Core**:
- `DEPLOYMENT_MODE`: `docker` or `kubernetes`
- `DATABASE_URL`: PostgreSQL connection string
- `SECRET_KEY`: JWT signing key

**Kubernetes**:
- `K8S_DEVSERVER_IMAGE`: User container image
- `K8S_STORAGE_CLASS`: PVC storage class
- `K8S_INGRESS_DOMAIN`: Base domain for projects
- `K8S_NAMESPACE_PER_PROJECT`: `true` for isolation

**S3 Storage**:
- `S3_BUCKET_NAME`: Bucket for project storage
- `S3_ENDPOINT_URL`: S3 endpoint (empty for AWS, MinIO URL for local)
- `S3_REGION`: AWS region

**Security**:
- `COOKIE_SECURE`: `true` for HTTPS
- `COOKIE_DOMAIN`: `.your-domain.com` for subdomains
- `CORS_ORIGINS`: Allowed frontend origins

### Secrets

**Minikube**: Secrets in `k8s/overlays/minikube/secrets/` (gitignored)
- `postgres-secret.yaml`: Database credentials
- `s3-credentials.yaml`: MinIO credentials
- `app-secrets.yaml`: API keys, OAuth secrets

**AWS EKS**: Secrets created via kubectl (not in git)
```bash
kubectl create secret generic tesslate-secrets -n tesslate \
  --from-literal=SECRET_KEY=xxx \
  --from-literal=DATABASE_URL=xxx \
  --from-literal=LITELLM_API_BASE=xxx \
  --from-literal=LITELLM_MASTER_KEY=xxx
```

## Troubleshooting

### Minikube Issues

**Image not updating after rebuild**:
```bash
# Delete from minikube first
minikube -p tesslate ssh -- docker rmi -f tesslate-backend:latest
# Then rebuild and load
docker build --no-cache -t tesslate-backend:latest -f orchestrator/Dockerfile orchestrator/
minikube -p tesslate image load tesslate-backend:latest
kubectl delete pod -n tesslate -l app=tesslate-backend
```

**Tunnel not working**:
```bash
# Use port-forward instead
kubectl port-forward -n tesslate svc/tesslate-frontend-service 5000:80
kubectl port-forward -n tesslate svc/tesslate-backend-service 8000:8000
```

### AWS EKS Issues

**User container ImagePullBackOff**:
```bash
# Check image configuration
kubectl describe pod -n proj-{uuid} | grep Image
# Should be: <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-devserver:latest
```

**503 error on user project**:
```bash
# Check pod status
kubectl get pods -n proj-{uuid}
# Check logs
kubectl logs -n proj-{uuid} {pod-name} -c dev-server
kubectl logs -n proj-{uuid} {pod-name} -c hydrate-project
```

**NGINX Ingress not routing**:
```bash
# Restart ingress controller after backend changes
kubectl rollout restart deployment/ingress-nginx-controller -n ingress-nginx
```

## Related Documentation

- **[kubernetes/README.md](kubernetes/README.md)**: Detailed Kubernetes configuration
- **[docker/README.md](docker/README.md)**: Docker Compose setup
- **[terraform/README.md](terraform/README.md)**: Infrastructure provisioning
- **[../deployment/README.md](../deployment/README.md)**: Deployment procedures
- **[../architecture/README.md](../architecture/README.md)**: System architecture

## References

- Kubernetes Manifests: `c:/Users/Smirk/Downloads/Tesslate-Studio/k8s/`
- Docker Compose: `c:/Users/Smirk/Downloads/Tesslate-Studio/docker-compose.yml`
- Terraform: `c:/Users/Smirk/Downloads/Tesslate-Studio/k8s/terraform/aws/`
- Backend Config: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/config.py`
