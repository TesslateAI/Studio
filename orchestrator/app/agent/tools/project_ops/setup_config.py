"""Apply setup config — agent wrapper over sync_project_config service.

Parity with ``POST /{slug}/setup-config``: writes ``.tesslate/config.json``
to the project filesystem/PVC and replaces the container, connection,
deployment, and preview graph in one transaction. Returns the synced
container IDs so downstream tool calls (``project_start`` etc.) can act
on them.
"""

from __future__ import annotations

import logging
from typing import Any

from ....schemas import TesslateConfigCreate
from ..output_formatter import error_output, success_output
from ..registry import Tool, ToolCategory
from ._helpers import fetch_project, require_project_context

logger = logging.getLogger(__name__)


def _build_parameters() -> dict[str, Any]:
    """Build the tool parameter schema from the real Pydantic config model.

    The ``config`` parameter's type is the JSON Schema of
    ``TesslateConfigCreate`` — so the LLM receives the exact shape the
    endpoint accepts, generated live. Description points at the
    ``project-architecture`` built-in skill for field-level semantics,
    validation rules, service catalog, and worked examples.
    """
    schema = TesslateConfigCreate.model_json_schema()
    defs = schema.pop("$defs", {})

    params: dict[str, Any] = {
        "type": "object",
        "properties": {
            "config": {
                **schema,
                "description": (
                    "Full .tesslate/config.json object. Call "
                    "load_skill('project-architecture') for field semantics, "
                    "validation rules, the infrastructure service catalog, "
                    "and worked examples."
                ),
            },
        },
        "required": ["config"],
    }
    if defs:
        params["$defs"] = defs
    return params


_PARAMETERS = _build_parameters()


async def apply_setup_config_executor(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Atomically write config.json and sync the project graph."""
    ctx = require_project_context(context)
    if ctx is None:
        return error_output(
            message="Missing required context (db, user_id, or project_id)",
            suggestion="Ensure the tool is called within a valid project session",
        )
    db, user_id, project_id = ctx

    raw_config = params.get("config")
    if not isinstance(raw_config, dict):
        return error_output(
            message="'config' parameter must be an object matching the .tesslate/config.json schema",
            suggestion="Pass the full config — see the tool description for required keys",
        )

    project = await fetch_project(db, project_id)
    if not project:
        return error_output(
            message="Project not found",
            suggestion="Ensure you are in a valid project context",
        )

    from ....schemas import TesslateConfigCreate
    from ....services.config_sync import ConfigSyncError, sync_project_config

    try:
        config_data = TesslateConfigCreate(**raw_config)
    except Exception as exc:
        return error_output(
            message=f"Invalid config payload: {exc}",
            suggestion="Check schema: apps (dict), primaryApp (string), optional infrastructure/connections/deployments/previews",
        )

    try:
        response = await sync_project_config(db, project, config_data, user_id)
    except ConfigSyncError as exc:
        return error_output(
            message=str(exc),
            suggestion="Fix the offending startup command or field and retry",
        )
    except Exception as exc:
        logger.error("apply_setup_config failed: %s", exc, exc_info=True)
        return error_output(
            message=f"Config sync failed: {exc}",
            suggestion="Check logs for the full stack trace",
        )

    return success_output(
        message=f"Synced {len(response.container_ids)} container(s) from config",
        container_ids=response.container_ids,
        primary_container_id=response.primary_container_id,
    )


def register_setup_config_tool(registry):
    """Register the apply_setup_config tool."""
    registry.register(
        Tool(
            name="apply_setup_config",
            description=(
                "Atomically write .tesslate/config.json AND replace the project's "
                "container/connection/deployment/preview graph to match. Use this instead "
                "of write_file for config.json — it is the single source of truth and "
                "syncs every related record in one transaction. Validates startup commands. "
                "Returns the resulting container_ids."
            ),
            category=ToolCategory.PROJECT,
            parameters=_PARAMETERS,
            executor=apply_setup_config_executor,
            examples=[
                (
                    '{"tool_name": "apply_setup_config", "parameters": {"config": {'
                    '"apps": {"frontend": {"directory": "frontend", "port": 3000, "start": "npm run dev"}}, '
                    '"primaryApp": "frontend"}}}'
                ),
                (
                    '{"tool_name": "apply_setup_config", "parameters": {"config": {'
                    '"apps": {"api": {"directory": "api", "port": 8000, "start": "uvicorn app:app"}}, '
                    '"infrastructure": {"postgres": {"port": 5432, "type": "container"}}, '
                    '"connections": [{"from_node": "api", "to_node": "postgres"}], '
                    '"primaryApp": "api"}}}'
                ),
            ],
        )
    )
    logger.info("Registered apply_setup_config tool")
