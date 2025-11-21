# Developer Quickstart

Make code changes and deploy to the DOKS cluster.

## Prerequisites

```bash
# Install doctl and kubectl if not already installed
brew install doctl kubectl  # macOS
```

## 1. Authenticate with DigitalOcean

```bash
# Switch to tesslate context (if you have multiple DO accounts)
doctl auth switch tesslate

# Connect to cluster
doctl kubernetes cluster kubeconfig save tesslate-studio-nyc2

# Verify
kubectl get nodes
```

## 2. Verify Secrets Exist

The cluster needs these secrets to run. They should already exist - just verify:

```bash
# Check secrets exist
kubectl get secret tesslate-app-secrets -n tesslate
kubectl get secret postgres-secret -n tesslate
kubectl get secret docr-registry -n tesslate
```

If missing, see [First-Time Setup](#first-time-setup-secrets) below.

## 3. Build & Push Images

```bash
# Set your DOCR token
export DOCR_TOKEN="your_digitalocean_api_token"

# Or add to k8s/.env (recommended)
echo "DOCR_TOKEN=your_token" > k8s/.env

# Build and push
cd k8s/scripts/deployment
./build-push-images.sh
```

## 4. Deploy Changes

```bash
# Restart deployments to pull new images
kubectl rollout restart deployment/tesslate-backend -n tesslate
kubectl rollout restart deployment/tesslate-frontend -n tesslate

# Watch rollout
kubectl rollout status deployment/tesslate-backend -n tesslate
```

## Quick Reference

| Task | Command |
|------|---------|
| View pods | `kubectl get pods -n tesslate` |
| Backend logs | `kubectl logs -f deployment/tesslate-backend -n tesslate` |
| Frontend logs | `kubectl logs -f deployment/tesslate-frontend -n tesslate` |
| Shell into backend | `kubectl exec -it deployment/tesslate-backend -n tesslate -- /bin/bash` |
| Check events | `kubectl get events -n tesslate --sort-by='.lastTimestamp'` |

## Troubleshooting

**Image pull errors:**
```bash
./setup-registry-auth.sh
```

**Pod not starting:**
```bash
kubectl describe pod <pod-name> -n tesslate
```

---

## First-Time Setup (Secrets)

Only needed if secrets don't exist:

```bash
# Generate secrets
cd k8s/scripts
./generate-secrets.sh  # or generate-secrets.bat on Windows

# Apply secrets
kubectl apply -f ../manifests/security/app-secrets.yaml
kubectl apply -f ../manifests/database/postgres-secret.yaml

# Setup registry auth
cd deployment
./setup-registry-auth.sh
```
