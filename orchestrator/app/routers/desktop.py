"""Desktop tray/shell support endpoints.

Thin, always-responsive endpoints consumed by the desktop client:

- ``GET /api/desktop/runtime-probe`` — which runtimes (local/docker/k8s) the
  orchestrator can currently reach.
- ``GET /api/desktop/tray-state`` — tray summary (runtimes + placeholders for
  running projects/agents).

Non-blocking contract: even if a probe raises unexpectedly, the endpoint
returns a well-formed payload with ``ok=False`` and a reason string. The
desktop shell polls these endpoints and must never see a 5xx from a probe.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends

from ..models import User
from ..services.runtime_probe import ProbeResult, get_runtime_probe
from ..users import current_active_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/desktop", tags=["desktop"])


async def _safe_probe(coro) -> dict[str, Any]:
    """Run a probe coroutine, never raising. Unexpected failures become ok=False."""
    try:
        result: ProbeResult = await coro
        return result.to_dict()
    except Exception as exc:  # pragma: no cover - defense-in-depth
        logger.warning("runtime probe raised unexpectedly: %s", exc)
        return {"ok": False, "reason": "Probe failed"}


async def _collect_runtimes(user: User) -> dict[str, dict[str, Any]]:
    probe = get_runtime_probe()
    return {
        "local": await _safe_probe(probe.local_available()),
        "docker": await _safe_probe(probe.docker_available()),
        "k8s": await _safe_probe(probe.k8s_remote_available(user=user)),
    }


@router.get("/runtime-probe")
async def runtime_probe(user: User = Depends(current_active_user)) -> dict[str, Any]:
    return await _collect_runtimes(user)


@router.get("/tray-state")
async def tray_state(user: User = Depends(current_active_user)) -> dict[str, Any]:
    return {
        "runtimes": await _collect_runtimes(user),
        "running_projects": [],
        "running_agents": [],
    }
