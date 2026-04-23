# Creators Router

**File**: `orchestrator/app/routers/creators.py`

**Base path**: `/api/creators`

## Purpose

Public-facing creator profile and agent catalog for the marketplace creator program. Backs the "creator page" UI where visitors browse an author's published agents and aggregate stats.

## Endpoints

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/by-username/{username}` | optional | Resolve a handle to a creator profile. |
| GET | `/check-username/{username}` | optional | Verify handle availability (used during onboarding). |
| GET | `/{user_id}` | optional | Full creator profile by user id. |
| GET | `/{user_id}/agents` | optional | Published agents for the creator. |
| GET | `/{user_id}/stats` | optional | Aggregate stats (downloads, revenue, follower count). |

## Auth

Public browsing; authenticated requests may receive additional fields (e.g., whether the viewer follows the creator).

## Related

- Models: `User`, `MarketplaceAgent` in [models.py](../../../orchestrator/app/models.py).
- Admin-side creator operations: [admin.md](admin.md).
- Marketplace listings: [marketplace.md](marketplace.md).
