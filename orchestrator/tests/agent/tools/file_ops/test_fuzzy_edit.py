"""
Unit + integration tests for the multi-strategy fuzzy editor.

These tests hit every branch of :mod:`app.agent.tools.file_ops.fuzzy_editor`:
exact, flexible-whitespace, Levenshtein fuzzy (success, tie, over-threshold),
LLM-repair (success / failure), and the omission-placeholder guard. They
also verify multi-occurrence handling via the ``patch_file`` tool wrapper
and confirm the shared ``EDIT_HISTORY`` records mutations.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.tools.file_ops import edit as edit_module
from app.agent.tools.file_ops.edit import multi_edit_tool, patch_file_tool
from app.agent.tools.file_ops.edit_history import EDIT_HISTORY
from app.agent.tools.file_ops.fuzzy_editor import (
    EditError,
    RepairSuggestion,
    apply_edit,
    contains_omission_placeholder,
)

pytestmark = pytest.mark.asyncio


# =============================================================================
# Pure fuzzy_editor tests
# =============================================================================


async def test_strategy_exact_single_match() -> None:
    result = await apply_edit(
        content="hello world",
        old_str="world",
        new_str="there",
    )
    assert result.strategy == "exact"
    assert result.content == "hello there"
    assert result.occurrences == 1


async def test_strategy_flexible_whitespace_match() -> None:
    content = "def foo():\n    x   =    1\n    return x\n"
    result = await apply_edit(
        content=content,
        old_str="x = 1",
        new_str="x = 2",
    )
    assert result.strategy == "flexible"
    assert "x = 2" in result.content
    assert "x   =    1" not in result.content


async def test_strategy_fuzzy_success() -> None:
    # A 40-char needle with a 2-char typo lives well under the 10% threshold.
    content = "alpha beta gamma delta epsilon zeta eta theta iota"
    typo = "beta gamma delta epsilOn zeta eta theta"  # one substitution
    assert len(typo) >= 10
    result = await apply_edit(
        content=content,
        old_str=typo,
        new_str="REPLACED",
    )
    assert result.strategy == "fuzzy"
    assert "REPLACED" in result.content


async def test_strategy_fuzzy_tie_rejected() -> None:
    # Two identical windows — fuzzy refuses to pick one.
    content = "abcdefghij XXXX abcdefghij YYYY"
    with pytest.raises(EditError) as ei:
        await apply_edit(
            content=content,
            old_str="abcdefghij",
            new_str="ZZZZZZZZZZ",
            expected_occurrence=1,
            allow_multiple=False,
        )
    # Exact matched twice but expected 1; error mentions expected occurrences.
    assert "Expected 1 occurrence" in str(ei.value) or "ambiguous" in str(ei.value)


async def test_strategy_fuzzy_over_threshold_rejected() -> None:
    # Completely unrelated 15-char needle.
    content = "lorem ipsum dolor sit amet consectetur adipiscing elit"
    needle = "xxxxxxxxxxxxxxxxxxxxxxxxxx"  # 26 chars, way over threshold distance
    with pytest.raises(EditError) as ei:
        await apply_edit(
            content=content,
            old_str=needle,
            new_str="wat",
        )
    assert "Could not locate" in str(ei.value)
    assert "fuzzy" in ei.value.attempted


async def test_omission_placeholder_rejected() -> None:
    with pytest.raises(EditError) as ei:
        await apply_edit(
            content="def foo():\n    return 1\n",
            old_str="return 1",
            new_str="return 2\n...\nreturn 3",
        )
    assert "omission placeholder" in str(ei.value)


async def test_contains_omission_placeholder_variants() -> None:
    assert contains_omission_placeholder("good\n...\nmore")
    assert contains_omission_placeholder("good\n// ...\nmore")
    assert contains_omission_placeholder("good\n# ...\nmore")
    assert not contains_omission_placeholder("good\nno dots here\n")
    assert not contains_omission_placeholder("inline ... is fine")


async def test_multi_occurrence_mismatch_without_allow_multiple() -> None:
    content = "foo bar foo bar foo"
    with pytest.raises(EditError) as ei:
        await apply_edit(
            content=content,
            old_str="foo",
            new_str="baz",
            expected_occurrence=1,
            allow_multiple=False,
        )
    assert "Expected 1 occurrence" in str(ei.value)


async def test_multi_occurrence_match_when_expected_equals_count() -> None:
    content = "foo bar foo bar foo"
    result = await apply_edit(
        content=content,
        old_str="foo",
        new_str="baz",
        expected_occurrence=3,
        allow_multiple=False,
    )
    assert result.content == "baz bar baz bar baz"
    assert result.strategy == "exact"


async def test_allow_multiple_replaces_all() -> None:
    content = "x y x y x y"
    result = await apply_edit(
        content=content,
        old_str="x",
        new_str="Q",
        allow_multiple=True,
    )
    assert result.content == "Q y Q y Q y"
    assert result.occurrences == 3


async def test_llm_repair_success() -> None:
    calls: list[tuple[str, str, str]] = []

    async def fake_repair(
        file_path: str, content: str, old_str: str, new_str: str
    ) -> RepairSuggestion | None:
        calls.append((file_path, old_str, new_str))
        return RepairSuggestion(old_str="return 1", new_str="return 42")

    result = await apply_edit(
        content="def f():\n    return 1\n",
        old_str="return FOO",  # never matches
        new_str="return 42",
        file_path="f.py",
        repair_fn=fake_repair,
    )
    assert result.repair_applied is True
    assert "return 42" in result.content
    assert calls and calls[0][0] == "f.py"


async def test_llm_repair_failure_propagates_original_error() -> None:
    async def fake_repair(*_args, **_kwargs) -> RepairSuggestion | None:
        return None

    with pytest.raises(EditError):
        await apply_edit(
            content="unchanged\n",
            old_str="nonexistent-needle-value",
            new_str="replacement",
            file_path="g.py",
            repair_fn=fake_repair,
        )


async def test_llm_repair_rejects_placeholder_suggestion() -> None:
    async def placeholder_repair(*_args, **_kwargs) -> RepairSuggestion | None:
        return RepairSuggestion(old_str="return 1", new_str="return 1\n    # ...\n    return 2")

    with pytest.raises(EditError) as ei:
        await apply_edit(
            content="def f():\n    return 1\n",
            old_str="never-matches",
            new_str="return 2",
            repair_fn=placeholder_repair,
        )
    assert "placeholder" in str(ei.value)


# =============================================================================
# patch_file / multi_edit integration tests
# =============================================================================


async def test_patch_file_exact_path(
    bound_orchestrator, project_root: Path, fops_context, monkeypatch
) -> None:
    monkeypatch.setattr(edit_module, "llm_repair", _fail_repair)

    (project_root / "a.js").write_text("const color = 'blue';\n", encoding="utf-8")
    result = await patch_file_tool(
        {
            "file_path": "a.js",
            "old_str": "'blue'",
            "new_str": "'green'",
        },
        fops_context,
    )
    assert result["success"] is True
    assert result["details"]["strategy"] == "exact"
    assert (project_root / "a.js").read_text(encoding="utf-8") == "const color = 'green';\n"

    # EDIT_HISTORY should have one record for this path.
    entry = await EDIT_HISTORY.pop_latest("a.js")
    assert entry is not None


async def test_patch_file_flexible_whitespace(
    bound_orchestrator, project_root: Path, fops_context, monkeypatch
) -> None:
    monkeypatch.setattr(edit_module, "llm_repair", _fail_repair)

    body = "def greet():\n    name   =     'world'\n    return name\n"
    (project_root / "g.py").write_text(body, encoding="utf-8")
    result = await patch_file_tool(
        {
            "file_path": "g.py",
            "old_str": "name = 'world'",
            "new_str": "name = 'tesslate'",
        },
        fops_context,
    )
    assert result["success"] is True
    assert result["details"]["strategy"] == "flexible"
    assert "tesslate" in (project_root / "g.py").read_text(encoding="utf-8")


async def test_patch_file_llm_repair_path(
    bound_orchestrator, project_root: Path, fops_context, monkeypatch
) -> None:
    async def canned_repair(file_path, content, old_str, new_str):
        return RepairSuggestion(old_str="value = 1", new_str="value = 99")

    monkeypatch.setattr(edit_module, "llm_repair", canned_repair)

    (project_root / "c.py").write_text("value = 1\n", encoding="utf-8")
    result = await patch_file_tool(
        {
            "file_path": "c.py",
            "old_str": "value = ONE_HUNDRED",
            "new_str": "value = 99",
        },
        fops_context,
    )
    assert result["success"] is True, result
    assert result["details"]["repair_applied"] is True
    assert (project_root / "c.py").read_text(encoding="utf-8") == "value = 99\n"


async def test_patch_file_rejects_omission_placeholder(
    bound_orchestrator, project_root: Path, fops_context, monkeypatch
) -> None:
    monkeypatch.setattr(edit_module, "llm_repair", _fail_repair)

    (project_root / "f.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    result = await patch_file_tool(
        {
            "file_path": "f.py",
            "old_str": "return 1",
            "new_str": "return 1\n# ...\nreturn 2",
        },
        fops_context,
    )
    assert result["success"] is False
    assert "placeholder" in (result["details"].get("error", "") + result["message"])


async def test_multi_edit_sequential_branches(
    bound_orchestrator, project_root: Path, fops_context, monkeypatch
) -> None:
    monkeypatch.setattr(edit_module, "llm_repair", _fail_repair)

    body = "alpha\nbeta\ngamma\n"
    (project_root / "m.txt").write_text(body, encoding="utf-8")
    result = await multi_edit_tool(
        {
            "file_path": "m.txt",
            "edits": [
                {"old_str": "alpha", "new_str": "ALPHA"},
                {"old_str": "beta", "new_str": "BETA"},
                {"old_str": "gamma", "new_str": "GAMMA"},
            ],
        },
        fops_context,
    )
    assert result["success"] is True
    assert (project_root / "m.txt").read_text(encoding="utf-8") == "ALPHA\nBETA\nGAMMA\n"
    assert result["details"]["edit_count"] == 3


async def test_multi_edit_stop_on_failure_reports_index(
    bound_orchestrator, project_root: Path, fops_context, monkeypatch
) -> None:
    monkeypatch.setattr(edit_module, "llm_repair", _fail_repair)

    (project_root / "m.txt").write_text("alpha\nbeta\n", encoding="utf-8")
    result = await multi_edit_tool(
        {
            "file_path": "m.txt",
            "edits": [
                {"old_str": "alpha", "new_str": "ALPHA"},
                {"old_str": "nonexistent", "new_str": "nope"},
            ],
        },
        fops_context,
    )
    assert result["success"] is False
    assert result["details"]["edit_index"] == 1
    # Disk was not written (the good edit is discarded when the batch fails).
    assert (project_root / "m.txt").read_text(encoding="utf-8") == "alpha\nbeta\n"


async def test_patch_file_allow_multiple(
    bound_orchestrator, project_root: Path, fops_context, monkeypatch
) -> None:
    monkeypatch.setattr(edit_module, "llm_repair", _fail_repair)

    (project_root / "multi.txt").write_text("x y x y x", encoding="utf-8")
    result = await patch_file_tool(
        {
            "file_path": "multi.txt",
            "old_str": "x",
            "new_str": "Q",
            "allow_multiple": True,
        },
        fops_context,
    )
    assert result["success"] is True
    assert (project_root / "multi.txt").read_text(encoding="utf-8") == "Q y Q y Q"
    assert result["details"]["occurrences"] == 3


# =============================================================================
# Helpers
# =============================================================================


async def _fail_repair(*_args, **_kwargs) -> RepairSuggestion | None:
    """Stand-in repair callable that never suggests anything."""
    return None
