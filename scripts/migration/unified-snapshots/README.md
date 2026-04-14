# Unified Snapshots Migration

Migrates the btrfs CSI storage system from the linear `layers` manifest format
(develop branch) to the DAG-based `snapshots` format (feat/unified-snapshots-system).

## What Changes

Only S3 manifest files (`manifests/{volume_id}.json`) are modified.
CAS blobs, tombstones, and template indexes are format-identical and untouched.

| Field | Old | New |
|-------|-----|-----|
| Layer storage | `"layers": [...]` (array) | `"snapshots": {...}` (hash-indexed map) |
| Type field | `"type": "sync"\|"snapshot"` | `"role": "sync"\|"checkpoint"` |
| Current pointer | implicit (last array entry) | `"head": "sha256:..."` |
| Branches | not supported | `"branches": {}` |
| Timeline | implicit (array order) | `"prev": "sha256:..."` per entry |
| Consolidation | not tracked | `"consolidation": true\|false` |

## Scripts

| Script | Purpose |
|--------|---------|
| `run_migration.sh` | Full migration orchestrator (all phases) |
| `backup_s3.sh` | Phase 2: Full bucket backup (blobs + index + manifests + tombstones) |
| `convert_manifests.py` | Phase 3: Convert manifest format with per-run state tracking |
| `rollback.sh` | Restore from backup |

## Observability

Every `convert_manifests.py` run writes locally AND mirrors to S3.

**Local** (`runs/{run_id}/`):
```
runs/2026-04-14T02-22-25Z/
├── state.json      # authoritative per-volume status (resumable, atomic writes)
├── run.log         # human-readable progress (timestamped)
└── summary.json    # final counts
```

**S3** (`s3://{bucket}/backups/feat-unified-snapshots/runs/{run_id}/`):
- `state.json` — uploaded every 25 state flushes (crash visibility)
- `run.log` — uploaded at run close
- `summary.json` — uploaded at run close

Disable S3 uploads with `--no-s3-log` (local-only).

### Per-volume state

Each volume has:
- `status`: `pending` | `in_progress` | `succeeded` | `failed` | `skipped`
- `key`, `started_at`, `finished_at`, `duration_sec`
- `pre_sha256` (source), `post_sha256` (uploaded)
- `layers_count`, `snapshots_count`, `consolidations`, `head`
- `error` on failure, `skip_reason` on skip

### Commands

```bash
# List all prior runs (local)
python3 convert_manifests.py --list-runs

# Show status of a run
python3 convert_manifests.py --status --run-id 2026-04-14T02-22-25Z

# Resume an interrupted run (skips already-succeeded, retries pending/failed)
python3 convert_manifests.py --bucket BUCKET --run-id 2026-04-14T02-22-25Z

# Retry only failed volumes from a specific run
python3 convert_manifests.py --bucket BUCKET --run-id 2026-04-14T02-22-25Z --retry-failed

# Pull a run's artifacts from S3 (another operator's run, or after losing local state)
python3 convert_manifests.py --pull-from-s3 --bucket BUCKET --run-id 2026-04-14T02-22-25Z
```

### Crash safety

- `state.json` is flushed atomically after every volume via rename
- A volume in `in_progress` status at startup means the prior run crashed mid-conversion — inspect and retry
- Every successful conversion is verified via post-upload re-download + SHA check

## Full Migration Workflow

```bash
# 1. Dry run — plan the run, validate the converter
./run_migration.sh --dry-run

# 2. Single-volume sanity check
python3 convert_manifests.py --from-k8s-secret --context tesslate-beta-eks \
    --volume-id vol-5babb7cf9cbb --dry-run

# 3. Stop the cluster (all pods + Volume Hub + btrfs CSI DS)
./run_migration.sh --phase stop

# 4. Full S3 backup (copy-only, non-destructive)
./backup_s3.sh --from-k8s-secret --context tesslate-beta-eks

# 5. Convert all manifests
./run_migration.sh --phase convert

# 6. If any failed, retry:
python3 convert_manifests.py --bucket BUCKET --run-id <id> --retry-failed

# 7. Deploy new images
./run_migration.sh --phase deploy

# 8. Start the cluster
./run_migration.sh --phase start

# 9. Rollback if needed
./rollback.sh --from-k8s-secret --context tesslate-beta-eks
```

## Pre-Requisites

- `aws` CLI configured with access to the btrfs-snapshots bucket
- `kubectl` with access to the beta cluster (`tesslate-beta-eks`)
- Python 3.10+
- New images already built and pushed to ECR (<AWS_ACCOUNT_ID>)
