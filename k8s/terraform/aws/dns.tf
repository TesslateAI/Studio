# =============================================================================
# Cloudflare DNS Records
# =============================================================================
# Automatically creates CNAME records pointing the domain (and wildcard)
# to the NGINX Ingress NLB. This runs on every terraform apply so DNS
# always points to the current cluster's load balancer.
# =============================================================================

provider "cloudflare" {
  api_token = var.cloudflare_api_token
}

# Get the NLB hostname from the NGINX ingress service
data "kubernetes_service" "nginx_ingress" {
  metadata {
    name      = "ingress-nginx-controller"
    namespace = "ingress-nginx"
  }

  depends_on = [helm_release.nginx_ingress]
}

locals {
  nlb_hostname = try(
    data.kubernetes_service.nginx_ingress.status[0].load_balancer[0].ingress[0].hostname,
    ""
  )
}

# -----------------------------------------------------------------------------
# Base domain CNAME → NLB (e.g., opensail.tesslate.com → NLB)
# -----------------------------------------------------------------------------
resource "cloudflare_record" "domain" {
  count = var.cloudflare_zone_id != "" ? 1 : 0

  zone_id         = var.cloudflare_zone_id
  name            = local.dns_subdomain
  content         = local.nlb_hostname
  type            = "CNAME"
  proxied         = false  # Must be false for cert-manager DNS01 validation
  ttl             = 1      # Auto TTL
  comment         = "Managed by Terraform (${var.environment})"
  allow_overwrite = true

  lifecycle {
    precondition {
      condition     = local.nlb_hostname != ""
      error_message = "NLB hostname not yet available. Deploy nginx ingress first."
    }
  }
}

# -----------------------------------------------------------------------------
# Wildcard CNAME → NLB (e.g., *.opensail.tesslate.com → NLB)
# Required for user project subdomains
# -----------------------------------------------------------------------------
resource "cloudflare_record" "wildcard" {
  count = var.cloudflare_zone_id != "" ? 1 : 0

  zone_id         = var.cloudflare_zone_id
  name            = local.dns_subdomain == "@" ? "*" : "*.${local.dns_subdomain}"
  content         = local.nlb_hostname
  type            = "CNAME"
  proxied         = false
  ttl             = 1
  comment         = "Managed by Terraform (${var.environment})"
  allow_overwrite = true

  lifecycle {
    precondition {
      condition     = local.nlb_hostname != ""
      error_message = "NLB hostname not yet available. Deploy nginx ingress first."
    }
  }
}
