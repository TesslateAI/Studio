# =============================================================================
# Terraform Backend Configuration - Shared Resources
# =============================================================================
# Usage: terraform init -backend-config=backend.hcl
# =============================================================================

bucket         = "<TERRAFORM_STATE_BUCKET>"
key            = "shared/terraform.tfstate"
region         = "us-east-1"
encrypt        = true
dynamodb_table = "<AWS_IAM_USER>-locks"
