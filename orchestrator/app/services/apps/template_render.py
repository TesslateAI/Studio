"""Long-lived render-worker supervisor with IPC.

Owns a single :mod:`app.services.apps.template_render_worker` subprocess
and serializes ``render(template, context)`` calls over its stdin/stdout
pipe. Per-render cost is ~1 ms IPC + Jinja render — versus ~30-80 ms
for ``subprocess.Popen`` per call (importing :mod:`jinja2.sandbox` alone
is ~20 ms; at 500 renders/min that's ~30 s/min CPU just for delivery
rendering).

Lifecycle:

* The worker is spawned lazily on the first :meth:`TemplateRenderClient.render`
  call. It self-exits cleanly after
  :data:`~app.services.apps.template_render_worker.MAX_RENDERS` renders.
  The supervisor notices ``returncode is not None`` on the next call and
  respawns. One log line per respawn — never spam stderr per render.
* On render timeout the supervisor :meth:`Process.kill`-s the worker
  (its stdin/stdout pipe is now out of sync; recovery isn't worth
  trying) and raises :class:`RenderError`. The next call respawns.
* On worker pipe close (``BrokenPipeError`` / EOF) the supervisor drops
  its handle and raises :class:`RenderError`; the next call respawns.

Concurrency: an :class:`asyncio.Lock` serializes stdin writes and
stdout reads so concurrent ``render`` callers don't interleave their
JSON lines on the worker's pipe. Throughput at 1 ms/render is ~1000
calls/s on a single worker, which is well above the 500 renders/min
ceiling the plan calls out. If we ever need more, the supervisor can
become a small pool — but a singleton is fine for now.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Optional

logger = logging.getLogger(__name__)

# Mirror the worker's MAX_RENDERS so the supervisor can preemptively drop
# its handle on the rotation boundary. We don't want to write to a worker
# that's about to close its stdin.
ROTATION_THRESHOLD = 1000

# Default per-render timeout. Render is CPU-bound and bounded by the 4 KB
# template + small Jinja AST — 5 s is generous for a render that should
# complete in <1 ms.
DEFAULT_RENDER_TIMEOUT_SECONDS = 5.0


class RenderError(RuntimeError):
    """Raised when the render worker fails or times out for a single call."""


class TemplateRenderClient:
    """Async-safe supervisor for a single render-worker subprocess."""

    def __init__(self) -> None:
        self._proc: Optional[asyncio.subprocess.Process] = None
        # Lock serializes stdin writes + stdout reads. The IPC contract is
        # one-line-in / one-line-out, so two concurrent renders would
        # interleave each other's JSON otherwise.
        self._lock = asyncio.Lock()
        self._render_count = 0

    async def _spawn_worker(self) -> asyncio.subprocess.Process:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "app.services.apps.template_render_worker",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            # Keep stderr captured so a worker traceback doesn't pollute
            # the orchestrator stderr stream. We deliberately do NOT log
            # it per render — the supervisor only logs on respawn.
            stderr=asyncio.subprocess.PIPE,
        )
        logger.info("template_render: spawned worker pid=%s", proc.pid)
        return proc

    async def _ensure_worker(self) -> asyncio.subprocess.Process:
        proc = self._proc
        if proc is None or proc.returncode is not None:
            if proc is not None:
                logger.info(
                    "template_render: worker exited (returncode=%s); respawning",
                    proc.returncode,
                )
            self._proc = await self._spawn_worker()
            self._render_count = 0
        return self._proc

    async def render(
        self,
        template_str: str,
        context: dict,
        *,
        timeout: float = DEFAULT_RENDER_TIMEOUT_SECONDS,
    ) -> str:
        """Render ``template_str`` with ``context`` via the worker.

        Raises :class:`RenderError` on any failure — timeout, worker
        crash, malformed worker output, or the worker reporting a
        sandbox/Jinja error. Caller should treat this as
        "delivery rendering failed" and surface a fallback (e.g. the
        unrendered template body, the raw output JSON, or skip
        delivery entirely).
        """
        if not isinstance(template_str, str):
            raise RenderError("template must be a string")
        if not isinstance(context, dict):
            raise RenderError("context must be a dict")

        async with self._lock:
            proc = await self._ensure_worker()
            assert proc.stdin is not None
            assert proc.stdout is not None

            payload = json.dumps(
                {"template": template_str, "context": context},
                default=str,  # tolerate datetime/Decimal/etc. in context
            )
            try:
                proc.stdin.write(payload.encode("utf-8") + b"\n")
                await proc.stdin.drain()
                line = await asyncio.wait_for(
                    proc.stdout.readline(), timeout=timeout
                )
            except asyncio.TimeoutError as exc:
                # Worker is now out-of-sync (its stdout response line, if
                # any, will desync the next caller). Kill and respawn on
                # next call.
                self._kill_worker(proc)
                self._proc = None
                raise RenderError(f"render timed out after {timeout}s") from exc
            except (BrokenPipeError, ConnectionResetError) as exc:
                self._proc = None
                raise RenderError(f"worker pipe closed: {exc!r}") from exc

            if not line:
                # Worker exited without responding (likely hit MAX_RENDERS
                # mid-call or crashed). Drop the handle so the next call
                # respawns.
                self._proc = None
                raise RenderError("worker EOF")

            try:
                result = json.loads(line.decode("utf-8"))
            except json.JSONDecodeError as exc:
                # Output desync — safer to kill the worker than try to
                # recover. The next call gets a fresh process.
                self._kill_worker(proc)
                self._proc = None
                raise RenderError(f"worker output not JSON: {exc}") from exc

            self._render_count += 1
            # Worker self-exits at MAX_RENDERS; pre-emptively drop the
            # handle so the next call respawns instead of writing to a
            # closing pipe.
            if self._render_count >= ROTATION_THRESHOLD:
                self._proc = None
                self._render_count = 0

            if not result.get("ok"):
                raise RenderError(result.get("error", "unknown render error"))

            rendered = result.get("rendered", "")
            if not isinstance(rendered, str):
                raise RenderError("worker returned non-string rendered value")
            return rendered

    @staticmethod
    def _kill_worker(proc: asyncio.subprocess.Process) -> None:
        """Best-effort kill — never raise from cleanup."""
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        except Exception:  # noqa: BLE001 — cleanup must not raise
            logger.exception("template_render: kill failed")

    async def close(self) -> None:
        """Shut the worker down cleanly. Safe to call multiple times."""
        proc = self._proc
        self._proc = None
        if proc is None or proc.returncode is not None:
            return
        try:
            if proc.stdin is not None and not proc.stdin.is_closing():
                proc.stdin.close()
            await asyncio.wait_for(proc.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            self._kill_worker(proc)
            try:
                await proc.wait()
            except Exception:  # noqa: BLE001
                pass
        except ProcessLookupError:
            pass
        except Exception:  # noqa: BLE001
            logger.exception("template_render: close failed")


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_singleton: Optional[TemplateRenderClient] = None


def get_render_client() -> TemplateRenderClient:
    """Return the process-wide :class:`TemplateRenderClient` singleton.

    The supervisor is cheap to keep around (one worker pid, one pipe
    pair) and pooling is unnecessary at the documented call rate. If
    multi-worker throughput is ever required, replace this accessor
    with a small round-robin pool — the public ``render`` surface stays
    the same.
    """
    global _singleton
    if _singleton is None:
        _singleton = TemplateRenderClient()
    return _singleton


async def shutdown_render_client() -> None:
    """Tear down the singleton — used by tests + graceful orchestrator
    shutdown to release the worker subprocess."""
    global _singleton
    if _singleton is None:
        return
    client = _singleton
    _singleton = None
    await client.close()


__all__ = [
    "DEFAULT_RENDER_TIMEOUT_SECONDS",
    "RenderError",
    "ROTATION_THRESHOLD",
    "TemplateRenderClient",
    "get_render_client",
    "shutdown_render_client",
]
