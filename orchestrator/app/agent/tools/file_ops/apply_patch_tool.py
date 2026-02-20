"""
Apply Patch Tool

Codex-style unified patch tool that can add, delete, update, and move files
in a single operation. Uses the pure algorithm from agent/apply_patch.py
with container I/O via the orchestrator.

This is a FREEFORM tool — the LLM provides the patch directly, no structured
file_path/search/replace parameters needed. The patch format itself specifies
which files to touch and how.

Atomicity:
  All file operations are atomic at the patch level. Before any writes,
  the tool reads and backs up every file that will be touched. If ANY
  hunk fails, all previously applied changes are rolled back to their
  original state (or deleted if they were newly created).
"""

import logging
import shlex
from dataclasses import dataclass, field
from typing import Any

from ...apply_patch import (
    AddFile,
    DeleteFile,
    Hunk,
    UpdateFile,
    apply_patch_to_text,
    parse_patch,
    validate_patch,
)
from ..output_formatter import error_output, success_output
from ..registry import Tool, ToolCategory
from ..retry_config import tool_retry

logger = logging.getLogger(__name__)


APPLY_PATCH_DESCRIPTION = """Edit files using Codex patch format. This is a FREEFORM tool.

Format:
*** Begin Patch
*** Add File: path/to/new.py
+line1
+line2
*** Delete File: path/to/old.py
*** Update File: path/to/file.py
*** Move to: path/to/newname.py
@@ def function_name():
 context line (unchanged)
-line to remove
+line to add
*** End of File
*** End Patch

Rules:
- Lines with + are additions
- Lines with - are removals
- Lines with space are context (help locate the change)
- @@ markers show context/location hints
- *** End of File marks EOF-relative changes
- Multiple file operations in a single patch
- All changes are atomic: if any file fails, all changes are rolled back"""


# Sentinel: file did not exist before this patch (used for rollback of AddFile)
_FILE_DID_NOT_EXIST = object()


@dataclass
class _PatchContext:
    """Shared state for a single patch execution."""

    user_id: Any
    project_id: str
    project_slug: str | None
    container_directory: str | None
    container_name: str | None
    orchestrator: Any

    # Rollback state: path -> original content (str) or _FILE_DID_NOT_EXIST
    backups: dict[str, Any] = field(default_factory=dict)
    # Tracks which files we've already written (for rollback)
    applied: list[str] = field(default_factory=list)

    async def read_file(self, file_path: str) -> str | None:
        return await self.orchestrator.read_file(
            user_id=self.user_id,
            project_id=self.project_id,
            container_name=self.container_name,
            file_path=file_path,
            project_slug=self.project_slug,
            subdir=self.container_directory,
        )

    async def write_file(self, file_path: str, content: str) -> bool:
        return await self.orchestrator.write_file(
            user_id=self.user_id,
            project_id=self.project_id,
            container_name=self.container_name,
            file_path=file_path,
            content=content,
            project_slug=self.project_slug,
            subdir=self.container_directory,
        )

    async def delete_file(self, file_path: str) -> None:
        await self.orchestrator.execute_command(
            user_id=self.user_id,
            project_id=self.project_id,
            container_name=self.container_name,
            command=f"rm -f {shlex.quote(file_path)}",
            project_slug=self.project_slug,
        )

    async def backup(self, file_path: str) -> None:
        """Snapshot a file's current content before modifying it."""
        if file_path in self.backups:
            return  # Already backed up
        content = await self.read_file(file_path)
        self.backups[file_path] = content if content is not None else _FILE_DID_NOT_EXIST

    async def rollback(self) -> list[str]:
        """Restore all backed-up files to their pre-patch state.

        Returns list of rollback action descriptions.
        """
        rollback_log = []
        for path, original in self.backups.items():
            try:
                if original is _FILE_DID_NOT_EXIST:
                    # File was created by this patch — remove it
                    await self.delete_file(path)
                    rollback_log.append(f"Rolled back: deleted new file {path}")
                else:
                    # File existed — restore original content
                    await self.write_file(path, original)
                    rollback_log.append(f"Rolled back: restored {path}")
            except Exception as rb_err:
                logger.error(f"[APPLY-PATCH] Rollback failed for {path}: {rb_err}")
                rollback_log.append(f"Rollback FAILED for {path}: {rb_err}")
        return rollback_log


async def _apply_add(hunk: AddFile, ctx: _PatchContext) -> str:
    """Apply an AddFile hunk. Returns result description."""
    file_path = str(hunk.path)
    await ctx.backup(file_path)
    success = await ctx.write_file(file_path, hunk.contents)
    if not success:
        raise RuntimeError(f"Failed to create {file_path}")
    ctx.applied.append(file_path)
    return f"A {file_path}"


async def _apply_delete(hunk: DeleteFile, ctx: _PatchContext) -> str:
    """Apply a DeleteFile hunk. Returns result description."""
    file_path = str(hunk.path)
    await ctx.backup(file_path)
    await ctx.delete_file(file_path)
    ctx.applied.append(file_path)
    return f"D {file_path}"


async def _apply_update(hunk: UpdateFile, ctx: _PatchContext) -> str:
    """Apply an UpdateFile hunk (with optional move). Returns result description."""
    file_path = str(hunk.path)
    await ctx.backup(file_path)

    current_content = await ctx.read_file(file_path)
    if current_content is None:
        raise FileNotFoundError(f"File not found: {file_path}")

    new_content = apply_patch_to_text(current_content, hunk.chunks)

    dest_path = str(hunk.move_path) if hunk.move_path else file_path

    # If moving to a new path, back up the destination too
    if hunk.move_path:
        await ctx.backup(dest_path)

    success = await ctx.write_file(dest_path, new_content)
    if not success:
        raise RuntimeError(f"Failed to write {dest_path}")
    ctx.applied.append(dest_path)

    if hunk.move_path:
        await ctx.delete_file(file_path)
        ctx.applied.append(file_path)
        return f"M {file_path} -> {dest_path}"

    return f"U {file_path}"


async def _apply_hunk(hunk: Hunk, ctx: _PatchContext) -> str:
    """Dispatch a single hunk to the appropriate handler."""
    if isinstance(hunk, AddFile):
        return await _apply_add(hunk, ctx)
    elif isinstance(hunk, DeleteFile):
        return await _apply_delete(hunk, ctx)
    elif isinstance(hunk, UpdateFile):
        return await _apply_update(hunk, ctx)
    else:
        raise ValueError(f"Unknown hunk type: {type(hunk).__name__}")


@tool_retry
async def apply_patch_tool(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """
    Apply a Codex-format patch to files in the user's container.

    Supports Add, Delete, Update (with Move) operations in a single patch.
    Uses 4-level fuzzy matching for robust context location.

    All operations are atomic: if any file fails mid-patch, all previously
    applied changes are rolled back to their original state.
    """
    patch_text = params.get("patch")
    if not patch_text:
        raise ValueError("patch parameter is required")

    # Validate first
    validation_error = validate_patch(patch_text)
    if validation_error:
        return error_output(
            message=f"Invalid patch format: {validation_error}",
            suggestion="Ensure patch starts with '*** Begin Patch' and ends with '*** End Patch'",
        )

    # Parse
    try:
        hunks = parse_patch(patch_text, lenient=True)
    except ValueError as e:
        return error_output(
            message=f"Patch parse error: {str(e)}",
            suggestion="Check patch format — ensure markers are correct",
        )

    if not hunks:
        return error_output(message="Patch contains no file operations")

    from ....services.orchestration import get_orchestrator

    ctx = _PatchContext(
        user_id=context["user_id"],
        project_id=str(context["project_id"]),
        project_slug=context.get("project_slug"),
        container_directory=context.get("container_directory"),
        container_name=context.get("container_name"),
        orchestrator=get_orchestrator(),
    )

    # --- Atomic apply: backup -> apply all -> or rollback everything ---
    results = []
    try:
        for hunk in hunks:
            result = await _apply_hunk(hunk, ctx)
            results.append(result)
    except Exception as e:
        # Something failed — roll back ALL changes made so far
        file_path = str(hunk.path) if hasattr(hunk, "path") else "unknown"
        logger.error(f"[APPLY-PATCH] Hunk failed on {file_path}: {e}")

        rollback_log = await ctx.rollback()

        error_detail = f"Failed on {file_path}: {str(e)}"
        rollback_summary = "\n".join(rollback_log) if rollback_log else "No files to roll back"

        return error_output(
            message="Patch failed, all changes rolled back",
            suggestion="Fix the failing file and retry the full patch",
            details={
                "error": error_detail,
                "applied_before_failure": results,
                "rollback": rollback_log,
            },
            content=f"Error: {error_detail}\n\nRollback:\n{rollback_summary}",
        )

    return success_output(
        message=f"Patch applied: {len(results)} file(s) modified",
        content="Updated files:\n" + "\n".join(results),
        details={
            "files_modified": len(results),
            "operations": results,
        },
    )


def register_apply_patch_tool(registry):
    """Register the apply_patch tool."""
    registry.register(
        Tool(
            name="apply_patch",
            description=APPLY_PATCH_DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "patch": {
                        "type": "string",
                        "description": "The patch content in Codex format",
                    },
                },
                "required": ["patch"],
            },
            executor=apply_patch_tool,
            category=ToolCategory.FILE_OPS,
            examples=[
                '*** Begin Patch\n*** Update File: src/app.py\n@@ def greet():\n-print("Hi")\n+print("Hello")\n*** End Patch',
            ],
        )
    )
