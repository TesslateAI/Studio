# Tesslate Studio Kubernetes Deployment

This directory contains the complete Kubernetes manifests and scripts for deploying Tesslate Studio using kubeadm on a single server or multi-node cluster.

## Directory Structure

```
k8s/
├── manifests/
│   ├── base/               # Core infrastructure (namespaces, storage, network policies)
│   ├── database/           # PostgreSQL deployment and configuration
│   ├── app/                # Application deployments (backend, frontend)
│   └── registry/           # Local Docker registry for container images
├── scripts/
│   ├── 01-prepare-server.sh     # Server preparation script
│   ├── 02-install-kubernetes.sh # Kubernetes installation
│   ├── 03-configure-cluster.sh  # Cluster configuration and add-ons
│   ├── 04-deploy-tesslate.sh    # Application deployment
│   ├── build-images.sh          # Docker image building
│   ├── setup-all.sh             # Complete setup orchestration
│   └── manage-tesslate.sh       # Management utilities
├── docs/
│   ├── KUBERNETES_DEPLOYMENT_GUIDE.md      # Comprehensive deployment guide
│   ├── PRODUCTION_DEPLOYMENT_STRATEGY.md   # Production deployment strategies
│   └── SERVERLESS_CONTAINER_ARCHITECTURE.md # Serverless architecture docs
├── local-dev/
│   ├── LOCAL_K8S_README.md      # Local development setup guide
│   ├── k8s-local-setup.sh       # Local k8s in Docker setup (Linux/macOS)
│   ├── k8s-local-helper.sh      # Local k8s management helper
│   ├── k8s-local-windows.ps1    # Local k8s in Docker setup (Windows)
│   ├── deploy-to-local-k8s.sh   # Deploy to local k8s (Linux/macOS)
│   └── deploy-to-local-k8s.ps1  # Deploy to local k8s (Windows)
└── README.md
```

## Quick Start (Single Server)

### Prerequisites

- Ubuntu 22.04 LTS server (or compatible)
- Minimum 2-4 CPU cores, 4-8GB RAM, 100GB SSD
- Static IP address
- Root or sudo access

### Choose Your Kubernetes Distribution

#### Option 1: k3s (Recommended for Single Server)
**Faster, lighter, easier to manage**

```bash
# Clone the repository
git clone https://github.com/TesslateAI/Studio.git
cd Studio/k8s/scripts

# Run k3s setup (much faster!)
sudo ./k3s-setup-all.sh 192.168.1.100
```

#### Option 2: Full Kubernetes with kubeadm
**More customizable, better for multi-node clusters**

```bash
# Run complete kubeadm setup
sudo ./setup-all.sh 192.168.1.100
```

This will:
1. Prepare the server (disable swap, install containerd)
2. Install Kubernetes components (kubeadm, kubelet, kubectl)
3. Initialize the cluster and install CNI
4. Install Ingress Controller and cert-manager
5. Build application Docker images
6. Deploy Tesslate Studio

### Manual Step-by-Step Installation

```bash
# Step 1: Prepare the server
sudo ./01-prepare-server.sh

# Step 2: Install Kubernetes
sudo ./02-install-kubernetes.sh <SERVER_IP>

# Step 3: Configure cluster
sudo ./03-configure-cluster.sh

# Step 4: Build Docker images
./build-images.sh

# Step 5: Deploy application
./04-deploy-tesslate.sh
```

## Configuration

### DigitalOcean Container Registry Authentication

Before deploying to production, configure your DigitalOcean Container Registry token:

```bash
# Navigate to k8s directory
cd k8s

# Copy the example file
cp .env.example .env

# Edit .env and replace YOUR_DOCR_TOKEN_HERE with your actual token
# Get your token from: https://cloud.digitalocean.com/account/api/tokens
```

The `.env` file should contain:
```
DOCR_TOKEN=your_actual_token_here
```

**Important**: The `.env` file is already in `.gitignore` and will not be committed.

### Secrets Setup

Before deploying to production, you must configure all secrets. Follow these steps:

#### Step 1: Create Secret Files

```bash
# Navigate to manifests directory
cd k8s/manifests

# Copy example files to create actual secret files
cp security/app-secrets.yaml.example security/app-secrets.yaml
cp database/postgres-secret.yaml.example database/postgres-secret.yaml

# Secure file permissions (Unix/Linux/Mac)
chmod 600 security/app-secrets.yaml
chmod 600 database/postgres-secret.yaml
```

#### Step 2: Generate Strong Passwords

Use these commands to generate cryptographically secure passwords:

```bash
# Generate 64-character secrets (for JWT, SECRET_KEY)
openssl rand -base64 64

# Generate 32-character passwords (for database)
openssl rand -base64 32
```

#### Step 3: Configure PostgreSQL Secrets

Edit `k8s/manifests/database/postgres-secret.yaml`:

```bash
# Generate passwords
POSTGRES_PASSWORD=$(openssl rand -base64 32)
POSTGRES_ROOT_PASSWORD=$(openssl rand -base64 32)

echo "POSTGRES_PASSWORD: $POSTGRES_PASSWORD"
echo "POSTGRES_ROOT_PASSWORD: $POSTGRES_ROOT_PASSWORD"
```

**Important**: Keep the generated POSTGRES_PASSWORD - you'll need it for the next step!

#### Step 4: Configure Application Secrets

Edit `k8s/manifests/security/app-secrets.yaml`:

**Required Values:**

1. **SECRET_KEY** (Application Secret)
   ```bash
   SECRET_KEY=$(openssl rand -base64 64)
   echo "SECRET_KEY: $SECRET_KEY"
   ```

2. **JWT_SECRET** (JWT Signing Key)
   ```bash
   JWT_SECRET=$(openssl rand -base64 64)
   echo "JWT_SECRET: $JWT_SECRET"
   ```

3. **DATABASE_URL** - Format:
   ```
   postgresql+asyncpg://tesslate_user:<POSTGRES_PASSWORD>@postgres.tesslate.svc.cluster.local:5432/tesslate
   ```
   Replace `<POSTGRES_PASSWORD>` with the password from Step 3.

4. **AI Service Credentials**:
   - `OPENAI_API_KEY`: Your AI provider API key
   - `OPENAI_API_BASE`: API endpoint URL (e.g., `https://api.openai.com/v1`)
   - `OPENAI_MODEL`: Model identifier (e.g., `gpt-4-turbo`)

#### Step 5: Verify Secret Files

```bash
# Check files exist
ls -la k8s/manifests/security/app-secrets.yaml
ls -la k8s/manifests/database/postgres-secret.yaml

# Verify no "REPLACE_WITH" placeholders remain
grep -i "REPLACE_WITH" k8s/manifests/security/app-secrets.yaml
grep -i "REPLACE_WITH" k8s/manifests/database/postgres-secret.yaml
# Should return nothing

# Confirm files are in .gitignore
git status k8s/manifests/security/app-secrets.yaml
git status k8s/manifests/database/postgres-secret.yaml
# Should show: "nothing to commit" or file not tracked
```

#### Step 6: Deploy Secrets to Kubernetes

```bash
# Deploy PostgreSQL secret
kubectl apply -f k8s/manifests/database/postgres-secret.yaml

# Deploy application secrets
kubectl apply -f k8s/manifests/security/app-secrets.yaml

# Verify secrets were created
kubectl get secrets -n tesslate
```

#### Security Checklist

Before deploying to production, ensure:
- [ ] All secrets generated with `openssl rand`
- [ ] No "REPLACE_WITH" or "changeme" values remain
- [ ] DATABASE_URL password matches POSTGRES_PASSWORD
- [ ] All secrets are at least 32 characters
- [ ] Secret files are in .gitignore
- [ ] Secrets NOT committed to git
- [ ] Backup stored in password manager
- [ ] All pods start successfully
- [ ] Application can connect to database

**See also**: `manifests/security/SECRETS_SETUP_GUIDE.md` for detailed instructions and troubleshooting

### Environment Variables

Configure environment variables in:
- **Backend config**: `manifests/app/02-backend-configmap.yaml`

### Storage

By default, uses local storage at `/opt/k8s-data/`. Modify PersistentVolume definitions in `manifests/base/03-persistent-volumes.yaml` to change paths.

## Management

### Using the Management Script

```bash
# Check status
./scripts/manage-tesslate.sh status

# View logs
./scripts/manage-tesslate.sh logs backend
./scripts/manage-tesslate.sh logs frontend

# Restart services
./scripts/manage-tesslate.sh restart backend

# Scale deployments
./scripts/manage-tesslate.sh scale backend 3

# Database backup
./scripts/manage-tesslate.sh backup

# Port forwarding for local access
./scripts/manage-tesslate.sh port-forward

# Update secrets
./scripts/manage-tesslate.sh secrets
```

### Common kubectl Commands

```bash
# View all pods
kubectl get pods -n tesslate

# View logs
kubectl logs -f deployment/tesslate-backend -n tesslate

# Execute commands in pods
kubectl exec -it deployment/postgres -n tesslate -- psql -U tesslate_user

# Describe resources
kubectl describe pod <pod-name> -n tesslate

# Port forward for debugging
kubectl port-forward service/tesslate-frontend-service 3000:80 -n tesslate
```

## Architecture

### Namespaces

- **tesslate**: Main application namespace (backend, frontend, database)
- **tesslate-registry**: Docker registry for container images
- **tesslate-monitoring**: Monitoring stack (Prometheus, Grafana) - optional

### Services

- **Backend**: FastAPI application on port 8005
- **Frontend**: React application served by nginx on port 80
- **PostgreSQL**: Database on port 5432
- **Registry**: Docker registry on NodePort 30500

### Ingress

- HTTP: `http://<SERVER_IP>:30080`
- HTTPS: `https://<SERVER_IP>:30443`
- Hostname: `tesslate.local`

### Storage

- PostgreSQL data: 20Gi PVC
- Project files: 50Gi PVC (shared between backend pods)
- Registry: 30Gi PVC

## Networking

### Access Points

After deployment, access the application at:

- **Web Interface**: `http://<SERVER_IP>:30080`
- **API Endpoint**: `http://<SERVER_IP>:30080/api`
- **Docker Registry**: `<SERVER_IP>:30500`

### Configure Local Access

Add to `/etc/hosts`:
```
<SERVER_IP> tesslate.local
```

Then access: `http://tesslate.local:30080`

## Troubleshooting

### Pods Not Starting

```bash
# Check pod status
kubectl describe pod <pod-name> -n tesslate

# Check events
kubectl get events -n tesslate --sort-by='.lastTimestamp'
```

### Database Connection Issues

```bash
# Check PostgreSQL pod
kubectl logs deployment/postgres -n tesslate

# Test connection
kubectl run -it --rm debug --image=postgres:15 --restart=Never -- psql -h postgres.tesslate.svc.cluster.local -U tesslate_user
```

### Ingress Not Working

```bash
# Check ingress controller
kubectl get pods -n ingress-nginx

# Check ingress configuration
kubectl describe ingress tesslate-ingress -n tesslate
```

### Storage Issues

```bash
# Check PVC status
kubectl get pvc -n tesslate

# Check PV status
kubectl get pv
```

## Scaling

### Horizontal Scaling

```bash
# Scale backend
kubectl scale deployment tesslate-backend --replicas=3 -n tesslate

# Scale frontend
kubectl scale deployment tesslate-frontend --replicas=3 -n tesslate
```

### Adding Worker Nodes

```bash
# On master node, generate join command
kubeadm token create --print-join-command

# On worker node, run the join command
sudo <join-command-from-above>
```

## Backup and Recovery

### Database Backup

```bash
# Manual backup
./scripts/manage-tesslate.sh backup

# Scheduled backup (add to crontab)
0 2 * * * /path/to/scripts/manage-tesslate.sh backup
```

### Database Restore

```bash
./scripts/manage-tesslate.sh restore backup_file.sql
```

### Full Cluster Backup

For production, consider using Velero for complete cluster backup.

## Security Considerations

1. **Change all default passwords** before production deployment
2. **Enable RBAC** for fine-grained access control
3. **Use TLS/SSL** for all external communications
4. **Implement network policies** to restrict pod-to-pod communication
5. **Regular security updates** for cluster and applications
6. **Use secrets management** solutions like Sealed Secrets or External Secrets

## Migration from Docker Compose

If migrating from the existing Docker Compose setup:

1. Backup PostgreSQL data from Docker environment
2. Build and push Docker images
3. Deploy to Kubernetes
4. Restore data to Kubernetes PostgreSQL
5. Update DNS/proxy settings

## Local Development

For local testing using Docker containers instead of a real server:

```bash
# Navigate to local development directory
cd local-dev/

# For Linux/macOS
./k8s-local-setup.sh
./deploy-to-local-k8s.sh

# For Windows (PowerShell)
.\k8s-local-windows.ps1
.\deploy-to-local-k8s.ps1
```

See [local-dev/LOCAL_K8S_README.md](local-dev/LOCAL_K8S_README.md) for complete local development setup.

## Documentation

- **[docs/K3S_DEPLOYMENT_GUIDE.md](docs/K3S_DEPLOYMENT_GUIDE.md)**: k3s deployment guide (recommended for single-server)
- **[docs/KUBERNETES_DEPLOYMENT_GUIDE.md](docs/KUBERNETES_DEPLOYMENT_GUIDE.md)**: Full Kubernetes deployment with kubeadm
- **[docs/PRODUCTION_DEPLOYMENT_STRATEGY.md](docs/PRODUCTION_DEPLOYMENT_STRATEGY.md)**: Production deployment strategies and best practices
- **[docs/SERVERLESS_CONTAINER_ARCHITECTURE.md](docs/SERVERLESS_CONTAINER_ARCHITECTURE.md)**: Serverless architecture documentation

## Support

For issues or questions:
- Check the [main deployment guide](docs/KUBERNETES_DEPLOYMENT_GUIDE.md)
- Review logs using `kubectl logs`
- Check cluster events with `kubectl get events`

## License

See the main project LICENSE file.