"""Desktop tray/shell router package.

All endpoints mount under ``/api/desktop`` and require an authenticated
session via ``current_active_user``. Submodules:

    tray         — runtime probe, tray state
    auth         — cloud pairing (auth/status, auth/token)
    tickets      — agent tickets list + approve
    directories  — directory CRUD + git-root detection
    sessions     — agent sessions + per-ticket diff
    projects     — project import + sync push/pull/status
    handoff      — agent handoff push/pull via cloud

Non-blocking contract: probes and cloud calls that fail unexpectedly must
degrade to a well-formed payload — the desktop shell polls these endpoints
and must never observe a 5xx caused by an unreachable probe or cloud.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ...models import User
from ...services import sync_client  # noqa: F401  (re-exported for tests)
from ...services.runtime_probe import get_runtime_probe
from . import auth, directories, handoff, projects, sessions, tickets, tray
from ._helpers import (
    _canonical_path,
    _detect_git_root,
    _load_project,
    _map_sync_error,
    _safe_probe,
    _serialize_directory,
    _serialize_session,
    _serialize_ticket,
)
from .auth import CloudTokenBody
from .directories import DirectoryCreate
from .handoff import HandoffPullBody
from .projects import DesktopImportBody


async def _collect_runtimes(user: User) -> dict[str, dict[str, Any]]:
    """Collect runtime probes. Looks up ``get_runtime_probe`` via this module
    so tests can monkeypatch ``desktop.get_runtime_probe``.
    """
    probe = get_runtime_probe()
    return {
        "local": await _safe_probe(probe.local_available()),
        "docker": await _safe_probe(probe.docker_available()),
        "k8s": await _safe_probe(probe.k8s_remote_available(user=user)),
    }


router = APIRouter(prefix="/api/desktop", tags=["desktop"])
router.include_router(tray.router)
router.include_router(auth.router)
router.include_router(tickets.router)
router.include_router(directories.router)
router.include_router(sessions.router)
router.include_router(projects.router)
router.include_router(handoff.router)

__all__ = [
    "router",
    "get_runtime_probe",
    "_collect_runtimes",
    "_safe_probe",
    "_canonical_path",
    "_detect_git_root",
    "_load_project",
    "_map_sync_error",
    "_serialize_ticket",
    "_serialize_directory",
    "_serialize_session",
    "CloudTokenBody",
    "DirectoryCreate",
    "DesktopImportBody",
    "HandoffPullBody",
]
