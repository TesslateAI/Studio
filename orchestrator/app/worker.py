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
            # 1. Load project
            result = await db.execute(select(Project).where(Project.id == UUID(project_id)))
            project = result.scalar_one_or_none()
            if not project:
                await _publish_error(pubsub, task_id, "Project not found")
                return

            # 2. Acquire per-chat lock (allows concurrent agents across sessions)
            project_settings = project.settings or {}
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
            except Exception as mcp_err:
                logger.warning("[WORKER] MCP context loading failed (non-fatal): %s", mcp_err)

            container_id = UUID(payload.container_id) if payload.container_id else None
            container_name = payload.container_name
            container_directory = payload.container_directory

            if container_id and (not container_name or container_directory is None):
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
                project_id=project_id,
                container_name=container_name,
                db=db,
            )

            chat_history = payload.chat_history or await _get_chat_history(UUID(payload.chat_id), db, limit=10)

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
                "project_id": UUID(project_id),
            }
            active_plan = await PlanManager.get_plan(payload_context)

            # 8. Build execution context (same structure as chat.py)
            context = {
                "user_id": UUID(payload.user_id),
                "project_id": UUID(project_id),
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
                # Volume routing hints
                "volume_id": project.volume_id,
                "node_name": project.node_name,
                "volume_state": project.volume_state,
                "compute_tier": project.compute_tier,
            }

            # Inject MCP server configs so bridge executors can reconnect
            if mcp_context and mcp_context.get("mcp_configs"):
                context["mcp_configs"] = mcp_context["mcp_configs"]

            # Inject channel context for send_message "reply" channel
            if payload.channel_config_id:
                context["channel_config_id"] = payload.channel_config_id
                context["channel_jid"] = payload.channel_jid
                context["channel_type"] = payload.channel_type

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
                        await arq_redis.enqueue_job(
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
                    "git", "ls-remote", base.git_repo_url, "HEAD",
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
                logger.exception(
                    "[WORKER] Failed to refresh template for %s", base.slug
                )

        if rebuilt:
            logger.info("[WORKER] Refreshed %d templates", rebuilt)


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

    return jobs


_max_jobs, _job_timeout, _max_tries = _get_worker_settings()


class WorkerSettings:
    """ARQ worker configuration."""

    functions = [execute_agent_task, send_webhook_callback]
    cron_jobs = _build_cron_jobs()
    redis_settings = _get_redis_settings()
    max_jobs = _max_jobs
    job_timeout = _job_timeout
    on_startup = startup
    on_shutdown = shutdown
    max_tries = _max_tries
