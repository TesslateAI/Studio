"""
Unit tests for Project Metadata Tools.

Tests project information retrieval tools.
"""

import pytest
from unittest.mock import Mock, AsyncMock
from uuid import uuid4
from datetime import datetime
from app.agent.tools.project_ops.metadata import get_project_info_tool


@pytest.mark.unit
class TestProjectMetadataTools:
    """Test suite for project metadata tools."""

    @pytest.fixture
    def mock_project(self):
        """Create a mock project."""
        project = Mock()
        project.id = uuid4()
        project.name = "Test Project"
        project.description = "A test project for unit testing"
        project.owner_id = uuid4()
        project.created_at = datetime(2024, 1, 1, 12, 0, 0)
        project.updated_at = datetime(2024, 1, 15, 14, 30, 0)
        return project

    @pytest.fixture
    def mock_db(self):
        """Create a mock database session."""
        return AsyncMock()

    @pytest.fixture
    def test_context(self, mock_db):
        """Create a test context."""
        return {
            "user_id": uuid4(),
            "project_id": uuid4(),
            "db": mock_db
        }

    @pytest.mark.asyncio
    async def test_get_project_info_success(self, test_context, mock_project, mock_db):
        """Test successful project info retrieval."""
        # Setup mock database response
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = mock_project
        mock_db.execute.return_value = mock_result

        result = await get_project_info_tool({}, test_context)

        assert result["message"] == f"Project: {mock_project.name}"
        assert result["id"] == mock_project.id
        assert result["name"] == mock_project.name
        assert result["description"] == mock_project.description

    @pytest.mark.asyncio
    async def test_get_project_info_includes_details(self, test_context, mock_project, mock_db):
        """Test that project info includes detailed information."""
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = mock_project
        mock_db.execute.return_value = mock_result

        result = await get_project_info_tool({}, test_context)

        assert "details" in result
        assert result["details"]["owner_id"] == mock_project.owner_id
        assert result["details"]["created_at"] == "2024-01-01T12:00:00"
        assert result["details"]["updated_at"] == "2024-01-15T14:30:00"

    @pytest.mark.asyncio
    async def test_get_project_info_not_found(self, test_context, mock_db):
        """Test handling of project not found."""
        # Setup mock database to return None
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        result = await get_project_info_tool({}, test_context)

        assert "not found" in result["message"]
        assert result["exists"] is False
        assert "suggestion" in result

    @pytest.mark.asyncio
    async def test_get_project_info_uses_context_project_id(self, test_context, mock_project, mock_db):
        """Test that tool uses project_id from context."""
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = mock_project
        mock_db.execute.return_value = mock_result

        await get_project_info_tool({}, test_context)

        # Verify the execute was called
        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_project_info_handles_none_timestamps(self, test_context, mock_project, mock_db):
        """Test handling of None timestamps."""
        mock_project.created_at = None
        mock_project.updated_at = None

        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = mock_project
        mock_db.execute.return_value = mock_result

        result = await get_project_info_tool({}, test_context)

        assert result["details"]["created_at"] is None
        assert result["details"]["updated_at"] is None

    @pytest.mark.asyncio
    async def test_get_project_info_with_empty_description(self, test_context, mock_project, mock_db):
        """Test project info with empty description."""
        mock_project.description = ""

        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = mock_project
        mock_db.execute.return_value = mock_result

        result = await get_project_info_tool({}, test_context)

        assert result["description"] == ""
        assert result["name"] == mock_project.name

    @pytest.mark.asyncio
    async def test_get_project_info_with_long_description(self, test_context, mock_project, mock_db):
        """Test project info with very long description."""
        mock_project.description = "A" * 10000

        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = mock_project
        mock_db.execute.return_value = mock_result

        result = await get_project_info_tool({}, test_context)

        assert len(result["description"]) == 10000

    @pytest.mark.asyncio
    async def test_get_project_info_with_special_characters(self, test_context, mock_project, mock_db):
        """Test project info with special characters in name/description."""
        mock_project.name = "Project with émojis 🚀 and spëcial chars"
        mock_project.description = "Description with\nmultiple\nlines"

        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = mock_project
        mock_db.execute.return_value = mock_result

        result = await get_project_info_tool({}, test_context)

        assert "🚀" in result["name"]
        assert "émojis" in result["name"]
        assert "\n" in result["description"]

    @pytest.mark.asyncio
    async def test_get_project_info_returns_all_required_fields(self, test_context, mock_project, mock_db):
        """Test that all required fields are present in response."""
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = mock_project
        mock_db.execute.return_value = mock_result

        result = await get_project_info_tool({}, test_context)

        # Check all expected fields are present
        assert "message" in result
        assert "id" in result
        assert "name" in result
        assert "description" in result
        assert "details" in result
        assert "owner_id" in result["details"]
        assert "created_at" in result["details"]
        assert "updated_at" in result["details"]

    @pytest.mark.asyncio
    async def test_get_project_info_error_message_helpful(self, test_context, mock_db):
        """Test that error message is helpful when project not found."""
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        result = await get_project_info_tool({}, test_context)

        assert "suggestion" in result
        assert "Check if the project exists" in result["suggestion"]

    @pytest.mark.asyncio
    async def test_get_project_info_no_params_required(self, test_context, mock_project, mock_db):
        """Test that tool works with empty parameters."""
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = mock_project
        mock_db.execute.return_value = mock_result

        # Should work with empty dict
        result = await get_project_info_tool({}, test_context)
        assert result["name"] == mock_project.name

    @pytest.mark.asyncio
    async def test_get_project_info_message_format(self, test_context, mock_project, mock_db):
        """Test the format of success message."""
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = mock_project
        mock_db.execute.return_value = mock_result

        result = await get_project_info_tool({}, test_context)

        # Message should be in format "Project: {name}"
        assert result["message"].startswith("Project:")
        assert mock_project.name in result["message"]

    @pytest.mark.asyncio
    async def test_get_project_info_multiple_calls_consistent(self, test_context, mock_project, mock_db):
        """Test that multiple calls return consistent results."""
        mock_result = Mock()
        mock_result.scalar_one_or_none.return_value = mock_project
        mock_db.execute.return_value = mock_result

        result1 = await get_project_info_tool({}, test_context)

        # Reset mock for second call
        mock_db.execute.reset_mock()
        mock_db.execute.return_value = mock_result

        result2 = await get_project_info_tool({}, test_context)

        assert result1["id"] == result2["id"]
        assert result1["name"] == result2["name"]
        assert result1["description"] == result2["description"]
