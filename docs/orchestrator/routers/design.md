# Design Router

**File**: `orchestrator/app/routers/design.py`

**Base path**: `/api/projects/{project_slug}/design`

## Purpose

OID (object identifier) indexing and AST-based write-back for the visual design editor. Lets the frontend attach stable IDs to React/JSX elements and apply diffs (move, resize, restyle) back to source code without rewriting the whole file.

## Endpoints

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/index` | owner | Build/refresh the OID index for a project (walks the src tree and tags JSX nodes). |
| GET | `/index` | owner | Return the current OID index. |
| POST | `/apply-diff` | owner | Apply a structured diff (OID plus prop/style mutations) back to source via AST edits. |

## Auth

All endpoints require `current_active_user` and project ownership.

## Related

- Services: design indexing + AST tools in [../services/](../services/) (see `design/` subpackage).
- Models: `Project`, `ProjectFile` in [models.py](../../../orchestrator/app/models.py).
