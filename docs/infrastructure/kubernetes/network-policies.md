# Network Policies

Network security configuration for Tesslate Studio's Kubernetes deployment.

**File**: `c:/Users/Smirk/Downloads/Tesslate-Studio/k8s/base/security/network-policies.yaml`

## Overview

NetworkPolicies provide firewall-like rules at the pod level, controlling ingress and egress traffic. Tesslate uses a **default deny, explicit allow** approach for security.

## Architecture

```
┌──────────────┐
│ NGINX Ingress│  (ingress-nginx namespace)
└──────┬───────┘
       │ ALLOWED
       ↓
┌──────────────────────────────────────────┐
│ tesslate namespace                       │
│  ┌──────────┐     ┌────────┐            │
│  │ Frontend │ --> │ Backend│ --> External│
│  └──────────┘     └────┬───┘            │
│                        │                 │
│                        ↓                 │
│                   ┌─────────┐            │
│                   │Postgres │            │
│                   └─────────┘            │
└──────────────────────────────────────────┘

┌──────────────────────────────────────────┐
│ proj-{uuid} namespace (user project)    │
│  ┌──────────────┐                        │
│  │Dev Container │ <-- NGINX Ingress ONLY │
│  │              │ --> External (npm,pip) │
│  └──────────────┘                        │
└──────────────────────────────────────────┘
```

## Platform Namespace Policies

### 1. default-deny-ingress

**Purpose**: Block all incoming traffic by default

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-ingress
  namespace: tesslate
spec:
  podSelector: {}  # Applies to all pods in namespace
  policyTypes:
  - Ingress
```

**Effect**: All ingress blocked unless explicitly allowed by other policies

### 2. allow-ingress-controller

**Purpose**: Allow NGINX Ingress to reach platform services

```yaml
spec:
  podSelector: {}  # Applies to all pods
  policyTypes:
  - Ingress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: ingress-nginx
```

**Effect**: NGINX Ingress Controller can reach any pod in `tesslate` namespace

### 3. allow-backend-from-frontend

**Purpose**: Allow frontend to call backend API

```yaml
spec:
  podSelector:
    matchLabels:
      app: tesslate-backend
  policyTypes:
  - Ingress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: tesslate-frontend
    ports:
    - protocol: TCP
      port: 8000
```

**Effect**: Frontend pods can reach backend port 8000

### 4. allow-postgres-from-backend

**Purpose**: Allow backend to access database

```yaml
spec:
  podSelector:
    matchLabels:
      app: postgres
  policyTypes:
  - Ingress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: tesslate-backend
    ports:
    - protocol: TCP
      port: 5432
```

**Effect**: Only backend can reach Postgres port 5432

### 5. allow-dns-egress

**Purpose**: Allow all pods to resolve DNS

```yaml
spec:
  podSelector: {}  # Applies to all pods
  policyTypes:
  - Egress
  egress:
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: kube-system
    ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
```

**Effect**: All pods can query kube-dns (CoreDNS) for name resolution

### 6. allow-backend-egress

**Purpose**: Allow backend to manage projects and reach external services

```yaml
spec:
  podSelector:
    matchLabels:
      app: tesslate-backend
  policyTypes:
  - Egress
  egress:
  # Allow to any namespace (for managing proj-* namespaces)
  - to:
    - namespaceSelector: {}
  # Allow to external (S3, LiteLLM, OAuth)
  - to:
    - ipBlock:
        cidr: 0.0.0.0/0
        except:
        - 10.0.0.0/8     # Exclude internal ranges
        - 172.16.0.0/12
        - 192.168.0.0/16
    ports:
    - protocol: TCP
      port: 443
    - protocol: TCP
      port: 80
    - protocol: TCP
      port: 9000  # MinIO
```

**Effect**: Backend can:
- Reach pods in `proj-*` namespaces (via Kubernetes API)
- Make HTTPS requests to external services (S3, LiteLLM, OAuth)
- Reach MinIO port 9000 (Minikube only)

## User Project Namespace Policies

Created dynamically by backend when project starts:

**File**: `c:/Users/Smirk/Downloads/Tesslate-Studio/orchestrator/app/services/orchestration/kubernetes_orchestrator.py`

### 1. default-deny-ingress

Same as platform namespace - block all ingress by default

### 2. allow-ingress-to-{container}

**Purpose**: Allow NGINX Ingress to reach specific container

```yaml
spec:
  podSelector:
    matchLabels:
      tesslate.io/container-directory: frontend  # e.g.
  policyTypes:
  - Ingress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: ingress-nginx
    ports:
    - protocol: TCP
      port: 3000  # Dev server port
```

**Effect**: Only NGINX Ingress can reach user container

### 3. allow-dns-egress

Same as platform namespace

### 4. allow-external-egress

**Purpose**: Allow user containers to install dependencies and call APIs

```yaml
spec:
  podSelector: {}
  policyTypes:
  - Egress
  egress:
  - to:
    - ipBlock:
        cidr: 0.0.0.0/0
        except:
        - 10.0.0.0/8
        - 172.16.0.0/12
        - 192.168.0.0/16
    ports:
    - protocol: TCP
      port: 443
    - protocol: TCP
      port: 80
```

**Effect**: User containers can:
- npm install (registry.npmjs.org)
- pip install (pypi.org)
- Make API calls to external services

**Blocked**: Access to internal cluster services (except DNS)

## Security Implications

### What's Protected

**Platform namespace**:
- Postgres only reachable by backend
- Backend only reachable by frontend and NGINX
- Frontend only reachable by NGINX

**User projects**:
- Isolated from platform namespace
- Isolated from other user projects
- Only reachable via NGINX Ingress (public internet)

### What's Not Protected

**User projects can**:
- Make arbitrary external HTTP/HTTPS requests
- Download from npm, pip, etc.
- Call external APIs

**Why**: User projects need dependency installation. Blocking would break development workflow.

**Mitigation**: Network policies + resource quotas + monitoring

## Verifying Network Policies

### Check Applied Policies

```bash
# Platform namespace
kubectl get networkpolicies -n tesslate

# User project namespace
kubectl get networkpolicies -n proj-{uuid}
```

### Describe Policy

```bash
kubectl describe networkpolicy default-deny-ingress -n tesslate
```

### Test Connectivity

**From backend to Postgres (should work)**:
```bash
kubectl exec -n tesslate deployment/tesslate-backend -- nc -zv postgres 5432
```

**From frontend to Postgres (should fail)**:
```bash
kubectl exec -n tesslate deployment/tesslate-frontend -- nc -zv postgres 5432
# Should timeout or be refused
```

**From user container to backend (should fail)**:
```bash
kubectl exec -n proj-{uuid} {pod-name} -- curl -m 5 http://tesslate-backend-service.tesslate.svc.cluster.local:8000/health
# Should timeout
```

## Troubleshooting

### Connection Timeouts

**Symptom**: Pod logs show connection timeouts to other services

**Check**:
```bash
# List policies in namespace
kubectl get networkpolicies -n {namespace}

# Describe pod's labels
kubectl describe pod -n {namespace} {pod-name} | grep Labels

# Check if policy allows connection
kubectl describe networkpolicy {policy-name} -n {namespace}
```

**Fix**: Add explicit allow rule if connection is legitimate

### DNS Not Working

**Symptom**: `getaddrinfo` errors, cannot resolve hostnames

**Check**:
```bash
kubectl exec -n tesslate deployment/tesslate-backend -- nslookup kubernetes.default
```

**Fix**: Ensure `allow-dns-egress` policy is applied
```bash
kubectl apply -f k8s/base/security/network-policies.yaml
```

### External Traffic Blocked

**Symptom**: npm install, pip install, or API calls fail

**Check**:
```bash
kubectl exec -n proj-{uuid} {pod-name} -- curl -m 5 https://registry.npmjs.org
```

**Fix**: Check egress policy allows port 443:
```bash
kubectl describe networkpolicy allow-external-egress -n proj-{uuid}
```

## Modifying Policies

### Adding New Allow Rule

1. Edit `k8s/base/security/network-policies.yaml`
2. Add new NetworkPolicy resource:
```yaml
---
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
3. Apply changes:
```bash
kubectl apply -f k8s/base/security/network-policies.yaml
```

### Disabling Network Policies

**Not recommended for production**, but useful for debugging:

```bash
# Delete all policies in namespace
kubectl delete networkpolicies --all -n tesslate
```

**Note**: Default deny policy will be gone, all traffic allowed.

## Best Practices

1. **Default deny first**: Always create deny-all policy before allow policies
2. **Explicit ports**: Specify exact ports, don't allow all ports
3. **Minimum necessary**: Only allow connections that are required
4. **Test thoroughly**: Verify connectivity after policy changes
5. **Document rules**: Add comments explaining why each rule exists
6. **Monitor violations**: Set up alerts for policy violations (requires CNI plugin support)

## CNI Plugin Requirements

Network policies require CNI plugin support:

**Minikube**: Uses Kindnet (supports NetworkPolicy)
**AWS EKS**: Uses AWS VPC CNI (supports NetworkPolicy)
**GKE**: Uses Google CNI (supports NetworkPolicy)

**Verify**:
```bash
kubectl get pods -n kube-system | grep -E 'calico|cilium|weave|canal'
```

If no CNI found, network policies have no effect (still created but not enforced).

## Related Documentation

- [rbac.md](rbac.md): RBAC security
- [../base/README.md](base/README.md): Base manifests
- Kubernetes Network Policies: https://kubernetes.io/docs/concepts/services-networking/network-policies/
