# OpenSail - AWS EKS Deployment Guide

This guide walks you through deploying OpenSail on AWS EKS using Terraform.

## Architecture Overview

```
                        ┌─────────────────────────────────────────┐
                        │           Cloudflare DNS                │
                        │   your-domain.com → NLB                    │
                        │   *.your-domain.com → NLB                  │
                        └─────────────────┬───────────────────────┘
                                          │
                        ┌─────────────────▼───────────────────────┐
                        │        AWS Network Load Balancer        │
                        └─────────────────┬───────────────────────┘
                                          │
┌─────────────────────────────────────────▼─────────────────────────────────────────┐
│                              AWS VPC (10.0.0.0/16)                                 │
│  ┌──────────────────────────────────────────────────────────────────────────────┐ │
│  │                           EKS Cluster                                         │ │
│  │  ┌─────────────────────────────────────────────────────────────────────────┐ │ │
│  │  │                    NGINX Ingress Controller                              │ │ │
│  │  │  Routes: your-domain.com → tesslate namespace                               │ │ │
│  │  │          *.your-domain.com → proj-* namespaces                              │ │ │
│  │  └─────────────────────────────────────────────────────────────────────────┘ │ │
│  │                                                                               │ │
│  │  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────────┐    │ │
│  │  │ tesslate         │  │ cert-manager     │  │ external-dns             │    │ │
│  │  │ namespace        │  │ namespace        │  │ namespace                │    │ │
│  │  │ - backend        │  │ - TLS certs via  │  │ - Auto DNS via           │    │ │
│  │  │ - frontend       │  │   Let's Encrypt  │  │   Cloudflare API         │    │ │
│  │  │ - postgres       │  │   + Cloudflare   │  │                          │    │ │
│  │  └──────────────────┘  └──────────────────┘  └──────────────────────────┘    │ │
│  │                                                                               │ │
│  │  ┌──────────────────────────────────────────────────────────────────────┐    │ │
│  │  │ proj-* namespaces (dynamically created per user project)              │    │ │
│  │  │ - file-manager pod (always running)                                   │    │ │
│  │  │ - dev-container pods (when started)                                   │    │ │
│  │  │ - PVC (gp3 EBS storage)                                               │    │ │
│  │  └──────────────────────────────────────────────────────────────────────┘    │ │
│  └───────────────────────────────────────────────────────────────────────────────┘ │
│                                                                                     │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────────────────┐  │
│  │ S3 Bucket        │  │ ECR              │  │ IAM Roles (IRSA)                 │  │
│  │ - Project        │  │ - backend        │  │ - tesslate-backend (S3 access)   │  │
│  │   hibernation    │  │ - frontend       │  │ - ebs-csi-driver                 │  │
│  │                  │  │ - devserver      │  │ - cluster-autoscaler             │  │
│  └──────────────────┘  └──────────────────┘  └──────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

## Prerequisites

1. **AWS CLI** configured with appropriate credentials
   ```bash
   aws configure
   # Or use environment variables:
   export AWS_ACCESS_KEY_ID="your-key"
   export AWS_SECRET_ACCESS_KEY="your-secret"
   export AWS_REGION="us-east-1"
   ```

2. **Terraform** >= 1.5.0
   ```bash
   # macOS
   brew install terraform

   # Windows (chocolatey)
   choco install terraform

   # Linux
   curl -fsSL https://apt.releases.hashicorp.com/gpg | sudo apt-key add -
   sudo apt-add-repository "deb [arch=amd64] https://apt.releases.hashicorp.com $(lsb_release -cs) main"
   sudo apt-get update && sudo apt-get install terraform
   ```

3. **kubectl** for Kubernetes management
   ```bash
   # macOS
   brew install kubectl

   # Windows
   choco install kubernetes-cli
   ```

4. **Docker** for building images

5. **Cloudflare Account** with your domain configured
   - Create an API token at: https://dash.cloudflare.com/profile/api-tokens
   - Required permissions: `Zone:DNS:Edit`, `Zone:Zone:Read`

## Multi-Environment Support

This Terraform configuration supports **separate production and beta environments** using:

- **Separate backend state files**: Each environment has its own state file in S3
  - Production: `s3://<TERRAFORM_STATE_BUCKET>/production/terraform.tfstate`
  - Beta: `s3://<TERRAFORM_STATE_BUCKET>/beta/terraform.tfstate`

- **Environment-specific tfvars**: Variables are stored in AWS Secrets Manager
  - Download with: `./scripts/terraform/secrets.sh production` or `./scripts/terraform/secrets.sh beta`

- **Helper script**: `scripts/aws-deploy.sh` manages initialization and deployment
  - Ensures correct backend config is used for each environment
  - Prevents accidental cross-environment changes

### Shared Resources (ECR)

ECR repositories (`tesslate-backend`, `tesslate-frontend`, `tesslate-devserver`) are **shared across environments** — both push different image tags (`:beta`, `:production`) to the same repos.

ECR is managed by a **dedicated shared stack** (`k8s/terraform/shared/`) with its own state file:

```bash
./scripts/aws-deploy.sh init shared
./scripts/aws-deploy.sh plan shared
./scripts/aws-deploy.sh apply shared
```

Per-environment stacks reference ECR via computed URL locals (`local.ecr_*_url` in `aws/ecr.tf`) — no cross-state dependencies needed.

## Deployment Steps

### Step 1: Configure Variables

```bash
cd k8s/terraform/aws

# Edit terraform.tfvars with your values
# IMPORTANT: Fill in all required fields marked with comments
```

Key variables to set:
- `cloudflare_api_token` - Your Cloudflare API token
- `postgres_password` - Generate with `openssl rand -hex 32`
- `app_secret_key` - Generate with `python -c "import secrets; print(secrets.token_hex(32))"`
- `litellm_api_base` and `litellm_master_key` - Your LiteLLM instance

### Step 2: Pull Environment Variables from AWS Secrets Manager

```bash
cd ../../../scripts/terraform

# Pull secrets for your environment
./sync_tfvars.sh pull production  # For production deployment
# OR
./sync_tfvars.sh pull beta         # For beta deployment

cd ../../k8s/terraform/aws
```

This creates `terraform.production.tfvars` or `terraform.beta.tfvars` with secrets stored in AWS Secrets Manager.

**Note**: Backend configuration is environment-specific and stored in `backend-{env}.hcl` files (not in main.tf).

### Step 3: Initialize Terraform with Environment-Specific Backend

```bash
# For production
./deploy.sh init production

# OR for beta
./deploy.sh init beta
```

This initializes Terraform with the correct backend configuration:
- Production: `s3://<TERRAFORM_STATE_BUCKET>/production/terraform.tfstate`
- Beta: `s3://<TERRAFORM_STATE_BUCKET>/beta/terraform.tfstate`

### Step 4: Review the Plan

```bash
# For production
./deploy.sh plan production

# OR for beta
./deploy.sh plan beta
```

Review the resources that will be created:
- VPC with public/private subnets
- EKS cluster with node groups
- S3 bucket for project storage
- ECR repositories
- IAM roles with IRSA
- NGINX Ingress, cert-manager, external-dns

### Step 5: Apply Infrastructure

```bash
# For production (requires confirmation)
./deploy.sh apply production

# OR for beta
./deploy.sh apply beta
```

This takes approximately 15-20 minutes. Grab a coffee!

### Step 6: Configure kubectl

```bash
# Get the command from Terraform output
./deploy.sh output {environment}

# Run the configure_kubectl_command (example):
aws eks update-kubeconfig --name tesslate-production-eks --region us-east-1
```

### Step 7: Build and Push Docker Images

```bash
# Login to ECR
$(terraform output -raw ecr_login_command)

# Get ECR URLs
export BACKEND_REPO=$(terraform output -raw ecr_backend_repository_url)
export FRONTEND_REPO=$(terraform output -raw ecr_frontend_repository_url)
export DEVSERVER_REPO=$(terraform output -raw ecr_devserver_repository_url)

# Build and push (from project root)
cd ../../../  # Back to project root

# Backend
docker build -t $BACKEND_REPO:latest -f orchestrator/Dockerfile orchestrator/
docker push $BACKEND_REPO:latest

# Frontend
docker build -t $FRONTEND_REPO:latest -f app/Dockerfile.prod app/
docker push $FRONTEND_REPO:latest

# Devserver
docker build -t $DEVSERVER_REPO:latest -f orchestrator/Dockerfile.devserver orchestrator/
docker push $DEVSERVER_REPO:latest
```

### Step 8: Update Kustomization with ECR URLs

```bash
cd k8s/overlays/aws

# Update kustomization.yaml with your ECR URLs
# Replace ACCOUNT_ID and REGION with actual values from terraform output
```

### Step 9: Deploy Tesslate Application

```bash
kubectl apply -k k8s/overlays/aws
```

### Step 10: Configure Cloudflare DNS

After deployment, get the NLB DNS name:

```bash
kubectl get svc -n ingress-nginx ingress-nginx-controller -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'
```

In Cloudflare Dashboard:
1. Go to DNS settings for your-domain.com
2. Add records:
   - `your-domain.com` → CNAME to NLB DNS name (Proxied: Yes)
   - `*.your-domain.com` → CNAME to NLB DNS name (Proxied: Yes)
3. SSL/TLS settings:
   - Mode: Full (strict)
   - Edge Certificates: Enable Universal SSL

### Step 11: Verify Deployment

```bash
# Check all pods are running
kubectl get pods -n tesslate
kubectl get pods -n ingress-nginx
kubectl get pods -n cert-manager
kubectl get pods -n external-dns

# Check certificate is issued
kubectl get certificate -n tesslate

# Check ingress
kubectl get ingress -n tesslate

# Test the application
curl -I https://your-domain.com
```

## Post-Deployment

### Monitoring Logs

```bash
# Backend logs
kubectl logs -f deployment/tesslate-backend -n tesslate

# Frontend logs
kubectl logs -f deployment/tesslate-frontend -n tesslate

# Ingress controller logs
kubectl logs -f deployment/ingress-nginx-controller -n ingress-nginx
```

### Scaling

```bash
# Scale backend
kubectl scale deployment/tesslate-backend -n tesslate --replicas=3

# Or let cluster-autoscaler handle it automatically
```

### Updating Application

```bash
# Rebuild and push new images
docker build -t $BACKEND_REPO:latest -f orchestrator/Dockerfile orchestrator/
docker push $BACKEND_REPO:latest

# Restart deployment to pull new image
kubectl rollout restart deployment/tesslate-backend -n tesslate
```

## Troubleshooting

### Certificate Not Issuing

```bash
# Check cert-manager logs
kubectl logs -f deployment/cert-manager -n cert-manager

# Check certificate status
kubectl describe certificate tesslate-wildcard-tls -n tesslate

# Check certificate request
kubectl get certificaterequest -n tesslate
```

### DNS Not Resolving

```bash
# Check external-dns logs
kubectl logs -f deployment/external-dns -n external-dns

# Verify Cloudflare API token permissions
```

### Pods Stuck in Pending

```bash
# Check node resources
kubectl describe nodes

# Check if cluster-autoscaler is working
kubectl logs -f deployment/cluster-autoscaler -n kube-system
```

### S3 Access Issues

```bash
# Verify IRSA is configured correctly
kubectl describe sa tesslate-backend-sa -n tesslate

# Check if pod has AWS credentials
kubectl exec -it deployment/tesslate-backend -n tesslate -- env | grep AWS
```

## Cost Optimization

- Use `single_nat_gateway = true` for non-production ($32/month savings per AZ)
- Use Spot instances for user project workloads
- Enable S3 lifecycle policies (already configured)
- Set appropriate node group sizes

## Cleanup

To destroy all resources:

```bash
# First, delete all user project namespaces
kubectl get ns | grep proj- | awk '{print $1}' | xargs kubectl delete ns

# Then destroy Terraform resources for the environment
./deploy.sh destroy production  # Requires typing "destroy production" to confirm
# OR
./deploy.sh destroy beta
```

**WARNING**: This will delete all data including S3 bucket contents if `s3_force_destroy = true`.

## Security Considerations

- All secrets are managed via Terraform and stored in Kubernetes secrets
- S3 access uses IRSA (no static credentials)
- TLS certificates are automatically managed by cert-manager
- Network policies isolate user project namespaces
- EBS volumes are encrypted by default

## Support

For issues, check:
1. This README troubleshooting section
2. [OpenSail issues](https://github.com/your-repo/issues)
3. AWS EKS documentation
4. Terraform AWS provider documentation
