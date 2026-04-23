# Kubernetes Overlays

Overlays provide environment-specific configuration that patches the base manifests.

**Location**: `c:/Users/Smirk/Downloads/Tesslate-Studio/k8s/overlays/`

## Structure

```
overlays/
├── minikube/                    # Local development
│   ├── kustomization.yaml
│   ├── backend-patch.yaml
│   ├── frontend-patch.yaml
│   ├── ingress-patch.yaml
│   ├── storage-class.yaml
│   └── secrets/                 # Gitignored
│       ├── postgres-secret.yaml
│       ├── s3-credentials.yaml
│       └── app-secrets.yaml
├── aws/                         # AWS EKS production
│   ├── kustomization.yaml
│   ├── backend-patch.yaml
│   ├── frontend-patch.yaml
│   ├── ingress-patch.yaml
│   └── storage-class.yaml
├── digitalocean/                # DigitalOcean (deprecated)
└── gke/                         # Google Kubernetes Engine (future)
```

## Overlay Concepts

### Base Reference

Each overlay references the base:

```yaml
# kustomization.yaml
resources:
  - ../../base
```

### Image Overrides

Overlays specify complete image references:

```yaml
# Minikube (local images)
images:
  - name: tesslate-backend
    newName: tesslate-backend
    newTag: latest

# AWS (ECR)
images:
  - name: tesslate-backend
    newName: <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend
    newTag: latest
```

### Patches

Overlays apply patches to modify base manifests:

**Strategic Merge Patch** (partial update):
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: tesslate-backend
spec:
  replicas: 2  # Override just this field
```

**JSON6902 Patch** (precise modifications):
```yaml
- op: replace
  path: /spec/replicas
  value: 2
```

### Secrets

**Minikube**: Secrets stored as files (gitignored)
**AWS**: Secrets created manually via kubectl (not in git)

## Environment Comparison

| Setting | Minikube | AWS EKS |
|---------|----------|---------|
| **Registry** | Local | ECR (<AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com) |
| **Image Pull Policy** | Never | Always |
| **Image Pull Secret** | None | None (public ECR or IRSA) |
| **Storage Class** | minikube-hostpath | tesslate-block-storage (gp3) |
| **S3** | MinIO (minio-system) | AWS S3 native |
| **S3 Endpoint** | http://minio.minio-system.svc.cluster.local:9000 | (empty, uses AWS SDK default) |
| **Domain** | None (port-forward) | your-domain.com |
| **TLS** | Disabled | Enabled (cert-manager + Cloudflare) |
| **Cookie Secure** | false | true |
| **Cookie Domain** | (empty) | .your-domain.com |
| **Replicas** | 1 (backend, frontend) | 1 (backend), 2 (frontend) |
| **Resource Limits** | Lower (256Mi-512Mi) | Higher (512Mi-2Gi) |

## Minikube Overlay

**File**: `k8s/overlays/minikube/kustomization.yaml`

**Purpose**: Local Kubernetes testing

**Key Patches**:
- `imagePullPolicy: Never` (use locally loaded images)
- `K8S_DEVSERVER_IMAGE=tesslate-devserver:latest` (no registry)
- `K8S_IMAGE_PULL_POLICY=Never`
- Lower resource limits

**Secrets**:
- Created from `.env.minikube` via `k8s/scripts/generate-secrets.sh`
- Stored in `secrets/` (gitignored)

**S3**:
- MinIO deployed in `minio-system` namespace
- Endpoint: `http://minio.minio-system.svc.cluster.local:9000`

**Deploy**:
```bash
kubectl apply -k k8s/overlays/minikube
```

**Access**:
```bash
# Option 1: Tunnel (requires admin)
minikube -p tesslate tunnel

# Option 2: Port-forward
kubectl port-forward -n tesslate svc/tesslate-frontend-service 5000:80
```

## AWS Overlay

**File**: `k8s/overlays/aws/kustomization.yaml`

**Purpose**: Production deployment on AWS EKS

**Key Patches**:
- `imagePullPolicy: Always` (check for updates)
- ECR image URIs
- `K8S_DEVSERVER_IMAGE=<AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-devserver:latest`
- Domain: `your-domain.com`
- TLS enabled
- Higher resource limits

**Secrets**:
- Created manually via kubectl
- Not stored in git

**S3**:
- Native AWS S3 (bucket: `tesslate-projects-production-7761157a`)
- Uses IRSA for authentication (no credentials in secrets)
- Endpoint: (empty, uses AWS SDK default)

**Deploy**:
```bash
kubectl apply -k k8s/overlays/aws
```

**Access**:
```
https://your-domain.com
```

## Creating New Overlay

1. **Create directory**:
```bash
mkdir -p k8s/overlays/myenv
```

2. **Create kustomization.yaml**:
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

namespace: tesslate

resources:
  - ../../base

images:
  - name: tesslate-backend
    newName: {your-registry}/tesslate-backend
    newTag: latest

patches:
  - path: backend-patch.yaml
```

3. **Create patches**:
```yaml
# backend-patch.yaml
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
        - name: APP_DOMAIN
          value: "myenv.example.com"
```

4. **Create secrets** (see next section)

5. **Deploy**:
```bash
kubectl apply -k k8s/overlays/myenv
```

## Managing Secrets

### Minikube (File-based)

1. Copy template:
```bash
cp k8s/overlays/minikube/.env.example k8s/overlays/minikube/.env.minikube
```

2. Edit values:
```bash
# .env.minikube
SECRET_KEY=your-secret-key
DATABASE_URL=postgresql+asyncpg://tesslate_user:password@postgres:5432/tesslate_dev
LITELLM_API_BASE=https://your-litellm-instance.com
# ... etc
```

3. Generate secrets:
```bash
k8s/scripts/generate-secrets.sh minikube
```

This creates YAML files in `secrets/` that Kustomize includes.

### AWS (kubectl)

1. Create secret imperatively:
```bash
kubectl create secret generic tesslate-app-secrets -n tesslate \
  --from-literal=SECRET_KEY=xxx \
  --from-literal=DATABASE_URL=xxx \
  --from-literal=LITELLM_API_BASE=xxx \
  --from-literal=LITELLM_MASTER_KEY=xxx \
  --from-literal=APP_DOMAIN=your-domain.com \
  --from-literal=APP_BASE_URL=https://your-domain.com \
  --from-literal=CORS_ORIGINS=https://your-domain.com \
  --from-literal=ALLOWED_HOSTS=your-domain.com \
  # ... (full list in k8s/overlays/aws/README.md)
```

2. Create PostgreSQL secret:
```bash
kubectl create secret generic postgres-secret -n tesslate \
  --from-literal=POSTGRES_DB=tesslate_prod \
  --from-literal=POSTGRES_USER=tesslate_user \
  --from-literal=POSTGRES_PASSWORD=xxx
```

3. S3 credentials (for MinIO, not needed for AWS with IRSA):
```bash
kubectl create secret generic s3-credentials -n tesslate \
  --from-literal=S3_ACCESS_KEY_ID=xxx \
  --from-literal=S3_SECRET_ACCESS_KEY=xxx \
  --from-literal=S3_BUCKET_NAME=tesslate-projects-production-7761157a \
  --from-literal=S3_ENDPOINT_URL= \
  --from-literal=S3_REGION=us-east-1
```

## Troubleshooting

### Minikube: Image not updating

**Problem**: Rebuilt image but pod still uses old code

**Diagnosis**:
```bash
# Check image in Minikube
minikube -p tesslate ssh -- docker images | grep tesslate

# Check pod image
kubectl describe pod -n tesslate {pod-name} | grep Image
```

**Solution**: Delete image from Minikube before loading new one
```bash
minikube -p tesslate ssh -- docker rmi -f tesslate-backend:latest
docker build --no-cache -t tesslate-backend:latest -f orchestrator/Dockerfile orchestrator/
minikube -p tesslate image load tesslate-backend:latest
kubectl delete pod -n tesslate -l app=tesslate-backend
```

### AWS: User container ImagePullBackOff

**Problem**: User project pods can't pull devserver image

**Diagnosis**:
```bash
kubectl describe pod -n proj-{uuid} {pod-name} | grep Image
kubectl exec -n tesslate deployment/tesslate-backend -- env | grep K8S_DEVSERVER_IMAGE
```

**Solution**: Verify `K8S_DEVSERVER_IMAGE` in backend patch includes full ECR URI

### Secrets missing

**Problem**: Pod crash with "secret not found"

**Diagnosis**:
```bash
kubectl get secrets -n tesslate
kubectl describe pod -n tesslate {pod-name}
```

**Solution**: Create missing secret
```bash
kubectl create secret generic {secret-name} -n tesslate --from-literal=KEY=value
```

## Best Practices

1. **Never commit secrets**: Use `.gitignore` for Minikube, imperative creation for AWS
2. **Use patches, not replacements**: Strategic merge patches are easier to maintain
3. **Test in Minikube first**: Catch issues before production
4. **Document secret keys**: Keep list of required secret keys in overlay README
5. **Version your overlays**: Tag overlay changes with version numbers
6. **Minimize differences**: Keep overlays as similar as possible for consistency

## Related Documentation

- [../README.md](../README.md): Kubernetes overview
- [../base/README.md](../base/README.md): Base manifests
- [minikube.md](minikube.md): Minikube configuration details
- [aws.md](aws.md): AWS EKS configuration details (legacy single-env layout)
- [aws-base.md](aws-base.md): Shared AWS patches consumed by beta + production
- [aws-beta.md](aws-beta.md): Beta AWS overlay
- [aws-production.md](aws-production.md): Production AWS overlay
- [digitalocean.md](digitalocean.md): DigitalOcean overlay
- [gke.md](gke.md): GKE overlay
