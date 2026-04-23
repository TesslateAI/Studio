# cmd/migrate

One-shot migrator: `services/btrfs-csi/cmd/migrate/main.go`.

## Purpose

Upgrades CAS manifests and on-disk state from the legacy template-based sync format to the incremental-chain snapshot model. Intended to be run as a Job during platform upgrades.

## Modes

| Flag | Effect |
|------|--------|
| `--dry-run` | Prints the migration plan without writing. |
| `--execute` | Performs the migration. |
| `--validate` | Verifies post-migration state is consistent. |
| `--skip-disk` | S3-only migration; no btrfs access needed. Useful when the migrator pod has no privileged access. |

## What it does

1. Lists existing `manifests/*.json` keys in S3.
2. For each volume manifest, rewrites to the current schema (base blob hash, ordered layers with `parent`, `type`, `ts`).
3. Updates `index/templates.json` to the name-to-hash format consumed by `pkg/cas/templates.go`.
4. Optionally walks `/mnt/tesslate-pool/volumes` and `/mnt/tesslate-pool/snapshots` to prune unreferenced local data.
