# =============================================================================
# Outputs for Shared Infrastructure
# =============================================================================

# -----------------------------------------------------------------------------
# ECR Outputs
# -----------------------------------------------------------------------------
output "ecr_registry_url" {
  description = "ECR registry URL (without repository name)"
  value       = split("/", aws_ecr_repository.backend.repository_url)[0]
}

output "ecr_backend_url" {
  description = "ECR repository URL for backend"
  value       = aws_ecr_repository.backend.repository_url
}

output "ecr_frontend_url" {
  description = "ECR repository URL for frontend"
  value       = aws_ecr_repository.frontend.repository_url
}

output "ecr_devserver_url" {
  description = "ECR repository URL for devserver"
  value       = aws_ecr_repository.devserver.repository_url
}

output "ecr_login_command" {
  description = "Command to login to ECR"
  value       = "aws ecr get-login-password --region ${var.aws_region} | docker login --username AWS --password-stdin ${split("/", aws_ecr_repository.backend.repository_url)[0]}"
}

# -----------------------------------------------------------------------------
# VPC Outputs
# -----------------------------------------------------------------------------
output "vpc_id" {
  description = "Platform VPC ID"
  value       = module.vpc.vpc_id
}

output "vpc_cidr" {
  description = "Platform VPC CIDR block"
  value       = module.vpc.vpc_cidr_block
}

# -----------------------------------------------------------------------------
# EKS Outputs
# -----------------------------------------------------------------------------
output "cluster_name" {
  description = "Platform EKS cluster name"
  value       = module.eks.cluster_name
}

output "cluster_endpoint" {
  description = "Platform EKS cluster API endpoint"
  value       = module.eks.cluster_endpoint
}

output "eks_deployer_role_arn" {
  description = "IAM role ARN for EKS cluster access — assume this role for kubectl"
  value       = aws_iam_role.eks_deployer.arn
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

# -----------------------------------------------------------------------------
# Networking Outputs
# -----------------------------------------------------------------------------
output "nlb_hostname" {
  description = "NLB hostname for the platform ingress"
  value       = local.nlb_hostname
}

# -----------------------------------------------------------------------------
# Headscale Outputs
# -----------------------------------------------------------------------------
output "headscale_url" {
  description = "Headscale control server URL"
  value       = "https://${var.headscale_subdomain}.${var.domain_name}"
}

# -----------------------------------------------------------------------------
# Litestream S3 Outputs
# -----------------------------------------------------------------------------
output "litestream_bucket_name" {
  description = "S3 bucket name for Litestream SQLite replication"
  value       = aws_s3_bucket.litestream.id
}

output "litestream_bucket_arn" {
  description = "S3 bucket ARN for Litestream SQLite replication"
  value       = aws_s3_bucket.litestream.arn
}

# -----------------------------------------------------------------------------
# Useful Commands
# -----------------------------------------------------------------------------
output "configure_kubectl_command" {
  description = "Command to configure kubectl for the platform cluster (via eks-deployer role)"
  value       = "aws eks update-kubeconfig --name ${module.eks.cluster_name} --region ${var.aws_region} --role-arn ${aws_iam_role.eks_deployer.arn}"
}

output "verify_headscale_command" {
  description = "Command to check Headscale pods"
  value       = "kubectl get pods -n headscale"
}
