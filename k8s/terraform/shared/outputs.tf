# =============================================================================
# Outputs for Shared Resources
# =============================================================================

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
