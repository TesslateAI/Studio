# =============================================================================
# Tesslate Studio - Shared AWS Resources
# =============================================================================
# Manages resources shared across all environments:
# - ECR repositories (backend, frontend, devserver)
# - ECR lifecycle policies
# - ECR pull-through cache rules
#
# Both production and beta push different image tags to the SAME repos.
# This stack has its own state file, independent of environment stacks.
# =============================================================================

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {}
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = var.project_name
      ManagedBy = "terraform"
      Stack     = "shared"
    }
  }
}

data "aws_caller_identity" "current" {}
