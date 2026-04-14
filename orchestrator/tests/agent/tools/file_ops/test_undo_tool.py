"""
Integration tests for the ``file_undo`` tool.

Each test sets up a real :class:`LocalOrchestrator` bound to a
``tmp_path`` project root and records mutations in the shared
``EDIT_HISTORY`` buffer so the tool has something to walk back.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.tools.file_ops.edit_history import EDIT_HISTORY
from app.agent.tools.file_ops.undo_tool import file_undo_tool

pytestmark = pytest.mark.asyncio


async def test_undo_restores_previous_content(
    bound_orchestrator, project_root: Path, fops_context
) -> None:
    target = project_root / "hello.txt"
    target.write_text("current", encoding="utf-8")

    await EDIT_HISTORY.record("hello.txt", "previous", "edit")

    result = await file_undo_tool({"file_path": "hello.txt"}, fops_context)

    assert result["success"] is True
    assert target.read_text(encoding="utf-8") == "previous"


async def test_undo_deletes_file_that_did_not_exist(
    bound_orchestrator, project_root: Path, fops_context
) -> None:
    target = project_root / "fresh.txt"
    target.write_text("brand new", encoding="utf-8")

    # prev_content=None means the file did not exist before the mutation.
    await EDIT_HISTORY.record("fresh.txt", None, "write")

    result = await file_undo_tool({"file_path": "fresh.txt"}, fops_context)

    assert result["success"] is True
    assert result["details"]["action"] == "delete"
    assert not target.exists()


async def test_undo_with_empty_history_errors(bound_orchestrator, fops_context) -> None:
    result = await file_undo_tool({"file_path": "nothing.txt"}, fops_context)

    assert result["success"] is False
    assert "Nothing to undo" in result["message"]


async def test_undo_missing_parameter(fops_context) -> None:
    with pytest.raises(ValueError, match="file_path parameter is required"):
        await file_undo_tool({}, fops_context)


async def test_undo_only_pops_once(bound_orchestrator, project_root: Path, fops_context) -> None:
    target = project_root / "layers.txt"
    target.write_text("v3", encoding="utf-8")

    await EDIT_HISTORY.record("layers.txt", "v1", "edit")
    await EDIT_HISTORY.record("layers.txt", "v2", "edit")

    first = await file_undo_tool({"file_path": "layers.txt"}, fops_context)
    assert first["success"] is True
    assert target.read_text(encoding="utf-8") == "v2"

    second = await file_undo_tool({"file_path": "layers.txt"}, fops_context)
    assert second["success"] is True
    assert target.read_text(encoding="utf-8") == "v1"

    third = await file_undo_tool({"file_path": "layers.txt"}, fops_context)
    assert third["success"] is False
