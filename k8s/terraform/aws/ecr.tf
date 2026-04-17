# =============================================================================
# ECR URL Locals (Computed References)
# =============================================================================
# ECR repositories are managed by the shared stack (k8s/terraform/shared/).
# Both production and beta push different image tags to the SAME repos.
#
# These locals compute the deterministic ECR URLs from account ID + region,
# so environment stacks can reference them without owning the resources.
# =============================================================================

locals {
  ecr_registry_url  = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com"
  ecr_backend_url   = "${local.ecr_registry_url}/${var.project_name}-backend"
  ecr_frontend_url  = "${local.ecr_registry_url}/${var.project_name}-frontend"
  ecr_devserver_url = "${local.ecr_registry_url}/${var.project_name}-devserver"
  ecr_ast_url       = "${local.ecr_registry_url}/${var.project_name}-ast"
}
