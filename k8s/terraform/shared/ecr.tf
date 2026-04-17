# =============================================================================
# ECR Repositories for Tesslate Studio Container Images
# =============================================================================
# Shared across all environments. Each environment pushes with its own tag:
#   - production: tesslate-backend:production
#   - beta:       tesslate-backend:beta
# =============================================================================

# -----------------------------------------------------------------------------
# Backend ECR Repository
# -----------------------------------------------------------------------------
resource "aws_ecr_repository" "backend" {
  name                 = "${var.project_name}-backend"
  image_tag_mutability = "MUTABLE"
  force_delete         = false

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Name      = "${var.project_name}-backend"
    Component = "backend"
  }
}

# -----------------------------------------------------------------------------
# Frontend ECR Repository
# -----------------------------------------------------------------------------
resource "aws_ecr_repository" "frontend" {
  name                 = "${var.project_name}-frontend"
  image_tag_mutability = "MUTABLE"
  force_delete         = false

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Name      = "${var.project_name}-frontend"
    Component = "frontend"
  }
}

# -----------------------------------------------------------------------------
# Devserver ECR Repository
# -----------------------------------------------------------------------------
resource "aws_ecr_repository" "devserver" {
  name                 = "${var.project_name}-devserver"
  image_tag_mutability = "MUTABLE"
  force_delete         = false

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Name      = "${var.project_name}-devserver"
    Component = "devserver"
  }
}

# -----------------------------------------------------------------------------
# btrfs CSI Driver ECR Repository
# -----------------------------------------------------------------------------
resource "aws_ecr_repository" "btrfs_csi" {
  name                 = "${var.project_name}-btrfs-csi"
  image_tag_mutability = "MUTABLE"
  force_delete         = false

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Name      = "${var.project_name}-btrfs-csi"
    Component = "btrfs-csi"
  }
}

# -----------------------------------------------------------------------------
# AST Sidecar ECR Repository
# -----------------------------------------------------------------------------
# Node.js gRPC service that runs as a sidecar inside the backend pod —
# handles JSX/TSX AST transforms for the design panel. Separate image
# so Node stays out of the backend image and AST can be versioned /
# rolled back independently at the image level.
resource "aws_ecr_repository" "ast" {
  name                 = "${var.project_name}-ast"
  image_tag_mutability = "MUTABLE"
  force_delete         = false

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Name      = "${var.project_name}-ast"
    Component = "ast"
  }
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
        description  = "Protect environment and release tags"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["production", "beta", "v", "release"]
          countType     = "imageCountMoreThan"
          countNumber   = 30
        }
        action = {
          type = "expire"
        }
      },
      {
        rulePriority = 2
        description  = "Remove untagged images older than 1 day"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 1
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

resource "aws_ecr_lifecycle_policy" "btrfs_csi" {
  repository = aws_ecr_repository.btrfs_csi.name
  policy     = local.ecr_lifecycle_policy
}

resource "aws_ecr_lifecycle_policy" "ast" {
  repository = aws_ecr_repository.ast.name
  policy     = local.ecr_lifecycle_policy
}

# -----------------------------------------------------------------------------
# ECR Pull Through Cache (for public images like nginx, postgres)
# -----------------------------------------------------------------------------
resource "aws_ecr_pull_through_cache_rule" "quay" {
  ecr_repository_prefix = "quay"
  upstream_registry_url = "quay.io"
}
