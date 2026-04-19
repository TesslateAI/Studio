"""
Local Orchestrator

Filesystem + subprocess orchestration backend for environments where the
agent runs directly against the host machine, with no container isolation.

This backend reinterprets the project/container-centric BaseOrchestrator
interface as follows:

    - A single "project root" directory is taken from the ``PROJECT_ROOT``
      environment variable (falling back to ``os.getcwd()`` when unset).
    - ``project_slug`` / ``project_id`` / ``container_name`` / ``volume_id``
      / ``cache_node`` are all ignored for path resolution. They are still
      logged for debugging parity with the Docker and Kubernetes backends.
    - ``subdir`` is honored — when provided, paths resolve under
      ``<root>/<subdir>/`` instead of ``<root>/``.
    - All resolved paths are post-symlink verified to live inside the root.
      Any attempt to escape the root is refused.

This orchestrator is intended for benchmark / sandbox scenarios (e.g. the
agent running inside a pre-provisioned environment like Terminal Bench)
where container orchestration is unavailable or unnecessary.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import tempfile
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from .base import BaseOrchestrator
from .deployment_mode import DeploymentMode

logger = logging.getLogger(__name__)

# Directories to skip when walking the filesystem in list_tree.
EXCLUDED_TREE_DIRS: frozenset[str] = frozenset(
    {
        "node_modules",
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        "dist",
        "build",
        ".next",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "target",
    }
)


def _get_project_root(project: Any | None = None) -> Path:
    """
    Resolve the local project root.

    Resolution order:

    1. If a ``project`` row is supplied AND the app is running under
       ``DEPLOYMENT_MODE=desktop``, the root is
       ``$TESSLATE_STUDIO_HOME/projects/{slug}-{id}`` so multi-project
       desktop shells can host many projects simultaneously. The directory
       is NOT created here — the importer / setup path is responsible for
       materializing it.
    2. ``$PROJECT_ROOT`` env var (legacy single-project / benchmark mode).
    3. ``os.getcwd()`` as a final fallback.

    Args:
        project: Optional SQLAlchemy ``Project`` row. When provided under
            desktop mode, its ``slug`` and ``id`` are used to form a
            per-project directory. Ignored otherwise.

    Returns:
        Absolute, resolved Path pointing at the project root.
    """
    if project is not None:
        try:
            from ...config import get_settings

            settings = get_settings()
            if settings.deployment_mode.lower() == "desktop":
                from ..desktop_paths import ensure_studio_home

                home = ensure_studio_home(settings.tesslate_studio_home or None)
                slug = getattr(project, "slug", None) or "project"
                pid = getattr(project, "id", None)
                dir_name = f"{slug}-{pid}" if pid is not None else slug
                return (home / "projects" / dir_name).resolve()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("[LOCAL] per-project root resolution failed: %s", exc)

    raw = os.environ.get("PROJECT_ROOT") or os.getcwd()
    return Path(raw).resolve()


def _safe_resolve(root: Path, rel: str | None, subdir: str | None = None) -> Path:
    """
    Resolve ``rel`` beneath ``root`` (optionally under ``subdir``) with strict
    containment checking.

    Args:
        root: Absolute project root (already resolved).
        rel: Relative path inside the project. ``None`` and ``""`` both map
            to the root itself.
        subdir: Optional subdirectory beneath the root.

    Returns:
        Absolute, resolved path guaranteed to live inside ``root``.

    Raises:
        PermissionError: If the resolved path escapes ``root``.
    """
    base = root
    if subdir:
        base = (root / subdir).resolve()
        # Containment check for the subdir itself.
        try:
            base.relative_to(root)
        except ValueError as exc:
            raise PermissionError(f"[LOCAL] subdir '{subdir}' escapes project root {root}") from exc

    candidate = base if not rel or rel in (".", "./") else (base / rel)
    # resolve() collapses .. and symlinks; we verify containment after.
    resolved = candidate.resolve()

    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PermissionError(
            f"[LOCAL] path '{rel}' (under subdir='{subdir}') escapes project root {root}"
        ) from exc

    return resolved


# =============================================================================
# PTY SESSION REGISTRY
# =============================================================================


class PtySessionRegistry:
    """
    In-memory registry of interactive PTY-backed subprocess sessions.

    Each session wraps a ``ptyprocess.PtyProcess`` spawned in its own
    process group. A background asyncio task continuously drains the PTY
    master into an in-memory byte buffer so that callers can poll for
    output without blocking on the read side.

    This is the foundation for later interactive shell tooling — it is
    implemented here so LocalOrchestrator and any future shell-ops agent
    tool share a single source of truth for session lifecycle.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    def create(
        self,
        command: list[str] | str,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        run_id: str | None = None,
    ) -> str:
        """
        Spawn a new PTY-backed session and start draining its output.

        Args:
            command: Command to execute. Either a list (argv form) or a
                single string (run via ``/bin/sh -c``).
            cwd: Working directory for the spawned process.
            env: Environment overrides. When ``None``, the current
                process environment is inherited.
            run_id: Optional invocation identifier used by background
                tools to scope a session to the tool call that created
                it.

        Returns:
            The session identifier (uuid4 hex) — use it for subsequent
            ``read`` / ``write`` / ``status`` / ``close`` calls.
        """
        import ptyprocess  # Imported lazily so test collection never pulls it in.

        if isinstance(command, str):
            argv = ["/bin/sh", "-c", command]
            display = command
        else:
            argv = list(command)
            display = " ".join(argv)

        spawn_env = dict(os.environ)
        if env:
            spawn_env.update(env)

        proc = ptyprocess.PtyProcess.spawn(
            argv,
            cwd=cwd,
            env=spawn_env,
            dimensions=(24, 120),
        )

        session_id = uuid.uuid4().hex
        try:
            pgid = os.getpgid(proc.pid)
        except (OSError, ProcessLookupError):
            pgid = proc.pid

        entry: dict[str, Any] = {
            "pty": proc,
            "command": display,
            "started_at": time.time(),
            "status": "running",
            "exit_code": None,
            "output_buffer": bytearray(),
            "pgid": pgid,
            "pid": proc.pid,
            "drain_task": None,
            "run_id": run_id,
            "history": bytearray(),
        }
        self._sessions[session_id] = entry

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None:
            entry["drain_task"] = loop.create_task(self._drain(session_id))

        logger.info(
            "[LOCAL] Created PTY session %s pid=%s cmd=%r",
            session_id,
            proc.pid,
            display,
        )
        return session_id

    async def _drain(self, session_id: str) -> None:
        """Background coroutine that continuously pulls bytes from the PTY."""
        entry = self._sessions.get(session_id)
        if entry is None:
            return

        proc = entry["pty"]
        loop = asyncio.get_running_loop()
        buf: bytearray = entry["output_buffer"]
        history: bytearray = entry["history"]

        def _read_chunk() -> bytes:
            try:
                return proc.read(4096)
            except EOFError:
                return b""
            except OSError:
                return b""

        try:
            while True:
                if not proc.isalive() and not entry["output_buffer"]:
                    # Try one final drain before giving up.
                    chunk = await loop.run_in_executor(None, _read_chunk)
                    if chunk:
                        buf.extend(chunk)
                        history.extend(chunk)
                    break

                chunk = await loop.run_in_executor(None, _read_chunk)
                if not chunk:
                    if not proc.isalive():
                        break
                    await asyncio.sleep(0.02)
                    continue
                buf.extend(chunk)
                history.extend(chunk)
        finally:
            # Mark the session as exited and capture the exit code.
            try:
                if proc.isalive():
                    # Leave it alone — will be marked on next status poll.
                    pass
                else:
                    entry["status"] = "exited"
                    exit_status = getattr(proc, "exitstatus", None)
                    if exit_status is None:
                        exit_status = getattr(proc, "status", None)
                    entry["exit_code"] = exit_status
            except Exception:
                entry["status"] = "exited"

    def write(self, session_id: str, chars: str) -> None:
        """
        Write ``chars`` into the PTY session.

        Args:
            session_id: Session identifier returned by ``create``.
            chars: Characters to send to the PTY master. Typically includes
                an explicit ``\\n`` when simulating a pressed Enter key.

        Raises:
            KeyError: If ``session_id`` is not registered.
        """
        entry = self._sessions[session_id]
        proc = entry["pty"]
        proc.write(chars.encode("utf-8"))

    def read(self, session_id: str, max_bytes: int = 65536) -> bytes:
        """
        Return the next chunk of buffered output and clear it from the buffer.

        Args:
            session_id: Session identifier.
            max_bytes: Maximum number of bytes to return. When the buffer
                contains more than this, the excess is preserved for the
                next call.

        Returns:
            The next chunk of output (possibly empty if nothing has been
            drained yet).

        Raises:
            KeyError: If ``session_id`` is not registered.
        """
        entry = self._sessions[session_id]
        buf: bytearray = entry["output_buffer"]
        if not buf:
            return b""
        chunk = bytes(buf[:max_bytes])
        del buf[: len(chunk)]
        return chunk

    def status(self, session_id: str) -> dict[str, Any]:
        """
        Return a snapshot of the session's current state.

        Refreshes ``status`` / ``exit_code`` if the underlying process has
        exited since the last poll.

        Returns:
            Dict with ``pid``, ``command``, ``started_at``, ``status``,
            ``exit_code``.

        Raises:
            KeyError: If ``session_id`` is not registered.
        """
        entry = self._sessions[session_id]
        proc = entry["pty"]
        if entry["status"] == "running" and not proc.isalive():
            entry["status"] = "exited"
            exit_status = getattr(proc, "exitstatus", None)
            if exit_status is None:
                exit_status = getattr(proc, "status", None)
            entry["exit_code"] = exit_status

        return {
            "pid": entry["pid"],
            "command": entry["command"],
            "started_at": entry["started_at"],
            "status": entry["status"],
            "exit_code": entry["exit_code"],
            "run_id": entry.get("run_id"),
        }

    def close(self, session_id: str) -> None:
        """
        Terminate the session's process group and drop it from the registry.

        Safe to call multiple times — subsequent calls for a removed session
        are no-ops.
        """
        entry = self._sessions.pop(session_id, None)
        if entry is None:
            return

        proc = entry["pty"]
        pgid = entry.get("pgid")

        if proc.isalive():
            if pgid:
                with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
                    os.killpg(pgid, signal.SIGTERM)
            with contextlib.suppress(Exception):
                proc.terminate(force=False)

            # Give it a moment to exit gracefully, then SIGKILL if needed.
            deadline = time.time() + 1.0
            while proc.isalive() and time.time() < deadline:
                time.sleep(0.02)

            if proc.isalive():
                if pgid:
                    with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
                        os.killpg(pgid, signal.SIGKILL)
                with contextlib.suppress(Exception):
                    proc.terminate(force=True)

        with contextlib.suppress(Exception):
            proc.close(force=True)

        drain_task = entry.get("drain_task")
        if drain_task is not None and not drain_task.done():
            drain_task.cancel()

        logger.info("[LOCAL] Closed PTY session %s", session_id)

    def list(self) -> list[dict[str, Any]]:
        """
        Return status snapshots for every live session in the registry.

        Returns:
            List of status dicts (same shape as ``status``) plus a
            ``session_id`` field per entry.
        """
        results: list[dict[str, Any]] = []
        for session_id in list(self._sessions.keys()):
            try:
                snapshot = self.status(session_id)
            except KeyError:
                continue
            snapshot["session_id"] = session_id
            entry = self._sessions.get(session_id)
            if entry is not None:
                snapshot["run_id"] = entry.get("run_id")
            results.append(snapshot)
        return results

    def list_by_run(self, run_id: str | None) -> list[dict[str, Any]]:
        """
        Return status snapshots for every session tagged with ``run_id``.

        Args:
            run_id: The invocation identifier to filter by. When ``None``,
                every session in the registry is returned (used as a
                fallback when the caller cannot provide a run id).

        Returns:
            List of status dicts, same shape as :meth:`list`.
        """
        all_sessions = self.list()
        if run_id is None:
            return all_sessions
        return [entry for entry in all_sessions if entry.get("run_id") == run_id]

    def read_history(self, session_id: str, max_bytes: int = 65536) -> bytes:
        """
        Return the last ``max_bytes`` of accumulated PTY output.

        Unlike :meth:`read`, this does NOT consume the live output buffer
        — it peeks at the full history recorded since session creation.

        Args:
            session_id: Session identifier.
            max_bytes: Maximum number of bytes to return. If the history
                exceeds this, the tail is returned.

        Raises:
            KeyError: If ``session_id`` is not registered.
        """
        entry = self._sessions[session_id]
        history: bytearray = entry["history"]
        if not history:
            return b""
        if len(history) <= max_bytes:
            return bytes(history)
        return bytes(history[-max_bytes:])

    def get_run_id(self, session_id: str) -> str | None:
        """Return the ``run_id`` associated with ``session_id`` (or None)."""
        entry = self._sessions.get(session_id)
        if entry is None:
            return None
        return entry.get("run_id")

    def has(self, session_id: str) -> bool:
        """Return True when ``session_id`` is currently registered."""
        return session_id in self._sessions

    async def drain(
        self,
        session_id: str,
        max_duration_ms: int,
        idle_timeout_ms: int = 0,
        max_bytes: int | None = None,
        wait_for_exit: bool = True,
    ) -> bytes:
        """
        Accumulate output from a session until one of several conditions
        is met.

        Termination conditions (checked in order on each poll):

        1. ``max_duration_ms`` elapsed since this call started.
        2. ``idle_timeout_ms > 0`` and no new bytes arrived for that long.
        3. ``wait_for_exit`` is True and the process has exited AND the
           drain buffer is empty.
        4. ``max_bytes`` collected.

        Returns the bytes collected (which are consumed from the session's
        drain buffer so subsequent calls see fresh output only).
        """
        if session_id not in self._sessions:
            raise KeyError(session_id)

        entry = self._sessions[session_id]
        proc = entry["pty"]

        collected = bytearray()
        start = time.monotonic()
        last_activity = start

        while True:
            chunk = self.read(session_id, max_bytes=65536)
            if chunk:
                collected.extend(chunk)
                last_activity = time.monotonic()
                if max_bytes is not None and len(collected) >= max_bytes:
                    break

            # Refresh exit state.
            _ = self.status(session_id)

            if wait_for_exit and not proc.isalive() and not entry["output_buffer"]:
                # Final sweep in case the drain task is still flushing.
                tail = self.read(session_id, max_bytes=65536)
                if tail:
                    collected.extend(tail)
                break

            now = time.monotonic()
            if (now - start) * 1000.0 >= max_duration_ms:
                break
            if idle_timeout_ms > 0 and (now - last_activity) * 1000.0 >= idle_timeout_ms:
                break

            await asyncio.sleep(0.02)

        return bytes(collected)


# Module-level singleton for agent tools to share.
PTY_SESSIONS = PtySessionRegistry()


# =============================================================================
# LOCAL ORCHESTRATOR
# =============================================================================


class LocalOrchestrator(BaseOrchestrator):
    """
    Filesystem + subprocess orchestrator.

    Operates directly against the host machine at the path given by the
    ``PROJECT_ROOT`` environment variable. All project / container metadata
    passed through the BaseOrchestrator interface is logged but otherwise
    ignored: there is exactly one "project" per process, and it lives at
    the project root.
    """

    def __init__(self) -> None:
        self._root = _get_project_root()
        logger.info("[LOCAL] Initialized with PROJECT_ROOT=%s", self._root)

    @property
    def deployment_mode(self) -> DeploymentMode:
        return DeploymentMode.LOCAL

    @property
    def root(self) -> Path:
        """
        Return a fresh view of the project root.

        Re-reads the environment on every access so tests can swap the
        root via ``monkeypatch.setenv("PROJECT_ROOT", ...)`` without
        recreating the orchestrator instance.
        """
        return _get_project_root()

    # =========================================================================
    # PROJECT LIFECYCLE (no-ops)
    # =========================================================================

    async def start_project(
        self,
        project: Any,
        containers: list,
        connections: list,
        user_id: UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        slug = getattr(project, "slug", None) or "local"
        logger.info("[LOCAL] start_project no-op for project=%s", slug)
        return {
            "status": "running",
            "project_slug": slug,
            "containers": {},
            "mode": "local",
        }

    async def stop_project(self, project_slug: str, project_id: UUID, user_id: UUID) -> None:
        logger.info("[LOCAL] stop_project no-op for project=%s", project_slug)
        return None

    async def restart_project(
        self,
        project: Any,
        containers: list,
        connections: list,
        user_id: UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        logger.info(
            "[LOCAL] restart_project delegates to start_project for project=%s",
            getattr(project, "slug", "local"),
        )
        return await self.start_project(project, containers, connections, user_id, db)

    async def get_project_status(self, project_slug: str, project_id: UUID) -> dict[str, Any]:
        return {
            "status": "running",
            "project_slug": project_slug,
            "containers": {},
            "mode": "local",
        }

    # =========================================================================
    # INDIVIDUAL CONTAINER MANAGEMENT (no-ops)
    # =========================================================================

    async def start_container(
        self,
        project: Any,
        container: Any,
        all_containers: list,
        connections: list,
        user_id: UUID,
        db: AsyncSession,
    ) -> dict[str, Any]:
        name = getattr(container, "name", "local")
        logger.info("[LOCAL] start_container no-op for container=%s", name)
        return {
            "status": "running",
            "container_name": name,
            "url": "",
            "mode": "local",
        }

    async def stop_container(
        self,
        project_slug: str,
        project_id: UUID,
        container_name: str,
        user_id: UUID,
    ) -> None:
        logger.info(
            "[LOCAL] stop_container no-op for project=%s container=%s",
            project_slug,
            container_name,
        )
        return None

    async def get_container_status(
        self,
        project_slug: str,
        project_id: UUID,
        container_name: str,
        user_id: UUID,
    ) -> dict[str, Any]:
        return {
            "status": "running",
            "container_name": container_name,
            "url": "",
            "mode": "local",
        }

    # =========================================================================
    # FILE OPERATIONS
    # =========================================================================

    async def read_file(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        file_path: str,
        project_slug: str | None = None,
        subdir: str | None = None,
        volume_id: str | None = None,
        cache_node: str | None = None,
    ) -> str | None:
        """
        Read a file from the local project root.

        Returns:
            The file contents as a string, or ``None`` if the path does not
            exist, points at a directory, or escapes the project root.
        """
        root = self.root
        try:
            target = _safe_resolve(root, file_path, subdir)
        except PermissionError as exc:
            logger.warning("[LOCAL] read_file refused: %s", exc)
            return None

        if not target.exists() or not target.is_file():
            return None

        try:
            return target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            logger.warning(
                "[LOCAL] read_file utf-8 decode failed for %s; retrying as latin-1",
                target,
            )
            try:
                return target.read_text(encoding="latin-1")
            except OSError as exc:
                logger.error("[LOCAL] read_file failed: %s", exc)
                return None
        except OSError as exc:
            logger.error("[LOCAL] read_file failed: %s", exc)
            return None

    async def write_file(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        file_path: str,
        content: str,
        project_slug: str | None = None,
        subdir: str | None = None,
        volume_id: str | None = None,
        cache_node: str | None = None,
    ) -> bool:
        """
        Atomically write a file under the local project root.

        Parent directories are created if missing. File mode is preserved
        when overwriting an existing file.

        Returns:
            True on success, False if the path is rejected or an OS error
            occurs.
        """
        root = self.root
        try:
            # _safe_resolve calls .resolve() which requires the file to exist
            # for full symlink verification; for write we validate against
            # the parent directory and then verify the final path.
            if file_path is None or file_path == "":
                logger.warning("[LOCAL] write_file refused: empty file_path")
                return False

            base = root if not subdir else _safe_resolve(root, None, subdir)
            candidate = (base / file_path).resolve()

            try:
                candidate.relative_to(root)
            except ValueError as exc:
                raise PermissionError(
                    f"[LOCAL] write path '{file_path}' escapes project root {root}"
                ) from exc

            target = candidate
        except PermissionError as exc:
            logger.warning("[LOCAL] write_file refused: %s", exc)
            return False

        parent = target.parent

        try:
            parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.error("[LOCAL] write_file mkdir failed: %s", exc)
            return False

        # Preserve the existing file mode, if any.
        existing_mode: int | None = None
        if target.exists() and target.is_file():
            try:
                existing_mode = target.stat().st_mode & 0o777
            except OSError:
                existing_mode = None

        tmp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=str(parent),
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as tmp:
                tmp.write(content)
                tmp.flush()
                os.fsync(tmp.fileno())
                tmp_path = tmp.name

            if existing_mode is not None:
                with contextlib.suppress(OSError):
                    os.chmod(tmp_path, existing_mode)

            os.replace(tmp_path, str(target))
            tmp_path = None  # Ownership handed off.
            logger.debug("[LOCAL] Wrote file %s (%d bytes)", target, len(content))
            return True
        except OSError as exc:
            logger.error("[LOCAL] write_file failed for %s: %s", target, exc)
            return False
        finally:
            if tmp_path is not None:
                with contextlib.suppress(OSError):
                    os.unlink(tmp_path)

    async def delete_file(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        file_path: str,
    ) -> bool:
        """
        Remove a file under the local project root.

        Returns:
            True if the file was removed successfully, False if the file
            did not exist or the path was rejected.
        """
        root = self.root
        try:
            target = _safe_resolve(root, file_path, None)
        except PermissionError as exc:
            logger.warning("[LOCAL] delete_file refused: %s", exc)
            return False

        if not target.exists():
            return False
        if not target.is_file():
            logger.warning("[LOCAL] delete_file refused: %s is not a file", target)
            return False

        try:
            os.remove(target)
            logger.debug("[LOCAL] Deleted file %s", target)
            return True
        except OSError as exc:
            logger.error("[LOCAL] delete_file failed for %s: %s", target, exc)
            return False

    async def list_files(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        directory: str = ".",
    ) -> list[dict[str, Any]]:
        """
        List immediate entries in a directory relative to the project root.

        Hidden entries (names starting with ``.``) are skipped.

        Returns:
            List of dicts, each with ``name``, ``type`` (``"file"`` or
            ``"directory"``), ``size``, and ``path`` (relative to root).
            Sorted by name.
        """
        root = self.root
        try:
            target = _safe_resolve(root, directory or ".", None)
        except PermissionError as exc:
            logger.warning("[LOCAL] list_files refused: %s", exc)
            return []

        if not target.exists() or not target.is_dir():
            return []

        entries: list[dict[str, Any]] = []
        try:
            for child in target.iterdir():
                if child.name.startswith("."):
                    continue
                try:
                    st = child.stat()
                except OSError:
                    continue
                try:
                    rel = child.resolve().relative_to(root)
                except (ValueError, OSError):
                    continue
                entries.append(
                    {
                        "name": child.name,
                        "type": "directory" if child.is_dir() else "file",
                        "size": st.st_size if child.is_file() else 0,
                        "path": str(rel),
                    }
                )
        except OSError as exc:
            logger.error("[LOCAL] list_files failed: %s", exc)
            return []

        entries.sort(key=lambda e: e["name"])
        return entries

    async def list_tree(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        subdir: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Recursive file tree, honoring ``.gitignore`` and a baseline set of
        always-excluded directories (``node_modules``, ``.git``, build
        output, virtualenvs, caches, etc.).

        Returns:
            List of dicts with ``path`` (relative to root), ``name``,
            ``is_dir``, ``size``, ``mod_time``.
        """
        root = self.root
        try:
            walk_root = _safe_resolve(root, None, subdir) if subdir else root
        except PermissionError as exc:
            logger.warning("[LOCAL] list_tree refused: %s", exc)
            return []

        if not walk_root.exists() or not walk_root.is_dir():
            return []

        gitignore_matcher = self._load_gitignore_matcher(root)

        entries: list[dict[str, Any]] = []

        def _should_exclude_rel(rel: str, is_dir: bool) -> bool:
            if gitignore_matcher is None:
                return False
            check = rel + "/" if is_dir and not rel.endswith("/") else rel
            return gitignore_matcher(check)

        try:
            for current, dirnames, filenames in os.walk(walk_root):
                current_path = Path(current)
                # Filter excluded dirs in place so os.walk doesn't descend.
                filtered_dirs: list[str] = []
                for d in dirnames:
                    if d in EXCLUDED_TREE_DIRS:
                        continue
                    rel_dir = str((current_path / d).relative_to(root))
                    if _should_exclude_rel(rel_dir, True):
                        continue
                    filtered_dirs.append(d)
                dirnames[:] = filtered_dirs

                rel_current = current_path.relative_to(root)

                for d in dirnames:
                    full = current_path / d
                    rel_path = rel_current / d if str(rel_current) != "." else Path(d)
                    try:
                        st = full.stat()
                        mod_time = float(st.st_mtime)
                    except OSError:
                        mod_time = 0.0
                    entries.append(
                        {
                            "path": str(rel_path),
                            "name": d,
                            "is_dir": True,
                            "size": 0,
                            "mod_time": mod_time,
                        }
                    )

                for filename in filenames:
                    rel_path = rel_current / filename if str(rel_current) != "." else Path(filename)
                    if _should_exclude_rel(str(rel_path), False):
                        continue
                    full = current_path / filename
                    try:
                        st = full.stat()
                        size = st.st_size
                        mod_time = float(st.st_mtime)
                    except OSError:
                        continue
                    entries.append(
                        {
                            "path": str(rel_path),
                            "name": filename,
                            "is_dir": False,
                            "size": size,
                            "mod_time": mod_time,
                        }
                    )
        except OSError as exc:
            logger.error("[LOCAL] list_tree failed: %s", exc)
            return entries

        return entries

    def _load_gitignore_matcher(self, root: Path):
        """
        Build a callable that returns True when a given relative path should
        be excluded by a root-level ``.gitignore``.

        Uses ``pathspec`` when available; otherwise returns None (matching
        only the baseline EXCLUDED_TREE_DIRS set).
        """
        gitignore_path = root / ".gitignore"
        if not gitignore_path.exists() or not gitignore_path.is_file():
            return None

        try:
            patterns_text = gitignore_path.read_text(encoding="utf-8")
        except OSError:
            return None

        try:
            import pathspec  # type: ignore[import-not-found]
        except ImportError:
            return self._build_minimal_matcher(patterns_text)

        try:
            spec = pathspec.PathSpec.from_lines("gitwildmatch", patterns_text.splitlines())
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("[LOCAL] pathspec compile failed: %s", exc)
            return self._build_minimal_matcher(patterns_text)

        def _match(rel_path: str) -> bool:
            return spec.match_file(rel_path)

        return _match

    @staticmethod
    def _build_minimal_matcher(patterns_text: str):
        """
        Fallback matcher when ``pathspec`` isn't installed.

        Handles only the most common cases: ``#`` comments, plain names,
        trailing-slash directory markers, and the ``**`` wildcard.
        """
        import fnmatch

        raw_lines = [ln.strip() for ln in patterns_text.splitlines()]
        patterns: list[tuple[str, bool]] = []
        for line in raw_lines:
            if not line or line.startswith("#"):
                continue
            directory_only = line.endswith("/")
            pat = line.rstrip("/")
            patterns.append((pat, directory_only))

        def _match(rel_path: str) -> bool:
            rel_norm = rel_path.rstrip("/")
            is_dir = rel_path.endswith("/")
            for pat, dir_only in patterns:
                if dir_only and not is_dir:
                    continue
                if fnmatch.fnmatch(rel_norm, pat) or fnmatch.fnmatch(
                    os.path.basename(rel_norm), pat
                ):
                    return True
            return False

        return _match

    async def read_file_content(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        file_path: str,
        subdir: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Read a single file and return its metadata + content.

        Returns:
            Dict with ``path``, ``content``, ``size`` — or ``None`` if the
            file does not exist.
        """
        content = await self.read_file(
            user_id,
            project_id,
            container_name,
            file_path,
            subdir=subdir,
        )
        if content is None:
            return None
        return {
            "path": file_path,
            "content": content,
            "size": len(content),
        }

    async def read_files_batch(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        paths: list[str],
        subdir: str | None = None,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """
        Batch-read several files.

        Returns:
            Tuple of (successful_reads, failed_paths). ``successful_reads``
            is a list of dicts matching the ``read_file_content`` shape;
            ``failed_paths`` lists any paths that couldn't be read.
        """
        files: list[dict[str, Any]] = []
        errors: list[str] = []

        async def _read_one(path: str) -> None:
            try:
                result = await self.read_file_content(
                    user_id,
                    project_id,
                    container_name,
                    path,
                    subdir=subdir,
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("[LOCAL] read_files_batch entry failed: %s", exc)
                errors.append(path)
                return
            if result is None:
                errors.append(path)
            else:
                files.append(result)

        for p in paths:
            await _read_one(p)
        return files, errors

    # =========================================================================
    # SHELL OPERATIONS
    # =========================================================================

    async def execute_command(
        self,
        user_id: UUID,
        project_id: UUID,
        container_name: str,
        command: list[str],
        timeout: int = 120,
        working_dir: str | None = None,
    ) -> str:
        """
        Run a command in the local project root (or in a subdirectory).

        The command is executed in its own process group so a timeout can
        reliably tear down the entire process tree.

        Args:
            command: Argv-style command list.
            timeout: Seconds to wait before killing the process group.
            working_dir: Optional directory (relative to root) to run in.

        Returns:
            Combined stdout + stderr as a UTF-8 string (replacement chars
            used for undecodable bytes). On nonzero exit codes the output
            is still returned — callers that care about success should
            use higher-level tooling.

        Raises:
            RuntimeError: If the command times out or fails to spawn.
        """
        if not command:
            raise RuntimeError("[LOCAL] execute_command: empty command")

        root = self.root
        try:
            cwd = _safe_resolve(root, working_dir, None) if working_dir else root
        except PermissionError as exc:
            raise RuntimeError(f"[LOCAL] execute_command refused: {exc}") from exc

        if not cwd.exists() or not cwd.is_dir():
            raise RuntimeError(f"[LOCAL] execute_command: cwd does not exist: {cwd}")

        logger.info("[LOCAL] execute_command cwd=%s argv=%r", cwd, command)

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"[LOCAL] execute_command: {exc}") from exc
        except OSError as exc:
            raise RuntimeError(f"[LOCAL] execute_command spawn failed: {exc}") from exc

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except TimeoutError:
            logger.warning(
                "[LOCAL] execute_command timed out after %ss; killing pgid=%s",
                timeout,
                process.pid,
            )
            await self._terminate_process_group(process)
            raise RuntimeError(f"[LOCAL] Command timed out after {timeout} seconds") from None
        except Exception as exc:
            await self._terminate_process_group(process)
            raise RuntimeError(f"[LOCAL] Command execution failed: {exc}") from exc

        out = (stdout or b"").decode("utf-8", errors="replace")
        err = (stderr or b"").decode("utf-8", errors="replace")
        return out + err

    @staticmethod
    async def _terminate_process_group(process: asyncio.subprocess.Process) -> None:
        """
        Send SIGTERM to the process group, wait briefly, then SIGKILL if
        the children are still alive.
        """
        pid = process.pid
        if pid is None:
            return

        try:
            pgid = os.getpgid(pid)
        except (ProcessLookupError, PermissionError, OSError):
            pgid = pid

        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            os.killpg(pgid, signal.SIGTERM)

        try:
            await asyncio.wait_for(process.wait(), timeout=2.0)
            return
        except TimeoutError:
            pass
        except Exception:
            pass

        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            os.killpg(pgid, signal.SIGKILL)

        with contextlib.suppress(Exception):
            await asyncio.wait_for(process.wait(), timeout=2.0)

    async def is_container_ready(
        self, user_id: UUID, project_id: UUID, container_name: str
    ) -> dict[str, Any]:
        return {
            "ready": True,
            "message": "local mode always ready",
            "mode": "local",
        }

    # =========================================================================
    # ACTIVITY TRACKING
    # =========================================================================

    def track_activity(
        self,
        user_id: UUID,
        project_id: str,
        container_name: str | None = None,
    ) -> None:
        """No-op in local mode — nothing to idle-reap."""
        return None

    # =========================================================================
    # LOG STREAMING
    # =========================================================================

    async def stream_logs(
        self,
        project_id: UUID,
        user_id: UUID,
        container_id: UUID | None = None,
        tail_lines: int = 100,
    ) -> AsyncIterator[str]:
        """Yield a single informational line — local mode has no container logs."""
        yield "local mode: no container logs"
        return
