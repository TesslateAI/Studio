# Test Helpers Router

**File**: `orchestrator/app/routers/test_helpers.py`

**Base path**: `/api/__test__`

## Purpose

E2E-test-only helpers. Only mounted when the harness enables test mode (see `main.py` guard). In production builds these routes do not exist.

## Endpoints

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| GET | `/magic-link-inbox` | test mode | Return the most recently emitted magic-link tokens so Playwright tests can complete the login flow without SMTP. |

## Auth

Gated by the mount-time feature flag; there is no per-request auth. **Never enable in production.**

## Related

- Magic link flow: [magic-link.md](magic-link.md).
