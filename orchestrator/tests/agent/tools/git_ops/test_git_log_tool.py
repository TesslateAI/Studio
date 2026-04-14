"""
Tests for the git_log agent tool.

Asserts that ``git_log_tool`` parses the structured commit format the
tool installs via ``--pretty=format`` and honors the filter parameters.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_git_log_returns_all_commits_on_main(temp_git_repo, tool_context):
    from app.agent.tools.git_ops.git_log_tool import git_log_tool

    result = await git_log_tool({}, tool_context)

    assert result["success"] is True
    assert result["count"] == 3
    commits = result["commits"]
    assert len(commits) == 3

    # Newest commit first (git log default).
    assert commits[0]["subject"] == "Update greeting"
    assert commits[0]["author"]["name"] == "Bob"
    assert commits[0]["author"]["email"] == "bob@example.com"

    assert commits[1]["subject"] == "Add app.py"
    assert commits[1]["author"]["name"] == "Alice"

    assert commits[2]["subject"] == "Initial commit"
    assert commits[2]["author"]["name"] == "Alice"

    for commit in commits:
        assert isinstance(commit["hash"], str) and len(commit["hash"]) == 40
        assert isinstance(commit["abbrev"], str) and 0 < len(commit["abbrev"]) <= 12
        assert commit["date"].startswith("2024-")


async def test_git_log_max_count_limits_results(temp_git_repo, tool_context):
    from app.agent.tools.git_ops.git_log_tool import git_log_tool

    result = await git_log_tool({"max_count": 2}, tool_context)

    assert result["success"] is True
    assert result["count"] == 2
    assert result["commits"][0]["subject"] == "Update greeting"
    assert result["commits"][1]["subject"] == "Add app.py"


async def test_git_log_author_filter(temp_git_repo, tool_context):
    from app.agent.tools.git_ops.git_log_tool import git_log_tool

    result = await git_log_tool({"author": "Bob"}, tool_context)

    assert result["success"] is True
    assert result["count"] == 1
    assert result["commits"][0]["author"]["name"] == "Bob"
    assert result["commits"][0]["subject"] == "Update greeting"


async def test_git_log_path_filter(temp_git_repo, tool_context):
    from app.agent.tools.git_ops.git_log_tool import git_log_tool

    result = await git_log_tool({"path": "src/app.py"}, tool_context)

    assert result["success"] is True
    # src/app.py was added in commit 2 and modified in commit 3.
    assert result["count"] == 2
    subjects = {c["subject"] for c in result["commits"]}
    assert subjects == {"Add app.py", "Update greeting"}


async def test_git_log_rejects_non_positive_max_count(temp_git_repo, tool_context):
    from app.agent.tools.git_ops.git_log_tool import git_log_tool

    result = await git_log_tool({"max_count": 0}, tool_context)
    assert result["success"] is False
    assert "positive" in result["message"]
