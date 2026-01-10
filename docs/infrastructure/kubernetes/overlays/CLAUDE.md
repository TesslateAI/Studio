# Overlays Agent Context

Working on Kubernetes overlays. Quick reference for environment-specific configuration.

## File Locations

**Minikube**: `c:/Users/Smirk/Downloads/Tesslate-Studio/k8s/overlays/minikube/`
**AWS**: `c:/Users/Smirk/Downloads/Tesslate-Studio/k8s/overlays/aws/`

## Key Differences

| What | Minikube | AWS |
|------|----------|-----|
| Image registry | Local | ECR <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com |
| Pull policy | Never | Always |
| Storage | minikube-hostpath | tesslate-block-storage (gp3) |
| S3 | MinIO (port 9000) | AWS S3 native |
| Domain | None | your-domain.com |
| TLS | No | Yes (cert-manager) |

## Modifying Overlay

1. Edit patch file in `k8s/overlays/{env}/`
2. Apply: `kubectl apply -k k8s/overlays/{env}`
3. Restart pods if needed: `kubectl delete pod -n tesslate -l app={app}`

## Adding Environment Variable

**Option 1**: Add to base (`k8s/base/core/backend-deployment.yaml`), use everywhere

**Option 2**: Add to patch (`k8s/overlays/{env}/backend-patch.yaml`), environment-specific

Example patch:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: tesslate-backend
spec:
  template:
    spec:
      containers:
      - name: backend
        env:
        - name: MY_NEW_VAR
          value: "my-value"
```

## Testing Changes

1. **Minikube**: `kubectl apply -k k8s/overlays/minikube`
2. **Check pods**: `kubectl get pods -n tesslate`
3. **View logs**: `kubectl logs -n tesslate deployment/tesslate-backend`
4. **Verify env**: `kubectl exec -n tesslate deployment/tesslate-backend -- env | grep MY_NEW_VAR`
