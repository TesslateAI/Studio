"""
ARQ Worker for Agent Task Execution

Runs agent tasks asynchronously, decoupled from the API pod's HTTP lifecycle.
Events are published to Redis Streams for real-time streaming back to clients.
Progressive step persistence ensures completed work survives crashes.

Usage:
    # Run as standalone worker process (uses same Docker image as backend)
    arq app.worker.WorkerSettings

    # Or via command line
    python -m arq app.worker.WorkerSettings
"""

import asyncio
import contextlib
import logging
import os
from datetime import UTC
from uuid import UUID

from arq.connections import RedisSettings

from .services.apps.app_invocations import invoke_app_instance_task
from .services.apps.settlement_worker import settle_spend_batch as settle_spend_batch_cron

logger = logging.getLogger(__name__)


async def _auto_title_chat(chat, model_adapter, user_message: str, db) -> None:
    """Generate and set a chat title from the user's first message. Non-blocking."""
    if not chat or chat.title:
        return
    try:
        title_text = ""
        async for chunk in model_adapter.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "Generate a concise 3-6 word title for this chat based on "
                        "the user's message. Return ONLY the title, no quotes or "
                        "punctuation. Examples: 'Login page with OAuth', "
                        "'Fix navbar responsive layout', 'Add dark mode toggle'."
                    ),
                },
                {"role": "user", "content": user_message[:500]},
            ],
            max_tokens=20,
        ):
            title_text += chunk
        title_text = title_text.strip().strip("\"'")[:100]
        if title_text:
            chat.title = title_text
            await db.commit()
            logger.info(f"[WORKER] Auto-titled chat {chat.id}: {title_text}")
    except Exception as e:
        logger.warning(f"[WORKER] Auto-title generation failed: {e}")


async def _create_agent_checkpoint(volume_id: str, summary: str) -> None:
    """Fire-and-forget CAS checkpoint after agent task completion.

    Creates a labeled snapshot so the user can restore to any agent run.
    Failures are logged but never propagated — agent completion is not
    contingent on snapshot success.
    """
    try:
        from .config import get_settings
        from .services.hub_client import HubClient

        settings = get_settings()
        if not settings.volume_hub_address:
            return
        label = f"agent: {summary[:80]}"
        async with HubClient(settings.volume_hub_address) as client:
            await client.create_snapshot(volume_id, label, timeout=30.0)
        logger.info("[WORKER] Agent checkpoint created: volume=%s", volume_id)
    except Exception as e:
        logger.warning("[WORKER] Agent checkpoint failed (non-fatal): %s", e)


def _build_step_dict(step_data: dict, _convert_uuids_to_strings) -> dict:
    """Build a normalized step dict from raw agent step data."""
    return {
        "iteration": step_data.get("iteration"),
        "thought": step_data.get("thought"),
        "tool_calls": [
            {
                "name": tc.get("name"),
                "parameters": _convert_uuids_to_strings(tc.get("parameters", {})),
                "result": _convert_uuids_to_strings(
                    step_data.get("tool_results", [])[idx]
                    if idx < len(step_data.get("tool_results", []))
                    else {}
                ),
            }
            for idx, tc in enumerate(step_data.get("tool_calls", []))
        ],
        "response_text": step_data.get("response_text", ""),
        "is_complete": step_data.get("is_complete", False),
        "timestamp": step_data.get("timestamp", ""),
    }


async def _heartbeat_lock(pubsub, chat_id: str, task_id: str):
    """Extend the chat lock every 10 seconds until cancelled.

    When the lock is lost (stolen or expired), signals cancellation
    via Redis so the agent loop stops at the next iteration check.
    """
    try:
        while True:
            await asyncio.sleep(10)
            extended = await pubsub.extend_chat_lock(chat_id, task_id)
            if not extended:
                logger.warning(
                    f"[WORKER] Lost chat lock for {chat_id}, "
                    f"task {task_id} — signalling cancellation"
                )
                await pubsub.request_cancellation(task_id)
                break
    except asyncio.CancelledError:
        pass


async def execute_agent_task(ctx: dict, payload_dict: dict):
    """
    Execute an agent task in the worker process.

    This function:
    1. Deserializes the task payload
    2. Acquires per-project lock (if enabled)
    3. Creates placeholder Message in DB before agent loop
    4. Runs agent.run() — INSERTs AgentStep rows progressively
    5. Finalizes the Message with summary metadata on completion
    6. Publishes events to Redis Streams for live SSE relay
    7. Enqueues webhook callback if configured
    8. Cleans up bash sessions and releases lock
    """
    from sqlalchemy import select

    from .agent.factory import create_agent_from_db_model
    from .agent.iterative_agent import _convert_uuids_to_strings
    from .agent.models import create_model_adapter
    from .config import get_settings
    from .database import AsyncSessionLocal
    from .models import (
        AgentStep,
        Chat,
        Container,
        MarketplaceAgent,
        Message,
        Project,
        UserPurchasedAgent,
    )
    from .services.agent_context import (
        _build_architecture_context,
        _build_cross_platform_context,
        _build_git_context,
        _build_tesslate_context,
        _get_chat_history,
        _resolve_container_name,
    )
    from .services.agent_task import AgentTaskPayload
    from .services.pubsub import get_pubsub

    settings = get_settings()
    payload = AgentTaskPayload.from_dict(payload_dict)
    pubsub = get_pubsub()
    task_id = payload.task_id
    project_id = payload.project_id
    heartbeat_task = None
    lock_acquired = False
    message_id = None

    logger.info(f"[WORKER] Starting agent task {task_id} for project {project_id}")

    async with AsyncSessionLocal() as db:
        try:
            # 1. Load project (optional for standalone chats)
            project = None
            if project_id:
                result = await db.execute(select(Project).where(Project.id == UUID(project_id)))
                project = result.scalar_one_or_none()
                if not project:
                    await _publish_error(pubsub, task_id, "Project not found")
                    return

            # 2. Acquire per-chat lock (allows concurrent agents across sessions)
            project_settings = (project.settings or {}) if project else {}
            agent_lock_enabled = project_settings.get("agent_lock_enabled", True)
            chat_id = payload.chat_id

            if agent_lock_enabled and pubsub:
                lock_acquired = await pubsub.acquire_chat_lock(chat_id, task_id)
                if not lock_acquired:
                    # If the holding task has been cancelled, wait briefly
                    # for it to release the lock (e.g. user cancelled then
                    # immediately sent a new message).
                    holding_task = await pubsub.get_chat_lock(chat_id)
                    if holding_task and await pubsub.is_cancelled(holding_task):
                        for _retry in range(10):
                            await asyncio.sleep(0.5)
                            lock_acquired = await pubsub.acquire_chat_lock(chat_id, task_id)
                            if lock_acquired:
                                logger.info(
                                    f"[WORKER] Acquired lock after cancelled task "
                                    f"{holding_task} released"
                                )
                                break
                    if not lock_acquired:
                        holding_task = await pubsub.get_chat_lock(chat_id)
                        await _publish_error(
                            pubsub,
                            task_id,
                            f"Another agent is running in this session (task: {holding_task})",
                        )
                        return
                # Start heartbeat to extend lock every 10s
                heartbeat_task = asyncio.create_task(_heartbeat_lock(pubsub, chat_id, task_id))

            # 3. Load agent model
            agent_model = None
            if payload.agent_id:
                result = await db.execute(
                    select(MarketplaceAgent).where(
                        MarketplaceAgent.id == UUID(payload.agent_id),
                        MarketplaceAgent.is_active.is_(True),
                    )
                )
                agent_model = result.scalar_one_or_none()
            else:
                result = await db.execute(
                    select(MarketplaceAgent)
                    .where(
                        MarketplaceAgent.is_active.is_(True),
                        MarketplaceAgent.agent_type == "IterativeAgent",
                    )
                    .limit(1)
                )
                agent_model = result.scalar_one_or_none()

            if not agent_model:
                await _publish_error(pubsub, task_id, "No agent found")
                return

            # 4. Get model name
            model_name = payload.model_name
            if not model_name:
                user_id = UUID(payload.user_id)
                result = await db.execute(
                    select(UserPurchasedAgent).where(
                        UserPurchasedAgent.user_id == user_id,
                        UserPurchasedAgent.agent_id == agent_model.id,
                    )
                )
                user_purchase = result.scalar_one_or_none()
                model_name = (
                    user_purchase.selected_model
                    if user_purchase and user_purchase.selected_model
                    else agent_model.model or settings.litellm_default_models.split(",")[0]
                )

            # 5. Create model adapter
            model_adapter = await create_model_adapter(
                model_name=model_name,
                user_id=UUID(payload.user_id),
                db=db,
            )

            # 6. Create view-scoped tool registry if needed
            tools_override = None
            if payload.view_context:
                from .agent.tools.view_context import ViewContext
                from .agent.tools.view_scoped_factory import create_view_scoped_registry

                view_context_str = (
                    payload.view_context.get("view")
                    if isinstance(payload.view_context, dict)
                    else payload.view_context
                )
                if view_context_str:
                    view_context = ViewContext.from_string(view_context_str)
                    tools_override = create_view_scoped_registry(
                        view_context=view_context,
                        project_id=UUID(project_id),
                        container_id=(UUID(payload.container_id) if payload.container_id else None),
                    )

            # 7. Create agent instance
            agent_instance = await create_agent_from_db_model(
                agent_model=agent_model,
                model_adapter=model_adapter,
                tools_override=tools_override,
            )

            # 7b. Load MCP tools for this user/agent and inject into tool registry
            mcp_context: dict | None = None
            try:
                from .services.mcp.manager import get_mcp_manager

                mcp_mgr = get_mcp_manager()
                mcp_context = await mcp_mgr.get_user_mcp_context(
                    user_id=payload.user_id,
                    db=db,
                    agent_id=str(agent_model.id),
                    team_id=payload.team_id or None,
                    project_id=payload.project_id or None,
                )
                mcp_tools = mcp_context.get("tools", [])
                if mcp_tools and hasattr(agent_instance, "tools") and agent_instance.tools:
                    for mcp_tool in mcp_tools:
                        agent_instance.tools.register(mcp_tool)
                    logger.info(
                        "[WORKER] Registered %d MCP tools for agent '%s'",
                        len(mcp_tools),
                        agent_model.slug,
                    )

                # Surface connectors that failed discovery (stale OAuth, 401,
                # etc.) — without this, the agent silently gets an empty tool
                # list for Notion/Linear/etc and confabulates "I don't have
                # access" when the user knows they attached it. The UI shows
                # a red dot via the `needs_reauth` flag; this log gives us a
                # breadcrumb when debugging reports like "agent says it can't
                # reach X."
                unavailable = mcp_context.get("unavailable_servers", [])
                if unavailable:
                    logger.warning(
                        "[WORKER] %d MCP connector(s) unavailable for agent '%s': %s",
                        len(unavailable),
                        agent_model.slug,
                        ", ".join(
                            f"{u.get('server_slug')}({u.get('reason')})" for u in unavailable
                        ),
                    )
            except Exception as mcp_err:
                logger.warning("[WORKER] MCP context loading failed (non-fatal): %s", mcp_err)

            container_id = UUID(payload.container_id) if payload.container_id else None
            container_name = payload.container_name
            container_directory = payload.container_directory

            if container_id and project_id and (not container_name or container_directory is None):
                container_result = await db.execute(
                    select(Container).where(
                        Container.id == container_id,
                        Container.project_id == UUID(project_id),
                    )
                )
                container = container_result.scalar_one_or_none()
                if container:
                    container_name = _resolve_container_name(container)
                    if container.directory and container.directory != ".":
                        container_directory = container.directory

            # Discover available skills for this agent (progressive disclosure)
            from .services.skill_discovery import discover_skills

            available_skills = await discover_skills(
                agent_id=agent_model.id if agent_model else None,
                user_id=UUID(payload.user_id),
                project_id=project_id if project_id else None,
                container_name=container_name,
                db=db,
            )

            chat_history = payload.chat_history or await _get_chat_history(
                UUID(payload.chat_id), db, limit=10
            )

            if project:
                project_context = payload.project_context or {
                    "project_name": project.name,
                    "project_description": project.description,
                }
                tesslate_context = await _build_tesslate_context(
                    project,
                    UUID(payload.user_id),
                    db,
                    container_name=container_name,
                    container_directory=container_directory,
                )
                if tesslate_context:
                    project_context["tesslate_context"] = tesslate_context
                git_context = await _build_git_context(project, UUID(payload.user_id), db)
                if git_context:
                    project_context["git_context"] = git_context
                architecture_context = await _build_architecture_context(project, db)
                if architecture_context:
                    project_context["architecture_context"] = architecture_context
            else:
                project_context = payload.project_context or {}

            # Add available skills to project_context (for prompt injection)
            if available_skills:
                project_context["available_skills"] = available_skills

            # Add MCP resource/prompt catalogs to project_context for prompt injection
            if mcp_context:
                if mcp_context.get("resource_catalog"):
                    project_context["mcp_resource_catalog"] = mcp_context["resource_catalog"]
                if mcp_context.get("prompt_catalog"):
                    project_context["mcp_prompt_catalog"] = mcp_context["prompt_catalog"]

            # Warm the local plan mirror from Redis before the agent builds its prompt.
            from .agent.plan_manager import PlanManager

            payload_context = {
                "user_id": UUID(payload.user_id),
                "project_id": UUID(project_id) if project_id else None,
            }
            active_plan = await PlanManager.get_plan(payload_context)

            # Tier snapshot for agent context (compute_tier-aware tools read these).
            from .services.agent_context import build_tier_snapshot

            _tier_snapshot = await build_tier_snapshot(project, db)
            _tier_containers = _tier_snapshot.get("containers", [])

            # 8. Build execution context (same structure as chat.py)
            context = {
                "user_id": UUID(payload.user_id),
                "project_id": UUID(project_id) if project_id else None,
                "project_slug": payload.project_slug,
                "container_directory": container_directory,
                "chat_id": UUID(payload.chat_id),
                "task_id": task_id,
                "db": db,
                "chat_history": chat_history,
                "project_context": project_context,
                "edit_mode": payload.edit_mode,
                "container_id": container_id,
                "container_name": container_name,
                "view_context": (
                    payload.view_context.get("view")
                    if isinstance(payload.view_context, dict)
                    else payload.view_context
                ),
                "model_name": model_name,
                "agent_id": agent_model.id,
                "_active_plan": active_plan,
                "available_skills": available_skills,
                "attachments": payload.attachments,
                "api_key_scopes": payload.api_key_scopes,
                # Volume routing — Hub is the live source of truth for node
                # placement; cache_node is NOT passed (dead DB field).
                "volume_id": project.volume_id if project else None,
                "compute_tier": project.compute_tier if project else None,
                "active_compute_pod": project.active_compute_pod if project else None,
                "environment_status": project.environment_status if project else None,
                "containers": _tier_containers,
            }

            # Inject MCP server configs so bridge executors can connect per-call
            if mcp_context and mcp_context.get("mcp_configs"):
                context["mcp_configs"] = mcp_context["mcp_configs"]

            # Inject channel context for send_message "reply" channel
            if payload.channel_config_id:
                context["channel_config_id"] = payload.channel_config_id
                context["channel_jid"] = payload.channel_jid
                context["channel_type"] = payload.channel_type

            # Inject cross-platform context for gateway-originated tasks
            if payload.channel_type and project:
                cross_platform = await _build_cross_platform_context(
                    chat_id=UUID(payload.chat_id),
                    user_id=UUID(payload.user_id),
                    project_id=UUID(project_id) if project_id else None,
                    platform=payload.channel_type,
                    db=db,
                )
                if cross_platform:
                    project_context["cross_platform_context"] = cross_platform

            # 9. Create placeholder Message before agent loop (crash-safe)
            assistant_message = Message(
                chat_id=UUID(payload.chat_id),
                role="assistant",
                content="",  # Will be finalized on completion
                message_metadata={
                    "agent_mode": True,
                    "agent_type": agent_model.agent_type,
                    "completion_reason": "in_progress",
                    "executed_by": "worker",
                    "task_id": task_id,
                },
            )
            db.add(assistant_message)
            await db.commit()
            await db.refresh(assistant_message)
            message_id = assistant_message.id

            # Create file checkpoint before agent execution (for /undo file revert).
            # Uses git ghost commits when a container is running, or a btrfs
            # volume fork for K8s tier-0 projects (no pod).
            checkpoint_hash = None
            if project_id:
                try:
                    from .services.checkpoint_manager import CheckpointManager

                    ckpt_mgr = CheckpointManager(
                        user_id=UUID(payload.user_id),
                        project_id=project_id,
                        volume_id=project.volume_id if project else None,
                    )
                    checkpoint_hash = await ckpt_mgr.create_checkpoint()
                    if checkpoint_hash:
                        logger.info(
                            "[WORKER] Checkpoint %s for task %s",
                            checkpoint_hash[:12],
                            task_id,
                        )
                except Exception as ckpt_err:
                    logger.warning("[WORKER] Checkpoint failed (non-fatal): %s", ckpt_err)

            # Update chat status to running
            chat_result = await db.execute(select(Chat).where(Chat.id == UUID(payload.chat_id)))
            chat = chat_result.scalar_one_or_none()
            if chat:
                chat.status = "running"
                await db.commit()

            # 10. Run agent and publish events — progressive step persistence
            final_response = ""
            iterations = 0
            tool_calls_made = 0
            completion_reason = "task_complete"
            session_id = None
            event_count = 0
            step_index = 0

            try:
                async for event in agent_instance.run(payload.message, context):
                    event_count += 1
                    event_type = event.get("type", "unknown")

                    # Check for cancellation between events
                    if pubsub and await pubsub.is_cancelled(task_id):
                        logger.info(f"[WORKER] Task {task_id} cancelled by client")
                        completion_reason = "cancelled"
                        final_response = "Request was cancelled."
                        await pubsub.publish_agent_event(
                            task_id,
                            {
                                "type": "complete",
                                "data": {
                                    "final_response": final_response,
                                    "iterations": iterations,
                                    "tool_calls_made": tool_calls_made,
                                    "completion_reason": "cancelled",
                                },
                            },
                        )
                        break

                    # Progressive step persistence: INSERT AgentStep row per step
                    if event_type == "agent_step":
                        step_data = event.get("data", {})
                        normalized = _build_step_dict(step_data, _convert_uuids_to_strings)
                        agent_step = AgentStep(
                            message_id=message_id,
                            chat_id=UUID(payload.chat_id),
                            step_index=step_index,
                            step_data=normalized,
                        )
                        db.add(agent_step)
                        await db.commit()
                        step_index += 1

                    elif event_type == "complete":
                        complete_data = event.get("data", {})
                        final_response = complete_data.get("final_response", "")
                        iterations = complete_data.get("iterations", iterations)
                        tool_calls_made = complete_data.get("tool_calls_made", tool_calls_made)
                        completion_reason = complete_data.get(
                            "completion_reason", completion_reason
                        )
                        session_id = complete_data.get("session_id")

                    # Publish event to Redis Stream for API pod to forward to SSE
                    if pubsub:
                        await pubsub.publish_agent_event(task_id, event)

            finally:
                # Finalize Message regardless of how we exit the loop
                logger.info(
                    f"[WORKER] Agent finished: task={task_id}, events={event_count}, "
                    f"iterations={iterations}, tool_calls={tool_calls_made}"
                )

                # 10b. Create CAS checkpoint snapshot (bounded, shutdown-safe)
                if (
                    project
                    and getattr(project, "volume_id", None)
                    and completion_reason != "cancelled"
                ):
                    with contextlib.suppress(Exception):
                        await asyncio.wait_for(
                            _create_agent_checkpoint(
                                project.volume_id,
                                final_response or "Agent task completed",
                            ),
                            timeout=35.0,
                        )

                # 11. Increment usage count
                agent_model.usage_count = (agent_model.usage_count or 0) + 1
                db.add(agent_model)

                # 12. Finalize the placeholder Message with summary metadata
                assistant_message.content = final_response or "Agent task completed."
                assistant_message.message_metadata = {
                    "agent_mode": True,
                    "agent_type": agent_model.agent_type,
                    "iterations": iterations,
                    "tool_calls_made": tool_calls_made,
                    "completion_reason": completion_reason,
                    "session_id": session_id,
                    "executed_by": "worker",
                    "task_id": task_id,
                    "checkpoint_hash": checkpoint_hash,
                    "trajectory_path": (
                        f".tesslate/trajectories/trajectory_{session_id}.json"
                        if session_id
                        else None
                    ),
                    # Steps are now in agent_steps table, not here
                    "steps_table": True,
                }
                db.add(assistant_message)

                # Update chat status
                if chat:
                    chat.status = "completed" if completion_reason != "cancelled" else "active"
                await db.commit()

            # 13. Auto-generate chat title on first message (non-blocking)
            if completion_reason != "cancelled":
                await _auto_title_chat(chat, model_adapter, payload.message, db)
                # Publish title to SSE so frontend can update immediately
                if pubsub and chat and chat.title:
                    await pubsub.publish_agent_event(
                        task_id,
                        {
                            "type": "chat_title",
                            "data": {
                                "chat_id": str(chat.id),
                                "title": chat.title,
                            },
                        },
                    )

            # 14. Publish done event
            if pubsub:
                await pubsub.publish_agent_event(
                    task_id, {"type": "done", "data": {"task_id": task_id}}
                )

            # 14a. Gateway delivery — XADD to delivery stream if gateway-bound
            if payload.gateway_deliver:
                try:
                    from .services.cache_service import get_redis_client

                    gw_redis = await get_redis_client()
                    if gw_redis:
                        await gw_redis.xadd(
                            settings.gateway_delivery_stream,
                            {
                                "task_id": task_id,
                                "config_id": payload.channel_config_id or "",
                                "session_key": payload.session_key or "",
                                "deliver": payload.gateway_deliver,
                                "response": (final_response or "")[:8000],
                                "schedule_id": payload.schedule_id or "",
                            },
                            maxlen=settings.gateway_delivery_maxlen,
                        )
                        logger.info(
                            "[WORKER] XADD delivery for task %s (session=%s)",
                            task_id,
                            payload.session_key,
                        )
                except Exception as gw_err:
                    logger.warning("[WORKER] Gateway delivery XADD failed: %s", gw_err)

            # 14b. Enqueue webhook callback if configured
            if payload.webhook_callback_url:
                try:
                    from .services.task_queue import get_task_queue

                    await get_task_queue().enqueue(
                        "send_webhook_callback",
                        payload.webhook_callback_url,
                        {
                            "task_id": task_id,
                            "status": completion_reason,
                            "final_response": final_response,
                            "chat_id": payload.chat_id,
                            "project_id": project_id,
                            "iterations": iterations,
                            "tool_calls_made": tool_calls_made,
                        },
                    )
                    logger.info(f"[WORKER] Enqueued webhook callback for task {task_id}")
                except Exception as wh_err:
                    logger.warning(f"[WORKER] Failed to enqueue webhook callback: {wh_err}")

            # 15. Cleanup bash session
            if context.get("_bash_session_id"):
                try:
                    from .services.shell_session_manager import get_shell_session_manager

                    shell_manager = get_shell_session_manager()
                    await shell_manager.close_session(context["_bash_session_id"])
                except Exception as cleanup_err:
                    logger.warning(f"[WORKER] Failed to cleanup bash session: {cleanup_err}")

            # Belt-and-suspenders: update task status in Redis directly
            # so get_active_agent_task sees COMPLETED even if the SSE relay
            # pod didn't call update_task_status.
            await _update_task_status_redis(task_id, "completed")

            logger.info(f"[WORKER] Task {task_id} complete, saved to database")

        except Exception as e:
            import traceback

            error_traceback = traceback.format_exc()
            logger.error(f"[WORKER] Agent task {task_id} failed: {e}")
            logger.error(f"[WORKER] Traceback:\n{error_traceback}")

            # Publish error event
            await _publish_error(pubsub, task_id, str(e))

            # Update task status to FAILED in Redis
            await _update_task_status_redis(task_id, "failed", error=str(e))

            # Finalize stale in_progress placeholder message and reset chat status
            try:
                # Finalize the placeholder Message so it doesn't show thinking dots
                if message_id is not None:
                    msg_result = await db.execute(select(Message).where(Message.id == message_id))
                    stale_msg = msg_result.scalar_one_or_none()
                    if (
                        stale_msg
                        and (stale_msg.message_metadata or {}).get("completion_reason")
                        == "in_progress"
                    ):
                        stale_msg.content = f"Agent task failed: {str(e)[:200]}"
                        stale_msg.message_metadata = {
                            **(stale_msg.message_metadata or {}),
                            "completion_reason": "error",
                            "error": str(e)[:500],
                        }
                        db.add(stale_msg)

                # Mark chat as active (not running) on error
                chat_result = await db.execute(select(Chat).where(Chat.id == UUID(payload.chat_id)))
                chat = chat_result.scalar_one_or_none()
                if chat and chat.status == "running":
                    chat.status = "active"

                await db.commit()
            except Exception as db_err:
                logger.warning(
                    f"[WORKER] Failed to finalize stale message / reset chat status: {db_err}"
                )

        finally:
            # Always release chat lock and cancel heartbeat
            if heartbeat_task:
                heartbeat_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat_task
            if lock_acquired and pubsub:
                await pubsub.release_chat_lock(payload.chat_id, task_id)
                logger.debug(f"[WORKER] Released chat lock for {payload.chat_id}")


async def send_webhook_callback(ctx: dict, url: str, payload: dict):
    """
    Send webhook callback to external client.

    ARQ handles retries (max_tries=5, exponential backoff).
    """
    from urllib.parse import urlparse

    import httpx

    parsed_url = urlparse(url)
    logger.info(
        f"[WEBHOOK] Sending callback to {parsed_url.scheme}://{parsed_url.hostname}{parsed_url.path}"
    )

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()

    logger.info(f"[WEBHOOK] Callback sent successfully: {response.status_code}")


async def _update_task_status_redis(task_id: str, status: str, error: str | None = None):
    """Directly update task status in Redis from the worker process.

    The worker doesn't share TaskManager state with the API pod, so we write
    the status key directly.  Belt-and-suspenders for when the SSE relay pod
    doesn't mark the task as completed.
    """
    try:
        from .services.cache_service import get_redis_client

        redis = await get_redis_client()
        if not redis:
            return

        import json
        from datetime import datetime

        task_key = f"tesslate:task:{task_id}"
        raw = await redis.get(task_key)
        if not raw:
            return

        data = json.loads(raw)
        data["status"] = status
        data["completed_at"] = datetime.now(UTC).isoformat()
        if error:
            data["error"] = error

        await redis.setex(task_key, 86400, json.dumps(data))
        logger.info(f"[WORKER] Updated task {task_id} status to {status} in Redis")
    except Exception as e:
        logger.debug(f"[WORKER] Failed to update task status in Redis (non-blocking): {e}")


async def _publish_error(pubsub, task_id: str, message: str):
    """Publish an error event to Redis."""
    if pubsub:
        await pubsub.publish_agent_event(
            task_id,
            {"type": "error", "data": {"message": message}},
        )
        # Also publish done so the API pod stops listening
        await pubsub.publish_agent_event(
            task_id,
            {"type": "done", "data": {"task_id": task_id, "error": message}},
        )


async def refresh_templates(ctx: dict):
    """Check for outdated templates and trigger rebuilds.

    Compares git HEAD SHA of each base's repo with the SHA stored in
    the TemplateBuild record. If different, triggers a rebuild.
    """
    from sqlalchemy import select

    from .config import get_settings

    settings = get_settings()
    if not settings.template_build_enabled:
        return

    from .database import AsyncSessionLocal
    from .models import MarketplaceBase, TemplateBuild
    from .services.template_builder import TemplateBuilderService

    async with AsyncSessionLocal() as db:
        # Find bases with ready templates that have a git repo
        result = await db.execute(
            select(MarketplaceBase).where(
                MarketplaceBase.template_slug.isnot(None),
                MarketplaceBase.git_repo_url.isnot(None),
            )
        )
        bases = result.scalars().all()

        if not bases:
            return

        builder = TemplateBuilderService()
        rebuilt = 0
        for base in bases:
            try:
                # Get latest remote SHA via git ls-remote
                proc = await asyncio.create_subprocess_exec(
                    "git",
                    "ls-remote",
                    base.git_repo_url,
                    "HEAD",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
                if proc.returncode != 0:
                    continue
                remote_sha = stdout.decode().split()[0][:40]

                # Get latest successful build SHA
                latest_build = await db.scalar(
                    select(TemplateBuild)
                    .where(
                        TemplateBuild.base_slug == base.slug,
                        TemplateBuild.status == "ready",
                    )
                    .order_by(TemplateBuild.completed_at.desc())
                    .limit(1)
                )

                if latest_build and latest_build.git_commit_sha == remote_sha:
                    continue  # Template is up to date

                logger.info(
                    "[WORKER] Template %s outdated (remote=%s, build=%s), rebuilding...",
                    base.slug,
                    remote_sha[:8],
                    (latest_build.git_commit_sha or "none")[:8] if latest_build else "none",
                )
                await builder.build_template(base, db)
                rebuilt += 1
            except Exception:
                logger.exception("[WORKER] Failed to refresh template for %s", base.slug)

        if rebuilt:
            logger.info("[WORKER] Refreshed %d templates", rebuilt)


async def reap_idle_session_keys(ctx: dict) -> dict:
    """Periodic task: sweep idle session-tier LiteLLM keys past their TTL.

    For each idle key, transition active -> settling (revokes at LiteLLM),
    then settling -> settled. Per-key work is best-effort; failures are
    logged and the sweep continues.
    """
    from .database import AsyncSessionLocal
    from .services import litellm_keys
    from .services.litellm_service import litellm_service

    async with AsyncSessionLocal() as db:
        try:
            key_ids = await litellm_keys.select_idle_session_keys(db, limit=200)
        except Exception:
            logger.exception("reap_idle_session_keys: select failed")
            return {"swept": 0}

        swept = 0
        for key_id in key_ids:
            try:
                await litellm_keys.begin_settlement(
                    db, delegate=litellm_service, key_id=key_id, reason="idle_reap"
                )
                await litellm_keys.finalize_settlement(db, key_id=key_id)
                await db.commit()
                swept += 1
            except Exception:
                await db.rollback()
                logger.exception("reap_idle_session_keys: key %s failed", key_id)

        if swept:
            logger.info("[WORKER] reaped %d idle session keys", swept)
        return {"swept": swept}


async def settle_invocation_key(ctx: dict, key_id: str) -> dict:
    """Enqueue-able: settle a completed invocation key (headless run).

    Called by the billing dispatcher when an invocation completes. The
    dispatcher is responsible for wallet reserve/settle — this function
    owns only the ledger transition and the LiteLLM revoke.
    """
    from .database import AsyncSessionLocal
    from .services import litellm_keys
    from .services.litellm_service import litellm_service

    async with AsyncSessionLocal() as db:
        try:
            await litellm_keys.begin_settlement(
                db, delegate=litellm_service, key_id=key_id, reason="complete"
            )
            await litellm_keys.finalize_settlement(db, key_id=key_id)
            await db.commit()
            return {"key_id": key_id, "state": "settled"}
        except Exception:
            await db.rollback()
            logger.exception("settle_invocation_key: %s failed", key_id)
            raise


async def cascade_revoke_children(ctx: dict, parent_key_id: str) -> dict:
    """Enqueue-able: BFS revoke all active descendants of a key.

    Fired when a parent transitions out of active (explicit revoke, failed
    state, etc.). Returns the list of revoked key_ids.
    """
    from .database import AsyncSessionLocal
    from .services import litellm_keys
    from .services.litellm_service import litellm_service

    async with AsyncSessionLocal() as db:
        try:
            revoked = await litellm_keys.cascade_revoke(
                db, delegate=litellm_service, parent_key_id=parent_key_id
            )
            await db.commit()
            return {"parent_key_id": parent_key_id, "revoked": revoked}
        except Exception:
            await db.rollback()
            logger.exception("cascade_revoke_children: %s failed", parent_key_id)
            raise


async def refill_warm_pools_cron(ctx: dict) -> dict:
    """Every 60s: refill warm pools for all installed AppInstances whose
    manifest declares any hosted agent with `warm_pool_size > 0`.

    The refill is idempotent — it only mints the shortfall per agent.
    """
    from sqlalchemy import select

    from .database import AsyncSessionLocal
    from .models import AppInstance
    from .services.apps import warm_pool
    from .services.litellm_service import litellm_service

    async with AsyncSessionLocal() as db:
        try:
            instance_ids = (
                (await db.execute(select(AppInstance.id).where(AppInstance.state == "installed")))
                .scalars()
                .all()
            )
        except Exception:
            logger.exception("refill_warm_pools_cron: scan failed")
            return {"scanned": 0, "refilled": 0}

    refilled = 0
    for instance_id in instance_ids:
        async with AsyncSessionLocal() as db:
            try:
                result = await warm_pool.refill_warm_pool(
                    db, app_instance_id=instance_id, delegate=litellm_service
                )
                await db.commit()
                if result.get("minted", 0) > 0:
                    refilled += 1
            except Exception:
                await db.rollback()
                logger.exception("refill_warm_pools_cron: instance %s failed", instance_id)
    return {"scanned": len(instance_ids), "refilled": refilled}


async def refill_warm_pool_task(ctx: dict, app_instance_id: str) -> dict:
    """Enqueue-able per-instance warm-pool refill (e.g., right after install)."""
    from .database import AsyncSessionLocal
    from .services.apps import warm_pool
    from .services.litellm_service import litellm_service

    async with AsyncSessionLocal() as db:
        try:
            result = await warm_pool.refill_warm_pool(
                db,
                app_instance_id=UUID(app_instance_id),
                delegate=litellm_service,
            )
            await db.commit()
            return result
        except Exception:
            await db.rollback()
            logger.exception("refill_warm_pool_task: %s failed", app_instance_id)
            raise


async def drain_warm_pool_task(ctx: dict, app_instance_id: str) -> dict:
    """Enqueue-able warm-pool drain on uninstall/yank."""
    from .database import AsyncSessionLocal
    from .services.apps import warm_pool
    from .services.litellm_service import litellm_service

    async with AsyncSessionLocal() as db:
        try:
            count = await warm_pool.drain_warm_pool(
                db,
                app_instance_id=UUID(app_instance_id),
                delegate=litellm_service,
            )
            await db.commit()
            return {"app_instance_id": app_instance_id, "drained": count}
        except Exception:
            await db.rollback()
            logger.exception("drain_warm_pool_task: %s failed", app_instance_id)
            raise


from .services.apps.app_invocations import invoke_app_instance_task  # noqa: E402
from .services.apps.settlement_worker import (  # noqa: E402
    settle_spend_batch as settle_spend_batch_cron,
)


async def run_stage1_scan_task(ctx: dict, submission_id: str) -> dict:
    """Wave 7: run the Stage1 structural scan on a submission."""
    from uuid import UUID as _UUID

    from .database import AsyncSessionLocal
    from .services.apps import stage1_scanner

    async with AsyncSessionLocal() as db:
        try:
            out = await stage1_scanner.run_stage1_scan(db, submission_id=_UUID(submission_id))
            await db.commit()
            return out
        except Exception:
            await db.rollback()
            logger.exception("run_stage1_scan_task: %s failed", submission_id)
            raise


async def run_stage2_eval_task(ctx: dict, submission_id: str) -> dict:
    """Wave 7: run the Stage2 sandbox eval on a submission."""
    from uuid import UUID as _UUID

    from .database import AsyncSessionLocal
    from .services.apps import stage2_sandbox

    async with AsyncSessionLocal() as db:
        try:
            out = await stage2_sandbox.run_stage2_eval(db, submission_id=_UUID(submission_id))
            await db.commit()
            return out
        except Exception:
            await db.rollback()
            logger.exception("run_stage2_eval_task: %s failed", submission_id)
            raise


async def run_monitoring_sweep_task(ctx: dict, app_version_id: str) -> dict:
    """Wave 7: run a single monitoring canary sweep for an approved AppVersion."""
    from uuid import UUID as _UUID

    from .database import AsyncSessionLocal
    from .services.apps import monitoring_sweep

    async with AsyncSessionLocal() as db:
        try:
            out = await monitoring_sweep.run_monitoring_sweep(
                db, app_version_id=_UUID(app_version_id)
            )
            await db.commit()
            return out
        except Exception:
            await db.rollback()
            logger.exception("run_monitoring_sweep_task: %s failed", app_version_id)
            raise


async def process_schedule_triggers_cron(ctx: dict) -> dict:
    """Wave 7 cron: drain pending schedule_trigger_events."""
    from .services.apps import schedule_triggers

    try:
        return await schedule_triggers.process_trigger_events_batch(ctx)
    except Exception:
        logger.exception("process_schedule_triggers_cron failed")
        return {"processed": 0, "failed": 0, "skipped": 0, "error": True}


async def reap_orphaned_install_attempts_cron(ctx: dict) -> dict:
    """Wave 9 A2 cron: free Hub volumes orphaned by crashed installs.

    Cheap when idle (single indexed scan on ``app_install_attempts`` where
    ``state='hub_created'``). 60s cadence; grace window 15 min before an
    attempt is eligible for reaping.
    """
    from .config import get_settings
    from .services.apps.install_reaper import reap_orphaned_install_attempts
    from .services.hub_client import HubClient

    hub = HubClient(get_settings().volume_hub_address)
    try:
        return await reap_orphaned_install_attempts(hub)
    except Exception:
        logger.exception("reap_orphaned_install_attempts_cron failed")
        return {"scanned": 0, "reaped": 0, "failed": 0, "error": True}
    finally:
        close = getattr(hub, "close", None)
        if callable(close):
            with contextlib.suppress(Exception):
                await close()


async def db_event_dispatcher_cron(ctx: dict) -> dict:
    """Wave 9 D1 cron: drain tesslate:db_events:* streams into ScheduleTriggerEvent.

    No-op while no AgentSchedule has trigger_kind='db_event'. Wave 10 lights
    consumers up; the rails ship now so schema/topology are stable.
    """
    from .services.apps.db_event_dispatcher import db_event_dispatcher

    try:
        return await db_event_dispatcher(ctx)
    except Exception:
        logger.exception("db_event_dispatcher_cron failed")
        return {"streams": 0, "events": 0, "inserted": 0, "error": True}


async def startup(ctx: dict):
    """Worker startup hook — initialize logging."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logger.info("[WORKER] ARQ worker started")

    # Load prompt-caching eligible models from LiteLLM
    from .agent.prompt_caching import refresh_eligible_models

    await refresh_eligible_models()


async def shutdown(ctx: dict):
    """Worker shutdown hook — cleanup."""
    logger.info("[WORKER] ARQ worker shutting down")


def _get_redis_settings() -> RedisSettings:
    """Build ARQ RedisSettings from REDIS_URL environment variable."""
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")

    # Parse redis://host:port/db format
    from urllib.parse import urlparse

    parsed = urlparse(redis_url)
    return RedisSettings(
        host=parsed.hostname or "redis",
        port=parsed.port or 6379,
        database=int(parsed.path.lstrip("/") or "0"),
        password=parsed.password,
    )


def _get_worker_settings():
    """Load worker tuning values from app config (env-overridable)."""
    from .config import get_settings

    s = get_settings()
    return s.worker_max_jobs, s.worker_job_timeout, s.worker_max_tries


def _build_cron_jobs():
    """Build list of ARQ cron jobs from settings."""
    from arq.cron import cron

    from .config import get_settings

    s = get_settings()
    jobs = []

    if s.template_build_enabled and s.template_refresh_interval_hours > 0:
        # Run template refresh at the configured interval.
        # ARQ cron uses hour= to set which hours the job runs.
        # For a 24h interval, run at midnight; for shorter intervals,
        # build a set of hours to match the cadence.
        interval_h = s.template_refresh_interval_hours
        run_hours = set(range(0, 24, interval_h)) if interval_h < 24 else {0}
        jobs.append(
            cron(
                refresh_templates,
                hour=run_hours,
                minute={0},
                timeout=s.template_build_timeout + 120,  # extra grace for multiple builds
                unique=True,
                run_at_startup=False,
            )
        )

    # Tesslate Apps: idle session-key reaper. Runs every minute; short budget.
    # The reaper is cheap when idle (single SELECT with partial index), so
    # the 60s cadence is safe and keeps session TTL enforcement tight.
    jobs.append(
        cron(
            reap_idle_session_keys,
            minute=set(range(0, 60)),  # every minute
            timeout=120,
            unique=True,
            run_at_startup=False,
        )
    )

    # Tesslate Apps: spend settlement sweep. Every minute, bounded batch.
    jobs.append(
        cron(
            settle_spend_batch_cron,
            minute=set(range(0, 60)),
            timeout=180,
            unique=True,
            run_at_startup=False,
        )
    )

    # Tesslate Apps (Wave 6): hosted-agent warm-pool refill. 60s cadence.
    jobs.append(
        cron(
            refill_warm_pools_cron,
            minute=set(range(0, 60)),
            timeout=120,
            unique=True,
            run_at_startup=False,
        )
    )

    # Tesslate Apps (Wave 7): schedule trigger events drain. 60s cadence.
    jobs.append(
        cron(
            process_schedule_triggers_cron,
            minute=set(range(0, 60)),
            timeout=120,
            unique=True,
            run_at_startup=False,
        )
    )

    # Tesslate Apps (Wave 9 A2): orphaned install-attempt reaper. 60s cadence.
    # Grace window is 15 min inside the reaper; keep cron cheap and frequent.
    jobs.append(
        cron(
            reap_orphaned_install_attempts_cron,
            minute=set(range(0, 60)),
            timeout=120,
            unique=True,
            run_at_startup=False,
        )
    )

    # Tesslate Apps (Wave 9 D1): DB-event stream drain → ScheduleTriggerEvent.
    # 5-second cadence — DB events should feel near-real-time to Apps. The
    # cron is cheap when no streams exist (single SCAN, returns immediately).
    jobs.append(
        cron(
            db_event_dispatcher_cron,
            second=set(range(0, 60, 5)),
            timeout=60,
            unique=True,
            run_at_startup=False,
        )
    )

    return jobs


_max_jobs, _job_timeout, _max_tries = _get_worker_settings()


class WorkerSettings:
    """ARQ worker configuration."""

    functions = [
        execute_agent_task,
        send_webhook_callback,
        reap_idle_session_keys,
        settle_invocation_key,
        cascade_revoke_children,
        settle_spend_batch_cron,
        refill_warm_pools_cron,
        refill_warm_pool_task,
        drain_warm_pool_task,
        run_stage1_scan_task,
        run_stage2_eval_task,
        run_monitoring_sweep_task,
        process_schedule_triggers_cron,
        db_event_dispatcher_cron,
        reap_orphaned_install_attempts_cron,
        invoke_app_instance_task,
    ]
    cron_jobs = _build_cron_jobs()
    redis_settings = _get_redis_settings()
    max_jobs = _max_jobs
    job_timeout = _job_timeout
    on_startup = startup
    on_shutdown = shutdown
    max_tries = _max_tries
