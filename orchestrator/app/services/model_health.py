"""
Background model health checker.

Tests each LiteLLM model with a tiny completion every 10 minutes.
Results cached in distributed cache for the /api/marketplace/models endpoint.
"""

import asyncio
import logging
import time
from typing import Any

import aiohttp

from .cache_service import cache

logger = logging.getLogger(__name__)

CACHE_KEY = "litellm_model_health"
CACHE_TTL = 660  # 11 min — slightly longer than interval to avoid gaps
CHECK_INTERVAL = 600  # 10 minutes
MODEL_TIMEOUT = 30  # per-model completion timeout in seconds
PROBE_MAX_TOKENS = 3
PROBE_MESSAGE = "Say ok"


async def _probe_model(
    session: aiohttp.ClientSession, url: str, headers: dict, model_id: str
) -> dict[str, Any]:
    """Send a tiny completion to a single model and return its health result."""
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": PROBE_MESSAGE}],
        "max_tokens": PROBE_MAX_TOKENS,
        "temperature": 0,
    }
    start = time.monotonic()
    try:
        async with session.post(
            url,
            headers=headers,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=MODEL_TIMEOUT),
        ) as resp:
            latency = round(time.monotonic() - start, 2)
            if resp.status == 200:
                return {"status": "healthy", "latency": latency}
            # Try JSON first, fall back to raw text for non-JSON errors (HTML 502, etc.)
            try:
                body = await resp.json()
                error = body.get("error", {})
                msg = (
                    error.get("message", str(error))[:120]
                    if isinstance(error, dict)
                    else str(error)[:120]
                )
            except Exception:
                msg = (await resp.text())[:120]
            return {"status": "unhealthy", "latency": latency, "error": msg}
    except TimeoutError:
        return {"status": "timeout", "latency": round(time.monotonic() - start, 2)}
    except Exception as e:
        return {
            "status": "unhealthy",
            "latency": round(time.monotonic() - start, 2),
            "error": str(e)[:120],
        }


async def _run_health_cycle(base_url: str, headers: dict, model_ids: list[str]) -> dict[str, dict]:
    """Test all models in parallel with a shared HTTP session."""
    url = f"{base_url}/v1/chat/completions"
    async with aiohttp.ClientSession() as session:
        tasks = {
            model_id: asyncio.create_task(_probe_model(session, url, headers, model_id))
            for model_id in model_ids
        }
        results = {}
        for model_id, task in tasks.items():
            results[model_id] = await task
    return results


# Track the current cycle task so we can detect stuck cycles
_current_cycle: asyncio.Task | None = None


async def model_health_check_loop():
    """Background loop: every 10 min, test all LiteLLM models in parallel."""
    global _current_cycle

    from .litellm_service import litellm_service

    logger.info(
        "Model health check loop started (interval=%ds, timeout=%ds/model)",
        CHECK_INTERVAL,
        MODEL_TIMEOUT,
    )

    while True:
        try:
            # Read base_url/headers fresh each cycle so key rotations are picked up
            base_url = litellm_service.base_url.rstrip("/")
            if base_url.endswith("/v1"):
                base_url = base_url[:-3]
            headers = litellm_service.headers

            # 1. Get current model list from cached models (or fetch fresh)
            from .cache_service import cache as _cache

            cached_models = await _cache.get("litellm_models")
            if not cached_models:
                cached_models = await litellm_service.get_available_models()
            model_ids = [mid for m in cached_models if (mid := m.get("id"))]

            if not model_ids:
                logger.warning("Model health check: no models found, skipping cycle")
                await asyncio.sleep(CHECK_INTERVAL)
                continue

            # 2. If previous cycle is still running, mark stuck models as timeout
            if _current_cycle is not None and not _current_cycle.done():
                logger.warning(
                    "Previous health check cycle still running — cancelling and marking as timeout"
                )
                _current_cycle.cancel()
                timeout_map = {mid: {"status": "timeout", "latency": -1} for mid in model_ids}
                await cache.set(CACHE_KEY, timeout_map, ttl=CACHE_TTL)

            # 3. Run the new cycle as a tracked task
            _current_cycle = asyncio.create_task(_run_health_cycle(base_url, headers, model_ids))
            results = await _current_cycle

            # 4. Cache the results
            await cache.set(CACHE_KEY, results, ttl=CACHE_TTL)

            healthy = sum(1 for r in results.values() if r["status"] == "healthy")
            unhealthy = sum(1 for r in results.values() if r["status"] == "unhealthy")
            timed_out = sum(1 for r in results.values() if r["status"] == "timeout")
            logger.info(
                "Model health check complete: %d models — %d healthy, %d unhealthy, %d timeout",
                len(results),
                healthy,
                unhealthy,
                timed_out,
            )

        except asyncio.CancelledError:
            logger.info("Model health check loop cancelled, shutting down")
            raise
        except Exception as e:
            logger.error("Model health check error: %s", e, exc_info=True)

        await asyncio.sleep(CHECK_INTERVAL)
