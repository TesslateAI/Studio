"""
PubSub package — picks a backend based on whether Redis is configured.

Public surface (import sites across the app depend on this being stable):
    from app.services.pubsub import get_pubsub
    from app.services.pubsub import (
        CHANNEL_PREFIX, AGENT_STREAM_PREFIX,
        PROJECT_LOCK_PREFIX, CHAT_LOCK_PREFIX, CANCEL_KEY_PREFIX,
    )

Backends:
- RedisPubSub (redis_pubsub.py) — used when settings.redis_url is set (cloud).
- LocalPubSub (local_pubsub.py) — in-process fallback (desktop sidecar).
"""

from __future__ import annotations

from .base import (
    AGENT_STREAM_PREFIX,
    APP_RUNTIME_STREAM_PREFIX,
    CANCEL_KEY_PREFIX,
    CHANNEL_PREFIX,
    CHAT_LOCK_PREFIX,
    PROJECT_LOCK_PREFIX,
    PubSub,
)
from .local_pubsub import LocalPubSub
from .redis_pubsub import (
    RedisPubSub,
    publish_app_runtime_event,
    subscribe_app_runtime_events,
)

_pubsub: PubSub | None = None


def get_pubsub() -> PubSub:
    """
    Return the process-wide PubSub backend.

    Picks RedisPubSub when settings.redis_url is set, else LocalPubSub.
    Cached on first access so all callers share state (locks, streams, etc.).
    """
    global _pubsub
    if _pubsub is not None:
        return _pubsub

    from ...config import get_settings

    settings = get_settings()
    redis_url = getattr(settings, "redis_url", "") or ""
    _pubsub = RedisPubSub() if redis_url else LocalPubSub()
    return _pubsub


def _reset_pubsub_for_tests() -> None:
    """Test-only: clear the cached backend so the factory re-picks."""
    global _pubsub
    _pubsub = None


__all__ = [
    "PubSub",
    "RedisPubSub",
    "LocalPubSub",
    "get_pubsub",
    "CHANNEL_PREFIX",
    "AGENT_STREAM_PREFIX",
    "APP_RUNTIME_STREAM_PREFIX",
    "PROJECT_LOCK_PREFIX",
    "CHAT_LOCK_PREFIX",
    "CANCEL_KEY_PREFIX",
    "publish_app_runtime_event",
    "subscribe_app_runtime_events",
]
