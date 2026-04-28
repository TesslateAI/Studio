"""
Persistent Cross-Session Memory Tools

Provides a markdown-backed persistent memory store that the agent can use
to retain knowledge, decisions, and context across sessions. Memory is
organized into H2 sections (``## Topic``) within a single ``memory.md``
file stored either inside the project (``scope="project"``) or in the
user's home directory (``scope="global"``).

Storage layout
--------------
- ``project`` scope -> ``<PROJECT_ROOT>/.tesslate/memory.md``
  where ``PROJECT_ROOT`` is read from the environment, falling back to
  ``context['project_root']`` when that is unset.
- ``global`` scope -> ``<HOME>/.tesslate/memory.md``

File format
-----------
GitHub-flavored markdown. Sections are delimited by ``## <topic>`` H2
headings. Any content before the first ``## `` heading is treated as a
preamble and is accessible under the empty section name ``""``.

Concurrency
-----------
All disk I/O is routed through ``asyncio.to_thread`` so that the event
loop is never blocked on filesystem operations. Writes take an exclusive
``fcntl.flock`` on the target file; reads take a shared lock. Writes are
additionally atomic: content is first written to a sibling tempfile and
then renamed into place with ``os.replace`` so that a crash mid-write can
never leave the memory file in a partially written state.
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from ..output_formatter import error_output, success_output
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)


# =============================================================================
# Path resolution
# =============================================================================

MEMORY_DIR_NAME = ".tesslate"
MEMORY_FILE_NAME = "memory.md"
MEMORY_PREFIX_HEADER = "## Persistent Memory"
H2_PATTERN = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def _resolve_project_root(context: dict[str, Any] | None = None) -> Path:
    """
    Resolve the project root for ``scope="project"``.

    Precedence:
      1. ``PROJECT_ROOT`` environment variable.
      2. ``context['project_root']`` when provided.
      3. Desktop mode: ``$OPENSAIL_HOME/projects/{slug}-{id}`` derived
         from ``context['project_slug']`` + ``context['project_id']``.
      4. Current working directory.
    """
    raw = os.environ.get("PROJECT_ROOT")
    if raw:
        return Path(raw).resolve()
    if context and context.get("project_root"):
        return Path(str(context["project_root"])).resolve()
    if context and context.get("project_id") and context.get("project_slug"):
        try:
            from ...config import get_settings

            settings = get_settings()
            if (settings.deployment_mode or "").lower() == "desktop":
                from ...services.desktop_paths import ensure_opensail_home

                home = ensure_opensail_home(settings.opensail_home or None)
                slug = context["project_slug"]
                pid = context["project_id"]
                return (home / "projects" / f"{slug}-{pid}").resolve()
        except Exception:
            pass
    return Path(os.getcwd()).resolve()


def _resolve_memory_path(scope: str, context: dict[str, Any] | None = None) -> Path:
    """
    Return the absolute path of the ``memory.md`` file for ``scope``.

    Args:
        scope: ``"project"`` or ``"global"``.
        context: Optional agent tool context used only for the
            ``project`` scope fallback.

    Raises:
        ValueError: If ``scope`` is not one of the allowed values.
    """
    if scope == "project":
        return _resolve_project_root(context) / MEMORY_DIR_NAME / MEMORY_FILE_NAME
    if scope == "global":
        return Path.home() / MEMORY_DIR_NAME / MEMORY_FILE_NAME
    raise ValueError(f"Unknown memory scope '{scope}'; expected 'project' or 'global'")


# =============================================================================
# Section parsing / serialization
# =============================================================================


def _parse_sections(text: str) -> list[tuple[str, str]]:
    """
    Parse ``text`` into an ordered list of ``(name, body)`` pairs.

    The preamble (content before the first ``## `` heading) is emitted as
    the leading pair with ``name == ""``. A file consisting solely of a
    preamble produces a single ``("", body)`` entry. Bodies are preserved
    verbatim, including their trailing newlines, so that round-tripping
    ``_serialize_sections(_parse_sections(x))`` is a no-op for any input.
    """
    matches = list(H2_PATTERN.finditer(text))
    sections: list[tuple[str, str]] = []

    if not matches:
        if text:
            sections.append(("", text))
        return sections

    first_start = matches[0].start()
    preamble = text[:first_start]
    if preamble:
        sections.append(("", preamble))

    for i, match in enumerate(matches):
        name = match.group(1).strip()
        body_start = match.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end]
        # Strip the single leading newline after the heading if present so
        # that stored bodies don't accumulate blank lines over round-trips.
        if body.startswith("\r\n"):
            body = body[2:]
        elif body.startswith("\n"):
            body = body[1:]
        sections.append((name, body))

    return sections


def _serialize_sections(sections: list[tuple[str, str]]) -> str:
    """
    Serialize an ordered list of ``(name, body)`` pairs back into
    markdown. The inverse of ``_parse_sections`` for well-formed input.
    """
    parts: list[str] = []
    for name, body in sections:
        if name == "":
            parts.append(body)
            continue
        heading = f"## {name}\n"
        if body == "":
            parts.append(heading)
        else:
            if not body.endswith("\n"):
                body = body + "\n"
            parts.append(f"{heading}{body}")
    return "".join(parts)


def _normalize_body(body: str) -> str:
    """
    Normalize a section body so it always ends with exactly one newline.
    Empty bodies are represented as ``""`` (not ``"\n"``).
    """
    if not body:
        return ""
    stripped = body.rstrip("\r\n")
    if not stripped:
        return ""
    return stripped + "\n"


# =============================================================================
# File locking (shared / exclusive) with sync I/O routed through a thread
# =============================================================================


class _LockedFile:
    """Context manager holding an fcntl lock on an open file object."""

    def __init__(self, path: Path, mode: str, lock_op: int):
        self._path = path
        self._mode = mode
        self._lock_op = lock_op
        self._fh = None

    def __enter__(self):
        # "x" (exclusive create) is not a real concept here — callers use
        # "r", "r+", "w" or "a".
        self._fh = open(self._path, self._mode, encoding="utf-8")
        try:
            fcntl.flock(self._fh.fileno(), self._lock_op)
        except OSError:
            self._fh.close()
            self._fh = None
            raise
        return self._fh

    def __exit__(self, exc_type, exc, tb):
        if self._fh is None:
            return False
        try:
            with contextlib.suppress(OSError):
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        finally:
            self._fh.close()
            self._fh = None
        return False


@contextlib.asynccontextmanager
async def _with_file_lock(path: Path, mode: str):
    """
    Async context manager yielding an open file object under a POSIX
    ``flock`` held for the duration of the ``with`` block. ``mode`` uses
    the standard Python file-mode strings; ``"r"`` takes a shared lock,
    anything else takes an exclusive lock.

    All blocking operations are dispatched to a worker thread so that the
    asyncio event loop remains responsive even under heavy contention.
    """
    lock_op = fcntl.LOCK_SH if mode == "r" else fcntl.LOCK_EX

    locked = _LockedFile(path, mode, lock_op)

    fh = await asyncio.to_thread(locked.__enter__)
    try:
        yield fh
    finally:
        await asyncio.to_thread(locked.__exit__, None, None, None)


# =============================================================================
# MemoryStore — the core persistence layer
# =============================================================================


class MemoryStore:
    """
    Async, section-aware, lock-safe markdown persistence for agent memory.

    The store is stateless; every method call re-resolves the target path
    based on ``scope`` so that environment / home-directory changes are
    picked up immediately. This makes the store cheap to instantiate and
    safe to reuse across test cases with monkeypatched paths.
    """

    def __init__(self, context: dict[str, Any] | None = None):
        self._context = context

    # ------------------------------------------------------------------ paths

    def resolve_path(self, scope: str) -> Path:
        """Return the on-disk path for the memory file at ``scope``."""
        return _resolve_memory_path(scope, self._context)

    # ------------------------------------------------------------------ read

    async def _read_file_locked(self, path: Path) -> str:
        """Read the entire memory file under a shared lock."""
        if not path.exists():
            raise FileNotFoundError(f"Memory file does not exist: {path}")

        async with _with_file_lock(path, "r") as fh:
            # ``fh.read`` is synchronous but we're already inside a thread-
            # dispatched lock manager; the read itself is small enough that
            # inlining it here does not meaningfully block the loop.
            return await asyncio.to_thread(fh.read)

    async def read_section(self, scope: str, section: str | None) -> str:
        """
        Return the body of a single section, or the full file when
        ``section is None``.

        Args:
            scope: ``"project"`` or ``"global"``.
            section: Section name to extract. When ``None``, returns the
                entire file. The empty string ``""`` selects the preamble
                (content before the first ``## `` heading).

        Raises:
            FileNotFoundError: If the file or the named section does not
                exist.
        """
        path = self.resolve_path(scope)
        content = await self._read_file_locked(path)

        if section is None:
            return content

        sections = _parse_sections(content)
        for name, body in sections:
            if name == section:
                return body

        raise FileNotFoundError(f"Section '{section}' not found in memory file {path}")

    async def list_sections(self, scope: str) -> list[str]:
        """
        Return the ordered list of ``## `` section names in the file.

        The preamble (if any) is not returned — this is a list of H2
        headings only. Returns an empty list if the file does not exist.
        """
        path = self.resolve_path(scope)
        if not path.exists():
            return []

        content = await self._read_file_locked(path)
        sections = _parse_sections(content)
        return [name for name, _ in sections if name != ""]

    # ------------------------------------------------------------------ write

    async def write_section(
        self,
        scope: str,
        section: str,
        body: str,
        mode: str = "replace",
    ) -> None:
        """
        Create or update a section in the memory file.

        Args:
            scope: ``"project"`` or ``"global"``.
            section: H2 heading name. Must be non-empty.
            body: New body content for the section.
            mode: ``"replace"`` overwrites the existing body; ``"append"``
                adds to the existing body, separated by exactly one blank
                line when the previous body was non-empty.

        Raises:
            ValueError: If ``section`` is empty or ``mode`` is invalid.
        """
        if not section or not section.strip():
            raise ValueError("section name must be a non-empty string")
        section = section.strip()
        if mode not in ("replace", "append"):
            raise ValueError(f"mode must be 'replace' or 'append', got {mode!r}")

        path = self.resolve_path(scope)
        parent = path.parent

        def _ensure_parent() -> None:
            parent.mkdir(parents=True, exist_ok=True)

        await asyncio.to_thread(_ensure_parent)

        async with _with_file_lock_for_write(path) as existing_text:
            sections = _parse_sections(existing_text)

            found = False
            for i, (name, current_body) in enumerate(sections):
                if name == section:
                    found = True
                    if mode == "replace":
                        new_body = _normalize_body(body)
                    else:  # append
                        base = current_body.rstrip("\r\n")
                        add = body.lstrip("\r\n")
                        combined = f"{base}\n\n{add}" if base and add else base + add
                        new_body = _normalize_body(combined)
                    sections[i] = (section, new_body)
                    break

            if not found:
                sections.append((section, _normalize_body(body)))

            new_text = _serialize_sections(sections)
            await _atomic_write(path, new_text)

        logger.info(
            "[MEMORY] write_section scope=%s section=%r mode=%s bytes=%d",
            scope,
            section,
            mode,
            len(body.encode("utf-8")),
        )


# =============================================================================
# Write-path helpers — kept module-level so they can be patched in tests
# =============================================================================


@contextlib.asynccontextmanager
async def _with_file_lock_for_write(path: Path):
    """
    Acquire an exclusive lock on ``path`` and yield its current text
    contents. Uses a sidecar lock file so that we can safely take the
    lock even when the target file does not yet exist.

    The sidecar is never removed — flock state on a dangling path is
    fine because all writers take it through the same location, and
    the sidecar itself is a few bytes.
    """
    parent = path.parent
    lock_path = parent / f".{path.name}.lock"

    def _open_lock():
        parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
        except OSError:
            os.close(fd)
            raise
        return fd

    def _read_existing() -> str:
        if not path.exists():
            return ""
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def _release(fd: int) -> None:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        with contextlib.suppress(OSError):
            os.close(fd)

    fd = await asyncio.to_thread(_open_lock)
    try:
        existing = await asyncio.to_thread(_read_existing)
        yield existing
    finally:
        await asyncio.to_thread(_release, fd)


async def _atomic_write(path: Path, content: str) -> None:
    """
    Atomically write ``content`` to ``path``.

    Uses ``tempfile.NamedTemporaryFile`` in the target directory followed
    by ``os.replace``. If ``os.replace`` raises, the temp file is cleaned
    up and the original file is guaranteed untouched.
    """

    def _do_write() -> None:
        parent = path.parent
        parent.mkdir(parents=True, exist_ok=True)

        tmp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=str(parent),
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as tmp:
                tmp.write(content)
                tmp.flush()
                os.fsync(tmp.fileno())
                tmp_path = tmp.name

            os.replace(tmp_path, str(path))
            tmp_path = None
        finally:
            if tmp_path is not None:
                with contextlib.suppress(OSError):
                    os.unlink(tmp_path)

    await asyncio.to_thread(_do_write)


# =============================================================================
# Module-level helper for agent system prompt injection
# =============================================================================


def load_memory_prefix(project_root: Path) -> str:
    """
    Synchronous helper used by the agent runner to inject persistent
    project memory into the system prompt at startup.

    Reads ``<project_root>/.tesslate/memory.md`` (if it exists) and
    returns the content wrapped in a ``## Persistent Memory`` banner
    bracketed by ``---`` horizontal rules. Returns an empty string if
    the file does not exist, is empty, or cannot be read.
    """
    try:
        path = Path(project_root) / MEMORY_DIR_NAME / MEMORY_FILE_NAME
    except TypeError:
        return ""

    if not path.exists() or not path.is_file():
        return ""

    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("[MEMORY] load_memory_prefix failed for %s: %s", path, exc)
        return ""

    stripped = content.strip()
    if not stripped:
        return ""

    return f"\n\n---\n{MEMORY_PREFIX_HEADER}\n\n{stripped}\n\n---\n"


# =============================================================================
# Agent-facing tools
# =============================================================================


async def memory_read_tool(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """
    Read persistent agent memory.

    Parameters
    ----------
    section : str, optional
        Section name to read. When omitted, the full file is returned.
    scope : {"project", "global"}, optional
        Which memory file to read. Defaults to ``"project"``.
    """
    scope = str(params.get("scope") or "project")
    section = params.get("section")
    if section is not None and not isinstance(section, str):
        return error_output(
            message="section must be a string when provided",
            suggestion="Pass a section name like 'Conventions' or omit it to read the whole file.",
        )

    try:
        store = MemoryStore(context=context)
        path = store.resolve_path(scope)
    except ValueError as exc:
        return error_output(
            message=str(exc),
            suggestion="Use scope='project' or scope='global'.",
        )

    try:
        content = await store.read_section(scope, section)
    except FileNotFoundError as exc:
        return error_output(
            message=str(exc),
            suggestion=(
                "Call memory_write to create the section, or omit the section "
                "argument to read the whole file."
            ),
            scope=scope,
            section=section,
            exists=False,
            path=str(path),
        )

    try:
        sections = await store.list_sections(scope)
    except FileNotFoundError:
        sections = []

    return success_output(
        message=(
            f"Read {len(content.encode('utf-8'))} bytes from memory "
            f"({'section=' + section if section else 'full file'}, scope={scope})"
        ),
        content=content,
        scope=scope,
        section=section,
        sections=sections,
        path=str(path),
    )


async def memory_write_tool(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """
    Create or update a section in persistent agent memory.

    Parameters
    ----------
    section : str
        H2 heading name. Required.
    body : str
        Section body content. Required.
    mode : {"replace", "append"}, optional
        ``replace`` overwrites the section body; ``append`` adds to it.
        Defaults to ``"replace"``.
    scope : {"project", "global"}, optional
        Which memory file to update. Defaults to ``"project"``.
    """
    section = params.get("section")
    body = params.get("body")
    mode = str(params.get("mode") or "replace")
    scope = str(params.get("scope") or "project")

    if not isinstance(section, str) or not section.strip():
        return error_output(
            message="section is required and must be a non-empty string",
            suggestion="Pass a short H2 heading name like 'Conventions' or 'Decisions'.",
        )
    if not isinstance(body, str):
        return error_output(
            message="body is required and must be a string",
            suggestion="Pass the section body as a string (markdown allowed).",
        )
    if mode not in ("replace", "append"):
        return error_output(
            message=f"mode must be 'replace' or 'append', got {mode!r}",
            suggestion="Use mode='replace' to overwrite or mode='append' to add to the existing body.",
        )

    try:
        store = MemoryStore(context=context)
        path = store.resolve_path(scope)
    except ValueError as exc:
        return error_output(
            message=str(exc),
            suggestion="Use scope='project' or scope='global'.",
        )

    try:
        await store.write_section(scope, section, body, mode=mode)
    except ValueError as exc:
        return error_output(message=str(exc))
    except OSError as exc:
        logger.error("[MEMORY] write failed for %s: %s", path, exc)
        return error_output(
            message=f"Failed to write memory section '{section}': {exc}",
            suggestion="Check that the parent directory is writable.",
        )

    return success_output(
        message=f"Saved memory section '{section}' ({mode}, scope={scope})",
        scope=scope,
        section=section,
        mode=mode,
        bytes_written=len(body.encode("utf-8")),
        path=str(path),
    )


# =============================================================================
# Tool registration
# =============================================================================


MEMORY_READ_PARAMS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "section": {
            "type": "string",
            "description": (
                "Optional section name (H2 heading) to read. Omit to return the entire memory file."
            ),
        },
        "scope": {
            "type": "string",
            "enum": ["project", "global"],
            "description": (
                "Which memory file to read. 'project' reads the current "
                "project's .tesslate/memory.md; 'global' reads the user-wide "
                "file in the home directory. Defaults to 'project'."
            ),
        },
    },
    "required": [],
}


MEMORY_WRITE_PARAMS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "section": {
            "type": "string",
            "description": (
                "Section name (H2 heading) to create or update. Use short, "
                "topical names like 'Conventions', 'Decisions', 'APIs'."
            ),
        },
        "body": {
            "type": "string",
            "description": "Markdown body content for the section.",
        },
        "mode": {
            "type": "string",
            "enum": ["replace", "append"],
            "description": (
                "'replace' overwrites the section body; 'append' adds to it "
                "with a blank-line separator. Defaults to 'replace'."
            ),
        },
        "scope": {
            "type": "string",
            "enum": ["project", "global"],
            "description": (
                "'project' writes to the current project's memory file; "
                "'global' writes to the user-wide file. Defaults to 'project'."
            ),
        },
    },
    "required": ["section", "body"],
}


def register_memory_ops_tools(registry) -> None:
    """Register the memory_read and memory_write tools on ``registry``."""

    registry.register(
        Tool(
            name="memory_read",
            description=(
                "Read persistent cross-session memory. Use this at the start "
                "of a task to recall conventions, decisions, and context that "
                "were saved in previous sessions. Returns the full memory.md "
                "file, or just a single section when 'section' is provided."
            ),
            parameters=MEMORY_READ_PARAMS,
            executor=memory_read_tool,
            category=ToolCategory.MEMORY_OPS,
            # Optional section/scope in, memory text dict out — JSON-clean.
            state_serializable=True,
            # Reads from a markdown file on disk; no in-memory cache.
            holds_external_state=False,
            examples=[
                '{"tool_name": "memory_read", "parameters": {}}',
                '{"tool_name": "memory_read", "parameters": {"section": "Conventions"}}',
                '{"tool_name": "memory_read", "parameters": {"scope": "global"}}',
            ],
        )
    )

    registry.register(
        Tool(
            name="memory_write",
            description=(
                "Save a fact, convention, decision, or reusable snippet to "
                "persistent memory so future sessions can recall it. Memory "
                "is organized into H2 sections inside a markdown file; "
                "choose a short topical section name. Use mode='append' to "
                "add to an existing section without losing prior content."
            ),
            parameters=MEMORY_WRITE_PARAMS,
            executor=memory_write_tool,
            category=ToolCategory.MEMORY_OPS,
            # Section + body in, success dict out — JSON-clean.
            state_serializable=True,
            # Atomic markdown file write; no persistent state.
            holds_external_state=False,
            examples=[
                (
                    '{"tool_name": "memory_write", "parameters": '
                    '{"section": "Conventions", "body": "- Use pytest fixtures for DB setup."}}'
                ),
                (
                    '{"tool_name": "memory_write", "parameters": '
                    '{"section": "Decisions", "body": "Picked Redis Streams over Kafka.", '
                    '"mode": "append"}}'
                ),
                (
                    '{"tool_name": "memory_write", "parameters": '
                    '{"section": "Shortcuts", "body": "- uv run pytest -x", "scope": "global"}}'
                ),
            ],
        )
    )

    logger.info("Registered 2 memory operation tools")
