# ECR Container Registry

Amazon ECR repositories for Tesslate Studio images.

**File**: `c:/Users/Smirk/Downloads/Tesslate-Studio/k8s/terraform/aws/ecr.tf`

## Repositories

### tesslate-backend

**URI**: `<AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend`
**Purpose**: FastAPI orchestrator image
**Dockerfile**: `orchestrator/Dockerfile`

### tesslate-frontend

**URI**: `<AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-frontend`
**Purpose**: React + NGINX frontend image
**Dockerfile**: `app/Dockerfile.prod`

### tesslate-devserver

**URI**: `<AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-devserver`
**Purpose**: User project dev environment image
**Dockerfile**: `orchestrator/Dockerfile.devserver`

## Configuration

### Image Scanning

**Enabled**: `scan_on_push = true`

Scans images for vulnerabilities (CVEs) on push.

View scan results:
```bash
aws ecr describe-image-scan-findings --repository-name tesslate-backend --image-id imageTag=latest
```

### Encryption

**Type**: AES256 (AWS-managed keys)

For KMS encryption:
```hcl
encryption_configuration {
  encryption_type = "KMS"
  kms_key = aws_kms_key.ecr.arn
}
```

### Image Tag Mutability

**Setting**: `MUTABLE`

Allows pushing to same tag (e.g., :latest multiple times)

For immutable tags (production):
```hcl
image_tag_mutability = "IMMUTABLE"
```

## Lifecycle Policies

Automatically delete old images to save storage costs.

**Rules** (priority order):

1. **Keep last 30 tagged images** (priority 1)
   - Tags: v*, release*
   - Type: imageCountMoreThan
   - Count: 30

2. **Delete untagged images after 7 days** (priority 2)
   - Status: untagged
   - Type: sinceImagePushed
   - Days: 7

3. **Keep latest 10 images** (priority 3)
   - Status: any (catch-all)
   - Type: imageCountMoreThan
   - Count: 10

**Note**: Rules with `tagStatus=any` MUST have lowest priority (highest number).

## Usage

### Login to ECR

```bash
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com
```

**Token expires in 12 hours**, re-login if needed.

### Build and Push

```bash
# Build
docker build --no-cache -t tesslate-backend:latest -f orchestrator/Dockerfile orchestrator/

# Tag
docker tag tesslate-backend:latest <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend:latest

# Push
docker push <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend:latest
```

### Pull Image

```bash
docker pull <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/tesslate-backend:latest
```

Kubernetes automatically pulls when `imagePullPolicy: Always`.

## Pull Through Cache (Optional)

**Purpose**: Cache public images (nginx, postgres) in ECR to avoid rate limits.

**Currently enabled**: Quay.io

**Configuration**:
```hcl
resource "aws_ecr_pull_through_cache_rule" "quay" {
  ecr_repository_prefix = "quay"
  upstream_registry_url = "quay.io"
}
```

**Usage**:
```yaml
# Instead of: quay.io/organization/image:tag
# Use: <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/quay/organization/image:tag
image: <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/quay/prometheus/node-exporter:latest
```

**Note**: Docker Hub and GitHub Container Registry require authentication via Secrets Manager.

## Monitoring

### List Images

```bash
aws ecr list-images --repository-name tesslate-backend
```

### Image Details

```bash
aws ecr describe-images --repository-name tesslate-backend --image-ids imageTag=latest
```

### Repository Size

```bash
aws ecr describe-repositories --repository-names tesslate-backend --query 'repositories[0].repositorySizeInBytes'
```

## Troubleshooting

### Authentication Failed

**Symptom**: `no basic auth credentials`

**Fix**: Re-login to ECR (token expired)
```bash
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <AWS_ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com
```

### Image Not Found

**Symptom**: `repository does not exist`

**Fix**: Ensure repository created by Terraform
```bash
terraform apply
```

### Lifecycle Policy Not Working

**Symptom**: Old images not being deleted

**Check policy**:
```bash
aws ecr get-lifecycle-policy --repository-name tesslate-backend
```

**Dry run**:
```bash
aws ecr start-lifecycle-policy-preview --repository-name tesslate-backend --lifecycle-policy-text file://policy.json
```

## Cost Optimization

**Storage**: $0.10/GB/month

**Tips**:
1. Use lifecycle policies to delete old images
2. Don't push large images (optimize Dockerfiles)
3. Use multi-stage builds to reduce image size
4. Delete unused repositories

**Example**: 10 images × 500MB = 5GB = $0.50/month

## Security

### Scan on Push

View vulnerabilities:
```bash
aws ecr describe-image-scan-findings --repository-name tesslate-backend --image-id imageTag=latest
```

### Image Signing (Future)

Use AWS Signer or Cosign to sign images and verify in admission controller.

### Private Registry

ECR is private by default. For public access, use ECR Public instead.

## Related Documentation

- [README.md](README.md): Terraform overview
- [eks.md](eks.md): EKS cluster
- [s3.md](s3.md): Project storage
- AWS ECR: https://docs.aws.amazon.com/ecr/
