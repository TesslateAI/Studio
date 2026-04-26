"""Phase 1 — unit tests for ``worker.dispatch_automation_task`` and the
automation-context plumbing through ``AgentTaskPayload``.

Scope (Phase 1 — keep tight):

* ``dispatch_automation_task`` calls ``services.automations.dispatcher.
  dispatch_automation`` with the right kwargs and returns a JSON-friendly
  shape.
* ``dispatch_automation_task`` does not crash the ARQ worker on dispatcher
  exceptions (it logs + rolls back + re-raises so ARQ retries).
* ``AgentTaskPayload.from_dict`` accepts dicts with NEW keys
  (``automation_run_id``, ``contract``, ...) and dicts WITHOUT them
  (legacy callers — chat.py, channels, schedules, external_agent).
* ``AgentTaskPayload`` round-trips the new keys through ``to_dict`` /
  ``from_dict`` (this is the contract the dispatcher relies on when it
  enqueues ``execute_agent_task`` with the new keys in the payload).

Out of scope (Phase 2 / later waves):

* ContractGate enforcement (Phase 2).
* Real ``execute_agent_task`` end-to-end run — the agent runner itself
  imports kubernetes / model adapters / Redis pub-sub, which would balloon
  this unit test into an integration test. We assert that the payload
  carries the keys the worker expects; an integration test in the
  automations suite already covers the dispatcher → worker enqueue handoff.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# AgentTaskPayload field plumbing
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_agent_task_payload_from_dict_accepts_legacy_dict() -> None:
    """Legacy callers (no automation_* keys) keep working.

    chat.py / channels.py / schedules.py / external_agent.py all build
    payload dicts before the Phase 1 fields existed. They MUST keep
    deserializing without crashing.
    """
    from app.services.agent_task import AgentTaskPayload

    legacy = {
        "task_id": "t-1",
        "user_id": str(uuid.uuid4()),
        "chat_id": str(uuid.uuid4()),
        "message": "hello",
    }
    payload = AgentTaskPayload.from_dict(legacy)

    assert payload.task_id == "t-1"
    # New fields default to None / no-op values.
    assert payload.automation_run_id is None
    assert payload.automation_id is None
    assert payload.contract is None
    assert payload.trigger_kind is None
    assert payload.trigger_payload is None
    assert payload.trigger_event_id is None


@pytest.mark.unit
def test_agent_task_payload_from_dict_loads_automation_keys() -> None:
    """New dispatcher-built payload dicts populate automation fields."""
    from app.services.agent_task import AgentTaskPayload

    contract = {
        "allowed_tools": ["read_file"],
        "max_compute_tier": 1,
        "on_breach": "pause_for_approval",
    }
    payload_dict = {
        "task_id": "t-2",
        "user_id": str(uuid.uuid4()),
        "chat_id": str(uuid.uuid4()),
        "message": "do the thing",
        "automation_run_id": "run-uuid",
        "automation_id": "automation-uuid",
        "contract": contract,
        "trigger_kind": "manual",
        "trigger_payload": {"hello": "world"},
        "trigger_event_id": "event-uuid",
    }
    payload = AgentTaskPayload.from_dict(payload_dict)

    assert payload.automation_run_id == "run-uuid"
    assert payload.automation_id == "automation-uuid"
    assert payload.contract == contract
    assert payload.trigger_kind == "manual"
    assert payload.trigger_payload == {"hello": "world"}
    assert payload.trigger_event_id == "event-uuid"


@pytest.mark.unit
def test_agent_task_payload_round_trip_preserves_automation_keys() -> None:
    """``to_dict`` -> ``from_dict`` is lossless for the new fields.

    This is the contract the dispatcher relies on: it builds a dict, ARQ
    serializes it through Redis, and the worker reconstructs it on the
    other side via ``from_dict``.
    """
    from app.services.agent_task import AgentTaskPayload

    original = AgentTaskPayload(
        task_id="t-3",
        user_id=str(uuid.uuid4()),
        chat_id=str(uuid.uuid4()),
        message="round trip",
        automation_run_id="run-3",
        automation_id="auto-3",
        contract={"allowed_tools": ["read_file"], "max_compute_tier": 0, "on_breach": "hard_stop"},
        trigger_kind="cron",
        trigger_payload={"cron_at": "2026-04-26T00:00:00Z"},
        trigger_event_id="evt-3",
    )

    revived = AgentTaskPayload.from_dict(original.to_dict())

    assert revived.automation_run_id == original.automation_run_id
    assert revived.automation_id == original.automation_id
    assert revived.contract == original.contract
    assert revived.trigger_kind == original.trigger_kind
    assert revived.trigger_payload == original.trigger_payload
    assert revived.trigger_event_id == original.trigger_event_id


@pytest.mark.unit
def test_agent_task_payload_from_dict_ignores_unknown_keys() -> None:
    """``from_dict`` filters via ``__dataclass_fields__`` so unknown keys
    (forward-compat from a future dispatcher version) don't blow up the
    legacy worker."""
    from app.services.agent_task import AgentTaskPayload

    payload = AgentTaskPayload.from_dict(
        {
            "task_id": "t-4",
            "user_id": str(uuid.uuid4()),
            "chat_id": str(uuid.uuid4()),
            "message": "x",
            "phase_99_future_field": "ignored",
            "another_unknown": {"deep": "value"},
        }
    )
    assert payload.task_id == "t-4"


# ---------------------------------------------------------------------------
# dispatch_automation_task — ARQ wrapper around dispatcher.dispatch_automation
# ---------------------------------------------------------------------------


class _FakeAsyncSession:
    """Minimal AsyncSession stand-in for the worker wrapper.

    The wrapper only needs ``__aenter__`` / ``__aexit__`` and ``rollback``;
    ``dispatch_automation`` itself is mocked so we never touch SQL.
    """

    def __init__(self) -> None:
        self.rollback_called = False

    async def __aenter__(self) -> "_FakeAsyncSession":
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        return None

    async def rollback(self) -> None:
        self.rollback_called = True


@pytest.mark.unit
def test_dispatch_automation_task_calls_dispatcher_with_uuids() -> None:
    """Wrapper parses string UUIDs and forwards them to the dispatcher."""
    from app import worker

    automation_id = uuid.uuid4()
    event_id = uuid.uuid4()
    run_id = uuid.uuid4()

    fake_session = _FakeAsyncSession()
    fake_session_factory = MagicMock(return_value=fake_session)

    # Build a DispatchResult-shaped object the wrapper can introspect.
    from app.services.automations.dispatcher import DispatchResult, DispatchStatus

    fake_result = DispatchResult(
        status=DispatchStatus.SUCCEEDED,
        run_id=run_id,
        run_status="succeeded",
        reason=None,
    )
    mock_dispatch = AsyncMock(return_value=fake_result)

    async def go():
        with (
            patch.object(worker, "AsyncSessionLocal", fake_session_factory, create=True)
            if hasattr(worker, "AsyncSessionLocal")
            else patch("app.database.AsyncSessionLocal", fake_session_factory),
            patch(
                "app.services.automations.dispatcher.dispatch_automation",
                mock_dispatch,
            ),
        ):
            return await worker.dispatch_automation_task(
                ctx={},
                automation_id_str=str(automation_id),
                event_id_str=str(event_id),
                worker_id="worker-XYZ",
            )

    out = asyncio.run(go())

    # Dispatcher was called once with parsed UUIDs.
    assert mock_dispatch.await_count == 1
    _, kwargs = mock_dispatch.await_args
    assert kwargs["automation_id"] == automation_id
    assert kwargs["event_id"] == event_id
    assert kwargs["worker_id"] == "worker-XYZ"

    # Return shape is JSON-serializable (no UUIDs / Enums leaking through).
    assert out == {
        "run_id": str(run_id),
        "status": "succeeded",
        "run_status": "succeeded",
        "reason": None,
    }
    assert not fake_session.rollback_called


@pytest.mark.unit
def test_dispatch_automation_task_rolls_back_and_reraises_on_failure() -> None:
    """Dispatcher exceptions trigger rollback + re-raise (ARQ retry path)."""
    from app import worker

    fake_session = _FakeAsyncSession()
    fake_session_factory = MagicMock(return_value=fake_session)

    boom = RuntimeError("dispatcher exploded")
    mock_dispatch = AsyncMock(side_effect=boom)

    async def go():
        with (
            patch("app.database.AsyncSessionLocal", fake_session_factory),
            patch(
                "app.services.automations.dispatcher.dispatch_automation",
                mock_dispatch,
            ),
        ):
            await worker.dispatch_automation_task(
                ctx={},
                automation_id_str=str(uuid.uuid4()),
                event_id_str=str(uuid.uuid4()),
                worker_id="worker-FAIL",
            )

    with pytest.raises(RuntimeError, match="dispatcher exploded"):
        asyncio.run(go())

    # ARQ relies on re-raise for retries; we should also have attempted a
    # rollback so the session isn't left in a half-committed state.
    assert fake_session.rollback_called is True


@pytest.mark.unit
def test_dispatch_automation_task_registered_in_worker_settings() -> None:
    """The task must be in WorkerSettings.functions or ARQ won't pick it up."""
    from app.worker import WorkerSettings, dispatch_automation_task

    assert dispatch_automation_task in WorkerSettings.functions
