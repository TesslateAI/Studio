"""Telegram slash-command + bot-mention triggers (Phase 4).

Telegram slash commands arrive as ``/automation_run <name> [args...]``
(no spaces in the command per Telegram convention). Bot mentions arrive
as ``@mybot <action_name> [args...]`` in groups. The Telegram adapter
identifies both via the leading ``/`` or ``@`` and forwards the message
text + sender id here.

Same shape as the Slack handler: parse → resolve identity → resolve
automation/action → ingest event → enqueue ``dispatch_automation_task``
→ return ``{"event_id", "ack"}`` (or an error envelope).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import ChannelConfig
from .common import (
    GatewayCommandError,
    NoMatchingAppAction,
    NoMatchingAutomation,
    ingest_and_enqueue_command,
    parse_bot_mention,
    parse_slash_command,
    resolve_app_action_by_name,
    resolve_automation_by_name,
    resolve_platform_identity,
)

logger = logging.getLogger(__name__)


__all__ = ["dispatch_from_telegram", "handle_telegram_command"]


async def _resolve_owner(
    db: AsyncSession, channel_config_id: uuid.UUID
) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    config = await db.scalar(
        select(ChannelConfig).where(ChannelConfig.id == channel_config_id)
    )
    if config is None:
        return None, None
    return config.user_id, getattr(config, "team_id", None)


async def dispatch_from_telegram(
    *,
    payload: dict[str, Any],
    channel_config_id: uuid.UUID,
    db: AsyncSession,
    arq_pool: Any,
) -> dict[str, Any]:
    """Route a Telegram slash command or mention into the dispatcher.

    The payload shape is the verbatim ``message`` object from the Telegram
    Update — caller (the adapter) extracts the relevant ``message`` from
    the outer Update envelope.
    """
    raw_text: str = (payload.get("text") or "").strip()
    if not raw_text:
        return {"ack": "ok", "error": "empty_text"}

    is_slash = raw_text.startswith("/")
    if is_slash:
        # Telegram slash commands may include ``@botname`` suffix —
        # strip it so the parser sees ``/automation_run`` not
        # ``/automation_run@mybot``.
        first, _, rest = raw_text.partition(" ")
        first_clean = first.split("@", 1)[0]
        normalized = (first_clean + (" " + rest if rest else "")).strip()
        parsed = parse_slash_command(normalized)
    else:
        parsed = parse_bot_mention(raw_text)

    if parsed.kind == "unknown":
        return {"ack": "ok", "error": "could_not_parse", "raw": raw_text[:200]}

    sender = payload.get("from") or {}
    platform_user_id = str(sender.get("id") or "")
    identity = await resolve_platform_identity(
        db, platform="telegram", platform_user_id=platform_user_id
    )

    owner_user_id, team_id = await _resolve_owner(db, channel_config_id)
    invoking_user_id = identity.user_id if identity else owner_user_id

    chat = payload.get("chat") or {}
    extra_payload: dict[str, Any] = {
        "channel_config_id": str(channel_config_id),
        "telegram_chat_id": str(chat.get("id") or ""),
        "telegram_chat_type": chat.get("type"),
        "telegram_user_id": platform_user_id,
        "telegram_message_id": payload.get("message_id"),
    }
    if parsed.app_alias:
        extra_payload["mention_alias"] = parsed.app_alias

    try:
        if parsed.kind == "automation":
            automation = await resolve_automation_by_name(
                db,
                name=parsed.name,
                owner_user_id=invoking_user_id,
                team_id=team_id,
            )
        else:
            _action, automation = await resolve_app_action_by_name(
                db,
                name=parsed.name,
                app_alias=parsed.app_alias,
                owner_user_id=invoking_user_id,
                team_id=team_id,
            )
            extra_payload["app_action_name"] = parsed.name
    except NoMatchingAutomation as exc:
        return {"ack": "ok", "error": "no_automation", "detail": str(exc)}
    except NoMatchingAppAction as exc:
        return {"ack": "ok", "error": "no_app_action", "detail": str(exc)}

    try:
        event_id = await ingest_and_enqueue_command(
            db,
            arq_pool,
            automation=automation,
            platform="telegram",
            invoking_user_id=invoking_user_id,
            raw_text=raw_text,
            args=parsed.args,
            extra_payload=extra_payload,
        )
    except GatewayCommandError as exc:
        return {"ack": "ok", "error": "enqueue_failed", "detail": str(exc)}

    return {"event_id": str(event_id), "ack": "ok"}


# Alias matching the ``handle_<platform>_command`` naming convention.
async def handle_telegram_command(
    body: dict[str, Any],
    *,
    channel_config_id: uuid.UUID,
    db: AsyncSession,
    arq_pool: Any,
) -> dict[str, Any]:
    """Thin shim — see :func:`dispatch_from_telegram` for the contract."""
    return await dispatch_from_telegram(
        payload=body,
        channel_config_id=channel_config_id,
        db=db,
        arq_pool=arq_pool,
    )
