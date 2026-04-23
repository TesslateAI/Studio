# Kubernetes Management Scripts

> Operator-friendly wrappers around kubectl. They exist so day-to-day lifecycle commands have one canonical form and the kubectl context safety rule (always pass `--context=<name>`) is enforced.

## `manage-k8s.sh`

Path: `scripts/kubernetes/manage-k8s.sh`

Subcommands (not exhaustive):

| Command | Effect |
|---------|--------|
| `status` | `kubectl get all,ingress,pvc,secret` across the OpenSail namespace. |
| `logs <service>` | Tail the named Deployment's logs. |
| `restart <service>` | `kubectl rollout restart deployment/<service>`. |
| `scale <service> <replicas>` | Scale a Deployment. |
| `deploy` | Apply the current kustomize overlay. |
| `update` | Build images, push, and apply the overlay. |
| `backup` | Dump the Postgres database to a local file. |
| `restore <file>` | Restore the Postgres database from a dump. |

Every invocation must be paired with an explicit kubectl context flag. Context switching via `kubectl config use-context` is banned (see [root CLAUDE.md](../../CLAUDE.md)).

## `cleanup-k8s.sh`

Path: `scripts/kubernetes/cleanup-k8s.sh`

Two interactive modes:

1. **User environments only** (safe): deletes `proj-*` namespaces. Core platform survives.
2. **Everything** (destructive): also drops the database. Use only for clean-slate dev resets.

## Related

- Infrastructure context: [docs/infrastructure/kubernetes/CLAUDE.md](../infrastructure/kubernetes/CLAUDE.md)
- `minikube-dev` skill (local K8s workflow)
- `aws-deploy` skill (production workflow via `scripts/aws-deploy.sh`)
