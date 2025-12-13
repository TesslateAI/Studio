"""
Unit tests for Todo Planning Tools.

Tests todo read/write operations and session management.
"""

import pytest
from uuid import uuid4
from app.agent.tools.planning_ops.todos import (
    todo_read_tool,
    todo_write_tool,
    _get_session_key,
    _todo_storage
)


@pytest.mark.unit
class TestTodoTools:
    """Test suite for todo planning tools."""

    @pytest.fixture(autouse=True)
    def clear_todo_storage(self):
        """Clear todo storage before each test."""
        _todo_storage.clear()
        yield
        _todo_storage.clear()

    @pytest.fixture
    def test_context(self):
        """Create a test context."""
        return {
            "user_id": uuid4(),
            "project_id": str(uuid4())
        }

    def test_get_session_key(self, test_context):
        """Test session key generation."""
        key = _get_session_key(test_context)

        assert isinstance(key, str)
        assert str(test_context["user_id"]) in key
        assert test_context["project_id"] in key

    def test_get_session_key_consistent(self, test_context):
        """Test that session key is consistent for same context."""
        key1 = _get_session_key(test_context)
        key2 = _get_session_key(test_context)

        assert key1 == key2

    def test_get_session_key_different_for_different_users(self):
        """Test that different users get different session keys."""
        context1 = {"user_id": uuid4(), "project_id": "project1"}
        context2 = {"user_id": uuid4(), "project_id": "project1"}

        key1 = _get_session_key(context1)
        key2 = _get_session_key(context2)

        assert key1 != key2

    @pytest.mark.asyncio
    async def test_todo_read_empty(self, test_context):
        """Test reading from empty todo list."""
        result = await todo_read_tool({}, test_context)

        assert result["message"] == "No todos in current session"
        assert result["todos"] == []
        assert result["details"]["total"] == 0

    @pytest.mark.asyncio
    async def test_todo_write_single(self, test_context):
        """Test writing a single todo."""
        params = {
            "todos": [
                {
                    "content": "Read package.json",
                    "status": "pending"
                }
            ]
        }

        result = await todo_write_tool(params, test_context)

        assert "message" in result
        assert result["details"]["total"] == 1
        assert result["details"]["pending"] == 1
        assert result["todos"][0]["content"] == "Read package.json"

    @pytest.mark.asyncio
    async def test_todo_write_multiple(self, test_context):
        """Test writing multiple todos."""
        params = {
            "todos": [
                {"content": "Task 1", "status": "completed"},
                {"content": "Task 2", "status": "in_progress"},
                {"content": "Task 3", "status": "pending"}
            ]
        }

        result = await todo_write_tool(params, test_context)

        assert result["details"]["total"] == 3
        assert result["details"]["completed"] == 1
        assert result["details"]["in_progress"] == 1
        assert result["details"]["pending"] == 1

    @pytest.mark.asyncio
    async def test_todo_write_replaces_existing(self, test_context):
        """Test that writing todos replaces existing list."""
        # Write first set
        params1 = {
            "todos": [
                {"content": "Old task", "status": "pending"}
            ]
        }
        await todo_write_tool(params1, test_context)

        # Write second set (should replace)
        params2 = {
            "todos": [
                {"content": "New task 1", "status": "pending"},
                {"content": "New task 2", "status": "pending"}
            ]
        }
        result = await todo_write_tool(params2, test_context)

        assert result["details"]["total"] == 2
        assert result["todos"][0]["content"] == "New task 1"

    @pytest.mark.asyncio
    async def test_todo_read_after_write(self, test_context):
        """Test reading todos after writing."""
        # Write todos
        params = {
            "todos": [
                {"content": "Task 1", "status": "completed"},
                {"content": "Task 2", "status": "pending"}
            ]
        }
        await todo_write_tool(params, test_context)

        # Read todos
        result = await todo_read_tool({}, test_context)

        assert result["details"]["total"] == 2
        assert result["details"]["completed"] == 1
        assert result["details"]["pending"] == 1

    @pytest.mark.asyncio
    async def test_todo_write_adds_default_priority(self, test_context):
        """Test that default priority is added if missing."""
        params = {
            "todos": [
                {"content": "Task without priority", "status": "pending"}
            ]
        }

        result = await todo_write_tool(params, test_context)

        assert result["todos"][0]["priority"] == "medium"

    @pytest.mark.asyncio
    async def test_todo_write_preserves_explicit_priority(self, test_context):
        """Test that explicit priority is preserved."""
        params = {
            "todos": [
                {"content": "High priority task", "status": "pending", "priority": "high"}
            ]
        }

        result = await todo_write_tool(params, test_context)

        assert result["todos"][0]["priority"] == "high"

    @pytest.mark.asyncio
    async def test_todo_write_adds_timestamps(self, test_context):
        """Test that timestamps are added automatically."""
        params = {
            "todos": [
                {"content": "Task", "status": "pending"}
            ]
        }

        result = await todo_write_tool(params, test_context)

        assert "created_at" in result["todos"][0]
        assert "id" in result["todos"][0]

    @pytest.mark.asyncio
    async def test_todo_write_validates_missing_todos_param(self, test_context):
        """Test validation when todos parameter is missing."""
        result = await todo_write_tool({}, test_context)

        assert "Missing 'todos' parameter" in result["message"]

    @pytest.mark.asyncio
    async def test_todo_write_validates_todos_type(self, test_context):
        """Test validation when todos is not an array."""
        params = {"todos": "not an array"}

        result = await todo_write_tool(params, test_context)

        assert "Invalid 'todos' parameter type" in result["message"]

    @pytest.mark.asyncio
    async def test_todo_write_validates_empty_array(self, test_context):
        """Test validation when todos array is empty."""
        params = {"todos": []}

        result = await todo_write_tool(params, test_context)

        assert "Empty 'todos' array" in result["message"]

    @pytest.mark.asyncio
    async def test_todo_write_validates_todo_structure(self, test_context):
        """Test validation of individual todo structure."""
        params = {
            "todos": [
                {"status": "pending"}  # Missing 'content'
            ]
        }

        result = await todo_write_tool(params, test_context)

        assert "missing required 'content' field" in result["message"]

    @pytest.mark.asyncio
    async def test_todo_write_validates_status_field(self, test_context):
        """Test validation when status field is missing."""
        params = {
            "todos": [
                {"content": "Task"}  # Missing 'status'
            ]
        }

        result = await todo_write_tool(params, test_context)

        assert "missing required 'status' field" in result["message"]

    @pytest.mark.asyncio
    async def test_todo_write_validates_status_values(self, test_context):
        """Test validation of status field values."""
        params = {
            "todos": [
                {"content": "Task", "status": "invalid_status"}
            ]
        }

        result = await todo_write_tool(params, test_context)

        assert "invalid status" in result["message"]
        assert "pending" in result["message"]
        assert "in_progress" in result["message"]
        assert "completed" in result["message"]

    @pytest.mark.asyncio
    async def test_todo_write_validates_todo_is_dict(self, test_context):
        """Test validation when todo is not a dictionary."""
        params = {
            "todos": ["not a dict"]
        }

        result = await todo_write_tool(params, test_context)

        assert "must be an object" in result["message"]

    @pytest.mark.asyncio
    async def test_todos_isolated_by_session(self):
        """Test that todos are isolated between different sessions."""
        context1 = {"user_id": uuid4(), "project_id": "project1"}
        context2 = {"user_id": uuid4(), "project_id": "project2"}

        # Write to session 1
        await todo_write_tool(
            {"todos": [{"content": "Task 1", "status": "pending"}]},
            context1
        )

        # Write to session 2
        await todo_write_tool(
            {"todos": [{"content": "Task 2", "status": "pending"}]},
            context2
        )

        # Read from session 1
        result1 = await todo_read_tool({}, context1)
        assert result1["todos"][0]["content"] == "Task 1"

        # Read from session 2
        result2 = await todo_read_tool({}, context2)
        assert result2["todos"][0]["content"] == "Task 2"

    @pytest.mark.asyncio
    async def test_todo_write_with_all_statuses(self, test_context):
        """Test writing todos with all possible statuses."""
        params = {
            "todos": [
                {"content": "Pending task", "status": "pending"},
                {"content": "In progress task", "status": "in_progress"},
                {"content": "Completed task", "status": "completed"}
            ]
        }

        result = await todo_write_tool(params, test_context)

        assert result["details"]["pending"] == 1
        assert result["details"]["in_progress"] == 1
        assert result["details"]["completed"] == 1

    @pytest.mark.asyncio
    async def test_todo_read_message_format(self, test_context):
        """Test the format of read message with todos."""
        params = {
            "todos": [
                {"content": "Task 1", "status": "completed"},
                {"content": "Task 2", "status": "in_progress"},
                {"content": "Task 3", "status": "pending"}
            ]
        }
        await todo_write_tool(params, test_context)

        result = await todo_read_tool({}, test_context)

        assert "Found 3 todos" in result["message"]
        assert "1 completed" in result["message"]
        assert "1 in progress" in result["message"]
        assert "1 pending" in result["message"]

    @pytest.mark.asyncio
    async def test_todo_write_complex_content(self, test_context):
        """Test writing todos with complex content."""
        params = {
            "todos": [
                {
                    "content": "Task with\nmultiple\nlines",
                    "status": "pending"
                },
                {
                    "content": "Task with special chars: @#$%^&*()",
                    "status": "pending"
                }
            ]
        }

        result = await todo_write_tool(params, test_context)

        assert result["details"]["total"] == 2
        assert "multiple" in result["todos"][0]["content"]
        assert "@#$%^&*()" in result["todos"][1]["content"]
