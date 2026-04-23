"""
Tests for file operation tools.

Tests read_file, write_file, patch_file, and multi_edit tools.

All tools use the unified orchestrator interface (get_orchestrator()),
so tests mock app.services.orchestration.get_orchestrator to return
an in-memory mock orchestrator.
"""

from unittest.mock import Mock, patch

import pytest

from app.agent.tools.file_ops.edit import multi_edit_tool, patch_file_tool
from app.agent.tools.file_ops.read_write import read_file_tool, write_file_tool


@pytest.fixture
def mock_orchestrator():
    """
    Create a mock orchestrator with in-memory file storage.

    Simulates the unified orchestrator interface used by file tools.
    Files are stored in a dict keyed by file_path for easy assertions.
    """
    orchestrator = Mock()
    files: dict[str, str] = {}

    async def mock_read_file(**kwargs):
        file_path = kwargs.get("file_path")
        if file_path in files:
            return files[file_path]
        return None

    async def mock_write_file(**kwargs):
        file_path = kwargs.get("file_path")
        content = kwargs.get("content")
        files[file_path] = content
        return True

    orchestrator.read_file = mock_read_file
    orchestrator.write_file = mock_write_file
    orchestrator._files = files  # Expose for assertions

    return orchestrator


@pytest.fixture
def patched_orchestrator(mock_orchestrator):
    """Patch get_orchestrator to return our mock for all tool imports."""
    with patch(
        "app.services.orchestration.get_orchestrator",
        return_value=mock_orchestrator,
    ):
        yield mock_orchestrator


@pytest.mark.unit
class TestReadFileTool:
    """Test suite for read_file tool."""

    @pytest.mark.asyncio
    async def test_read_file_success_docker(self, test_context, patched_orchestrator):
        """Test reading a file in Docker mode."""
        # Seed a file in the mock orchestrator
        patched_orchestrator._files["test.txt"] = "Hello World"

        result = await read_file_tool({"file_path": "test.txt"}, test_context)

        assert "content" in result
        assert result["content"] == "Hello World"

    @pytest.mark.asyncio
    async def test_read_file_not_found_docker(self, test_context, patched_orchestrator):
        """Test reading a non-existent file."""
        result = await read_file_tool({"file_path": "nonexistent.txt"}, test_context)

        assert result.get("exists") is False
        assert "does not exist" in result["message"]

    @pytest.mark.asyncio
    async def test_read_file_missing_parameter(self, test_context):
        """Test read_file with missing file_path parameter."""
        with pytest.raises(ValueError, match="file_path parameter is required"):
            await read_file_tool({}, test_context)

    @pytest.mark.asyncio
    async def test_read_file_kubernetes_mode(self, test_context, patched_orchestrator):
        """Test reading a file via orchestrator (same interface for K8s and Docker)."""
        patched_orchestrator._files["src/App.jsx"] = "File content from pod"

        result = await read_file_tool({"file_path": "src/App.jsx"}, test_context)

        assert "content" in result
        assert result["content"] == "File content from pod"


@pytest.mark.unit
class TestWriteFileTool:
    """Test suite for write_file tool."""

    @pytest.mark.asyncio
    async def test_write_file_success_docker(self, test_context, patched_orchestrator):
        """Test writing a file via orchestrator."""
        content = "New file content"
        result = await write_file_tool(
            {"file_path": "new_file.txt", "content": content}, test_context
        )

        assert "preview" in result
        assert "line_count" in result["details"]

        # Verify file was stored in mock orchestrator
        assert patched_orchestrator._files["new_file.txt"] == content

    @pytest.mark.asyncio
    async def test_write_file_creates_directories(self, test_context, patched_orchestrator):
        """Test that write_file handles nested paths."""
        result = await write_file_tool(
            {"file_path": "nested/dir/file.txt", "content": "Content"}, test_context
        )

        assert "preview" in result

        # Verify nested file was stored
        assert patched_orchestrator._files["nested/dir/file.txt"] == "Content"

    @pytest.mark.asyncio
    async def test_write_file_kubernetes_mode(self, test_context, patched_orchestrator):
        """Test writing a file via orchestrator (same interface for K8s and Docker)."""
        result = await write_file_tool(
            {"file_path": "src/NewComponent.jsx", "content": "Component code"}, test_context
        )

        assert "preview" in result
        assert patched_orchestrator._files["src/NewComponent.jsx"] == "Component code"

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
    async def test_patch_file_success_docker(self, test_context, patched_orchestrator):
        """Test successfully patching a file."""
        original_content = """function App() {
  return (
    <div className="bg-blue-500">
      <h1>Hello</h1>
    </div>
  );
}"""
        patched_orchestrator._files["App.jsx"] = original_content

        result = await patch_file_tool(
            {
                "file_path": "App.jsx",
                "search": '<div className="bg-blue-500">',
                "replace": '<div className="bg-green-500">',
            },
            test_context,
        )

        assert "diff" in result
        assert "match_method" in result["details"]

        # Verify patch was applied via orchestrator
        patched_content = patched_orchestrator._files["App.jsx"]
        assert "bg-green-500" in patched_content
        assert "bg-blue-500" not in patched_content

    @pytest.mark.asyncio
    async def test_patch_file_search_not_found(self, test_context, patched_orchestrator):
        """Test patch_file when search block is not found."""
        patched_orchestrator._files["App.jsx"] = "function App() { return <div>Test</div>; }"

        result = await patch_file_tool(
            {"file_path": "App.jsx", "search": "nonexistent code", "replace": "new code"},
            test_context,
        )

        assert "Could not find matching code" in result["message"]
        assert "suggestion" in result

    @pytest.mark.asyncio
    async def test_patch_file_not_found(self, test_context, patched_orchestrator):
        """Test patch_file on non-existent file."""
        result = await patch_file_tool(
            {"file_path": "nonexistent.jsx", "search": "old", "replace": "new"}, test_context
        )

        assert "does not exist" in result["message"]


@pytest.mark.unit
class TestMultiEditTool:
    """Test suite for multi_edit tool."""

    @pytest.mark.asyncio
    async def test_multi_edit_success(self, test_context, patched_orchestrator):
        """Test applying multiple edits successfully."""
        original_content = """const API_URL = 'http://localhost:3000';
const APP_NAME = 'My App';
const VERSION = '1.0.0';"""
        patched_orchestrator._files["config.js"] = original_content

        result = await multi_edit_tool(
            {
                "file_path": "config.js",
                "edits": [
                    {"search": "http://localhost:3000", "replace": "https://api.example.com"},
                    {"search": "My App", "replace": "OpenSail"},
                    {"search": "1.0.0", "replace": "2.0.0"},
                ],
            },
            test_context,
        )

        assert "diff" in result
        assert result["details"]["edit_count"] == 3
        assert len(result["details"]["applied_edits"]) == 3

        # Verify all edits were applied
        new_content = patched_orchestrator._files["config.js"]
        assert "https://api.example.com" in new_content
        assert "OpenSail" in new_content
        assert "2.0.0" in new_content

    @pytest.mark.asyncio
    async def test_multi_edit_partial_failure(self, test_context, patched_orchestrator):
        """Test multi_edit when one edit fails."""
        patched_orchestrator._files["config.js"] = "const API_URL = 'localhost';"

        result = await multi_edit_tool(
            {
                "file_path": "config.js",
                "edits": [
                    {"search": "localhost", "replace": "example.com"},
                    {"search": "nonexistent", "replace": "new"},  # This will fail
                ],
            },
            test_context,
        )

        assert "failed" in result["message"].lower()
        assert "edit_index" in result["details"]

    @pytest.mark.asyncio
    async def test_multi_edit_empty_edits(self, test_context):
        """Test multi_edit with empty edits list."""
        with pytest.raises(ValueError, match="edits parameter is required"):
            await multi_edit_tool({"file_path": "test.js", "edits": []}, test_context)

    @pytest.mark.asyncio
    async def test_multi_edit_invalid_edit_format(self, test_context, patched_orchestrator):
        """Test multi_edit with invalid edit format."""
        patched_orchestrator._files["test.js"] = "some content"

        result = await multi_edit_tool(
            {
                "file_path": "test.js",
                "edits": [
                    {"search": "old"},  # Missing 'replace'
                ],
            },
            test_context,
        )

        assert "missing 'search' or 'replace'" in result["message"]


@pytest.mark.unit
class TestPatchFileFuzzyMatching:
    """Test fuzzy whitespace matching through the patch_file tool.

    These tests verify that the tool-level patch_file correctly delegates
    to the fuzzy matching in code_patching, handling real-world scenarios
    where AI-generated search blocks don't exactly match file content.
    """

    @pytest.mark.asyncio
    async def test_patch_file_fuzzy_indentation_mismatch(self, test_context, patched_orchestrator):
        """Test patch_file when AI search has different indentation than file."""
        original = """  function greet(name) {
    return `Hello, ${name}!`;
  }"""
        patched_orchestrator._files["utils.js"] = original

        # AI provides search with different indentation (no leading spaces)
        result = await patch_file_tool(
            {
                "file_path": "utils.js",
                "search": "function greet(name) {\n  return `Hello, ${name}!`;\n}",
                "replace": "function greet(name) {\n  return `Hi, ${name}! Welcome!`;\n}",
            },
            test_context,
        )

        assert "diff" in result
        assert "match_method" in result["details"]
        patched = patched_orchestrator._files["utils.js"]
        assert "Welcome!" in patched
        assert "Hello" not in patched

    @pytest.mark.asyncio
    async def test_patch_file_fuzzy_extra_whitespace(self, test_context, patched_orchestrator):
        """Test patch_file when file has extra trailing whitespace."""
        original = "const  data  =  {\n  name:    'John',\n    age:     30\n};"
        patched_orchestrator._files["data.js"] = original

        # AI provides normalized whitespace search
        result = await patch_file_tool(
            {
                "file_path": "data.js",
                "search": "const data = {\n  name: 'John',\n  age: 30\n};",
                "replace": "const data = {\n  name: 'Jane',\n  age: 25\n};",
            },
            test_context,
        )

        assert "diff" in result
        patched = patched_orchestrator._files["data.js"]
        assert "Jane" in patched

    @pytest.mark.asyncio
    async def test_patch_file_fuzzy_blank_line_differences(
        self, test_context, patched_orchestrator
    ):
        """Test patch_file when AI search has extra blank lines vs file."""
        original = "function test() {\n  console.log('hello');\n  return true;\n}"
        patched_orchestrator._files["test.js"] = original

        # AI provides search with extra blank lines
        result = await patch_file_tool(
            {
                "file_path": "test.js",
                "search": "function test() {\n\n  console.log('hello');\n\n  return true;\n}",
                "replace": "function test() {\n  console.log('updated');\n  return true;\n}",
            },
            test_context,
        )

        assert "diff" in result
        patched = patched_orchestrator._files["test.js"]
        assert "updated" in patched

    @pytest.mark.asyncio
    async def test_multi_edit_with_fuzzy_matching(self, test_context, patched_orchestrator):
        """Test multi_edit tool uses fuzzy matching for each edit."""
        original = """  const API_URL = 'http://localhost:3000';
  const APP_NAME = 'My App';"""
        patched_orchestrator._files["config.js"] = original

        # AI searches without leading indentation
        result = await multi_edit_tool(
            {
                "file_path": "config.js",
                "edits": [
                    {
                        "search": "const API_URL = 'http://localhost:3000';",
                        "replace": "const API_URL = 'https://api.example.com';",
                    },
                    {
                        "search": "const APP_NAME = 'My App';",
                        "replace": "const APP_NAME = 'OpenSail';",
                    },
                ],
            },
            test_context,
        )

        assert "diff" in result
        patched = patched_orchestrator._files["config.js"]
        assert "https://api.example.com" in patched
        assert "OpenSail" in patched


@pytest.mark.integration
class TestFileOpsIntegration:
    """Integration tests for file operation tools."""

    @pytest.mark.asyncio
    async def test_write_then_read_workflow(self, test_context, patched_orchestrator):
        """Test writing a file and then reading it back."""
        content = "Test content"

        # Write file
        write_result = await write_file_tool(
            {"file_path": "test.txt", "content": content}, test_context
        )

        assert "preview" in write_result

        # Read file back
        read_result = await read_file_tool({"file_path": "test.txt"}, test_context)

        assert read_result["content"] == content

    @pytest.mark.asyncio
    async def test_write_patch_read_workflow(self, test_context, patched_orchestrator):
        """Test writing, patching, and reading a file."""
        # Write initial file
        await write_file_tool(
            {
                "file_path": "Component.jsx",
                "content": '<button className="bg-blue-500">Click</button>',
            },
            test_context,
        )

        # Patch the file
        patch_result = await patch_file_tool(
            {"file_path": "Component.jsx", "search": "bg-blue-500", "replace": "bg-green-500"},
            test_context,
        )

        assert "diff" in patch_result

        # Read the patched file
        read_result = await read_file_tool({"file_path": "Component.jsx"}, test_context)

        assert "bg-green-500" in read_result["content"]
        assert "bg-blue-500" not in read_result["content"]
