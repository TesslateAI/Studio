# Kubernetes Agent Context

You are working on Tesslate Studio's Kubernetes configuration. This context provides quick reference for common Kubernetes tasks.

## File Locations

**Base manifests**: `c:/Users/Smirk/Downloads/Tesslate-Studio/k8s/base/`
**Overlays**: `c:/Users/Smirk/Downloads/Tesslate-Studio/k8s/overlays/{minikube,aws}/`
**Terraform**: `c:/Users/Smirk/Downloads/Tesslate-Studio/k8s/terraform/aws/`

## Quick Commands

### Minikube

```bash
# Build and load image (CRITICAL: Delete first!)
minikube -p tesslate ssh -- docker rmi -f tesslate-backend:latest
docker build --no-cache -t tesslate-backend:latest -f orchestrator/Dockerfile orchestrator/
minikube -p tesslate image load tesslate-backend:latest
kubectl delete pod -n tesslate -l app=tesslate-backend

# Deploy
kubectl apply -k k8s/overlays/minikube

# Access
kubectl port-forward -n tesslate svc/tesslate-frontend-service 5000:80
```

### AWS EKS

```bash
# Build and push
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com
docker build --no-cache -t tesslate-backend:latest -f orchestrator/Dockerfile orchestrator/
docker tag tesslate-backend:latest <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend:latest
docker push <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend:latest

# Deploy
kubectl apply -k k8s/overlays/aws
kubectl delete pod -n tesslate -l app=tesslate-backend

# Restart ingress (clears cache)
kubectl rollout restart deployment/ingress-nginx-controller -n ingress-nginx
```

## Kustomize Structure

**Base** (`k8s/base/kustomization.yaml`):
- Defines common resources
- Sets namespace to `tesslate`
- Lists image names (without tags)

**Overlay** (`k8s/overlays/{env}/kustomization.yaml`):
- References base: `resources: [../../base]`
- Overrides images with registry and tag
- Applies patches for environment-specific config

**Worker Deployment** (`k8s/base/core/worker-deployment.yaml`):
- Runs same image as backend with `arq orchestrator.app.worker.WorkerSettings` command
- Shares `tesslate-secrets` and config with backend
- Separate resource limits for worker pods
- AWS overlay patch: `k8s/overlays/aws-base/worker-patch.yaml`

**Redis** (`k8s/base/redis/`):
- `redis-deployment.yaml` - Single replica Redis with PVC persistence
- `redis-service.yaml` - ClusterIP service (port 6379)
- `redis-pvc.yaml` - 1Gi persistent volume claim
- ConfigMap with `maxmemory 512mb`, `volatile-lru` eviction, `appendonly yes`

## Common Tasks

### Adding Environment Variable

1. Edit `k8s/base/core/backend-deployment.yaml`
2. Add env var to container spec
3. If environment-specific, override in `k8s/overlays/{env}/backend-patch.yaml`
4. Apply: `kubectl apply -k k8s/overlays/{env}`

### Modifying Resource Limits

1. Edit deployment manifest or patch
2. Update `resources.requests` and `resources.limits`
3. Apply: `kubectl apply -k k8s/overlays/{env}`
4. Pods automatically restart with new limits

### Adding New Secret

1. **Minikube**: Add to `k8s/overlays/minikube/secrets/{secret-name}.yaml`
2. **AWS**: Create via kubectl: `kubectl create secret generic {name} -n tesslate --from-literal=KEY=value`
3. Reference in deployment: `valueFrom.secretKeyRef`

### Changing Image

1. **Base**: Update `images` section in `k8s/base/kustomization.yaml`
2. **Overlay**: Update `images` section in `k8s/overlays/{env}/kustomization.yaml`
3. Apply and restart pods

## Network Policies

**Location**: `k8s/base/security/network-policies.yaml`

**Structure**:
- One NetworkPolicy per rule
- `podSelector` defines which pods the policy applies to
- `policyTypes` defines direction (Ingress, Egress, or both)
- `ingress`/`egress` rules define allowed traffic

**Adding new rule**:
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-{source}-to-{dest}
  namespace: tesslate
spec:
  podSelector:
    matchLabels:
      app: {dest-app}
  policyTypes:
  - Ingress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: {source-app}
    ports:
    - protocol: TCP
      port: {port}
```

## RBAC

**Location**: `k8s/base/security/rbac.yaml`

**Components**:
1. ServiceAccount: `tesslate-backend-sa`
2. ClusterRole: `tesslate-dev-environments-manager` (defines permissions)
3. ClusterRoleBinding: `tesslate-backend-cluster-access` (grants permissions to SA)

**Adding permission**:
1. Edit ClusterRole
2. Add resource and verbs to `rules` section
3. Apply: `kubectl apply -k k8s/overlays/{env}`

## EBS VolumeSnapshot (Project Persistence)

**Storage**: Projects use persistent EBS volumes that survive pod restarts.

**Snapshots**: Created via `snapshot_manager.py` using K8s VolumeSnapshot API
- Function: `create_snapshot()` - Creates EBS snapshot (non-blocking)
- Function: `restore_from_snapshot()` - Creates PVC from snapshot
- Function: `cleanup_expired_snapshots()` - Removes old soft-deleted snapshots

**Cleanup cronjobs**: `k8s/base/core/`
- `cleanup-cronjob.yaml` - Runs every 2 minutes, creates snapshots for idle projects
- `snapshot-cleanup-cronjob.yaml` - Daily at 3 AM, deletes expired soft-deleted snapshots

**Timeline UI**: Frontend displays up to 5 snapshots per project for version history

## Debugging

### Pod crash loop
```bash
kubectl logs -n tesslate {pod-name} --previous
kubectl describe pod -n tesslate {pod-name}
```

### Image pull issues
```bash
# Minikube
minikube -p tesslate ssh -- docker images | grep tesslate

# AWS
aws ecr describe-images --repository-name tesslate-backend --region us-east-1
```

### Service not reachable
```bash
kubectl get endpoints -n tesslate tesslate-backend-service
kubectl run -n tesslate test --rm -it --image=curlimages/curl -- curl http://tesslate-backend-service:8000/health
```

### Ingress not routing
```bash
kubectl logs -n ingress-nginx deployment/ingress-nginx-controller --tail=50
kubectl rollout restart deployment/ingress-nginx-controller -n ingress-nginx
```

## Best Practices

1. **Use overlays, not base edits**: Modify environment-specific files in overlays
2. **Always --no-cache on builds**: Ensures code changes are included
3. **Delete before load (Minikube)**: `minikube image load` doesn't overwrite
4. **Restart ingress after backend changes**: Clears endpoint cache
5. **Test in Minikube first**: Catches K8s issues before production
