"""
AstWorker — Python manager for the Node.js AST sidecar.

The worker is a long-lived Node process (``orchestrator/ast_worker/worker.mjs``)
that reads NDJSON commands from stdin and writes NDJSON replies to stdout.
Each command has a unique integer id; replies are correlated by id.

Usage:
    worker = get_ast_worker()
    result = await worker.index([{"path": "app/page.tsx", "content": "..."}])
    result = await worker.apply_diff(files, requests)

The worker auto-starts on first call and stays running until ``stop()`` is
called or the process exits. A single worker is shared by all requests via
``get_ast_worker()``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Resolve the Node worker script relative to this file.
#   this file: orchestrator/app/services/design/ast_worker.py
#   parents[3]: orchestrator/
_WORKER_DIR = Path(__file__).resolve().parents[3] / "ast_worker"
_WORKER_SCRIPT = _WORKER_DIR / "worker.mjs"
_WORKER_NODE_MODULES = _WORKER_DIR / "node_modules"

# Call timeout for AST operations. Large projects with hundreds of files
# can take several seconds to index, so we allow a generous default.
_DEFAULT_CALL_TIMEOUT = 60.0
_STARTUP_TIMEOUT = 15.0


class AstWorkerError(RuntimeError):
    """Raised when the AST worker fails to start or process a command."""


class AstWorker:
    """Manages a single long-lived Node subprocess with an NDJSON protocol."""

    def __init__(self) -> None:
        self._proc: asyncio.subprocess.Process | None = None
        self._start_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._next_id = 0
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._ready_event: asyncio.Event | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def _ensure_started(self) -> None:
        async with self._start_lock:
            if self._proc and self._proc.returncode is None:
                return

            node = shutil.which("node")
            if node is None:
                raise AstWorkerError(
                    "Node.js runtime not found on PATH. Install Node 18+ and ensure "
                    "`node` is available to the orchestrator process."
                )
            if not _WORKER_SCRIPT.exists():
                raise AstWorkerError(
                    f"AST worker script missing at {_WORKER_SCRIPT}. "
                    "Check the orchestrator deployment."
                )
            if not _WORKER_NODE_MODULES.exists():
                raise AstWorkerError(
                    f"AST worker dependencies not installed. Run "
                    f"`cd {_WORKER_DIR} && npm install --omit=dev`"
                )

            logger.info("[AstWorker] starting node worker at %s", _WORKER_SCRIPT)
            self._ready_event = asyncio.Event()
            self._proc = await asyncio.create_subprocess_exec(
                node,
                str(_WORKER_SCRIPT),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(_WORKER_DIR),
            )
            self._reader_task = asyncio.create_task(
                self._read_loop(), name="ast-worker-stdout"
            )
            self._stderr_task = asyncio.create_task(
                self._drain_stderr(), name="ast-worker-stderr"
            )

            try:
                await asyncio.wait_for(self._ready_event.wait(), timeout=_STARTUP_TIMEOUT)
            except TimeoutError as exc:
                await self._kill_process()
                raise AstWorkerError(
                    f"AST worker did not emit a ready signal within {_STARTUP_TIMEOUT}s"
                ) from exc
            logger.info("[AstWorker] worker pid=%s ready", self._proc.pid)

    async def _kill_process(self) -> None:
        if self._proc and self._proc.returncode is None:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=2.0)
            except TimeoutError:
                self._proc.kill()
            except ProcessLookupError:
                pass
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
        if self._stderr_task and not self._stderr_task.done():
            self._stderr_task.cancel()
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(AstWorkerError("worker process exited"))
        self._pending.clear()
        self._proc = None
        self._reader_task = None
        self._stderr_task = None

    async def stop(self) -> None:
        async with self._start_lock:
            await self._kill_process()

    # ── Read / stderr loops ───────────────────────────────────────────

    async def _read_loop(self) -> None:
        assert self._proc and self._proc.stdout
        stdout = self._proc.stdout
        try:
            while True:
                line = await stdout.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError:
                    logger.warning("[AstWorker] non-json line: %r", line[:200])
                    continue

                # Startup signal
                if isinstance(msg, dict) and msg.get("event") == "ready":
                    if self._ready_event and not self._ready_event.is_set():
                        self._ready_event.set()
                    continue

                msg_id = msg.get("id") if isinstance(msg, dict) else None
                if msg_id is None:
                    # Unsolicited event — log and ignore
                    logger.debug("[AstWorker] unsolicited: %s", msg)
                    continue

                fut = self._pending.pop(msg_id, None)
                if fut and not fut.done():
                    fut.set_result(msg)
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001
            logger.exception("[AstWorker] reader loop crashed: %s", exc)
        finally:
            # Anything still pending is now orphaned.
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(AstWorkerError("worker stdout closed"))
            self._pending.clear()

    async def _drain_stderr(self) -> None:
        assert self._proc and self._proc.stderr
        stderr = self._proc.stderr
        try:
            while True:
                line = await stderr.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    logger.warning("[AstWorker:stderr] %s", text)
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001
            logger.exception("[AstWorker] stderr loop crashed")

    # ── RPC ───────────────────────────────────────────────────────────

    async def _call(
        self,
        op: str,
        payload: dict[str, Any],
        timeout: float = _DEFAULT_CALL_TIMEOUT,
    ) -> Any:
        await self._ensure_started()
        assert self._proc and self._proc.stdin

        async with self._write_lock:
            self._next_id += 1
            msg_id = self._next_id
            fut: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
            self._pending[msg_id] = fut
            line = (
                json.dumps(
                    {"id": msg_id, "op": op, "payload": payload},
                    ensure_ascii=False,
                )
                + "\n"
            )
            try:
                self._proc.stdin.write(line.encode("utf-8"))
                await self._proc.stdin.drain()
            except Exception as exc:  # noqa: BLE001
                self._pending.pop(msg_id, None)
                raise AstWorkerError(f"failed to write to worker stdin: {exc}") from exc

        try:
            reply = await asyncio.wait_for(fut, timeout=timeout)
        except TimeoutError as exc:
            self._pending.pop(msg_id, None)
            raise AstWorkerError(f"worker op={op} timed out after {timeout:.0f}s") from exc

        if not reply.get("ok"):
            err = reply.get("error") or "worker call failed"
            raise AstWorkerError(f"worker op={op} failed: {err}")
        return reply.get("result")

    async def ping(self) -> dict[str, Any]:
        return await self._call("ping", {}, timeout=5.0)

    async def index(self, files: list[dict[str, str]]) -> dict[str, Any]:
        """Inject data-oid into every JSX element. Returns {files, index}."""
        return await self._call("index", {"files": files})

    async def apply_diff(
        self,
        files: list[dict[str, str]],
        requests: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Apply CodeDiffRequest list to files. Returns {files}."""
        return await self._call("apply_diff", {"files": files, "requests": requests})


# ── Global singleton ─────────────────────────────────────────────────────

_GLOBAL_WORKER: AstWorker | None = None


def get_ast_worker() -> AstWorker:
    """Return the shared AstWorker instance, creating it if needed."""
    global _GLOBAL_WORKER
    if _GLOBAL_WORKER is None:
        _GLOBAL_WORKER = AstWorker()
    return _GLOBAL_WORKER


async def shutdown_ast_worker() -> None:
    """Stop the shared worker — call during orchestrator shutdown."""
    global _GLOBAL_WORKER
    if _GLOBAL_WORKER is not None:
        await _GLOBAL_WORKER.stop()
        _GLOBAL_WORKER = None
