# tests/migrations

## Purpose
Programmatic alembic checks that run `upgrade head` on a fresh SQLite
database and verify new columns / tables are wired up. Guards against
migrations that work in Postgres but silently break the desktop SQLite
path.

## Key files
- `test_0049_runtime_fields.py` — projects.runtime / source_path /
  sync_enabled columns exist and are writable after upgrade.

## Related contexts
- `orchestrator/alembic/versions/` — migration scripts.
- `app/models.py` — ORM column definitions.

## When to load
Load when adding a new alembic migration, especially one that touches the
`projects` table or needs SQLite compatibility for the desktop shell.
