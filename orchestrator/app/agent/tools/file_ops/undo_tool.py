"""
File Undo Tool

Reverts the most recent mutation to a given file by popping the latest
matching entry off the shared :data:`EDIT_HISTORY` buffer and restoring
the recorded ``prev_content`` via the active orchestrator.

Semantics:
    * If the recorded ``prev_content`` is ``None``, the file did not exist
      before the recorded mutation. Undoing the mutation therefore deletes
      the file.
    * Otherwise, the recorded content is written back verbatim.
    * If nothing has been recorded for the path, the tool returns a
      structured error ("nothing to undo").

This tool does NOT cascade: calling it once restores the single most
recent mutation on that path, even if multiple mutations are queued up
in the buffer. Call it again to walk further back.
"""

from __future__ import annotations

import logging
from typing import Any

from ....services.orchestration import get_orchestrator
from ..output_formatter import error_output, success_output
from ..registry import Tool, ToolCategory
from .edit_history import EDIT_HISTORY

logger = logging.getLogger(__name__)


async def file_undo_tool(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """
    Revert the most recent mutation to ``file_path``.

    Args:
        params: ``{"file_path": str}``
        context: Standard tool context (user_id, project_id, project_slug,
            container_directory, container_name, ...).

    Returns:
        Standardized success or error output.
    """
    file_path = params.get("file_path")
    if not file_path:
        raise ValueError("file_path parameter is required")

    entry = await EDIT_HISTORY.pop_latest(file_path)
    if entry is None:
        return error_output(
            message=f"Nothing to undo for '{file_path}'",
            suggestion=(
                "No recorded mutation was found for this path in the current "
                "run. Undo only covers changes made by agent tools within this "
                "session."
            ),
            file_path=file_path,
        )

    user_id = context.get("user_id")
    project_id_raw = context.get("project_id")
    project_id = str(project_id_raw) if project_id_raw is not None else ""
    project_slug = context.get("project_slug")
    container_directory = context.get("container_directory")
    container_name = context.get("container_name")

    orchestrator = get_orchestrator()

    volume_hints = {
        "volume_id": context.get("volume_id"),
        "cache_node": context.get("cache_node"),
    }

    try:
        if entry.prev_content is None:
            deleted = await orchestrator.delete_file(
                user_id=user_id,
                project_id=project_id,
                container_name=container_name,
                file_path=file_path,
            )
            if not deleted:
                logger.warning("[FILE-UNDO] delete_file returned False for %s", file_path)
                return error_output(
                    message=f"Could not remove '{file_path}' to complete undo",
                    suggestion=(
                        "The file may already be gone or the orchestrator "
                        "refused the delete. Verify the path and retry."
                    ),
                    file_path=file_path,
                    details={"op": entry.op},
                )
            return success_output(
                message=(f"Reverted '{file_path}' (deleted -- file did not previously exist)"),
                file_path=file_path,
                details={
                    "op": entry.op,
                    "timestamp": entry.timestamp,
                    "action": "delete",
                },
            )

        success = await orchestrator.write_file(
            user_id=user_id,
            project_id=project_id,
            container_name=container_name,
            file_path=file_path,
            content=entry.prev_content,
            project_slug=project_slug,
            subdir=container_directory,
            **volume_hints,
        )

        if not success:
            return error_output(
                message=f"Could not restore '{file_path}' to its prior state",
                suggestion="Check write permissions and disk space, then retry",
                file_path=file_path,
                details={"op": entry.op},
            )

        return success_output(
            message=f"Reverted '{file_path}' to previous state",
            file_path=file_path,
            details={
                "op": entry.op,
                "timestamp": entry.timestamp,
                "restored_bytes": len(entry.prev_content),
                "action": "restore",
            },
        )
    except Exception as exc:
        logger.error("[FILE-UNDO] Failed to undo %s: %s", file_path, exc, exc_info=True)
        return error_output(
            message=f"Undo failed for '{file_path}': {exc}",
            suggestion="Verify the orchestrator is healthy and try again",
            file_path=file_path,
            details={"error": str(exc), "op": entry.op},
        )


def register_undo_tool(registry) -> None:
    """Register the ``file_undo`` tool on the given registry."""

    registry.register(
        Tool(
            name="file_undo",
            description=(
                "Revert the most recent mutation (write/edit/patch/delete/move) "
                "applied to a file by the agent in this run. Only undoes a single "
                "step -- call again to walk further back."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": ("Path of the file to revert (relative to project root)."),
                    }
                },
                "required": ["file_path"],
            },
            executor=file_undo_tool,
            category=ToolCategory.FILE_OPS,
            examples=[
                '{"tool_name": "file_undo", "parameters": {"file_path": "src/App.jsx"}}',
            ],
        )
    )

    logger.info("Registered file_undo tool")
