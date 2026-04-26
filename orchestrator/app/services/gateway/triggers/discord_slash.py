"""Discord slash-command + bot-mention triggers (Phase 4).

Discord slash commands arrive as Interactions (type=2) with a
``data.options`` array. The Discord adapter extracts ``data.name`` (e.g.
``"automation"``), the leading subcommand (``"run"``), and the ``name``
+ args options into a normalized dict before calling this module:

    {"command_name": "automation",
     "subcommand": "run",
     "options": {"name": "standup", "args": "..."},
     "user_id": "...",
     "channel_id": "...",
     "guild_id": "..."}

Bot mentions in messages are also normalized to ``{"text": "<@BOT> ...",
"user_id": ...}`` so the same parser works for both.
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


__all__ = ["dispatch_from_discord", "handle_discord_command"]


async def _resolve_owner(
    db: AsyncSession, channel_config_id: uuid.UUID
) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    config = await db.scalar(
        select(ChannelConfig).where(ChannelConfig.id == channel_config_id)
    )
    if config is None:
        return None, None
    return config.user_id, getattr(config, "team_id", None)


def _build_text_from_interaction(payload: dict[str, Any]) -> str:
    """Reconstitute a slash-command text shape that ``parse_slash_command``
    can chew on (so we share the same parser across platforms)."""
    cmd = payload.get("command_name") or ""
    sub = payload.get("subcommand") or ""
    options = payload.get("options") or {}
    name = options.get("name") or ""
    args = options.get("args") or ""
    parts = []
    if cmd:
        parts.append("/" + cmd if not cmd.startswith("/") else cmd)
    if sub:
        parts.append(sub)
    if name:
        parts.append(name)
    if args:
        parts.append(args)
    return " ".join(parts).strip()


async def dispatch_from_discord(
    *,
    payload: dict[str, Any],
    channel_config_id: uuid.UUID,
    db: AsyncSession,
    arq_pool: Any,
) -> dict[str, Any]:
    """Route a Discord slash command or mention into the dispatcher."""
    # Two normalized shapes: slash-interaction (has ``command_name``) and
    # message-mention (has ``text`` starting with ``<@BOT>``).
    if payload.get("command_name"):
        raw_text = _build_text_from_interaction(payload)
        parsed = parse_slash_command(raw_text)
    else:
        raw_text = (payload.get("text") or "").strip()
        parsed = parse_bot_mention(raw_text)

    if parsed.kind == "unknown":
        return {"ack": "ok", "error": "could_not_parse", "raw": raw_text[:200]}

    platform_user_id = str(payload.get("user_id") or "")
    identity = await resolve_platform_identity(
        db, platform="discord", platform_user_id=platform_user_id
    )

    owner_user_id, team_id = await _resolve_owner(db, channel_config_id)
    invoking_user_id = identity.user_id if identity else owner_user_id

    extra_payload: dict[str, Any] = {
        "channel_config_id": str(channel_config_id),
        "discord_channel_id": payload.get("channel_id"),
        "discord_guild_id": payload.get("guild_id"),
        "discord_user_id": platform_user_id,
        "discord_interaction_id": payload.get("interaction_id"),
        "discord_interaction_token": payload.get("interaction_token"),
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
            platform="discord",
            invoking_user_id=invoking_user_id,
            raw_text=raw_text,
            args=parsed.args,
            extra_payload=extra_payload,
        )
    except GatewayCommandError as exc:
        return {"ack": "ok", "error": "enqueue_failed", "detail": str(exc)}

    return {"event_id": str(event_id), "ack": "ok"}


# Alias matching the ``handle_<platform>_command`` naming convention.
async def handle_discord_command(
    body: dict[str, Any],
    *,
    channel_config_id: uuid.UUID,
    db: AsyncSession,
    arq_pool: Any,
) -> dict[str, Any]:
    """Thin shim — see :func:`dispatch_from_discord` for the contract."""
    return await dispatch_from_discord(
        payload=body,
        channel_config_id=channel_config_id,
        db=db,
        arq_pool=arq_pool,
    )
