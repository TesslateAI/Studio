"""Install-time container materialization from the bundle's tesslate config.

The 2026-05 manifest deliberately drops the legacy ``compute.containers[]``
block — the App Runtime Contract treats the bundle CAS as the source of truth
for the container layout. Publish snapshots the source project's volume
(including ``.tesslate/config.json``); install creates a fresh volume from the
bundle, which means the new volume already carries that config.

This helper reads the config off the materialized volume via the orchestrator
file API (works under docker / k8s / desktop-local without conditional logic),
parses it through the canonical :func:`parse_tesslate_config`, and writes
``Container`` + ``ContainerConnection`` rows under the install's runtime
project. It is the install-time symmetric of
:func:`app.services.config_sync.ensure_config_synced` — same parser, same
container shape — but stays inside the caller's transaction (no file writes,
no commit) so install_app's saga semantics hold.

Why a separate module rather than reusing ``sync_project_config`` directly:
``sync_project_config`` rewrites ``.tesslate/config.json`` and commits at the
end. Install's transaction owns the AppInstance + AppRuntimeDeployment +
McpConsentRecord rows together; an early commit would leak partial state if
later steps fail. So we take the parser + container projection out and skip
the file-write half.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from ...models import Container, ContainerConnection, Project

if TYPE_CHECKING:
    from uuid import UUID

logger = logging.getLogger(__name__)


class BundleConfigMissing(Exception):
    """The materialized volume has no readable .tesslate/config.json.

    Raised when ``read_file`` returns falsy — either the bundle never carried
    a config (the publish-time inferrer should reject this) or the volume
    isn't wired up. Callers translate to ``IncompatibleAppError`` so the
    install path returns a clean 4xx instead of crashing mid-transaction.
    """


async def materialize_compute_from_volume(
    db: AsyncSession,
    *,
    project: Project,
    installer_user_id: UUID,
    volume_id: str | None,
    cache_node: str | None,
    runtime_env_overlay: dict[str, str] | None = None,
) -> tuple[dict[str, Container], Container | None]:
    """Read .tesslate/config.json from the install's volume and materialize.

    Side effects (all on ``db``, no commit):
      - One ``Container`` per ``config.apps`` entry (``container_type='base'``).
      - One ``Container`` per ``config.infrastructure`` entry
        (``container_type='service'``).
      - The container matching ``config.primaryApp`` (or the first app, if
        unspecified) is marked ``is_primary=True``.
      - ``ContainerConnection`` rows mirroring ``config.connections``
        (best-effort: connections referencing names not present in the
        config are logged and skipped — the publisher should have caught
        that, and a hard fail here would block install on cosmetic drift).

    Args:
        db: Active install transaction.
        project: The runtime ``Project`` row already inserted by the install.
        installer_user_id: Used by ``orchestrator.read_file`` for K8s ACLs.
        volume_id: The fresh Hub volume id (from ``create_volume_from_bundle``).
        cache_node: Cache node hint, passed through to the orchestrator.
        runtime_env_overlay: Per-pod runtime env (``OPENSAIL_RUNTIME_URL`` etc.)
            layered onto every container's ``environment_vars``. Manifest-
            declared values win — overlay only fills gaps.

    Returns:
        ``(containers_by_name, primary_container)`` so the caller can wire
        the AppInstance's ``primary_container_id`` and stamp the
        ``OPENSAIL_APPINSTANCE_TOKEN`` secret reference onto the primary.

    Raises:
        BundleConfigMissing: ``.tesslate/config.json`` could not be read.
        ValueError: Re-raised from :func:`parse_tesslate_config` for invalid
            JSON or unsafe startup commands; install_app translates these.
    """
    from ..base_config_parser import parse_tesslate_config
    from ..orchestration import get_orchestrator

    orchestrator = get_orchestrator()
    config_json = await orchestrator.read_file(
        user_id=installer_user_id,
        project_id=project.id,
        container_name=None,
        file_path=".tesslate/config.json",
        project_slug=project.slug,
        volume_id=volume_id,
        cache_node=cache_node,
    )
    if not config_json:
        raise BundleConfigMissing(
            f"bundle volume {volume_id!r} has no readable .tesslate/config.json — "
            "publish-time inferrer should have rejected the manifest"
        )

    config = parse_tesslate_config(config_json)
    if not config.apps and not config.infrastructure:
        raise BundleConfigMissing(
            "parsed .tesslate/config.json is empty (no apps, no infrastructure)"
        )

    overlay = dict(runtime_env_overlay or {})
    containers_by_name: dict[str, Container] = {}

    # primaryApp wins; otherwise first inserted base container is primary.
    primary_app_name = config.primaryApp or (
        next(iter(config.apps)) if config.apps else None
    )

    for app_name, app_cfg in config.apps.items():
        env: dict[str, str] = dict(app_cfg.env or {})
        for key, value in overlay.items():
            env.setdefault(key, value)

        container = Container(
            project_id=project.id,
            name=app_name,
            directory=app_cfg.directory or ".",
            container_name=f"{project.slug}-{app_name}",
            port=app_cfg.port or None,
            internal_port=app_cfg.port or None,
            environment_vars=env,
            startup_command=app_cfg.start or None,
            build_command=app_cfg.build or None,
            output_directory=app_cfg.output or None,
            framework=app_cfg.framework or None,
            exports=app_cfg.exports or None,
            container_type="base",
            status="stopped",
            is_primary=(app_name == primary_app_name),
            position_x=app_cfg.x if app_cfg.x is not None else 200,
            position_y=app_cfg.y if app_cfg.y is not None else 200,
        )
        db.add(container)
        containers_by_name[app_name] = container

    for infra_name, infra_cfg in config.infrastructure.items():
        # Infra containers don't get the runtime overlay — those env values
        # are app-pod concerns (the SDK runs in the app, not in postgres).
        infra_env: dict[str, str] = dict(infra_cfg.env or {})

        container = Container(
            project_id=project.id,
            name=infra_name,
            directory=".",
            container_name=f"{project.slug}-{infra_name}",
            port=infra_cfg.port or None,
            internal_port=infra_cfg.port or None,
            environment_vars=infra_env,
            exports=infra_cfg.exports or None,
            container_type="service",
            service_slug=infra_name,
            image=infra_cfg.image or None,
            deployment_mode=(
                "external" if infra_cfg.infra_type == "external" else "container"
            ),
            external_endpoint=infra_cfg.endpoint,
            status="stopped",
            position_x=infra_cfg.x if infra_cfg.x is not None else 400,
            position_y=infra_cfg.y if infra_cfg.y is not None else 400,
        )
        db.add(container)
        containers_by_name[infra_name] = container

    # Flush so ContainerConnection FK refs resolve. Caller still owns the TXN.
    await db.flush()

    primary: Container | None = (
        containers_by_name.get(primary_app_name) if primary_app_name else None
    )

    for conn in config.connections:
        source = containers_by_name.get(conn.from_node)
        target = containers_by_name.get(conn.to_node)
        if source is None or target is None:
            logger.warning(
                "install_compute_materializer: skipping connection %r->%r "
                "(unknown container name) project=%s",
                conn.from_node,
                conn.to_node,
                project.id,
            )
            continue
        db.add(
            ContainerConnection(
                project_id=project.id,
                source_container_id=source.id,
                target_container_id=target.id,
                connector_type="env_injection",
                connection_type="depends_on",
            )
        )

    logger.info(
        "install_compute_materializer: project=%s materialized %d containers "
        "(primary=%r) + %d connections from bundle config.json",
        project.id,
        len(containers_by_name),
        primary_app_name,
        len(config.connections),
    )
    return containers_by_name, primary
