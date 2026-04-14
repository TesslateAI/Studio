"""Unit tests for agent handoff bundle + service helpers."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

import app.models  # noqa: F401
from app.services.public.handoff_service import (
    HandoffBundle,
    bundle_from_payload,
    build_enqueue_payload,
    make_continuation_token,
    parse_continuation_token,
    serialize_task,
)


def test_continuation_token_roundtrip():
    chat_id = str(uuid4())
    token = make_continuation_token(chat_id, 7)
    decoded = parse_continuation_token(token)
    assert decoded == {"chat_id": chat_id, "step": 7}


def test_parse_continuation_token_rejects_garbage():
    with pytest.raises(ValueError):
        parse_continuation_token("not-base64!!!")


def test_bundle_from_payload_requires_project_and_chat():
    with pytest.raises(ValueError):
        bundle_from_payload({"chat_id": "x"})
    with pytest.raises(ValueError):
        bundle_from_payload({"project_id": "x"})


def test_bundle_from_payload_defaults_lists():
    b = bundle_from_payload({"project_id": "p", "chat_id": "c", "message": "hi"})
    assert b.trajectory == []
    assert b.goal_ancestry == []
    assert b.skill_bindings == []
    assert b.message == "hi"


def test_build_enqueue_payload_includes_handoff_context():
    bundle = HandoffBundle(
        project_id=str(uuid4()),
        chat_id=str(uuid4()),
        message="continue please",
        task_id="origin-123",
        trajectory=[
            {"response_text": "prior assistant turn"},
            {"thought": "another thought"},
        ],
        goal_ancestry=["root"],
        skill_bindings=["search"],
        continuation_token="ctk",
    )
    task_id, payload = build_enqueue_payload(
        bundle, user_id=uuid4(), project_slug="proj", api_key_scopes=["agents.handoff"]
    )
    assert UUID(task_id)
    assert payload["message"] == "continue please"
    assert payload["project_slug"] == "proj"
    handoff = payload["project_context"]["handoff"]
    assert handoff["origin_task_id"] == "origin-123"
    assert handoff["continuation_token"] == "ctk"
    assert handoff["skill_bindings"] == ["search"]
    # Chat history derived from trajectory summaries
    assert payload["chat_history"] == [
        {"role": "assistant", "content": "prior assistant turn"},
        {"role": "assistant", "content": "another thought"},
    ]


@pytest.mark.asyncio
async def test_serialize_task_rebuilds_trajectory_from_steps():
    chat_id = uuid4()
    project_id = uuid4()

    task = MagicMock()
    task.id = "task-1"
    task.metadata = {
        "chat_id": str(chat_id),
        "project_id": str(project_id),
        "message": "original prompt",
        "skill_bindings": ["a", "b"],
        "goal_ancestry": ["root"],
        "agent_id": "agent-x",
    }

    step1 = MagicMock(step_data={"response_text": "first"}, step_index=0)
    step2 = MagicMock(step_data={"thought": "second"}, step_index=1)

    result = MagicMock()
    result.scalars.return_value.all.return_value = [step1, step2]
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)

    bundle = await serialize_task(db, task)
    assert bundle.task_id == "task-1"
    assert bundle.chat_id == str(chat_id)
    assert bundle.message == "original prompt"
    assert bundle.trajectory == [{"response_text": "first"}, {"thought": "second"}]
    assert bundle.skill_bindings == ["a", "b"]
    assert bundle.goal_ancestry == ["root"]
    assert bundle.continuation_token is not None
    assert parse_continuation_token(bundle.continuation_token)["step"] == 1


@pytest.mark.asyncio
async def test_serialize_task_with_no_chat_returns_empty_trajectory():
    task = MagicMock()
    task.id = "task-2"
    task.metadata = {"project_id": str(uuid4())}

    db = AsyncMock()
    bundle = await serialize_task(db, task)
    assert bundle.trajectory == []
    assert bundle.continuation_token is None
    assert bundle.chat_id == ""
