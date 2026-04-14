"""Unit tests for public agents router (list / cancel / steps)."""
from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import MagicMock

import app.models  # noqa: F401
from app.routers.public.agents import _task_to_dict


def _task(**overrides):
    t = MagicMock()
    t.id = overrides.get("id", "task-1")
    t.user_id = overrides.get("user_id", uuid.uuid4())
    t.status = overrides.get("status")
    t.type = overrides.get("type", "agent_execution")
    t.created_at = overrides.get("created_at", datetime(2026, 4, 13, 10, 0, 0))
    t.started_at = overrides.get("started_at")
    t.completed_at = overrides.get("completed_at")
    t.error = overrides.get("error")
    t.metadata = overrides.get(
        "metadata",
        {"project_id": str(uuid.uuid4()), "chat_id": str(uuid.uuid4()), "origin": "api", "message": "hi"},
    )
    return t


def test_task_to_dict_includes_metadata_fields():
    status = MagicMock()
    status.value = "running"
    meta = {"project_id": "p1", "chat_id": "c1", "origin": "api", "message": "build me a thing"}
    task = _task(status=status, metadata=meta)

    d = _task_to_dict(task)
    assert d["task_id"] == "task-1"
    assert d["status"] == "running"
    assert d["project_id"] == "p1"
    assert d["chat_id"] == "c1"
    assert d["origin"] == "api"
    assert d["message_preview"] == "build me a thing"


def test_task_to_dict_handles_missing_metadata():
    status = MagicMock()
    status.value = "queued"
    task = _task(status=status, metadata={})
    d = _task_to_dict(task)
    assert d["project_id"] is None
    assert d["chat_id"] is None
    assert d["origin"] is None
