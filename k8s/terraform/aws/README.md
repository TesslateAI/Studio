# Tesslate Studio - AWS EKS Deployment Guide

This guide walks you through deploying Tesslate Studio on AWS EKS using Terraform.

## Architecture Overview

```
                        ┌─────────────────────────────────────────┐
                        │           Cloudflare DNS                │
                        │   saipriya.org → NLB                    │
                        │   *.saipriya.org → NLB                  │
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
│  │  │  Routes: saipriya.org → tesslate namespace                               │ │ │
│  │  │          *.saipriya.org → proj-* namespaces                              │ │ │
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

### Step 2: Initialize Terraform

```bash
terraform init
```

This downloads required providers and modules.

### Step 3: Review the Plan

```bash
terraform plan -out=tfplan
```

Review the resources that will be created:
- VPC with public/private subnets
- EKS cluster with node groups
- S3 bucket for project storage
- ECR repositories
- IAM roles with IRSA
- NGINX Ingress, cert-manager, external-dns

### Step 4: Apply Infrastructure

```bash
terraform apply tfplan
```

This takes approximately 15-20 minutes. Grab a coffee!

### Step 5: Configure kubectl

```bash
# Get the command from Terraform output
terraform output configure_kubectl_command

# Run it (example):
aws eks update-kubeconfig --name tesslate-production-eks --region us-east-1
```

### Step 6: Build and Push Docker Images

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

### Step 7: Update Kustomization with ECR URLs

```bash
cd k8s/overlays/aws

# Update kustomization.yaml with your ECR URLs
# Replace ACCOUNT_ID and REGION with actual values from terraform output
```

### Step 8: Deploy Tesslate Application

```bash
kubectl apply -k k8s/overlays/aws
```

### Step 9: Configure Cloudflare DNS

After deployment, get the NLB DNS name:

```bash
kubectl get svc -n ingress-nginx ingress-nginx-controller -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'
```

In Cloudflare Dashboard:
1. Go to DNS settings for saipriya.org
2. Add records:
   - `saipriya.org` → CNAME to NLB DNS name (Proxied: Yes)
   - `*.saipriya.org` → CNAME to NLB DNS name (Proxied: Yes)
3. SSL/TLS settings:
   - Mode: Full (strict)
   - Edge Certificates: Enable Universal SSL

### Step 10: Verify Deployment

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
curl -I https://saipriya.org
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

# Then destroy Terraform resources
terraform destroy
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
2. [Tesslate Studio issues](https://github.com/your-repo/issues)
3. AWS EKS documentation
4. Terraform AWS provider documentation
