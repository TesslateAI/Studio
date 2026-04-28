"""call_agent — multi-agent delegation to another configured marketplace agent.

Wired by the @-mention picker. When a user types ``@coworker-agent`` in
the chat, the chat router puts that agent's id in
``payload.mention_agent_ids`` and the worker registers this tool only on
that turn. The calling agent invokes the tool with ``{agent_id, message}``.

Distinct from the in-process subagent tools (``task`` / ``wait_agent``
in ``packages/tesslate-agent/.../delegation_ops/``) — those let the
agent spawn ephemeral specialists with prompts it crafts inline, run
in-process, and never touch the DB. ``call_agent`` instead routes to
another **configured marketplace agent** with its own DB-backed system
prompt, model, MCP assignments, and skills, via the standard
``execute_agent_task`` worker path. The two layers compose: a
delegated agent is itself free to use ``task`` to spawn its own
ephemeral subagents.

Flow:

1. Validate ``agent_id`` is in the authorized list (no LLM-invented ids).
2. Create a disposable ``Chat`` row tagged ``is_delegated_run=True``
   and ``parent_task_id=<parent task id>``. The chat list filters
   ``is_delegated_run=False`` so the row stays out of the sidebar; the
   chat-detail endpoint does NOT filter, so the drill-in UI ("expand
   call_agent tool call → View full trajectory") can navigate by id.
3. Run ``execute_agent_task`` in-process on a fresh payload with
   ``mention_agent_ids=[]``. That empty list is the multi-agent cap:
   the delegated agent never gets ``call_agent`` registered, so
   multi-agent ping-pong is structurally impossible. The delegated
   agent KEEPS ``task``/``wait_agent``/etc., so it can still spawn
   ephemeral subagents — that is in-process subagent work, not
   another configured-agent invocation.
4. Read the final assistant Message from the delegated chat and return
   ``{ok, output, sub_chat_id, sub_task_id, agent_slug, duration_seconds}``.

On failure the exception is caught and surfaced as ``{ok: False, error}``
— same pattern as ``invoke_app_action``.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any
from uuid import UUID

from ..output_formatter import error_output, success_output
from ..registry import Tool, ToolCategory

logger = logging.getLogger(__name__)


async def call_agent_executor(
    params: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Run an authorized delegated agent stateless and return its output."""

    target_agent_id_raw = params.get("agent_id")
    sub_message = params.get("message")

    if not target_agent_id_raw:
        return error_output(
            message="agent_id parameter is required",
            suggestion="Pass the UUID of the agent the user @-mentioned.",
            ok=False,
        )
    if not isinstance(sub_message, str) or not sub_message.strip():
        return error_output(
            message="message parameter is required and must be a non-empty string",
            suggestion="Pass the prompt you want the sub-agent to answer.",
            ok=False,
        )

    db = context.get("db")
    if db is None:
        return error_output(
            message="Database session not available in execution context",
            suggestion="This is an internal error — please report it.",
            ok=False,
        )

    try:
        target_agent_id = UUID(str(target_agent_id_raw))
    except (TypeError, ValueError):
        return error_output(
            message=f"agent_id is not a valid UUID: {target_agent_id_raw!r}",
            suggestion="Pass an authorized agent UUID.",
            ok=False,
        )

    authorized_ids = {str(x) for x in (context.get("mention_agent_ids") or [])}
    if str(target_agent_id) not in authorized_ids:
        return error_output(
            message=(
                "agent_id is not in the user's @-mention authorization list "
                "for this turn"
            ),
            suggestion=(
                "Only agents the user explicitly @-mentioned can be called. "
                "Authorized ids: " + ", ".join(sorted(authorized_ids)) if authorized_ids
                else "The user did not @-mention any agent on this turn."
            ),
            ok=False,
        )

    user_id_raw = context.get("user_id")
    if not user_id_raw:
        return error_output(
            message="user_id missing from execution context",
            suggestion="This is an internal error — please report it.",
            ok=False,
        )
    try:
        user_id = UUID(str(user_id_raw))
    except (TypeError, ValueError):
        return error_output(
            message=f"user_id is not a valid UUID: {user_id_raw!r}",
            suggestion="This is an internal error — please report it.",
            ok=False,
        )

    parent_task_id = str(context.get("task_id") or "")

    # Late imports — keeps the worker / model layers off the import path
    # for tool definitions that don't exercise this code path.
    from ....database import AsyncSessionLocal
    from ....models import Chat, MarketplaceAgent, Message
    from ....services.agent_task import AgentTaskPayload

    project_id_ctx = context.get("project_id")
    project_id_uuid: UUID | None = None
    if project_id_ctx:
        try:
            project_id_uuid = UUID(str(project_id_ctx))
        except (TypeError, ValueError):
            project_id_uuid = None

    team_id_ctx = context.get("team_id")
    team_id_uuid: UUID | None = None
    if team_id_ctx:
        try:
            team_id_uuid = UUID(str(team_id_ctx))
        except (TypeError, ValueError):
            team_id_uuid = None

    # Resolve target agent — surface a clean error if the marketplace row
    # was deleted between the user @-mentioning it and the agent calling.
    from sqlalchemy import select

    target_result = await db.execute(
        select(MarketplaceAgent).where(MarketplaceAgent.id == target_agent_id)
    )
    target_agent = target_result.scalar_one_or_none()
    if target_agent is None:
        return error_output(
            message="Authorized agent_id was not found in the marketplace",
            suggestion=(
                "The agent may have been deleted or unpublished. Ask the "
                "user to re-add the @-mention from the picker."
            ),
            ok=False,
        )

    # Create the disposable sub-chat in a fresh session so its commit is
    # independent of the parent run's transaction. If the parent rolls back
    # later, the sub-run still exists for audit — exactly what the drill-in
    # UI expects. Mirrors how the worker uses AsyncSessionLocal for its own
    # writes rather than the inbound request session.
    sub_chat_id: UUID
    async with AsyncSessionLocal() as sub_db:
        sub_chat = Chat(
            id=uuid.uuid4(),
            user_id=user_id,
            team_id=team_id_uuid,
            project_id=project_id_uuid,
            title=f"@{target_agent.slug}: {sub_message[:80]}",
            origin="delegated",
            status="active",
            parent_task_id=parent_task_id or None,
            is_delegated_run=True,
        )
        sub_db.add(sub_chat)
        await sub_db.commit()
        await sub_db.refresh(sub_chat)
        sub_chat_id = sub_chat.id

    # User Message row so the sub-chat reads naturally in the drill-in UI.
    async with AsyncSessionLocal() as sub_db:
        sub_db.add(
            Message(
                chat_id=sub_chat_id,
                role="user",
                content=sub_message,
            )
        )
        await sub_db.commit()

    sub_task_id = str(uuid.uuid4())
    sub_payload = AgentTaskPayload(
        task_id=sub_task_id,
        user_id=str(user_id),
        chat_id=str(sub_chat_id),
        message=sub_message,
        project_id=str(project_id_uuid) if project_id_uuid else "",
        project_slug=str(context.get("project_slug") or ""),
        team_id=str(team_id_uuid) if team_id_uuid else "",
        agent_id=str(target_agent_id),
        model_name="",
        edit_mode=context.get("edit_mode"),
        view_context=None,
        container_id=str(context.get("container_id") or "") or None,
        container_name=context.get("container_name"),
        container_directory=context.get("container_directory"),
        chat_history=[],
        # MULTI-AGENT CAP: empty mention list means call_agent is NOT
        # registered for the delegated run, so it cannot itself @-call
        # another agent. Structural, not a numeric counter. Cannot be
        # bypassed via prompt injection. The delegated agent KEEPS its
        # in-process subagent tools (task, wait_agent, etc.) — those are
        # a separate layer in the tesslate-agent submodule and are
        # unaffected by this cap.
        mention_agent_ids=[],
        mention_mcp_config_ids=[],
        mention_app_instance_ids=[],
        parent_task_id=parent_task_id or None,
    )

    # Direct in-process invocation of the worker entry point. Avoids the
    # cross-pod queue hop and the pubsub-subscription dance — we just await
    # the coroutine and read the assistant message back out when it returns.
    from ....worker import execute_agent_task

    started_at = time.monotonic()
    try:
        await execute_agent_task(
            {"job_id": sub_task_id, "task_queue": None}, sub_payload.to_dict()
        )
    except Exception as exc:  # noqa: BLE001 — never crash the parent loop
        logger.exception(
            "call_agent delegated run failed parent_task=%s delegated_chat=%s agent=%s",
            parent_task_id,
            sub_chat_id,
            target_agent.slug,
        )
        return error_output(
            message=f"Delegated agent run failed: {exc}",
            suggestion=(
                "Inspect the delegated-run trajectory via the drill-in UI "
                "(expand this tool call → View full trajectory), or retry "
                "— the delegated agent's own tools may have hit a "
                "transient error."
            ),
            ok=False,
            sub_chat_id=str(sub_chat_id),
            sub_task_id=sub_task_id,
            agent_slug=target_agent.slug,
            error=exc.__class__.__name__,
            error_message=str(exc),
        )
    duration_seconds = round(time.monotonic() - started_at, 4)

    # Pull the final assistant Message — the worker writes ``content`` on
    # finalize, so the latest assistant row in the sub-chat carries the
    # model's reply.
    final_text = ""
    async with AsyncSessionLocal() as sub_db:
        msg_result = await sub_db.execute(
            select(Message)
            .where(Message.chat_id == sub_chat_id, Message.role == "assistant")
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        final_msg = msg_result.scalar_one_or_none()
        if final_msg is not None:
            final_text = final_msg.content or ""

    return success_output(
        message=(
            f"Delegated agent '{target_agent.slug}' returned "
            f"{len(final_text)} chars in {duration_seconds}s"
        ),
        ok=True,
        output=final_text,
        agent_slug=target_agent.slug,
        sub_chat_id=str(sub_chat_id),
        sub_task_id=sub_task_id,
        duration_seconds=duration_seconds,
    )


def register_call_agent_tool(registry, *, authorized_agents: list[dict[str, str]]) -> None:
    """Register call_agent on the run's tool registry.

    ``authorized_agents`` is the list of agents the user explicitly @-mentioned
    on this turn (each ``{id, slug, name}``). It's surfaced in the tool
    description so the LLM knows which ids it may pass — the executor still
    re-validates against ``context['mention_agent_ids']`` so a hallucinated id
    is rejected at call time, not just at prompt time.
    """
    if not authorized_agents:
        # Defensive: registration should be gated upstream, but skipping here
        # too keeps a stray registration from advertising an empty list.
        return

    roster_lines = "\n".join(
        f"  - {a.get('slug', '?')} (id={a.get('id', '?')})"
        + (f" — {a['name']}" if a.get("name") else "")
        for a in authorized_agents
    )

    registry.register(
        Tool(
            name="call_agent",
            description=(
                "Delegate one turn to another of the user's configured "
                "agents (with its own system prompt, model, connectors, "
                "and skills) and return its final output. The delegated "
                "agent runs stateless: it sees only the message you pass "
                "— no parent chat history. Use this when the user "
                "@-mentioned another agent (e.g. '@coworker get me the "
                "Linear status'). Distinct from the `task` tool, which "
                "spawns ephemeral specialist subagents in-process; "
                "call_agent invokes a pre-existing configured agent. "
                "Returns {ok: True, output, agent_slug, sub_chat_id, "
                "sub_task_id, duration_seconds} on success or "
                "{ok: False, error_message} on failure.\n\n"
                "Authorized agents this turn:\n" + roster_lines + "\n\n"
                "Only the ids above may be passed; any other id will be "
                "rejected. If the user did not @-mention an agent, do not "
                "use this tool."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "format": "uuid",
                        "description": (
                            "UUID of the authorized delegated agent (one "
                            "of the ids in this tool's description)."
                        ),
                    },
                    "message": {
                        "type": "string",
                        "description": (
                            "The prompt to pass to the delegated agent. "
                            "Be self-contained — the delegated agent has "
                            "no chat history."
                        ),
                    },
                },
                "required": ["agent_id", "message"],
            },
            executor=call_agent_executor,
            category=ToolCategory.DELEGATION_OPS,
            # UUID + string in, JSON dict out — fully serializable.
            state_serializable=True,
            # Sub-run owns its own DB session + lock; this tool holds no
            # cross-call handles, sockets, or streams once the sub-run finishes.
            holds_external_state=False,
            examples=[
                '{"tool_name": "call_agent", "parameters": {'
                '"agent_id": "00000000-0000-0000-0000-000000000001", '
                '"message": "Summarise our open Linear issues for the runtime team."}}',
            ],
        )
    )

    logger.info(
        "Registered call_agent tool with %d authorized agent(s)",
        len(authorized_agents),
    )
