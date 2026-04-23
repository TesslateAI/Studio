# Webhooks Router

**File**: `orchestrator/app/routers/webhooks.py`

**Base path**: `/api/webhooks`

## Purpose

Inbound webhooks from third parties. Today only Stripe is wired here; messaging-platform webhooks live in [channels.md](channels.md).

## Endpoints

| Method | Path | Auth | Summary |
|--------|------|------|---------|
| POST | `/stripe` | Stripe signature | Handle Stripe events (subscription lifecycle, invoice paid, checkout completed, etc.). Updates `User.subscription_tier`, credits, and ledger entries. |

## Auth

The endpoint itself is unauthenticated; it verifies the `Stripe-Signature` header against `STRIPE_WEBHOOK_SECRET` and rejects unsigned/forged requests.

## Related

- Billing router: [billing.md](billing.md).
- Stripe integration: [../services/stripe.md](../services/stripe.md).
