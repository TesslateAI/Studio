"""
Integration tests for the ``grep`` navigation tool.

These tests shell out to ``rg`` via the real LocalOrchestrator. The entire
suite is skipped if ripgrep is not available on PATH.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from uuid import uuid4

import pytest

_ORCHESTRATOR_ROOT = Path(__file__).resolve().parents[4]
if str(_ORCHESTRATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_ORCHESTRATOR_ROOT))

from app.agent.tools.nav_ops.grep_tool import grep_tool  # noqa: E402
from app.services.orchestration import (  # noqa: E402
    DeploymentMode,
    LocalOrchestrator,
    OrchestratorFactory,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        shutil.which("rg") is None,
        reason="ripgrep (rg) is required for grep tool tests",
    ),
]


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture
def project_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))

    _write(
        tmp_path / "src" / "alpha.py",
        "def alpha():\n    return 'hello world'\n\n# TODO: refactor\n",
    )
    _write(
        tmp_path / "src" / "beta.py",
        "class Beta:\n    def greet(self):\n        return 'Hello, World!'\n",
    )
    _write(
        tmp_path / "src" / "gamma.ts",
        "export const greeting = 'hello world';\nexport function hi() { return 'HELLO'; }\n",
    )
    _write(
        tmp_path / "tests" / "test_alpha.py",
        "from src.alpha import alpha\n\ndef test_alpha():\n    assert alpha() == 'hello world'\n",
    )
    _write(
        tmp_path / "docs" / "README.md",
        "# Project\n\nThis project says hello world to everyone.\n",
    )
    # Multiline block used by the multiline regex test.
    _write(
        tmp_path / "src" / "multi.py",
        "def start():\n    x = 1\n    y = 2\n    return x + y\n",
    )
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


async def test_files_with_matches_default(bound_orchestrator, tool_context):
    result = await grep_tool({"pattern": "hello world"}, tool_context)
    assert result["success"] is True
    files = set(result["files"])
    assert any("alpha.py" in f for f in files)
    assert any("gamma.ts" in f for f in files)
    assert any("test_alpha.py" in f for f in files)


async def test_content_mode_with_context(bound_orchestrator, tool_context):
    result = await grep_tool(
        {
            "pattern": "hello world",
            "output_mode": "content",
            "-C": 1,
            "-n": True,
        },
        tool_context,
    )
    assert result["success"] is True
    assert "matches" in result
    assert len(result["matches"]) >= 1
    first = result["matches"][0]
    assert "path" in first
    assert "line_number" in first
    assert "line_text" in first
    # At least one match should carry context entries.
    has_context = any(("before_context" in m or "after_context" in m) for m in result["matches"])
    assert has_context


async def test_count_mode(bound_orchestrator, tool_context):
    result = await grep_tool(
        {"pattern": "hello world", "output_mode": "count"},
        tool_context,
    )
    assert result["success"] is True
    assert "counts" in result
    total = sum(result["counts"].values())
    assert total >= 3


async def test_case_insensitive(bound_orchestrator, tool_context):
    ci = await grep_tool(
        {"pattern": "hello", "-i": True, "output_mode": "count"},
        tool_context,
    )
    assert ci["success"] is True
    cs = await grep_tool(
        {"pattern": "HELLO", "output_mode": "count"},
        tool_context,
    )
    assert cs["success"] is True
    ci_total = sum(ci["counts"].values())
    cs_total = sum(cs["counts"].values())
    assert ci_total >= cs_total
    assert ci_total > cs_total  # case-insensitive picks up more hits


async def test_glob_filter(bound_orchestrator, tool_context):
    result = await grep_tool(
        {"pattern": "hello world", "glob": "*.ts"},
        tool_context,
    )
    assert result["success"] is True
    files = result["files"]
    assert all(f.endswith(".ts") for f in files)
    assert any("gamma.ts" in f for f in files)


async def test_head_limit_and_offset(bound_orchestrator, tool_context):
    # Ripgrep's output ordering is non-deterministic across runs (parallel
    # file scanning), so we assert slicing invariants rather than exact
    # paths. Count-mode returns a dict so we sidestep ordering entirely for
    # the totals check.
    full = await grep_tool({"pattern": "hello world"}, tool_context)
    assert full["success"] is True
    total = len(full["files"])
    assert total >= 3

    limited = await grep_tool(
        {"pattern": "hello world", "head_limit": 2},
        tool_context,
    )
    assert limited["success"] is True
    assert len(limited["files"]) == 2
    # Every returned file must be a real hit.
    assert set(limited["files"]).issubset(set(full["files"]))

    offset_page = await grep_tool(
        {"pattern": "hello world", "head_limit": 10, "offset": 1},
        tool_context,
    )
    assert offset_page["success"] is True
    # offset=1 must drop exactly one entry.
    assert len(offset_page["files"]) == total - 1
    assert set(offset_page["files"]).issubset(set(full["files"]))


async def test_multiline_regex(bound_orchestrator, tool_context):
    result = await grep_tool(
        {
            "pattern": r"def start\(\):.*return",
            "output_mode": "files_with_matches",
            "multiline": True,
        },
        tool_context,
    )
    assert result["success"] is True
    assert any("multi.py" in f for f in result["files"])


async def test_missing_pattern_errors(bound_orchestrator, tool_context):
    result = await grep_tool({}, tool_context)
    assert result["success"] is False
    assert "pattern" in result["message"].lower()


async def test_invalid_regex_errors(bound_orchestrator, tool_context):
    result = await grep_tool({"pattern": "(unclosed"}, tool_context)
    assert result["success"] is False
    assert "invalid" in result["message"].lower()
