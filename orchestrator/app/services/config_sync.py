"""
Config sync service — builds config.json from DB state.

DB → Config: build_config_from_db() reads all canvas entities and produces a TesslateProjectConfig.
This is called when the user clicks "Save Config" on the canvas.
"""

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import (
    BrowserPreview,
    Container,
    ContainerConnection,
    DeploymentTarget,
    Project,
)
from .base_config_parser import (
    AppConfig,
    ConnectionConfig,
    DeploymentConfig,
    InfraConfig,
    PreviewConfig,
    TesslateProjectConfig,
)
from .secret_codec import decode_secret_map

logger = logging.getLogger(__name__)


async def build_config_from_db(
    db: AsyncSession, project_id: UUID
) -> TesslateProjectConfig:
    """Read all canvas state from DB and build a complete TesslateProjectConfig."""
    config = TesslateProjectConfig()

    # 1. Load containers
    containers_result = await db.execute(
        select(Container).where(Container.project_id == project_id)
    )
    containers = containers_result.scalars().all()
    container_name_by_id: dict[str, str] = {str(c.id): c.name for c in containers}

    for c in containers:
        # Decode base64-encoded env vars to plain text for config output
        decoded_env = decode_secret_map(c.environment_vars) if c.environment_vars else {}

        if c.container_type == "base":
            config.apps[c.name] = AppConfig(
                directory=c.directory or ".",
                port=c.internal_port or c.port or 3000,
                start=c.startup_command or "",
                build=c.build_command or None,
                output=c.output_directory or None,
                framework=c.framework or None,
                env=decoded_env,
                exports=c.exports or {},
                x=c.position_x,
                y=c.position_y,
            )
        elif c.container_type == "service":
            infra = InfraConfig(
                port=c.internal_port or c.port or 5432,
                env=decoded_env,
                exports=c.exports or {},
                x=c.position_x,
                y=c.position_y,
            )
            if c.deployment_mode == "external":
                infra.infra_type = "external"
                infra.endpoint = c.external_endpoint
            else:
                from .service_definitions import get_service

                svc_def = get_service(c.service_slug) if c.service_slug else None
                infra.image = (
                    svc_def.docker_image
                    if svc_def
                    else f"{c.service_slug or 'unknown'}:latest"
                )
            config.infrastructure[c.name] = infra

    # 2. Load connections
    conns_result = await db.execute(
        select(ContainerConnection).where(
            ContainerConnection.project_id == project_id
        )
    )
    for conn in conns_result.scalars().all():
        from_name = container_name_by_id.get(str(conn.source_container_id), "")
        to_name = container_name_by_id.get(str(conn.target_container_id), "")
        if from_name and to_name:
            config.connections.append(
                ConnectionConfig(from_node=from_name, to_node=to_name)
            )

    # 3. Load deployment targets
    targets_result = await db.execute(
        select(DeploymentTarget)
        .where(DeploymentTarget.project_id == project_id)
        .options(selectinload(DeploymentTarget.connected_containers))
    )
    for target in targets_result.scalars().all():
        target_containers = [
            container_name_by_id.get(str(dtc.container_id), "")
            for dtc in target.connected_containers
        ]
        deploy_key = target.name or f"{target.provider}-{int(target.position_x or 0)}"
        config.deployments[deploy_key] = DeploymentConfig(
            provider=target.provider,
            targets=[n for n in target_containers if n],
            env=target.deployment_env or {},
            x=target.position_x,
            y=target.position_y,
        )

    # 4. Load previews
    previews_result = await db.execute(
        select(BrowserPreview).where(BrowserPreview.project_id == project_id)
    )
    for i, preview in enumerate(previews_result.scalars().all()):
        connected_name = (
            container_name_by_id.get(str(preview.connected_container_id), "")
            if preview.connected_container_id
            else ""
        )
        config.previews[f"preview-{i + 1}"] = PreviewConfig(
            target=connected_name,
            x=preview.position_x,
            y=preview.position_y,
        )

    # 5. Primary app — use first app as primary
    if config.apps:
        config.primaryApp = next(iter(config.apps))

    return config
