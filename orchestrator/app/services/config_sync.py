"""
Config sync service — bidirectional .tesslate/config.json ↔ DB sync.

Two directions:
  - DB → Config:  build_config_from_db()   reads canvas state, produces TesslateProjectConfig.
                  Used when a user clicks "Save Config" on the canvas.
  - Config → DB:  sync_project_config()    writes .tesslate/config.json AND replaces the
                  project's container/connection/deployment/preview graph in one transaction.
                  Used by the setup-config HTTP route and the apply_setup_config agent tool.

Auto-sync helper:
  - ensure_config_synced()  reads .tesslate/config.json from disk (or PVC) and
                            applies it via sync_project_config. Non-blocking on
                            failure — start/restart paths call this so config.json
                            is the source of truth without a separate setup-config call.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..models import (
    BrowserPreview,
    Container,
    ContainerConnection,
    DeploymentTarget,
    DeploymentTargetConnection,
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
from .secret_manager_env import container_env

if TYPE_CHECKING:
    from ..schemas import SetupConfigSyncResponse, TesslateConfigCreate

logger = logging.getLogger(__name__)


class ConfigSyncError(ValueError):
    """Raised when sync_project_config cannot complete (e.g., invalid startup command)."""


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
        # Emits plaintext env vars plus decrypted secrets — legacy base64
        # rows are detected and handled (with a structured warning).
        decoded_env = container_env(c) if (c.environment_vars or c.encrypted_secrets) else {}

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


async def sync_project_config(
    db: AsyncSession,
    project: Project,
    config_data: TesslateConfigCreate,
    user_id: UUID,
) -> SetupConfigSyncResponse:
    """Write .tesslate/config.json and replace the project's graph to match.

    Full-graph sync: containers (app + infrastructure), connections, deployment
    targets, and previews are updated to exactly mirror ``config_data``. Entries
    absent from the config are deleted. The caller is responsible for resolving
    the project and checking permissions before calling this.

    Args:
        db: Active async session. Committed at the end.
        project: Project model (already loaded).
        config_data: ``TesslateConfigCreate`` Pydantic object (see schemas.py).
        user_id: Owner UUID — used for orchestrator file writes in K8s mode.

    Returns:
        ``SetupConfigSyncResponse`` with ``container_ids`` and
        ``primary_container_id``.

    Raises:
        ConfigSyncError: A startup command failed validation.
    """
    # Imports are deferred to avoid pulling heavy modules at service import time.
    from ..config import get_settings
    from ..schemas import SetupConfigSyncResponse
    from .base_config_parser import (
        serialize_config_to_json,
        validate_startup_command,
        write_tesslate_config,
    )

    settings = get_settings()

    for app_name, app_data in config_data.apps.items():
        if app_data.start:
            is_valid, error = validate_startup_command(app_data.start)
            if not is_valid:
                raise ConfigSyncError(
                    f"App '{app_name}' has invalid start command: {error}"
                )

    config = TesslateProjectConfig(
        apps={
            name: AppConfig(
                directory=app.directory,
                port=app.port,
                start=app.start,
                build=app.build or None,
                output=app.output or None,
                framework=app.framework or None,
                env=app.env,
                exports=app.exports,
                x=app.x,
                y=app.y,
            )
            for name, app in config_data.apps.items()
        },
        infrastructure={
            name: InfraConfig(
                image=infra.image or "",
                port=infra.port or 5432,
                env=infra.env,
                exports=infra.exports,
                infra_type=infra.type or "container",
                provider=infra.provider,
                endpoint=infra.endpoint,
                x=infra.x,
                y=infra.y,
            )
            for name, infra in config_data.infrastructure.items()
        },
        connections=[
            ConnectionConfig(from_node=c.from_node, to_node=c.to_node)
            for c in config_data.connections
        ],
        deployments={
            name: DeploymentConfig(
                provider=dep.provider,
                targets=dep.targets,
                env=dep.env,
                x=dep.x,
                y=dep.y,
            )
            for name, dep in config_data.deployments.items()
        },
        previews={
            name: PreviewConfig(
                target=prev.target,
                x=prev.x,
                y=prev.y,
            )
            for name, prev in config_data.previews.items()
        },
        primaryApp=config_data.primaryApp,
    )

    if settings.deployment_mode == "docker":
        write_tesslate_config(f"/projects/{project.slug}", config)
    else:
        from .orchestration import get_orchestrator

        orchestrator = get_orchestrator()
        await orchestrator.write_file(
            user_id=user_id,
            project_id=project.id,
            container_name=None,
            file_path=".tesslate/config.json",
            content=serialize_config_to_json(config),
            project_slug=project.slug,
            volume_id=project.volume_id,
            cache_node=project.cache_node,
        )

    container_ids: list[str] = []
    primary_container_id: str | None = None

    existing_result = await db.execute(
        select(Container).where(Container.project_id == project.id)
    )
    existing_containers = {c.name: c for c in existing_result.scalars().all()}

    for app_name, app_config in config.apps.items():
        if app_name in existing_containers:
            container = existing_containers[app_name]
            container.directory = app_config.directory
            container.internal_port = app_config.port or 3000
            container.environment_vars = (
                dict(app_config.env) if app_config.env else {}
            )
            container.exports = app_config.exports or None
            container.startup_command = app_config.start or None
            container.build_command = app_config.build or None
            container.output_directory = app_config.output or None
            container.framework = app_config.framework or None
            if app_config.x is not None:
                container.position_x = app_config.x
            if app_config.y is not None:
                container.position_y = app_config.y
            del existing_containers[app_name]
        else:
            container = Container(
                project_id=project.id,
                name=app_name,
                directory=app_config.directory,
                container_name=f"{project.slug}-{app_name}",
                internal_port=app_config.port or 3000,
                environment_vars=(
                    dict(app_config.env) if app_config.env else {}
                ),
                exports=app_config.exports or None,
                startup_command=app_config.start or None,
                build_command=app_config.build or None,
                output_directory=app_config.output or None,
                framework=app_config.framework or None,
                container_type="base",
                status="stopped",
                position_x=app_config.x or 200,
                position_y=app_config.y or 200,
            )
            db.add(container)

        await db.flush()
        await db.refresh(container)
        container_ids.append(str(container.id))
        if app_name == config.primaryApp:
            primary_container_id = str(container.id)

    for infra_name, infra_config in config.infrastructure.items():
        if infra_name in existing_containers:
            container = existing_containers[infra_name]
            container.internal_port = infra_config.port
            container.environment_vars = (
                dict(infra_config.env)
                if infra_config.env
                else container.environment_vars
            )
            container.exports = infra_config.exports or None
            container.deployment_mode = (
                infra_config.infra_type
                if infra_config.infra_type == "external"
                else "container"
            )
            container.external_endpoint = infra_config.endpoint
            if infra_config.x is not None:
                container.position_x = infra_config.x
            if infra_config.y is not None:
                container.position_y = infra_config.y
            del existing_containers[infra_name]
        else:
            container = Container(
                project_id=project.id,
                name=infra_name,
                directory=".",
                container_name=f"{project.slug}-{infra_name}",
                internal_port=infra_config.port,
                environment_vars=(
                    dict(infra_config.env) if infra_config.env else {}
                ),
                exports=infra_config.exports or None,
                container_type="service",
                service_slug=infra_name,
                deployment_mode=(
                    "external" if infra_config.infra_type == "external" else "container"
                ),
                external_endpoint=infra_config.endpoint,
                status="stopped",
                position_x=infra_config.x or 400,
                position_y=infra_config.y or 400,
            )
            db.add(container)

        await db.flush()
        await db.refresh(container)
        container_ids.append(str(container.id))

    for orphan_name, orphan_container in existing_containers.items():
        logger.info("[config_sync] Deleting orphaned container: %s", orphan_name)
        await db.delete(orphan_container)

    all_containers_result = await db.execute(
        select(Container).where(Container.project_id == project.id)
    )
    container_by_name = {c.name: c for c in all_containers_result.scalars().all()}

    existing_conns = await db.execute(
        select(ContainerConnection).where(ContainerConnection.project_id == project.id)
    )
    for conn in existing_conns.scalars().all():
        await db.delete(conn)

    for conn_config in config.connections:
        source = container_by_name.get(conn_config.from_node)
        target = container_by_name.get(conn_config.to_node)
        if source and target:
            db.add(
                ContainerConnection(
                    project_id=project.id,
                    source_container_id=source.id,
                    target_container_id=target.id,
                    connector_type="env_injection",
                    connection_type="depends_on",
                )
            )

    existing_targets = await db.execute(
        select(DeploymentTarget).where(DeploymentTarget.project_id == project.id)
    )
    for target in existing_targets.scalars().all():
        await db.delete(target)
    await db.flush()

    for dep_name, dep_config in config.deployments.items():
        dep_target = DeploymentTarget(
            project_id=project.id,
            provider=dep_config.provider,
            name=dep_name,
            deployment_env=dep_config.env or None,
            position_x=dep_config.x or 0,
            position_y=dep_config.y or 0,
        )
        db.add(dep_target)
        await db.flush()
        await db.refresh(dep_target)

        for target_app_name in dep_config.targets:
            target_container = container_by_name.get(target_app_name)
            if target_container:
                db.add(
                    DeploymentTargetConnection(
                        project_id=project.id,
                        container_id=target_container.id,
                        deployment_target_id=dep_target.id,
                        deployment_settings=dep_config.env or {},
                    )
                )

    existing_previews = await db.execute(
        select(BrowserPreview).where(BrowserPreview.project_id == project.id)
    )
    for preview in existing_previews.scalars().all():
        await db.delete(preview)

    for _preview_name, preview_config in config.previews.items():
        target_container = container_by_name.get(preview_config.target)
        db.add(
            BrowserPreview(
                project_id=project.id,
                connected_container_id=target_container.id if target_container else None,
                position_x=preview_config.x or 0,
                position_y=preview_config.y or 0,
                current_path="/",
            )
        )

    await db.commit()

    return SetupConfigSyncResponse(
        container_ids=container_ids,
        primary_container_id=primary_container_id,
    )


async def ensure_config_synced(
    db: AsyncSession,
    project: Project,
    user_id: UUID,
) -> bool:
    """Read ``.tesslate/config.json`` from disk/PVC and sync it to the DB.

    Called from start/restart endpoints so edits to ``config.json`` propagate
    to the Container model without a separate ``POST /setup-config`` call.

    Non-blocking: any failure (missing file, parse error, sync error) is
    logged and swallowed. The caller continues with whatever is already in
    the DB. Returns True iff a sync actually ran.
    """
    import json

    from ..schemas import TesslateConfigCreate
    from .base_config_parser import (
        parse_tesslate_config,
        read_tesslate_config,
        serialize_config_to_json,
    )
    from .project_fs import get_project_fs_path

    try:
        config_obj = None
        fs_path = get_project_fs_path(project)
        if fs_path is not None:
            config_obj = read_tesslate_config(str(fs_path))
        else:
            from .orchestration import get_orchestrator

            orchestrator = get_orchestrator()
            config_json = await orchestrator.read_file(
                user_id=user_id,
                project_id=project.id,
                container_name=None,
                file_path=".tesslate/config.json",
                project_slug=project.slug,
                volume_id=getattr(project, "volume_id", None),
                cache_node=getattr(project, "cache_node", None),
            )
            if config_json:
                config_obj = parse_tesslate_config(config_json)

        if config_obj is None or not config_obj.apps:
            return False

        # Round-trip through serialize_config_to_json so the payload exactly
        # matches the JSON shape TesslateConfigCreate expects (including the
        # `from`/`to` aliases on connections). Avoids field-name skew between
        # the parser dataclasses and the API schema.
        payload = json.loads(serialize_config_to_json(config_obj))
        if not payload.get("primaryApp") and config_obj.apps:
            payload["primaryApp"] = next(iter(config_obj.apps))

        cfg_create = TesslateConfigCreate(**payload)

        await sync_project_config(db, project, cfg_create, user_id)
        logger.info(
            "[CONFIG-SYNC] Auto-synced .tesslate/config.json for project %s",
            project.slug,
        )
        return True
    except Exception as exc:
        logger.warning(
            "[CONFIG-SYNC] Auto-sync of .tesslate/config.json failed for project %s: %s — continuing with existing DB state",
            getattr(project, "slug", "?"),
            exc,
        )
        return False
