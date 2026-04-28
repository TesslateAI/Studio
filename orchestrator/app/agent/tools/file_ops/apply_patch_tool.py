"""
Apply Patch Tool (structured change format)

Batches multiple file operations into a single atomic call:

    * ``create`` -- write a new file (errors if destination already exists)
    * ``update`` -- search/replace an existing file via the fuzzy editor
    * ``delete`` -- remove a file
    * ``move``   -- move a file from one path to another (no content edit)

The tool runs a **two-phase commit**:

    1. **Validate** every change in memory: resolve paths under ``cwd``,
       read existing contents, compute new contents for ``update`` via
       :func:`fuzzy_editor.apply_edit`, and verify destinations / sources
       for the other operations.
    2. **Apply** the validated plan by calling the orchestrator. Any
       mutation recorded during apply also snapshots the prior state
       into :data:`EDIT_HISTORY` so ``file_undo`` can revert it.

If validation fails for ANY change, no files are written. The call
errors with a structured per-change breakdown so the model can see
which entry needs fixing.

All paths are resolved as project-relative. Any ``..`` escape is
rejected. ``cwd`` is a path relative to the project root (``""`` for
root-level).
"""

from __future__ import annotations

import logging
import shlex
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from ....services.orchestration import get_orchestrator
from ..output_formatter import error_output, success_output
from ..registry import Tool, ToolCategory
from ..retry_config import tool_retry
from .edit_history import EDIT_HISTORY
from .fuzzy_editor import EditError, EditResult, apply_edit, llm_repair

logger = logging.getLogger(__name__)


APPLY_PATCH_DESCRIPTION = (
    "Apply a batch of file changes atomically. Supports create / update / "
    "delete / move operations. Every change is validated in-memory first; "
    "if any validation fails nothing is written. Update operations use the "
    "same multi-strategy matcher as patch_file."
)


VALID_OPS = {"create", "update", "delete", "move"}


def _resolve_rel(cwd: str, path: str) -> str:
    """
    Resolve ``path`` relative to ``cwd`` and return a normalized
    project-relative string. Refuses any escape above the root.
    """
    if path is None or path == "":
        raise ValueError("change path cannot be empty")

    cwd_parts = PurePosixPath(cwd or "").parts
    combined = PurePosixPath(*cwd_parts, *PurePosixPath(path).parts)

    normalized: list[str] = []
    for part in combined.parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not normalized:
                raise ValueError(f"path '{path}' escapes project root")
            normalized.pop()
            continue
        normalized.append(part)

    return "/".join(normalized)


@dataclass
class _Change:
    """One normalized change entry -- filled in during the validate phase."""

    index: int
    op: str
    path: str
    source_path: str | None = None
    new_content: str | None = None
    content: str | None = None
    prev_content_at_path: str | None = None
    prev_content_at_source: str | None = None
    path_existed: bool = False
    source_existed: bool = False
    strategy: str | None = None
    repair_applied: bool = False


@dataclass
class _PatchState:
    """Shared state across the two phases."""

    user_id: Any
    project_id: str
    project_slug: str | None
    container_directory: str | None
    container_name: str | None
    orchestrator: Any
    cwd: str
    changes: list[_Change] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

    async def read(self, rel_path: str) -> str | None:
        return await self.orchestrator.read_file(
            user_id=self.user_id,
            project_id=self.project_id,
            container_name=self.container_name,
            file_path=rel_path,
            project_slug=self.project_slug,
            subdir=self.container_directory,
        )

    async def write(self, rel_path: str, content: str) -> bool:
        return await self.orchestrator.write_file(
            user_id=self.user_id,
            project_id=self.project_id,
            container_name=self.container_name,
            file_path=rel_path,
            content=content,
            project_slug=self.project_slug,
            subdir=self.container_directory,
        )

    async def delete(self, rel_path: str) -> bool:
        orch = self.orchestrator
        delete_file = getattr(orch, "delete_file", None)
        if delete_file is not None:
            try:
                return bool(
                    await delete_file(
                        user_id=self.user_id,
                        project_id=self.project_id,
                        container_name=self.container_name,
                        file_path=rel_path,
                    )
                )
            except Exception as exc:
                logger.warning(
                    "[APPLY-PATCH] orchestrator.delete_file failed, falling back to shell: %s",
                    exc,
                )

        # Shell fallback for container-backed orchestrators.
        try:
            await orch.execute_command(
                user_id=self.user_id,
                project_id=self.project_id,
                container_name=self.container_name,
                command=["/bin/sh", "-c", f"rm -f {shlex.quote(rel_path)}"],
            )
            return True
        except Exception as exc:
            logger.error("[APPLY-PATCH] shell delete failed: %s", exc)
            return False


def _validate_entry(entry: dict[str, Any], index: int) -> _Change:
    """Turn a raw change dict into a :class:`_Change` or raise ``ValueError``."""
    if not isinstance(entry, dict):
        raise ValueError(f"change #{index} is not an object")

    op = entry.get("op")
    if op not in VALID_OPS:
        raise ValueError(
            f"change #{index} has invalid op '{op}'. Must be one of: {sorted(VALID_OPS)}"
        )

    path: str | None = None
    source: str | None = None
    content: str | None = None

    if op == "create":
        path = entry.get("path")
        content = entry.get("content")
        if content is None:
            raise ValueError(f"change #{index}: create requires 'content'")
        if not isinstance(content, str):
            raise ValueError(f"change #{index}: create 'content' must be a string")

    elif op == "update":
        path = entry.get("path")
        if not isinstance(entry.get("old_str"), str):
            raise ValueError(f"change #{index}: update requires 'old_str'")
        if not isinstance(entry.get("new_str"), str):
            raise ValueError(f"change #{index}: update requires 'new_str'")

    elif op == "delete":
        path = entry.get("path")

    elif op == "move":
        source = entry.get("from")
        path = entry.get("to")
        if not isinstance(source, str) or not source:
            raise ValueError(f"change #{index}: move requires 'from'")

    if not isinstance(path, str) or not path:
        raise ValueError(f"change #{index}: missing 'path'")

    return _Change(
        index=index,
        op=op,
        path=path,
        source_path=source,
    )


async def _phase1_validate(
    state: _PatchState,
    raw_changes: list[dict[str, Any]],
) -> list[_Change]:
    """
    Normalize every change, read current contents, and pre-compute new
    contents for ``update`` ops. Populates ``state.errors`` per-change
    rather than raising early so the caller can report everything.
    """
    resolved_paths: dict[str, _Change] = {}
    staged: list[_Change] = []

    for i, entry in enumerate(raw_changes):
        try:
            change = _validate_entry(entry, i)
        except ValueError as exc:
            state.errors.append(
                {
                    "index": i,
                    "op": entry.get("op") if isinstance(entry, dict) else None,
                    "path": entry.get("path") if isinstance(entry, dict) else None,
                    "error": str(exc),
                }
            )
            continue

        try:
            change.path = _resolve_rel(state.cwd, change.path)
            if change.source_path is not None:
                change.source_path = _resolve_rel(state.cwd, change.source_path)
        except ValueError as exc:
            state.errors.append(
                {
                    "index": i,
                    "op": change.op,
                    "path": change.path,
                    "error": str(exc),
                }
            )
            continue

        prev_at_path = await state.read(change.path)
        change.prev_content_at_path = prev_at_path
        change.path_existed = prev_at_path is not None

        if change.source_path:
            prev_at_source = await state.read(change.source_path)
            change.prev_content_at_source = prev_at_source
            change.source_existed = prev_at_source is not None

        if change.op == "create":
            if change.path_existed:
                state.errors.append(
                    {
                        "index": i,
                        "op": change.op,
                        "path": change.path,
                        "error": (f"create: destination '{change.path}' already exists"),
                    }
                )
                continue
            change.content = entry.get("content") or ""

        elif change.op == "update":
            if not change.path_existed:
                state.errors.append(
                    {
                        "index": i,
                        "op": change.op,
                        "path": change.path,
                        "error": f"update: source '{change.path}' does not exist",
                    }
                )
                continue
            old_str = entry.get("old_str", "")
            new_str = entry.get("new_str", "")
            expected_occurrence = int(entry.get("expected_occurrence", 1) or 1)
            allow_multiple = bool(entry.get("allow_multiple", False))
            try:
                result: EditResult = await apply_edit(
                    content=change.prev_content_at_path or "",
                    old_str=old_str,
                    new_str=new_str,
                    expected_occurrence=expected_occurrence,
                    allow_multiple=allow_multiple,
                    file_path=change.path,
                    repair_fn=llm_repair,
                )
            except EditError as exc:
                state.errors.append(
                    {
                        "index": i,
                        "op": change.op,
                        "path": change.path,
                        "error": exc.args[0],
                        "attempted_strategies": exc.attempted,
                        "suggestion": exc.suggestion,
                    }
                )
                continue
            change.new_content = result.content
            change.strategy = result.strategy
            change.repair_applied = result.repair_applied

        elif change.op == "delete":
            if not change.path_existed:
                state.errors.append(
                    {
                        "index": i,
                        "op": change.op,
                        "path": change.path,
                        "error": f"delete: '{change.path}' does not exist",
                    }
                )
                continue

        elif change.op == "move":
            if not change.source_existed:
                state.errors.append(
                    {
                        "index": i,
                        "op": change.op,
                        "path": change.path,
                        "error": (f"move: source '{change.source_path}' does not exist"),
                    }
                )
                continue
            if change.path_existed:
                state.errors.append(
                    {
                        "index": i,
                        "op": change.op,
                        "path": change.path,
                        "error": (f"move: destination '{change.path}' already exists"),
                    }
                )
                continue

        if change.path in resolved_paths:
            state.errors.append(
                {
                    "index": i,
                    "op": change.op,
                    "path": change.path,
                    "error": (
                        f"path '{change.path}' is touched by multiple changes in "
                        f"this batch (also at index {resolved_paths[change.path].index})"
                    ),
                }
            )
            continue
        resolved_paths[change.path] = change
        if change.source_path:
            if change.source_path in resolved_paths:
                state.errors.append(
                    {
                        "index": i,
                        "op": change.op,
                        "path": change.path,
                        "error": (
                            f"source '{change.source_path}' is touched by another "
                            f"change at index {resolved_paths[change.source_path].index}"
                        ),
                    }
                )
                continue
            resolved_paths[change.source_path] = change

        staged.append(change)

    return staged


async def _phase2_apply(state: _PatchState, staged: list[_Change]) -> list[dict[str, Any]]:
    """
    Apply every staged change. Records :data:`EDIT_HISTORY` entries
    before each mutation so the undo tool can walk back individual
    steps.
    """
    applied: list[dict[str, Any]] = []

    for change in staged:
        if change.op == "create":
            await EDIT_HISTORY.record(change.path, None, "write")
            ok = await state.write(change.path, change.content or "")
            if not ok:
                raise RuntimeError(f"create: write_file returned False for {change.path}")
            applied.append(
                {
                    "index": change.index,
                    "op": "create",
                    "path": change.path,
                    "status": "ok",
                }
            )

        elif change.op == "update":
            await EDIT_HISTORY.record(change.path, change.prev_content_at_path, "patch")
            ok = await state.write(change.path, change.new_content or "")
            if not ok:
                raise RuntimeError(f"update: write_file returned False for {change.path}")
            applied.append(
                {
                    "index": change.index,
                    "op": "update",
                    "path": change.path,
                    "status": "ok",
                    "strategy": change.strategy,
                    "repair_applied": change.repair_applied,
                }
            )

        elif change.op == "delete":
            await EDIT_HISTORY.record(change.path, change.prev_content_at_path, "delete")
            ok = await state.delete(change.path)
            if not ok:
                raise RuntimeError(f"delete: orchestrator could not remove {change.path}")
            applied.append(
                {
                    "index": change.index,
                    "op": "delete",
                    "path": change.path,
                    "status": "ok",
                }
            )

        elif change.op == "move":
            await EDIT_HISTORY.record(
                change.source_path or "",
                change.prev_content_at_source,
                "move_src",
            )
            await EDIT_HISTORY.record(change.path, None, "move_dst")

            ok = await state.write(change.path, change.prev_content_at_source or "")
            if not ok:
                raise RuntimeError(f"move: write_file returned False for {change.path}")
            ok = await state.delete(change.source_path or "")
            if not ok:
                raise RuntimeError(f"move: could not remove source {change.source_path}")
            applied.append(
                {
                    "index": change.index,
                    "op": "move",
                    "path": change.path,
                    "from": change.source_path,
                    "status": "ok",
                }
            )

    return applied


@tool_retry
async def apply_patch_tool(params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """
    Apply a batch of structured file changes.

    See :data:`APPLY_PATCH_DESCRIPTION` for the full format.
    """
    cwd = params.get("cwd", "") or ""
    changes = params.get("changes")
    if not isinstance(changes, list) or not changes:
        return error_output(
            message="apply_patch requires a non-empty 'changes' array",
            suggestion="Provide at least one change object with op/path fields.",
        )

    if not isinstance(cwd, str):
        return error_output(
            message="apply_patch 'cwd' must be a string",
            suggestion="Set cwd to '' for the project root or a subdirectory path.",
        )

    project_id_raw = context.get("project_id")
    project_id = str(project_id_raw) if project_id_raw is not None else ""

    state = _PatchState(
        user_id=context.get("user_id"),
        project_id=project_id,
        project_slug=context.get("project_slug"),
        container_directory=context.get("container_directory"),
        container_name=context.get("container_name"),
        orchestrator=get_orchestrator(),
        cwd=cwd,
    )

    staged = await _phase1_validate(state, changes)

    if state.errors:
        return error_output(
            message=(
                f"apply_patch validation failed: {len(state.errors)} error(s), nothing was written"
            ),
            suggestion=(
                "Fix the per-change errors and retry. No filesystem mutations were applied."
            ),
            details={"errors": state.errors},
        )

    try:
        applied = await _phase2_apply(state, staged)
    except Exception as exc:
        logger.error("[APPLY-PATCH] phase2 failed: %s", exc, exc_info=True)
        return error_output(
            message=f"apply_patch runtime failure: {exc}",
            suggestion=(
                "One or more file writes failed mid-batch. Use file_undo on the "
                "affected paths to walk back any partial mutations."
            ),
            details={"error": str(exc)},
        )

    return success_output(
        message=f"apply_patch applied {len(applied)} change(s)",
        details={"applied": applied},
    )


def register_apply_patch_tool(registry) -> None:
    """Register the ``apply_patch`` tool on the given registry."""

    registry.register(
        Tool(
            name="apply_patch",
            description=APPLY_PATCH_DESCRIPTION,
            parameters={
                "type": "object",
                "properties": {
                    "cwd": {
                        "type": "string",
                        "description": (
                            "Project-relative base directory for all paths. Use '' "
                            "for the project root."
                        ),
                    },
                    "changes": {
                        "type": "array",
                        "description": "List of structured change operations.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "op": {
                                    "type": "string",
                                    "enum": sorted(VALID_OPS),
                                },
                                "path": {"type": "string"},
                                "from": {"type": "string"},
                                "content": {"type": "string"},
                                "old_str": {"type": "string"},
                                "new_str": {"type": "string"},
                                "expected_occurrence": {"type": "integer"},
                                "allow_multiple": {"type": "boolean"},
                            },
                            "required": ["op"],
                        },
                    },
                },
                "required": ["changes"],
            },
            executor=apply_patch_tool,
            category=ToolCategory.FILE_OPS,
            # Structured changes list in, per-op result list out — JSON-clean.
            state_serializable=True,
            # Patches applied atomically; no persistent patch session held.
            holds_external_state=False,
            examples=[
                (
                    '{"tool_name": "apply_patch", "parameters": {"cwd": "", '
                    '"changes": [{"op": "create", "path": "README.md", "content": "# Hi"}]}}'
                ),
                (
                    '{"tool_name": "apply_patch", "parameters": {"cwd": "src", '
                    '"changes": [{"op": "update", "path": "App.jsx", '
                    '"old_str": "bg-blue-500", "new_str": "bg-green-500"}]}}'
                ),
            ],
        )
    )

    logger.info("Registered apply_patch tool")
