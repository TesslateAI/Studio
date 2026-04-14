"""
Unit tests for :mod:`app.agent.tools.file_ops.edit_history`.

These tests exercise the ring-buffer bookkeeping in isolation — they do
not touch the filesystem or any orchestrator.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ORCHESTRATOR_ROOT = Path(__file__).resolve().parents[4]
if str(_ORCHESTRATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_ORCHESTRATOR_ROOT))

from app.agent.tools.file_ops.edit_history import EDIT_HISTORY, EditHistory  # noqa: E402

pytestmark = pytest.mark.asyncio


async def test_record_and_pop_latest_round_trip() -> None:
    hist = EditHistory(capacity=10)
    await hist.record("src/a.py", "one", "edit")
    await hist.record("src/a.py", "two", "edit")
    await hist.record("src/b.py", "alpha", "write")

    latest_a = await hist.pop_latest("src/a.py")
    assert latest_a is not None
    assert latest_a.prev_content == "two"
    assert latest_a.op == "edit"

    penultimate_a = await hist.pop_latest("src/a.py")
    assert penultimate_a is not None
    assert penultimate_a.prev_content == "one"

    third_a = await hist.pop_latest("src/a.py")
    assert third_a is None

    b_entry = await hist.pop_latest("src/b.py")
    assert b_entry is not None
    assert b_entry.prev_content == "alpha"
    assert b_entry.op == "write"


async def test_pop_latest_returns_none_for_unknown_path() -> None:
    hist = EditHistory(capacity=10)
    await hist.record("one.py", "contents", "write")
    assert await hist.pop_latest("other.py") is None


async def test_all_returns_snapshot_oldest_first() -> None:
    hist = EditHistory(capacity=10)
    await hist.record("a", "1", "write")
    await hist.record("b", "2", "edit")
    await hist.record("c", "3", "delete")

    snapshot = await hist.all()
    assert [e.path for e in snapshot] == ["a", "b", "c"]

    # Mutating after snapshot does not affect the returned list.
    await hist.record("d", "4", "write")
    assert [e.path for e in snapshot] == ["a", "b", "c"]


async def test_ring_buffer_evicts_oldest_past_capacity() -> None:
    hist = EditHistory(capacity=3)
    await hist.record("a", "1", "write")
    await hist.record("b", "2", "write")
    await hist.record("c", "3", "write")
    await hist.record("d", "4", "write")

    snapshot = await hist.all()
    assert [e.path for e in snapshot] == ["b", "c", "d"]
    assert await hist.pop_latest("a") is None


async def test_clear_empties_buffer() -> None:
    hist = EditHistory(capacity=5)
    await hist.record("a", "1", "write")
    await hist.record("b", "2", "write")
    await hist.clear()
    assert await hist.all() == []


async def test_capacity_must_be_positive() -> None:
    with pytest.raises(ValueError):
        EditHistory(capacity=0)


async def test_module_singleton_is_usable() -> None:
    await EDIT_HISTORY.clear()
    await EDIT_HISTORY.record("singleton.py", "seed", "write")
    entry = await EDIT_HISTORY.pop_latest("singleton.py")
    assert entry is not None and entry.prev_content == "seed"
    await EDIT_HISTORY.clear()
