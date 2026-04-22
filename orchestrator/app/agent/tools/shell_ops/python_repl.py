"""
Persistent Python REPL Tool.

Exposes a per-session Python interpreter that keeps locals across calls,
captures stdout/stderr/exceptions, and supports simple expression
evaluation (returning the repr of the result in the ``value`` field).

Execution is offloaded to a daemon thread with a hard deadline — when
the deadline elapses the session is marked ``bad`` because arbitrary
Python code cannot be interrupted safely, and subsequent calls against
that session are rejected until ``reset=True`` is passed.

Design notes:
- Each session owns an :class:`code.InteractiveInterpreter` and a
  dedicated ``locals_dict``.
- Sessions are held in a process-local registry
  (:data:`PYTHON_REPL_SESSIONS`) keyed by uuid4 hex.
- Expression vs statement detection uses :func:`ast.parse`.
- Output buffers are per-call: stdout/stderr are captured with
  :class:`io.StringIO` and redirected around the thread invocation.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import io
import logging
import threading
import traceback
import uuid
from code import InteractiveInterpreter
from typing import Any

from ..output_formatter import error_output, success_output
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)

_BYTES_PER_TOKEN = 4
_TRUNCATION_MARKER = "\n[truncated]\n"


def _truncate(text: str, max_output_tokens: int) -> str:
    if not text:
        return text
    if max_output_tokens <= 0:
        return text
    budget = max_output_tokens * _BYTES_PER_TOKEN
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= budget:
        return text
    tail = encoded[-budget:]
    try:
        decoded = tail.decode("utf-8", errors="replace")
    except UnicodeDecodeError:
        decoded = tail.decode("latin-1", errors="replace")
    return _TRUNCATION_MARKER + decoded


class PythonReplSession:
    """
    A single persistent Python interpreter.

    Holds its own ``locals_dict``, a lock to serialize concurrent calls
    from the same session, and a ``bad`` flag that is set when the
    previous execution timed out and cannot be safely reused.
    """

    def __init__(self) -> None:
        self.locals_dict: dict[str, Any] = {
            "__name__": "__repl__",
            "__builtins__": __builtins__,
        }
        self.interpreter = InteractiveInterpreter(self.locals_dict)
        self.lock = threading.Lock()
        self.bad = False
        self.bad_reason: str | None = None


class PythonReplSessionRegistry:
    """In-memory registry of persistent Python REPL sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, PythonReplSession] = {}
        self._lock = threading.Lock()

    def create(self) -> tuple[str, PythonReplSession]:
        session_id = uuid.uuid4().hex
        session = PythonReplSession()
        with self._lock:
            self._sessions[session_id] = session
        return session_id, session

    def get(self, session_id: str) -> PythonReplSession | None:
        with self._lock:
            return self._sessions.get(session_id)

    def drop(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def reset(self, session_id: str) -> PythonReplSession:
        self.drop(session_id)
        session = PythonReplSession()
        with self._lock:
            self._sessions[session_id] = session
        return session

    def has(self, session_id: str) -> bool:
        with self._lock:
            return session_id in self._sessions


PYTHON_REPL_SESSIONS = PythonReplSessionRegistry()


def _execute_code_sync(
    session: PythonReplSession,
    code: str,
) -> tuple[str, str, str | None]:
    """
    Execute ``code`` against ``session`` and return ``(stdout, stderr, value)``.

    This function is called inside a worker thread. It acquires the
    session lock for the duration of the call so two overlapping
    ``python_repl`` invocations against the same session serialize.
    """
    if not session.lock.acquire(blocking=False):
        return (
            "",
            "another python_repl call is already running against this session\n",
            None,
        )

    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    value: str | None = None

    try:
        with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
            # Try expression first.
            try:
                expr_node = ast.parse(code, mode="eval")
            except SyntaxError:
                expr_node = None

            if expr_node is not None:
                try:
                    compiled = compile(expr_node, "<python_repl>", "eval")
                    result = eval(compiled, session.locals_dict)  # noqa: S307
                    if result is not None:
                        value = repr(result)
                        # Mirror Python REPL behavior: bind `_` to the last value.
                        session.locals_dict["_"] = result
                except SystemExit as exc:
                    stderr_buf.write(f"SystemExit: {exc}\n")
                except BaseException:  # noqa: BLE001 - capture all exceptions in REPL
                    traceback.print_exc(file=stderr_buf)
            else:
                # Statement path — parse+compile so syntax errors surface nicely.
                try:
                    stmt_node = ast.parse(code, mode="exec")
                    compiled = compile(stmt_node, "<python_repl>", "exec")
                    exec(compiled, session.locals_dict)  # noqa: S102
                except SystemExit as exc:
                    stderr_buf.write(f"SystemExit: {exc}\n")
                except BaseException:  # noqa: BLE001
                    traceback.print_exc(file=stderr_buf)
    finally:
        session.lock.release()

    return stdout_buf.getvalue(), stderr_buf.getvalue(), value


async def python_repl_tool(
    params: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """
    Run ``code`` against a persistent Python REPL session.

    Args:
        params: {
            code: str,
            session_id: str | None,
            reset: bool = False,
            timeout_ms: int = 30000,
            max_output_tokens: int = 4096,
        }
    """
    code = params.get("code")
    if code is None or not isinstance(code, str):
        raise ValueError("code parameter is required and must be a string")

    session_id = params.get("session_id")
    reset_flag = bool(params.get("reset", False))
    timeout_ms = int(params.get("timeout_ms", 30000))
    if timeout_ms <= 0:
        raise ValueError("timeout_ms must be a positive integer")
    max_output_tokens = int(params.get("max_output_tokens", 4096))

    # Resolve or create the target session.
    if session_id is None or session_id == "":
        session_id, session = PYTHON_REPL_SESSIONS.create()
    else:
        if not isinstance(session_id, str):
            raise ValueError("session_id must be a string")
        if reset_flag:
            session = PYTHON_REPL_SESSIONS.reset(session_id)
        else:
            existing = PYTHON_REPL_SESSIONS.get(session_id)
            if existing is None:
                # Session didn't exist — create fresh with the requested id.
                session = PythonReplSession()
                with PYTHON_REPL_SESSIONS._lock:  # noqa: SLF001
                    PYTHON_REPL_SESSIONS._sessions[session_id] = session  # noqa: SLF001
            else:
                session = existing

    if session.bad and not reset_flag:
        return error_output(
            message=(
                f"Python REPL session {session_id} is marked bad "
                f"({session.bad_reason or 'previous execution timed out'}). "
                f"Pass reset=true to recreate it."
            ),
            suggestion="Retry with reset=true to drop the broken session and start fresh.",
            details={
                "session_id": session_id,
                "bad_reason": session.bad_reason,
                "tier": "local",
            },
        )

    loop = asyncio.get_running_loop()

    # Daemon-thread approach: we can't safely interrupt arbitrary Python
    # on timeout, but we *can* abandon a daemon thread when the process
    # exits. Using ThreadPoolExecutor would hang the workers at shutdown
    # when a stuck ``while True: pass`` blocks the pool forever.
    done_event = asyncio.Event()
    result_holder: dict[str, Any] = {"stdout": "", "stderr": "", "value": None}

    def _runner() -> None:
        try:
            s, e, v = _execute_code_sync(session, code)
            result_holder["stdout"] = s
            result_holder["stderr"] = e
            result_holder["value"] = v
        finally:
            loop.call_soon_threadsafe(done_event.set)

    worker = threading.Thread(target=_runner, name=f"py-repl-{session_id}", daemon=True)
    worker.start()

    timed_out = False
    stdout = ""
    stderr = ""
    value: str | None = None

    try:
        await asyncio.wait_for(done_event.wait(), timeout=timeout_ms / 1000.0)
        stdout = result_holder["stdout"]
        stderr = result_holder["stderr"]
        value = result_holder["value"]
    except TimeoutError:
        timed_out = True
        session.bad = True
        session.bad_reason = f"execution exceeded {timeout_ms}ms"
        # The underlying thread cannot be safely killed — it will keep
        # running as a daemon until the process exits. Mark the session
        # bad so future calls require an explicit reset.
        stderr = (
            f"TimeoutError: python_repl execution exceeded {timeout_ms}ms; "
            f"session {session_id} is now marked bad and must be reset before reuse.\n"
        )

    stdout = _truncate(stdout, max_output_tokens)
    stderr = _truncate(stderr, max_output_tokens)
    if value is not None:
        value = _truncate(value, max_output_tokens)

    logger.info(
        "[PY-REPL] session=%s timed_out=%s stdout_len=%d stderr_len=%d has_value=%s",
        session_id,
        timed_out,
        len(stdout),
        len(stderr),
        value is not None,
    )

    return success_output(
        message=(
            f"python_repl execution timed out after {timeout_ms}ms (session {session_id} bad)"
            if timed_out
            else f"python_repl executed in session {session_id}"
        ),
        session_id=session_id,
        stdout=stdout,
        stderr=stderr,
        value=value,
        timed_out=timed_out,
        details={
            "session_id": session_id,
            "stdout": stdout,
            "stderr": stderr,
            "value": value,
            "timed_out": timed_out,
            "tier": "local",
        },
    )


def register_python_repl_tool(registry) -> None:
    """Register the ``python_repl`` tool on ``registry``."""
    registry.register(
        Tool(
            name="python_repl",
            description=(
                "Execute Python code in a persistent REPL session. Locals "
                "survive across calls within the same session_id, so you can "
                "define a variable or import a module in one call and use it "
                "in the next. Expressions return a `value` (repr of the "
                "result); statements return stdout/stderr. Pass reset=true "
                "to drop the session. timeout_ms is a hard deadline — on "
                "timeout the session is marked bad and must be reset."
            ),
            category=ToolCategory.SHELL,
            parameters={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python source code (expression or statements).",
                    },
                    "session_id": {
                        "type": "string",
                        "description": (
                            "Persistent session identifier. Omit to auto-generate "
                            "a fresh one (the id is returned in the response)."
                        ),
                    },
                    "reset": {
                        "type": "boolean",
                        "description": "Drop any existing session for session_id before executing.",
                        "default": False,
                    },
                    "timeout_ms": {
                        "type": "integer",
                        "description": (
                            "Hard deadline in milliseconds. On timeout the session is marked bad."
                        ),
                        "default": 30000,
                    },
                    "max_output_tokens": {
                        "type": "integer",
                        "description": "Approximate token budget for stdout/stderr/value.",
                        "default": 4096,
                    },
                },
                "required": ["code"],
            },
            executor=python_repl_tool,
            examples=[
                '{"tool_name": "python_repl", "parameters": {"code": "2 + 2"}}',
                '{"tool_name": "python_repl", "parameters": {"code": "x = 5"}}',
                '{"tool_name": "python_repl", "parameters": {"code": "print(x)", "session_id": "abc123"}}',
            ],
        )
    )

    logger.info("Registered python_repl tool")
