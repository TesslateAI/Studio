# Base: compute-pool

Kustomize group at `k8s/base/compute-pool/`. Defines the dedicated namespace where per-project compute pods run (separate from the platform `tesslate` namespace and the per-project `proj-*` namespaces).

## Files

| File | Purpose |
|------|---------|
| `kustomization.yaml` | Lists the resources below. |
| `namespace.yaml` | `Namespace tesslate-compute-pool`. Houses ephemeral compute pods used for agent bash, user app boot, and shared service pods. |
| `network-policy.yaml` | NetworkPolicies scoped to the compute pool: default-deny ingress, allow DNS, allow external egress except `169.254.169.254/32` (AWS IMDS). |
| `resource-quota.yaml` | Caps CPU, memory, and pod counts for the entire compute pool so a runaway workload cannot exhaust the cluster. |

## Why a separate namespace

- Compute pods are short-lived and created programmatically by the orchestrator. They should not share a Service account, RBAC, or quotas with the platform namespace.
- Dedicated namespace gives a single place to apply IMDS-egress blocks, so user code cannot steal node IAM credentials from the AWS metadata service.
- The reaper (`services/compute_reaper` in the orchestrator) uses this namespace as its sole target.

## Related

- `k8s/base/security/network-policies.yaml` holds the analogous policies for `proj-*` namespaces.
- Orchestrator compute manager: `orchestrator/app/services/compute_manager.py`.
