# =============================================================================
# Variables for Shared Resources
# =============================================================================

variable "project_name" {
  description = "Name of the project (used for resource naming)"
  type        = string
  default     = "tesslate"
}

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}
