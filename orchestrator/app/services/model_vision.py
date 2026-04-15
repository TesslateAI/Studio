"""
Model vision support from LiteLLM.

Shared module that fetches supports_vision from LiteLLM's /model/info endpoint.
Cached for 5 minutes, same pattern as model_pricing.py.

The LiteLLM proxy returns authoritative vision metadata for each deployed model,
unlike litellm.supports_vision() which only knows canonical model names and
fails on custom aliases (e.g. "claude-sonnet-4.6" vs "claude-sonnet-4-20250514").
"""

import logging

from .cache_service import cache

logger = logging.getLogger(__name__)

_VISION_CACHE_TTL = 300  # 5 minutes, matches model pricing


async def get_cached_model_vision_map() -> dict[str, bool]:
    """
    Build a model-name → supports_vision map from LiteLLM /model/info.

    Uses the model_name field (our custom alias) as the key, which matches
    what the /models endpoint returns as model id.

    Models with supports_vision=None are treated as False (unknown = no vision).
    """
    cache_key = "litellm_model_vision"

    cached = await cache.get(cache_key)
    if cached is not None:
        return cached

    from .litellm_service import litellm_service

    info_list = await litellm_service.get_model_info()

    vision_map: dict[str, bool] = {}
    for entry in info_list:
        model_name = entry.get("model_name")
        if not model_name:
            continue

        model_info = entry.get("model_info") or {}
        # None means unknown — treat as not vision-capable
        vision_map[model_name] = model_info.get("supports_vision") is True

    await cache.set(cache_key, vision_map, ttl=_VISION_CACHE_TTL)
    logger.info(
        f"Refreshed model vision cache ({sum(vision_map.values())}/{len(vision_map)} vision-capable)"
    )

    return vision_map


async def model_supports_vision(model_name: str) -> bool:
    """
    Check if a model supports vision input.

    Strips routing prefixes (builtin/, custom/, provider/) before lookup
    so callers don't need to worry about prefix handling.
    """
    from .model_adapters import resolve_model_name

    bare = resolve_model_name(model_name)
    vision_map = await get_cached_model_vision_map()
    return vision_map.get(bare, False)
