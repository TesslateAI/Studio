"""Tests for chat-lock takeover semantics (stop-as-undo).

The ``acquire_chat_lock`` contract changed so a new task can atomically take
over the lock from a holder whose cancellation flag is set. This file locks
that behavior in place since it's load-bearing for the UX ("stop is undo")
and for multiple-agents-per-project concurrency.
"""

from __future__ import annotations

import pytest

from app.services.pubsub.local_pubsub import LocalPubSub


@pytest.mark.asyncio
async def test_acquire_succeeds_when_free():
    pub = LocalPubSub()
    assert await pub.acquire_chat_lock("c1", "taskA") is True


@pytest.mark.asyncio
async def test_live_holder_blocks_new_acquire():
    pub = LocalPubSub()
    assert await pub.acquire_chat_lock("c1", "taskA") is True
    # taskB is blocked while taskA is live (no cancel flag set).
    assert await pub.acquire_chat_lock("c1", "taskB") is False


@pytest.mark.asyncio
async def test_cancelled_holder_is_taken_over_atomically():
    """The core of stop-as-undo: one call, instant takeover."""
    pub = LocalPubSub()
    assert await pub.acquire_chat_lock("c1", "taskA") is True
    await pub.request_cancellation("taskA")
    # taskB takes over atomically — no retry loop, no timeout.
    assert await pub.acquire_chat_lock("c1", "taskB") is True
    # taskA's expire-only release is a no-op now that taskB owns the lock.
    assert await pub.release_chat_lock("c1", "taskA") is False
    # taskC is blocked — taskB has no cancel flag.
    assert await pub.acquire_chat_lock("c1", "taskC") is False


@pytest.mark.asyncio
async def test_extend_detects_stolen_lock():
    """An evicted task must see extend fail so it can exit quietly."""
    pub = LocalPubSub()
    assert await pub.acquire_chat_lock("c1", "taskA") is True
    await pub.request_cancellation("taskA")
    assert await pub.acquire_chat_lock("c1", "taskB") is True
    # taskA's heartbeat would try to extend — must fail so the agent loop
    # stops extending and exits.
    assert await pub.extend_chat_lock("c1", "taskA") is False
    # taskB's heartbeat still works.
    assert await pub.extend_chat_lock("c1", "taskB") is True


@pytest.mark.asyncio
async def test_same_task_reacquire_refreshes_ttl():
    """An already-owning task calling acquire should succeed (refresh)."""
    pub = LocalPubSub()
    assert await pub.acquire_chat_lock("c1", "taskA") is True
    assert await pub.acquire_chat_lock("c1", "taskA") is True


@pytest.mark.asyncio
async def test_force_release_unsticks_even_without_cancel_flag():
    pub = LocalPubSub()
    assert await pub.acquire_chat_lock("c1", "taskA") is True
    released = await pub.force_release_chat_lock("c1")
    assert released is True
    # Force-release also flags cancellation so any in-flight worker sees it.
    assert await pub.is_cancelled("taskA") is True
    # Lock is now free.
    assert await pub.acquire_chat_lock("c1", "taskB") is True
