# Migration Scripts

> One-off production migrations that do not fit Alembic's schema model (typically object-store or CAS data). Keep these scripts even after they run so the rollback path stays reproducible.

## unified-snapshots (CAS layer format to snapshot DAG)

Location: `scripts/migration/unified-snapshots/`

Converts the CAS bucket from the old linear `Layer` manifest format to the new DAG `Snapshot` format used by the unified snapshots feature.

### Playbook (phases)

1. **Backup**: `backup_s3.sh` does a server-side copy of the `btrfs-snapshots` bucket to a dated backup bucket. Non-destructive.
2. **Convert**: `convert_manifests.py` rewrites every CAS manifest in place. Idempotent: skips manifests already in DAG format.
3. **Verify**: Point an orchestrator at the new bucket; exercise timeline + restore.
4. **Rollback (emergency only)**: `rollback.sh` restores the bucket contents from the backup.

### Entrypoint

`run_migration.sh` chains phases 1 -> 3 and prints a human-readable status after each phase. Read [MIGRATION_GUIDE.md](../../scripts/migration/unified-snapshots/MIGRATION_GUIDE.md) before invoking.

### Ownership

Owned by the storage team. Do not modify without coordinating on `#infra` because a partial run leaves the bucket in a split state.

## `scripts/migrations/` (standalone column adds)

Pre-Alembic scripts that add single columns. New work goes into Alembic (`orchestrator/alembic/versions/`), not here.

| Script | Column added |
|--------|--------------|
| `migrations/add_avatar_url_column.py` | `marketplace_agents.avatar_url` |
| `migrations/add_tool_configs_column.py` | `marketplace_agents.tool_configs` (JSON) |

## Related

- Alembic migrations: [docs/guides/database-migrations.md](../guides/database-migrations.md)
- Storage architecture: [docs/architecture/storage-architecture.md](../architecture/storage-architecture.md)
