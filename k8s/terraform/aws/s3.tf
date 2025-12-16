# =============================================================================
# S3 Bucket for Tesslate Project Storage
# =============================================================================
# Creates an S3 bucket for project hibernation/restoration.
# Projects are zipped and stored when users leave, then restored when they return.
# =============================================================================

# -----------------------------------------------------------------------------
# S3 Bucket
# -----------------------------------------------------------------------------
resource "aws_s3_bucket" "tesslate_projects" {
  bucket        = "${var.s3_bucket_prefix}-${var.environment}-${random_id.suffix.hex}"
  force_destroy = var.s3_force_destroy

  tags = merge(local.common_tags, {
    Name = "${var.project_name}-${var.environment}-projects"
  })
}

# -----------------------------------------------------------------------------
# S3 Bucket Versioning (for data protection)
# -----------------------------------------------------------------------------
resource "aws_s3_bucket_versioning" "tesslate_projects" {
  bucket = aws_s3_bucket.tesslate_projects.id

  versioning_configuration {
    status = "Enabled"
  }
}

# -----------------------------------------------------------------------------
# S3 Bucket Encryption
# -----------------------------------------------------------------------------
resource "aws_s3_bucket_server_side_encryption_configuration" "tesslate_projects" {
  bucket = aws_s3_bucket.tesslate_projects.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

# -----------------------------------------------------------------------------
# S3 Bucket Public Access Block
# -----------------------------------------------------------------------------
resource "aws_s3_bucket_public_access_block" "tesslate_projects" {
  bucket = aws_s3_bucket.tesslate_projects.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# -----------------------------------------------------------------------------
# S3 Bucket Lifecycle Rules
# -----------------------------------------------------------------------------
resource "aws_s3_bucket_lifecycle_configuration" "tesslate_projects" {
  bucket = aws_s3_bucket.tesslate_projects.id

  # Move old project versions to cheaper storage
  rule {
    id     = "archive-old-versions"
    status = "Enabled"

    filter {}  # Apply to all objects

    noncurrent_version_transition {
      noncurrent_days = 30
      storage_class   = "STANDARD_IA"
    }

    noncurrent_version_transition {
      noncurrent_days = 90
      storage_class   = "GLACIER"
    }

    noncurrent_version_expiration {
      noncurrent_days = 365
    }
  }

  # Clean up incomplete multipart uploads
  rule {
    id     = "abort-incomplete-multipart"
    status = "Enabled"

    filter {}  # Apply to all objects

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  # Optional: Expire projects not accessed for a long time
  # Uncomment if you want automatic cleanup
  # rule {
  #   id     = "expire-inactive-projects"
  #   status = "Enabled"
  #
  #   filter {
  #     prefix = "projects/"
  #   }
  #
  #   expiration {
  #     days = 180  # Delete projects not accessed for 6 months
  #   }
  # }
}

# -----------------------------------------------------------------------------
# S3 Bucket CORS Configuration (for direct uploads if needed)
# -----------------------------------------------------------------------------
resource "aws_s3_bucket_cors_configuration" "tesslate_projects" {
  bucket = aws_s3_bucket.tesslate_projects.id

  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["GET", "PUT", "POST", "DELETE", "HEAD"]
    allowed_origins = [
      "https://${var.domain_name}",
      "https://*.${var.domain_name}"
    ]
    expose_headers  = ["ETag"]
    max_age_seconds = 3600
  }
}

# -----------------------------------------------------------------------------
# S3 Bucket Policy (optional - for cross-account access or specific policies)
# -----------------------------------------------------------------------------
resource "aws_s3_bucket_policy" "tesslate_projects" {
  bucket = aws_s3_bucket.tesslate_projects.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "EnforceTLS"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.tesslate_projects.arn,
          "${aws_s3_bucket.tesslate_projects.arn}/*"
        ]
        Condition = {
          Bool = {
            "aws:SecureTransport" = "false"
          }
        }
      }
    ]
  })
}
