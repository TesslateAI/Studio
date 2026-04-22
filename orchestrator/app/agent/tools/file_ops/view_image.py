"""
View Image Tool

Reads an image file from the project and returns it as a base64-encoded
content part so the agent loop can attach it to the next model turn.

Validation:
    * Extension must be one of .png, .jpg, .jpeg, .gif, .webp.
    * Raw file size must be <= 20 MiB.
    * If the caller context explicitly sets ``model_supports_vision=False``,
      the tool refuses early with a structured error.

The orchestrator's text-oriented ``read_file`` is used to fetch the raw
bytes: since images are binary, the content is first read as UTF-8 with
the ``latin-1`` fallback that LocalOrchestrator provides, then re-encoded
back to bytes. For the byte-exact path we instead ask the orchestrator
for the file directly via the filesystem — on Docker/K8s mode we use
``execute_command`` with ``base64`` to avoid any text decoding, and on
Local mode we read the raw bytes off disk through the orchestrator's
project root. A small helper encapsulates both paths.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any

from ..output_formatter import error_output, success_output
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 20 * 1024 * 1024  # 20 MiB

EXTENSION_MEDIA_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

VALID_DETAILS = {"low", "high", "auto"}


async def _read_image_bytes(
    orchestrator: Any,
    *,
    user_id: Any,
    project_id: str,
    container_name: str | None,
    project_slug: str | None,
    container_directory: str | None,
    file_path: str,
    volume_hints: dict[str, Any],
) -> bytes | None:
    """
    Fetch an image from the configured orchestrator as raw bytes.

    Strategy:
        1. If the orchestrator exposes a ``root`` property (LocalOrchestrator),
           read the file directly off the filesystem after joining it under
           the project root. This is the exact-byte path.
        2. Otherwise, shell out through the orchestrator's ``execute_command``
           to ``base64 -w0`` the target file and decode the result.

    Returns:
        Raw image bytes, or ``None`` if the file does not exist or the
        orchestrator refused the operation.
    """
    # Preferred path: direct filesystem read via the orchestrator's root.
    root = getattr(orchestrator, "root", None)
    if root is not None:
        try:
            base = Path(root)
            if container_directory:
                base = (base / container_directory).resolve()
                base.relative_to(Path(root))
            target = (base / file_path).resolve()
            target.relative_to(Path(root))
        except ValueError:
            logger.warning("[VIEW-IMAGE] refused: path '%s' escapes project root", file_path)
            return None

        if not target.exists() or not target.is_file():
            return None
        try:
            return target.read_bytes()
        except OSError as exc:
            logger.error("[VIEW-IMAGE] read_bytes failed for %s: %s", target, exc)
            return None

    # Container-backed path: base64-encode via the orchestrator's shell.
    import shlex

    command_str = f"base64 -w0 {shlex.quote(file_path)}"
    try:
        output = await orchestrator.execute_command(
            user_id=user_id,
            project_id=project_id,
            container_name=container_name,
            command=["/bin/sh", "-c", command_str],
            project_slug=project_slug,
        )
    except TypeError:
        # Some orchestrators expect argv only (no project_slug kwarg).
        output = await orchestrator.execute_command(
            user_id=user_id,
            project_id=project_id,
            container_name=container_name,
            command=["/bin/sh", "-c", command_str],
        )
    except Exception as exc:
        logger.error("[VIEW-IMAGE] execute_command failed: %s", exc)
        return None

    if not output:
        return None

    try:
        return base64.b64decode(output.strip(), validate=False)
    except (ValueError, base64.binascii.Error) as exc:
        logger.error("[VIEW-IMAGE] base64 decode failed: %s", exc)
        return None


async def view_image_tool(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """
    Load an image file from the project and return it as a base64 content
    part plus a human-readable text note.

    Args:
        params: ``{"path": str, "detail": "low"|"high"|"auto" = "auto"}``
        context: Standard tool context. Honors ``model_supports_vision``
            when set (False short-circuits with a structured error).

    Returns:
        Standardized success output with an extra ``content_parts`` field
        that the agent loop can forward to the model.
    """
    path = params.get("path") or params.get("file_path")
    if not path:
        raise ValueError("path parameter is required")

    detail_raw = params.get("detail", "auto")
    detail = (detail_raw or "auto").lower()
    if detail not in VALID_DETAILS:
        return error_output(
            message=f"Invalid detail '{detail_raw}'",
            suggestion=f"Use one of: {', '.join(sorted(VALID_DETAILS))}",
            file_path=path,
        )

    vision_flag = context.get("model_supports_vision")
    if vision_flag is False:
        return error_output(
            message="view_image is not available: the current model does not support vision",
            suggestion="Switch to a vision-capable model or use read_file for textual data",
            file_path=path,
        )

    extension = Path(path).suffix.lower()
    media_type = EXTENSION_MEDIA_TYPES.get(extension)
    if media_type is None:
        return error_output(
            message=f"Unsupported image type '{extension or '<none>'}'",
            suggestion=(f"view_image supports: {', '.join(sorted(EXTENSION_MEDIA_TYPES.keys()))}"),
            file_path=path,
            details={"extension": extension},
        )

    user_id = context.get("user_id")
    pid = context.get("project_id")
    project_id = str(pid) if pid is not None else None
    project_slug = context.get("project_slug")
    container_directory = context.get("container_directory")
    container_name = context.get("container_name")

    volume_hints = {
        "volume_id": context.get("volume_id"),
        "cache_node": context.get("cache_node"),
    }

    from ....services.orchestration import get_orchestrator

    orchestrator = get_orchestrator()

    raw = await _read_image_bytes(
        orchestrator,
        user_id=user_id,
        project_id=project_id,
        container_name=container_name,
        project_slug=project_slug,
        container_directory=container_directory,
        file_path=path,
        volume_hints=volume_hints,
    )

    if raw is None:
        return error_output(
            message=f"Image '{path}' does not exist",
            suggestion="Check the path and that the file is present in the project",
            file_path=path,
        )

    size = len(raw)
    if size > MAX_IMAGE_BYTES:
        return error_output(
            message=(
                f"Image '{path}' is {size} bytes, which exceeds the {MAX_IMAGE_BYTES}-byte limit"
            ),
            suggestion="Shrink or crop the image before passing it to the model",
            file_path=path,
            details={"size_bytes": size, "max_bytes": MAX_IMAGE_BYTES},
        )

    encoded = base64.b64encode(raw).decode("ascii")
    content_parts = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": encoded,
            },
        },
        {
            "type": "text",
            "text": f"Image loaded: {path} ({size}B)",
        },
    ]

    return success_output(
        message=f"Loaded image '{path}' ({size} bytes, {media_type})",
        file_path=path,
        content_parts=content_parts,
        details={
            "size_bytes": size,
            "media_type": media_type,
            "detail": detail,
        },
    )


def register_view_image_tool(registry) -> None:
    """Register the ``view_image`` tool on the given registry."""

    registry.register(
        Tool(
            name="view_image",
            description=(
                "Load an image file from the project and attach it to the next "
                "model turn. Supports PNG, JPG/JPEG, GIF, and WEBP up to 20 MiB."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the image file, relative to the project root.",
                    },
                    "detail": {
                        "type": "string",
                        "enum": sorted(VALID_DETAILS),
                        "description": "Requested rendering detail hint for the model.",
                    },
                },
                "required": ["path"],
            },
            executor=view_image_tool,
            category=ToolCategory.FILE_OPS,
            examples=[
                '{"tool_name": "view_image", "parameters": {"path": "design/mockup.png"}}',
                '{"tool_name": "view_image", "parameters": {"path": "assets/logo.jpg", "detail": "high"}}',
            ],
        )
    )

    logger.info("Registered view_image tool")
