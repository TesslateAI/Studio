"""
Tests for the structured update_plan tool.

Covers:
    1. Missing/empty action rejected
    2. Invalid status / empty plan / empty step-text rejected
    3. create: required name + task, mirrors markdown + _active pointer
    4. update: replaces steps on the active plan, preserves identity
    5. update without active plan rejected
    6. complete: marks plan done, clears _active pointer, keeps MD on disk
    7. complete without active plan rejected
    8. Event emission via async callable + asyncio.Queue
    9. Concurrent run_ids isolated
    10. Slug sanitisation + fallback when name is empty/garbage
    11. PLAN_STORE.get() before any call returns None
    12. Registration exposes the tool + action param
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.agent.tools.planning_ops.update_plan import (
    ACTIVE_POINTER_PATH,
    DEFAULT_RUN_ID,
    PLAN_STORE,
    PLANS_DIR,
    PlanStep,
    PlanStore,
    _fallback_slug,
    _sanitise_slug,
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
    """Point the LocalOrchestrator at an isolated temp directory."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    PLAN_STORE._states.clear()
    yield tmp_path
    PLAN_STORE._states.clear()


@pytest.fixture
def local_orchestrator(project_root):
    orchestrator = LocalOrchestrator()
    with patch(
        "app.services.orchestration.get_orchestrator",
        return_value=orchestrator,
    ):
        yield orchestrator


def _make_context(run_id: str = "test-run-1", **extra: Any) -> dict[str, Any]:
    ctx: dict[str, Any] = {
        "run_id": run_id,
        "user_id": uuid4(),
        "project_id": uuid4(),
        "project_slug": "test-project",
    }
    ctx.update(extra)
    return ctx


def _basic_steps() -> list[dict[str, Any]]:
    return [
        {"step": "Read the failing test", "status": "completed", "notes": "Isolated"},
        {"step": "Patch regression in parser", "status": "in_progress"},
        {"step": "Run full suite", "status": "pending"},
    ]


async def _create_plan(
    ctx: dict[str, Any],
    *,
    name: str = "add-oauth-login",
    task: str = "Add Google OAuth login flow",
    steps: list[dict[str, Any]] | None = None,
    reasoning: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "action": "create",
        "name": name,
        "task": task,
        "plan": steps if steps is not None else _basic_steps(),
    }
    if reasoning is not None:
        params["reasoning"] = reasoning
    return await update_plan_tool(params, ctx)


# ---------------------------------------------------------------------------
# 1. Missing / invalid action
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_action_rejected(local_orchestrator):
    ctx = _make_context()
    result = await update_plan_tool({"plan": _basic_steps()}, ctx)
    assert result["success"] is False
    assert "action" in result["message"].lower()


@pytest.mark.asyncio
async def test_invalid_action_rejected(local_orchestrator):
    ctx = _make_context()
    result = await update_plan_tool({"action": "archive"}, ctx)
    assert result["success"] is False
    assert "action" in result["message"].lower()


# ---------------------------------------------------------------------------
# 2. Input validation on create
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_requires_name(local_orchestrator):
    ctx = _make_context()
    result = await update_plan_tool(
        {"action": "create", "task": "Do the thing", "plan": _basic_steps()},
        ctx,
    )
    assert result["success"] is False
    assert "name" in result["message"].lower()


@pytest.mark.asyncio
async def test_create_requires_task(local_orchestrator):
    ctx = _make_context()
    result = await update_plan_tool(
        {"action": "create", "name": "slug-here", "plan": _basic_steps()},
        ctx,
    )
    assert result["success"] is False
    assert "task" in result["message"].lower()


@pytest.mark.asyncio
async def test_create_empty_plan_rejected(local_orchestrator):
    ctx = _make_context()
    result = await update_plan_tool(
        {"action": "create", "name": "x", "task": "t", "plan": []},
        ctx,
    )
    assert result["success"] is False
    assert "empty" in result["message"].lower()


@pytest.mark.asyncio
async def test_invalid_status_rejected(local_orchestrator):
    ctx = _make_context()
    result = await _create_plan(
        ctx,
        steps=[
            {"step": "Do thing", "status": "pending"},
            {"step": "Bad step", "status": "halfway"},
        ],
    )
    assert result["success"] is False
    assert "invalid status" in result["message"].lower()
    assert "halfway" in result["message"]
    assert await PLAN_STORE.get("test-run-1") is None


# ---------------------------------------------------------------------------
# 3. create: happy path writes markdown + _active pointer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_writes_markdown_and_active_pointer(project_root, local_orchestrator):
    ctx = _make_context(run_id="happy-run")
    result = await _create_plan(
        ctx,
        name="add-oauth-login",
        task="Add Google OAuth login flow",
        reasoning="Breaking the feature into verifiable steps",
    )

    assert result["success"] is True
    assert result["action"] == "create"
    assert result["name"] == "add-oauth-login"
    assert result["task"] == "Add Google OAuth login flow"
    assert result["status"] == "active"
    assert result["filename"].endswith("-add-oauth-login.md")
    assert result["mirror_path"].startswith(f"{PLANS_DIR}/")
    assert result["mirror_path"].endswith("-add-oauth-login.md")
    assert len(result["plan"]) == 3
    assert result["details"]["step_count"] == 3
    assert result["details"]["status_counts"]["completed"] == 1
    assert result["details"]["status_counts"]["in_progress"] == 1
    assert result["details"]["status_counts"]["pending"] == 1
    assert result["details"]["mirror_written"] is True
    assert result["details"]["active"] is True

    # In-memory state.
    state = await PLAN_STORE.get("happy-run")
    assert state is not None
    assert state.name == "add-oauth-login"
    assert state.status == "active"

    # Markdown file exists and contains the core fields.
    md_file = Path(project_root) / result["mirror_path"]
    assert md_file.exists()
    body = md_file.read_text(encoding="utf-8")
    assert "# Plan:" in body
    assert "add-oauth-login" in body
    assert "Add Google OAuth login flow" in body
    assert "[x] Read the failing test" in body
    assert "[~] Patch regression in parser" in body
    assert "[ ] Run full suite" in body
    assert "Breaking the feature into verifiable steps" in body

    # _active pointer contains just the filename.
    pointer_file = Path(project_root) / ACTIVE_POINTER_PATH
    assert pointer_file.exists()
    assert pointer_file.read_text(encoding="utf-8").strip() == result["filename"]


# ---------------------------------------------------------------------------
# 4. update: replaces steps but preserves identity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_replaces_steps_and_preserves_identity(project_root, local_orchestrator):
    ctx = _make_context(run_id="replace-run")
    created = await _create_plan(ctx, name="refactor-chat-stream", task="Refactor chat stream")
    assert created["success"]
    original_filename = created["filename"]
    original_created_at = created["created_at"]

    second = await update_plan_tool(
        {
            "action": "update",
            "plan": [
                {"step": "New one", "status": "in_progress"},
                {"step": "New two", "status": "pending"},
            ],
            "reasoning": "Simplified",
        },
        ctx,
    )

    assert second["success"] is True
    assert second["action"] == "update"
    assert second["name"] == created["name"]
    assert second["filename"] == original_filename  # identity preserved
    assert second["created_at"] == original_created_at  # identity preserved
    assert second["status"] == "active"
    assert len(second["plan"]) == 2
    assert [s["step"] for s in second["plan"]] == ["New one", "New two"]
    assert second["reasoning"] == "Simplified"

    # Markdown file is the SAME file, now rewritten.
    md_file = Path(project_root) / second["mirror_path"]
    assert md_file.exists()
    body = md_file.read_text(encoding="utf-8")
    assert "New one" in body
    assert "New two" in body
    assert "Read the failing test" not in body  # original steps gone

    # _active still points at this same filename.
    pointer_file = Path(project_root) / ACTIVE_POINTER_PATH
    assert pointer_file.read_text(encoding="utf-8").strip() == original_filename


# ---------------------------------------------------------------------------
# 5. update without active plan
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_without_active_plan_rejected(local_orchestrator):
    ctx = _make_context(run_id="no-plan-run")
    result = await update_plan_tool(
        {"action": "update", "plan": _basic_steps()},
        ctx,
    )
    assert result["success"] is False
    assert "no active plan" in result["message"].lower()


# ---------------------------------------------------------------------------
# 6. complete: marks plan done, clears pointer, keeps file
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_complete_clears_active_pointer_keeps_file(project_root, local_orchestrator):
    ctx = _make_context(run_id="finish-run")
    created = await _create_plan(ctx, name="ship-the-thing", task="Ship the thing")
    md_file = Path(project_root) / created["mirror_path"]
    assert md_file.exists()

    completed = await update_plan_tool(
        {"action": "complete", "reasoning": "done"},
        ctx,
    )
    assert completed["success"] is True
    assert completed["action"] == "complete"
    assert completed["status"] == "completed"
    assert completed["details"]["active"] is False

    # Markdown still on disk (plan history).
    assert md_file.exists()
    body = md_file.read_text(encoding="utf-8")
    assert "completed" in body.lower()

    # _active pointer cleared.
    pointer_file = Path(project_root) / ACTIVE_POINTER_PATH
    assert pointer_file.read_text(encoding="utf-8").strip() == ""


@pytest.mark.asyncio
async def test_complete_without_plan_rejected(local_orchestrator):
    ctx = _make_context(run_id="no-plan-complete")
    result = await update_plan_tool({"action": "complete"}, ctx)
    assert result["success"] is False
    assert "no plan" in result["message"].lower()


# ---------------------------------------------------------------------------
# 7. Event emission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_emission_async_callable(local_orchestrator):
    received: list[dict[str, Any]] = []

    async def sink(event: dict[str, Any]) -> None:
        received.append(event)

    ctx = _make_context(run_id="callable-run", event_sink=sink)
    await _create_plan(ctx, name="test-events", task="Test emission path")

    assert len(received) == 1
    event = received[0]
    assert event["type"] == "plan_update"
    data = event["data"]
    assert data["action"] == "create"
    assert data["run_id"] == "callable-run"
    assert data["name"] == "test-events"
    assert data["status"] == "active"
    assert len(data["plan"]) == 3
    assert "updated_at" in data


@pytest.mark.asyncio
async def test_event_emission_queue(local_orchestrator):
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    ctx = _make_context(run_id="queue-run", event_sink=queue)
    await _create_plan(ctx, name="queue-check", task="Queue emission check")

    assert queue.qsize() == 1
    event = queue.get_nowait()
    assert event["type"] == "plan_update"
    assert event["data"]["run_id"] == "queue-run"
    assert event["data"]["name"] == "queue-check"


# ---------------------------------------------------------------------------
# 8. Concurrent run_ids isolated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_run_ids_isolated(local_orchestrator):
    async def create(run_id: str, name: str, step_text: str) -> None:
        ctx = _make_context(run_id=run_id)
        result = await _create_plan(
            ctx,
            name=name,
            task=step_text,
            steps=[
                {"step": step_text, "status": "in_progress"},
                {"step": f"{step_text} follow-up", "status": "pending"},
            ],
        )
        assert result["success"] is True

    await asyncio.gather(
        create("run-alpha", "alpha-plan", "Alpha task"),
        create("run-beta", "beta-plan", "Beta task"),
        create("run-gamma", "gamma-plan", "Gamma task"),
    )

    alpha = await PLAN_STORE.get("run-alpha")
    beta = await PLAN_STORE.get("run-beta")
    gamma = await PLAN_STORE.get("run-gamma")

    assert alpha is not None and beta is not None and gamma is not None
    assert alpha.name == "alpha-plan"
    assert beta.name == "beta-plan"
    assert gamma.name == "gamma-plan"
    assert alpha.plan[0].step == "Alpha task"
    assert beta.plan[0].step == "Beta task"


# ---------------------------------------------------------------------------
# 9. Slug sanitisation + fallback
# ---------------------------------------------------------------------------


def test_sanitise_slug_cleans_and_caps():
    assert _sanitise_slug("Add OAuth Login!") == "add-oauth-login"
    assert _sanitise_slug("  lots   of   spaces  ") == "lots-of-spaces"
    # Length cap at 40.
    long_raw = "a" * 200
    cleaned = _sanitise_slug(long_raw)
    assert len(cleaned) <= 40
    assert cleaned == "a" * 40


def test_sanitise_slug_empty_garbage_returns_empty():
    assert _sanitise_slug("") == ""
    assert _sanitise_slug("!!!") == ""
    assert _sanitise_slug(None) == ""
    assert _sanitise_slug(123) == ""  # type: ignore[arg-type]


def test_fallback_slug_prefers_task():
    assert _fallback_slug("Add Google OAuth login flow", "run-xyz").startswith("add-google-oauth")


def test_fallback_slug_uses_run_id_tail_when_task_empty():
    assert _fallback_slug("", "run-abcd1234efgh5678").startswith("plan-")


@pytest.mark.asyncio
async def test_create_with_garbage_name_falls_back(project_root, local_orchestrator):
    ctx = _make_context(run_id="fallback-name-run")
    result = await update_plan_tool(
        {
            "action": "create",
            "name": "!!!",  # sanitises to empty → fallback used
            "task": "Refactor chat stream handler",
            "plan": _basic_steps(),
        },
        ctx,
    )
    assert result["success"] is True
    # Fallback slug derived from task text.
    assert "refactor-chat-stream" in result["name"]
    assert result["filename"].endswith(f"-{result['name']}.md")


# ---------------------------------------------------------------------------
# 10. Empty store + default run_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_get_before_any_update_returns_none():
    store = PlanStore()
    assert await store.get("never-seen") is None

    PLAN_STORE._states.clear()
    assert await PLAN_STORE.get("also-never-seen") is None


@pytest.mark.asyncio
async def test_default_run_id_fallback(local_orchestrator):
    ctx = {
        "user_id": uuid4(),
        "project_id": uuid4(),
        "project_slug": "fallback-project",
    }
    result = await update_plan_tool(
        {
            "action": "create",
            "name": "default-run-plan",
            "task": "Default run fallback",
            "plan": [{"step": "fallback step", "status": "pending"}],
        },
        ctx,
    )
    assert result["success"] is True
    assert result["run_id"] == DEFAULT_RUN_ID

    state = await PLAN_STORE.get(DEFAULT_RUN_ID)
    assert state is not None
    assert state.name == "default-run-plan"


# ---------------------------------------------------------------------------
# 11. Registration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_update_plan_tool():
    registry = ToolRegistry()
    register_update_plan_tool(registry)

    tool = registry.get("update_plan")
    assert tool is not None
    assert tool.name == "update_plan"
    props = tool.parameters["properties"]
    assert "action" in props
    assert props["action"]["enum"] == ["create", "update", "complete"]
    assert "name" in props
    assert "task" in props
    assert "plan" in props
    assert props["plan"]["items"]["properties"]["status"]["enum"] == [
        "pending",
        "in_progress",
        "completed",
        "blocked",
    ]


@pytest.mark.asyncio
async def test_plan_step_to_dict_shape():
    step = PlanStep(index=2, step="Some work", status="blocked", notes="waiting on CI")
    assert step.to_dict() == {
        "index": 2,
        "step": "Some work",
        "status": "blocked",
        "notes": "waiting on CI",
    }
