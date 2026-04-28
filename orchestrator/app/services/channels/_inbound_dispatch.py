"""Shared inbound-dispatch helpers for messaging-platform adapters (Phase 4).

Two responsibilities:

  * :func:`post_approval_response_locally` — when a button click arrives
    on the inbound socket, route it directly to the same code path that
    ``POST /api/chat/approval/{input_id}/respond`` uses (the
    ``PendingUserInputManager`` + Redis pubsub for cross-pod delivery).
    This guarantees button clicks NEVER enter ``_pending_messages``
    (the chat-session ordering layer).

  * :func:`dispatch_gateway_command` — common wrapper for slash-command
    payloads that opens an ``AsyncSession``, looks up the dispatch
    handler for the platform, and runs it. The adapter just hands us
    the normalized payload.

Both helpers are async, idempotent on retries, and never raise — failures
are logged and surfaced as audit fields on the related row.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


__all__ = [
    "post_approval_response_locally",
    "dispatch_gateway_command",
]


async def post_approval_response_locally(
    *,
    input_id: str,
    choice: str,
    platform: str,
    platform_user_id: str | None = None,
) -> bool:
    """Resolve an approval-card button click to a stored approval response.

    Equivalent to a synthetic POST to
    ``/api/chat/approval/{input_id}/respond`` but skips the HTTP layer
    entirely. Returns ``True`` if the response was delivered (or
    cached for a late-arriving request).

    The choice strings used by Phase 4 (``allow_once`` ·
    ``allow_for_run`` · ``allow_permanently`` · ``deny``) extend the
    legacy set (``allow_once`` · ``allow_all`` · ``stop``); the
    ``PendingUserInputManager`` accepts arbitrary string payloads, so
    the new vocabulary lands without a manager-side change.
    """
    if not input_id or not choice:
        return False

    try:
        from ...agent.tools.approval_manager import (
            get_approval_manager,
            publish_approval_response,
        )
    except Exception:  # pragma: no cover - defensive
        logger.exception("[INBOUND] failed to import approval_manager")
        return False

    try:
        # Local in-process delivery (works on the same pod as the
        # waiting agent loop).
        get_approval_manager().respond_to_approval(input_id, choice)
        # Cross-pod delivery via the existing Redis pubsub channel.
        await publish_approval_response(input_id, choice)
    except Exception:
        logger.exception(
            "[INBOUND] approval response failed input=%s choice=%s",
            input_id,
            choice,
        )
        return False

    logger.info(
        "[INBOUND] approval response %s=%s from %s user=%s",
        input_id,
        choice,
        platform,
        platform_user_id,
    )
    return True


async def dispatch_gateway_command(
    *,
    payload: dict[str, Any],
    channel_config_id: str | uuid.UUID,
    handler: Callable[..., Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    """Open an ``AsyncSession``, resolve an ARQ pool, and run ``handler``.

    Returns the handler's response dict, or an error envelope if any
    step failed. Never raises — adapters use this from inside socket
    callbacks that swallow exceptions silently otherwise.
    """
    cc_id: uuid.UUID
    try:
        cc_id = (
            channel_config_id
            if isinstance(channel_config_id, uuid.UUID)
            else uuid.UUID(str(channel_config_id))
        )
    except Exception:
        logger.warning(
            "[INBOUND] dispatch_gateway_command: bad channel_config_id=%r",
            channel_config_id,
        )
        return {"ack": "ok", "error": "bad_channel_config_id"}

    try:
        from ...database import AsyncSessionLocal
    except Exception:  # pragma: no cover - defensive
        logger.exception("[INBOUND] failed to import AsyncSessionLocal")
        return {"ack": "ok", "error": "no_db"}

    arq_pool = await _get_arq_pool()

    try:
        async with AsyncSessionLocal() as db:
            return await handler(
                payload=payload,
                channel_config_id=cc_id,
                db=db,
                arq_pool=arq_pool,
            )
    except Exception:
        logger.exception(
            "[INBOUND] dispatch_gateway_command: handler raised channel=%s",
            cc_id,
        )
        return {"ack": "ok", "error": "handler_raised"}


# ---------------------------------------------------------------------------
# Lightweight ARQ pool accessor — same module-singleton pattern used in
# routers/app_triggers.py so adapters can dispatch directly without
# touching an HTTP layer.
# ---------------------------------------------------------------------------


_arq_pool: Any = None


async def _get_arq_pool() -> Any:
    """Return a cached ARQ pool or ``None`` if Redis isn't configured.

    On no-Redis (desktop) the trigger common helper falls through to
    ``get_task_queue().enqueue(...)`` which is the right thing.
    """
    global _arq_pool
    if _arq_pool is not None:
        return _arq_pool

    try:
        from urllib.parse import urlparse

        from arq import create_pool
        from arq.connections import RedisSettings

        from ...config import get_settings

        settings = get_settings()
        redis_url = getattr(settings, "redis_url", "") or ""
        if not redis_url:
            return None
        parsed = urlparse(redis_url)
        _arq_pool = await create_pool(
            RedisSettings(
                host=parsed.hostname or "redis",
                port=parsed.port or 6379,
                database=int((parsed.path or "/0").lstrip("/") or "0"),
                password=parsed.password,
            )
        )
    except Exception:
        logger.exception("[INBOUND] failed to create ARQ pool — using fallback")
        _arq_pool = None
    return _arq_pool
