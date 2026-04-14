"""
Integration tests for the ``glob`` navigation tool.

Each test sets ``PROJECT_ROOT`` to a temporary directory, wires the
``LocalOrchestrator`` into the orchestration factory cache, builds a
realistic file tree, and invokes the tool's executor. No mocking of
the orchestrator — every path is real I/O under ``tmp_path``.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from uuid import uuid4

import pytest

_ORCHESTRATOR_ROOT = Path(__file__).resolve().parents[4]
if str(_ORCHESTRATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_ORCHESTRATOR_ROOT))

from app.agent.tools.nav_ops.glob_tool import glob_tool  # noqa: E402
from app.services.orchestration import (  # noqa: E402
    DeploymentMode,
    LocalOrchestrator,
    OrchestratorFactory,
)

pytestmark = pytest.mark.asyncio


def _touch(path: Path, content: str = "", mtime: float | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


@pytest.fixture
def project_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Realistic mixed-language project under ``tmp_path``."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))

    # Python sources (mixed mtimes).
    now = time.time()
    _touch(tmp_path / "app" / "main.py", "print('hi')\n", mtime=now - 30)
    _touch(tmp_path / "app" / "utils.py", "def x():\n    pass\n", mtime=now - 20)
    _touch(tmp_path / "app" / "sub" / "helpers.py", "# helpers\n", mtime=now - 10)

    # TypeScript sources.
    _touch(tmp_path / "src" / "index.ts", "export const a = 1;\n", mtime=now - 40)
    _touch(tmp_path / "src" / "ui" / "App.tsx", "export default () => null;\n", mtime=now - 5)

    # Tests.
    _touch(tmp_path / "tests" / "test_main.py", "def test_a():\n    assert True\n")

    # Docs + README.
    _touch(tmp_path / "README.md", "# project\n")
    _touch(tmp_path / "docs" / "intro.md", "# intro\n")

    # Hidden file that should NOT appear unless include_hidden=True.
    _touch(tmp_path / ".hidden" / "secret.txt", "shh\n")

    # Files that should be excluded by the baseline tree exclusions.
    _touch(tmp_path / "node_modules" / "lib" / "index.js", "module.exports = {};\n")
    _touch(tmp_path / "dist" / "bundle.js", "// bundled\n")

    # A .gitignore excluding a specific file and a directory.
    _touch(tmp_path / ".gitignore", "ignored_file.py\nignored_dir/\n")
    _touch(tmp_path / "ignored_file.py", "# should be gitignored\n")
    _touch(tmp_path / "ignored_dir" / "inner.py", "# inside ignored_dir\n")

    return tmp_path


@pytest.fixture
def bound_orchestrator(project_tree: Path, monkeypatch: pytest.MonkeyPatch):
    """Install a LocalOrchestrator into the factory cache for this test."""
    monkeypatch.setenv("DEPLOYMENT_MODE", "local")
    OrchestratorFactory.clear_cache()
    orchestrator = LocalOrchestrator()
    # Seed the cache for every deployment mode so ``get_orchestrator`` returns
    # this instance regardless of which mode the current settings report.
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


async def test_simple_pattern_matches(bound_orchestrator, tool_context):
    result = await glob_tool({"pattern": "**/*.py"}, tool_context)
    assert result["success"] is True
    paths = [m["path"] for m in result["matches"]]
    assert "app/main.py" in paths
    assert "app/utils.py" in paths
    assert "app/sub/helpers.py" in paths
    assert "tests/test_main.py" in paths
    # Excluded by .gitignore:
    assert "ignored_file.py" not in paths
    assert not any(p.startswith("ignored_dir/") for p in paths)
    # Excluded by baseline tree exclusions:
    assert not any(p.startswith("node_modules/") for p in paths)


async def test_recursive_false_only_direct_children(bound_orchestrator, tool_context):
    result = await glob_tool(
        {"pattern": "*.py", "path": "app", "recursive": False},
        tool_context,
    )
    assert result["success"] is True
    paths = [m["path"] for m in result["matches"]]
    assert "app/main.py" in paths
    assert "app/utils.py" in paths
    # helpers.py lives one level deeper — must be excluded.
    assert "app/sub/helpers.py" not in paths


async def test_limit_honored(bound_orchestrator, tool_context):
    result = await glob_tool({"pattern": "**/*.py", "limit": 2}, tool_context)
    assert result["success"] is True
    assert len(result["matches"]) == 2
    assert result["truncated"] is True
    assert result["total_found"] >= 3


async def test_gitignore_respected(bound_orchestrator, tool_context):
    result = await glob_tool({"pattern": "**/*.py"}, tool_context)
    assert result["success"] is True
    paths = [m["path"] for m in result["matches"]]
    assert "ignored_file.py" not in paths
    assert not any(p.startswith("ignored_dir/") for p in paths)


async def test_sort_mtime_newest_first(bound_orchestrator, tool_context):
    result = await glob_tool(
        {"pattern": "**/*.py", "sort": "mtime"},
        tool_context,
    )
    assert result["success"] is True
    mtimes = [m["mtime"] for m in result["matches"]]
    assert mtimes == sorted(mtimes, reverse=True)


async def test_sort_name_alphabetical(bound_orchestrator, tool_context):
    result = await glob_tool(
        {"pattern": "**/*.py", "sort": "name"},
        tool_context,
    )
    assert result["success"] is True
    paths = [m["path"] for m in result["matches"]]
    assert paths == sorted(paths)


async def test_hidden_files_gated(bound_orchestrator, tool_context):
    hidden_off = await glob_tool({"pattern": "**/*.txt"}, tool_context)
    assert hidden_off["success"] is True
    assert all(not p["path"].startswith(".") for p in hidden_off["matches"])

    hidden_on = await glob_tool(
        {"pattern": "**/*.txt", "include_hidden": True},
        tool_context,
    )
    assert hidden_on["success"] is True
    paths_on = [m["path"] for m in hidden_on["matches"]]
    assert any(p.startswith(".hidden/") for p in paths_on)


async def test_no_matches_returns_success_with_empty_list(bound_orchestrator, tool_context):
    result = await glob_tool({"pattern": "**/*.nonexistentext"}, tool_context)
    assert result["success"] is True
    assert result["matches"] == []
    assert result["total_found"] == 0


async def test_missing_pattern_errors(bound_orchestrator, tool_context):
    result = await glob_tool({}, tool_context)
    assert result["success"] is False
    assert "pattern" in result["message"].lower()
