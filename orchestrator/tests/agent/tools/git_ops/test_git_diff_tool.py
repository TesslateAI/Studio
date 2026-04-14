"""
Tests for the git_diff agent tool.

Covers the four supported invocation modes: unstaged worktree diff,
staged (``--cached``) diff, base..target ref comparison, and the
``unified`` context-line parameter.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_git_diff_unstaged_shows_readme(temp_git_repo, tool_context):
    from app.agent.tools.git_ops.git_diff_tool import git_diff_tool

    result = await git_diff_tool({}, tool_context)

    assert result["success"] is True
    assert result["stats"]["files_changed"] == 1

    files = result["files"]
    assert files[0]["path"] == "README.md"
    assert files[0]["old_path"] == "README.md"

    hunks = files[0]["hunks"]
    assert len(hunks) == 1
    hunk = hunks[0]
    assert hunk["old_start"] == 1
    assert hunk["new_start"] == 1

    # The modification appended an "Extra line." to README.md.
    addition_texts = [ln["text"] for ln in hunk["lines"] if ln["type"] == "addition"]
    assert "Extra line." in addition_texts

    # Ensure the stats count the single insertion correctly.
    assert result["stats"]["insertions"] >= 1

    # Raw diff text is exposed for agent fallback inspection.
    assert isinstance(result["raw"], str)
    assert "README.md" in result["raw"]


async def test_git_diff_staged_shows_new_file(temp_git_repo, tool_context):
    from app.agent.tools.git_ops.git_diff_tool import git_diff_tool

    result = await git_diff_tool({"staged": True}, tool_context)

    assert result["success"] is True
    files = result["files"]
    paths = {f["path"] for f in files}
    # Only src/staged.py was staged in the fixture.
    assert "src/staged.py" in paths
    assert "README.md" not in paths

    staged_file = next(f for f in files if f["path"] == "src/staged.py")
    additions = [
        ln["text"] for h in staged_file["hunks"] for ln in h["lines"] if ln["type"] == "addition"
    ]
    assert "STAGED = True" in additions


async def test_git_diff_staged_differs_from_unstaged(temp_git_repo, tool_context):
    from app.agent.tools.git_ops.git_diff_tool import git_diff_tool

    unstaged = await git_diff_tool({}, tool_context)
    staged = await git_diff_tool({"staged": True}, tool_context)

    unstaged_paths = {f["path"] for f in unstaged["files"]}
    staged_paths = {f["path"] for f in staged["files"]}

    # Disjoint: unstaged only has README.md, staged only has src/staged.py.
    assert unstaged_paths == {"README.md"}
    assert staged_paths == {"src/staged.py"}


async def test_git_diff_base_target_feature_branch(temp_git_repo, tool_context):
    from app.agent.tools.git_ops.git_diff_tool import git_diff_tool

    result = await git_diff_tool(
        {"base": "main", "target": "feature"},
        tool_context,
    )

    assert result["success"] is True
    # The feature branch added exactly one new file.
    files = result["files"]
    assert len(files) == 1
    feature_file = files[0]
    assert feature_file["path"] == "src/feature.py"

    additions = [
        ln["text"] for h in feature_file["hunks"] for ln in h["lines"] if ln["type"] == "addition"
    ]
    assert "def feature():" in additions


async def test_git_diff_unified_context_honored(temp_git_repo, tool_context):
    from app.agent.tools.git_ops.git_diff_tool import git_diff_tool

    # A large unified context asks git to emit as much context as possible.
    result = await git_diff_tool({"unified": 10}, tool_context)
    assert result["success"] is True

    # With -U10 and a README.md modification, the resulting hunk should
    # include the original file's lines as context entries.
    hunks = result["files"][0]["hunks"]
    context_texts = [ln["text"] for h in hunks for ln in h["lines"] if ln["type"] == "context"]
    # The README.md's first line is "# Test Repo"; it should show up as context.
    assert "# Test Repo" in context_texts
