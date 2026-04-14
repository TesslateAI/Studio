"""Runtime probe and tray-state endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import get_db
from ...models import AgentTask, Project, User
from ...users import current_active_user

logger = logging.getLogger(__name__)

router = APIRouter()

_RUNNING_PROJECT_LIMIT = 25
_RUNNING_AGENT_LIMIT = 25


@router.get("/runtime-probe")
async def runtime_probe(user: User = Depends(current_active_user)) -> dict[str, Any]:
    from . import _collect_runtimes

    return await _collect_runtimes(user)


async def _running_projects(db: AsyncSession, user: User) -> list[dict[str, Any]]:
    stmt = (
        select(Project)
        .where(Project.owner_id == user.id)
        .where(Project.last_activity.is_not(None))
        .order_by(Project.last_activity.desc())
        .limit(_RUNNING_PROJECT_LIMIT)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(row.id),
            "slug": row.slug,
            "name": row.name,
            "runtime": row.runtime,
            "last_activity": row.last_activity.isoformat() if row.last_activity else None,
        }
        for row in rows
    ]


async def _running_agents(db: AsyncSession, user: User) -> list[dict[str, Any]]:
    stmt = (
        select(AgentTask, Project.slug, Project.name)
        .join(Project, Project.id == AgentTask.project_id)
        .where(Project.owner_id == user.id)
        .where(AgentTask.status.in_(["running", "awaiting_approval", "queued"]))
        .order_by(AgentTask.created_at.desc())
        .limit(_RUNNING_AGENT_LIMIT)
    )
    rows = (await db.execute(stmt)).all()
    return [
        {
            "id": str(task.id),
            "ref_id": task.ref_id,
            "title": task.title,
            "status": task.status,
            "project_id": str(task.project_id),
            "project_slug": slug,
            "project_name": name,
            "created_at": task.created_at.isoformat() if task.created_at else None,
        }
        for task, slug, name in rows
    ]


@router.get("/tray-state")
async def tray_state(
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from . import _collect_runtimes

    runtimes = await _collect_runtimes(user)
    try:
        projects = await _running_projects(db, user)
    except Exception as exc:
        logger.debug("tray running_projects query failed: %s", exc)
        projects = []
    try:
        agents = await _running_agents(db, user)
    except Exception as exc:
        logger.debug("tray running_agents query failed: %s", exc)
        agents = []
    return {
        "runtimes": runtimes,
        "running_projects": projects,
        "running_agents": agents,
    }
