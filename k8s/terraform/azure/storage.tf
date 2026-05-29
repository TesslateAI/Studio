# =============================================================================
# Storage Account + Blob Containers for OpenSail
# =============================================================================
# Single Storage Account holds three Blob containers (parity with the three
# S3 buckets in aws/s3.tf):
#   - projects             — project hibernation
#   - btrfs-snapshots      — btrfs CSI sync target
#   - marketplace-bundles  — published app archives
#
# Versioning + soft-delete give the same recovery story as S3 versioning +
# lifecycle. TLS is enforced at the account level (matches the EnforceTLS
# bucket policy on S3).
#
# Workload Identity grants per-SA Blob Data Contributor scoped to each
# container — see iam.tf for the role assignments.
# =============================================================================

resource "azurerm_storage_account" "this" {
  # Storage account names must be globally unique, lowercase, 3-24 chars.
  # acr_name's suffix gives us a stable random — reuse it here to keep
  # both names tied to the same `terraform apply`.
  name                     = lower(replace("${var.project_name}${var.environment}sa${random_id.suffix.hex}", "-", ""))
  resource_group_name      = azurerm_resource_group.this.name
  location                 = azurerm_resource_group.this.location
  account_tier             = var.storage_account_tier
  account_replication_type = var.storage_account_replication
  account_kind             = "StorageV2"

  # TLS 1.2 enforced + HTTPS-only (parity with EnforceTLS bucket policy)
  https_traffic_only_enabled      = true
  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false
  shared_access_key_enabled       = true # S3-compat path needs account key fallback

  # Blob versioning + soft-delete (matches S3 versioning + lifecycle).
  blob_properties {
    versioning_enabled       = true
    change_feed_enabled      = false
    last_access_time_enabled = false

    delete_retention_policy {
      days = 30
    }
    container_delete_retention_policy {
      days = 30
    }
  }

  # Restrict network access to the AKS subnet + bypass for Azure services.
  network_rules {
    default_action             = "Allow" # Permissive default — tighten via tfvars per env
    bypass                     = ["AzureServices"]
    virtual_network_subnet_ids = [azurerm_subnet.aks_nodes.id]
  }

  tags = local.common_tags
}

# -----------------------------------------------------------------------------
# Projects container — project hibernation
# -----------------------------------------------------------------------------
resource "azurerm_storage_container" "projects" {
  name                  = "projects"
  storage_account_name  = azurerm_storage_account.this.name
  container_access_type = "private"
}

# -----------------------------------------------------------------------------
# btrfs-snapshots container — CSI sync target
# -----------------------------------------------------------------------------
resource "azurerm_storage_container" "btrfs_snapshots" {
  name                  = "btrfs-snapshots"
  storage_account_name  = azurerm_storage_account.this.name
  container_access_type = "private"
}

# -----------------------------------------------------------------------------
# Marketplace bundles container — published app archives
# -----------------------------------------------------------------------------
resource "azurerm_storage_container" "marketplace_bundles" {
  name                  = "marketplace-bundles"
  storage_account_name  = azurerm_storage_account.this.name
  container_access_type = "private"
}

# -----------------------------------------------------------------------------
# Storage management policy — retire old blob versions to Cool / Archive
# (parity with the noncurrent-version lifecycle on S3).
# -----------------------------------------------------------------------------
resource "azurerm_storage_management_policy" "this" {
  storage_account_id = azurerm_storage_account.this.id

  rule {
    name    = "archive-old-versions"
    enabled = true

    filters {
      blob_types = ["blockBlob"]
    }

    actions {
      version {
        change_tier_to_cool_after_days_since_creation    = 30
        change_tier_to_archive_after_days_since_creation = 90
        delete_after_days_since_creation                 = 365
      }
    }
  }

  # Note: Azure Blob auto-GCs uncommitted block uploads after 7 days at the
  # service level. There's no direct equivalent of S3's
  # abort-incomplete-multipart-upload lifecycle action because the cleanup
  # is built into the platform — no extra rule needed here.

  rule {
    name    = "expire-old-snapshots"
    enabled = true

    filters {
      blob_types = ["blockBlob"]
    }

    actions {
      base_blob {
        # Stale base blobs retire after a year of no modification — keeps
        # storage growth bounded even when versioning misses the rotation.
        delete_after_days_since_modification_greater_than = 365
      }
    }
  }
}
