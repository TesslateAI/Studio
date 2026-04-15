"""
Prompt caching for LLM providers.

Injects cache_control breakpoints into message arrays for providers that
support explicit prompt caching (Anthropic Claude on Bedrock, direct API,
and via OpenRouter).  For providers with automatic caching (OpenAI,
DeepSeek, Groq, Together, Fireworks, etc.) this is a no-op.

Eligibility is determined from two sources — no hardcoded model names:

1. **Builtin / LiteLLM-proxied models** – the LiteLLM proxy config is the
   source of truth.  Models with ``supports_prompt_caching: true`` in their
   ``model_info`` block are eligible.  The orchestrator fetches this via
   ``/model/info`` at startup and caches the set in memory.

2. **BYOK providers** – ``BUILTIN_PROVIDERS`` in ``agent/models.py``.
   Any entry with ``"prompt_caching": "explicit"`` enables injection when
   the resolved model name retains that provider prefix (e.g.
   ``"anthropic/claude-3.5-sonnet"``).

How it works
------------
Anthropic prompt caching stores the KV-cache state at each breakpoint.
On subsequent requests whose message prefix matches a cached state, those
tokens are charged at 10 % of the base input price (90 % discount).
Writing to the cache costs 125 % (25 % surcharge), but any read on a
later call more than pays for it.

Strategy
--------
Up to four breakpoints per request (Anthropic recommended for tool-use loops):

1. **System message** – large, stable across every iteration.
2-4. **Trailing cache window** – the last 3 messages with cacheable content,
   creating a rolling cache of recent conversational turns.

On each LLM call old breakpoints are stripped and fresh ones injected so
that up to four breakpoints are present.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

_CACHE_CONTROL = {"type": "ephemeral"}

# In-memory set of builtin model names fetched from LiteLLM's /model/info
# where model_info.supports_prompt_caching is true.
# Populated by refresh_eligible_models() at app startup.
_eligible_builtin_models: set[str] | None = None


# ---------------------------------------------------------------------------
# Startup — populate eligible model set from LiteLLM
# ---------------------------------------------------------------------------


async def refresh_eligible_models() -> None:
    """Fetch model info from the LiteLLM proxy and cache which models
    have ``supports_prompt_caching: true`` in their ``model_info``.

    Call this once at app startup (``main.py``).  The result is stored in
    the module-level ``_eligible_builtin_models`` set and used by
    :func:`is_cache_eligible` for all subsequent checks.
    """
    global _eligible_builtin_models
    try:
        from ..services.litellm_service import litellm_service

        models = await litellm_service.get_model_info()
        _eligible_builtin_models = set()
        for entry in models:
            info = entry.get("model_info") or {}
            if info.get("supports_prompt_caching"):
                name = entry.get("model_name", "")
                if name:
                    _eligible_builtin_models.add(name)

        logger.info(
            "[PromptCaching] Loaded %d cache-eligible models from LiteLLM: %s",
            len(_eligible_builtin_models),
            sorted(_eligible_builtin_models),
        )
    except Exception:
        logger.warning(
            "[PromptCaching] Could not fetch model info from LiteLLM — "
            "prompt caching disabled for builtin models until next refresh",
            exc_info=True,
        )
        _eligible_builtin_models = set()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_cache_eligible(model_name: str) -> bool:
    """Return True if *model_name* requires explicit ``cache_control`` breakpoints.

    Two resolution paths (no hardcoded model names):

    1. **BYOK** – if the resolved model name has a ``/`` prefix matching a
       provider in ``BUILTIN_PROVIDERS`` with ``"prompt_caching": "explicit"``,
       return True.  Covers e.g. ``"anthropic/claude-3.5-sonnet"``
       (direct BYOK and OpenRouter-resolved names).

    2. **Builtin / LiteLLM** – check the in-memory set populated from the
       LiteLLM proxy's ``/model/info`` endpoint at startup.  Models whose
       config has ``supports_prompt_caching: true`` in ``model_info`` are
       eligible.
    """
    name = (model_name or "").strip()
    if not name:
        return False

    from .model_adapters import (
        extract_provider_slug,
        get_builtin_provider_config,
        resolve_model_name,
    )

    # --- BYOK path: check provider metadata ---
    provider = extract_provider_slug(name)
    if provider is not None:
        cfg = get_builtin_provider_config(provider)
        return cfg is not None and cfg.get("prompt_caching") == "explicit"

    # --- Builtin / LiteLLM path: check the set fetched at startup ---
    if _eligible_builtin_models is None:
        # Not yet populated (startup race) — safe no-op.
        return False

    # Normalise to the bare model name LiteLLM uses (strips "builtin/" etc.)
    bare = resolve_model_name(name)
    return bare in _eligible_builtin_models


def inject_cache_breakpoints(
    messages: list[dict[str, Any]],
    model_name: str,
) -> None:
    """Add ``cache_control`` breakpoints to *messages* **in-place**.

    No-op for non-eligible models.  Safe to call on every request.
    """
    if not messages or not is_cache_eligible(model_name):
        return

    # 1. Clear stale breakpoints from prior iterations.
    _strip_all_cache_control(messages)

    # 2. Breakpoint 1 – system message.
    if messages[0].get("role") == "system":
        _set_cache_control(messages[0])

    # 3. Breakpoints 2-4 – last 3 messages with cacheable content.
    #    Creates a rolling cache window of recent conversational turns.
    #    Anthropic supports up to 4 breakpoints for tool-use loops.
    breakpoints_placed = 0
    if len(messages) >= 3:
        for i in range(len(messages) - 2, 0, -1):
            if breakpoints_placed >= 3:
                break
            if _has_cacheable_content(messages[i]):
                _set_cache_control(messages[i])
                breakpoints_placed += 1

    logger.debug(
        "[PromptCaching] Injected breakpoints for %s (%d messages)",
        model_name,
        len(messages),
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _has_cacheable_content(msg: dict[str, Any]) -> bool:
    """Return True if the message has non-empty content we can annotate."""
    content = msg.get("content")
    return not (content is None or content == "")


def _set_cache_control(msg: dict[str, Any]) -> None:
    """Convert *msg* content to block format and tag the last block."""
    content = msg.get("content")
    if content is None:
        return

    blocks = _to_blocks(content)
    if not blocks:
        return

    # Tag the last block (works for text, image, tool_result, etc.).
    last = blocks[-1]
    if isinstance(last, dict):
        last["cache_control"] = _CACHE_CONTROL

    msg["content"] = blocks


def _strip_all_cache_control(messages: list[dict[str, Any]]) -> None:
    """Remove ``cache_control`` from every content block, simplifying back
    to plain strings when possible so messages stay clean for logging."""
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            continue

        for block in content:
            if isinstance(block, dict):
                block.pop("cache_control", None)

        # Simplify [{"type": "text", "text": "…"}] → "…"
        if (
            len(content) == 1
            and isinstance(content[0], dict)
            and set(content[0].keys()) == {"type", "text"}
            and content[0].get("type") == "text"
        ):
            msg["content"] = content[0]["text"]


def _to_blocks(content: Any) -> list[dict[str, Any]]:
    """Normalise content to the content-block array format."""
    if isinstance(content, list):
        return content
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    # Fallback – unlikely but safe.
    return [{"type": "text", "text": str(content)}]
