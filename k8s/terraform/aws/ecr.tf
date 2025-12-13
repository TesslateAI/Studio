# =============================================================================
# ECR Repositories for Tesslate Studio Container Images
# =============================================================================
# Creates ECR repositories for:
# - tesslate-backend: FastAPI orchestrator
# - tesslate-frontend: React frontend
# - tesslate-devserver: User project dev server
# =============================================================================

# -----------------------------------------------------------------------------
# Backend ECR Repository
# -----------------------------------------------------------------------------
resource "aws_ecr_repository" "backend" {
  name                 = "${var.project_name}-backend"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = merge(local.common_tags, {
    Name      = "${var.project_name}-backend"
    Component = "backend"
  })
}

# -----------------------------------------------------------------------------
# Frontend ECR Repository
# -----------------------------------------------------------------------------
resource "aws_ecr_repository" "frontend" {
  name                 = "${var.project_name}-frontend"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = merge(local.common_tags, {
    Name      = "${var.project_name}-frontend"
    Component = "frontend"
  })
}

# -----------------------------------------------------------------------------
# Devserver ECR Repository
# -----------------------------------------------------------------------------
resource "aws_ecr_repository" "devserver" {
  name                 = "${var.project_name}-devserver"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = merge(local.common_tags, {
    Name      = "${var.project_name}-devserver"
    Component = "devserver"
  })
}

# -----------------------------------------------------------------------------
# ECR Lifecycle Policy (shared by all repos)
# -----------------------------------------------------------------------------
# Note: tagStatus=any rules MUST have the lowest priority (highest number)
locals {
  ecr_lifecycle_policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 30 tagged images"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["v", "release"]
          countType     = "imageCountMoreThan"
          countNumber   = 30
        }
        action = {
          type = "expire"
        }
      },
      {
        rulePriority = 2
        description  = "Remove untagged images older than 7 days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 7
        }
        action = {
          type = "expire"
        }
      },
      {
        # tagStatus=any must have lowest priority (highest number)
        rulePriority = 3
        description  = "Keep latest 10 images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 10
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}

resource "aws_ecr_lifecycle_policy" "backend" {
  repository = aws_ecr_repository.backend.name
  policy     = local.ecr_lifecycle_policy
}

resource "aws_ecr_lifecycle_policy" "frontend" {
  repository = aws_ecr_repository.frontend.name
  policy     = local.ecr_lifecycle_policy
}

resource "aws_ecr_lifecycle_policy" "devserver" {
  repository = aws_ecr_repository.devserver.name
  policy     = local.ecr_lifecycle_policy
}

# -----------------------------------------------------------------------------
# ECR Pull Through Cache (for public images like nginx, postgres)
# -----------------------------------------------------------------------------
# Note: Docker Hub and GitHub require authentication via Secrets Manager.
# Only Quay.io works without auth for public images.
# To enable Docker Hub/GitHub, create secrets in AWS Secrets Manager and
# add credential_arn parameter to the rules below.
# -----------------------------------------------------------------------------

resource "aws_ecr_pull_through_cache_rule" "quay" {
  ecr_repository_prefix = "quay"
  upstream_registry_url = "quay.io"
}
