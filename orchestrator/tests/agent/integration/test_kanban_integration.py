"""
Integration tests for the Kanban agent tool.

Verifies the kanban tool works through the actual ToolRegistry execution
path — registration, parameter schema, execute() wrapping, and end-to-end
action flows with mocked DB.
"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.agent.tools.registry import ToolCategory, get_tool_registry

MODULE = "app.agent.tools.project_ops.kanban"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_board(**overrides):
    defaults = {
        "id": uuid4(),
        "project_id": uuid4(),
        "name": "Project Board",
        "columns": [],
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_column(**overrides):
    defaults = {
        "id": uuid4(),
        "name": "To Do",
        "description": "Things to do",
        "position": 0,
        "color": "blue",
        "icon": "\U0001f4dd",
        "is_backlog": False,
        "is_completed": False,
        "task_limit": None,
        "tasks": [],
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_task(**overrides):
    now = datetime(2026, 4, 5, 12, 0, 0)
    defaults = {
        "id": uuid4(),
        "board_id": uuid4(),
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
        "due_date": None,
        "started_at": None,
        "completed_at": None,
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _build_context(**overrides):
    """Build a standard tool execution context with mocked DB."""
    ctx = {
        "db": AsyncMock(),
        "user_id": uuid4(),
        "project_id": str(uuid4()),
        "edit_mode": "allow",
    }
    ctx.update(overrides)
    return ctx


# ---------------------------------------------------------------------------
# 1. Registry integration
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestKanbanRegistryIntegration:
    """Verify the kanban tool is correctly registered in the global registry."""

    def test_kanban_tool_is_registered(self):
        registry = get_tool_registry()
        tool = registry.get("kanban")
        assert tool is not None, "kanban tool should be present in the global registry"

    def test_kanban_tool_has_correct_category(self):
        registry = get_tool_registry()
        tool = registry.get("kanban")
        assert tool.category == ToolCategory.PROJECT

    def test_kanban_tool_requires_action_parameter(self):
        registry = get_tool_registry()
        tool = registry.get("kanban")
        schema = tool.parameters
        assert schema.get("required") == ["action"]
        assert "action" in schema["properties"]

    def test_kanban_tool_action_enum_is_populated(self):
        registry = get_tool_registry()
        tool = registry.get("kanban")
        action_prop = tool.parameters["properties"]["action"]
        assert "enum" in action_prop
        actions = action_prop["enum"]
        for expected in [
            "get_board",
            "create_task",
            "update_task",
            "move_task",
            "delete_task",
            "add_comment",
            "search_tasks",
            "create_column",
            "update_column",
            "delete_column",
        ]:
            assert expected in actions, f"Missing action '{expected}' in enum"

    def test_kanban_tool_has_examples(self):
        registry = get_tool_registry()
        tool = registry.get("kanban")
        assert tool.examples is not None
        assert len(tool.examples) > 0

    def test_kanban_tool_has_description(self):
        registry = get_tool_registry()
        tool = registry.get("kanban")
        assert "kanban" in tool.description.lower()

    def test_kanban_tool_appears_in_project_category_listing(self):
        registry = get_tool_registry()
        project_tools = registry.list_tools(category=ToolCategory.PROJECT)
        tool_names = [t.name for t in project_tools]
        assert "kanban" in tool_names


# ---------------------------------------------------------------------------
# 2. Execution flow through registry.execute()
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestKanbanRegistryExecution:
    """Test execution through registry.execute() — verifies wrapping."""

    @pytest.mark.asyncio
    async def test_execute_get_board_wraps_result(self):
        """registry.execute wraps the executor result with success/tool keys."""
        registry = get_tool_registry()
        context = _build_context()

        board = _make_board(project_id=context["project_id"])
        col1 = _make_column(position=0, tasks=[])
        col2 = _make_column(name="Done", position=1, is_completed=True, tasks=[])
        board.columns = [col1, col2]

        # _get_or_create_board is called, then the action does a fresh
        # db.execute() with selectinload to reload the board with relations.
        with patch(
            f"{MODULE}._get_or_create_board",
            new_callable=AsyncMock,
            return_value=board,
        ):
            # Mock the second db.execute (the eager-load query) to return the board
            mock_result = MagicMock()
            mock_result.scalar_one.return_value = board
            context["db"].execute = AsyncMock(return_value=mock_result)

            result = await registry.execute("kanban", {"action": "get_board"}, context)

        # Registry wrapping
        assert "success" in result
        assert "tool" in result
        assert result["tool"] == "kanban"
        assert result["success"] is True

        # Inner result — board data is inline in the message
        inner = result["result"]
        assert inner["success"] is True
        assert "Board:" in inner["message"]

    @pytest.mark.asyncio
    async def test_execute_missing_action_returns_error(self):
        """Missing action param should propagate as a failed result."""
        registry = get_tool_registry()
        context = _build_context()

        result = await registry.execute("kanban", {}, context)

        assert result["success"] is False
        assert result["tool"] == "kanban"
        inner = result["result"]
        assert inner["success"] is False
        assert "'action' parameter is required" in inner["message"]

    @pytest.mark.asyncio
    async def test_execute_unknown_action_returns_error(self):
        """Unknown action should produce a structured error through the registry."""
        registry = get_tool_registry()
        context = _build_context()

        result = await registry.execute("kanban", {"action": "fly_to_moon"}, context)

        assert result["success"] is False
        assert result["tool"] == "kanban"
        inner = result["result"]
        assert inner["success"] is False
        assert "Unknown action" in inner["message"]

    @pytest.mark.asyncio
    async def test_execute_missing_context_returns_error(self):
        """No db/user_id/project_id should fail gracefully."""
        registry = get_tool_registry()
        context = {"edit_mode": "allow"}

        result = await registry.execute("kanban", {"action": "get_board"}, context)

        assert result["success"] is False
        assert result["tool"] == "kanban"
        inner = result["result"]
        assert inner["success"] is False
        assert "Missing required context" in inner["message"]

    @pytest.mark.asyncio
    async def test_execute_nonexistent_tool_returns_error(self):
        """Calling a tool name that does not exist."""
        registry = get_tool_registry()
        result = await registry.execute("kanban_does_not_exist", {}, {})

        assert result["success"] is False
        assert "Unknown tool" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_null_db_returns_context_error(self):
        """db=None in context should be caught before dispatching."""
        registry = get_tool_registry()
        context = {
            "db": None,
            "user_id": uuid4(),
            "project_id": str(uuid4()),
            "edit_mode": "allow",
        }

        result = await registry.execute("kanban", {"action": "get_board"}, context)

        assert result["success"] is False
        inner = result["result"]
        assert inner["success"] is False
        assert "Missing required context" in inner["message"]


# ---------------------------------------------------------------------------
# 3. End-to-end action flows (mocked DB)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestKanbanEndToEndFlows:
    """Full action flows through registry.execute() with mocked DB internals."""

    @pytest.mark.asyncio
    async def test_create_task_flow(self):
        """Create a task through the registry and verify result structure."""
        registry = get_tool_registry()
        context = _build_context()

        board = _make_board(project_id=context["project_id"])
        column = _make_column(name="To Do")

        task_id = uuid4()
        now = datetime(2026, 4, 5, 12, 0, 0)

        with patch(
            f"{MODULE}._get_or_create_board",
            new_callable=AsyncMock,
            return_value=board,
        ), patch(
            f"{MODULE}._resolve_column",
            new_callable=AsyncMock,
            return_value=column,
        ), patch(
            f"{MODULE}._max_position",
            new_callable=AsyncMock,
            return_value=2,
        ):
            # db.add, db.commit, db.refresh are already AsyncMock from _build_context.
            # db.refresh should populate the task object — we simulate by intercepting add.
            added_objects = []

            def capture_add(obj):
                added_objects.append(obj)
                # Simulate DB-assigned fields
                obj.id = task_id
                obj.created_at = now
                obj.updated_at = now
                obj.status = obj.status or "open"
                obj.task_type = obj.task_type or "task"
                obj.spent_hours = None
                obj.started_at = None
                obj.completed_at = None

            context["db"].add = capture_add

            result = await registry.execute(
                "kanban",
                {
                    "action": "create_task",
                    "title": "Fix auth bug",
                    "column": "To Do",
                    "priority": "high",
                    "point_value": 5,
                },
                context,
            )

        assert result["success"] is True
        assert result["tool"] == "kanban"
        inner = result["result"]
        assert inner["success"] is True
        assert "Created task" in inner["message"]
        assert "To Do" in inner["message"]
        assert str(task_id) in inner["message"]

    @pytest.mark.asyncio
    async def test_move_task_flow(self):
        """Move a task to a different column through the registry."""
        registry = get_tool_registry()
        context = _build_context()

        board = _make_board(project_id=context["project_id"])
        old_col = _make_column(name="To Do")
        dest_column = _make_column(name="In Progress")
        task = _make_task(title="Implement login", column_id=old_col.id)

        # Mock the db.execute for old column lookup + shift queries
        mock_old_col_result = MagicMock()
        mock_old_col_result.scalar_one_or_none.return_value = old_col
        context["db"].execute = AsyncMock(return_value=mock_old_col_result)

        with patch(
            f"{MODULE}._fetch_task",
            new_callable=AsyncMock,
            return_value=task,
        ), patch(
            f"{MODULE}._get_or_create_board",
            new_callable=AsyncMock,
            return_value=board,
        ), patch(
            f"{MODULE}._resolve_column",
            new_callable=AsyncMock,
            return_value=dest_column,
        ), patch(
            f"{MODULE}._reorder_tasks_in_column",
            new_callable=AsyncMock,
        ), patch(
            f"{MODULE}._max_position",
            new_callable=AsyncMock,
            return_value=0,
        ):
            result = await registry.execute(
                "kanban",
                {
                    "action": "move_task",
                    "task_id": str(task.id),
                    "column": "In Progress",
                },
                context,
            )

        assert result["success"] is True
        inner = result["result"]
        assert inner["success"] is True
        assert "In Progress" in inner["message"]
        # The task's column_id should have been updated
        assert task.column_id == dest_column.id

    @pytest.mark.asyncio
    async def test_delete_task_flow(self):
        """Delete a task through the registry."""
        registry = get_tool_registry()
        context = _build_context()

        task = _make_task(title="Old task")

        with patch(
            f"{MODULE}._fetch_task",
            new_callable=AsyncMock,
            return_value=task,
        ), patch(
            f"{MODULE}._reorder_tasks_in_column",
            new_callable=AsyncMock,
        ):
            result = await registry.execute(
                "kanban",
                {"action": "delete_task", "task_id": str(task.id)},
                context,
            )

        assert result["success"] is True
        inner = result["result"]
        assert inner["success"] is True
        assert "deleted" in inner["message"].lower()
        # db.delete should have been called
        context["db"].delete.assert_awaited_once_with(task)
        context["db"].commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_search_tasks_flow(self):
        """Search tasks through the registry."""
        registry = get_tool_registry()
        context = _build_context()

        board = _make_board(project_id=context["project_id"])
        col_id = uuid4()
        tasks = [
            _make_task(title="Auth bug", priority="high", column_id=col_id),
            _make_task(title="Auth refactor", priority="medium", column_id=col_id),
        ]
        col = _make_column(id=col_id, name="To Do")

        # The search action does two db.execute calls: one for tasks, one for columns.
        task_result = MagicMock()
        task_result.scalars.return_value.all.return_value = tasks
        col_result = MagicMock()
        col_result.scalars.return_value.all.return_value = [col]

        context["db"].execute = AsyncMock(side_effect=[task_result, col_result])

        with patch(
            f"{MODULE}._get_or_create_board",
            new_callable=AsyncMock,
            return_value=board,
        ):
            result = await registry.execute(
                "kanban",
                {"action": "search_tasks", "query": "auth"},
                context,
            )

        assert result["success"] is True
        inner = result["result"]
        assert inner["success"] is True
        assert "Found 2 task(s)" in inner["message"]
        # Task IDs and column names inline in message
        assert "To Do" in inner["message"]

    @pytest.mark.asyncio
    async def test_create_column_flow(self):
        """Create a column through the registry."""
        registry = get_tool_registry()
        context = _build_context()

        board = _make_board(project_id=context["project_id"])

        col_id = uuid4()

        # db.execute for max position query
        max_pos_result = MagicMock()
        max_pos_result.scalar.return_value = 3
        context["db"].execute = AsyncMock(return_value=max_pos_result)

        added_objects = []

        def capture_add(obj):
            added_objects.append(obj)
            obj.id = col_id

        context["db"].add = capture_add

        with patch(
            f"{MODULE}._get_or_create_board",
            new_callable=AsyncMock,
            return_value=board,
        ):
            result = await registry.execute(
                "kanban",
                {"action": "create_column", "title": "Review", "color": "purple"},
                context,
            )

        assert result["success"] is True
        inner = result["result"]
        assert inner["success"] is True
        assert "Created column" in inner["message"]
        assert "Review" in inner["message"]
        assert str(col_id) in inner["message"]

    @pytest.mark.asyncio
    async def test_add_comment_flow(self):
        """Add a comment to a task through the registry."""
        registry = get_tool_registry()
        context = _build_context()

        task = _make_task(title="Some task")
        comment_id = uuid4()

        added_objects = []

        def capture_add(obj):
            added_objects.append(obj)
            obj.id = comment_id
            obj.created_at = datetime(2026, 4, 5, 12, 0, 0)

        context["db"].add = capture_add

        with patch(
            f"{MODULE}._fetch_task",
            new_callable=AsyncMock,
            return_value=task,
        ):
            result = await registry.execute(
                "kanban",
                {
                    "action": "add_comment",
                    "task_id": str(task.id),
                    "content": "Looks good!",
                },
                context,
            )

        assert result["success"] is True
        inner = result["result"]
        assert inner["success"] is True
        assert "Added comment" in inner["message"]
        assert str(task.id) in inner["message"]

    @pytest.mark.asyncio
    async def test_handler_exception_surfaces_through_registry(self):
        """An exception inside a handler should be caught and wrapped."""
        registry = get_tool_registry()
        context = _build_context()

        with patch(
            f"{MODULE}._get_or_create_board",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Connection lost"),
        ):
            result = await registry.execute(
                "kanban", {"action": "get_board"}, context
            )

        # The executor catches the exception internally and returns success=False
        assert result["success"] is False
        assert result["tool"] == "kanban"
        inner = result["result"]
        assert inner["success"] is False
        assert "Connection lost" in inner["message"]

    @pytest.mark.asyncio
    async def test_create_task_column_not_found(self):
        """create_task with a non-existent column returns an error."""
        registry = get_tool_registry()
        context = _build_context()

        board = _make_board(project_id=context["project_id"])

        with patch(
            f"{MODULE}._get_or_create_board",
            new_callable=AsyncMock,
            return_value=board,
        ), patch(
            f"{MODULE}._resolve_column",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await registry.execute(
                "kanban",
                {
                    "action": "create_task",
                    "title": "A task",
                    "column": "Nonexistent",
                },
                context,
            )

        assert result["success"] is False
        inner = result["result"]
        assert inner["success"] is False
        assert "not found" in inner["message"].lower()

    @pytest.mark.asyncio
    async def test_move_task_not_found(self):
        """move_task with a non-existent task ID returns an error."""
        registry = get_tool_registry()
        context = _build_context()

        with patch(
            f"{MODULE}._fetch_task",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await registry.execute(
                "kanban",
                {
                    "action": "move_task",
                    "task_id": str(uuid4()),
                    "column": "Done",
                },
                context,
            )

        assert result["success"] is False
        inner = result["result"]
        assert inner["success"] is False
        assert "not found" in inner["message"].lower()
