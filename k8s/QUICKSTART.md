# Kubernetes Quickstart

Run Tesslate Studio on Kubernetes (Minikube for local dev, DigitalOcean for production).

## Local Development (Minikube)

### Prerequisites

**Windows (recommended):**
```powershell
# Install via Chocolatey
choco install minikube kubectl
```

**macOS:**
```bash
brew install minikube kubectl
```

**Linux:**
```bash
curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
sudo install minikube-linux-amd64 /usr/local/bin/minikube
```

### 1. Start Minikube

```bash
# Create cluster with profile "tesslate"
minikube start -p tesslate --driver=docker --memory=4096 --cpus=2

# Enable ingress addon
minikube -p tesslate addons enable ingress

# Verify
kubectl get nodes
```

### 2. Configure Credentials

```bash
# Copy example env and edit with your credentials
cp k8s/.env.example k8s/.env.minikube

# Edit k8s/.env.minikube with your:
# - LiteLLM API key
# - OAuth credentials (Google, GitHub)
# - Stripe keys (optional)
```

### 3. Generate Secrets

```bash
cd k8s
bash scripts/generate-secrets-from-env.sh minikube
```

### 4. Deploy MinIO (S3 Storage)

```bash
# Create MinIO namespace and credentials
kubectl create namespace minio-system
kubectl create secret generic minio-credentials \
  --from-literal=MINIO_ROOT_USER=tesslate-admin \
  --from-literal=MINIO_ROOT_PASSWORD=tesslate-secret-key-change-in-prod \
  -n minio-system

# Deploy MinIO
kubectl apply -f k8s/base/minio/minio-pvc.yaml
kubectl apply -f k8s/base/minio/minio-deployment.yaml
kubectl apply -f k8s/base/minio/minio-service.yaml
kubectl apply -f k8s/base/minio/minio-init-job.yaml

# Wait for MinIO
kubectl wait --for=condition=ready pod -l app=minio -n minio-system --timeout=120s
```

### 5. Build & Load Images

```bash
# Point Docker to Minikube's Docker daemon
eval $(minikube -p tesslate docker-env)

# Build images
docker build -t tesslate-backend:latest -f orchestrator/Dockerfile orchestrator/
docker build -t tesslate-frontend:latest -f app/Dockerfile.prod app/
docker build -t tesslate-devserver:latest -f orchestrator/Dockerfile.devserver orchestrator/

# Load into Minikube
minikube -p tesslate image load tesslate-backend:latest
minikube -p tesslate image load tesslate-frontend:latest
minikube -p tesslate image load tesslate-devserver:latest
```

### 6. Deploy Application

```bash
# Deploy everything with Kustomize
kubectl apply -k k8s/overlays/minikube

# Wait for pods
kubectl wait --for=condition=ready pod -l app=tesslate-backend -n tesslate --timeout=120s
kubectl wait --for=condition=ready pod -l app=tesslate-frontend -n tesslate --timeout=120s
```

### 7. Access the App

```bash
# Start tunnel (run in separate terminal, keep it open)
minikube -p tesslate tunnel
```

Open **http://localhost/** in your browser.

### 8. Seed Marketplace Agents

```bash
kubectl exec -n tesslate deployment/tesslate-backend -- python -c "
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from app.config import get_settings
from app.models import MarketplaceAgent

DEFAULT_AGENTS = [
    {'name': 'Stream Builder', 'slug': 'stream-builder', 'description': 'Real-time streaming code generation', 'category': 'builder', 'mode': 'stream', 'agent_type': 'StreamAgent', 'model': 'qwen-3-235b-a22b-instruct-2507', 'icon': '⚡', 'pricing_type': 'free', 'price': 0, 'source_type': 'open', 'is_forkable': True, 'requires_user_keys': False, 'is_featured': True, 'is_active': True, 'system_prompt': 'You are an expert React developer.'},
    {'name': 'Tesslate Agent', 'slug': 'tesslate-agent', 'description': 'Autonomous engineering agent', 'category': 'fullstack', 'mode': 'agent', 'agent_type': 'IterativeAgent', 'model': 'qwen-3-235b-a22b-instruct-2507', 'icon': '🤖', 'pricing_type': 'free', 'price': 0, 'source_type': 'open', 'is_forkable': True, 'requires_user_keys': False, 'is_featured': True, 'is_active': True, 'system_prompt': 'You are an autonomous software engineering agent.'},
]

async def seed():
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with AsyncSessionLocal() as db:
        for agent_data in DEFAULT_AGENTS:
            result = await db.execute(select(MarketplaceAgent).where(MarketplaceAgent.slug == agent_data['slug']))
            if not result.scalar_one_or_none():
                db.add(MarketplaceAgent(**agent_data))
                await db.commit()
                print(f'Created {agent_data[\"name\"]}')

asyncio.run(seed())
"
```

---

## Quick Reference

| Task | Command |
|------|---------|
| View pods | `kubectl get pods -n tesslate` |
| Backend logs | `kubectl logs -f deployment/tesslate-backend -n tesslate` |
| Frontend logs | `kubectl logs -f deployment/tesslate-frontend -n tesslate` |
| Shell into backend | `kubectl exec -it deployment/tesslate-backend -n tesslate -- /bin/bash` |
| Restart backend | `kubectl rollout restart deployment/tesslate-backend -n tesslate` |
| Check events | `kubectl get events -n tesslate --sort-by='.lastTimestamp'` |
| Stop cluster | `minikube -p tesslate stop` |
| Delete cluster | `minikube -p tesslate delete` |

---

## Updating Credentials

```bash
# Edit your env file
vim k8s/.env.minikube

# Regenerate secrets
bash k8s/scripts/generate-secrets-from-env.sh minikube

# Apply and restart
kubectl apply -f k8s/overlays/minikube/secrets/
kubectl rollout restart deployment/tesslate-backend -n tesslate
```

---

## Troubleshooting

**Pod not starting:**
```bash
kubectl describe pod <pod-name> -n tesslate
kubectl logs <pod-name> -n tesslate
```

**Database connection error:**
```bash
# Check postgres is running
kubectl get pods -n tesslate | grep postgres

# Check password matches
kubectl exec deployment/postgres -n tesslate -- env | grep POSTGRES_PASSWORD
```

**Image not found:**
```bash
# Verify image is loaded in Minikube
minikube -p tesslate image ls | grep tesslate

# Reload if needed
minikube -p tesslate image load tesslate-backend:latest
```

**Ingress not working:**
```bash
# Check ingress controller
kubectl get pods -n ingress-nginx

# Check ingress rules
kubectl get ingress -n tesslate
kubectl describe ingress tesslate-ingress -n tesslate
```

---

## Directory Structure

```
k8s/
├── .env.example          # Template (safe to commit)
├── .env.minikube         # Local credentials (gitignored)
├── .env.production       # Production credentials (gitignored)
├── base/                 # Kustomize base manifests
│   ├── core/            # Backend, frontend deployments
│   ├── database/        # PostgreSQL
│   ├── ingress/         # NGINX ingress rules
│   ├── minio/           # S3-compatible storage
│   └── security/        # RBAC, network policies
├── overlays/
│   └── minikube/        # Minikube-specific patches
│       ├── secrets/     # Generated secrets (gitignored)
│       └── *.yaml       # Patches for local dev
└── scripts/
    └── generate-secrets-from-env.sh
```

---

## Production (DigitalOcean)

For production deployment to DigitalOcean Kubernetes, see [CLAUDE.md](../CLAUDE.md) for cluster details and deployment commands.
