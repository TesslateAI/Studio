# Feature Flags Router

**File**: `orchestrator/app/routers/feature_flags.py`

**Base path**: `/api/feature-flags`

## Purpose

Expose the server's feature-flag snapshot to the frontend so UI gating stays consistent with backend behavior. Flags are computed from config and, where applicable, per-user overrides.

## Endpoints

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/api/feature-flags` | optional | Return the flag snapshot for the caller. |

## Auth

Public; the payload differs for authenticated vs. anonymous callers (authenticated sees user-scoped overrides).

## Related

- Config: [config.py](../../../orchestrator/app/config.py) for flag sources.
