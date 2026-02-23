# Credit System

**File**: `orchestrator/app/services/credit_service.py`

Handles real-time credit deduction for AI usage billing with multi-source credit pools, BYOK bypass, and race condition protection.

## Architecture

### Credit Types (4 pools)

| Type | Source | Resets | Deduction Priority |
|------|--------|--------|-------------------|
| **Daily** | Free-tier only (5/day) | UTC midnight | 1st (highest) |
| **Bundled** | Subscription allowance | Billing cycle | 2nd |
| **Signup Bonus** | Registration gift | Expires after N days | 3rd |
| **Purchased** | Credit packages | Never expires | 4th (last resort) |

**Deduction priority**: daily → bundled → signup_bonus → purchased. The cheapest/most-expirable credits are consumed first to maximize value of purchased credits.

### Credit Values

Credits are measured in **cents** (1 credit = $0.01 USD).

| Tier | Monthly Bundled | Daily |
|------|----------------|-------|
| Free | 0 | 5 |
| Basic ($20/mo) | 500 | 0 |
| Pro ($49/mo) | 2,000 | 0 |
| Ultra ($149/mo) | 8,000 | 0 |

### Credit Packages (one-time purchase)

| Package | Credits | Price |
|---------|---------|-------|
| Small | 500 | $5 |
| Medium | 2,500 | $25 |
| Large | 10,000 | $100 |
| Team | 50,000 | $500 |

## API

### `check_credits(user, model_name)` → `(bool, str)`

Pre-request guard. Returns `(True, "")` if the user can proceed, or `(False, error_message)` if insufficient credits. BYOK models always return True.

### `deduct_credits(db, user_id, model_name, tokens_in, tokens_out, agent_id?, project_id?)` → `dict`

Post-request deduction. Creates a `UsageLog` entry regardless of cost (including BYOK/zero-cost).

Returns:
```python
{
    "cost_total": 15,         # Total cost in cents
    "credits_deducted": 15,   # Credits actually taken
    "new_balance": 485,       # User's remaining total_credits
    "usage_log_id": "uuid",   # Created UsageLog ID
    "is_byok": False,         # Whether BYOK was used
}
```

### `is_byok_model(model_name)` → `bool`

Checks if a model uses the user's own API key (BYOK). Provider prefixes are derived from `BUILTIN_PROVIDERS` in `agent/models.py` — the single source of truth. Adding a new provider there automatically makes it recognized as BYOK.

## Race Condition Handling

The deduction uses `SELECT FOR UPDATE` to lock the user row during credit modification:

```python
result = await db.execute(
    select(User).where(User.id == user_id).with_for_update()
)
```

If a serialization failure occurs (e.g., concurrent requests), the operation retries up to 3 times with automatic rollback between attempts.

## BYOK Bypass

When a model is identified as BYOK (uses user's own API key), the cost is $0 and no credits are deducted. A `UsageLog` entry is still created with `is_byok=True` and `billed_status="exempt"` for analytics tracking.

## Integration

### With `model_pricing.py`
Credit service calls `calculate_cost_cents(model, tokens_in, tokens_out)` to determine the cost before deduction. See [model-pricing.md](./model-pricing.md).

### With `usage_service.py`
Both create `UsageLog` entries. The credit service creates entries during real-time deduction; the usage service provides aggregation and reporting.

### With `daily_credit_reset.py`
Background loop resets `daily_credits` for free-tier users at UTC midnight (hourly check). Also expires signup bonuses past their expiry date.

## Related

- [model-pricing.md](./model-pricing.md) — LiteLLM pricing cache and cost calculation
- [stripe.md](./stripe.md) — Stripe checkout for credit purchases and subscriptions
- [../routers/billing.md](../routers/billing.md) — Billing API endpoints
