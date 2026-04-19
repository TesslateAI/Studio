"""Tests for LocalPubSub — the in-process PubSub backend."""

from __future__ import annotations

import asyncio

import pytest

from app.services.pubsub.local_pubsub import LocalPubSub


@pytest.mark.asyncio
async def test_publish_and_subscribe_replays_from_start():
    pub = LocalPubSub()
    await pub.publish_agent_event("t1", {"type": "agent_step", "i": 0})
    await pub.publish_agent_event("t1", {"type": "agent_step", "i": 1})
    await pub.publish_agent_event("t1", {"type": "done"})

    got: list[dict] = []
    async for ev in pub.subscribe_agent_events("t1"):
        got.append(ev)
    assert [e.get("i") for e in got[:2]] == [0, 1]
    assert got[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_consumer_group_disjoint_reads_and_ack_advances():
    pub = LocalPubSub()
    for i in range(4):
        await pub.publish_agent_event("t2", {"type": "agent_step", "i": i})

    # Two consumers in the same group
    a = await pub.group_read("t2", "grp", "A", count=2)
    b = await pub.group_read("t2", "grp", "B", count=2)

    # Each consumer gets a disjoint subset; union covers everything read.
    a_ids = {e["i"] for _, e in a}
    b_ids = {e["i"] for _, e in b}
    assert a_ids.isdisjoint(b_ids)
    assert a_ids.union(b_ids) == {0, 1, 2, 3}

    # Ack last seen, then a re-read sees nothing new (group HW advanced).
    if a:
        await pub.group_ack("t2", "grp", "A", a[-1][0])
    if b:
        await pub.group_ack("t2", "grp", "B", b[-1][0])
    assert await pub.group_read("t2", "grp", "A") == []


@pytest.mark.asyncio
async def test_group_resume_replays_after_last_id():
    pub = LocalPubSub()
    for i in range(3):
        await pub.publish_agent_event("t3", {"type": "agent_step", "i": i})

    batch = await pub.group_read("t3", "grp", "A", count=2)
    assert len(batch) == 2
    last_id = batch[-1][0]
    await pub.group_ack("t3", "grp", "A", last_id)

    # Publish one more, then reconnect by resuming from last_id.
    await pub.publish_agent_event("t3", {"type": "agent_step", "i": 3})
    resumed = await pub.group_resume_from("t3", "grp", "A")
    ids = [e["i"] for _, e in resumed]
    # Resume gives us entries strictly after last ack: {2, 3}
    assert ids == [2, 3]


@pytest.mark.asyncio
async def test_subscribe_from_resumes_after_last_id():
    pub = LocalPubSub()
    await pub.publish_agent_event("t4", {"type": "agent_step", "i": 0})
    await pub.publish_agent_event("t4", {"type": "agent_step", "i": 1})
    await pub.publish_agent_event("t4", {"type": "done"})

    # Consume first via subscribe to capture id format
    first_two: list[tuple[str, dict]] = []
    async for ev in pub.subscribe_agent_events("t4"):
        first_two.append(("?", ev))
        if len(first_two) == 1:
            break

    # Resume from entry 0 — should see 1 and done
    got = []
    async for ev in pub.subscribe_agent_events_from("t4", "00000000000000000000"):
        got.append(ev)
    assert got[0].get("i") == 1
    assert got[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_cancellation_and_lock_ttl_behavior():
    pub = LocalPubSub()
    assert await pub.is_cancelled("task-x") is False
    await pub.request_cancellation("task-x")
    assert await pub.is_cancelled("task-x") is True

    assert await pub.acquire_chat_lock("c1", "task-a") is True
    assert await pub.acquire_chat_lock("c1", "task-b") is False
    assert await pub.get_chat_lock("c1") == "task-a"
    assert await pub.extend_chat_lock("c1", "task-b") is False
    assert await pub.extend_chat_lock("c1", "task-a") is True
    assert await pub.release_chat_lock("c1", "task-b") is False
    assert await pub.release_chat_lock("c1", "task-a") is True
    assert await pub.get_chat_lock("c1") is None


@pytest.mark.asyncio
async def test_live_subscribe_wakes_on_publish():
    pub = LocalPubSub()
    events: list[dict] = []

    async def consumer():
        async for ev in pub.subscribe_agent_events("t5"):
            events.append(ev)

    task = asyncio.create_task(consumer())
    await asyncio.sleep(0.05)
    await pub.publish_agent_event("t5", {"type": "agent_step", "i": 0})
    await pub.publish_agent_event("t5", {"type": "done"})
    await asyncio.wait_for(task, timeout=2.0)
    assert events[0]["i"] == 0
    assert events[-1]["type"] == "done"
