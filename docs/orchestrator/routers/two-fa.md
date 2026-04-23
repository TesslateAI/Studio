# Two-Factor Auth Router

**File**: `orchestrator/app/routers/two_fa.py`

**Base path**: `/api/auth`

## Purpose

Email-based 2FA login flow. When `TWO_FA_ENABLED=true`, password login issues a short code via SMTP that the user must verify before a session is minted.

## Endpoints

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/login` | password | Step 1: validate password. If 2FA is enabled, emails a one-time code and returns `requires_2fa=True`. Otherwise logs the user in and sets cookies. |
| POST | `/2fa/verify` | challenge token | Step 2: verify the emailed code and mint the session. |
| POST | `/2fa/resend` | challenge token | Resend the 2FA code (rate-limited). |

## Auth

- `/login` accepts form credentials and validates via `UserManager`.
- `/2fa/verify` and `/2fa/resend` accept a short-lived challenge token issued by `/login`; no session cookie is required.
- On success, cookie + bearer JWTs are issued via the fastapi-users strategy.

## Config

- `TWO_FA_ENABLED` toggles the flow (default off).
- SMTP vars (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_SENDER_EMAIL`) deliver the code.

## Related

- Schemas: `LoginResponse`, `TwoFAVerifyRequest` in [schemas.py](../../../orchestrator/app/schemas.py).
- User manager: [../../../orchestrator/app/users.py](../../../orchestrator/app/users.py).
- Frontend: [../../app/pages/auth.md](../../app/pages/auth.md).
