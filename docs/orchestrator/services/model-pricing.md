# Model Pricing

**File**: `orchestrator/app/services/model_pricing.py`

Dynamic model pricing from LiteLLM's `/model/info` endpoint with caching and Decimal arithmetic.

## How It Works

1. **Fetch**: Calls LiteLLM `/model/info` to get per-token costs for all configured models
2. **Cache**: Stores pricing map in distributed cache (Redis or in-memory) for 5 minutes
3. **Lookup**: On each AI request, looks up the model's pricing (exact → partial → fallback)
4. **Calculate**: Converts token counts to cost in cents using Decimal arithmetic

## API

### `get_cached_model_pricing_map()` → `dict[str, dict[str, float]]`

Returns a model-name → `{input, output}` pricing map. Prices are in **USD per 1M tokens**. Cached for 5 minutes (`_PRICING_CACHE_TTL = 300`).

### `get_model_pricing(model)` → `dict[str, float]`

Returns `{input, output}` pricing for a specific model. Lookup order:
1. Exact match on model name
2. Partial match (substring in either direction)
3. Fallback: `{input: 1.00, output: 3.00}` USD per 1M tokens

### `calculate_cost_cents(model, tokens_in, tokens_out)` → `(int, int, int)`

Calculates cost in **cents** for given token counts.

**Formula** (using Decimal arithmetic):
```
raw_input  = (tokens_in / 1,000,000) * price_per_1M_input  * 100
raw_output = (tokens_out / 1,000,000) * price_per_1M_output * 100
cost_input  = ceil(raw_input)  if raw_input > 0 else 0
cost_output = ceil(raw_output) if raw_output > 0 else 0
cost_total  = cost_input + cost_output
```

**Ceil rounding**: Any non-zero usage costs at least 1 cent. This prevents "free" usage from tiny requests.

## Decimal Precision

All financial arithmetic uses `decimal.Decimal` to avoid floating-point errors:

```python
raw_input = Decimal(str(tokens_in)) / Decimal("1000000") * Decimal(str(pricing["input"])) * Decimal("100")
```

This ensures exact results — e.g., `0.1 + 0.2 == 0.3` (unlike float where `0.1 + 0.2 == 0.30000000000000004`).

## Fallback Pricing

If a model is not found in LiteLLM's pricing data, default pricing applies:
- Input: $1.00 per 1M tokens
- Output: $3.00 per 1M tokens

A warning is logged when fallback pricing is used.

## Cache Behavior

- **TTL**: 5 minutes (300 seconds)
- **Backend**: Uses `cache_service` (Redis with in-memory fallback)
- **Key**: `litellm_model_pricing`
- **Refresh**: Automatic on cache miss; logs the number of models with pricing data

## Related

- [credit-system.md](./credit-system.md) — Credit deduction that uses this pricing
- [../routers/billing.md](../routers/billing.md) — Billing API endpoints
