# Archived Kubernetes Manifests

This directory contains manifests that were used in previous setups or are provided as examples/references.

## 📂 Folder Structure

### `examples/`
Template and example manifest files:
- `00-docr-secret.yaml.example` - Example DigitalOcean Container Registry secret
- `01-app-secrets.yaml.example` - Example application secrets template

### `k3s-local/`
Manifests specific to local K3s/development clusters:
- `02-storage-class-k3s.yaml` - K3s storage class configuration
- `02-storage-class.yaml` - Local storage classes with no-provisioner
- `03-persistent-volumes.yaml` - Local hostPath persistent volumes
- `08-ingress-k3s.yaml` - K3s-specific ingress configuration

### `local-dev/`
Local development tools and scripts:
- `deploy-to-local-k8s.ps1` - PowerShell deployment script
- `k8s-local-windows.ps1` - Windows K8s setup script

### `local-registry/`
Self-hosted Docker registry manifests (replaced by DigitalOcean Container Registry):
- `01-registry-pvc.yaml` - Registry persistent volume claim
- `02-registry-deployment.yaml` - Registry deployment
- `03-registry-service.yaml` - Registry service
- `04-registry-tls-config.yaml` - Registry TLS configuration
- `05-kubelet-ca-trust.yaml` - Kubelet CA trust configuration
- `scripts/` - Registry setup and build scripts

## 🚀 Current Production Setup

The current production deployment uses:
- **DigitalOcean Kubernetes** (managed cluster)
- **DigitalOcean Container Registry** (private registry)
- **DigitalOcean Block Storage** (automatic provisioning)
- **NGINX Ingress Controller** (managed load balancer)

Active manifests are in:
- `k8s/manifests/app/` - Application components
- `k8s/manifests/base/` - Base infrastructure
- `k8s/manifests/database/` - PostgreSQL database

## 📝 Usage

These archived manifests are provided for reference and can be adapted for:
- Local development with K3s/minikube
- Self-hosted deployments
- Understanding the evolution of the deployment

**⚠️ Note**: These manifests may require updates to work with current versions.