"""Tests for LocalTaskQueue — the in-process task queue backend."""

from __future__ import annotations

import asyncio
import time

import pytest

from app.services.task_queue.local_queue import LocalTaskQueue


@pytest.mark.asyncio
async def test_enqueue_runs_handler_with_args():
    q = LocalTaskQueue(max_workers=2)
    seen: list[tuple] = []

    async def handler(ctx, a, b, *, k=None):
        seen.append((a, b, k))

    q.register("ping", handler)
    await q.enqueue("ping", 1, 2, k="x")
    for _ in range(50):
        if seen:
            break
        await asyncio.sleep(0.02)
    await q.stop()
    assert seen == [(1, 2, "x")]


@pytest.mark.asyncio
async def test_fifo_order_single_worker():
    q = LocalTaskQueue(max_workers=1)
    order: list[int] = []

    async def handler(ctx, i):
        order.append(i)

    q.register("append", handler)
    for i in range(5):
        await q.enqueue("append", i)
    for _ in range(100):
        if len(order) == 5:
            break
        await asyncio.sleep(0.02)
    await q.stop()
    assert order == [0, 1, 2, 3, 4]


@pytest.mark.asyncio
async def test_delayed_job_fires_after_delay():
    q = LocalTaskQueue(max_workers=2)
    fired_at: list[float] = []

    async def handler(ctx):
        fired_at.append(time.monotonic())

    q.register("later", handler)
    t0 = time.monotonic()
    await q.enqueue("later", _defer_by=0.3)
    for _ in range(100):
        if fired_at:
            break
        await asyncio.sleep(0.02)
    await q.stop()
    assert fired_at, "delayed job never fired"
    assert fired_at[0] - t0 >= 0.25


@pytest.mark.asyncio
async def test_cancel_pending_delayed_job_skipped():
    q = LocalTaskQueue(max_workers=1)
    ran: list[int] = []

    async def handler(ctx):
        ran.append(1)

    q.register("skip_me", handler)
    job_id = await q.enqueue("skip_me", _defer_by=0.5)
    assert q.cancel(job_id) is True
    await asyncio.sleep(0.7)
    await q.stop()
    assert ran == []
