# Auth Router

**File**: `orchestrator/app/routers/auth.py`

**Base path**: `/api/auth`

## Purpose

Custom session lifecycle endpoints layered on top of fastapi-users. Handles JWT refresh from the HTTP-only cookie, logout (cookie clear), and dev-server access verification (used by the dev-server reverse proxy to confirm the caller owns the requested project).

For registration, password reset, and email verification, see the fastapi-users routers mounted in [main.py](../../../orchestrator/app/main.py). For email 2FA and magic-link flows, see [two-fa.md](two-fa.md) and [magic-link.md](magic-link.md).

## Endpoints

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/refresh` | refresh cookie | Rotate the access token using the refresh cookie. Returns 401 if the cookie is missing or invalid. |
| POST | `/logout` | any | Clear auth cookies server-side. |
| GET | `/verify-access` | user | Confirm the caller owns `project_slug`; used by the dev-server proxy / container gateway to gate preview URLs. |

## Auth

`/refresh` reads the refresh JWT from the `tesslate_refresh` cookie. `/logout` accepts any request (idempotent). `/verify-access` requires `current_active_user` and validates project ownership via `Project.owner_id`.

## Related

- JWT strategy + cookie backends: [../../../orchestrator/app/users.py](../../../orchestrator/app/users.py).
- Frontend auth flow: [../../app/pages/auth.md](../../app/pages/auth.md).
- Related routers: [two-fa.md](two-fa.md), [magic-link.md](magic-link.md).
