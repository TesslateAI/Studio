"""``get_project_config`` — read-only inspection of the project's Config tab.

Lets the agent see what services / internal containers / deployment providers
are already configured before deciding whether to add a new node. Returns key
names only — never plaintext, never the ``__SET__`` sentinel — so the agent
can't accidentally exfiltrate secrets through it.

Use this before calling ``request_node_config`` to avoid duplicates. If a
matching node already exists, prefer ``request_node_config(mode='edit',
container_id=...)`` so the user updates the existing card.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select

from ....models import Container
from ....services.node_config_presets import FormSchema, resolve_schema
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)


def _resolve_schema_for_container(container: Container) -> FormSchema:
    slug = (container.service_slug or "").lower()
    if slug in ("supabase", "stripe", "rest_api", "external_generic"):
        return resolve_schema(slug, None)
    if slug.startswith("postgres"):
        return resolve_schema("postgres", None)
    return resolve_schema("external_generic", None)


async def get_project_config_executor(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    from ...tools.output_formatter import error_output, success_output

    db = context.get("db")
    project_id_raw = context.get("project_id")
    if not db or not project_id_raw:
        return error_output(message="Tool missing db/project_id context")
    project_id = (
        project_id_raw
        if isinstance(project_id_raw, UUID)
        else UUID(str(project_id_raw))
    )

    rows = await db.execute(
        select(Container).where(Container.project_id == project_id)
    )
    containers = list(rows.scalars().all())

    services: list[dict[str, Any]] = []
    for container in containers:
        schema = _resolve_schema_for_container(container)
        env_keys = sorted((container.environment_vars or {}).keys())
        secret_keys = sorted((container.encrypted_secrets or {}).keys())
        services.append(
            {
                "container_id": str(container.id),
                "container_name": container.name,
                "deployment_mode": container.deployment_mode,
                "container_type": container.container_type,
                "service_slug": container.service_slug,
                "preset": schema.preset,
                "schema_field_keys": [f.key for f in schema.fields],
                "configured_env_keys": env_keys,
                "configured_secret_keys": secret_keys,
                "needs_restart": bool(getattr(container, "needs_restart", False)),
            }
        )

    services.sort(
        key=lambda s: (
            0 if s["deployment_mode"] == "external" else 1,
            s["container_name"].lower(),
        )
    )

    return success_output(
        message=(
            f"Project has {len(services)} configured node(s)."
            if services
            else "Project has no configured services or containers yet."
        ),
        services=services,
        deployment_providers=[],  # placeholder; populated when DeploymentCredential cards land
    )


def register_get_project_config_tool(registry) -> None:
    registry.register(
        Tool(
            name="get_project_config",
            description=(
                "List every configured service, internal container, and deployment "
                "provider in this project, along with the env-var key names each one "
                "exposes. Read-only — never returns plaintext or secret values. Use "
                "this BEFORE creating a new node with `request_node_config` to avoid "
                "duplicates; if a matching card already exists, prefer "
                "`request_node_config(mode='edit', container_id=...)` so the user "
                "updates the existing card instead of seeing a second one appear."
            ),
            category=ToolCategory.PROJECT,
            parameters={
                "type": "object",
                "properties": {},
            },
            executor=get_project_config_executor,
            state_serializable=True,
            holds_external_state=False,
            examples=[
                '{"tool_name": "get_project_config", "parameters": {}}',
            ],
        )
    )
    logger.info("Registered node_config tool: get_project_config")
