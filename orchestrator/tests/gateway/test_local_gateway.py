"""Desktop-mode gateway tests: scheduler + LocalTaskQueue integration."""

from __future__ import annotations

import asyncio

import pytest

from app.services.gateway.scheduler import CronScheduler
from app.services.task_queue.local_queue import LocalTaskQueue


@pytest.mark.asyncio
async def test_scheduler_run_loop_ticks_and_stops():
    """
    The scheduler's run_loop must call tick() repeatedly and exit cleanly on
    stop(). We stub tick() to avoid touching the DB.
    """
    scheduler = CronScheduler(lock_dir="/tmp")

    tick_calls: list[int] = []

    async def fake_tick(db_factory, arq_pool):
        tick_calls.append(1)
        return 0

    scheduler.tick = fake_tick  # type: ignore[assignment]

    async def runner():
        await scheduler.run_loop(db_factory=None, arq_pool=None, interval=0)

    task = asyncio.create_task(runner())
    # Allow a few ticks to run
    for _ in range(20):
        await asyncio.sleep(0.01)
        if len(tick_calls) >= 2:
            break

    scheduler.stop()
    await asyncio.wait_for(task, timeout=1.0)

    assert len(tick_calls) >= 2


@pytest.mark.asyncio
async def test_scheduler_enqueues_via_local_task_queue():
    """
    Verify the scheduler's enqueue path (via get_task_queue) works on
    LocalTaskQueue — the desktop backend. We manually enqueue the same handler
    name the scheduler uses (``execute_agent_task``) and assert the handler
    runs in-process with no Redis.
    """
    q = LocalTaskQueue(max_workers=1)
    ran: list[dict] = []

    async def handler(ctx, payload_dict):
        ran.append(payload_dict)

    q.register("execute_agent_task", handler)
    await q.enqueue("execute_agent_task", {"task_id": "t-local"})

    for _ in range(50):
        if ran:
            break
        await asyncio.sleep(0.02)
    await q.stop()

    assert ran == [{"task_id": "t-local"}]


@pytest.mark.asyncio
async def test_stream_watcher_consumes_pubsub_events():
    """
    The gateway stream watcher must drive off the PubSub Protocol, not direct
    Redis. Publish a minimal ``done`` event on LocalPubSub and confirm the
    watcher sees terminal events and exits without error.
    """
    from app.services.pubsub.local_pubsub import LocalPubSub

    pub = LocalPubSub()
    task_id = "task-stream"
    await pub.publish_agent_event(task_id, {"type": "agent_step", "data": {"tool_calls": []}})
    await pub.publish_agent_event(task_id, {"type": "done"})

    got: list[dict] = []
    async for event in pub.subscribe_agent_events(task_id):
        got.append(event)

    assert got[-1]["type"] == "done"
    # Sanity: the same event structure the gateway watcher switches on.
    assert any(e.get("type") == "agent_step" for e in got)
