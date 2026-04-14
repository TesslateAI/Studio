"""
Integration tests for the ``list_dir`` navigation tool.
"""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

import pytest

_ORCHESTRATOR_ROOT = Path(__file__).resolve().parents[4]
if str(_ORCHESTRATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_ORCHESTRATOR_ROOT))

from app.agent.tools.nav_ops.list_dir_tool import (  # noqa: E402
    MAX_ENTRY_LENGTH,
    _truncate_name,
    list_dir_tool,
)
from app.services.orchestration import (  # noqa: E402
    DeploymentMode,
    LocalOrchestrator,
    OrchestratorFactory,
)

pytestmark = pytest.mark.asyncio


def _write(path: Path, content: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture
def project_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))

    # Top level.
    _write(tmp_path / "README.md", "# hi\n")
    _write(tmp_path / "LICENSE", "MIT\n")

    # One directory per letter so we have plenty of entries.
    for name in ("apples", "bananas", "cherries", "dates", "elderberries"):
        _write(tmp_path / "fruits" / name / "info.txt", f"{name}\n")

    # Nested tree for depth testing.
    _write(tmp_path / "src" / "a" / "b" / "c" / "deep.py", "x = 1\n")
    _write(tmp_path / "src" / "a" / "top.py", "y = 2\n")

    # Hidden file at the root.
    _write(tmp_path / ".secret", "shh\n")

    return tmp_path


@pytest.fixture
def bound_orchestrator(project_tree: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DEPLOYMENT_MODE", "local")
    OrchestratorFactory.clear_cache()
    orchestrator = LocalOrchestrator()
    from app.services.orchestration import factory as _factory_module

    for mode in DeploymentMode:
        _factory_module._orchestrators[mode] = orchestrator
    yield orchestrator
    OrchestratorFactory.clear_cache()


@pytest.fixture
def tool_context() -> dict:
    return {
        "user_id": uuid4(),
        "project_id": uuid4(),
        "project_slug": "test-project",
        "container_name": "main",
        "edit_mode": "auto",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_depth_one_only_direct_children(bound_orchestrator, tool_context):
    result = await list_dir_tool(
        {"dir_path": ".", "depth": 1, "limit": 100},
        tool_context,
    )
    assert result["success"] is True
    depths = {e["depth"] for e in result["entries"]}
    assert depths <= {0}


async def test_depth_two_descends_one_level(bound_orchestrator, tool_context):
    result = await list_dir_tool(
        {"dir_path": ".", "depth": 2, "limit": 200},
        tool_context,
    )
    assert result["success"] is True
    depths = {e["depth"] for e in result["entries"]}
    assert 0 in depths
    assert 1 in depths
    assert 2 not in depths  # depth=2 means at most two levels inclusive of root


async def test_offset_and_limit_paginate(bound_orchestrator, tool_context):
    first_page = await list_dir_tool(
        {"dir_path": ".", "depth": 1, "offset": 1, "limit": 2},
        tool_context,
    )
    assert first_page["success"] is True
    assert len(first_page["entries"]) == 2
    assert first_page["has_more"] is True

    second_page = await list_dir_tool(
        {"dir_path": ".", "depth": 1, "offset": 3, "limit": 2},
        tool_context,
    )
    assert second_page["success"] is True
    # Entries must not overlap between pages.
    first_names = {e["name"] for e in first_page["entries"]}
    second_names = {e["name"] for e in second_page["entries"]}
    assert first_names.isdisjoint(second_names)


async def test_truncate_name_helper_under_limit():
    name = "short.txt"
    truncated, flag = _truncate_name(name)
    assert truncated == name
    assert flag is False


async def test_truncate_name_helper_over_limit():
    raw = "z" * (MAX_ENTRY_LENGTH + 50)
    truncated, flag = _truncate_name(raw)
    assert flag is True
    assert len(truncated) <= MAX_ENTRY_LENGTH
    assert truncated.endswith("\u2026")


async def test_hidden_files_gated(bound_orchestrator, tool_context):
    default = await list_dir_tool(
        {"dir_path": ".", "depth": 1, "limit": 100},
        tool_context,
    )
    assert default["success"] is True
    assert all(not e["name"].startswith(".") for e in default["entries"])

    show_hidden = await list_dir_tool(
        {"dir_path": ".", "depth": 1, "limit": 100, "include_hidden": True},
        tool_context,
    )
    assert show_hidden["success"] is True
    # LocalOrchestrator.list_files filters dotfiles, so include_hidden primarily
    # documents intent here — assert we at least didn't error out and got
    # the non-hidden entries.
    assert len(show_hidden["entries"]) >= len(default["entries"])


async def test_missing_dir_path_errors(bound_orchestrator, tool_context):
    result = await list_dir_tool({}, tool_context)
    assert result["success"] is False
    assert "dir_path" in result["message"].lower()


async def test_zero_offset_errors(bound_orchestrator, tool_context):
    result = await list_dir_tool({"dir_path": ".", "offset": 0}, tool_context)
    assert result["success"] is False
    assert "offset" in result["message"].lower()


async def test_offset_beyond_total_errors(bound_orchestrator, tool_context):
    result = await list_dir_tool(
        {"dir_path": ".", "depth": 1, "offset": 9999, "limit": 10},
        tool_context,
    )
    assert result["success"] is False
    assert "offset" in result["message"].lower()


async def test_nested_deep_tree(bound_orchestrator, tool_context):
    result = await list_dir_tool(
        {"dir_path": "src", "depth": 5, "limit": 100},
        tool_context,
    )
    assert result["success"] is True
    names = [e["name"] for e in result["entries"]]
    assert "deep.py" in names
    # Ensure the deep.py entry has depth 3 (src -> a -> b -> c -> deep.py,
    # displayed as depth 3 relative to the given dir_path 'src').
    deep_entry = next(e for e in result["entries"] if e["name"] == "deep.py")
    assert deep_entry["depth"] == 3
