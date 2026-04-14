# Custom SQLAlchemy types

## Purpose
Dialect-agnostic column types so orchestrator models run unchanged across
Postgres (cloud) and SQLite (desktop sidecar).

## Key files
- `guid.py` — `GUID` TypeDecorator: Postgres `UUID` / SQLite `CHAR(36)`

## Related contexts
- `/docs/orchestrator/models/CLAUDE.md` — model definitions
- `/docs/orchestrator/services/sqlite-compat.md` — dialect compatibility notes

## When to load
Adding a column that must work on both backends, or touching any existing
UUID-typed column.
