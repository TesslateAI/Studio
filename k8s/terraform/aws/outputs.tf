# =============================================================================
# Terraform Outputs for Tesslate Studio AWS EKS
# =============================================================================

# -----------------------------------------------------------------------------
# VPC Outputs
# -----------------------------------------------------------------------------
output "vpc_id" {
  description = "VPC ID"
  value       = module.vpc.vpc_id
}

output "vpc_cidr" {
  description = "VPC CIDR block"
  value       = module.vpc.vpc_cidr_block
}

output "private_subnets" {
  description = "Private subnet IDs"
  value       = module.vpc.private_subnets
}

output "public_subnets" {
  description = "Public subnet IDs"
  value       = module.vpc.public_subnets
}

# -----------------------------------------------------------------------------
# EKS Outputs
# -----------------------------------------------------------------------------
output "cluster_name" {
  description = "EKS cluster name"
  value       = module.eks.cluster_name
}

output "cluster_endpoint" {
  description = "EKS cluster API endpoint"
  value       = module.eks.cluster_endpoint
}

output "cluster_certificate_authority_data" {
  description = "Base64 encoded certificate data for cluster authentication"
  value       = module.eks.cluster_certificate_authority_data
  sensitive   = true
}

output "cluster_oidc_provider_arn" {
  description = "OIDC provider ARN for IRSA"
  value       = module.eks.oidc_provider_arn
}

output "cluster_security_group_id" {
  description = "Security group ID attached to the EKS cluster"
  value       = module.eks.cluster_security_group_id
}

output "node_security_group_id" {
  description = "Security group ID attached to EKS nodes"
  value       = module.eks.node_security_group_id
}

# -----------------------------------------------------------------------------
# S3 Outputs
# -----------------------------------------------------------------------------
output "s3_bucket_name" {
  description = "S3 bucket name for project storage"
  value       = aws_s3_bucket.tesslate_projects.id
}

output "s3_bucket_arn" {
  description = "S3 bucket ARN"
  value       = aws_s3_bucket.tesslate_projects.arn
}

output "s3_bucket_region" {
  description = "S3 bucket region"
  value       = aws_s3_bucket.tesslate_projects.region
}

# -----------------------------------------------------------------------------
# ECR Outputs
# -----------------------------------------------------------------------------
output "ecr_backend_repository_url" {
  description = "ECR repository URL for backend"
  value       = aws_ecr_repository.backend.repository_url
}

output "ecr_frontend_repository_url" {
  description = "ECR repository URL for frontend"
  value       = aws_ecr_repository.frontend.repository_url
}

output "ecr_devserver_repository_url" {
  description = "ECR repository URL for devserver"
  value       = aws_ecr_repository.devserver.repository_url
}

output "ecr_registry_url" {
  description = "ECR registry URL (without repository name)"
  value       = split("/", aws_ecr_repository.backend.repository_url)[0]
}

# -----------------------------------------------------------------------------
# IAM Outputs
# -----------------------------------------------------------------------------
output "tesslate_backend_role_arn" {
  description = "IAM role ARN for Tesslate backend service account"
  value       = module.tesslate_backend_irsa.iam_role_arn
}

output "cluster_autoscaler_role_arn" {
  description = "IAM role ARN for cluster autoscaler"
  value       = module.cluster_autoscaler_irsa.iam_role_arn
}

output "external_dns_role_arn" {
  description = "IAM role ARN for external-dns"
  value       = module.external_dns_irsa.iam_role_arn
}

output "cert_manager_role_arn" {
  description = "IAM role ARN for cert-manager"
  value       = module.cert_manager_irsa.iam_role_arn
}

# -----------------------------------------------------------------------------
# Database Outputs (if RDS is enabled)
# -----------------------------------------------------------------------------
output "rds_endpoint" {
  description = "RDS endpoint"
  value       = var.create_rds ? aws_db_instance.tesslate[0].endpoint : "Using K8s-managed PostgreSQL"
}

output "rds_database_name" {
  description = "RDS database name"
  value       = var.create_rds ? aws_db_instance.tesslate[0].db_name : "tesslate"
}

# -----------------------------------------------------------------------------
# Useful Commands
# -----------------------------------------------------------------------------
output "configure_kubectl_command" {
  description = "Command to configure kubectl for this cluster"
  value       = "aws eks update-kubeconfig --name ${module.eks.cluster_name} --region ${var.aws_region}"
}

output "ecr_login_command" {
  description = "Command to login to ECR"
  value       = "aws ecr get-login-password --region ${var.aws_region} | docker login --username AWS --password-stdin ${split("/", aws_ecr_repository.backend.repository_url)[0]}"
}

output "build_and_push_commands" {
  description = "Commands to build and push Docker images"
  value = <<-EOT
    # Backend
    docker build -t ${aws_ecr_repository.backend.repository_url}:latest -f orchestrator/Dockerfile orchestrator/
    docker push ${aws_ecr_repository.backend.repository_url}:latest

    # Frontend
    docker build -t ${aws_ecr_repository.frontend.repository_url}:latest -f app/Dockerfile.prod app/
    docker push ${aws_ecr_repository.frontend.repository_url}:latest

    # Devserver
    docker build -t ${aws_ecr_repository.devserver.repository_url}:latest -f orchestrator/Dockerfile.devserver orchestrator/
    docker push ${aws_ecr_repository.devserver.repository_url}:latest
  EOT
}

output "domain_configuration" {
  description = "Domain configuration for the application"
  value = {
    main_domain     = var.domain_name
    wildcard_domain = "*.${var.domain_name}"
    app_url         = "https://${var.domain_name}"
    project_urls    = "https://<project>.<container>.${var.domain_name}"
  }
}
