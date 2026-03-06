# Terraform Secrets - Quick Start Guide

## For Team Members (Daily Use)

```bash
# Download tfvars from AWS (one time or when secrets change)
./scripts/terraform/secrets.sh production

# Run terraform - uses the downloaded file
./scripts/aws-deploy.sh plan production
./scripts/aws-deploy.sh apply production
```

**Note:** You must download tfvars before running terraform. Re-download when secrets are updated.

## First Time Setup

### Prerequisites

1. **Install AWS CLI:**
   ```bash
   aws --version  # Check if installed
   # If missing: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html
   ```

2. **Configure AWS credentials:**
   ```bash
   aws configure
   # Enter <AWS_IAM_USER> user credentials
   # Access Key ID: [from team lead]
   # Secret Access Key: [from team lead]
   # Region: us-east-1
   ```

3. **Verify credentials work:**
   ```bash
   aws sts get-caller-identity
   # Should show your AWS user info
   ```

### Download Secrets

```bash
# Download terraform variables from AWS
./scripts/terraform/secrets.sh production

# This creates: k8s/terraform/aws/terraform.production.tfvars

# Now you can run terraform
./scripts/aws-deploy.sh plan production
```

**Note:** ECR repositories are managed separately by the shared stack (`k8s/terraform/shared/`). Run `./scripts/aws-deploy.sh plan shared` to manage ECR. See `docs/infrastructure/terraform/ecr.md`.

## For Admins (Initial Upload)

### Upload Existing tfvars to AWS

```bash
# If you have local tfvars files, upload them to AWS
./scripts/terraform/secrets.sh upload production
./scripts/terraform/secrets.sh upload beta

# Now team can download
```

## Updating Secrets

### Method 1: Edit Local and Upload

```bash
# 1. Download latest (avoid conflicts)
./scripts/terraform/secrets.sh production

# 2. Edit local file
vim k8s/terraform/aws/terraform.production.tfvars

# 3. Upload to AWS
./scripts/terraform/secrets.sh upload production

# 4. Notify team to download latest
```

### Method 2: View/Edit in AWS Console

```bash
# View current content
./scripts/terraform/secrets.sh view production

# Or edit in AWS Console:
# 1. Go to AWS Secrets Manager
# 2. Find: tesslate/terraform/production
# 3. Edit the tfvars content
# 4. Save
```

## Troubleshooting

### "AWS credentials not configured"
```bash
aws configure
# Enter credentials and set region to us-east-1
```

### "Failed to fetch secret"
```bash
# Secret doesn't exist in AWS yet
# Admin needs to upload:
./scripts/terraform/secrets.sh upload production
```

### "Permission denied"
```bash
# Your AWS user needs secretsmanager permissions
# Contact admin to grant permissions
```

### Terraform can't find tfvars
```bash
# Download from AWS first
./scripts/terraform/secrets.sh production

# Then use terraform
./scripts/aws-deploy.sh plan production
```

## Commands Reference

| Command | Purpose |
|---------|---------|
| `./scripts/terraform/secrets.sh {env}` | Download tfvars from AWS (default) |
| `./scripts/terraform/secrets.sh download {env}` | Download tfvars from AWS (explicit) |
| `./scripts/terraform/secrets.sh upload {env}` | Upload local tfvars to AWS |
| `./scripts/terraform/secrets.sh view {env}` | View tfvars in AWS |
| `./scripts/aws-deploy.sh plan {env}` | Plan changes (requires tfvars) |
| `./scripts/aws-deploy.sh apply {env}` | Apply changes (requires tfvars) |

## How It Works

1. Tfvars files stored in AWS Secrets Manager (raw content)
2. `secrets.sh` downloads and saves to local file
3. Terraform uses local file with `-var-file` flag
4. Local file persists - reuse for multiple terraform runs
5. Re-download manually when secrets are updated

**Simple!** Download once, use many times. Manual control over when to sync.

## Full Documentation

- **Detailed docs**: [scripts/terraform/README.md](README.md)
- **Project docs**: [CLAUDE.md](../../CLAUDE.md)
