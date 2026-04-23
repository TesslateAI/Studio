# Version Router

**File**: `orchestrator/app/routers/version.py`

**Base path**: `/api/version`

## Purpose

Deployment metadata and client compatibility check. Used by the frontend and the desktop shell to decide whether the client is speaking a compatible API version.

## Endpoints

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `` | public | Return build metadata (git sha, build time, schema version, deployment mode). |
| POST | `/check-compat` | public | Given a client version, return whether it is supported, deprecated, or blocked. |

## Auth

Public; no session required.

## Related

- Schemas: `VersionResponse`, `CompatResponse` in [schemas.py](../../../orchestrator/app/schemas.py).
- Desktop updater: [../../desktop/CLAUDE.md](../../desktop/CLAUDE.md).
