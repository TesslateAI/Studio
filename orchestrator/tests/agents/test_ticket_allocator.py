"""Ticket allocator: ref_id generation + concurrent checkout disjointness."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from app.models import AgentTask
from app.services.agent_tickets import (
    checkout_ticket,
    create_ticket,
    finish_ticket,
    next_ref_id,
)

from .conftest import make_project_id


@pytest.mark.asyncio
async def test_next_ref_id_is_monotonic(async_session) -> None:
    project_id = make_project_id()

    a = await create_ticket(async_session, project_id=project_id, title="first")
    b = await create_ticket(async_session, project_id=project_id, title="second")
    c = await create_ticket(async_session, project_id=project_id, title="third")
    await async_session.commit()

    assert (a.ref_id, b.ref_id, c.ref_id) == ("TSK-0001", "TSK-0002", "TSK-0003")

    # Next allocation should continue the sequence.
    next_ref = await next_ref_id(async_session)
    assert next_ref == "TSK-0004"


@pytest.mark.asyncio
async def test_parallel_checkout_is_disjoint(session_factory) -> None:
    project_id = make_project_id()

    # Seed 10 queued tickets.
    async with session_factory() as s:
        for i in range(10):
            await create_ticket(s, project_id=project_id, title=f"t{i}")
        await s.commit()

    async def worker(worker_id: str):
        async with session_factory() as s:
            claimed = await checkout_ticket(s, worker_id=worker_id, project_id=project_id)
            return claimed.id if claimed else None

    results = await asyncio.gather(*(worker(f"w{i}") for i in range(10)))
    claimed_ids = [r for r in results if r is not None]
    assert len(claimed_ids) == 10
    assert len(set(claimed_ids)) == 10  # all distinct

    # Everything should now be running.
    async with session_factory() as s:
        rows = (await s.execute(select(AgentTask).where(AgentTask.project_id == project_id))).scalars().all()
        assert all(r.status == "running" for r in rows)

        # And one more worker finds nothing queued.
        empty = await checkout_ticket(s, worker_id="w-extra", project_id=project_id)
        assert empty is None


@pytest.mark.asyncio
async def test_finish_ticket_sets_terminal_state(async_session) -> None:
    project_id = make_project_id()
    t = await create_ticket(async_session, project_id=project_id, title="done")
    await async_session.commit()

    await finish_ticket(async_session, ticket_id=t.id, status="completed")
    row = (
        await async_session.execute(
            select(AgentTask.status, AgentTask.completed_at).where(AgentTask.id == t.id)
        )
    ).one()
    assert row[0] == "completed"
    assert row[1] is not None
