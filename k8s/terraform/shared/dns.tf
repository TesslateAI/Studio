# =============================================================================
# Cloudflare DNS Records for Platform Cluster
# =============================================================================
# Creates CNAME records pointing platform tool subdomains to the NLB.
# Each new tool adds its own record in its respective .tf file, or here if
# the tool doesn't warrant a separate file.
# =============================================================================

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
# CNAME: {headscale_subdomain}.{domain_name} -> Platform NLB
# -----------------------------------------------------------------------------
resource "cloudflare_record" "headscale" {
  count = var.cloudflare_zone_id != "" ? 1 : 0

  zone_id         = var.cloudflare_zone_id
  name            = var.headscale_subdomain
  content         = local.nlb_hostname
  type            = "CNAME"
  proxied         = false  # Must be false for cert-manager DNS01 + Tailscale protocol
  ttl             = 1      # Auto TTL
  comment         = "Managed by Terraform (shared)"
  allow_overwrite = true

  lifecycle {
    precondition {
      condition     = local.nlb_hostname != ""
      error_message = "NLB hostname not yet available. Deploy nginx ingress first."
    }
  }
}
