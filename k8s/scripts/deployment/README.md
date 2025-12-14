# Tesslate Studio Deployment Scripts

This directory contains scripts for deploying Tesslate Studio to Kubernetes using DigitalOcean Container Registry.

## 🚀 Quick Start

For complete deployment:

```bash
cd k8s/scripts/deployment
# 1. Setup registry authentication and build images
DOCR_TOKEN=<your_token> ./deploy-all.sh

# OR run step by step:
DOCR_TOKEN=<your_token> ./01-setup-registry-auth.sh
DOCR_TOKEN=<your_token> ./02-build-push-images.sh
./03-setup-app-secrets.sh
./04-deploy-application.sh
```

## 📋 Active Scripts

### 1. `01-setup-registry-auth.sh`
Creates Kubernetes secret for DigitalOcean Container Registry authentication.

**What it does:**
- Creates `docr-secret` in tesslate namespace
- Configures authentication for image pulls from DOCR

### 2. `02-build-push-images.sh`
Builds and pushes your application images to DigitalOcean Container Registry.

**What it does:**
- Builds backend (orchestrator) and frontend Docker images
- Logs into DigitalOcean Container Registry
- Tags and pushes images to `registry.digitalocean.com/tesslate-container-registry-nyc3/`
- Creates production-ready images:
  - `tesslate-backend:latest` (FastAPI orchestrator)
  - `test:production` (Production frontend with nginx)

### 3. `03-setup-app-secrets.sh`
Creates all required Kubernetes application secrets.

**What it does:**
- Generates secure JWT secret key and database password
- Prompts for OpenAI API key (required)
- Prompts for Anthropic API key (optional)
- Creates application secrets in Kubernetes

### 4. `04-deploy-application.sh`
Deploys the complete Tesslate Studio application.

**What it does:**
- Deploys PostgreSQL database
- Deploys backend and frontend services
- Configures ingress routing
- Shows access URLs

### 5. `deploy-all.sh`
Runs all deployment steps in sequence (recommended approach).

### 6. `cleanup.sh`
Removes all deployed resources (for cleanup/reset).

## 📂 Archived Scripts

The following scripts were used for the old local registry setup and have been moved to `k8s/manifests/archived/local-registry/scripts/`:
- `01-setup-registry.sh` (Local registry setup)
- `02-build-push-images.sh` (Local registry build script)

## 📝 Prerequisites

Before running these scripts, ensure you have:

1. **DigitalOcean Kubernetes cluster** running
2. **kubectl configured** with cluster access:
   ```bash
   export KUBECONFIG=~/.kube/configs/digitalocean.yaml
   ```
3. **Docker installed** and running locally
4. **DigitalOcean Container Registry access**:
   - DOCR token configured: `DOCR_TOKEN=<your_token>`
   - Registry: `registry.digitalocean.com/tesslate-container-registry-nyc3/`
5. **API keys** for AI services (OpenAI, Anthropic)

## 🔧 Usage Examples

### Complete deployment:
```bash
# Build and push images
DOCR_TOKEN=<your_token> ./02-build-push-docr.sh

# Deploy application
./03-create-secrets.sh
./04-deploy-application.sh
```

### Step-by-step deployment:
```bash
# 1. Setup registry authentication
DOCR_TOKEN=<your_token> ./01-setup-registry-auth.sh

# 2. Build and push to DigitalOcean registry
DOCR_TOKEN=<your_token> ./02-build-push-images.sh

# 3. Create Kubernetes application secrets
./03-setup-app-secrets.sh

# 4. Deploy application
./04-deploy-application.sh
```

### Check deployment status:
```bash
kubectl get pods,svc,ingress -n tesslate
```

### Clean up everything:
```bash
./cleanup.sh
```

## 🌐 Access Your Application

After deployment, your application will be accessible via:

- **Production URL**: http://134.199.242.35
- **Frontend**: Load Balancer IP (check ingress)
- **Backend API**: Load Balancer IP + `/api`

Get the Load Balancer IP:
```bash
kubectl get ingress -n tesslate
# or check service:
kubectl get svc -n ingress-nginx ingress-nginx-controller
```

## 🔍 Troubleshooting

**Images not pushing to DOCR:**
- Verify DOCR token is correct: `echo $DOCR_TOKEN`
- Check registry login: `docker login registry.digitalocean.com`

**Pods not starting:**
- Check secrets exist: `kubectl get secrets -n tesslate`
- Check image pull: `kubectl describe pod <pod-name> -n tesslate`
- Verify image exists in DOCR: `doctl registry repository list-tags <repository>`

**Load Balancer pending:**
- DigitalOcean LB takes 2-3 minutes to provision
- Check status: `kubectl get ingress -n tesslate`

**Frontend white screen:**
- Check if using production image: `registry.digitalocean.com/tesslate-container-registry-nyc3/tesslate-frontend:latest`
- Verify service port configuration matches container port

## 🔒 Security Features

### DigitalOcean Container Registry Security
- **Private Registry**: Images stored securely in DigitalOcean private registry
- **Token-based Access**: DOCR token for push/pull authentication
- **HTTPS**: All registry communication encrypted via HTTPS

### Application Security
- **Kubernetes Secrets**: API keys and database passwords stored securely
- **Image Pull Secrets**: DOCR authentication configured in cluster
- **Production Images**: Nginx-based frontend serving static assets securely

### Security Commands
```bash
# Check DOCR secret
kubectl get secret docr-secret -n tesslate -o yaml

# Check application secrets
kubectl get secrets -n tesslate

# Verify image pull access
kubectl describe pod <pod-name> -n tesslate
```