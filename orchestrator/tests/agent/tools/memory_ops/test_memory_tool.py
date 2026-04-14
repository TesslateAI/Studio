"""
Tests for persistent cross-session memory tools.

Covers MemoryStore round-trips, append/replace semantics, section ordering,
scope resolution, concurrent writes under file locking, atomic write
crash-safety, and the ``load_memory_prefix`` system-prompt helper.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from pathlib import Path

import pytest

from app.agent.tools.memory_ops import (
    MemoryStore,
    load_memory_prefix,
    memory_read_tool,
    memory_write_tool,
    register_memory_ops_tools,
)
from app.agent.tools.memory_ops import memory_tool as mod
from app.agent.tools.registry import ToolCategory, ToolRegistry

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def project_root(tmp_path, monkeypatch):
    """
    Isolated project root. Sets PROJECT_ROOT so MemoryStore's project
    scope writes into ``tmp_path/.tesslate/memory.md``.
    """
    root = tmp_path / "proj"
    root.mkdir()
    monkeypatch.setenv("PROJECT_ROOT", str(root))
    return root


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """Monkeypatched HOME for testing ``scope='global'`` in isolation."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    # Path.home() on POSIX honors HOME when set, but some environments
    # cache the result; patch expanduser for full safety.
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


@pytest.fixture
def store(project_root):
    return MemoryStore()


# =============================================================================
# 1. Read-nonexistent returns structured error
# =============================================================================


@pytest.mark.asyncio
async def test_read_nonexistent_returns_structured_error(project_root):
    result = await memory_read_tool({}, {})
    assert result["success"] is False
    assert result["exists"] is False
    assert result["scope"] == "project"
    assert "does not exist" in result["message"].lower()
    assert "suggestion" in result
    assert Path(result["path"]) == project_root / ".tesslate" / "memory.md"


@pytest.mark.asyncio
async def test_read_nonexistent_section_returns_structured_error(project_root, store):
    await store.write_section("project", "Alpha", "first section body")
    result = await memory_read_tool({"section": "MissingOne"}, {})
    assert result["success"] is False
    assert "MissingOne" in result["message"]
    assert result["section"] == "MissingOne"


# =============================================================================
# 2. Write a new section, read it back — round-trip
# =============================================================================


@pytest.mark.asyncio
async def test_write_then_read_roundtrip(project_root, store):
    await store.write_section("project", "Conventions", "Use snake_case for Python.")

    body = await store.read_section("project", "Conventions")
    assert body.strip() == "Use snake_case for Python."

    full = await store.read_section("project", None)
    assert "## Conventions" in full
    assert "Use snake_case for Python." in full

    # The on-disk file exists where we expect
    path = project_root / ".tesslate" / "memory.md"
    assert path.exists()
    assert path.read_text(encoding="utf-8").startswith("## Conventions\n")


# =============================================================================
# 3. Replace an existing section — body changes, others untouched
# =============================================================================


@pytest.mark.asyncio
async def test_replace_existing_section_preserves_others(project_root, store):
    await store.write_section("project", "Alpha", "alpha original")
    await store.write_section("project", "Beta", "beta original")
    await store.write_section("project", "Gamma", "gamma original")

    await store.write_section("project", "Beta", "beta replaced", mode="replace")

    assert (await store.read_section("project", "Alpha")).strip() == "alpha original"
    assert (await store.read_section("project", "Beta")).strip() == "beta replaced"
    assert (await store.read_section("project", "Gamma")).strip() == "gamma original"

    # Order preserved
    assert await store.list_sections("project") == ["Alpha", "Beta", "Gamma"]


# =============================================================================
# 4. Append to an existing section
# =============================================================================


@pytest.mark.asyncio
async def test_append_to_existing_section(project_root, store):
    await store.write_section("project", "Decisions", "First decision.")
    await store.write_section("project", "Decisions", "Second decision.", mode="append")

    body = await store.read_section("project", "Decisions")
    assert "First decision." in body
    assert "Second decision." in body
    # Separator is exactly one blank line
    assert "First decision.\n\nSecond decision." in body


@pytest.mark.asyncio
async def test_append_creates_section_when_missing(project_root, store):
    await store.write_section("project", "New", "initial body", mode="append")
    body = await store.read_section("project", "New")
    assert body.strip() == "initial body"


# =============================================================================
# 5. List sections in file order
# =============================================================================


@pytest.mark.asyncio
async def test_list_sections_preserves_file_order(project_root, store):
    for name in ("Zeta", "Alpha", "Mu"):
        await store.write_section("project", name, f"{name} body")
    assert await store.list_sections("project") == ["Zeta", "Alpha", "Mu"]


@pytest.mark.asyncio
async def test_list_sections_on_missing_file_is_empty(project_root, store):
    assert await store.list_sections("project") == []


# =============================================================================
# 6. Global vs project scope use different files
# =============================================================================


@pytest.mark.asyncio
async def test_global_and_project_scopes_are_separate(project_root, isolated_home, store):
    await store.write_section("project", "Topic", "project body")
    await store.write_section("global", "Topic", "global body")

    project_body = await store.read_section("project", "Topic")
    global_body = await store.read_section("global", "Topic")

    assert project_body.strip() == "project body"
    assert global_body.strip() == "global body"

    assert (project_root / ".tesslate" / "memory.md").exists()
    assert (isolated_home / ".tesslate" / "memory.md").exists()


@pytest.mark.asyncio
async def test_invalid_scope_raises(project_root):
    store = MemoryStore()
    with pytest.raises(ValueError):
        store.resolve_path("bogus")


# =============================================================================
# 7. Concurrent writes are serialized by the file lock
# =============================================================================


@pytest.mark.asyncio
async def test_concurrent_writes_do_not_corrupt(project_root, store):
    # Two concurrent writers, distinct sections — both must land in the file.
    await asyncio.gather(
        store.write_section("project", "One", "body one"),
        store.write_section("project", "Two", "body two"),
    )

    sections = await store.list_sections("project")
    assert sorted(sections) == ["One", "Two"]

    assert (await store.read_section("project", "One")).strip() == "body one"
    assert (await store.read_section("project", "Two")).strip() == "body two"


@pytest.mark.asyncio
async def test_concurrent_appends_to_same_section(project_root, store):
    # Seed the section so both appends have something to extend.
    await store.write_section("project", "Log", "initial")

    await asyncio.gather(
        store.write_section("project", "Log", "first append", mode="append"),
        store.write_section("project", "Log", "second append", mode="append"),
    )

    body = await store.read_section("project", "Log")
    assert "initial" in body
    assert "first append" in body
    assert "second append" in body


# =============================================================================
# 8. load_memory_prefix returns wrapped content or empty string
# =============================================================================


def test_load_memory_prefix_empty_when_missing(project_root):
    assert load_memory_prefix(project_root) == ""


@pytest.mark.asyncio
async def test_load_memory_prefix_wraps_existing_content(project_root, store):
    await store.write_section("project", "Conventions", "Never skip type hints.")

    prefix = load_memory_prefix(project_root)
    assert prefix.startswith("\n\n---\n## Persistent Memory\n\n")
    assert prefix.endswith("\n\n---\n")
    assert "## Conventions" in prefix
    assert "Never skip type hints." in prefix


def test_load_memory_prefix_handles_empty_file(project_root):
    (project_root / ".tesslate").mkdir(parents=True, exist_ok=True)
    (project_root / ".tesslate" / "memory.md").write_text("   \n", encoding="utf-8")
    assert load_memory_prefix(project_root) == ""


# =============================================================================
# 9. Atomic write: failure during os.replace leaves the original intact
# =============================================================================


@pytest.mark.asyncio
async def test_atomic_write_failure_preserves_original(project_root, store, monkeypatch):
    # Seed the file with known content.
    await store.write_section("project", "Stable", "original content")
    memory_path = project_root / ".tesslate" / "memory.md"
    original_text = memory_path.read_text(encoding="utf-8")

    # Monkeypatch os.replace inside the memory_tool module to fail exactly once,
    # then restore normal behavior so subsequent writes work again.
    real_replace = os.replace
    calls = {"n": 0}

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            # Clean up the tempfile ourselves so the test doesn't leak it;
            # the production finally-block also handles this.
            with contextlib.suppress(OSError):
                os.unlink(src)
            raise OSError("simulated disk failure")
        return real_replace(src, dst)

    monkeypatch.setattr(mod.os, "replace", flaky_replace)

    with pytest.raises(OSError, match="simulated disk failure"):
        await store.write_section("project", "Stable", "corrupted update")

    # Original file untouched
    assert memory_path.read_text(encoding="utf-8") == original_text

    # No stray temp files left behind
    stray = [p for p in (project_root / ".tesslate").iterdir() if p.name.startswith(".memory.md.")]
    # Allow the lock sidecar but nothing else that looks like a tempfile.
    for p in stray:
        assert not p.name.endswith(".tmp"), f"leftover tempfile: {p}"

    # Restore and verify a follow-up write succeeds end-to-end.
    monkeypatch.setattr(mod.os, "replace", real_replace)
    await store.write_section("project", "Stable", "recovered content")
    assert (await store.read_section("project", "Stable")).strip() == "recovered content"


# =============================================================================
# Registration smoke test
# =============================================================================


def test_register_memory_ops_tools_adds_both_tools():
    registry = ToolRegistry()
    register_memory_ops_tools(registry)

    read_tool = registry.get("memory_read")
    write_tool = registry.get("memory_write")

    assert read_tool is not None
    assert write_tool is not None
    assert read_tool.category == ToolCategory.MEMORY_OPS
    assert write_tool.category == ToolCategory.MEMORY_OPS
    assert "section" in write_tool.parameters["properties"]
    assert "body" in write_tool.parameters["properties"]


# =============================================================================
# Tool-layer smoke tests (exercise the async tool functions end-to-end)
# =============================================================================


@pytest.mark.asyncio
async def test_memory_write_tool_validation():
    result = await memory_write_tool({"section": "", "body": "x"}, {})
    assert result["success"] is False

    result = await memory_write_tool({"section": "A", "body": 42}, {})
    assert result["success"] is False

    result = await memory_write_tool({"section": "A", "body": "x", "mode": "wrong"}, {})
    assert result["success"] is False


@pytest.mark.asyncio
async def test_memory_tool_roundtrip_via_tool_layer(project_root):
    write_result = await memory_write_tool(
        {"section": "Ideas", "body": "Try FSM for state"},
        {},
    )
    assert write_result["success"] is True
    assert write_result["section"] == "Ideas"
    assert write_result["bytes_written"] == len(b"Try FSM for state")

    read_result = await memory_read_tool({"section": "Ideas"}, {})
    assert read_result["success"] is True
    assert "Try FSM for state" in read_result["content"]
    assert read_result["sections"] == ["Ideas"]


@pytest.mark.asyncio
async def test_context_project_root_fallback(tmp_path, monkeypatch):
    # Clear PROJECT_ROOT so the context fallback is exercised.
    monkeypatch.delenv("PROJECT_ROOT", raising=False)
    ctx_root = tmp_path / "ctx_project"
    ctx_root.mkdir()

    store = MemoryStore(context={"project_root": str(ctx_root)})
    await store.write_section("project", "From", "context")

    assert (ctx_root / ".tesslate" / "memory.md").exists()
