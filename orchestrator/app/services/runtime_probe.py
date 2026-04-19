"""Runtime availability probes.

Lightweight, non-blocking checks for which execution runtimes the orchestrator
can currently reach. Used by the desktop tray/UI to gate project-creation
choices (local vs docker vs cloud k8s) without performing a full orchestration
round-trip.

Every probe is bounded and never raises: a failed probe returns a well-formed
``ProbeResult`` with ``ok=False`` and a human-readable ``reason``.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    reason: str | None = None

    def to_dict(self) -> dict:
        return {"ok": self.ok, "reason": self.reason}


_DOCKER_CACHE_TTL_SECONDS = 30.0
_DOCKER_PROBE_TIMEOUT_SECONDS = 3.0


class RuntimeProbe:
    """Async runtime probes with bounded caching."""

    def __init__(self) -> None:
        self._docker_cache: tuple[float, ProbeResult] | None = None
        self._docker_lock = asyncio.Lock()

    async def local_available(self) -> ProbeResult:
        """The local runtime is always available — it's the orchestrator process itself."""
        return ProbeResult(ok=True, reason=None)

    async def docker_available(self) -> ProbeResult:
        """Probe the Docker daemon by shelling ``docker info --format json``.

        Cached for 30s (monotonic clock) so the tray can poll freely.
        Never raises; failures become ``ok=False`` with a reason.
        """
        now = time.monotonic()
        cached = self._docker_cache
        if cached is not None and (now - cached[0]) < _DOCKER_CACHE_TTL_SECONDS:
            return cached[1]

        async with self._docker_lock:
            # Re-check under lock to avoid dogpile.
            now = time.monotonic()
            cached = self._docker_cache
            if cached is not None and (now - cached[0]) < _DOCKER_CACHE_TTL_SECONDS:
                return cached[1]

            result = await self._probe_docker()
            self._docker_cache = (time.monotonic(), result)
            return result

    async def _probe_docker(self) -> ProbeResult:
        unreachable = ProbeResult(ok=False, reason="Docker daemon unreachable")
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "info",
                "--format",
                "json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, _stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=_DOCKER_PROBE_TIMEOUT_SECONDS
                )
            except TimeoutError:
                with _suppress():
                    proc.kill()
                    await proc.wait()
                return unreachable

            if proc.returncode != 0:
                return unreachable

            # Best-effort parse: `docker info --format json` returns a JSON object
            # when the daemon is reachable. If parsing fails, treat as unreachable.
            try:
                data = json.loads(stdout.decode("utf-8", errors="replace"))
            except (ValueError, UnicodeDecodeError):
                return unreachable

            if not isinstance(data, dict):
                return unreachable

            # Daemon errors still exit 0 but include a top-level `ServerErrors`
            # list; treat non-empty errors as unreachable.
            server_errors = data.get("ServerErrors")
            if server_errors:
                return unreachable

            return ProbeResult(ok=True, reason=None)
        except (FileNotFoundError, OSError):
            return unreachable
        except Exception:
            # Defensive: probe must never propagate.
            return unreachable

    async def k8s_remote_available(self, user=None) -> ProbeResult:
        """Remote (cloud) k8s requires pairing. Stubbed until pairing lands."""
        return ProbeResult(ok=False, reason="Cloud pairing required")


class _suppress:
    """Tiny no-raise context manager used instead of contextlib in the hot path."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, tb) -> bool:
        return True


_singleton: RuntimeProbe | None = None


def get_runtime_probe() -> RuntimeProbe:
    global _singleton
    if _singleton is None:
        _singleton = RuntimeProbe()
    return _singleton
