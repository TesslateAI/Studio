# Base: security

Kustomize group at `k8s/base/security/`. RBAC, NetworkPolicies, and ResourceQuotas for the platform namespace.

## Files

| File | Purpose |
|------|---------|
| `rbac.yaml` | ServiceAccount `tesslate-backend-sa` + ClusterRole `tesslate-dev-environments-manager` + ClusterRoleBinding `tesslate-backend-cluster-access`. Grants cluster-wide manage rights on namespaces, pods, services, PVCs, secrets, configmaps, deployments, ingresses, networkpolicies, jobs, cronjobs, events. Required because the backend creates `proj-*` namespaces. |
| `team-rbac.yaml` | RBAC for team-scoped service accounts and audit-log readers. Role binding layered on top of `rbac.yaml`. |
| `network-policies.yaml` | Default-deny ingress, allow NGINX -> backend/frontend, frontend -> backend, backend -> postgres, allow DNS, allow backend egress (external with `169.254.169.254/32` excepted), allow worker egress. See `docs/infrastructure/kubernetes/network-policies.md`. |
| `resource-quotas.yaml` | Platform-namespace ResourceQuota: pods 20, CPU requests 12 limits 24, memory requests 24Gi limits 48Gi, PVCs 10, storage 100Gi. |

## Related

- [`../rbac.md`](../rbac.md)
- [`../network-policies.md`](../network-policies.md)
