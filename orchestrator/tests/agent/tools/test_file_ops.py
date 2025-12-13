"""
Tests for file operation tools.

Tests read_file, write_file, patch_file, and multi_edit tools.
"""

import pytest
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch, Mock

from app.agent.tools.file_ops.read_write import read_file_tool, write_file_tool
from app.agent.tools.file_ops.edit import patch_file_tool, multi_edit_tool


@pytest.mark.unit
class TestReadFileTool:
    """Test suite for read_file tool."""

    @pytest.mark.asyncio
    async def test_read_file_success_docker(self, test_context, temp_project_dir, monkeypatch):
        """Test reading a file in Docker mode."""
        # Mock settings to use Docker mode
        from app.config import get_settings
        settings = get_settings()
        monkeypatch.setattr(settings, "deployment_mode", "docker")

        # Mock get_project_path to return our temp directory
        def mock_get_project_path(user_id, project_id):
            return f"{temp_project_dir}/../../.."

        monkeypatch.setattr("app.agent.tools.file_ops.read_write.get_project_path",
                          lambda u, p: str(temp_project_dir.parent.parent))

        # Create test file
        test_file = temp_project_dir / "test.txt"
        test_content = "Hello World"
        test_file.write_text(test_content)

        result = await read_file_tool(
            {"file_path": "test.txt"},
            test_context
        )

        assert "content" in result
        assert result["content"] == test_content

    @pytest.mark.asyncio
    async def test_read_file_not_found_docker(self, test_context, temp_project_dir, monkeypatch):
        """Test reading a non-existent file in Docker mode."""
        from app.config import get_settings
        settings = get_settings()
        monkeypatch.setattr(settings, "deployment_mode", "docker")
        monkeypatch.setattr("app.agent.tools.file_ops.read_write.get_project_path",
                          lambda u, p: str(temp_project_dir.parent.parent))

        result = await read_file_tool(
            {"file_path": "nonexistent.txt"},
            test_context
        )

        assert result.get("exists") is False
        assert "does not exist" in result["message"]

    @pytest.mark.asyncio
    async def test_read_file_missing_parameter(self, test_context):
        """Test read_file with missing file_path parameter."""
        with pytest.raises(ValueError, match="file_path parameter is required"):
            await read_file_tool({}, test_context)

    @pytest.mark.asyncio
    async def test_read_file_kubernetes_mode(self, test_context, monkeypatch):
        """Test reading a file in Kubernetes mode."""
        from app.config import get_settings
        from unittest.mock import AsyncMock
        settings = get_settings()
        monkeypatch.setattr(settings, "deployment_mode", "kubernetes")

        # Mock the orchestrator
        mock_orchestrator = Mock()
        mock_orchestrator.read_file = AsyncMock(return_value="File content from pod")

        monkeypatch.setattr("app.agent.tools.file_ops.read_write.get_orchestrator",
                          lambda: mock_orchestrator)
        monkeypatch.setattr("app.agent.tools.file_ops.read_write.is_kubernetes_mode",
                          lambda: True)

        result = await read_file_tool(
            {"file_path": "src/App.jsx"},
            test_context
        )

        assert "content" in result
        assert result["content"] == "File content from pod"
        mock_orchestrator.read_file.assert_called_once()


@pytest.mark.unit
class TestWriteFileTool:
    """Test suite for write_file tool."""

    @pytest.mark.asyncio
    async def test_write_file_success_docker(self, test_context, temp_project_dir, monkeypatch):
        """Test writing a file in Docker mode."""
        from app.config import get_settings
        settings = get_settings()
        monkeypatch.setattr(settings, "deployment_mode", "docker")
        monkeypatch.setattr("app.agent.tools.file_ops.read_write.get_project_path",
                          lambda u, p: str(temp_project_dir.parent.parent))

        content = "New file content"
        result = await write_file_tool(
            {"file_path": "new_file.txt", "content": content},
            test_context
        )

        assert "preview" in result
        assert "line_count" in result["details"]

        # Verify file was created
        file_path = temp_project_dir / "new_file.txt"
        assert file_path.exists()
        assert file_path.read_text() == content

    @pytest.mark.asyncio
    async def test_write_file_creates_directories(self, test_context, temp_project_dir, monkeypatch):
        """Test that write_file creates parent directories."""
        from app.config import get_settings
        settings = get_settings()
        monkeypatch.setattr(settings, "deployment_mode", "docker")
        monkeypatch.setattr("app.agent.tools.file_ops.read_write.get_project_path",
                          lambda u, p: str(temp_project_dir.parent.parent))

        result = await write_file_tool(
            {"file_path": "nested/dir/file.txt", "content": "Content"},
            test_context
        )

        assert "preview" in result

        # Verify nested directories and file created
        file_path = temp_project_dir / "nested" / "dir" / "file.txt"
        assert file_path.exists()

    @pytest.mark.asyncio
    async def test_write_file_kubernetes_mode(self, test_context, monkeypatch):
        """Test writing a file in Kubernetes mode."""
        from app.config import get_settings
        from unittest.mock import AsyncMock
        settings = get_settings()
        monkeypatch.setattr(settings, "deployment_mode", "kubernetes")

        # Mock the orchestrator
        mock_orchestrator = Mock()
        mock_orchestrator.write_file = AsyncMock(return_value=True)

        monkeypatch.setattr("app.agent.tools.file_ops.read_write.get_orchestrator",
                          lambda: mock_orchestrator)
        monkeypatch.setattr("app.agent.tools.file_ops.read_write.is_kubernetes_mode",
                          lambda: True)

        result = await write_file_tool(
            {"file_path": "src/NewComponent.jsx", "content": "Component code"},
            test_context
        )

        assert "preview" in result
        mock_orchestrator.write_file.assert_called_once()

    @pytest.mark.asyncio
    async def test_write_file_missing_parameters(self, test_context):
        """Test write_file with missing parameters."""
        with pytest.raises(ValueError, match="file_path parameter is required"):
            await write_file_tool({"content": "test"}, test_context)

        with pytest.raises(ValueError, match="content parameter is required"):
            await write_file_tool({"file_path": "test.txt"}, test_context)


@pytest.mark.unit
class TestPatchFileTool:
    """Test suite for patch_file tool."""

    @pytest.mark.asyncio
    async def test_patch_file_success_docker(self, test_context, temp_project_dir, monkeypatch):
        """Test successfully patching a file in Docker mode."""
        from app.config import get_settings
        settings = get_settings()
        monkeypatch.setattr(settings, "deployment_mode", "docker")
        monkeypatch.setattr("app.agent.tools.file_ops.edit.get_project_path",
                          lambda u, p: str(temp_project_dir.parent.parent))

        # Create a file to patch
        test_file = temp_project_dir / "App.jsx"
        original_content = """function App() {
  return (
    <div className="bg-blue-500">
      <h1>Hello</h1>
    </div>
  );
}"""
        test_file.write_text(original_content)

        result = await patch_file_tool(
            {
                "file_path": "App.jsx",
                "search": '<div className="bg-blue-500">',
                "replace": '<div className="bg-green-500">'
            },
            test_context
        )

        assert "diff" in result
        assert "match_method" in result["details"]

        # Verify patch was applied
        patched_content = test_file.read_text()
        assert "bg-green-500" in patched_content
        assert "bg-blue-500" not in patched_content

    @pytest.mark.asyncio
    async def test_patch_file_search_not_found(self, test_context, temp_project_dir, monkeypatch):
        """Test patch_file when search block is not found."""
        from app.config import get_settings
        settings = get_settings()
        monkeypatch.setattr(settings, "deployment_mode", "docker")
        monkeypatch.setattr("app.agent.tools.file_ops.edit.get_project_path",
                          lambda u, p: str(temp_project_dir.parent.parent))

        test_file = temp_project_dir / "App.jsx"
        test_file.write_text("function App() { return <div>Test</div>; }")

        result = await patch_file_tool(
            {
                "file_path": "App.jsx",
                "search": "nonexistent code",
                "replace": "new code"
            },
            test_context
        )

        assert "Could not find matching code" in result["message"]
        assert "suggestion" in result

    @pytest.mark.asyncio
    async def test_patch_file_not_found(self, test_context, temp_project_dir, monkeypatch):
        """Test patch_file on non-existent file."""
        from app.config import get_settings
        settings = get_settings()
        monkeypatch.setattr(settings, "deployment_mode", "docker")
        monkeypatch.setattr("app.agent.tools.file_ops.edit.get_project_path",
                          lambda u, p: str(temp_project_dir.parent.parent))

        result = await patch_file_tool(
            {
                "file_path": "nonexistent.jsx",
                "search": "old",
                "replace": "new"
            },
            test_context
        )

        assert "does not exist" in result["message"]


@pytest.mark.unit
class TestMultiEditTool:
    """Test suite for multi_edit tool."""

    @pytest.mark.asyncio
    async def test_multi_edit_success(self, test_context, temp_project_dir, monkeypatch):
        """Test applying multiple edits successfully."""
        from app.config import get_settings
        settings = get_settings()
        monkeypatch.setattr(settings, "deployment_mode", "docker")
        monkeypatch.setattr("app.agent.tools.file_ops.edit.get_project_path",
                          lambda u, p: str(temp_project_dir.parent.parent))

        test_file = temp_project_dir / "config.js"
        original_content = """const API_URL = 'http://localhost:3000';
const APP_NAME = 'My App';
const VERSION = '1.0.0';"""
        test_file.write_text(original_content)

        result = await multi_edit_tool(
            {
                "file_path": "config.js",
                "edits": [
                    {"search": "http://localhost:3000", "replace": "https://api.example.com"},
                    {"search": "My App", "replace": "Tesslate Studio"},
                    {"search": "1.0.0", "replace": "2.0.0"}
                ]
            },
            test_context
        )

        assert "diff" in result
        assert result["details"]["edit_count"] == 3
        assert len(result["details"]["applied_edits"]) == 3

        # Verify all edits were applied
        new_content = test_file.read_text()
        assert "https://api.example.com" in new_content
        assert "Tesslate Studio" in new_content
        assert "2.0.0" in new_content

    @pytest.mark.asyncio
    async def test_multi_edit_partial_failure(self, test_context, temp_project_dir, monkeypatch):
        """Test multi_edit when one edit fails."""
        from app.config import get_settings
        settings = get_settings()
        monkeypatch.setattr(settings, "deployment_mode", "docker")
        monkeypatch.setattr("app.agent.tools.file_ops.edit.get_project_path",
                          lambda u, p: str(temp_project_dir.parent.parent))

        test_file = temp_project_dir / "config.js"
        test_file.write_text("const API_URL = 'localhost';")

        result = await multi_edit_tool(
            {
                "file_path": "config.js",
                "edits": [
                    {"search": "localhost", "replace": "example.com"},
                    {"search": "nonexistent", "replace": "new"}  # This will fail
                ]
            },
            test_context
        )

        assert "failed" in result["message"].lower()
        assert "edit_index" in result["details"]

    @pytest.mark.asyncio
    async def test_multi_edit_empty_edits(self, test_context):
        """Test multi_edit with empty edits list."""
        with pytest.raises(ValueError, match="edits parameter is required"):
            await multi_edit_tool(
                {"file_path": "test.js", "edits": []},
                test_context
            )

    @pytest.mark.asyncio
    async def test_multi_edit_invalid_edit_format(self, test_context):
        """Test multi_edit with invalid edit format."""
        result = await multi_edit_tool(
            {
                "file_path": "test.js",
                "edits": [
                    {"search": "old"},  # Missing 'replace'
                ]
            },
            test_context
        )

        assert "missing 'search' or 'replace'" in result["message"]


@pytest.mark.integration
class TestFileOpsIntegration:
    """Integration tests for file operation tools."""

    @pytest.mark.asyncio
    async def test_write_then_read_workflow(self, test_context, temp_project_dir, monkeypatch):
        """Test writing a file and then reading it back."""
        from app.config import get_settings
        settings = get_settings()
        monkeypatch.setattr(settings, "deployment_mode", "docker")
        monkeypatch.setattr("app.agent.tools.file_ops.read_write.get_project_path",
                          lambda u, p: str(temp_project_dir.parent.parent))

        content = "Test content"

        # Write file
        write_result = await write_file_tool(
            {"file_path": "test.txt", "content": content},
            test_context
        )

        assert "preview" in write_result

        # Read file back
        read_result = await read_file_tool(
            {"file_path": "test.txt"},
            test_context
        )

        assert read_result["content"] == content

    @pytest.mark.asyncio
    async def test_write_patch_read_workflow(self, test_context, temp_project_dir, monkeypatch):
        """Test writing, patching, and reading a file."""
        from app.config import get_settings
        settings = get_settings()
        monkeypatch.setattr(settings, "deployment_mode", "docker")

        def mock_get_project_path(u, p):
            return str(temp_project_dir.parent.parent)

        monkeypatch.setattr("app.agent.tools.file_ops.read_write.get_project_path", mock_get_project_path)
        monkeypatch.setattr("app.agent.tools.file_ops.edit.get_project_path", mock_get_project_path)

        # Write initial file
        await write_file_tool(
            {"file_path": "Component.jsx", "content": '<button className="bg-blue-500">Click</button>'},
            test_context
        )

        # Patch the file
        patch_result = await patch_file_tool(
            {
                "file_path": "Component.jsx",
                "search": "bg-blue-500",
                "replace": "bg-green-500"
            },
            test_context
        )

        assert "diff" in patch_result

        # Read the patched file
        read_result = await read_file_tool(
            {"file_path": "Component.jsx"},
            test_context
        )

        assert "bg-green-500" in read_result["content"]
        assert "bg-blue-500" not in read_result["content"]
