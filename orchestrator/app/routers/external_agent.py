"""
External Agent API

Enables external clients (Slack bots, CLI tools, Discord bots) to invoke the
Tesslate agent, stream events, and poll status. Uses API key authentication.
"""

import asyncio
import hashlib
import json
import logging
import secrets
import uuid as _uuid
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth_external import get_external_api_user
from ..config import get_settings
from ..database import get_db
from ..models import Chat, Container, ExternalAPIKey, Message, Project, User
from ..schemas import (
    ExternalAgentInvokeRequest,
    ExternalAgentInvokeResponse,
    ExternalAgentStatusResponse,
    ExternalAPIKeyCreate,
    ExternalAPIKeyResponse,
)
from ..services.agent_context import (
    _build_architecture_context,
    _build_git_context,
    _build_tesslate_context,
    _get_chat_history,
    _resolve_container_name,
)
from ..users import current_active_user

settings = get_settings()
router = APIRouter(prefix="/api/external", tags=["external"])
logger = logging.getLogger(__name__)


# ARQ Redis pool (lazy initialized, separate from chat.py's pool)
_arq_pool = None


async def _get_arq_pool():
    """Get or create the ARQ Redis pool for task dispatch."""
    global _arq_pool
    if _arq_pool is not None:
        return _arq_pool

    from ..services.cache_service import get_redis_client

    redis = await get_redis_client()
    if not redis:
        return None

    try:
        from urllib.parse import urlparse

        from arq import create_pool
        from arq.connections import RedisSettings

        redis_url = settings.redis_url if hasattr(settings, "redis_url") else ""
        if not redis_url:
            return None

        parsed = urlparse(redis_url)
        _arq_pool = await create_pool(
            RedisSettings(
                host=parsed.hostname or "redis",
                port=parsed.port or 6379,
                database=int(parsed.path.lstrip("/") or "0"),
                password=parsed.password,
            )
        )
        logger.info("[ARQ-EXT] Redis pool created for external agent task dispatch")
        return _arq_pool
    except Exception as e:
        logger.warning(f"[ARQ-EXT] Failed to create Redis pool: {e}")
        return None


# =============================================================================
# Agent Invocation (API Key auth)
# =============================================================================


@router.post("/agent/invoke", response_model=ExternalAgentInvokeResponse)
async def invoke_agent(
    request: ExternalAgentInvokeRequest,
    user: User = Depends(get_external_api_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Invoke the Tesslate agent on a project.

    Requires API key authentication via Authorization: Bearer tsk_...
    Creates a new chat session with origin="api", saves the user message,
    builds context, and enqueues the agent task to the ARQ worker fleet.

    Returns task_id for polling status or subscribing to SSE events.
    """

    # Verify project access via RBAC
    from ..permissions import Permission, get_project_with_access

    project, _role = await get_project_with_access(
        db, str(request.project_id), user.id, Permission.CHAT_SEND
    )

    # Check API key project restrictions (if any)
    api_key_record = getattr(user, "_api_key_record", None)
    if api_key_record and api_key_record.project_ids:
        allowed_ids = [str(pid) for pid in api_key_record.project_ids]
        if str(request.project_id) not in allowed_ids:
            raise HTTPException(
                status_code=403,
                detail="API key does not have access to this project",
            )

    # Resolve container if specified
    container_id = None
    container_name = None
    container_directory = None

    if request.container_id:
        container_result = await db.execute(
            select(Container).where(
                Container.id == request.container_id,
                Container.project_id == request.project_id,
            )
        )
        container = container_result.scalar_one_or_none()
        if container:
            container_id = container.id
            container_name = _resolve_container_name(container)
            if container.directory and container.directory != ".":
                container_directory = container.directory
            logger.info(f"[EXT-AGENT] Using container: {container_name} (id: {container_id})")

    # Create a new chat session with origin="api"
    chat = Chat(
        user_id=user.id,
        project_id=request.project_id,
        origin="api",
        title=f"API: {request.message[:60]}",
    )
    db.add(chat)
    await db.commit()
    await db.refresh(chat)

    # Save user message
    user_message = Message(chat_id=chat.id, role="user", content=request.message)
    db.add(user_message)
    await db.commit()

    # Build project context
    project_context = {}

    # Architecture context
    arch_context = await _build_architecture_context(project, db)
    if arch_context:
        project_context["architecture"] = arch_context

    # Git context
    git_context = await _build_git_context(project, user.id, db)
    if git_context:
        project_context["git"] = git_context

    # TESSLATE.md context
    tesslate_context = await _build_tesslate_context(
        project,
        user.id,
        db,
        container_name=container_name,
        container_directory=container_directory,
    )
    if tesslate_context:
        project_context["tesslate_md"] = tesslate_context

    # Chat history (empty for new session, but the API allows reuse in future)
    chat_history = await _get_chat_history(chat.id, db, limit=10)

    # Generate task ID and enqueue
    agent_task_id = str(_uuid.uuid4())

    arq_pool = await _get_arq_pool()
    if not arq_pool:
        raise HTTPException(
            status_code=503,
            detail="Task queue not available. Redis is required for external agent invocation.",
        )

    from ..services.agent_task import AgentTaskPayload

    payload = AgentTaskPayload(
        task_id=agent_task_id,
        user_id=str(user.id),
        project_id=str(request.project_id),
        project_slug=project.slug,
        chat_id=str(chat.id),
        message=request.message,
        agent_id=str(request.agent_id) if request.agent_id else None,
        model_name="",
        container_id=str(container_id) if container_id else None,
        container_name=container_name,
        container_directory=container_directory,
        chat_history=chat_history,
        project_context=project_context,
        webhook_callback_url=request.webhook_callback_url,
    )

    await arq_pool.enqueue_job("execute_agent_task", payload.to_dict())
    logger.info(f"[EXT-AGENT] Enqueued agent task {agent_task_id} to ARQ worker")

    # Register task with TaskManager for status tracking
    from ..services.task_manager import TaskStatus, get_task_manager

    task_manager = get_task_manager()
    task_manager.create_task(
        user_id=user.id,
        task_type="agent_execution",
        metadata={
            "project_id": str(request.project_id),
            "chat_id": str(chat.id),
            "message": request.message[:200],
            "origin": "api",
        },
        task_id=agent_task_id,
    )
    await task_manager.update_task_status(agent_task_id, TaskStatus.RUNNING)

    # Publish cross-source visibility notification
    from ..services.pubsub import get_pubsub

    pubsub = get_pubsub()
    if pubsub:
        await pubsub.publish_agent_task_notification(
            user_id=user.id,
            project_id=request.project_id,
            notification={
                "type": "agent_task_started",
                "task_id": agent_task_id,
                "chat_id": str(chat.id),
                "origin": "api",
                "message": request.message[:200],
            },
        )

    # Build events URL relative to the configured domain
    app_domain = settings.app_domain if hasattr(settings, "app_domain") else ""
    scheme = "https" if app_domain else "http"
    base_url = f"{scheme}://{app_domain}" if app_domain else ""
    events_url = f"{base_url}/api/external/agent/events/{agent_task_id}"

    return ExternalAgentInvokeResponse(
        task_id=agent_task_id,
        chat_id=chat.id,
        events_url=events_url,
        status="queued",
    )


# =============================================================================
# Agent Events SSE (API Key auth)
# =============================================================================


@router.get("/agent/events/{task_id}")
async def subscribe_agent_events(
    task_id: str,
    last_event_id: str | None = None,
    user: User = Depends(get_external_api_user),
):
    """
    Subscribe to agent execution events via Server-Sent Events (SSE).

    Streams real-time events from the agent execution. Supports reconnection
    via the `last_event_id` query parameter.

    Returns a streaming response with Content-Type: text/event-stream.
    """
    from starlette.responses import StreamingResponse as StarletteStreamingResponse

    from ..services.pubsub import get_pubsub

    pubsub = get_pubsub()
    if not pubsub:
        raise HTTPException(status_code=503, detail="Redis not available")

    async def event_stream():
        try:
            if last_event_id:
                async for event in pubsub.subscribe_agent_events_from(task_id, last_event_id):
                    yield f"data: {json.dumps(event)}\n\n"
                    if event.get("type") in ("done",):
                        break
            else:
                async for event in pubsub.subscribe_agent_events(task_id):
                    if event.get("type") == "done":
                        break
                    yield f"data: {json.dumps(event)}\n\n"
        except (asyncio.CancelledError, GeneratorExit):
            return

    return StarletteStreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# =============================================================================
# Agent Status Polling (API Key auth)
# =============================================================================


@router.get("/agent/status/{task_id}", response_model=ExternalAgentStatusResponse)
async def get_agent_status(
    task_id: str,
    user: User = Depends(get_external_api_user),
):
    """
    Get the current status of an agent task.

    Use this for polling-based integrations that cannot consume SSE streams.
    """
    from ..services.task_manager import get_task_manager

    task_manager = get_task_manager()
    task = await task_manager.get_task_async(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Verify the task belongs to this user
    if str(task.user_id) != str(user.id):
        raise HTTPException(status_code=404, detail="Task not found")

    return ExternalAgentStatusResponse(
        task_id=task.id,
        status=task.status.value,
        final_response=task.result if isinstance(task.result, str) else None,
        iterations=task.metadata.get("iterations") if task.metadata else None,
        tool_calls_made=task.metadata.get("tool_calls_made") if task.metadata else None,
        started_at=task.started_at,
        completed_at=task.completed_at,
    )


# =============================================================================
# API Key Management (JWT auth - current_active_user)
# =============================================================================


@router.post("/keys", response_model=ExternalAPIKeyResponse)
async def create_api_key(
    request: ExternalAPIKeyCreate,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new external API key.

    The raw key is returned ONLY in this response and is never stored or
    shown again. Store it securely.
    """

    # Rate limit: max 10 active keys per user
    count_result = await db.execute(
        select(func.count(ExternalAPIKey.id)).where(
            ExternalAPIKey.user_id == user.id,
            ExternalAPIKey.is_active.is_(True),
        )
    )
    active_count = count_result.scalar() or 0
    if active_count >= 10:
        raise HTTPException(
            status_code=400,
            detail="Maximum of 10 active API keys allowed. Deactivate an existing key first.",
        )

    # Generate key: tsk_ + 32 random hex chars
    raw_key = f"tsk_{secrets.token_hex(16)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:8]

    # Calculate expiration
    expires_at = None
    if request.expires_in_days:
        expires_at = datetime.now(UTC) + timedelta(days=request.expires_in_days)

    api_key = ExternalAPIKey(
        user_id=user.id,
        key_hash=key_hash,
        key_prefix=key_prefix,
        name=request.name,
        scopes=request.scopes,
        project_ids=[str(pid) for pid in request.project_ids] if request.project_ids else None,
        expires_at=expires_at,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    logger.info(f"[EXT-API] Created API key '{request.name}' for user {user.id}")

    return ExternalAPIKeyResponse(
        id=api_key.id,
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        scopes=api_key.scopes,
        project_ids=[UUID(pid) for pid in api_key.project_ids] if api_key.project_ids else None,
        is_active=api_key.is_active,
        created_at=api_key.created_at,
        last_used_at=api_key.last_used_at,
        expires_at=api_key.expires_at,
        key=raw_key,  # Only returned on creation
    )


@router.get("/keys", response_model=list[ExternalAPIKeyResponse])
async def list_api_keys(
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List all API keys for the authenticated user.

    The raw key value is never included in list responses.
    """
    result = await db.execute(
        select(ExternalAPIKey)
        .where(ExternalAPIKey.user_id == user.id)
        .order_by(ExternalAPIKey.created_at.desc())
    )
    keys = result.scalars().all()

    return [
        ExternalAPIKeyResponse(
            id=k.id,
            name=k.name,
            key_prefix=k.key_prefix,
            scopes=k.scopes,
            project_ids=[UUID(pid) for pid in k.project_ids] if k.project_ids else None,
            is_active=k.is_active,
            created_at=k.created_at,
            last_used_at=k.last_used_at,
            expires_at=k.expires_at,
            key=None,  # Never expose the raw key after creation
        )
        for k in keys
    ]


@router.delete("/keys/{key_id}")
async def deactivate_api_key(
    key_id: UUID,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Deactivate an API key (soft delete).

    The key remains in the database for audit purposes but can no longer
    be used for authentication.
    """
    result = await db.execute(
        select(ExternalAPIKey).where(
            ExternalAPIKey.id == key_id,
            ExternalAPIKey.user_id == user.id,
        )
    )
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")

    if not api_key.is_active:
        raise HTTPException(status_code=400, detail="API key is already deactivated")

    api_key.is_active = False
    await db.commit()

    logger.info(f"[EXT-API] Deactivated API key '{api_key.name}' (id: {key_id}) for user {user.id}")

    return {"status": "deactivated", "key_id": str(key_id)}
