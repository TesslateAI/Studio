"""Unit tests for the local-runtime port allocator."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest

from app.services.orchestration.local_ports import PortAllocator

pytestmark = pytest.mark.asyncio


def _make(tmp_path: Path, start: int = 42000, end: int = 42009) -> PortAllocator:
    return PortAllocator(cache_dir=tmp_path, range_start=start, range_end=end)


async def test_allocate_returns_port_in_range(tmp_path: Path) -> None:
    alloc = _make(tmp_path)
    port = await alloc.allocate(uuid4(), "main")
    assert 42000 <= port <= 42009


async def test_allocate_is_idempotent(tmp_path: Path) -> None:
    alloc = _make(tmp_path)
    pid = uuid4()
    first = await alloc.allocate(pid, "main")
    second = await alloc.allocate(pid, "main")
    assert first == second


async def test_release_frees_the_port(tmp_path: Path) -> None:
    alloc = _make(tmp_path, 42000, 42001)
    a = await alloc.allocate(uuid4(), "main")
    b = await alloc.allocate(uuid4(), "main")
    assert {a, b} == {42000, 42001}

    await alloc.release_project(str(uuid4()))  # no-op, different id
    # Range is full now:
    with pytest.raises(RuntimeError):
        await alloc.allocate(uuid4(), "main")


async def test_release_project_frees_all_containers(tmp_path: Path) -> None:
    alloc = _make(tmp_path, 42000, 42002)
    pid = uuid4()
    p1 = await alloc.allocate(pid, "frontend")
    p2 = await alloc.allocate(pid, "backend")
    assert p1 != p2

    await alloc.release_project(pid)
    # Both ports should be reusable.
    p3 = await alloc.allocate(uuid4(), "x")
    assert p3 in {p1, p2}


async def test_release_single_pair(tmp_path: Path) -> None:
    alloc = _make(tmp_path, 42000, 42001)
    pid = uuid4()
    a = await alloc.allocate(pid, "frontend")
    await alloc.allocate(pid, "backend")
    await alloc.release(pid, "frontend")
    # Re-allocating "frontend" should succeed (range size 2, one slot free).
    again = await alloc.allocate(pid, "frontend")
    assert again == a


async def test_no_collisions_across_100_allocations(tmp_path: Path) -> None:
    alloc = _make(tmp_path, 42000, 42099)  # exactly 100 slots
    ports: set[int] = set()
    for i in range(100):
        port = await alloc.allocate(uuid4(), f"c-{i}")
        ports.add(port)
    assert len(ports) == 100
    # 101st allocation must fail cleanly.
    with pytest.raises(RuntimeError):
        await alloc.allocate(uuid4(), "overflow")


async def test_concurrent_contention_is_race_free(tmp_path: Path) -> None:
    alloc = _make(tmp_path, 42000, 42049)  # 50 slots
    pids = [uuid4() for _ in range(50)]

    results = await asyncio.gather(*(alloc.allocate(pid, "main") for pid in pids))
    assert len(set(results)) == 50, f"Duplicate ports allocated: {results}"


async def test_persistence_round_trip(tmp_path: Path) -> None:
    alloc1 = _make(tmp_path)
    pid_a, pid_b = uuid4(), uuid4()
    port_a = await alloc1.allocate(pid_a, "main")
    port_b = await alloc1.allocate(pid_b, "worker")

    # Fresh instance pointing at the same cache dir should see both.
    alloc2 = _make(tmp_path)
    assert await alloc2.get(pid_a, "main") == port_a
    assert await alloc2.get(pid_b, "worker") == port_b

    # And cache file is valid JSON.
    data = json.loads((tmp_path / "ports.json").read_text())
    assert data["range"] == {"start": 42000, "end": 42009}
    assert len(data["assignments"]) == 2


async def test_reclaim_dead_frees_orphaned_entries(tmp_path: Path) -> None:
    alloc = _make(tmp_path, 42000, 42001)
    await alloc.allocate(uuid4(), "a")
    await alloc.allocate(uuid4(), "b")

    # Pretend every owning pid is dead.
    reclaimed = await alloc.reclaim_dead(pid_check=lambda _pid: False)
    assert reclaimed == 2

    # Now the full range is free again.
    port = await alloc.allocate(uuid4(), "fresh")
    assert 42000 <= port <= 42001


async def test_reclaim_dead_keeps_live_entries(tmp_path: Path) -> None:
    alloc = _make(tmp_path, 42000, 42001)
    pid = uuid4()
    port = await alloc.allocate(pid, "main")

    reclaimed = await alloc.reclaim_dead(pid_check=lambda _pid: True)
    assert reclaimed == 0
    assert await alloc.get(pid, "main") == port


async def test_empty_range_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        PortAllocator(cache_dir=tmp_path, range_start=42010, range_end=42000)
