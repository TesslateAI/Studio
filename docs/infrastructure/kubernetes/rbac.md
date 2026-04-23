# RBAC Configuration

Role-Based Access Control for OpenSail's Kubernetes deployment.

**File**: `c:/Users/Smirk/Downloads/Tesslate-Studio/k8s/base/security/rbac.yaml`

## Overview

Tesslate's backend needs cluster-wide permissions to dynamically create and manage user project namespaces (`proj-{uuid}`). This requires a ServiceAccount with ClusterRole permissions.

## Components

### ServiceAccount

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: tesslate-backend-sa
  namespace: tesslate
```

**Used by**:
- Backend deployment (`tesslate-backend`)
- Cleanup cronjob (`dev-environment-cleanup`)

**Purpose**: Identity for pods to authenticate with Kubernetes API

### ClusterRole

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: tesslate-dev-environments-manager
```

**Permissions**:

**Namespaces** (cluster-scoped):
- create, delete, get, list, watch, patch, update
- Required to create `proj-{uuid}` namespaces for projects

**Core Resources** (all namespaces):
- pods, pods/log, pods/exec
- services
- persistentvolumeclaims
- secrets
- configmaps

**Apps** (all namespaces):
- deployments
- replicasets
- statefulsets

**Networking** (all namespaces):
- ingresses
- networkpolicies

**Batch** (all namespaces):
- jobs
- cronjobs

**Events** (all namespaces):
- get, list, watch (for troubleshooting)

### ClusterRoleBinding

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: tesslate-backend-cluster-access
subjects:
- kind: ServiceAccount
  name: tesslate-backend-sa
  namespace: tesslate
roleRef:
  kind: ClusterRole
  name: tesslate-dev-environments-manager
  apiGroup: rbac.authorization.k8s.io
```

**Purpose**: Grants ClusterRole permissions to ServiceAccount

## Why ClusterRole (not Role)?

**Role**: Namespaced, only grants permissions within a single namespace
**ClusterRole**: Cluster-wide, can grant permissions across all namespaces

Backend needs to:
1. Create/delete namespaces (cluster-scoped resource)
2. Manage resources in `proj-*` namespaces (cross-namespace)

Therefore, ClusterRole is required.

## Security Considerations

### Principle of Least Privilege

**What backend CAN do**:
- Create/delete namespaces
- Manage pods, services, PVCs in any namespace
- Create ingresses for routing

**What backend CANNOT do**:
- Modify nodes
- Create/modify RBAC resources
- Access secrets in other namespaces (except for project management)
- Modify cluster-wide resources (except namespaces)

### Limiting Scope (Future Improvement)

Currently, backend has permissions across ALL namespaces. Could be limited to:
- `tesslate` namespace (platform)
- `proj-*` namespaces (user projects)

Using label selectors or namespace prefix matching (requires custom admission controller).

## Usage in Code

**File**: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/orchestration/kubernetes_orchestrator.py`

**Examples**:

**Create namespace**:
```python
from kubernetes import client

core_api = client.CoreV1Api()
namespace = client.V1Namespace(
    metadata=client.V1ObjectMeta(name=f"proj-{project_id}")
)
core_api.create_namespace(namespace)
```

**Create deployment**:
```python
apps_api = client.AppsV1Api()
apps_api.create_namespaced_deployment(
    namespace=f"proj-{project_id}",
    body=deployment_manifest
)
```

**Delete namespace** (cascades to all resources):
```python
core_api.delete_namespace(name=f"proj-{project_id}")
```

## Verifying Permissions

### Check ServiceAccount

```bash
kubectl get sa -n tesslate tesslate-backend-sa
kubectl describe sa -n tesslate tesslate-backend-sa
```

### Check ClusterRole

```bash
kubectl get clusterrole tesslate-dev-environments-manager
kubectl describe clusterrole tesslate-dev-environments-manager
```

### Check ClusterRoleBinding

```bash
kubectl get clusterrolebinding tesslate-backend-cluster-access
kubectl describe clusterrolebinding tesslate-backend-cluster-access
```

### Test Permissions

```bash
# From within backend pod
kubectl auth can-i create namespaces --as=system:serviceaccount:tesslate:tesslate-backend-sa
# Should return "yes"

kubectl auth can-i create deployments --namespace=proj-test --as=system:serviceaccount:tesslate:tesslate-backend-sa
# Should return "yes"

kubectl auth can-i delete nodes --as=system:serviceaccount:tesslate:tesslate-backend-sa
# Should return "no"
```

## Troubleshooting

### Permission Denied Errors

**Symptom**: Backend logs show `forbidden: User "system:serviceaccount:tesslate:tesslate-backend-sa" cannot create resource "namespaces"`

**Check**:
```bash
kubectl get clusterrolebinding tesslate-backend-cluster-access
```

**Fix**: Reapply RBAC manifests
```bash
kubectl apply -f k8s/base/security/rbac.yaml
```

### ServiceAccount Not Found

**Symptom**: Deployment fails with `serviceaccount "tesslate-backend-sa" not found`

**Check**:
```bash
kubectl get sa -n tesslate
```

**Fix**: Apply RBAC manifests first, then deployment
```bash
kubectl apply -k k8s/overlays/{env}
```

## Modifying Permissions

### Adding New Resource Type

1. Edit `k8s/base/security/rbac.yaml`
2. Add resource to ClusterRole `rules`:
```yaml
- apiGroups: ["custom.io"]
  resources:
    - customresources
  verbs: ["create", "delete", "get", "list"]
```
3. Apply changes:
```bash
kubectl apply -f k8s/base/security/rbac.yaml
```

### Restricting Permissions

To remove a permission:
1. Remove resource from ClusterRole
2. Apply changes
3. Test that backend still functions correctly

**Note**: Removing critical permissions will break project creation/deletion.

## Related Documentation

- [network-policies.md](network-policies.md): Network-level security
- [../base/README.md](base/README.md): Base manifests overview
- Kubernetes RBAC: https://kubernetes.io/docs/reference/access-authn-authz/rbac/
