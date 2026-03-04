"""
Dynamic model pricing from LiteLLM.

Shared module used by marketplace, credit_service, and usage_service.
Fetches real pricing from LiteLLM's /model/info endpoint, caches for 5 minutes.
"""

import logging
import math
from decimal import Decimal

from .cache_service import cache

logger = logging.getLogger(__name__)

# Cache TTL for pricing data (5 minutes)
_PRICING_CACHE_TTL = 300

# Fallback pricing for unknown models (USD per 1M tokens)
_DEFAULT_PRICING = {"input": 1.00, "output": 3.00}


async def get_cached_model_pricing_map() -> dict[str, dict[str, float]]:
    """
    Build a model-id -> {input, output} pricing map from LiteLLM /model/info.

    Prices are returned in USD per 1M tokens. The proxy reports per-token
    costs, so we multiply by 1_000_000 here. Results are cached for 5 minutes.
    """
    cache_key = "litellm_model_pricing"

    cached = await cache.get(cache_key)
    if cached is not None:
        return cached

    from .litellm_service import litellm_service

    info_list = await litellm_service.get_model_info()

    pricing_map: dict[str, dict[str, float]] = {}
    for entry in info_list:
        model_info = entry.get("model_info") or {}
        model_name = entry.get("model_name") or model_info.get("id")
        if not model_name:
            continue

        input_cost = model_info.get("input_cost_per_token")
        output_cost = model_info.get("output_cost_per_token")
        if input_cost is not None or output_cost is not None:
            pricing_map[model_name] = {
                "input": round((input_cost or 0) * 1_000_000, 4),
                "output": round((output_cost or 0) * 1_000_000, 4),
            }

    await cache.set(cache_key, pricing_map, ttl=_PRICING_CACHE_TTL)
    logger.info(f"Refreshed model pricing cache ({len(pricing_map)} models with pricing)")

    return pricing_map


async def get_model_pricing(model: str) -> dict[str, float]:
    """
    Return {input, output} pricing (USD per 1M tokens) for a specific model.

    Tries exact match, then partial match, then falls back to defaults.
    """
    pricing_map = await get_cached_model_pricing_map()

    # Exact match
    if model in pricing_map:
        return pricing_map[model]

    # Partial match (e.g. "gpt-4o" matches "builtin/gpt-4o")
    model_lower = model.lower()
    for key in pricing_map:
        if key in model_lower or model_lower in key:
            return pricing_map[key]

    logger.warning(f"Unknown model pricing for {model}, using default")
    return _DEFAULT_PRICING


async def calculate_cost_cents(model: str, tokens_in: int, tokens_out: int) -> tuple[int, int, int]:
    """
    Calculate cost in cents for a given model and token counts.

    Uses Decimal arithmetic to avoid floating-point errors in financial calculations.
    Ceil rounding means any non-zero usage costs at least 1 cent.

    Returns:
        (cost_input_cents, cost_output_cents, cost_total_cents)
    """
    pricing = await get_model_pricing(model)

    # pricing is USD per 1M tokens; convert to cents using Decimal for precision.
    raw_input = (
        Decimal(str(tokens_in))
        / Decimal("1000000")
        * Decimal(str(pricing["input"]))
        * Decimal("100")
    )
    raw_output = (
        Decimal(str(tokens_out))
        / Decimal("1000000")
        * Decimal(str(pricing["output"]))
        * Decimal("100")
    )

    cost_input = math.ceil(raw_input) if raw_input > 0 else 0
    cost_output = math.ceil(raw_output) if raw_output > 0 else 0
    cost_total = cost_input + cost_output

    return cost_input, cost_output, cost_total
