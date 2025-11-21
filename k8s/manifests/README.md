# Kubernetes Manifests

This directory contains all Kubernetes manifest files for Tesslate Studio, organized by function.

## Quick Deployment

```bash
cd k8s/scripts/deployment
./deploy-all.sh
```

## Directory Structure

```
manifests/
├── archived/           # Deprecated configs (k3s, local dev, local registry)
├── base/               # Namespace and network policies
├── core/               # Core application components
├── database/           # PostgreSQL database
├── ingress/            # NGINX ingress configuration
├── secrets/            # S3/Spaces credentials documentation
├── security/           # Secrets, RBAC, resource quotas
├── storage/            # Dynamic storage class
├── user-environments/  # User development environment namespace
└── README.md           # This file
```

### `archived/` - Deprecated Configurations

Old configurations no longer used in production:
- `examples/` - Example secret templates
- `k3s-local/` - K3s local deployment configs
- `local-dev/` - Local development scripts
- `local-registry/` - Local Docker registry setup

### `base/` - Base Infrastructure

- `namespaces.yaml` - Main namespace definition (`tesslate`)
- `network-policies.yaml` - Core networking policies

### `core/` - Core Application

Main application services in the `tesslate` namespace:

| File | Description |
|------|-------------|
| `backend-deployment.yaml` | FastAPI backend (2 replicas) |
| `backend-service.yaml` | Backend service on port 8005 |
| `backend-configmap.yaml` | Backend configuration |
| `frontend-deployment.yaml` | React frontend with nginx (2 replicas) |
| `frontend-service.yaml` | Frontend service on port 80 |
| `main-ingress.yaml` | NGINX ingress + SSL certificates |
| `clusterissuer.yaml` | Let's Encrypt certificate issuer |
| `cleanup-cronjob.yaml` | CronJob to cleanup idle user environments |

### `database/` - PostgreSQL

| File | Description |
|------|-------------|
| `postgres-deployment.yaml` | PostgreSQL 15-alpine deployment |
| `postgres-service.yaml` | Database service on port 5432 |
| `postgres-pvc.yaml` | 20Gi persistent volume claim |
| `postgres-secret.yaml` | Database credentials |
| `postgres-secret.yaml.example` | Secret template |

### `ingress/` - Ingress Configuration

- `nginx-enable-snippets.yaml` - NGINX ingress controller config

### `secrets/` - S3 Storage Documentation

- `README.md` - S3/Spaces credential setup guide
- `s3-credentials.yaml.template` - S3 credentials template

### `security/` - Security & RBAC

| File | Description |
|------|-------------|
| `app-secrets.yaml` | Application secrets (JWT, API keys, DB URL) |
| `app-secrets.yaml.example` | Secrets template |
| `app-resource-quotas.yaml` | Resource quotas for tesslate namespace |
| `dev-environments-rbac.yaml` | RBAC for user development environments |
| `project-namespace-rbac.yaml` | RBAC for project namespaces |
| `letsencrypt-issuer.yaml` | Let's Encrypt issuer config |
| `s3-credentials.yaml.example` | S3/Spaces credentials template |

### `storage/` - Storage Classes

- `dynamic-storage-class.yaml` - DigitalOcean Block Storage provisioner

### `user-environments/` - User Dev Environments

Separate namespace (`tesslate-user-environments`) for user containers:

| File | Description |
|------|-------------|
| `namespace.yaml` | Namespace definition |
| `resourcequota.yaml` | Limits: 50 pods, 20 CPU, 40GB RAM |
| `limitrange.yaml` | Per-pod limits: 256Mi-512Mi memory |
| `networkpolicy.yaml` | Network isolation policies |
| `projects-pvc.yaml` | Shared PVC for project files |

User environments are created dynamically by the backend with:
- Unique deployments, services, and ingresses per project
- Subdomain routing: `{project-slug}.{domain}`
- Automatic cleanup via CronJob (every 30 minutes)

## Production Configuration

| Setting | Value |
|---------|-------|
| **Cluster** | DigitalOcean Managed Kubernetes (NYC2) |
| **Registry** | registry.digitalocean.com/tesslate-container-registry-nyc3/ |
| **Primary Namespace** | tesslate |
| **User Environments** | tesslate-user-environments |
| **Ingress** | NGINX Ingress Controller |
| **SSL** | Let's Encrypt via cert-manager |
| **Storage** | DigitalOcean Block Storage |

### Current Images

- **Backend**: `registry.digitalocean.com/tesslate-container-registry-nyc3/tesslate-backend:latest`
- **Frontend**: `registry.digitalocean.com/tesslate-container-registry-nyc3/tesslate-frontend:latest`
- **Database**: `postgres:15-alpine`

### Persistent Storage

| PVC | Size | Purpose |
|-----|------|---------|
| `postgres-pvc` | 20Gi | PostgreSQL data |
| `tesslate-projects-pvc` | 5Gi | User project files |

## Prerequisites

Before deploying:

1. DigitalOcean Kubernetes cluster configured
2. `kubectl` configured with cluster access
3. DigitalOcean Container Registry credentials
4. Required secrets created (see deployment scripts)

## Deployment

Use the automated deployment scripts:

```bash
cd k8s/scripts/deployment
./deploy-all.sh
```

Or deploy manifests manually:

```bash
# Create namespaces
kubectl apply -f base/

# Deploy database
kubectl apply -f database/postgres-secret.yaml
kubectl apply -f database/

# Deploy security
kubectl apply -f security/

# Deploy storage
kubectl apply -f storage/

# Deploy application
kubectl apply -f core/

# Setup user environments
kubectl apply -f user-environments/
```

## Cluster Status

```bash
# View all resources
kubectl get all -n tesslate

# Check deployments
kubectl get deployments -n tesslate -o wide

# Check ingress
kubectl get ingress -n tesslate

# Recent events
kubectl get events -n tesslate --sort-by='.lastTimestamp' | tail -20

# Check user environments
kubectl get pods -n tesslate-user-environments
kubectl get resourcequota -n tesslate-user-environments

# View logs
kubectl logs -f deployment/tesslate-backend -n tesslate
kubectl logs -f deployment/tesslate-frontend -n tesslate
```

## Updating Deployments

```bash
# Build and push new images
cd k8s/scripts/deployment
./build-push-images.sh

# Rolling update (automatic with imagePullPolicy: Always)
kubectl rollout restart deployment/tesslate-backend -n tesslate
kubectl rollout restart deployment/tesslate-frontend -n tesslate

# Check rollout status
kubectl rollout status deployment/tesslate-backend -n tesslate
kubectl rollout status deployment/tesslate-frontend -n tesslate
```
