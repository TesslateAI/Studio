"""``request_workspace`` — agent pauses to ask the user for a workspace.

Mirrors ``agent/tools/node_config/request_node_config.py`` byte-for-byte
in shape: same heartbeat helper, same await flow, same cancelled / timeout
sentinels.

Flow:
  1. Agent calls the tool from a standalone chat (``project_id is None``).
  2. Tool lists the user's workspaces.
  3. Publishes ``workspace_attach_required`` carrying ``input_id`` and the
     candidate list.
  4. Awaits the user's submit / cancel via Redis pub/sub
     (``PendingUserInputManager.await_input``).
  5. Applies the choice — ``attach`` to an existing project, ``create_empty``
     to spin up a fresh blank workspace, or ``cancel``.
  6. CRITICAL: mutates the agent's ``context`` dict in place — sets
     ``project_id``, ``volume_id``, ``compute_tier`` so downstream file tools
     resolve against the new workspace.

Gating:
  * Refuses on delegated subagent runs (``parent_task_id`` set) — there is
    no human to answer.
  * Refuses on automation-driven runs (``automation_run_id`` set) — same.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import or_, select

from ....config import get_settings
from ....models import Project
from ....services.pubsub import get_pubsub
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_SECONDS = 30


async def _publish(task_id: str | None, event: dict) -> None:
    if not task_id:
        return
    pubsub = get_pubsub()
    if pubsub is None:
        return
    try:
        await pubsub.publish_agent_event(task_id, event)
    except Exception:
        logger.exception("[request_workspace] failed to publish event")


async def _heartbeat_loop(task_id: str | None, input_id: str) -> None:
    """Emit a heartbeat every 30s so the UI/worker can show liveness."""
    try:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
            await _publish(
                task_id,
                {
                    "type": "agent_heartbeat",
                    "data": {
                        "reason": "waiting_for_user_input",
                        "input_id": input_id,
                    },
                },
            )
    except asyncio.CancelledError:
        return


class _suppress_cancel:
    """Small context manager: swallow a single CancelledError on exit."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return exc_type is asyncio.CancelledError

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return exc_type is asyncio.CancelledError


async def _await_with_heartbeat(task_id: str | None, input_id: str, timeout: int):
    from ..approval_manager import get_pending_input_manager

    manager = get_pending_input_manager()
    hb_task = asyncio.create_task(_heartbeat_loop(task_id, input_id))
    try:
        return await manager.await_input(input_id, timeout=timeout)
    finally:
        hb_task.cancel()
        with _suppress_cancel():
            await hb_task


async def _list_user_workspaces(db, user_id: UUID) -> list[Project]:
    """Return every Project the user has access to that they could attach.

    Includes:
      * Projects they own.
      * Projects they're a member of via ``ProjectMembership``.

    Per the plan §"Decisions (locked)": "all user-owned workspaces" — no
    filtering by ``compute_tier``. Already-attached workspaces are visible
    but the UI marks them.
    """
    from ....models_team import ProjectMembership

    member_subq = select(ProjectMembership.project_id).where(ProjectMembership.user_id == user_id)
    rows = await db.execute(
        select(Project)
        .where(
            or_(
                Project.owner_id == user_id,
                Project.id.in_(member_subq),
            )
        )
        .order_by(Project.updated_at.desc())
    )
    return list(rows.scalars().all())


def _serialize_candidate(p: Project) -> dict[str, Any]:
    return {
        "id": str(p.id),
        "name": p.name,
        "slug": p.slug,
        "compute_tier": p.compute_tier,
        "created_via": getattr(p, "created_via", None),
        "project_kind": p.project_kind,
        "environment_status": p.environment_status,
    }


async def _create_empty_workspace(db, *, user_id: UUID, name: str) -> Project:
    """Internal-call path for the ``create_empty`` action.

    Calls the same shared helper the projects router uses so both surfaces
    converge on identical Project rows + on-disk materialization.
    """
    from ....models_auth import User
    from ....routers.projects import create_project_from_payload
    from ....schemas import ProjectCreate

    user = await db.get(User, user_id)
    if user is None:
        raise ValueError(f"User {user_id} not found")

    payload = ProjectCreate(name=name, source_type="empty")
    result = await create_project_from_payload(payload, current_user=user, db=db)
    return result["project"]


async def request_workspace_executor(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Executor — see module docstring for flow."""
    from ....models import Chat
    from ..output_formatter import error_output, success_output

    # ---- Gating: no delegated / automation runs ----
    if context.get("parent_task_id") is not None:
        return error_output(
            message="workspace attach requires direct user interaction (delegated run)"
        )
    if context.get("automation_run_id") is not None:
        return error_output(
            message="workspace attach requires direct user interaction (automation run)"
        )

    db = context.get("db")
    user_id_raw = context.get("user_id")
    chat_id_raw = context.get("chat_id")
    task_id = context.get("task_id")
    if not db or not user_id_raw or not chat_id_raw:
        return error_output(message="Tool missing db/user_id/chat_id context")

    user_id = user_id_raw if isinstance(user_id_raw, UUID) else UUID(str(user_id_raw))
    chat_id = chat_id_raw if isinstance(chat_id_raw, UUID) else UUID(str(chat_id_raw))

    # If a workspace is already attached, surface the linkage and exit so the
    # agent doesn't park on a redundant prompt.
    existing_chat = await db.get(Chat, chat_id)
    if existing_chat is None:
        return error_output(message=f"Chat {chat_id} not found")
    if existing_chat.project_id is not None:
        project = await db.get(Project, existing_chat.project_id)
        if project is not None:
            # Mutate the agent's context so downstream file tools see the
            # current workspace even if the worker built `context` before the
            # chat was linked elsewhere.
            context["project_id"] = project.id
            context["volume_id"] = project.volume_id
            context["compute_tier"] = project.compute_tier
            return success_output(
                message=f"Workspace '{project.name}' is already attached to this chat",
                project_id=str(project.id),
                project_name=project.name,
                project_slug=project.slug,
                volume_id=project.volume_id,
                already_attached=True,
            )

    workspaces = await _list_user_workspaces(db, user_id)
    candidates = [_serialize_candidate(p) for p in workspaces]

    # Register pending-input + emit the SSE event the WorkspaceAttachCard renders.
    from ..approval_manager import get_pending_input_manager

    input_id = str(uuid4())
    settings = get_settings()
    timeout = (
        getattr(settings, "workspace_attach_input_timeout_seconds", None)
        or getattr(settings, "node_config_input_timeout_seconds", 1800)
        or 1800
    )

    manager = get_pending_input_manager()
    await manager.create_input_request(
        input_id=input_id,
        kind="workspace_attach",
        session_id=str(chat_id),
        schema_json={
            "candidate_workspaces": candidates,
            "actions": ["attach", "create_empty", "cancel"],
            "reason": params.get("reason") or "",
        },
        metadata={
            "user_id": str(user_id),
            "chat_id": str(chat_id),
            "ttl": int(timeout),
        },
        ttl=int(timeout),
    )

    await _publish(
        task_id,
        {
            "type": "workspace_attach_required",
            "data": {
                "input_id": input_id,
                "chat_id": str(chat_id),
                "reason": params.get("reason") or "",
                "candidate_workspaces": candidates,
            },
        },
    )

    response = await _await_with_heartbeat(task_id, input_id, timeout=int(timeout))

    if response is None or response == "__cancelled__":
        await _publish(
            task_id,
            {
                "type": "workspace_attach_cancelled",
                "data": {
                    "input_id": input_id,
                    "reason": "timeout" if response is None else "user_cancelled",
                },
            },
        )
        return success_output(
            message=(
                "User cancelled workspace attach"
                if response == "__cancelled__"
                else "Workspace attach timed out"
            ),
            cancelled=True,
            timed_out=response is None,
        )

    if not isinstance(response, dict):
        return error_output(
            message=f"Unexpected response shape for {input_id}: {type(response).__name__}"
        )

    action = (response.get("action") or "").lower()

    target: Project | None = None
    if action == "attach":
        target_id_raw = response.get("project_id")
        if not target_id_raw:
            return error_output(message="action='attach' requires project_id")
        try:
            target_id = UUID(str(target_id_raw))
        except (ValueError, TypeError):
            return error_output(message=f"Invalid project_id: {target_id_raw!r}")
        target = await db.get(Project, target_id)
        if target is None:
            return error_output(message=f"Workspace {target_id} not found")
        # Authorize — must own or be a member.
        from ....models_team import ProjectMembership

        if target.owner_id != user_id:
            membership_row = await db.execute(
                select(ProjectMembership).where(
                    ProjectMembership.project_id == target.id,
                    ProjectMembership.user_id == user_id,
                )
            )
            if membership_row.scalar_one_or_none() is None:
                return error_output(message="Not authorized to attach this workspace")
    elif action == "create_empty":
        name = (response.get("name") or "").strip() or "New workspace"
        try:
            target = await _create_empty_workspace(db, user_id=user_id, name=name)
        except Exception as exc:
            logger.exception("[request_workspace] empty workspace creation failed")
            return error_output(message=f"Failed to create empty workspace: {exc}")
    elif action == "cancel":
        await _publish(
            task_id,
            {
                "type": "workspace_attach_cancelled",
                "data": {
                    "input_id": input_id,
                    "reason": "user_cancelled",
                },
            },
        )
        return success_output(
            message="User cancelled workspace attach",
            cancelled=True,
        )
    else:
        return error_output(
            message=f"Unknown action {action!r} (expected attach|create_empty|cancel)"
        )

    assert target is not None  # narrowed by branches above

    # Concurrency: re-read chat.project_id at apply time. If non-null and
    # different, surface a clear conflict to the agent.
    fresh_chat = await db.get(Chat, chat_id)
    if fresh_chat is None:
        return error_output(message="Chat vanished mid-attach")
    if fresh_chat.project_id is not None and fresh_chat.project_id != target.id:
        return error_output(message="Chat is already attached to a different workspace (race)")

    fresh_chat.project_id = target.id
    await db.commit()

    # CRITICAL: mutate the agent's context so file tools resolve against the
    # newly-attached workspace on their NEXT call. The plan verified
    # registry.py:469 + view_scoped_registry.py:282 pass context by reference
    # — no deep copy — so this propagates.
    context["project_id"] = target.id
    context["volume_id"] = target.volume_id
    context["compute_tier"] = target.compute_tier

    await _publish(
        task_id,
        {
            "type": "workspace_attach_resumed",
            "data": {
                "input_id": input_id,
                "chat_id": str(chat_id),
                "project_id": str(target.id),
                "project_name": target.name,
                "project_slug": target.slug,
                "action": action,
            },
        },
    )

    return success_output(
        message=(
            f"Created and attached new workspace '{target.name}'"
            if action == "create_empty"
            else f"Attached workspace '{target.name}'"
        ),
        project_id=str(target.id),
        project_name=target.name,
        project_slug=target.slug,
        volume_id=target.volume_id,
        compute_tier=target.compute_tier,
        created=action == "create_empty",
    )


def register_workspace_tool(registry) -> None:
    registry.register(
        Tool(
            name="request_workspace",
            description=(
                "Pause and ask the user to attach a workspace to this chat. "
                "Use whenever the conversation needs storage, compute, or "
                "persistence — saving notes, writing files, running commands, "
                "or tracking state across turns. The user picks an existing "
                "workspace or creates a new (empty) one; the chat is then "
                "linked to it and every existing file/command tool starts "
                "resolving against that workspace automatically. Pure "
                "vision/text turns do NOT need this tool. Returns the linked "
                "project's id, name, and slug."
            ),
            category=ToolCategory.PROJECT,
            parameters={
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": (
                            "Short, user-visible justification for the prompt "
                            "(e.g., 'so I can save your notes')."
                        ),
                    },
                },
            },
            executor=request_workspace_executor,
            state_serializable=True,
            holds_external_state=False,
            examples=[
                '{"tool_name": "request_workspace", "parameters": {"reason": "so I can save your notes for later"}}',
            ],
        )
    )
    logger.info("Registered workspace tool: request_workspace")
