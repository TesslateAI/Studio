"""
Tests for the git_blame agent tool.

Validates porcelain parsing against a 5-line file whose every line was
authored in the initial commit by Alice, and also confirms that the
``line_start``/``line_end`` arguments scope the blame correctly.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_git_blame_whole_file(temp_git_repo, tool_context):
    from app.agent.tools.git_ops.git_blame_tool import git_blame_tool

    result = await git_blame_tool({"file_path": "poem.txt"}, tool_context)

    assert result["success"] is True
    assert result["file"] == "poem.txt"

    lines = result["lines"]
    assert len(lines) == 5

    expected_contents = [
        "line one",
        "line two",
        "line three",
        "line four",
        "line five",
    ]
    for idx, line in enumerate(lines):
        assert line["line_number"] == idx + 1
        assert line["content"] == expected_contents[idx]
        assert line["author"] == "Alice"
        assert line["author_mail"] == "alice@example.com"
        assert len(line["hash"]) == 40
        assert line["abbrev"] == line["hash"][:7]
        assert line["summary"] == "Initial commit"
        assert line["author_time"].isdigit()


async def test_git_blame_line_range(temp_git_repo, tool_context):
    from app.agent.tools.git_ops.git_blame_tool import git_blame_tool

    result = await git_blame_tool(
        {"file_path": "poem.txt", "line_start": 2, "line_end": 4},
        tool_context,
    )

    assert result["success"] is True
    lines = result["lines"]
    assert [line_entry["line_number"] for line_entry in lines] == [2, 3, 4]
    assert [line_entry["content"] for line_entry in lines] == [
        "line two",
        "line three",
        "line four",
    ]


async def test_git_blame_missing_file_path(temp_git_repo, tool_context):
    from app.agent.tools.git_ops.git_blame_tool import git_blame_tool

    result = await git_blame_tool({}, tool_context)
    assert result["success"] is False
    assert "file_path" in result["message"]


async def test_git_blame_invalid_range(temp_git_repo, tool_context):
    from app.agent.tools.git_ops.git_blame_tool import git_blame_tool

    result = await git_blame_tool(
        {"file_path": "poem.txt", "line_start": 5, "line_end": 2},
        tool_context,
    )
    assert result["success"] is False
    assert "range" in result["message"].lower()
