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
import json
import logging
import os
from uuid import UUID

from arq.connections import RedisSettings

logger = logging.getLogger(__name__)


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


async def _heartbeat_lock(pubsub, project_id: str, task_id: str):
    """Extend the project lock every 10 seconds until cancelled."""
    try:
        while True:
            await asyncio.sleep(10)
            extended = await pubsub.extend_project_lock(project_id, task_id)
            if not extended:
                logger.warning(
                    f"[WORKER] Failed to extend project lock for {project_id}, "
                    f"task {task_id} — lock may have been stolen"
                )
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
    from .agent.factory import create_agent_from_db_model
    from .agent.iterative_agent import _convert_uuids_to_strings
    from .agent.models import create_model_adapter
    from .config import get_settings
    from .database import AsyncSessionLocal
    from .models import AgentStep, Chat, MarketplaceAgent, Message, Project, UserPurchasedAgent
    from .services.agent_task import AgentTaskPayload
    from .services.pubsub import get_pubsub

    from sqlalchemy import select

    settings = get_settings()
    payload = AgentTaskPayload.from_dict(payload_dict)
    pubsub = get_pubsub()
    task_id = payload.task_id
    project_id = payload.project_id
    heartbeat_task = None
    lock_acquired = False

    logger.info(
        f"[WORKER] Starting agent task {task_id} for project {project_id}"
    )

    async with AsyncSessionLocal() as db:
        try:
            # 1. Load project
            result = await db.execute(
                select(Project).where(Project.id == UUID(project_id))
            )
            project = result.scalar_one_or_none()
            if not project:
                await _publish_error(pubsub, task_id, "Project not found")
                return

            # 2. Acquire per-project lock (if enabled in project settings)
            project_settings = project.settings or {}
            agent_lock_enabled = project_settings.get("agent_lock_enabled", True)

            if agent_lock_enabled and pubsub:
                lock_acquired = await pubsub.acquire_project_lock(project_id, task_id)
                if not lock_acquired:
                    holding_task = await pubsub.get_project_lock(project_id)
                    await _publish_error(
                        pubsub, task_id,
                        f"Another agent is running on this project (task: {holding_task})"
                    )
                    return
                # Start heartbeat to extend lock every 10s
                heartbeat_task = asyncio.create_task(
                    _heartbeat_lock(pubsub, project_id, task_id)
                )

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
                        container_id=(
                            UUID(payload.container_id)
                            if payload.container_id
                            else None
                        ),
                    )

            # 7. Create agent instance
            agent_instance = await create_agent_from_db_model(
                agent_model=agent_model,
                model_adapter=model_adapter,
                tools_override=tools_override,
            )

            # 8. Build execution context (same structure as chat.py)
            context = {
                "user_id": UUID(payload.user_id),
                "project_id": UUID(project_id),
                "project_slug": payload.project_slug,
                "container_directory": payload.container_directory,
                "chat_id": UUID(payload.chat_id),
                "db": db,
                "chat_history": payload.chat_history,
                "project_context": payload.project_context,
                "edit_mode": payload.edit_mode,
                "container_id": (
                    UUID(payload.container_id) if payload.container_id else None
                ),
                "container_name": payload.container_name,
                "view_context": (
                    payload.view_context.get("view")
                    if isinstance(payload.view_context, dict)
                    else payload.view_context
                ),
                "model_name": model_name,
                "agent_id": agent_model.id,
            }

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

            # Update chat status to running
            chat_result = await db.execute(
                select(Chat).where(Chat.id == UUID(payload.chat_id))
            )
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
                        completion_reason = complete_data.get("completion_reason", completion_reason)
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

            # 13. Publish done event
            if pubsub:
                await pubsub.publish_agent_event(
                    task_id, {"type": "done", "data": {"task_id": task_id}}
                )

            # 14. Enqueue webhook callback if configured
            if payload.webhook_callback_url:
                try:
                    arq_redis = ctx.get("redis")
                    if arq_redis:
                        from arq import create_pool

                        pool = await create_pool(_get_redis_settings())
                        await pool.enqueue_job(
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

            logger.info(
                f"[WORKER] Task {task_id} complete, saved to database"
            )

        except Exception as e:
            import traceback

            error_traceback = traceback.format_exc()
            logger.error(f"[WORKER] Agent task {task_id} failed: {e}")
            logger.error(f"[WORKER] Traceback:\n{error_traceback}")

            # Publish error event
            await _publish_error(pubsub, task_id, str(e))

            # Mark chat as active (not running) on error
            try:
                chat_result = await db.execute(
                    select(Chat).where(Chat.id == UUID(payload.chat_id))
                )
                chat = chat_result.scalar_one_or_none()
                if chat and chat.status == "running":
                    chat.status = "active"
                    await db.commit()
            except Exception:
                pass

        finally:
            # Always release project lock and cancel heartbeat
            if heartbeat_task:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass
            if lock_acquired and pubsub:
                await pubsub.release_project_lock(project_id, task_id)
                logger.debug(f"[WORKER] Released project lock for {project_id}")


async def send_webhook_callback(ctx: dict, url: str, payload: dict):
    """
    Send webhook callback to external client.

    ARQ handles retries (max_tries=5, exponential backoff).
    """
    import httpx

    logger.info(f"[WEBHOOK] Sending callback to {url}")

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()

    logger.info(f"[WEBHOOK] Callback sent successfully: {response.status_code}")


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


async def startup(ctx: dict):
    """Worker startup hook — initialize logging."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logger.info("[WORKER] ARQ worker started")


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


class WorkerSettings:
    """ARQ worker configuration."""

    functions = [execute_agent_task, send_webhook_callback]
    redis_settings = _get_redis_settings()
    max_jobs = 10  # Max concurrent agent tasks per worker
    job_timeout = 600  # 10 minute max per agent run
    on_startup = startup
    on_shutdown = shutdown
    # Retry failed jobs once (in case of transient errors)
    max_tries = 2
