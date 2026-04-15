"""Unit tests for ``PendingUserInputManager`` + its ``ApprovalManager`` shim.

The manager is exercised in its in-memory mode (no Redis configured in the
test env), so the pub/sub subscriber is dormant and the futures complete
synchronously when ``submit_input`` / ``cancel_input`` fire.
"""
from __future__ import annotations

import asyncio

import pytest

from app.agent.tools.approval_manager import (
    ApprovalManager,
    PendingUserInputManager,
)


@pytest.fixture
def manager() -> PendingUserInputManager:
    # A fresh manager per test — avoids subscriber singleton leakage.
    return PendingUserInputManager()


# ---------------------------------------------------------------------------
# Node-config (form submit) flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_resolves_await_input_with_submitted_values(
    manager: PendingUserInputManager,
) -> None:
    await manager.create_input_request(
        input_id="inp-1",
        project_id="proj-1",
        chat_id="chat-1",
        container_id="cnt-1",
        schema_json={"fields": []},
        mode="create",
        ttl=5,
    )

    async def _submit_after_delay() -> None:
        await asyncio.sleep(0.05)
        manager.submit_input("inp-1", {"FOO": "bar", "BAZ": "qux"})

    result_task = asyncio.create_task(manager.await_input("inp-1", timeout=5))
    asyncio.create_task(_submit_after_delay())
    result = await result_task

    assert result == {"FOO": "bar", "BAZ": "qux"}


@pytest.mark.asyncio
async def test_cancel_resolves_await_input_with_sentinel(
    manager: PendingUserInputManager,
) -> None:
    await manager.create_input_request(
        input_id="inp-cancel",
        project_id="p",
        chat_id="c",
        container_id="ct",
        schema_json={},
        mode="create",
        ttl=5,
    )
    asyncio.get_event_loop().call_later(
        0.05, lambda: manager.cancel_input("inp-cancel")
    )
    result = await manager.await_input("inp-cancel", timeout=5)
    assert result == "__cancelled__"


@pytest.mark.asyncio
async def test_timeout_returns_none(manager: PendingUserInputManager) -> None:
    await manager.create_input_request(
        input_id="inp-timeout",
        project_id="p",
        chat_id="c",
        container_id="ct",
        schema_json={},
        mode="create",
        ttl=1,
    )
    result = await manager.await_input("inp-timeout", timeout=0.1)
    assert result is None


def test_submit_before_create_is_cached(
    manager: PendingUserInputManager,
) -> None:
    # Response arrives before request is registered — the manager caches it
    # so a subsequent create_input_request can pick it up instead of blocking.
    manager.submit_input("inp-early", {"A": "1"})
    assert manager._cached_responses["inp-early"] == {"A": "1"}


# ---------------------------------------------------------------------------
# Approval (legacy) flow — ApprovalManager shim
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approval_manager_shim_is_same_singleton_class() -> None:
    # ApprovalManager is a subclass alias of PendingUserInputManager, and the
    # global accessor returns the unified instance.
    from app.agent.tools.approval_manager import (
        get_approval_manager,
        get_pending_input_manager,
    )

    assert issubclass(ApprovalManager, PendingUserInputManager)
    assert get_approval_manager() is get_pending_input_manager()


@pytest.mark.asyncio
async def test_request_approval_and_respond(manager: PendingUserInputManager) -> None:
    approval_id, request = await manager.request_approval(
        "write_file", {"file": "/tmp/x"}, session_id="sess-1"
    )
    assert request.tool_name == "write_file"
    assert request.approval_id == approval_id

    asyncio.get_event_loop().call_later(
        0.05, lambda: manager.respond_to_approval(approval_id, "allow_once")
    )
    await asyncio.wait_for(request.event.wait(), timeout=1)
    assert request.response == "allow_once"


@pytest.mark.asyncio
async def test_allow_all_approval_caches_session_approval(
    manager: PendingUserInputManager,
) -> None:
    approval_id, request = await manager.request_approval(
        "bash_exec", {"command": "ls"}, session_id="sess-2"
    )
    manager.respond_to_approval(approval_id, "allow_all")
    await asyncio.wait_for(request.event.wait(), timeout=1)
    assert manager.is_tool_approved("sess-2", "bash_exec") is True


def test_approve_tool_for_session_marks_approved(manager: PendingUserInputManager) -> None:
    assert manager.is_tool_approved("s1", "t1") is False
    manager.approve_tool_for_session("s1", "t1")
    assert manager.is_tool_approved("s1", "t1") is True
    manager.clear_session_approvals("s1")
    assert manager.is_tool_approved("s1", "t1") is False
