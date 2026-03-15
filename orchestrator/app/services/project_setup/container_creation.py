"""Create Container DB records from a parsed TesslateProjectConfig.

This module is the single source of truth for translating a
TesslateProjectConfig (parsed from .tesslate/config.json) into persisted
Container rows.  It deliberately does **no** filesystem work, template
copying, or orchestrator calls -- just database writes.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Container
from ...services.base_config_parser import TesslateProjectConfig
from .naming import sanitize_name

logger = logging.getLogger(__name__)


async def create_containers(
    config: TesslateProjectConfig,
    project_id: UUID,
    project_slug: str,
    base_id: UUID | None,
    db: AsyncSession,
) -> tuple[str | None, list[str]]:
    """Create Container records from *config*.

    Returns
    -------
    tuple[str | None, list[str]]
        ``(primary_container_id, all_container_ids)`` where
        *primary_container_id* is the id of the container matching
        ``config.primaryApp``, falling back to the first container created
        if no match is found.  Never returns ``"needs_setup"``.
    """

    primary_container_id: str | None = None
    all_container_ids: list[str] = []

    # ------------------------------------------------------------------
    # App containers (user-facing services: frontend, backend, etc.)
    # ------------------------------------------------------------------
    for app_name, app_config in config.apps.items():
        container = Container(
            project_id=project_id,
            base_id=base_id,
            name=app_name,
            directory=app_config.directory,
            container_name=f"{project_slug}-{sanitize_name(app_name)}",
            internal_port=app_config.port or 3000,
            startup_command=app_config.start or None,
            environment_vars=app_config.env or {},
            container_type="base",
            status="stopped",
            position_x=app_config.x or 200,
            position_y=app_config.y or 200,
        )
        db.add(container)

        # Flush to materialise the server-generated ``id``.
        await db.flush()

        cid = str(container.id)
        all_container_ids.append(cid)

        if app_name == config.primaryApp:
            primary_container_id = cid

        logger.info(
            "Created app container %s (%s) for project %s",
            app_name,
            cid,
            project_id,
        )

    # ------------------------------------------------------------------
    # Infrastructure containers (postgres, redis, etc.)
    # ------------------------------------------------------------------
    for infra_name, infra_config in config.infrastructure.items():
        container = Container(
            project_id=project_id,
            name=infra_name,
            directory=".",
            container_name=f"{project_slug}-{sanitize_name(infra_name)}",
            internal_port=infra_config.port,
            container_type="service",
            service_slug=infra_name,
            status="stopped",
            position_x=infra_config.x or 400,
            position_y=infra_config.y or 400,
        )
        db.add(container)
        await db.flush()

        cid = str(container.id)
        all_container_ids.append(cid)

        logger.info(
            "Created infra container %s (%s) for project %s",
            infra_name,
            cid,
            project_id,
        )

    # ------------------------------------------------------------------
    # Resolve primary — fall back to first container if no explicit match.
    # ------------------------------------------------------------------
    if primary_container_id is None and all_container_ids:
        primary_container_id = all_container_ids[0]
        logger.info(
            "No primaryApp match; defaulting primary to %s",
            primary_container_id,
        )

    await db.commit()

    logger.info(
        "Container creation complete for project %s: primary=%s, total=%d",
        project_id,
        primary_container_id,
        len(all_container_ids),
    )

    return primary_container_id, all_container_ids
