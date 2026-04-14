"""
Tests for the structured update_plan tool.

Covers:
    1. Empty plan rejected with structured error
    2. Invalid status value rejected
    3. Happy path: 3-step plan, JSON mirror written and parseable
    4. Second call replaces the plan entirely (no merging)
    5. Event emission via an async callable event_sink
    6. Event emission via an asyncio.Queue event_sink
    7. Concurrent updates under different run_ids don't interfere
    8. PLAN_STORE.get(run_id) before any update_plan call returns None
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.agent.tools.planning_ops.update_plan import (
    DEFAULT_RUN_ID,
    PLAN_MIRROR_PATH,
    PLAN_STORE,
    PlanStep,
    PlanStore,
    register_update_plan_tool,
    update_plan_tool,
)
from app.agent.tools.registry import ToolRegistry
from app.services.orchestration.local import LocalOrchestrator

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def project_root(tmp_path, monkeypatch):
    """
    Point the LocalOrchestrator at an isolated temp directory and return it.

    Also clears the module-level PLAN_STORE so each test starts clean.
    """
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))

    # Reset the singleton plan store's internal dict so tests don't leak state.
    PLAN_STORE._states.clear()

    yield tmp_path

    PLAN_STORE._states.clear()


@pytest.fixture
def local_orchestrator(project_root):
    """
    Patch ``get_orchestrator`` (imported lazily inside the tool) to return
    a fresh LocalOrchestrator bound to the temp project root.
    """
    orchestrator = LocalOrchestrator()
    with patch(
        "app.services.orchestration.get_orchestrator",
        return_value=orchestrator,
    ):
        yield orchestrator


def _make_context(run_id: str = "test-run-1", **extra: Any) -> dict[str, Any]:
    """Build a minimal tool execution context."""
    ctx: dict[str, Any] = {
        "run_id": run_id,
        "user_id": uuid4(),
        "project_id": uuid4(),
        "project_slug": "test-project",
    }
    ctx.update(extra)
    return ctx


# ---------------------------------------------------------------------------
# 1. Empty plan rejected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_plan_rejected(local_orchestrator):
    ctx = _make_context()
    result = await update_plan_tool({"plan": []}, ctx)

    assert result["success"] is False
    assert "Empty" in result["message"] or "empty" in result["message"]
    assert "suggestion" in result

    # Nothing should have been stored.
    assert await PLAN_STORE.get("test-run-1") is None


@pytest.mark.asyncio
async def test_missing_plan_rejected(local_orchestrator):
    ctx = _make_context()
    result = await update_plan_tool({}, ctx)

    assert result["success"] is False
    assert "plan" in result["message"].lower()


# ---------------------------------------------------------------------------
# 2. Invalid status rejected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_status_rejected(local_orchestrator):
    ctx = _make_context()
    result = await update_plan_tool(
        {
            "plan": [
                {"step": "Do thing", "status": "pending"},
                {"step": "Bad step", "status": "halfway"},
            ]
        },
        ctx,
    )

    assert result["success"] is False
    assert "invalid status" in result["message"].lower()
    assert "halfway" in result["message"]

    assert await PLAN_STORE.get("test-run-1") is None


@pytest.mark.asyncio
async def test_empty_step_text_rejected(local_orchestrator):
    ctx = _make_context()
    result = await update_plan_tool(
        {"plan": [{"step": "   ", "status": "pending"}]},
        ctx,
    )

    assert result["success"] is False
    assert "step" in result["message"].lower()


# ---------------------------------------------------------------------------
# 3. Happy path with mirror file
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_writes_mirror(project_root, local_orchestrator):
    ctx = _make_context(run_id="happy-run")
    plan = [
        {"step": "Read the failing test", "status": "completed", "notes": "Isolated"},
        {"step": "Patch regression in parser", "status": "in_progress"},
        {"step": "Run full suite", "status": "pending"},
    ]

    result = await update_plan_tool(
        {"plan": plan, "reasoning": "Breaking the fix into verifiable steps"},
        ctx,
    )

    assert result["success"] is True
    assert result["run_id"] == "happy-run"
    assert len(result["plan"]) == 3
    assert result["plan"][0]["index"] == 0
    assert result["plan"][0]["status"] == "completed"
    assert result["plan"][0]["notes"] == "Isolated"
    assert result["plan"][1]["status"] == "in_progress"
    assert result["reasoning"] == "Breaking the fix into verifiable steps"
    assert result["mirror_path"] == PLAN_MIRROR_PATH
    assert result["details"]["step_count"] == 3
    assert result["details"]["status_counts"]["completed"] == 1
    assert result["details"]["status_counts"]["in_progress"] == 1
    assert result["details"]["status_counts"]["pending"] == 1
    assert result["details"]["status_counts"]["blocked"] == 0
    assert result["details"]["mirror_written"] is True

    # Plan store should contain the state.
    state = await PLAN_STORE.get("happy-run")
    assert state is not None
    assert len(state.plan) == 3
    assert state.plan[0].step == "Read the failing test"
    assert state.plan[1].status == "in_progress"
    assert state.reasoning == "Breaking the fix into verifiable steps"

    # Mirror file should exist and parse as JSON with the expected shape.
    mirror_file = Path(project_root) / PLAN_MIRROR_PATH
    assert mirror_file.exists()

    mirror_data = json.loads(mirror_file.read_text(encoding="utf-8"))
    assert mirror_data["run_id"] == "happy-run"
    assert mirror_data["reasoning"] == "Breaking the fix into verifiable steps"
    assert len(mirror_data["plan"]) == 3
    assert mirror_data["plan"][0]["step"] == "Read the failing test"
    assert mirror_data["plan"][0]["index"] == 0
    assert "updated_at" in mirror_data


# ---------------------------------------------------------------------------
# 4. Second call replaces the plan entirely
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_second_call_replaces_plan(project_root, local_orchestrator):
    ctx = _make_context(run_id="replace-run")

    first = await update_plan_tool(
        {
            "plan": [
                {"step": "Alpha", "status": "in_progress"},
                {"step": "Beta", "status": "pending"},
                {"step": "Gamma", "status": "pending"},
                {"step": "Delta", "status": "pending"},
            ]
        },
        ctx,
    )
    assert first["success"] is True
    assert len(first["plan"]) == 4

    second = await update_plan_tool(
        {
            "plan": [
                {"step": "New one", "status": "in_progress"},
                {"step": "New two", "status": "pending"},
            ],
            "reasoning": "Simplified",
        },
        ctx,
    )
    assert second["success"] is True
    assert len(second["plan"]) == 2
    assert second["plan"][0]["step"] == "New one"
    assert second["plan"][1]["step"] == "New two"

    # No trace of the original four-step plan should remain.
    state = await PLAN_STORE.get("replace-run")
    assert state is not None
    assert len(state.plan) == 2
    assert [step.step for step in state.plan] == ["New one", "New two"]
    assert state.reasoning == "Simplified"

    mirror_file = Path(project_root) / PLAN_MIRROR_PATH
    mirror_data = json.loads(mirror_file.read_text(encoding="utf-8"))
    assert len(mirror_data["plan"]) == 2
    assert mirror_data["plan"][0]["step"] == "New one"
    assert mirror_data["reasoning"] == "Simplified"


# ---------------------------------------------------------------------------
# 5. Event emission via async callable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_emission_async_callable(local_orchestrator):
    received: list[dict[str, Any]] = []

    async def sink(event: dict[str, Any]) -> None:
        received.append(event)

    ctx = _make_context(run_id="callable-run", event_sink=sink)
    await update_plan_tool(
        {
            "plan": [
                {"step": "Write tests", "status": "in_progress"},
                {"step": "Run pytest", "status": "pending"},
            ],
            "reasoning": "Test emission path",
        },
        ctx,
    )

    assert len(received) == 1
    event = received[0]
    assert event["type"] == "plan_update"
    data = event["data"]
    assert data["run_id"] == "callable-run"
    assert data["reasoning"] == "Test emission path"
    assert len(data["plan"]) == 2
    assert data["plan"][0]["step"] == "Write tests"
    assert data["plan"][0]["status"] == "in_progress"
    assert "updated_at" in data


# ---------------------------------------------------------------------------
# 6. Event emission via asyncio.Queue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_emission_queue(local_orchestrator):
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    ctx = _make_context(run_id="queue-run", event_sink=queue)
    await update_plan_tool(
        {"plan": [{"step": "Queue emission check", "status": "pending"}]},
        ctx,
    )

    assert queue.qsize() == 1
    event = queue.get_nowait()
    assert event["type"] == "plan_update"
    assert event["data"]["run_id"] == "queue-run"
    assert event["data"]["plan"][0]["step"] == "Queue emission check"


# ---------------------------------------------------------------------------
# 7. Concurrent updates across run_ids
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_run_ids_isolated(local_orchestrator):
    async def update(run_id: str, step_text: str) -> None:
        ctx = _make_context(run_id=run_id)
        result = await update_plan_tool(
            {
                "plan": [
                    {"step": step_text, "status": "in_progress"},
                    {"step": f"{step_text} follow-up", "status": "pending"},
                ]
            },
            ctx,
        )
        assert result["success"] is True

    await asyncio.gather(
        update("run-alpha", "Alpha task"),
        update("run-beta", "Beta task"),
        update("run-gamma", "Gamma task"),
    )

    alpha = await PLAN_STORE.get("run-alpha")
    beta = await PLAN_STORE.get("run-beta")
    gamma = await PLAN_STORE.get("run-gamma")

    assert alpha is not None and beta is not None and gamma is not None
    assert alpha.plan[0].step == "Alpha task"
    assert beta.plan[0].step == "Beta task"
    assert gamma.plan[0].step == "Gamma task"
    assert alpha.plan[0].step != beta.plan[0].step
    assert beta.plan[0].step != gamma.plan[0].step


# ---------------------------------------------------------------------------
# 8. Empty store read before any update
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_get_before_any_update_returns_none():
    # Use a fresh PlanStore instance so we don't depend on fixture order.
    store = PlanStore()
    assert await store.get("never-seen") is None

    # The module-level singleton exposes the same guarantee after we clear it.
    PLAN_STORE._states.clear()
    assert await PLAN_STORE.get("also-never-seen") is None


# ---------------------------------------------------------------------------
# Bonus: registration works and default run_id fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_update_plan_tool():
    registry = ToolRegistry()
    register_update_plan_tool(registry)

    tool = registry.get("update_plan")
    assert tool is not None
    assert tool.name == "update_plan"
    assert "plan" in tool.parameters["properties"]
    assert tool.parameters["properties"]["plan"]["items"]["properties"]["status"]["enum"] == [
        "pending",
        "in_progress",
        "completed",
        "blocked",
    ]


@pytest.mark.asyncio
async def test_default_run_id_fallback(local_orchestrator):
    # Neither run_id nor task_id present → DEFAULT_RUN_ID.
    ctx = {
        "user_id": uuid4(),
        "project_id": uuid4(),
        "project_slug": "fallback-project",
    }
    result = await update_plan_tool(
        {"plan": [{"step": "fallback step", "status": "pending"}]},
        ctx,
    )
    assert result["success"] is True
    assert result["run_id"] == DEFAULT_RUN_ID

    state = await PLAN_STORE.get(DEFAULT_RUN_ID)
    assert state is not None
    assert state.plan[0].step == "fallback step"


@pytest.mark.asyncio
async def test_plan_step_to_dict_shape():
    step = PlanStep(index=2, step="Some work", status="blocked", notes="waiting on CI")
    assert step.to_dict() == {
        "index": 2,
        "step": "Some work",
        "status": "blocked",
        "notes": "waiting on CI",
    }
