# Users Router

**File**: `orchestrator/app/routers/users.py`

**Base path**: `/api/users`

## Purpose

Profile and preference endpoints layered on top of the fastapi-users router. Registered BEFORE the fastapi-users router so `/preferences` and `/profile` match before the `/{id}` catch-all.

## Endpoints

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/preferences` | user | Return user UI/agent preferences (theme, sidebar, default agent, etc.). |
| PATCH | `/preferences` | user | Update preferences (partial). |
| PATCH | `/me/handle` | user | Rename the current user's handle (unique, lowercased). |
| GET | `/profile` | user | Return public profile (handle, display name, avatar, bio). |
| PATCH | `/profile` | user | Update profile fields. |

## Auth

All endpoints require `current_active_user`.

## Related

- Schemas: `UserPreferencesResponse`, `UserProfile` in [schemas.py](../../../orchestrator/app/schemas.py).
- Model: `User` in [models.py](../../../orchestrator/app/models.py).
- fastapi-users CRUD (GET/PATCH `/users/{id}`) is registered after this router.
