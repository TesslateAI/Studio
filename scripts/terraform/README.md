# Terraform Secrets Management

Manages environment-specific Terraform variables stored in AWS Secrets Manager.

## Overview

Terraform tfvars files are stored in **AWS Secrets Manager** and downloaded locally before running Terraform commands.

**Key Benefits:**
- **Centralized storage**: Team members download from AWS instead of manual sharing
- **No secrets in git**: tfvars files are in `.gitignore` and never committed
- **Environment support**: Separate secrets for production and beta
- **Simple workflow**: Download once, use with standard Terraform commands

## Quick Start

### For Team Members

```bash
# 1. Download tfvars from AWS (one time per environment)
./scripts/terraform/secrets.sh production

# 2. Run terraform commands - they use the downloaded file
./scripts/aws-deploy.sh plan production
./scripts/aws-deploy.sh apply production
```

Download tfvars manually before running terraform commands.

## Files

| File | Purpose |
|------|---------|
| `secrets.sh` | Manage tfvars: download (default), upload, and view |

## AWS Secrets Manager Structure

Secrets are stored as **raw tfvars file content** in AWS Secrets Manager:

| Secret Name | Environment | Content |
|-------------|-------------|---------|
| `tesslate/terraform/production` | Production | Raw content of terraform.production.tfvars |
| `tesslate/terraform/beta` | Beta | Raw content of terraform.beta.tfvars |

## Basic Usage

### Download tfvars from AWS

```bash
# Download production tfvars
./scripts/terraform/secrets.sh production

# Download beta tfvars
./scripts/terraform/secrets.sh beta

# This creates: k8s/terraform/aws/terraform.{env}.tfvars
```

### Run Terraform

```bash
# After downloading, run terraform commands
./scripts/aws-deploy.sh plan production
./scripts/aws-deploy.sh apply production
```

## Managing Secrets

### Upload Local tfvars to AWS

```bash
# Upload your local file to AWS
./scripts/terraform/secrets.sh upload production

# Now team members can download it
```

### Download from AWS

```bash
# Download and save to local file
./scripts/terraform/secrets.sh download production

# Or use the shorter command
./scripts/terraform/secrets.sh production
```

### View Content in AWS

```bash
# View tfvars content from AWS without downloading
./scripts/terraform/secrets.sh view production
```

## Updating Secrets

### Option 1: Edit Local File and Upload

```bash
# 1. Download latest version first (to avoid conflicts)
./scripts/terraform/secrets.sh production

# 2. Edit local file
vim k8s/terraform/aws/terraform.production.tfvars

# 3. Upload back to AWS
./scripts/terraform/secrets.sh upload production

# 4. Notify team to download latest
```

### Option 2: Edit in AWS Console

1. Go to AWS Secrets Manager console
2. Find secret: `tesslate/terraform/{environment}`
3. Click "Retrieve secret value"
4. Click "Edit"
5. Modify the tfvars content
6. Click "Save"

Changes take effect immediately - team members just need to download latest.

## Initial Setup (First Time)

### If You Have Existing tfvars Files

```bash
# Upload to AWS Secrets Manager
./scripts/terraform/secrets.sh upload production
./scripts/terraform/secrets.sh upload beta

# Test downloading
./scripts/terraform/secrets.sh production

# Test terraform
./scripts/aws-deploy.sh plan production
```

### If Starting Fresh

1. Create tfvars file locally:
   ```bash
   vim k8s/terraform/aws/terraform.production.tfvars
   # Add all your variables: environment, domain_name, passwords, API keys, etc.
   ```

2. Upload to AWS:
   ```bash
   ./scripts/terraform/secrets.sh upload production
   ```

3. Team members can now download:
   ```bash
   ./scripts/terraform/secrets.sh production
   ```

## Workflow

### For Admin (Managing Secrets)

```bash
# Make changes locally
vim k8s/terraform/aws/terraform.production.tfvars

# Upload to AWS
./scripts/terraform/secrets.sh upload production

# Notify team in Slack/email:
# "Updated production secrets, please re-download:
#  ./scripts/terraform/secrets.sh production"
```

### For Team Members

```bash
# Download latest secrets
./scripts/terraform/secrets.sh production

# Use terraform normally
./scripts/aws-deploy.sh plan production
./scripts/aws-deploy.sh apply production
```

## Required IAM Permissions

The AWS user/role needs:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue",
        "secretsmanager:PutSecretValue",
        "secretsmanager:CreateSecret",
        "secretsmanager:DescribeSecret"
      ],
      "Resource": "arn:aws:secretsmanager:us-east-1:*:secret:tesslate/terraform/*"
    }
  ]
}
```

The `<AWS_IAM_USER>` IAM user has these permissions.

## Environment-Specific Configuration

Some variables must differ between environments. Key settings:

| Variable | Production | Beta | Purpose |
|----------|-----------|------|---------|
| `environment` | `"production"` | `"beta"` | Resource naming, image tags |
| `domain_name` | `"your-domain.com"` | `"your-domain.com"` | Application domain |
| `image_tag` | `"production"` | `"beta"` | Docker image tag pushed to ECR |

**Note**: ECR repositories are managed by the **shared stack** (`k8s/terraform/shared/`), not by environment stacks. See `docs/infrastructure/terraform/ecr.md`.

## Security Best Practices

1. **Never commit .tfvars files to git**
   - Already in `.gitignore`: `k8s/terraform/**/*.tfvars`

2. **Download fresh copy before editing**
   - Prevents overwriting other team members' changes

3. **Notify team after uploading changes**
   - So they download the latest version

4. **Rotate sensitive values regularly**
   - Update locally, upload to AWS, team downloads latest

5. **Use least-privilege IAM roles**
   - Grant secretsmanager access only to terraform users

6. **Enable CloudTrail**
   - Audit who accessed/modified secrets and when

## Troubleshooting

### AWS CLI not installed

Install from: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html

### AWS credentials not configured

```bash
aws configure
# Or use environment variables:
export AWS_ACCESS_KEY_ID="your-key"
export AWS_SECRET_ACCESS_KEY="your-secret"
export AWS_REGION="us-east-1"
```

### Secret not found in AWS

```bash
# Upload it first
./scripts/terraform/secrets.sh upload production
```

### Permission denied

Verify your AWS user has the required IAM permissions (see above).

### Terraform can't find tfvars file

```bash
# Download it from AWS
./scripts/terraform/secrets.sh production

# Or use aws-deploy.sh which downloads automatically
./scripts/aws-deploy.sh plan production
```

## How It Works

### Download and Use Workflow

1. **Download tfvars** from AWS Secrets Manager:
   ```bash
   ./scripts/terraform/secrets.sh production
   ```

2. **File is saved** to: `k8s/terraform/aws/terraform.production.tfvars`

3. **Run terraform** with the downloaded file:
   ```bash
   ./scripts/aws-deploy.sh plan production
   # Terraform uses: -var-file="terraform.production.tfvars"
   ```

4. **Local file persists** - use it for multiple terraform commands until secrets change

5. **Re-download** when secrets are updated by team members

## Commands Reference

| Command | Purpose |
|---------|---------|
| `./scripts/terraform/secrets.sh {env}` | Download tfvars from AWS (default command) |
| `./scripts/terraform/secrets.sh download {env}` | Download tfvars from AWS (explicit) |
| `./scripts/terraform/secrets.sh upload {env}` | Upload local tfvars to AWS |
| `./scripts/terraform/secrets.sh view {env}` | View tfvars content in AWS |
| `./scripts/aws-deploy.sh plan {env}` | Plan changes (requires downloaded tfvars) |
| `./scripts/aws-deploy.sh apply {env}` | Apply changes (requires downloaded tfvars) |

## Related Documentation

- [k8s/terraform/aws/README.md](../../k8s/terraform/aws/README.md) - Terraform deployment guide
- [CLAUDE.md](../../CLAUDE.md) - Project documentation (see "Terraform Deployment & Configuration")
- [scripts/aws-deploy.sh](../aws-deploy.sh) - Main deployment script
- [QUICKSTART.md](QUICKSTART.md) - Quick reference guide
