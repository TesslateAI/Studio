"""Workspace-attach submit/cancel endpoints.

Mirror of ``routers/node_config.py:366-402`` — same pause/resume contract,
different metadata key. The agent paused inside ``request_workspace``;
the user clicks Attach / Create Empty / Cancel inside the
``WorkspaceAttachCard``; this router resumes the agent with the chosen
action.

Auth model:
  * Use ``get_authenticated_user`` (session JWT or tsk-auth API key) — the
    same dependency the chat endpoints use.
  * Ownership check: the caller must be the user who originated the
    paused agent run. We compare ``current_user.id`` to
    ``req.metadata['user_id']`` (a parallel of
    ``_verify_input_ownership`` in node_config.py:344-363, but keyed on
    user instead of project because the whole point of the prompt is
    that the chat doesn't have a project yet).
  * For ``action='attach'`` we additionally re-check that the user owns
    or is a member of the target workspace at submit time.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth_unified import get_authenticated_user
from ..database import get_db
from ..models import Project, User

logger = logging.getLogger(__name__)

router = APIRouter()


class WorkspaceAttachSubmitRequest(BaseModel):
    action: str  # 'attach' | 'create_empty' | 'cancel'
    project_id: str | None = None
    name: str | None = None


async def _find_pending(input_id: str):
    from ..agent.tools.approval_manager import (
        get_pending_input_manager,
        publish_pending_input_response,
    )

    return get_pending_input_manager(), publish_pending_input_response


async def _verify_workspace_input_ownership(
    db: AsyncSession, current_user: User, input_id: str
) -> dict:
    """Return the metadata dict for a paused ``workspace_attach`` request,
    after verifying the calling user is the one the prompt was created for.

    Parallels ``_verify_input_ownership`` in node_config.py but keyed on
    ``metadata['user_id']`` because a standalone chat has no project_id.
    """
    manager, _ = await _find_pending(input_id)
    req = manager._pending.get(input_id)  # noqa: SLF001 — internal hook for auth
    if req is None or req.kind != "workspace_attach":
        raise HTTPException(status_code=404, detail="Unknown or expired input_id")
    metadata: dict[str, Any] = req.metadata or {}
    expected = metadata.get("user_id")
    if not expected:
        raise HTTPException(status_code=404, detail="Pending input has no user_id")
    if str(expected) != str(current_user.id) and not getattr(current_user, "is_superuser", False):
        raise HTTPException(status_code=403, detail="Not authorized for this input request")
    return metadata


async def _validate_attach_target(
    db: AsyncSession, current_user: User, project_id_raw: str
) -> Project:
    try:
        project_id = UUID(str(project_id_raw))
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=400, detail=f"Invalid project_id: {project_id_raw!r}"
        ) from exc
    project = await db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if project.owner_id == current_user.id or getattr(current_user, "is_superuser", False):
        return project
    # Membership union — same logic the agent tool used when listing.
    from ..models_team import ProjectMembership

    row = await db.execute(
        select(ProjectMembership).where(
            ProjectMembership.project_id == project.id,
            ProjectMembership.user_id == current_user.id,
        )
    )
    if row.scalar_one_or_none() is None:
        raise HTTPException(status_code=403, detail="Not authorized for this workspace")
    return project


@router.post("/chat/workspace-attach/{input_id}/submit")
async def submit_workspace_attach(
    input_id: str,
    body: WorkspaceAttachSubmitRequest,
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    """Resume a paused ``request_workspace`` with the user's choice."""
    metadata = await _verify_workspace_input_ownership(db, current_user, input_id)
    chat_id = metadata.get("chat_id")

    action = (body.action or "").lower()
    if action not in ("attach", "create_empty", "cancel"):
        raise HTTPException(
            status_code=400,
            detail="action must be one of: attach | create_empty | cancel",
        )

    response: dict[str, Any] = {"action": action}

    if action == "attach":
        if not body.project_id:
            raise HTTPException(status_code=400, detail="project_id is required")
        # Concurrency guard: if the chat is already linked to a different
        # workspace we surface 409 BEFORE delivering the response so the
        # tool can re-check or surface the conflict cleanly.
        from ..models import Chat

        if chat_id:
            try:
                chat_uuid = UUID(str(chat_id))
            except (ValueError, TypeError):
                chat_uuid = None
            if chat_uuid is not None:
                chat = await db.get(Chat, chat_uuid)
                if (
                    chat is not None
                    and chat.project_id is not None
                    and str(chat.project_id) != str(body.project_id)
                ):
                    raise HTTPException(status_code=409, detail="chat_already_linked")
        await _validate_attach_target(db, current_user, body.project_id)
        response["project_id"] = body.project_id
    elif action == "create_empty":
        response["name"] = (body.name or "").strip() or "New workspace"

    manager, publish = await _find_pending(input_id)
    logger.info(
        "[workspace-attach] submit input=%s action=%s",
        input_id,
        action,
    )
    if action == "cancel":
        manager.cancel_input(input_id)
        await publish(input_id, "__cancelled__", kind="workspace_attach")
    else:
        manager.submit_input(input_id, response)
        await publish(input_id, response, kind="workspace_attach")
    return {"ok": True}


@router.post("/chat/workspace-attach/{input_id}/cancel")
async def cancel_workspace_attach(
    input_id: str,
    current_user: User = Depends(get_authenticated_user),
    db: AsyncSession = Depends(get_db),
):
    await _verify_workspace_input_ownership(db, current_user, input_id)
    manager, publish = await _find_pending(input_id)
    logger.info("[workspace-attach] cancel input=%s", input_id)
    manager.cancel_input(input_id)
    await publish(input_id, "__cancelled__", kind="workspace_attach")
    return {"ok": True}


__all__ = ["router"]
