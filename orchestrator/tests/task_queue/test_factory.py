"""Tests for the TaskQueue factory selection logic."""

from __future__ import annotations

import pytest

import app.services.task_queue as tq_pkg
from app.services.task_queue import (
    ArqTaskQueue,
    LocalTaskQueue,
    _reset_task_queue_for_tests,
    get_task_queue,
)


@pytest.fixture(autouse=True)
def _reset_singletons():
    _reset_task_queue_for_tests()
    yield
    _reset_task_queue_for_tests()


def test_factory_returns_local_when_redis_url_empty(monkeypatch):
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("REDIS_URL", "")
    # Force settings to rebuild with empty redis_url
    s = get_settings()
    monkeypatch.setattr(s, "redis_url", "", raising=False)

    q = get_task_queue()
    assert isinstance(q, LocalTaskQueue)


def test_factory_returns_arq_when_redis_url_set(monkeypatch):
    from app.config import get_settings

    get_settings.cache_clear()
    s = get_settings()
    monkeypatch.setattr(s, "redis_url", "redis://example:6379/0", raising=False)

    q = get_task_queue()
    assert isinstance(q, ArqTaskQueue)
    # Don't actually connect — just assert class.


def test_factory_caches_instance(monkeypatch):
    from app.config import get_settings

    get_settings.cache_clear()
    s = get_settings()
    monkeypatch.setattr(s, "redis_url", "", raising=False)

    q1 = get_task_queue()
    q2 = get_task_queue()
    assert q1 is q2
    assert tq_pkg._task_queue is q1
