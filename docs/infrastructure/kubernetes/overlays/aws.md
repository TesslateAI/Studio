# AWS EKS Overlay Configuration

Configuration for AWS EKS deployment (beta and production).

**Locations**:
- Shared base: `k8s/overlays/aws-base/`
- Beta: `k8s/overlays/aws-beta/`
- Production: `k8s/overlays/aws-production/`

## Overview

The AWS overlay is split into a shared base and environment-specific patches:
- **aws-base**: Common configuration (backend env vars, worker patch, `envFrom` for secrets)
- **aws-beta**: Beta-specific patches (replicas, resources, rollout strategy)
- **aws-production**: Production-specific patches

Both environments configure:
- ECR container registry
- AWS S3 for project storage
- TLS with cert-manager
- Environment-specific resource limits
- Domains: `your-domain.com` (beta), `opensail.tesslate.com` (production)

## Key Configuration

### Images

**Registry**: `<AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com`

**Image Pull Policy**: `Always` (check for updates on every pod start)

**Images**:
```yaml
images:
  - name: tesslate-backend
    newName: <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend
    newTag: latest
  - name: tesslate-frontend
    newName: <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-frontend
    newTag: latest
  - name: tesslate-devserver
    newName: <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-devserver
    newTag: latest
```

**Pushing Images**:
```bash
# Login
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com

# Build, tag, push
docker build --no-cache -t tesslate-backend:latest -f orchestrator/Dockerfile .
docker tag tesslate-backend:latest <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend:latest
docker push <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend:latest

# Force pod restart (pulls new image)
kubectl delete pod -n tesslate -l app=tesslate-backend
```

### Storage

**Storage Class**: `tesslate-block-storage`
- Type: EBS gp3
- Provisioner: `ebs.csi.aws.com`
- Access mode: ReadWriteOnce
- Encryption: Enabled
- Reclaim policy: Delete
- Volume binding: WaitForFirstConsumer

**Defined in**: `k8s/terraform/aws/eks.tf` (resource `kubernetes_storage_class.gp3`)

**PVC Settings**:
- Size: 5Gi (per project)
- Automatically encrypted

### S3 Storage

**Bucket**: `tesslate-projects-production-7761157a`
- Region: us-east-1
- Versioning: Enabled
- Encryption: AES256
- Lifecycle: Old versions → IA → Glacier → expire

**Authentication**: IRSA (IAM Roles for Service Accounts)
- No credentials in secrets
- Backend service account has S3 access via IAM role
- Configured in Terraform

**Endpoint**: Empty (uses AWS SDK default)

### Backend Configuration

**Patch File**: `backend-patch.yaml`

**Domain Settings**:
```yaml
- name: APP_DOMAIN
  value: "your-domain.com"
- name: APP_BASE_URL
  value: "https://your-domain.com"
- name: DEV_SERVER_BASE_URL
  value: "https://*.your-domain.com"
- name: CORS_ORIGINS
  value: "https://your-domain.com,https://*.your-domain.com"
- name: ALLOWED_HOSTS
  value: "your-domain.com,*.your-domain.com"
```

**Kubernetes Settings**:
```yaml
- name: K8S_INGRESS_DOMAIN
  value: "your-domain.com"
- name: K8S_DEVSERVER_IMAGE
  value: "<AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-devserver:latest"
- name: K8S_REGISTRY_URL
  value: "<AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com"
- name: K8S_IMAGE_PULL_POLICY
  value: "Always"
- name: K8S_WILDCARD_TLS_SECRET
  value: "tesslate-wildcard-tls"
```

**Additional env vars** (added to `aws-base/backend-patch.yaml`):
```yaml
- name: DISCORD_WEBHOOK_URL
  valueFrom: ...
- name: AGENT_DISCORD_WEBHOOK_URL
  valueFrom: ...
- name: TAVILY_API_KEY
  valueFrom: ...
```

**S3 Settings**:
```yaml
- name: S3_ENDPOINT_URL
  value: ""  # Empty for AWS native
- name: S3_BUCKET_NAME
  value: "tesslate-projects-production-7761157a"
- name: S3_REGION
  value: "us-east-1"
```

**Cookie Settings**:
```yaml
- name: COOKIE_SECURE
  value: "true"
- name: COOKIE_SAMESITE
  value: "lax"
- name: COOKIE_DOMAIN
  value: ".your-domain.com"  # Allows subdomains
```

**Resources**:
```yaml
resources:
  requests:
    memory: "512Mi"
    cpu: "250m"
  limits:
    memory: "2Gi"
    cpu: "2000m"
```

**Replicas**: 1 (CRITICAL - tasks stored in-memory, scaling requires distributed state)

**Beta Overlay** (`aws-beta/`):
- Custom replica counts
- Environment-specific resource requests/limits
- Rollout strategy patches (e.g., `maxSurge`, `maxUnavailable`)

### Frontend Configuration

**Resources**:
```yaml
resources:
  requests:
    memory: "128Mi"
    cpu: "50m"
  limits:
    memory: "256Mi"
    cpu: "200m"
```

**Replicas**: 2 (can scale, stateless)

### Ingress Configuration

**Patch File**: `ingress-patch.yaml`

**Host**: `your-domain.com`

**TLS**:
```yaml
spec:
  tls:
  - hosts:
    - your-domain.com
    - "*.your-domain.com"  # Wildcard for user projects
    secretName: tesslate-wildcard-tls
```

**Certificate**: Managed by cert-manager with Cloudflare DNS challenge

**Annotations**:
```yaml
cert-manager.io/cluster-issuer: letsencrypt-prod
nginx.ingress.kubernetes.io/ssl-redirect: "true"
```

## Secrets Management

Secrets created manually via kubectl (not in git).

### tesslate-app-secrets

```bash
kubectl create secret generic tesslate-app-secrets -n tesslate \
  --from-literal=SECRET_KEY=xxx \
  --from-literal=DATABASE_URL=postgresql+asyncpg://tesslate_user:xxx@postgres:5432/tesslate_prod \
  --from-literal=LITELLM_API_BASE=https://your-litellm.com \
  --from-literal=LITELLM_MASTER_KEY=xxx \
  --from-literal=LITELLM_DEFAULT_MODELS=claude-sonnet-4.6,claude-opus-4.6 \
  --from-literal=APP_DOMAIN=your-domain.com \
  --from-literal=APP_BASE_URL=https://your-domain.com \
  --from-literal=DEV_SERVER_BASE_URL=https://*.your-domain.com \
  --from-literal=CORS_ORIGINS=https://your-domain.com,https://*.your-domain.com \
  --from-literal=ALLOWED_HOSTS=your-domain.com,*.your-domain.com
```

### postgres-secret

```bash
kubectl create secret generic postgres-secret -n tesslate \
  --from-literal=POSTGRES_DB=tesslate_prod \
  --from-literal=POSTGRES_USER=tesslate_user \
  --from-literal=POSTGRES_PASSWORD=xxx
```

### s3-credentials

```bash
# For AWS with IRSA, leave credentials empty (uses IAM role)
kubectl create secret generic s3-credentials -n tesslate \
  --from-literal=S3_ACCESS_KEY_ID= \
  --from-literal=S3_SECRET_ACCESS_KEY= \
  --from-literal=S3_BUCKET_NAME=tesslate-projects-production-7761157a \
  --from-literal=S3_ENDPOINT_URL= \
  --from-literal=S3_REGION=us-east-1
```

## Deployment Procedure

### Initial Setup

1. **Provision infrastructure** (Terraform):
```bash
cd k8s/terraform/aws
terraform init
terraform apply
```

2. **Configure kubectl**:
```bash
aws eks update-kubeconfig --region us-east-1 --name <EKS_CLUSTER_NAME>
```

3. **Create secrets** (see above)

4. **Build and push images** (see Images section)

5. **Deploy platform**:
```bash
kubectl apply -k k8s/overlays/aws
```

6. **Verify**:
```bash
kubectl get pods -n tesslate
kubectl logs -n tesslate deployment/tesslate-backend
```

7. **Access**: `https://your-domain.com`

### Updating Deployment

**Code changes**:
```bash
# Always use --no-cache to ensure changes are included
docker build --no-cache -t tesslate-backend:latest -f orchestrator/Dockerfile .
docker tag tesslate-backend:latest <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend:latest
docker push <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend:latest

# Delete pod (pulls new image because imagePullPolicy: Always)
kubectl delete pod -n tesslate -l app=tesslate-backend

# CRITICAL: Restart ingress controller after backend changes
kubectl rollout restart deployment/ingress-nginx-controller -n ingress-nginx
```

**Manifest changes**:
```bash
kubectl apply -k k8s/overlays/aws
```

## Troubleshooting

### ImagePullBackOff

**Check ECR**:
```bash
aws ecr describe-images --repository-name tesslate-backend --region us-east-1
```

**Verify credentials**:
```bash
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com
```

### User Project 503 Errors

**Check pod status**:
```bash
kubectl get pods -n proj-{uuid}
kubectl logs -n proj-{uuid} {pod-name} -c dev-server
kubectl logs -n proj-{uuid} {pod-name} -c hydrate-project
```

**Check ingress**:
```bash
kubectl get ingress -n proj-{uuid}
kubectl describe ingress -n proj-{uuid}
```

**Restart NGINX**:
```bash
kubectl rollout restart deployment/ingress-nginx-controller -n ingress-nginx
```

### Certificate Issues

**Check cert-manager**:
```bash
kubectl get certificate -n tesslate
kubectl describe certificate tesslate-wildcard-tls -n tesslate
kubectl logs -n cert-manager deployment/cert-manager --tail=50
```

**Force renewal**:
```bash
kubectl delete certificate tesslate-wildcard-tls -n tesslate
kubectl apply -k k8s/overlays/aws
```

### S3 Access Issues

**Check IRSA**:
```bash
kubectl describe sa -n tesslate tesslate-backend-sa
# Should have annotation: eks.amazonaws.com/role-arn
```

**Check IAM role**:
```bash
aws iam get-role --role-name tesslate-backend-s3-access
```

## Best Practices

1. **Always --no-cache on builds**: Ensures code changes are included
2. **Delete pods after push**: Forces pull of new image
3. **Restart ingress after backend changes**: Clears endpoint cache
4. **Monitor costs**: EBS volumes and S3 storage add up
5. **Use IRSA, not credentials**: More secure, rotates automatically
6. **Test in Minikube first**: Catch issues before production
7. **Keep secrets out of git**: Use imperative kubectl create

## Monitoring

### Resource Usage

```bash
kubectl top pods -n tesslate
kubectl top nodes
```

### Logs

```bash
kubectl logs -n tesslate deployment/tesslate-backend -f
kubectl logs -n tesslate deployment/tesslate-frontend
```

### Events

```bash
kubectl get events -n tesslate --sort-by='.lastTimestamp'
```
