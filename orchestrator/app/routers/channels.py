"""
Channels API

Webhook inbound endpoints for messaging platforms (Telegram, Slack, Discord,
WhatsApp) and CRUD management for channel configurations.

Webhook endpoints are unauthenticated — platform signature verification is
performed by each channel implementation.  CRUD endpoints require JWT auth.
"""

import json
import logging
import uuid as _uuid
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_db
from ..models import ChannelConfig, ChannelMessage, Chat, Message, Project, User
from ..schemas import (
    ChannelConfigCreate,
    ChannelConfigResponse,
    ChannelConfigUpdate,
    ChannelMessageResponse,
    ChannelTestRequest,
)
from ..services.channels import (
    decrypt_credentials,
    encrypt_credentials,
    get_channel,
)
from ..services.channels.registry import generate_webhook_secret
from ..users import current_active_user

settings = get_settings()
router = APIRouter(prefix="/api/channels", tags=["channels"])
logger = logging.getLogger(__name__)

# Rate limiter keyed per config_id extracted from the path
limiter = Limiter(key_func=get_remote_address)

# ---------------------------------------------------------------------------
# ARQ pool (lazy-init, same pattern as external_agent.py)
# ---------------------------------------------------------------------------
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
        logger.info("[ARQ-CHAN] Redis pool created for channel task dispatch")
        return _arq_pool
    except Exception as e:
        logger.warning(f"[ARQ-CHAN] Failed to create Redis pool: {e}")
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_webhook_url(channel_type: str, config_id: UUID) -> str:
    """Construct the full webhook URL for a channel config."""
    domain = settings.app_domain or "localhost"
    scheme = "https" if domain != "localhost" else "http"
    return f"{scheme}://{domain}/api/channels/webhook/{channel_type}/{config_id}"


def _mask_credentials(creds: dict) -> dict:
    """Return a dict with credential values masked for safe display."""
    masked: dict = {}
    for key, value in creds.items():
        if isinstance(value, str) and len(value) > 6:
            masked[key] = value[:3] + "***" + value[-3:]
        else:
            masked[key] = "***"
    return masked


async def _load_config_for_user(
    config_id: UUID, user: User, db: AsyncSession
) -> ChannelConfig:
    """Load a ChannelConfig owned by the given user, or raise 404."""
    result = await db.execute(
        select(ChannelConfig).where(
            ChannelConfig.id == config_id,
            ChannelConfig.user_id == user.id,
        )
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Channel config not found")
    return config


# ============================================================================
# Webhook Inbound — GET (verification handshakes)
# ============================================================================


@router.get("/webhook/{channel_type}/{config_id}")
async def webhook_verification(
    channel_type: str,
    config_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Handle GET-based webhook verification for platforms that require it.

    - Slack: URL verification — echo back the ``challenge`` parameter.
    - WhatsApp: Hub verification — validate ``hub.verify_token`` against the
      stored webhook secret and return ``hub.challenge``.
    - Discord: PING (type 1) — respond with type 1 JSON.
    """
    result = await db.execute(
        select(ChannelConfig).where(
            ChannelConfig.id == config_id,
            ChannelConfig.is_active.is_(True),
        )
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Channel config not found")

    params = dict(request.query_params)

    if channel_type == "slack":
        # Slack sends challenge as a query or JSON body during URL verification
        challenge = params.get("challenge", "")
        return Response(
            content=json.dumps({"challenge": challenge}),
            media_type="application/json",
        )

    elif channel_type == "whatsapp":
        # WhatsApp webhook verification
        mode = params.get("hub.mode", "")
        token = params.get("hub.verify_token", "")
        challenge = params.get("hub.challenge", "")

        if mode == "subscribe" and token == config.webhook_secret:
            logger.info(f"[WEBHOOK] WhatsApp verification OK for config {config_id}")
            return Response(content=challenge, media_type="text/plain")

        logger.warning(
            f"[WEBHOOK] WhatsApp verification failed for config {config_id}: "
            f"mode={mode}, token_match={token == config.webhook_secret}"
        )
        raise HTTPException(status_code=403, detail="Verification failed")

    elif channel_type == "discord":
        # Discord PING → ACK
        return Response(
            content=json.dumps({"type": 1}),
            media_type="application/json",
        )

    # Fallback: return 200 for unknown GET verification
    return Response(status_code=200)


# ============================================================================
# Webhook Inbound — POST (message ingestion)
# ============================================================================


@router.post("/webhook/{channel_type}/{config_id}")
@limiter.limit(lambda: f"{settings.channel_webhook_rate_limit}/minute")
async def webhook_inbound(
    channel_type: str,
    config_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Receive inbound webhook payloads from messaging platforms.

    1. Rate-limit per remote address.
    2. Load and validate the ChannelConfig.
    3. Verify platform signature via the channel implementation.
    4. Parse the inbound payload into an InboundMessage.
    5. Store a ChannelMessage audit record.
    6. Enqueue an agent task (non-blocking).
    7. Return 200 immediately.

    Slack URL-verification POSTs (``{"type": "url_verification"}``) are handled
    inline without enqueuing a task.
    """
    # --- Load config ---
    result = await db.execute(
        select(ChannelConfig).where(
            ChannelConfig.id == config_id,
            ChannelConfig.is_active.is_(True),
        )
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Channel config not found")

    if config.channel_type != channel_type:
        raise HTTPException(
            status_code=400,
            detail="Channel type mismatch between URL and config",
        )

    # --- Read raw body + headers ---
    body = await request.body()
    headers = dict(request.headers)

    # --- Decrypt credentials & instantiate channel ---
    try:
        credentials = decrypt_credentials(config.credentials)
    except Exception as e:
        logger.exception(f"[WEBHOOK] Failed to decrypt credentials for config {config_id}")
        raise HTTPException(status_code=500, detail="Internal configuration error") from e

    channel = get_channel(channel_type, credentials)

    # --- Handle Slack URL verification POST (must respond before signature check
    #     because Slack's initial verification POST may arrive before the signing
    #     secret is fully configured) ---
    if channel_type == "slack":
        try:
            payload = json.loads(body)
            if payload.get("type") == "url_verification":
                logger.info(f"[WEBHOOK] Slack URL verification for config {config_id}")
                return Response(
                    content=json.dumps({"challenge": payload.get("challenge", "")}),
                    media_type="application/json",
                )
        except (json.JSONDecodeError, TypeError):
            pass

    # --- Verify webhook signature ---
    try:
        is_valid = await channel.verify_webhook(headers, body)
    except Exception as e:
        logger.exception(f"[WEBHOOK] Signature verification error for config {config_id}")
        raise HTTPException(status_code=401, detail="Webhook verification error") from e

    if not is_valid:
        logger.warning(f"[WEBHOOK] Invalid signature for config {config_id}")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    # --- Handle Discord PING POST (after signature verification for security) ---
    if channel_type == "discord":
        try:
            ping_payload = json.loads(body)
            if ping_payload.get("type") == 1:
                logger.info(f"[WEBHOOK] Discord PING (verified) for config {config_id}")
                return Response(
                    content=json.dumps({"type": 1}),
                    media_type="application/json",
                )
        except (json.JSONDecodeError, TypeError):
            pass

    # --- Parse inbound payload ---
    try:
        payload = json.loads(body) if isinstance(body, bytes) else body
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from e

    inbound = channel.parse_inbound(payload)
    if inbound is None:
        # Non-message event (e.g., bot's own messages, reactions) — acknowledge
        return Response(status_code=200)

    # --- Store inbound ChannelMessage ---
    task_id = str(_uuid.uuid4())

    channel_message = ChannelMessage(
        channel_config_id=config.id,
        direction="inbound",
        jid=inbound.jid,
        sender_name=inbound.sender_name,
        content=inbound.text,
        platform_message_id=inbound.platform_message_id,
        task_id=task_id,
        status="delivered",
    )
    db.add(channel_message)
    await db.commit()

    # --- Resolve project for agent context ---
    project = None
    if config.project_id:
        proj_result = await db.execute(
            select(Project).where(Project.id == config.project_id)
        )
        project = proj_result.scalar_one_or_none()

    if not project:
        # No project linked — still acknowledge but log
        logger.warning(
            f"[WEBHOOK] Config {config_id} has no linked project, cannot dispatch agent"
        )
        return Response(status_code=200)

    # --- Create chat session for this inbound message ---
    chat = Chat(
        user_id=config.user_id,
        project_id=project.id,
        origin="channel",
        title=f"[{channel_type}] {inbound.sender_name or 'user'}: {inbound.text[:50]}",
    )
    db.add(chat)
    await db.commit()
    await db.refresh(chat)

    user_message = Message(chat_id=chat.id, role="user", content=inbound.text)
    db.add(user_message)
    await db.commit()

    # --- Enqueue agent task (non-blocking) ---
    arq_pool = await _get_arq_pool()
    if not arq_pool:
        logger.error("[WEBHOOK] ARQ pool unavailable — cannot dispatch agent task")
        return Response(status_code=200)

    from ..services.agent_task import AgentTaskPayload

    payload_obj = AgentTaskPayload(
        task_id=task_id,
        user_id=str(config.user_id),
        project_id=str(project.id),
        project_slug=project.slug,
        chat_id=str(chat.id),
        message=inbound.text,
        agent_id=str(config.default_agent_id) if config.default_agent_id else None,
        model_name="",
        channel_config_id=str(config.id),
        channel_jid=inbound.jid,
        channel_type=channel_type,
    )

    try:
        await arq_pool.enqueue_job("execute_agent_task", payload_obj.to_dict())
        logger.info(
            f"[WEBHOOK] Enqueued agent task {task_id} for config {config_id} "
            f"(jid={inbound.jid})"
        )
    except Exception:
        logger.exception(f"[WEBHOOK] Failed to enqueue agent task {task_id}")

    return Response(status_code=200)


# ============================================================================
# CRUD — Create
# ============================================================================


@router.post("/configs", response_model=ChannelConfigResponse)
async def create_channel_config(
    payload: ChannelConfigCreate,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new channel configuration.

    Encrypts credentials, generates a webhook secret, and optionally
    auto-registers the webhook with the platform (e.g., Telegram setWebhook).
    """
    # Validate project ownership if project_id supplied
    if payload.project_id:
        proj_result = await db.execute(
            select(Project).where(
                Project.id == payload.project_id,
                Project.owner_id == user.id,
            )
        )
        if not proj_result.scalar_one_or_none():
            raise HTTPException(
                status_code=404, detail="Project not found or access denied"
            )

    # Encrypt credentials and generate webhook secret
    encrypted = encrypt_credentials(payload.credentials)
    secret = generate_webhook_secret()

    config = ChannelConfig(
        user_id=user.id,
        project_id=payload.project_id,
        channel_type=payload.channel_type,
        name=payload.name,
        credentials=encrypted,
        webhook_secret=secret,
        default_agent_id=payload.default_agent_id,
        is_active=True,
    )
    db.add(config)
    await db.commit()
    await db.refresh(config)

    webhook_url = _build_webhook_url(config.channel_type, config.id)

    # Auto-register webhook with platform (non-blocking best-effort)
    try:
        channel = get_channel(payload.channel_type, payload.credentials)
        reg_result = await channel.register_webhook(webhook_url, secret)
        logger.info(
            f"[CHANNELS] Webhook registration for {payload.channel_type}: {reg_result}"
        )
    except Exception:
        logger.warning(
            f"[CHANNELS] Auto-registration failed for {payload.channel_type} "
            f"config {config.id} — user may need to configure webhook URL manually",
            exc_info=True,
        )

    logger.info(
        f"[CHANNELS] Created {payload.channel_type} config '{payload.name}' "
        f"(id={config.id}) for user {user.id}"
    )

    return ChannelConfigResponse(
        id=config.id,
        channel_type=config.channel_type,
        name=config.name,
        project_id=config.project_id,
        default_agent_id=config.default_agent_id,
        is_active=config.is_active,
        webhook_url=webhook_url,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


# ============================================================================
# CRUD — List
# ============================================================================


@router.get("/configs", response_model=list[ChannelConfigResponse])
async def list_channel_configs(
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List all channel configs for the authenticated user."""
    result = await db.execute(
        select(ChannelConfig)
        .where(ChannelConfig.user_id == user.id)
        .order_by(ChannelConfig.created_at.desc())
    )
    configs = result.scalars().all()

    return [
        ChannelConfigResponse(
            id=c.id,
            channel_type=c.channel_type,
            name=c.name,
            project_id=c.project_id,
            default_agent_id=c.default_agent_id,
            is_active=c.is_active,
            webhook_url=_build_webhook_url(c.channel_type, c.id),
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
        for c in configs
    ]


# ============================================================================
# CRUD — Read single
# ============================================================================


@router.get("/configs/{config_id}", response_model=ChannelConfigResponse)
async def get_channel_config(
    config_id: UUID,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get a single channel config.

    Credentials are masked in the response — only partial values are shown.
    """
    config = await _load_config_for_user(config_id, user, db)

    return ChannelConfigResponse(
        id=config.id,
        channel_type=config.channel_type,
        name=config.name,
        project_id=config.project_id,
        default_agent_id=config.default_agent_id,
        is_active=config.is_active,
        webhook_url=_build_webhook_url(config.channel_type, config.id),
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


# ============================================================================
# CRUD — Update
# ============================================================================


@router.patch("/configs/{config_id}", response_model=ChannelConfigResponse)
async def update_channel_config(
    config_id: UUID,
    payload: ChannelConfigUpdate,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a channel configuration (name, credentials, agent, active state)."""
    config = await _load_config_for_user(config_id, user, db)

    if payload.name is not None:
        config.name = payload.name

    if payload.credentials is not None:
        config.credentials = encrypt_credentials(payload.credentials)

    if payload.default_agent_id is not None:
        config.default_agent_id = payload.default_agent_id

    if payload.is_active is not None:
        config.is_active = payload.is_active

    await db.commit()
    await db.refresh(config)

    webhook_url = _build_webhook_url(config.channel_type, config.id)

    # Re-register webhook if credentials changed
    if payload.credentials is not None:
        try:
            channel = get_channel(config.channel_type, payload.credentials)
            await channel.register_webhook(webhook_url, config.webhook_secret)
        except Exception:
            logger.warning(
                f"[CHANNELS] Webhook re-registration failed for config {config_id}",
                exc_info=True,
            )

    logger.info(f"[CHANNELS] Updated config {config_id} for user {user.id}")

    return ChannelConfigResponse(
        id=config.id,
        channel_type=config.channel_type,
        name=config.name,
        project_id=config.project_id,
        default_agent_id=config.default_agent_id,
        is_active=config.is_active,
        webhook_url=webhook_url,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


# ============================================================================
# CRUD — Soft Delete (deactivate)
# ============================================================================


@router.delete("/configs/{config_id}")
async def delete_channel_config(
    config_id: UUID,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Soft-deactivate a channel configuration.

    Attempts to deregister the webhook with the platform (best-effort).
    The config remains in the database for audit purposes.
    """
    config = await _load_config_for_user(config_id, user, db)

    if not config.is_active:
        raise HTTPException(status_code=400, detail="Channel config is already deactivated")

    # Best-effort deregister webhook
    try:
        credentials = decrypt_credentials(config.credentials)
        channel = get_channel(config.channel_type, credentials)
        await channel.deregister_webhook()
    except Exception:
        logger.warning(
            f"[CHANNELS] Webhook deregistration failed for config {config_id}",
            exc_info=True,
        )

    config.is_active = False
    await db.commit()

    logger.info(f"[CHANNELS] Deactivated config {config_id} for user {user.id}")

    return {"status": "deactivated", "config_id": str(config_id)}


# ============================================================================
# Test — send a test message through the channel
# ============================================================================


@router.post("/configs/{config_id}/test")
async def test_channel_config(
    config_id: UUID,
    payload: ChannelTestRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Send a test message through the channel to verify it works end-to-end.

    Stores the outbound message in ChannelMessage for audit.
    """
    config = await _load_config_for_user(config_id, user, db)

    if not config.is_active:
        raise HTTPException(status_code=400, detail="Channel config is not active")

    try:
        credentials = decrypt_credentials(config.credentials)
    except Exception as e:
        logger.exception(f"[CHANNELS] Failed to decrypt credentials for config {config_id}")
        raise HTTPException(status_code=500, detail="Internal configuration error") from e

    channel = get_channel(config.channel_type, credentials)
    test_text = "Hello from Tesslate Studio! Your channel is configured correctly."

    try:
        result = await channel.send_message(payload.jid, test_text)
    except Exception as exc:
        logger.exception(f"[CHANNELS] Test message failed for config {config_id}")
        raise HTTPException(
            status_code=502,
            detail=f"Failed to send test message: {exc}",
        ) from exc

    # Record outbound test message
    channel_message = ChannelMessage(
        channel_config_id=config.id,
        direction="outbound",
        jid=payload.jid,
        content=test_text,
        platform_message_id=result.get("platform_message_id"),
        status="delivered" if result.get("ok", True) else "failed",
    )
    db.add(channel_message)
    await db.commit()

    return {
        "status": "sent",
        "platform_message_id": result.get("platform_message_id"),
        "detail": result,
    }


# ============================================================================
# Message history
# ============================================================================


@router.get(
    "/configs/{config_id}/messages",
    response_model=list[ChannelMessageResponse],
)
async def list_channel_messages(
    config_id: UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List recent messages for a channel config (paginated)."""
    # Verify ownership
    await _load_config_for_user(config_id, user, db)

    result = await db.execute(
        select(ChannelMessage)
        .where(ChannelMessage.channel_config_id == config_id)
        .order_by(ChannelMessage.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    messages = result.scalars().all()

    return [
        ChannelMessageResponse(
            id=m.id,
            channel_config_id=m.channel_config_id,
            direction=m.direction,
            jid=m.jid,
            sender_name=m.sender_name,
            content=m.content,
            platform_message_id=m.platform_message_id,
            task_id=m.task_id,
            status=m.status,
            created_at=m.created_at,
        )
        for m in messages
    ]
