"""
Integration tests for the rewritten ``apply_patch`` tool.

Covers the structured create/update/delete/move format, validate-then-apply
two-phase commit, and rollback behavior when validation fails.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.tools.file_ops.apply_patch_tool import apply_patch_tool
from app.agent.tools.file_ops.edit_history import EDIT_HISTORY

pytestmark = pytest.mark.asyncio


async def test_apply_patch_create_update_delete_move(
    bound_orchestrator, project_root: Path, fops_context
) -> None:
    (project_root / "src").mkdir()
    (project_root / "src" / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    (project_root / "src" / "b.py").write_text("bbb\n", encoding="utf-8")
    (project_root / "src" / "c.py").write_text("ccc\n", encoding="utf-8")

    params = {
        "cwd": "",
        "changes": [
            {"op": "create", "path": "README.md", "content": "# Hello\n"},
            {
                "op": "update",
                "path": "src/a.py",
                "old_str": "return 1",
                "new_str": "return 42",
            },
            {"op": "delete", "path": "src/b.py"},
            {"op": "move", "from": "src/c.py", "to": "src/renamed.py"},
        ],
    }

    result = await apply_patch_tool(params, fops_context)

    assert result["success"] is True, result
    applied = result["details"]["applied"]
    assert len(applied) == 4
    assert (project_root / "README.md").read_text(encoding="utf-8") == "# Hello\n"
    assert "return 42" in (project_root / "src" / "a.py").read_text(encoding="utf-8")
    assert not (project_root / "src" / "b.py").exists()
    assert not (project_root / "src" / "c.py").exists()
    assert (project_root / "src" / "renamed.py").read_text(encoding="utf-8") == "ccc\n"


async def test_apply_patch_create_conflict_rolls_back_entire_batch(
    bound_orchestrator, project_root: Path, fops_context
) -> None:
    (project_root / "already.txt").write_text("existing", encoding="utf-8")

    params = {
        "cwd": "",
        "changes": [
            {"op": "create", "path": "new.txt", "content": "ok"},
            {"op": "create", "path": "already.txt", "content": "conflict"},
        ],
    }

    result = await apply_patch_tool(params, fops_context)

    assert result["success"] is False
    assert "validation failed" in result["message"]
    assert any("already exists" in e["error"] for e in result["details"]["errors"])

    # The first change must NOT have been written.
    assert not (project_root / "new.txt").exists()
    # And the pre-existing file must be untouched.
    assert (project_root / "already.txt").read_text(encoding="utf-8") == "existing"


async def test_apply_patch_update_missing_source_rolls_back(
    bound_orchestrator, project_root: Path, fops_context
) -> None:
    (project_root / "good.txt").write_text("alpha", encoding="utf-8")

    params = {
        "cwd": "",
        "changes": [
            {
                "op": "update",
                "path": "good.txt",
                "old_str": "alpha",
                "new_str": "beta",
            },
            {
                "op": "update",
                "path": "missing.txt",
                "old_str": "x",
                "new_str": "y",
            },
        ],
    }

    result = await apply_patch_tool(params, fops_context)
    assert result["success"] is False
    # No mutations hit disk.
    assert (project_root / "good.txt").read_text(encoding="utf-8") == "alpha"


async def test_apply_patch_resolves_cwd(
    bound_orchestrator, project_root: Path, fops_context
) -> None:
    (project_root / "pkg").mkdir()
    (project_root / "pkg" / "mod.py").write_text("x = 1\n", encoding="utf-8")

    params = {
        "cwd": "pkg",
        "changes": [
            {"op": "update", "path": "mod.py", "old_str": "x = 1", "new_str": "x = 2"},
        ],
    }

    result = await apply_patch_tool(params, fops_context)
    assert result["success"] is True
    assert (project_root / "pkg" / "mod.py").read_text(encoding="utf-8") == "x = 2\n"


async def test_apply_patch_escape_rejected(
    bound_orchestrator, project_root: Path, fops_context
) -> None:
    params = {
        "cwd": "",
        "changes": [
            {"op": "create", "path": "../escape.txt", "content": "nope"},
        ],
    }
    result = await apply_patch_tool(params, fops_context)
    assert result["success"] is False
    assert any("escapes project root" in e["error"] for e in result["details"]["errors"])


async def test_apply_patch_records_edit_history(
    bound_orchestrator, project_root: Path, fops_context
) -> None:
    (project_root / "x.txt").write_text("original\n", encoding="utf-8")

    params = {
        "cwd": "",
        "changes": [
            {
                "op": "update",
                "path": "x.txt",
                "old_str": "original",
                "new_str": "mutated",
            },
        ],
    }

    result = await apply_patch_tool(params, fops_context)
    assert result["success"] is True
    assert (project_root / "x.txt").read_text(encoding="utf-8") == "mutated\n"

    entry = await EDIT_HISTORY.pop_latest("x.txt")
    assert entry is not None
    assert entry.prev_content == "original\n"


async def test_apply_patch_requires_non_empty_changes(bound_orchestrator, fops_context) -> None:
    result = await apply_patch_tool({"cwd": "", "changes": []}, fops_context)
    assert result["success"] is False
    assert "non-empty" in result["message"]
