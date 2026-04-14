"""Approval gate: gated tools raise + flip status; approve returns to queued."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import AgentTask
from app.services.agent_approval import (
    ApprovalRequired,
    approve_ticket,
    check_tool_allowed,
)
from app.services.agent_tickets import create_ticket

from .conftest import make_project_id


@pytest.mark.asyncio
async def test_gated_tool_raises_and_flips_status(async_session) -> None:
    project_id = make_project_id()
    ticket = await create_ticket(
        async_session,
        project_id=project_id,
        title="deploy",
        requires_approval_for=["deploy", "drop_database"],
    )
    await async_session.commit()

    with pytest.raises(ApprovalRequired) as exc:
        await check_tool_allowed(async_session, ticket_id=ticket.id, tool_name="deploy")
    assert exc.value.tool_name == "deploy"

    refreshed_status = (
        await async_session.execute(
            select(AgentTask.status).where(AgentTask.id == ticket.id)
        )
    ).scalar_one()
    assert refreshed_status == "awaiting_approval"


@pytest.mark.asyncio
async def test_ungated_tool_passes_through(async_session) -> None:
    project_id = make_project_id()
    ticket = await create_ticket(
        async_session,
        project_id=project_id,
        title="ok",
        requires_approval_for=["deploy"],
    )
    await async_session.commit()

    # Must not raise, must not flip status.
    await check_tool_allowed(async_session, ticket_id=ticket.id, tool_name="read_file")
    refreshed_status = (
        await async_session.execute(
            select(AgentTask.status).where(AgentTask.id == ticket.id)
        )
    ).scalar_one()
    assert refreshed_status == "queued"


@pytest.mark.asyncio
async def test_approve_returns_to_queued(async_session) -> None:
    project_id = make_project_id()
    ticket = await create_ticket(
        async_session,
        project_id=project_id,
        title="deploy",
        requires_approval_for=["deploy"],
    )
    await async_session.commit()

    with pytest.raises(ApprovalRequired):
        await check_tool_allowed(async_session, ticket_id=ticket.id, tool_name="deploy")

    await approve_ticket(async_session, ticket_id=ticket.id)
    refreshed_status = (
        await async_session.execute(
            select(AgentTask.status).where(AgentTask.id == ticket.id)
        )
    ).scalar_one()
    assert refreshed_status == "queued"
