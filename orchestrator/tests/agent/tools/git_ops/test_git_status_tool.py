"""
Tests for the git_status agent tool.

Exercises the porcelain v2 parser against known worktree state:
 - modified unstaged README.md
 - staged new file src/staged.py
 - untracked notes.txt
 - current branch = main
"""

from __future__ import annotations

import subprocess

import pytest

pytestmark = pytest.mark.asyncio


async def test_git_status_reports_mixed_state(temp_git_repo, tool_context):
    from app.agent.tools.git_ops.git_status_tool import git_status_tool

    result = await git_status_tool({}, tool_context)

    assert result["success"] is True

    # Branch metadata.
    assert result["branch"]["name"] == "main"
    # No upstream configured in the fixture.
    assert result["branch"]["upstream"] is None
    assert result["branch"]["ahead"] == 0
    assert result["branch"]["behind"] == 0

    # Changes: one modified unstaged (README.md), one staged new (src/staged.py).
    by_path = {c["path"]: c for c in result["changes"]}
    assert "README.md" in by_path
    assert "src/staged.py" in by_path

    readme = by_path["README.md"]
    # README is modified in worktree, unchanged in index.
    assert readme["worktree_status"] == "M"
    assert readme["index_status"] == "."

    staged = by_path["src/staged.py"]
    # staged new file: added in index, unchanged in worktree.
    assert staged["index_status"] == "A"
    assert staged["worktree_status"] == "."

    # Untracked.
    assert "notes.txt" in result["untracked"]

    # No stash, no ignored entries emitted by default.
    assert result["stash_count"] == 0
    assert isinstance(result["ignored"], list)


async def test_git_status_clean_repo(temp_git_repo, tool_context):
    from app.agent.tools.git_ops.git_status_tool import git_status_tool

    # Revert all worktree changes and drop the untracked/staged files.
    subprocess.run(
        ["git", "restore", "README.md"],
        cwd=str(temp_git_repo),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "restore", "--staged", "src/staged.py"],
        cwd=str(temp_git_repo),
        check=True,
        capture_output=True,
    )
    (temp_git_repo / "src" / "staged.py").unlink()
    (temp_git_repo / "notes.txt").unlink()

    result = await git_status_tool({}, tool_context)

    assert result["success"] is True
    assert result["branch"]["name"] == "main"
    assert result["changes"] == []
    assert result["untracked"] == []
    assert "clean" in result["message"].lower()


async def test_git_status_exclude_untracked(temp_git_repo, tool_context):
    from app.agent.tools.git_ops.git_status_tool import git_status_tool

    result = await git_status_tool({"include_untracked": False}, tool_context)

    assert result["success"] is True
    # Untracked files should be absent when include_untracked=False.
    assert "notes.txt" not in result["untracked"]
    assert result["untracked"] == []
    # Tracked changes are still present.
    paths = {c["path"] for c in result["changes"]}
    assert "README.md" in paths
    assert "src/staged.py" in paths
