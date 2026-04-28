"""Slack slash-command + mention triggers (Phase 4).

Wired up by :class:`SlackChannel` for two payload shapes:

  * ``/automation run <name> [args...]`` — Slack POSTs a slash command
    body shaped like::

        {"command": "/automation", "text": "run standup", "user_id": "U..",
         "team_id": "T..", "channel_id": "C..", ...}

    The handler parses ``text`` as ``run <name>``, looks up the matching
    ``AutomationDefinition``, INSERTs an ``automation_events`` row, and
    enqueues ``dispatch_automation_task``.

  * ``@app summarize_commits {repo} {day}`` — a bot mention in a channel.
    The Slack adapter parses the ``app_mention`` event into
    ``{"text": "<@UBOT> summarize_commits foo bar", "user_id": "U..",
    "channel_id": "C..", ...}`` and the handler resolves the mention
    against the projected ``app_actions`` table.

The handler always returns ``{"event_id": ..., "ack": "ok"}`` (or an
error envelope) within the 3-second Slack response budget — agent
execution is async via ARQ.
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


__all__ = ["dispatch_from_slack", "handle_slash_command"]


async def _resolve_owner(
    db: AsyncSession, channel_config_id: uuid.UUID
) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """Return ``(owner_user_id, team_id)`` for the inbound channel config."""
    config = await db.scalar(
        select(ChannelConfig).where(ChannelConfig.id == channel_config_id)
    )
    if config is None:
        return None, None
    return config.user_id, getattr(config, "team_id", None)


async def dispatch_from_slack(
    *,
    payload: dict[str, Any],
    channel_config_id: uuid.UUID,
    db: AsyncSession,
    arq_pool: Any,
) -> dict[str, Any]:
    """Route a Slack slash command or mention into the automation dispatcher.

    The payload shape is the verbatim Slack request body — slash commands
    are URL-encoded form bodies, mentions are JSON. The Slack adapter
    normalizes both into a flat dict before calling this function.
    """
    # Slack distinguishes slash commands (have ``command`` key) from
    # ``app_mention`` events (have ``text`` starting with the bot mention).
    is_slash = bool(payload.get("command"))
    raw_text: str = (payload.get("text") or "").strip()

    if is_slash:
        parsed = parse_slash_command(raw_text)
    else:
        parsed = parse_bot_mention(raw_text)

    if parsed.kind == "unknown":
        return {"ack": "ok", "error": "could_not_parse", "raw": raw_text[:200]}

    platform_user_id = str(payload.get("user_id") or "")
    identity = await resolve_platform_identity(
        db, platform="slack", platform_user_id=platform_user_id
    )

    owner_user_id, team_id = await _resolve_owner(db, channel_config_id)
    invoking_user_id = identity.user_id if identity else owner_user_id

    extra_payload: dict[str, Any] = {
        "channel_config_id": str(channel_config_id),
        "slack_channel_id": payload.get("channel_id"),
        "slack_team_id": payload.get("team_id"),
        "slack_user_id": platform_user_id,
        "slack_response_url": payload.get("response_url"),
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
            platform="slack",
            invoking_user_id=invoking_user_id,
            raw_text=raw_text,
            args=parsed.args,
            extra_payload=extra_payload,
        )
    except GatewayCommandError as exc:
        return {"ack": "ok", "error": "enqueue_failed", "detail": str(exc)}

    return {"event_id": str(event_id), "ack": "ok"}


# Backwards-compatible alias so the Slack adapter can call
# ``slack_slash.handle_slash_command(body)`` exactly as the build directive
# describes. The wrapper exists because the directive uses positional-only
# `body`; we keep it as a thin shim around the kwargs-only async helper.
async def handle_slash_command(
    body: dict[str, Any],
    *,
    channel_config_id: uuid.UUID,
    db: AsyncSession,
    arq_pool: Any,
) -> dict[str, Any]:
    """Thin shim — see :func:`dispatch_from_slack` for the contract."""
    return await dispatch_from_slack(
        payload=body,
        channel_config_id=channel_config_id,
        db=db,
        arq_pool=arq_pool,
    )
