"""
Unit tests for LocalOrchestrator and PtySessionRegistry.

These tests exercise the filesystem + subprocess backend against a
real temp directory. They do not require Docker, Kubernetes, Redis,
Postgres, or any external service — every path is real I/O under
``tmp_path``.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from uuid import uuid4

import pytest

# Ensure the orchestrator package is importable.
_ORCHESTRATOR_ROOT = Path(__file__).resolve().parents[3]
if str(_ORCHESTRATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(_ORCHESTRATOR_ROOT))

from app.services.orchestration import (  # noqa: E402
    PTY_SESSIONS,
    DeploymentMode,
    LocalOrchestrator,
    PtySessionRegistry,
)

pytestmark = pytest.mark.asyncio


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def project_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point PROJECT_ROOT at an isolated tmp_path for each test."""
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    return tmp_path


@pytest.fixture
def orchestrator(project_root: Path) -> LocalOrchestrator:
    """Fresh LocalOrchestrator bound to the per-test temp root."""
    return LocalOrchestrator()


@pytest.fixture
def identity() -> tuple:
    """Dummy user/project/container identifiers — all ignored by LocalOrchestrator."""
    return (uuid4(), uuid4(), "main")


# =============================================================================
# deployment_mode / construction
# =============================================================================


async def test_deployment_mode_is_local(orchestrator: LocalOrchestrator) -> None:
    assert orchestrator.deployment_mode == DeploymentMode.LOCAL
    assert orchestrator.deployment_mode.is_local is True
    assert orchestrator.deployment_mode.is_docker is False
    assert orchestrator.deployment_mode.is_kubernetes is False


async def test_root_reflects_env(orchestrator: LocalOrchestrator, project_root: Path) -> None:
    assert orchestrator.root == project_root.resolve()


# =============================================================================
# File operations
# =============================================================================


async def test_read_file_roundtrip(
    orchestrator: LocalOrchestrator, project_root: Path, identity
) -> None:
    user_id, project_id, container = identity
    target = project_root / "hello.txt"
    target.write_text("hello world", encoding="utf-8")

    result = await orchestrator.read_file(user_id, project_id, container, "hello.txt")
    assert result == "hello world"


async def test_read_file_missing_returns_none(orchestrator: LocalOrchestrator, identity) -> None:
    user_id, project_id, container = identity
    assert await orchestrator.read_file(user_id, project_id, container, "missing.txt") is None


async def test_write_file_creates_parents_and_is_atomic(
    orchestrator: LocalOrchestrator, project_root: Path, identity
) -> None:
    user_id, project_id, container = identity

    ok = await orchestrator.write_file(
        user_id,
        project_id,
        container,
        "nested/dir/output.txt",
        "payload-contents",
    )
    assert ok is True

    target = project_root / "nested" / "dir" / "output.txt"
    assert target.exists()
    assert target.read_text(encoding="utf-8") == "payload-contents"

    # No stray temp files should remain.
    leftovers = [p.name for p in (project_root / "nested" / "dir").iterdir()]
    assert leftovers == ["output.txt"]


async def test_write_file_preserves_mode(
    orchestrator: LocalOrchestrator, project_root: Path, identity
) -> None:
    user_id, project_id, container = identity
    existing = project_root / "script.sh"
    existing.write_text("echo a", encoding="utf-8")
    os.chmod(existing, 0o750)

    ok = await orchestrator.write_file(user_id, project_id, container, "script.sh", "echo b")
    assert ok is True
    assert existing.read_text(encoding="utf-8") == "echo b"
    assert (existing.stat().st_mode & 0o777) == 0o750


async def test_delete_file_removes_and_returns_false_when_missing(
    orchestrator: LocalOrchestrator, project_root: Path, identity
) -> None:
    user_id, project_id, container = identity
    target = project_root / "drop.txt"
    target.write_text("x", encoding="utf-8")

    assert await orchestrator.delete_file(user_id, project_id, container, "drop.txt") is True
    assert not target.exists()

    assert await orchestrator.delete_file(user_id, project_id, container, "drop.txt") is False


async def test_list_files_sorted_with_metadata(
    orchestrator: LocalOrchestrator, project_root: Path, identity
) -> None:
    user_id, project_id, container = identity
    (project_root / "a.txt").write_text("aaa", encoding="utf-8")
    (project_root / "b.txt").write_text("bb", encoding="utf-8")
    (project_root / "sub").mkdir()
    (project_root / ".hidden").write_text("nope", encoding="utf-8")

    entries = await orchestrator.list_files(user_id, project_id, container, ".")
    names = [e["name"] for e in entries]

    assert names == ["a.txt", "b.txt", "sub"]
    by_name = {e["name"]: e for e in entries}
    assert by_name["a.txt"]["type"] == "file"
    assert by_name["a.txt"]["size"] == 3
    assert by_name["a.txt"]["path"] == "a.txt"
    assert by_name["sub"]["type"] == "directory"
    assert by_name["sub"]["size"] == 0


async def test_list_tree_excludes_standard_dirs(
    orchestrator: LocalOrchestrator, project_root: Path, identity
) -> None:
    user_id, project_id, container = identity

    (project_root / "src").mkdir()
    (project_root / "src" / "main.py").write_text("print('hi')", encoding="utf-8")

    (project_root / "node_modules").mkdir()
    (project_root / "node_modules" / "junk.js").write_text("x", encoding="utf-8")

    (project_root / ".git").mkdir()
    (project_root / ".git" / "HEAD").write_text("ref", encoding="utf-8")

    (project_root / "__pycache__").mkdir()
    (project_root / "__pycache__" / "x.pyc").write_bytes(b"\x00\x01")

    entries = await orchestrator.list_tree(user_id, project_id, container)
    paths = {e["path"] for e in entries}

    assert any("main.py" in p for p in paths)
    assert not any("node_modules" in p for p in paths)
    assert not any(".git" in p for p in paths)
    assert not any("__pycache__" in p for p in paths)


# =============================================================================
# Shell execution
# =============================================================================


async def test_execute_command_echo(orchestrator: LocalOrchestrator, identity) -> None:
    user_id, project_id, container = identity
    output = await orchestrator.execute_command(user_id, project_id, container, ["echo", "hello"])
    assert "hello" in output


async def test_execute_command_timeout_kills_process(
    orchestrator: LocalOrchestrator, identity
) -> None:
    user_id, project_id, container = identity
    with pytest.raises(RuntimeError) as exc_info:
        await orchestrator.execute_command(
            user_id,
            project_id,
            container,
            ["sleep", "5"],
            timeout=1,
        )
    assert "timed out" in str(exc_info.value).lower()


# =============================================================================
# Path-escape safety
# =============================================================================


async def test_read_file_refuses_path_escape(
    orchestrator: LocalOrchestrator, project_root: Path, identity, tmp_path: Path
) -> None:
    user_id, project_id, container = identity

    # Create an outside file we must never be able to read.
    outside = tmp_path.parent / f"outside-{uuid4().hex}.txt"
    outside.write_text("SECRET", encoding="utf-8")
    try:
        result = await orchestrator.read_file(
            user_id,
            project_id,
            container,
            "../../../etc/passwd",
        )
        # Should be refused — never leak anything outside the root.
        assert result is None

        # And also refuse a direct breakout into the sibling temp file.
        rel = os.path.relpath(outside, project_root)
        result2 = await orchestrator.read_file(user_id, project_id, container, rel)
        assert result2 is None or "SECRET" not in result2
    finally:
        if outside.exists():
            outside.unlink()


# =============================================================================
# Misc interface
# =============================================================================


async def test_is_container_ready_always_true(orchestrator: LocalOrchestrator, identity) -> None:
    user_id, project_id, container = identity
    result = await orchestrator.is_container_ready(user_id, project_id, container)
    assert result["ready"] is True
    assert result["mode"] == "local"


async def test_stream_logs_yields_at_least_one_line(
    orchestrator: LocalOrchestrator, identity
) -> None:
    user_id, project_id, _ = identity
    chunks: list[str] = []
    async for line in orchestrator.stream_logs(project_id, user_id):
        chunks.append(line)
    assert chunks  # non-empty
    assert all(isinstance(c, str) for c in chunks)


# =============================================================================
# PtySessionRegistry
# =============================================================================


async def test_pty_session_roundtrip(project_root: Path) -> None:
    # Skip if ptyprocess isn't importable — surfaced as a clear xfail rather
    # than a crash during collection.
    pytest.importorskip("ptyprocess")

    registry = PtySessionRegistry()
    session_id = registry.create(["cat"], cwd=str(project_root))
    try:
        # Give the drain task a tick to attach.
        await asyncio.sleep(0.1)

        registry.write(session_id, "hello\n")

        # Wait for the echo to arrive, with a bounded poll loop.
        collected = bytearray()
        for _ in range(50):
            chunk = registry.read(session_id)
            if chunk:
                collected.extend(chunk)
                if b"hello" in collected:
                    break
            await asyncio.sleep(0.05)

        assert b"hello" in collected

        snapshot = registry.status(session_id)
        assert snapshot["status"] == "running"
        assert snapshot["command"] == "cat"
        assert snapshot["pid"] > 0

        listing = registry.list()
        assert any(entry["session_id"] == session_id for entry in listing)
    finally:
        registry.close(session_id)

    # After close, status should raise KeyError.
    with pytest.raises(KeyError):
        registry.status(session_id)


async def test_pty_sessions_singleton_exists() -> None:
    assert isinstance(PTY_SESSIONS, PtySessionRegistry)
