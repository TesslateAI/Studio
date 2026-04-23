# Referrals Router

**File**: `orchestrator/app/routers/referrals.py`

**Base path**: `/api`

## Purpose

Track referral landings and surface referral stats for the current user.

## Endpoints

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/track-landing` | public | Record a landing visit with a `ref` code (sets a cookie so signup attribution survives navigation). |
| GET | `/referrals/stats` | user | Return referral totals (clicks, signups, rewards) for the current user. |

## Auth

`track-landing` is public; `referrals/stats` requires `current_active_user`.

## Related

- Models: `Referral`, `User.referral_code` in [models.py](../../../orchestrator/app/models.py).
