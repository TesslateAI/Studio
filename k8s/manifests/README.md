# Kubernetes Manifests

This directory contains all Kubernetes manifest files for the Tesslate Studio application, organized by function.

## 🚀 Quick Deployment

```bash
cd k8s/scripts/deployment
./deploy-all.sh
```

## 📂 Directory Structure

```
manifests/
├── archived/           # Archived configurations (K3s, local dev, old configs)
├── base/               # Base infrastructure (namespace, network policies)
├── core/               # Core application components
├── database/           # PostgreSQL database
├── monitoring/         # Monitoring configurations (empty/future use)
├── rbac/               # RBAC for backend service account
├── security/           # Secrets, resource quotas, Let's Encrypt
├── storage/            # Persistent volume claims
├── user-environments/  # User development environment namespace
└── README.md           # This file
```

### `archived/` - Archived Configurations
Contains old/deprecated configurations:
- K3s local deployment configs
- Local development manifests
- Example configurations
- Previous architecture versions

### `base/` - Base Infrastructure
- `namespaces.yaml`: Main namespace definition (`tesslate`)
- `network-policies.yaml`: Core networking policies

### `core/` - Core Application
Main application services that run in the `tesslate` namespace:
- **Backend**: `backend-deployment.yaml`, `backend-service.yaml`, `backend-configmap.yaml`
- **Frontend**: `frontend-deployment.yaml`, `frontend-service.yaml`
- **Ingress**: `main-ingress.yaml` (NGINX ingress with SSL)
- **Automation**: `cleanup-cronjob.yaml` (cleanup idle user environments)
- **RBAC**: `rbac.yaml` (service account permissions)
- **SSL**: `clusterissuer.yaml` (Let's Encrypt certificate issuer)

### `database/` - PostgreSQL Database
PostgreSQL database components with persistent storage:
- `postgres-deployment.yaml`: PostgreSQL 15-alpine deployment
- `postgres-service.yaml`: Database service
- `postgres-pvc.yaml`: 20Gi persistent volume claim
- `postgres-secret.yaml`: Database credentials

### `monitoring/` - Monitoring (Future)
Reserved for monitoring stack (Prometheus, Grafana, etc.)

### `rbac/` - Backend Service RBAC
RBAC configuration for backend service to manage user environments:
- `backend-role.yaml`: Role with permissions to manage deployments, services, ingresses
- `backend-rolebinding.yaml`: Binding for tesslate-backend service account

### `security/` - Security & Secrets
- `app-secrets.yaml`: Application secrets (JWT, API keys, DB credentials)
- `app-resource-quotas.yaml`: Resource quotas for tesslate namespace
- `dev-environments-rbac.yaml`: RBAC for user development environments
- `letsencrypt-issuer.yaml`: Let's Encrypt certificate issuer configuration

### `storage/` - Persistent Storage
- `projects-pvc.yaml`: Shared 5Gi PVC for user projects (DigitalOcean Block Storage)

### `user-environments/` - User Development Environments
Separate namespace (`tesslate-user-environments`) for user development containers:
- `namespace.yaml`: Namespace definition
- `resourcequota.yaml`: Resource limits (50 pods max, 20 CPU requests/40 CPU limits, 40GB RAM requests/80GB RAM limits)
- `limitrange.yaml`: Default resource limits per pod (256Mi-512Mi memory, 100m-500m CPU)
- `networkpolicy.yaml`: Network isolation policies
- `projects-pvc.yaml`: Shared PVC for user project files

**Note**: User environments are created dynamically by the backend service with:
- Unique deployments, services, and ingresses per user/project
- Subdomain routing: `user{id}-project{id}.studio-test.tesslate.com`
- Automatic cleanup via CronJob (every 30 minutes for idle environments)

## 🔧 Production Configuration

**Current Setup:**
- **Cluster**: DigitalOcean Managed Kubernetes (NYC3)
- **Registry**: DigitalOcean Container Registry (`registry.digitalocean.com/finetune/`)
- **Storage**: DigitalOcean Block Storage (automatic provisioning)
- **Load Balancer**: DigitalOcean Load Balancer (134.199.242.35)
- **Production URL**: https://studio-test.tesslate.com
- **Primary Namespace**: `tesslate`
- **User Environments Namespace**: `tesslate-user-environments`

**Current Deployments:**
- **Backend**: `registry.digitalocean.com/finetune/tesslate-backend:latest` (1 replica)
- **Frontend**: `registry.digitalocean.com/finetune/test:frontend-production` (2 replicas)
- **Database**: `postgres:15-alpine` (1 replica)

**Persistent Storage:**
- `postgres-pvc`: 20Gi (Local storage for PostgreSQL)
- `tesslate-backend-templates-pvc`: 5Gi (DO Block Storage for project templates)
- `tesslate-projects-pvc`: 5Gi (DO Block Storage for user projects)

**Ingress:**
- Main ingress: `tesslate-ingress` at studio-test.tesslate.com
- NGINX Ingress Controller with SSL/TLS termination
- Wildcard certificate for user environments: `*.studio-test.tesslate.com`

## 📝 Prerequisites

Before deploying:
1. DigitalOcean Kubernetes cluster configured
2. `kubectl` configured with cluster access
3. DigitalOcean Container Registry credentials configured
4. Required secrets created (see deployment scripts)

## 🛠️ Deployment Scripts

Use the automated deployment scripts for easier setup:
```bash
cd k8s/scripts/deployment
DOCR_TOKEN=<your_token> ./deploy-all.sh
```

See `k8s/scripts/deployment/README.md` for detailed instructions.

## 📊 Cluster Status

Check current deployment status:
```bash
# View all resources
kubectl get all -n tesslate

# Check deployments and image versions
kubectl get deployments -n tesslate -o wide

# Check ingress configuration
kubectl get ingress -n tesslate

# View recent events
kubectl get events -n tesslate --sort-by='.lastTimestamp' | tail -20

# Check user environments
kubectl get pods -n tesslate-user-environments
kubectl get resourcequota -n tesslate-user-environments

# View logs
kubectl logs -f deployment/tesslate-backend -n tesslate
kubectl logs -f deployment/tesslate-frontend -n tesslate
```

## 🔄 Updating Deployments

To update to the latest images:
```bash
# Build and push new images
cd k8s/scripts/deployment
DOCR_TOKEN=<your_token> ./build-push-images.sh

# Rolling update (automatic with imagePullPolicy: Always)
kubectl rollout restart deployment/tesslate-backend -n tesslate
kubectl rollout restart deployment/tesslate-frontend -n tesslate

# Check rollout status
kubectl rollout status deployment/tesslate-backend -n tesslate
kubectl rollout status deployment/tesslate-frontend -n tesslate
```