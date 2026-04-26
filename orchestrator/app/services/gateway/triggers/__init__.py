"""Gateway-as-trigger surface (Phase 4).

Each platform adapter (Slack / Telegram / Discord) routes inbound *commands*
(slash commands, bot mentions, button clicks) through one of the modules in
this package. The shared shape:

    async def dispatch_from_<platform>(
        *,
        payload: dict,
        channel_config_id: uuid.UUID,
        db: AsyncSession,
        arq_pool,
    ) -> dict[str, Any]

Each module:
  1. Resolves the inbound platform user → ``PlatformIdentity`` →
     ``invoking_user_id`` (or ``None`` if unpaired — most slash commands
     fall back to the channel-config owner).
  2. Parses the slash-command / mention to extract a target name —
     either an ``AutomationDefinition.name`` or an ``AppAction.name``.
  3. INSERTs an ``automation_events`` row with
     ``payload={kind:'gateway_command', platform:..., user_id:...,
     raw_text:...}`` so the dispatcher has full context.
  4. Enqueues ``dispatch_automation_task`` against the shared ARQ pool.
  5. Returns ``{"event_id": ..., "ack": "ok"}`` (or an error envelope) so
     the platform adapter can answer Slack/Telegram/Discord synchronously
     within its 3s response budget.

The trigger modules **never** synchronously execute the agent — they are
strictly enqueue-only, mirroring the webhook trigger contract in
``orchestrator/app/routers/app_triggers.py``.
"""

from __future__ import annotations

from .common import (
    GatewayCommandError,
    NoMatchingAutomation,
    NoMatchingAppAction,
    parse_slash_command,
    parse_bot_mention,
)

__all__ = [
    "GatewayCommandError",
    "NoMatchingAutomation",
    "NoMatchingAppAction",
    "parse_slash_command",
    "parse_bot_mention",
]
