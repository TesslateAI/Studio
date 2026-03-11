# =============================================================================
# S3 Bucket for Litestream SQLite Replication
# =============================================================================
# Stores Litestream WAL replicas for Headscale's SQLite database.
# Litestream manages its own WAL segment lifecycle, so no versioning needed.
# =============================================================================

resource "aws_s3_bucket" "litestream" {
  bucket        = "${var.project_name}-platform-litestream"
  force_destroy = false

  tags = merge(local.common_tags, {
    Name = "${var.project_name}-platform-litestream"
  })
}

resource "aws_s3_bucket_server_side_encryption_configuration" "litestream" {
  bucket = aws_s3_bucket.litestream.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "litestream" {
  bucket = aws_s3_bucket.litestream.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_policy" "litestream_tls_only" {
  bucket = aws_s3_bucket.litestream.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          aws_s3_bucket.litestream.arn,
          "${aws_s3_bucket.litestream.arn}/*",
        ]
        Condition = {
          Bool = {
            "aws:SecureTransport" = "false"
          }
        }
      }
    ]
  })

  depends_on = [aws_s3_bucket_public_access_block.litestream]
}

resource "aws_s3_bucket_lifecycle_configuration" "litestream" {
  bucket = aws_s3_bucket.litestream.id

  # Safety net for orphaned Litestream generations (Litestream handles its
  # own retention at 72h; this catches anything it misses)
  rule {
    id     = "expire-old-generations"
    status = "Enabled"

    filter {
      prefix = "headscale/"
    }

    expiration {
      days = 90
    }
  }

  rule {
    id     = "abort-incomplete-multipart"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}
