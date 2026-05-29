# =============================================================================
# AKS Cluster Configuration for OpenSail
# =============================================================================
# Creates an AKS cluster with:
#   - System node pool (CoreDNS, kube-proxy, metrics-server)
#   - User node pool (primary Tesslate workloads)
#   - Optional spot node pool (user-project workloads)
#   - Workload Identity enabled (federated tokens replace IRSA)
#   - OIDC issuer URL (federates with User-Assigned Managed Identities)
#   - Azure CNI Overlay (pod IPs from a separate CIDR, not the node subnet)
#   - Azure RBAC for Kubernetes Authorization (AAD groups → ClusterRoles)
#   - ACR pull access auto-attached so kubelet can pull from ACR without
#     image-pull secrets
# =============================================================================

resource "azurerm_kubernetes_cluster" "this" {
  name                = local.cluster_name
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  dns_prefix          = "${var.project_name}-${var.environment}"
  kubernetes_version  = var.aks_cluster_version

  # Workload Identity + OIDC issuer (replaces IRSA)
  oidc_issuer_enabled       = true
  workload_identity_enabled = true

  # Azure RBAC for K8s — admin AAD groups assigned via azurerm_role_assignment
  # below get the AKS Cluster Admin built-in role. Team groups
  # (deployer/observer/debugger) get scoped K8s RoleBindings created in
  # kubernetes.tf.
  azure_active_directory_role_based_access_control {
    managed                = true
    admin_group_object_ids = var.aks_admin_group_object_ids
    azure_rbac_enabled     = true
  }

  network_profile {
    network_plugin      = "azure"
    network_plugin_mode = "overlay"
    # Cilium NetworkPolicy needs the matching cilium data plane (Azure CNI
    # by Cilium). Pairing `network_policy = cilium` with the default Azure
    # data plane returns NetworkPolicyCiliumRequiresCiliumDataplane.
    network_policy    = "cilium"
    network_data_plane = "cilium"
    load_balancer_sku = "standard"
    service_cidr      = "10.100.0.0/16"
    dns_service_ip    = "10.100.0.10"
    pod_cidr          = "10.244.0.0/16"
  }

  # System node pool — runs CoreDNS, kube-proxy, metrics-server, cluster-autoscaler.
  # Cordoned from user workloads via a CriticalAddonsOnly taint.
  default_node_pool {
    name                         = "system"
    vm_size                      = var.aks_system_node_vm_size
    node_count                   = var.aks_system_node_count
    vnet_subnet_id               = azurerm_subnet.aks_nodes.id
    only_critical_addons_enabled = true
    type                         = "VirtualMachineScaleSets"
    orchestrator_version         = var.aks_cluster_version

    upgrade_settings {
      max_surge = "33%"
    }

    tags = local.common_tags
  }

  # OIDC + Workload Identity rely on the kubelet-identity being able to mint
  # tokens for itself. Use a system-assigned MI (simpler than a user-assigned
  # one for the cluster control plane).
  identity {
    type = "SystemAssigned"
  }

  # Auto-upgrade rolls patch versions so we don't fall behind CVE windows.
  # Minor upgrades stay manual via terraform.
  automatic_channel_upgrade = "patch"
  sku_tier                  = var.environment == "production" ? "Standard" : "Free"

  # Disable local accounts in production — forces AAD auth so audit logs
  # always identify who did what.
  local_account_disabled = var.environment == "production"

  tags = local.common_tags
}

# -----------------------------------------------------------------------------
# User (primary workload) node pool
# -----------------------------------------------------------------------------
resource "azurerm_kubernetes_cluster_node_pool" "user" {
  name                  = "user"
  kubernetes_cluster_id = azurerm_kubernetes_cluster.this.id
  vm_size               = var.aks_user_node_vm_size
  vnet_subnet_id        = azurerm_subnet.aks_nodes.id
  os_disk_size_gb       = var.aks_user_node_disk_size_gb
  mode                  = "User"

  enable_auto_scaling = var.enable_cluster_autoscaler
  node_count          = var.aks_user_node_count
  min_count           = var.enable_cluster_autoscaler ? var.aks_user_node_min_count : null
  max_count           = var.enable_cluster_autoscaler ? var.aks_user_node_max_count : null

  upgrade_settings {
    max_surge = "33%"
  }

  node_labels = {
    role        = "primary"
    environment = var.environment
  }

  tags = local.common_tags
}

# -----------------------------------------------------------------------------
# Optional spot node pool — user-project workloads run here when scheduling
# tolerates it. Matches the aws-eks `spot` group taint.
# -----------------------------------------------------------------------------
resource "azurerm_kubernetes_cluster_node_pool" "spot" {
  count = var.aks_spot_node_count > 0 ? 1 : 0

  name                  = "spot"
  kubernetes_cluster_id = azurerm_kubernetes_cluster.this.id
  vm_size               = var.aks_spot_node_vm_size
  vnet_subnet_id        = azurerm_subnet.aks_nodes.id
  mode                  = "User"

  priority        = "Spot"
  eviction_policy = "Delete"
  spot_max_price  = var.aks_spot_max_price

  enable_auto_scaling = true
  node_count          = var.aks_spot_node_count
  min_count           = 0
  max_count           = var.aks_spot_node_max_count

  node_labels = {
    role                                    = "spot"
    environment                             = var.environment
    "tesslate.io/workload-type"             = "user-project"
    "kubernetes.azure.com/scalesetpriority" = "spot"
  }

  # Spot pool requires the kubernetes.azure.com/scalesetpriority=spot:NoSchedule
  # taint per AKS docs — pods opt in with a matching toleration.
  node_taints = [
    "kubernetes.azure.com/scalesetpriority=spot:NoSchedule",
    "tesslate.io/spot=true:PreferNoSchedule",
  ]

  tags = local.common_tags
}

# -----------------------------------------------------------------------------
# ACR Pull — let AKS pull from our ACR without per-pod imagePullSecrets.
# Equivalent to attaching the AmazonEC2ContainerRegistryReadOnly policy to
# the EKS node group instance role.
# -----------------------------------------------------------------------------
resource "azurerm_role_assignment" "aks_acr_pull" {
  scope                = azurerm_container_registry.this.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_kubernetes_cluster.this.kubelet_identity[0].object_id
}

# -----------------------------------------------------------------------------
# AAD admin groups → Cluster Admin role assignment (Azure RBAC for K8s)
# Replaces the EKS access_entries map.
# -----------------------------------------------------------------------------
resource "azurerm_role_assignment" "aks_cluster_admin" {
  for_each = toset(var.aks_admin_group_object_ids)

  scope                = azurerm_kubernetes_cluster.this.id
  role_definition_name = "Azure Kubernetes Service RBAC Cluster Admin"
  principal_id         = each.key
}

# -----------------------------------------------------------------------------
# Team Access — AAD groups bound to scoped Azure RBAC for K8s roles.
# Hierarchy: observer < deployer < debugger < admin (admin handled above).
# -----------------------------------------------------------------------------
resource "azurerm_role_assignment" "aks_team_observer" {
  for_each = toset(var.aks_observer_group_object_ids)

  scope                = azurerm_kubernetes_cluster.this.id
  role_definition_name = "Azure Kubernetes Service RBAC Reader"
  principal_id         = each.key
}

resource "azurerm_role_assignment" "aks_team_deployer" {
  for_each = toset(var.aks_deployer_group_object_ids)

  scope                = azurerm_kubernetes_cluster.this.id
  role_definition_name = "Azure Kubernetes Service RBAC Writer"
  principal_id         = each.key
}

# Debugger gets Writer + the cluster-scoped Admin role narrowly through a
# custom RoleBinding in kubernetes.tf (exec only). Here we grant Writer so
# they can also rollout-restart deployments.
resource "azurerm_role_assignment" "aks_team_debugger" {
  for_each = toset(var.aks_debugger_group_object_ids)

  scope                = azurerm_kubernetes_cluster.this.id
  role_definition_name = "Azure Kubernetes Service RBAC Writer"
  principal_id         = each.key
}

# -----------------------------------------------------------------------------
# Wait for AKS to be ready before the kubernetes/helm providers run.
# AKS sometimes returns kube_admin_config before the API server is fully
# reachable — short null_resource gates downstream resources.
# -----------------------------------------------------------------------------
resource "time_sleep" "wait_for_aks" {
  depends_on      = [azurerm_kubernetes_cluster.this]
  create_duration = "30s"
}
