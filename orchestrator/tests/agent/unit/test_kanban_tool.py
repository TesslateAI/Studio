"""
Unit tests for Kanban Agent Tool.

Tests action dispatch, parameter validation, serialization helpers,
and column resolution logic.
"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.agent.tools.project_ops.kanban import (
    _serialize_column,
    _serialize_task,
    kanban_executor,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MODULE = "app.agent.tools.project_ops.kanban"


@pytest.fixture
def test_context():
    """Valid executor context with a mocked async DB session."""
    return {
        "db": AsyncMock(),
        "user_id": uuid4(),
        "project_id": str(uuid4()),
    }


def _make_task(**overrides):
    """Build a fake KanbanTask-like object with sensible defaults."""
    now = datetime(2026, 4, 5, 12, 0, 0)
    defaults = {
        "id": uuid4(),
        "column_id": uuid4(),
        "title": "Sample task",
        "description": "A description",
        "position": 0,
        "priority": "medium",
        "status": "open",
        "task_type": "task",
        "tags": ["backend"],
        "assignee_id": uuid4(),
        "reporter_id": uuid4(),
        "point_value": 3,
        "estimate_hours": 2,
        "spent_hours": 1,
        "due_date": now,
        "started_at": now,
        "completed_at": None,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_column(**overrides):
    """Build a fake KanbanColumn-like object with sensible defaults."""
    defaults = {
        "id": uuid4(),
        "name": "To Do",
        "description": "Things to do",
        "position": 1,
        "color": "blue",
        "icon": "📝",
        "is_backlog": False,
        "is_completed": False,
        "task_limit": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# 1. Executor validation tests (no DB needed)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestKanbanExecutorValidation:
    """Tests for top-level executor validation before dispatching."""

    @pytest.mark.asyncio
    async def test_missing_action_returns_error(self, test_context):
        result = await kanban_executor({}, test_context)
        assert result["success"] is False
        assert "'action' parameter is required" in result["message"]

    @pytest.mark.asyncio
    async def test_unknown_action_returns_error(self, test_context):
        result = await kanban_executor({"action": "nope"}, test_context)
        assert result["success"] is False
        assert "Unknown action 'nope'" in result["message"]

    @pytest.mark.asyncio
    async def test_missing_db_returns_error(self):
        context = {"db": None, "user_id": uuid4(), "project_id": str(uuid4())}
        result = await kanban_executor({"action": "get_board"}, context)
        assert result["success"] is False
        assert "Missing required context" in result["message"]

    @pytest.mark.asyncio
    async def test_missing_user_id_returns_error(self):
        context = {"db": AsyncMock(), "user_id": None, "project_id": str(uuid4())}
        result = await kanban_executor({"action": "get_board"}, context)
        assert result["success"] is False
        assert "Missing required context" in result["message"]

    @pytest.mark.asyncio
    async def test_missing_project_id_returns_error(self):
        context = {"db": AsyncMock(), "user_id": uuid4(), "project_id": None}
        result = await kanban_executor({"action": "get_board"}, context)
        assert result["success"] is False
        assert "Missing required context" in result["message"]

    @pytest.mark.asyncio
    async def test_completely_empty_context_returns_error(self):
        result = await kanban_executor({"action": "get_board"}, {})
        assert result["success"] is False
        assert "Missing required context" in result["message"]


# ---------------------------------------------------------------------------
# 2. Action parameter validation tests (mock DB)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestKanbanActionValidation:
    """Tests that each action rejects invalid / incomplete params."""

    # -- create_task --

    @pytest.mark.asyncio
    async def test_create_task_missing_title(self, test_context):
        result = await kanban_executor(
            {"action": "create_task", "column": "To Do"}, test_context
        )
        assert result["success"] is False
        assert "'title' is required" in result["message"]

    @pytest.mark.asyncio
    async def test_create_task_missing_column(self, test_context):
        result = await kanban_executor(
            {"action": "create_task", "title": "A task"}, test_context
        )
        assert result["success"] is False
        assert "'column' is required" in result["message"]

    # -- update_task --

    @pytest.mark.asyncio
    async def test_update_task_missing_task_id(self, test_context):
        result = await kanban_executor(
            {"action": "update_task", "title": "New title"}, test_context
        )
        assert result["success"] is False
        assert "'task_id' is required" in result["message"]

    @pytest.mark.asyncio
    async def test_update_task_no_updatable_fields(self, test_context):
        """update_task with a valid task_id but no fields to change."""
        task = _make_task()
        with patch(f"{MODULE}._fetch_task", new_callable=AsyncMock, return_value=task):
            result = await kanban_executor(
                {"action": "update_task", "task_id": str(task.id)}, test_context
            )
        assert result["success"] is False
        assert "No fields to update" in result["message"]

    # -- move_task --

    @pytest.mark.asyncio
    async def test_move_task_missing_task_id(self, test_context):
        result = await kanban_executor(
            {"action": "move_task", "column": "Done"}, test_context
        )
        assert result["success"] is False
        assert "'task_id' is required" in result["message"]

    @pytest.mark.asyncio
    async def test_move_task_missing_column(self, test_context):
        result = await kanban_executor(
            {"action": "move_task", "task_id": str(uuid4())}, test_context
        )
        assert result["success"] is False
        assert "'column' is required" in result["message"]

    # -- delete_task --

    @pytest.mark.asyncio
    async def test_delete_task_missing_task_id(self, test_context):
        result = await kanban_executor({"action": "delete_task"}, test_context)
        assert result["success"] is False
        assert "'task_id' is required" in result["message"]

    # -- add_comment --

    @pytest.mark.asyncio
    async def test_add_comment_missing_task_id(self, test_context):
        result = await kanban_executor(
            {"action": "add_comment", "content": "A comment"}, test_context
        )
        assert result["success"] is False
        assert "'task_id' is required" in result["message"]

    @pytest.mark.asyncio
    async def test_add_comment_missing_content(self, test_context):
        result = await kanban_executor(
            {"action": "add_comment", "task_id": str(uuid4())}, test_context
        )
        assert result["success"] is False
        assert "'content' is required" in result["message"]

    # -- create_column --

    @pytest.mark.asyncio
    async def test_create_column_missing_title(self, test_context):
        result = await kanban_executor({"action": "create_column"}, test_context)
        assert result["success"] is False
        assert "'title' is required" in result["message"]

    # -- update_column --

    @pytest.mark.asyncio
    async def test_update_column_missing_column_id(self, test_context):
        result = await kanban_executor(
            {"action": "update_column", "title": "New name"}, test_context
        )
        assert result["success"] is False
        assert "'column_id' is required" in result["message"]

    @pytest.mark.asyncio
    async def test_update_column_invalid_uuid(self, test_context):
        result = await kanban_executor(
            {"action": "update_column", "column_id": "not-a-uuid", "title": "X"},
            test_context,
        )
        assert result["success"] is False
        assert "Invalid column UUID" in result["message"]

    # -- delete_column --

    @pytest.mark.asyncio
    async def test_delete_column_missing_column_id(self, test_context):
        result = await kanban_executor({"action": "delete_column"}, test_context)
        assert result["success"] is False
        assert "'column_id' is required" in result["message"]

    @pytest.mark.asyncio
    async def test_delete_column_invalid_uuid(self, test_context):
        result = await kanban_executor(
            {"action": "delete_column", "column_id": "bad-uuid"}, test_context
        )
        assert result["success"] is False
        assert "Invalid column UUID" in result["message"]


# ---------------------------------------------------------------------------
# 3. Serialization tests (no DB)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestKanbanSerialization:
    """Tests for _serialize_task and _serialize_column helpers."""

    def test_serialize_task_all_fields(self):
        now = datetime(2026, 4, 5, 12, 0, 0)
        task = _make_task(
            due_date=now,
            started_at=now,
            completed_at=now,
            created_at=now,
            updated_at=now,
        )
        result = _serialize_task(task)

        assert result["id"] == str(task.id)
        assert result["column_id"] == str(task.column_id)
        assert result["title"] == "Sample task"
        assert result["description"] == "A description"
        assert result["position"] == 0
        assert result["priority"] == "medium"
        assert result["status"] == "open"
        assert result["task_type"] == "task"
        assert result["tags"] == ["backend"]
        assert result["assignee_id"] == str(task.assignee_id)
        assert result["reporter_id"] == str(task.reporter_id)
        assert result["point_value"] == 3
        assert result["estimate_hours"] == 2
        assert result["spent_hours"] == 1
        assert result["due_date"] == now.isoformat()
        assert result["started_at"] == now.isoformat()
        assert result["completed_at"] == now.isoformat()
        assert result["created_at"] == now.isoformat()
        assert result["updated_at"] == now.isoformat()

    def test_serialize_task_null_optional_fields(self):
        task = _make_task(
            description=None,
            assignee_id=None,
            reporter_id=None,
            point_value=None,
            estimate_hours=None,
            spent_hours=None,
            due_date=None,
            started_at=None,
            completed_at=None,
            created_at=None,
            updated_at=None,
            tags=None,
        )
        result = _serialize_task(task)

        assert result["description"] is None
        assert result["assignee_id"] is None
        assert result["reporter_id"] is None
        assert result["point_value"] is None
        assert result["estimate_hours"] is None
        assert result["spent_hours"] is None
        assert result["due_date"] is None
        assert result["started_at"] is None
        assert result["completed_at"] is None
        assert result["created_at"] is None
        assert result["updated_at"] is None
        assert result["tags"] is None
        # id and column_id should still be strings
        assert isinstance(result["id"], str)
        assert isinstance(result["column_id"], str)

    def test_serialize_column(self):
        col = _make_column()
        result = _serialize_column(col)

        assert result["id"] == str(col.id)
        assert result["name"] == "To Do"
        assert result["description"] == "Things to do"
        assert result["position"] == 1
        assert result["color"] == "blue"
        assert result["icon"] == "📝"
        assert result["is_backlog"] is False
        assert result["is_completed"] is False
        assert result["task_limit"] is None

    def test_serialize_column_backlog_and_completed(self):
        col = _make_column(is_backlog=True, is_completed=True, task_limit=5)
        result = _serialize_column(col)

        assert result["is_backlog"] is True
        assert result["is_completed"] is True
        assert result["task_limit"] == 5

    def test_serialize_task_returns_all_expected_keys(self):
        task = _make_task()
        result = _serialize_task(task)
        expected_keys = {
            "id", "column_id", "title", "description", "position",
            "priority", "status", "task_type", "tags", "assignee_id",
            "reporter_id", "point_value", "estimate_hours", "spent_hours",
            "due_date", "started_at", "completed_at", "created_at", "updated_at",
        }
        assert set(result.keys()) == expected_keys

    def test_serialize_column_returns_all_expected_keys(self):
        col = _make_column()
        result = _serialize_column(col)
        expected_keys = {
            "id", "name", "description", "position", "color",
            "icon", "is_backlog", "is_completed", "task_limit",
        }
        assert set(result.keys()) == expected_keys


# ---------------------------------------------------------------------------
# 4. Column resolution tests (mock DB)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestResolveColumn:
    """Tests for _resolve_column helper."""

    @pytest.mark.asyncio
    async def test_resolve_by_valid_uuid(self):
        from app.agent.tools.project_ops.kanban import _resolve_column

        col_id = uuid4()
        board_id = uuid4()
        fake_col = _make_column(id=col_id)

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = fake_col
        db.execute.return_value = mock_result

        result = await _resolve_column(db, board_id, str(col_id))
        assert result is fake_col
        # Should have called execute once (UUID path)
        assert db.execute.call_count == 1

    @pytest.mark.asyncio
    async def test_resolve_by_name_fallback(self):
        from app.agent.tools.project_ops.kanban import _resolve_column

        board_id = uuid4()
        fake_col = _make_column(name="In Progress")

        db = AsyncMock()
        mock_scalars = MagicMock()
        mock_scalars.first.return_value = fake_col
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        db.execute.return_value = mock_result

        # Pass a non-UUID string so it falls back to name match
        result = await _resolve_column(db, board_id, "in progress")
        assert result is fake_col

    @pytest.mark.asyncio
    async def test_resolve_returns_none_for_nonexistent(self):
        from app.agent.tools.project_ops.kanban import _resolve_column

        board_id = uuid4()

        db = AsyncMock()
        mock_scalars = MagicMock()
        mock_scalars.first.return_value = None
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        db.execute.return_value = mock_result

        result = await _resolve_column(db, board_id, "nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_resolve_uuid_parse_failure_falls_to_name(self):
        """When column_ref looks like a UUID but isn't valid, fall back to name."""
        from app.agent.tools.project_ops.kanban import _resolve_column

        board_id = uuid4()
        fake_col = _make_column(name="Backlog")

        db = AsyncMock()
        mock_scalars = MagicMock()
        mock_scalars.first.return_value = fake_col
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        db.execute.return_value = mock_result

        result = await _resolve_column(db, board_id, "Backlog")
        assert result is fake_col


# ---------------------------------------------------------------------------
# 5. Fetch task tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFetchTask:
    """Tests for _fetch_task helper."""

    @pytest.mark.asyncio
    async def test_fetch_task_invalid_uuid_returns_none(self):
        from app.agent.tools.project_ops.kanban import _fetch_task

        db = AsyncMock()
        result = await _fetch_task(db, "not-a-uuid")
        assert result is None
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_task_valid_uuid(self):
        from app.agent.tools.project_ops.kanban import _fetch_task

        task = _make_task()
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = task
        db.execute.return_value = mock_result

        result = await _fetch_task(db, str(task.id))
        assert result is task

    @pytest.mark.asyncio
    async def test_fetch_task_not_found(self):
        from app.agent.tools.project_ops.kanban import _fetch_task

        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result

        result = await _fetch_task(db, str(uuid4()))
        assert result is None


# ---------------------------------------------------------------------------
# 6. Handler exception handling
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestKanbanExceptionHandling:
    """Tests that exceptions in handlers are caught gracefully."""

    @pytest.mark.asyncio
    async def test_handler_exception_is_caught(self, test_context):
        """If a handler raises, executor returns a structured error."""
        with patch(
            f"{MODULE}._get_or_create_board",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB exploded"),
        ):
            result = await kanban_executor({"action": "get_board"}, test_context)

        assert result["success"] is False
        assert "failed" in result["message"]
        assert "DB exploded" in result["message"]


# ---------------------------------------------------------------------------
# 7. Action dispatch routing
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestKanbanDispatchRouting:
    """Verify that all declared actions are routable."""

    @pytest.mark.asyncio
    async def test_all_actions_are_in_dispatch(self):
        from app.agent.tools.project_ops.kanban import _ACTION_DISPATCH, _ALL_ACTIONS

        for action in _ALL_ACTIONS:
            assert action in _ACTION_DISPATCH, f"Action '{action}' missing from dispatch"

    def test_all_actions_list_matches_dispatch_keys(self):
        from app.agent.tools.project_ops.kanban import _ACTION_DISPATCH, _ALL_ACTIONS

        assert set(_ALL_ACTIONS) == set(_ACTION_DISPATCH.keys())
