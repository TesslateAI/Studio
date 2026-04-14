"""Shared helpers and serializers for the desktop router package."""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AgentTask, Directory, Project, User
from ...services import sync_client
from ...services.cloud_client import CircuitOpenError, NotPairedError
from ...services.runtime_probe import ProbeResult, get_runtime_probe

logger = logging.getLogger(__name__)


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


def _canonical_path(raw: str) -> str:
    """Normalize a user-supplied path for dedup (absolute, no trailing slash)."""
    expanded = os.path.expanduser(raw)
    try:
        resolved = str(Path(expanded).resolve(strict=False))
    except (OSError, RuntimeError):
        resolved = os.path.abspath(expanded)
    return resolved.rstrip(os.sep) or resolved


def _detect_git_root(path: str) -> str | None:
    """Walk up from ``path`` looking for a ``.git`` entry; return that dir or None."""
    try:
        current = Path(path).resolve(strict=False)
    except (OSError, RuntimeError):
        current = Path(path)
    for candidate in [current, *current.parents]:
        if (candidate / ".git").exists():
            return str(candidate)
    return None


def _serialize_ticket(ticket: AgentTask) -> dict[str, Any]:
    return {
        "id": str(ticket.id),
        "ref_id": ticket.ref_id,
        "project_id": str(ticket.project_id),
        "parent_task_id": str(ticket.parent_task_id) if ticket.parent_task_id else None,
        "status": ticket.status,
        "title": ticket.title,
        "assignee_agent_id": (
            str(ticket.assignee_agent_id) if ticket.assignee_agent_id else None
        ),
        "requires_approval_for": ticket.requires_approval_for or [],
        "goal_ancestry": ticket.goal_ancestry or [],
        "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
        "updated_at": ticket.updated_at.isoformat() if ticket.updated_at else None,
        "completed_at": ticket.completed_at.isoformat() if ticket.completed_at else None,
    }


def _serialize_directory(directory: Directory) -> dict[str, Any]:
    return {
        "id": str(directory.id),
        "path": directory.path,
        "runtime": directory.runtime,
        "project_id": str(directory.project_id) if directory.project_id else None,
        "git_root": directory.git_root,
        "last_opened_at": (
            directory.last_opened_at.isoformat() if directory.last_opened_at else None
        ),
        "created_at": directory.created_at.isoformat() if directory.created_at else None,
    }


def _serialize_session(ticket: AgentTask) -> dict[str, Any]:
    base = _serialize_ticket(ticket)
    base["source"] = "local"
    base["directories"] = [
        {"id": str(d.id), "path": d.path} for d in (ticket.directories or [])
    ]
    return base


async def _load_project(
    project_id: uuid.UUID, user: User, db: AsyncSession
) -> Project:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    if project.owner_id is not None and project.owner_id != user.id:
        raise HTTPException(status_code=404, detail="project not found")
    return project


def _map_sync_error(exc: Exception) -> HTTPException:
    if isinstance(exc, NotPairedError):
        return HTTPException(status_code=401, detail="cloud not paired")
    if isinstance(exc, sync_client.ConflictError):
        return HTTPException(
            status_code=409,
            detail={
                "message": str(exc),
                "cloud_updated_at": getattr(exc, "cloud_updated_at", None),
            },
        )
    if isinstance(exc, CircuitOpenError):
        return HTTPException(status_code=502, detail=f"cloud unavailable: {exc}")
    if isinstance(exc, sync_client.SyncError):
        return HTTPException(status_code=502, detail=str(exc))
    return HTTPException(status_code=500, detail="unexpected sync error")
