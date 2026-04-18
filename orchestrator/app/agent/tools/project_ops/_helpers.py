"""Shared lookup helpers for project_ops agent tools.

These used to live inside ``project_control.py`` when it was the one tool
that wrapped every lifecycle action. Now that lifecycle is split across
``project_control``, ``project_lifecycle``, ``container_lifecycle``, and
``setup_config``, the helpers have moved here so every tool imports from
one place.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ....models import Container as ContainerModel
    from ....models import ContainerConnection as ContainerConnectionModel
    from ....models import Project as ProjectModel

logger = logging.getLogger(__name__)


async def resolve_container_dir(project_id, container) -> str:
    """Resolve the K8s deployment directory key for *container*.

    Reads live pod labels (source of truth) first; falls back to the
    centralised helper that sanitises ``container.directory``.
    """
    from ....services.orchestration import get_orchestrator, is_kubernetes_mode

    if is_kubernetes_mode():
        try:
            orchestrator = get_orchestrator()
            status = await orchestrator.get_project_status("", project_id)
            cid = str(container.id)
            for dir_key, info in status.get("containers", {}).items():
                if info.get("container_id") == cid:
                    return dir_key
        except Exception:
            logger.debug(
                "K8s status lookup failed for container %s, using fallback",
                container.id,
                exc_info=True,
            )

    from ....services.compute_manager import resolve_k8s_container_dir

    return resolve_k8s_container_dir(container)


async def lookup_container_by_name(
    db: AsyncSession, project_id, container_name: str
) -> ContainerModel | None:
    """Return a Container model matched by name, or ``None``."""
    from ....models import Container

    result = await db.execute(
        select(Container).where(
            Container.name == container_name,
            Container.project_id == project_id,
        )
    )
    return result.scalar_one_or_none()


async def fetch_project(db: AsyncSession, project_id) -> ProjectModel | None:
    """Return the Project model for *project_id*, or ``None``."""
    from ....models import Project

    result = await db.execute(select(Project).where(Project.id == project_id))
    return result.scalar_one_or_none()


async def fetch_all_containers(
    db: AsyncSession, project_id
) -> list[ContainerModel]:
    """Return all Container models (with base eagerly loaded) for the project."""
    from ....models import Container

    result = await db.execute(
        select(Container)
        .where(Container.project_id == project_id)
        .options(selectinload(Container.base))
    )
    return list(result.scalars().all())


async def fetch_connections(
    db: AsyncSession, project_id
) -> list[ContainerConnectionModel]:
    """Return all ContainerConnection models for the project."""
    from ....models import ContainerConnection

    result = await db.execute(
        select(ContainerConnection).where(ContainerConnection.project_id == project_id)
    )
    return list(result.scalars().all())


def require_project_context(context: dict[str, Any]) -> tuple[Any, Any, Any] | None:
    """Return (db, user_id, project_id) if present, else ``None``.

    Used by every project_ops tool as the first step of its executor. When
    any is missing, the caller should return an ``error_output`` pointing
    at the missing context — see existing examples in project_control.py.
    """
    db = context.get("db")
    user_id = context.get("user_id")
    project_id = context.get("project_id")
    if not db or not user_id or not project_id:
        return None
    return db, user_id, project_id
