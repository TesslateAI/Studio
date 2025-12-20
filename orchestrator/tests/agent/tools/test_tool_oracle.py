"""
Oracle tests for agent tools using golden input/output pairs.

These tests verify that each tool produces expected outputs for known inputs.
They serve as regression tests to ensure tool behavior remains consistent.

Usage:
    pytest tests/agent/tools/test_tool_oracle.py -v
    pytest tests/agent/tools/test_tool_oracle.py -v -m oracle
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Load golden test data
FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures"


def load_golden_tool_outputs():
    """Load golden tool output test cases from JSON file."""
    filepath = FIXTURES_DIR / "golden_tool_outputs.json"
    with open(filepath, encoding="utf-8") as f:
        return json.load(f)


def load_golden_patches():
    """Load golden patch test cases from JSON file."""
    filepath = FIXTURES_DIR / "golden_patches.json"
    with open(filepath, encoding="utf-8") as f:
        return json.load(f)


GOLDEN_TOOL_OUTPUTS = load_golden_tool_outputs()
GOLDEN_PATCHES = load_golden_patches()


# ============================================================================
# Read File Tool Oracle Tests
# ============================================================================


@pytest.mark.oracle
@pytest.mark.unit
class TestReadFileToolOracle:
    """Oracle tests for read_file tool."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "test_case",
        GOLDEN_TOOL_OUTPUTS["read_file"],
        ids=[tc["id"] for tc in GOLDEN_TOOL_OUTPUTS["read_file"]],
    )
    async def test_read_file_oracle(self, test_case, test_context, tmp_path):
        """Test read_file produces expected outputs for golden inputs."""
        from app.agent.tools.file_ops.read_write import read_file_tool

        expected = test_case["expected"]

        # Create mock orchestrator
        mock_orchestrator = AsyncMock()

        # Setup mock return based on test case
        if test_case.get("mock_file_content") is not None:
            mock_orchestrator.read_file = AsyncMock(return_value=test_case["mock_file_content"])
        else:
            # File not found case
            mock_orchestrator.read_file = AsyncMock(side_effect=FileNotFoundError("File not found"))

        with patch("app.services.orchestration.get_orchestrator", return_value=mock_orchestrator):
            # Execute tool
            result = await read_file_tool(test_case["input"], test_context)

            # Verify success status
            if "success" in expected:
                if expected["success"]:
                    assert "content" in result or result.get("exists") is True, (
                        f"Expected successful read but got: {result}"
                    )
                else:
                    assert (
                        result.get("exists") is False
                        or "does not exist" in result.get("message", "")
                        or "not found" in result.get("message", "").lower()
                    )

            # Verify content if specified
            if "content" in expected and expected["success"]:
                assert result.get("content") == expected["content"], (
                    f"Content mismatch: expected {expected['content']!r}, got {result.get('content')!r}"
                )

            # Verify message pattern if specified
            if "message_contains" in expected:
                assert expected["message_contains"].lower() in result.get("message", "").lower(), (
                    f"Message should contain '{expected['message_contains']}'"
                )


# ============================================================================
# Write File Tool Oracle Tests
# ============================================================================


@pytest.mark.oracle
@pytest.mark.unit
class TestWriteFileToolOracle:
    """Oracle tests for write_file tool."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "test_case",
        GOLDEN_TOOL_OUTPUTS["write_file"],
        ids=[tc["id"] for tc in GOLDEN_TOOL_OUTPUTS["write_file"]],
    )
    async def test_write_file_oracle(self, test_case, test_context, tmp_path):
        """Test write_file produces expected outputs for golden inputs."""
        from app.agent.tools.file_ops.read_write import write_file_tool

        expected = test_case["expected"]

        # Track written content
        written_content = {}

        async def mock_write_file(
            user_id, project_id, container_name, file_path, content, **kwargs
        ):
            written_content[file_path] = content
            return True

        # Create mock orchestrator
        mock_orchestrator = AsyncMock()
        mock_orchestrator.write_file = mock_write_file

        with patch("app.services.orchestration.get_orchestrator", return_value=mock_orchestrator):
            # Execute tool
            result = await write_file_tool(test_case["input"], test_context)

            # Verify success
            if expected.get("success"):
                assert "preview" in result or result.get("success") is True, (
                    f"Expected success but got: {result}"
                )

                # Verify content was written
                file_path = test_case["input"]["file_path"]
                assert file_path in written_content, f"File {file_path} should have been written"
                assert written_content[file_path] == test_case["input"]["content"]

            # Verify message pattern if specified
            if "message_contains" in expected:
                assert expected["message_contains"].lower() in result.get("message", "").lower(), (
                    f"Message should contain '{expected['message_contains']}'"
                )

            # Verify details if specified
            if "details" in expected and "details" in result:
                for key, value in expected["details"].items():
                    assert result["details"].get(key) == value, (
                        f"Detail '{key}' mismatch: expected {value}, got {result['details'].get(key)}"
                    )


# ============================================================================
# Patch File Tool Oracle Tests
# ============================================================================


@pytest.mark.oracle
@pytest.mark.unit
class TestPatchFileToolOracle:
    """Oracle tests for patch_file tool."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "test_case",
        GOLDEN_TOOL_OUTPUTS["patch_file"],
        ids=[tc["id"] for tc in GOLDEN_TOOL_OUTPUTS["patch_file"]],
    )
    async def test_patch_file_oracle(self, test_case, test_context, tmp_path):
        """Test patch_file produces expected outputs for golden inputs."""
        from app.agent.tools.file_ops.edit import patch_file_tool

        expected = test_case["expected"]

        # Track file state for patching
        file_content = test_case.get("mock_file_content", "")
        patched_content = {}

        async def mock_read_file(user_id, project_id, container_name, file_path, **kwargs):
            if file_content is None:
                raise FileNotFoundError("File not found")
            return file_content

        async def mock_write_file(
            user_id, project_id, container_name, file_path, content, **kwargs
        ):
            patched_content[file_path] = content
            return True

        # Create mock orchestrator
        mock_orchestrator = AsyncMock()
        mock_orchestrator.read_file = mock_read_file
        mock_orchestrator.write_file = mock_write_file

        with patch("app.services.orchestration.get_orchestrator", return_value=mock_orchestrator):
            # Execute tool
            result = await patch_file_tool(test_case["input"], test_context)

            # Verify success status
            if expected.get("success"):
                assert "diff" in result or result.get("success") is True, (
                    f"Expected success but got: {result}"
                )

                # Verify match method if specified
                if "details" in expected and "match_method" in expected["details"]:
                    assert (
                        result.get("details", {}).get("match_method")
                        == expected["details"]["match_method"]
                    )
            else:
                # Should be an error
                if "message_contains" in expected:
                    assert (
                        expected["message_contains"].lower() in result.get("message", "").lower()
                    ), f"Message should contain '{expected['message_contains']}'"


# ============================================================================
# Golden Patch Test Cases (from golden_patches.json)
# ============================================================================


@pytest.mark.oracle
@pytest.mark.unit
class TestGoldenPatches:
    """Tests using golden patch cases from golden_patches.json."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "test_case",
        GOLDEN_PATCHES["exact_matches"],
        ids=[tc["id"] for tc in GOLDEN_PATCHES["exact_matches"]],
    )
    async def test_exact_match_patches(self, test_case, test_context, tmp_path):
        """Test exact match patches produce expected results."""
        from app.agent.tools.file_ops.edit import patch_file_tool

        # Track file state
        file_content = {"test_file.js": test_case["original"]}

        async def mock_read_file(user_id, project_id, container_name, file_path, **kwargs):
            return file_content.get(file_path, "")

        async def mock_write_file(
            user_id, project_id, container_name, file_path, content, **kwargs
        ):
            file_content[file_path] = content
            return True

        mock_orchestrator = AsyncMock()
        mock_orchestrator.read_file = mock_read_file
        mock_orchestrator.write_file = mock_write_file

        with patch("app.services.orchestration.get_orchestrator", return_value=mock_orchestrator):
            # Execute patch
            result = await patch_file_tool(
                {
                    "file_path": "test_file.js",
                    "search": test_case["search"],
                    "replace": test_case["replace"],
                },
                test_context,
            )

            expected = test_case["expected"]

            # Verify success
            assert expected["success"] is True, f"Expected success but got: {result}"
            assert "diff" in result or result.get("success") is True

            # Verify content if specified
            if "content" in expected:
                actual_content = file_content.get("test_file.js", "")
                assert actual_content == expected["content"], (
                    f"Content mismatch:\nExpected:\n{expected['content']}\n\nGot:\n{actual_content}"
                )

            # Verify match method
            if "match_method" in expected:
                assert result.get("details", {}).get("match_method") == expected["match_method"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "test_case",
        GOLDEN_PATCHES["fuzzy_matches"],
        ids=[tc["id"] for tc in GOLDEN_PATCHES["fuzzy_matches"]],
    )
    async def test_fuzzy_match_patches(self, test_case, test_context, tmp_path):
        """Test fuzzy match patches produce expected results."""
        from app.agent.tools.file_ops.edit import patch_file_tool

        # Track file state
        file_content = {"test_file.js": test_case["original"]}

        async def mock_read_file(user_id, project_id, container_name, file_path, **kwargs):
            return file_content.get(file_path, "")

        async def mock_write_file(
            user_id, project_id, container_name, file_path, content, **kwargs
        ):
            file_content[file_path] = content
            return True

        mock_orchestrator = AsyncMock()
        mock_orchestrator.read_file = mock_read_file
        mock_orchestrator.write_file = mock_write_file

        with patch("app.services.orchestration.get_orchestrator", return_value=mock_orchestrator):
            # Execute patch
            result = await patch_file_tool(
                {
                    "file_path": "test_file.js",
                    "search": test_case["search"],
                    "replace": test_case["replace"],
                },
                test_context,
            )

            expected = test_case["expected"]

            # Verify success
            if expected["success"]:
                assert "diff" in result or result.get("success") is True, (
                    f"Expected diff but got: {result}"
                )

                # Verify match method contains expected substring
                if "match_method_contains" in expected:
                    match_method = result.get("details", {}).get("match_method", "")
                    assert expected["match_method_contains"] in match_method

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "test_case",
        GOLDEN_PATCHES["no_match_cases"],
        ids=[tc["id"] for tc in GOLDEN_PATCHES["no_match_cases"]],
    )
    async def test_no_match_cases(self, test_case, test_context, tmp_path):
        """Test no-match cases produce expected error messages."""
        from app.agent.tools.file_ops.edit import patch_file_tool

        # Track file state
        file_content = {"test_file.js": test_case["original"]}

        async def mock_read_file(user_id, project_id, container_name, file_path, **kwargs):
            return file_content.get(file_path, "")

        async def mock_write_file(
            user_id, project_id, container_name, file_path, content, **kwargs
        ):
            file_content[file_path] = content
            return True

        mock_orchestrator = AsyncMock()
        mock_orchestrator.read_file = mock_read_file
        mock_orchestrator.write_file = mock_write_file

        with patch("app.services.orchestration.get_orchestrator", return_value=mock_orchestrator):
            # Execute patch
            result = await patch_file_tool(
                {
                    "file_path": "test_file.js",
                    "search": test_case["search"],
                    "replace": test_case["replace"],
                },
                test_context,
            )

            expected = test_case["expected"]

            # Verify failure
            assert expected["success"] is False
            assert "error_contains" in expected

            # Verify error message
            assert expected["error_contains"].lower() in result.get("message", "").lower(), (
                f"Error message should contain '{expected['error_contains']}'"
            )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "test_case",
        GOLDEN_PATCHES["special_characters"],
        ids=[tc["id"] for tc in GOLDEN_PATCHES["special_characters"]],
    )
    async def test_special_character_patches(self, test_case, test_context, tmp_path):
        """Test patches with special characters work correctly."""
        from app.agent.tools.file_ops.edit import patch_file_tool

        # Track file state
        file_content = {"test_file.js": test_case["original"]}

        async def mock_read_file(user_id, project_id, container_name, file_path, **kwargs):
            return file_content.get(file_path, "")

        async def mock_write_file(
            user_id, project_id, container_name, file_path, content, **kwargs
        ):
            file_content[file_path] = content
            return True

        mock_orchestrator = AsyncMock()
        mock_orchestrator.read_file = mock_read_file
        mock_orchestrator.write_file = mock_write_file

        with patch("app.services.orchestration.get_orchestrator", return_value=mock_orchestrator):
            # Execute patch
            result = await patch_file_tool(
                {
                    "file_path": "test_file.js",
                    "search": test_case["search"],
                    "replace": test_case["replace"],
                },
                test_context,
            )

            expected = test_case["expected"]

            # Verify success
            if expected["success"]:
                assert "diff" in result or result.get("success") is True

                # Verify content if specified
                if "content" in expected:
                    actual_content = file_content.get("test_file.js", "")
                    assert actual_content == expected["content"]


# ============================================================================
# Bash Exec Tool Oracle Tests
# ============================================================================


@pytest.mark.oracle
@pytest.mark.unit
class TestBashExecToolOracle:
    """Oracle tests for bash_exec tool."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "test_case",
        GOLDEN_TOOL_OUTPUTS["bash_exec"],
        ids=[tc["id"] for tc in GOLDEN_TOOL_OUTPUTS["bash_exec"]],
    )
    async def test_bash_exec_oracle(self, test_case, test_context):
        """Test bash_exec produces expected outputs for golden inputs."""
        from app.agent.tools.shell_ops.bash import bash_exec_tool

        expected = test_case["expected"]

        # Mock the shell session operations
        with (
            patch("app.agent.tools.shell_ops.bash.shell_open_executor") as mock_open,
            patch("app.agent.tools.shell_ops.bash.shell_exec_executor") as mock_exec,
            patch("app.agent.tools.shell_ops.bash.shell_close_executor") as mock_close,
        ):
            mock_open.return_value = {"success": True, "session_id": "mock-session-123"}

            # Setup mock output based on expected behavior
            if expected.get("success"):
                mock_output = test_case.get("mock_output", "")
                if "output_contains" in expected:
                    mock_output = expected["output_contains"]

                mock_exec.return_value = {"output": mock_output}
            else:
                mock_exec.return_value = {"output": "", "error": "command not found"}

            mock_close.return_value = {"success": True}

            # Execute tool
            result = await bash_exec_tool(test_case["input"], test_context)

            # Verify success status
            if expected.get("success"):
                assert result.get("success") is True, f"Expected success but got: {result}"

                # Verify output contains expected text
                if "output_contains" in expected:
                    output = result.get("output", "")
                    assert expected["output_contains"] in output, (
                        f"Output should contain '{expected['output_contains']}'"
                    )

            # Verify exit code if specified
            if (
                "details" in expected
                and expected.get("success")
                and "exit_code" in expected["details"]
            ):
                assert result["details"]["exit_code"] == expected["details"]["exit_code"]


# ============================================================================
# Shell Session Tool Oracle Tests
# ============================================================================


@pytest.mark.oracle
@pytest.mark.unit
class TestShellSessionToolOracle:
    """Oracle tests for shell session tools (shell_open, shell_exec, shell_close)."""

    @pytest.mark.asyncio
    async def test_shell_open_success_oracle(self, test_context):
        """Test shell_open produces expected output structure."""
        from app.agent.tools.shell_ops.session import shell_open_executor

        # Mock the shell session manager - patch at the source where it's imported from
        mock_manager = MagicMock()
        mock_manager.create_session = AsyncMock(
            return_value={"session_id": "test-session-uuid-123"}
        )

        with patch(
            "app.services.shell_session_manager.get_shell_session_manager",
            return_value=mock_manager,
        ):
            result = await shell_open_executor({}, test_context)

            # Verify expected structure
            assert result.get("success") is True
            assert "session_id" in result

    @pytest.mark.asyncio
    async def test_shell_close_success_oracle(self, test_context):
        """Test shell_close produces expected output structure."""
        from app.agent.tools.shell_ops.session import shell_close_executor

        # Mock the shell session manager - patch at the source where it's imported from
        mock_manager = MagicMock()
        mock_manager.close_session = AsyncMock()

        with patch(
            "app.services.shell_session_manager.get_shell_session_manager",
            return_value=mock_manager,
        ):
            result = await shell_close_executor({"session_id": "test-session-123"}, test_context)

            # Verify expected structure
            assert result.get("success") is True
            assert "closed" in result.get("message", "").lower()


# ============================================================================
# Todo Operations Tool Oracle Tests
# ============================================================================


@pytest.mark.oracle
@pytest.mark.unit
class TestTodoToolOracle:
    """Oracle tests for todo tools."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "test_case",
        GOLDEN_TOOL_OUTPUTS["todo_operations"],
        ids=[tc["id"] for tc in GOLDEN_TOOL_OUTPUTS["todo_operations"]],
    )
    async def test_todo_operations_oracle(self, test_case, test_context):
        """Test todo operations produce expected outputs."""
        from app.agent.tools.planning_ops.todos import todo_read_tool, todo_write_tool

        expected = test_case["expected"]

        # Setup mock context with todos
        test_context["_todos"] = []

        if test_case["id"] == "todo_write_success":
            result = await todo_write_tool(test_case["input"], test_context)

            assert result.get("success") == expected.get("success")

            # Verify details if specified
            if "details" in expected:
                for key, value in expected["details"].items():
                    assert result["details"].get(key) == value, f"Detail '{key}' mismatch"

        elif test_case["id"] == "todo_read_success":
            result = await todo_read_tool(test_case["input"], test_context)

            assert result.get("success") == expected.get("success")

            # Verify todos is array if specified
            if expected.get("todos_is_array"):
                assert isinstance(result.get("todos", []), list)


# ============================================================================
# Multi-Edit Tool Oracle Tests
# ============================================================================


@pytest.mark.oracle
@pytest.mark.unit
class TestMultiEditToolOracle:
    """Oracle tests for multi_edit tool using golden multi-edit cases."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "test_case",
        GOLDEN_PATCHES["multi_edit_cases"],
        ids=[tc["id"] for tc in GOLDEN_PATCHES["multi_edit_cases"]],
    )
    async def test_multi_edit_oracle(self, test_case, test_context, tmp_path):
        """Test multi_edit produces expected results for golden inputs."""
        from app.agent.tools.file_ops.edit import multi_edit_tool

        # Track file state
        file_content = {"test_file.js": test_case["original"]}

        async def mock_read_file(user_id, project_id, container_name, file_path, **kwargs):
            return file_content.get(file_path, "")

        async def mock_write_file(
            user_id, project_id, container_name, file_path, content, **kwargs
        ):
            file_content[file_path] = content
            return True

        mock_orchestrator = AsyncMock()
        mock_orchestrator.read_file = mock_read_file
        mock_orchestrator.write_file = mock_write_file

        with patch("app.services.orchestration.get_orchestrator", return_value=mock_orchestrator):
            # Execute multi-edit
            result = await multi_edit_tool(
                {"file_path": "test_file.js", "edits": test_case["edits"]}, test_context
            )

            expected = test_case["expected"]

            # Verify success
            if expected["success"]:
                assert "diff" in result or result.get("success") is True, (
                    f"Expected diff but got: {result}"
                )

                # Verify edit count
                if "edit_count" in expected:
                    assert result.get("details", {}).get("edit_count") == expected["edit_count"]

                # Verify final content
                if "content" in expected:
                    actual_content = file_content.get("test_file.js", "")
                    assert actual_content == expected["content"], (
                        f"Content mismatch:\nExpected:\n{expected['content']}\n\nGot:\n{actual_content}"
                    )
