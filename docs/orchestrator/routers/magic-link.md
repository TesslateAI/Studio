# Magic Link Router

**File**: `orchestrator/app/routers/magic_link.py`

**Base path**: `/api/auth/magic-link`

## Purpose

Passwordless login via an emailed single-use link. Used for self-service onboarding and support-initiated account recovery.

## Endpoints

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/request` | public | Email a magic-link token to the supplied address (no-op if the address is unknown; does not leak account existence). |
| POST | `/consume` | token | Consume the magic-link token, create/rotate the session, and return JWT cookies. |
| POST | `/verify` | token | Non-destructively verify that a token is still valid (used by the frontend before rendering the consume step). |

## Auth

- `/request` is public and rate-limited.
- `/consume` and `/verify` authenticate via the opaque one-time token issued by `/request`. Tokens expire after a short TTL and are single-use on consume.

## Related

- Service: [../services/](../services/) (`magic_link_service.py`).
- Test helper: [test-helpers.md](test-helpers.md) exposes an inbox endpoint for E2E tests.
- Frontend: [../../app/pages/auth.md](../../app/pages/auth.md).
