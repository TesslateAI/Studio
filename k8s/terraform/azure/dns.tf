# =============================================================================
# Cloudflare DNS Records — Azure Standard LB public IP (one-pass-safe)
# =============================================================================
# Azure Standard LB IP assignment is async — the Service object exists as soon
# as the NGINX Helm release completes, but the IP is empty for 60–120 s while
# Azure programs the load balancer behind it. The previous lifecycle
# precondition pattern (matching the AWS stack) failed `terraform apply` on
# the first run because the IP wasn't ready yet, forcing the operator to
# re-run apply.
#
# This file uses a `null_resource` that polls `kubectl get svc` until the IP
# appears, then a `data.kubernetes_service` read consumes the now-populated
# value, so Cloudflare records create with a real IP in the same apply.
# =============================================================================

provider "cloudflare" {
  api_token = var.cloudflare_api_token
}

# -----------------------------------------------------------------------------
# Persist the AKS admin kubeconfig to disk so the null_resource provisioner
# can run `kubectl` against the cluster. Written to .terraform/ which is
# already gitignored and stays inside the working directory (no cleanup
# required between runs — overwritten on next apply).
# -----------------------------------------------------------------------------
resource "local_sensitive_file" "kubeconfig" {
  filename        = "${path.module}/.terraform/.kubeconfig-${var.environment}"
  content         = azurerm_kubernetes_cluster.this.kube_admin_config_raw
  file_permission = "0600"

  depends_on = [azurerm_kubernetes_cluster.this]
}

# -----------------------------------------------------------------------------
# Block until the NGINX ingress LoadBalancer Service receives a public IP.
# Polls every 10 s for up to 10 min. Without this gate, Cloudflare record
# creation would race the LB programming and fail with an empty `content`.
# -----------------------------------------------------------------------------
resource "null_resource" "wait_for_lb_ip" {
  depends_on = [
    helm_release.nginx_ingress,
    local_sensitive_file.kubeconfig,
  ]

  # Re-poll if the Helm release rolls (e.g. chart upgrade) — otherwise the
  # cached completion state would skip the wait and the data source below
  # could read a stale "still pending" value.
  triggers = {
    helm_release_revision = helm_release.nginx_ingress.metadata[0].revision
  }

  provisioner "local-exec" {
    interpreter = ["bash", "-c"]
    environment = {
      KUBECONFIG = local_sensitive_file.kubeconfig.filename
    }
    command = <<-EOT
      set -e
      echo "Waiting for ingress-nginx LoadBalancer to receive public IP (max 10 min)..."
      for i in $(seq 1 60); do
        IP=$(kubectl get svc -n ingress-nginx ingress-nginx-controller \
               -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || true)
        if [ -n "$IP" ]; then
          echo "LB IP: $IP"
          exit 0
        fi
        printf "  attempt %02d/60 — still pending...\n" $i
        sleep 10
      done
      echo "ERROR: Timed out waiting for LB IP after 10 minutes" >&2
      exit 1
    EOT
  }
}

# -----------------------------------------------------------------------------
# Now safe to read the populated LB IP. depends_on the wait guarantees the
# data source re-reads after the IP is programmed (same apply).
# -----------------------------------------------------------------------------
data "kubernetes_service" "nginx_ingress" {
  metadata {
    name      = "ingress-nginx-controller"
    namespace = "ingress-nginx"
  }

  depends_on = [null_resource.wait_for_lb_ip]
}

locals {
  lb_ip = data.kubernetes_service.nginx_ingress.status[0].load_balancer[0].ingress[0].ip
}

# -----------------------------------------------------------------------------
# Apex / subdomain A record → LB IP
# -----------------------------------------------------------------------------
resource "cloudflare_record" "domain" {
  count = var.cloudflare_zone_id != "" ? 1 : 0

  zone_id         = var.cloudflare_zone_id
  name            = local.dns_subdomain
  content         = local.lb_ip
  type            = "A"
  proxied         = false # cert-manager DNS01 needs the record un-proxied
  ttl             = 1
  comment         = "Managed by Terraform (${var.environment} / Azure)"
  allow_overwrite = true
}

# -----------------------------------------------------------------------------
# Wildcard A record → LB IP (covers per-project subdomains)
# -----------------------------------------------------------------------------
resource "cloudflare_record" "wildcard" {
  count = var.cloudflare_zone_id != "" ? 1 : 0

  zone_id         = var.cloudflare_zone_id
  name            = local.dns_subdomain == "@" ? "*" : "*.${local.dns_subdomain}"
  content         = local.lb_ip
  type            = "A"
  proxied         = false
  ttl             = 1
  comment         = "Managed by Terraform (${var.environment} / Azure)"
  allow_overwrite = true
}
