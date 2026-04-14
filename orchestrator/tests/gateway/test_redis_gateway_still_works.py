"""
Smoke test: with Redis configured, gateway stream-watcher plumbing still
consumes agent events via the PubSub Protocol. Uses the pubsub factory reset
so a MockRedisPubSub stand-in is picked.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.pubsub import _reset_pubsub_for_tests, get_pubsub
from app.services.pubsub.local_pubsub import LocalPubSub


@pytest.mark.asyncio
async def test_get_pubsub_picks_redis_when_url_set():
    """When redis_url is set, get_pubsub() picks the Redis backend."""
    _reset_pubsub_for_tests()
    try:
        with patch("app.config.get_settings") as gs:
            gs.return_value.redis_url = "redis://localhost:6379/0"
            pub = get_pubsub()
            # Can't import RedisPubSub up top (avoid eager Redis connect).
            from app.services.pubsub.redis_pubsub import RedisPubSub

            assert isinstance(pub, RedisPubSub)
    finally:
        _reset_pubsub_for_tests()


@pytest.mark.asyncio
async def test_get_pubsub_picks_local_when_url_empty():
    _reset_pubsub_for_tests()
    try:
        with patch("app.config.get_settings") as gs:
            gs.return_value.redis_url = ""
            pub = get_pubsub()
            assert isinstance(pub, LocalPubSub)
    finally:
        _reset_pubsub_for_tests()
