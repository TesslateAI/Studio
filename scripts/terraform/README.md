# Terraform Variables Sync

Manages environment-specific Terraform variables stored in AWS Secrets Manager.

## Why AWS Secrets Manager?

- **Security**: Sensitive values (API keys, passwords) never committed to git
- **Team Collaboration**: Team members pull latest values without manual sharing
- **Version Control**: Track changes to infrastructure secrets
- **Environment Isolation**: Separate secrets for production and beta

## Files

| File | Purpose |
|------|---------|
| `sync_tfvars.sh` | Shell wrapper with convenience commands |
| `sync_tfvars.py` | Python script that interfaces with AWS Secrets Manager |

## Usage

### Pull Secrets from AWS

```bash
# Pull production secrets
./sync_tfvars.sh pull production

# Pull beta secrets
./sync_tfvars.sh pull beta
```

This creates `k8s/terraform/aws/terraform.{environment}.tfvars` with values from AWS Secrets Manager.

### Update Secrets in AWS

```bash
# Edit local tfvars file first
vim ../../k8s/terraform/aws/terraform.production.tfvars

# Push changes to AWS
./sync_tfvars.sh push production
```

**WARNING**: This overwrites secrets in AWS. Confirm before proceeding.

### Initial Setup (First Time)

```bash
# Create local tfvars file with all values
cp ../../k8s/terraform/aws/terraform.tfvars.example ../../k8s/terraform/aws/terraform.production.tfvars
vim ../../k8s/terraform/aws/terraform.production.tfvars  # Fill in values

# Upload to AWS Secrets Manager
./sync_tfvars.sh init production
```

## AWS Secrets Manager Structure

| Secret Name | Environment | Content |
|-------------|-------------|---------|
| `tesslate/terraform/production` | Production | Full terraform.production.tfvars content |
| `tesslate/terraform/beta` | Beta | Full terraform.beta.tfvars content |

## Required IAM Permissions

The AWS user/role running these scripts needs:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue",
        "secretsmanager:PutSecretValue",
        "secretsmanager:CreateSecret"
      ],
      "Resource": "arn:aws:secretsmanager:us-east-1:*:secret:tesslate/terraform/*"
    }
  ]
}
```

## Workflow

### Team Member Setup

```bash
# 1. Clone repo
git clone <repo-url>
cd tesslate-studio/scripts/terraform

# 2. Configure AWS credentials
aws configure  # Or use environment variables

# 3. Pull secrets for environment you're working on
./sync_tfvars.sh pull production

# 4. Use terraform with pulled vars
cd ../../k8s/terraform/aws
./deploy.sh init production
./deploy.sh plan production
```

### Updating Secrets

```bash
# 1. Pull latest to avoid conflicts
./sync_tfvars.sh pull production

# 2. Edit local file
vim ../../k8s/terraform/aws/terraform.production.tfvars

# 3. Test terraform plan to ensure syntax is correct
cd ../../k8s/terraform/aws
./deploy.sh plan production

# 4. Push updated secrets to AWS
cd ../../../scripts/terraform
./sync_tfvars.sh push production
```

## Security Best Practices

1. **Never commit .tfvars files to git**
   - Already in `.gitignore`: `k8s/terraform/**/*.tfvars`
   - Only `.tfvars.example` and `.tfvars.template` are tracked

2. **Rotate sensitive values regularly**
   - Update in local file
   - Push to AWS
   - Apply terraform changes

3. **Use least-privilege IAM roles**
   - Grant secretsmanager access only to terraform users
   - Restrict by resource ARN

4. **Audit secret access**
   - Enable CloudTrail for Secrets Manager API calls
   - Review who accessed secrets and when

## Troubleshooting

### boto3 not installed

```bash
pip3 install boto3
```

### AWS credentials not configured

```bash
aws configure
# Or use environment variables:
export AWS_ACCESS_KEY_ID="your-key"
export AWS_SECRET_ACCESS_KEY="your-secret"
export AWS_REGION="us-east-1"
```

### Secret not found in AWS

Run `init` command to create it:

```bash
./sync_tfvars.sh init production
```

### Permission denied

Verify your AWS user has the required IAM permissions (see above).

## Related Documentation

- [k8s/terraform/aws/README.md](../../k8s/terraform/aws/README.md) - Terraform deployment guide
- [CLAUDE.md](../../CLAUDE.md) - Project documentation (see "Terraform Deployment & Configuration" section)
