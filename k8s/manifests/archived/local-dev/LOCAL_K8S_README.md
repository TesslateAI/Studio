# Local Kubernetes in Docker Setup Guide

This guide helps you run Phase 1 of the Kubernetes deployment locally in a Docker container for testing and development purposes.

## What This Does

- Creates a fully functional Kubernetes cluster inside a Docker container
- Runs on your local machine without needing a VM or cloud server
- Includes all components from Phase 1 of the deployment guide
- Perfect for testing before deploying to production

## Prerequisites

- Docker Desktop installed and running
- At least 8GB RAM available
- 20GB free disk space
- Windows, macOS, or Linux

## Quick Start

### For Windows (PowerShell)

```powershell
# Run the setup script
.\local-dev\k8s-local-windows.ps1

# After setup completes, access the cluster
docker exec -it k8s-local-master bash
kubectl get nodes
```

### For macOS/Linux

```bash
# Make scripts executable
chmod +x local-dev/k8s-local-setup.sh local-dev/k8s-local-helper.sh

# Run the setup
./local-dev/k8s-local-setup.sh

# After setup completes, access the cluster
./local-dev/k8s-local-helper.sh shell
kubectl get nodes
```

## Using the Helper Script (macOS/Linux)

The helper script provides easy management commands:

```bash
# Start the container
./local-dev/k8s-local-helper.sh start

# Stop the container
./local-dev/k8s-local-helper.sh stop

# Enter the container shell
./local-dev/k8s-local-helper.sh shell

# Check cluster status
./local-dev/k8s-local-helper.sh status

# Set up kubectl on your host machine
./local-dev/k8s-local-helper.sh setup-kubectl
export KUBECONFIG=~/.kube/config-local
kubectl get nodes

# Install Helm package manager
./k8s-local-helper.sh install-helm

# Install NGINX Ingress Controller
./k8s-local-helper.sh install-ingress

# Deploy a test application
./k8s-local-helper.sh test-app

# Clean up everything
./k8s-local-helper.sh clean
```

## Accessing Services

The following ports are exposed on localhost:

- **6443**: Kubernetes API server
- **30080**: HTTP traffic (NodePort)
- **30443**: HTTPS traffic (NodePort)
- **30300**: Grafana (when installed)
- **30301**: Prometheus (when installed)
- **30500**: Docker Registry (when installed)
- **30900**: MinIO (when installed)

## Next Steps After Setup

Once your local Kubernetes is running, you can proceed with Phase 2 of the deployment guide:

1. **Deploy PostgreSQL**:
```bash
docker exec -it k8s-local-master bash
kubectl create namespace tesslate
# Follow Phase 2 steps from the main guide
```

2. **Build and Deploy Your Application**:
- Build Docker images on your host
- Push to the local registry at `localhost:30500`
- Deploy using Kubernetes manifests

3. **Test the Migration**:
- Verify all components work locally
- Test data migration scripts
- Validate the deployment process

## Differences from Production

This local setup has some differences from a production deployment:

1. **Single Node**: Everything runs on one node (no high availability)
2. **Resource Constraints**: Limited by your local machine's resources
3. **Storage**: Uses Docker volumes instead of persistent volume provisioners
4. **Networking**: Uses Docker's bridge network instead of cloud networking
5. **Security**: Some security features may be relaxed for local development

## Troubleshooting

### Container Won't Start

```bash
# Check Docker logs
docker logs k8s-local-master

# Ensure Docker has enough resources
# Docker Desktop > Settings > Resources
# Recommended: 4 CPUs, 8GB RAM
```

### Kubernetes Not Initializing

```bash
# Enter container and check services
docker exec -it k8s-local-master bash
systemctl status kubelet
systemctl status docker
journalctl -xe
```

### Can't Access Services

```bash
# Check if ports are properly exposed
docker port k8s-local-master

# Check if services are running
docker exec k8s-local-master kubectl get svc -A
```

### Reset Everything

```bash
# Complete cleanup
docker stop k8s-local-master
docker rm k8s-local-master
docker volume rm k8s-local-data k8s-etcd-data k8s-kubelet-data
docker network rm k8s-local-network

# Start fresh
./k8s-local-setup.sh  # or .\k8s-local-windows.ps1 on Windows
```

## Important Notes

1. **Not for Production**: This setup is for testing only
2. **Resource Intensive**: Kubernetes in Docker uses significant resources
3. **Persistence**: Data is stored in Docker volumes, backup important data
4. **Updates**: Stop and recreate the container to update Kubernetes version

## Migrating to Real Server

Once you've tested everything locally:

1. Document all customizations you made
2. Export your application manifests
3. Test your migration scripts with sample data
4. Follow the production deployment guide on your actual server
5. Use the same Helm charts and configurations tested locally

This local environment provides a safe space to experiment with Kubernetes without the cost or complexity of cloud resources or dedicated servers.