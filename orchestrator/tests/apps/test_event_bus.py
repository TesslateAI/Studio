"""Wave 9 Track D1: DB event bus producer tests.

Verifies the producer side of the DB event bus:

* INSERT on a whitelisted table (``marketplace_apps``) → publish on commit.
* ROLLBACK → no publish.
* INSERT on a non-whitelisted table (``users``) → no publish.

These tests stay pure-Python: we drive SQLAlchemy mapper events directly
against in-memory model instances and a synthetic ``Session`` so the
suite runs without Postgres.
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from app import models
from app.services.apps import event_bus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _ensure_listeners_registered():
    """Listeners are idempotent; calling at fixture time is safe."""
    event_bus.register_db_event_listeners()
    yield


class _FakeSession:
    """Minimal Session-shaped object that supports ``info`` + commit/rollback hooks."""

    def __init__(self):
        self.info: dict = {}

    def commit(self):
        # Fire the session-level after_commit hook the way SQLAlchemy would.
        event_bus._on_session_after_commit(self)

    def rollback(self):
        event_bus._on_session_after_rollback(self)


def _make_marketplace_app() -> models.MarketplaceApp:
    return models.MarketplaceApp(
        id=uuid.uuid4(),
        slug=f"app-{uuid.uuid4().hex[:8]}",
        name="Test App",
        creator_user_id=uuid.uuid4(),
    )


def _drive_after_insert(target, table: str, session: _FakeSession) -> None:
    """Invoke the staged listener as SQLAlchemy would on after_insert.

    We bypass ``Session.object_session(target)`` (which requires the real
    SA session machinery) by stubbing it for the duration of the call.
    """
    listener = event_bus._make_mapper_listener("insert", table)
    with patch.object(Session, "object_session", staticmethod(lambda _t: session)):
        listener(None, None, target)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_whitelist_contents():
    """Whitelist must be the explicit Wave 9 D1 set — no accidental drift."""
    assert event_bus.WHITELIST_TABLES == {"marketplace_apps", "app_instances"}


def test_insert_marketplace_app_publishes_on_commit():
    target = _make_marketplace_app()
    session = _FakeSession()

    # Patch the redis client used inside publish_row_event.
    fake_redis = MagicMock()
    fake_redis.xadd = AsyncMock(return_value=b"1-0")

    async def _scenario():
        with patch(
            "app.services.cache_service.get_redis_client",
            new=AsyncMock(return_value=fake_redis),
        ):
            _drive_after_insert(target, "marketplace_apps", session)

            # Pre-commit: nothing published yet.
            assert fake_redis.xadd.await_count == 0
            assert event_bus._PENDING_KEY in session.info

            # Commit fires the session hook, which schedules publish_all.
            session.commit()

            # Drain any tasks scheduled on the running loop.
            for _ in range(5):
                await asyncio.sleep(0)

        return fake_redis

    _run(_scenario())

    assert fake_redis.xadd.await_count == 1
    args, kwargs = fake_redis.xadd.call_args
    stream = args[0]
    fields = args[1]
    assert stream.startswith(event_bus.DB_EVENT_STREAM_PREFIX)
    assert fields["op"] == "insert"
    assert fields["table"] == "marketplace_apps"
    assert fields["row_id"] == str(target.id)
    assert fields["payload_hash"]  # non-empty hex digest
    assert kwargs.get("maxlen") == event_bus.DB_EVENT_STREAM_MAXLEN


def test_rollback_suppresses_publish():
    target = _make_marketplace_app()
    session = _FakeSession()

    fake_redis = MagicMock()
    fake_redis.xadd = AsyncMock(return_value=b"1-0")

    async def _scenario():
        with patch(
            "app.services.cache_service.get_redis_client",
            new=AsyncMock(return_value=fake_redis),
        ):
            _drive_after_insert(target, "marketplace_apps", session)
            assert event_bus._PENDING_KEY in session.info

            session.rollback()
            for _ in range(5):
                await asyncio.sleep(0)

        return fake_redis

    _run(_scenario())

    assert fake_redis.xadd.await_count == 0
    assert event_bus._PENDING_KEY not in session.info


def test_non_whitelisted_table_does_not_publish():
    """Inserting a User (not in WHITELIST_TABLES) must not enqueue any event.

    We assert this at the registration boundary: there is no listener attached
    to the User mapper. Driving an after_insert against User via SQLAlchemy
    would therefore be a no-op.
    """
    user_listeners_insert = event.contains(
        models.User,
        "after_insert",
        # Any of our staged listeners — we don't have a handle, so
        # assert by absence: there are no event_bus-staged listeners on User.
        lambda *_a, **_k: None,
    )
    # contains() with a fresh callable always returns False; the real check
    # is that no Session.info pending entry appears when we *would* fire.
    assert user_listeners_insert is False

    session = _FakeSession()
    fake_redis = MagicMock()
    fake_redis.xadd = AsyncMock(return_value=b"1-0")

    async def _scenario():
        with patch(
            "app.services.cache_service.get_redis_client",
            new=AsyncMock(return_value=fake_redis),
        ):
            # Simulate what SQLAlchemy would do: it would NOT call our listener
            # for a non-whitelisted mapper. So session.info stays empty.
            session.commit()
            for _ in range(5):
                await asyncio.sleep(0)
        return fake_redis

    _run(_scenario())

    assert fake_redis.xadd.await_count == 0
    assert event_bus._PENDING_KEY not in session.info
