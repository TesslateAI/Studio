# Base Manifests Agent Context

Working on base Kubernetes manifests. Quick reference for common modifications.

## File Locations

All files: `c:/Users/Smirk/Downloads/Tesslate-Studio/k8s/base/`

## Adding New Resource

1. Create YAML file in appropriate subdirectory (core/, database/, security/, ingress/)
2. Add filename to `kustomization.yaml` under `resources:`
3. Test: `kubectl kustomize k8s/base` (should not error)
4. Deploy via overlay: `kubectl apply -k k8s/overlays/minikube`

## Modifying Existing Resource

1. Edit YAML file
2. If adding env var to deployment, reference secret or configmap
3. Test with overlay: `kubectl apply -k k8s/overlays/minikube`
4. Check pod logs: `kubectl logs -n tesslate deployment/{name}`

## Common Patterns

### Environment Variable from Secret
```yaml
env:
- name: MY_VAR
  valueFrom:
    secretKeyRef:
      name: my-secret
      key: MY_VAR
```

### Environment Variable from ConfigMap
```yaml
env:
- name: MY_VAR
  valueFrom:
    configMapKeyRef:
      name: my-configmap
      key: MY_VAR
```

### Health Check
```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8000
  periodSeconds: 10
  timeoutSeconds: 5
  failureThreshold: 3
```

### Resource Limits
```yaml
resources:
  requests:
    memory: "256Mi"
    cpu: "100m"
  limits:
    memory: "512Mi"
    cpu: "500m"
```

## Don't Modify in Base

- Image registry/tags (use overlays)
- Secrets (create per environment)
- Domain/host configuration (use overlays)
- Resource limits (vary by environment, use overlays)
- Image pull policy (use overlays)
