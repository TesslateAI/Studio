"""Shared helpers for slash-command / mention triggers (Phase 4).

The parsers and resolvers here are deliberately platform-agnostic so the
slash command parser is unit-testable without booting Slack / Telegram /
Discord adapter fakes (per the build directive: "write tests for the
helpers (blocks/keyboards builders, delivery_fallback chain, slash
command parser)").
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....models import PlatformIdentity
from ....models_automations import (
    AppAction,
    AutomationAction,
    AutomationDefinition,
)
from ...automations.trigger_events import (
    ingest_trigger_event,
    mark_dispatched,
    mark_failed,
)

logger = logging.getLogger(__name__)


__all__ = [
    "GatewayCommandError",
    "NoMatchingAutomation",
    "NoMatchingAppAction",
    "ParsedCommand",
    "parse_slash_command",
    "parse_bot_mention",
    "resolve_platform_identity",
    "resolve_automation_by_name",
    "resolve_app_action_by_name",
    "ingest_and_enqueue_command",
]


# ---------------------------------------------------------------------------
# Errors — translated to platform-shaped responses by the adapter layer.
# ---------------------------------------------------------------------------


class GatewayCommandError(Exception):
    """Base error for gateway-command dispatch failures."""


class NoMatchingAutomation(GatewayCommandError):
    """No active ``AutomationDefinition`` matches the supplied name."""


class NoMatchingAppAction(GatewayCommandError):
    """No ``AppAction`` matches the supplied name (for the supplied user)."""


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParsedCommand:
    """Result of parsing a slash-command or mention.

    ``kind``      — ``"automation"`` (run a named automation),
                    ``"app_action"`` (invoke a named app action), or
                    ``"unknown"`` (parser couldn't classify the input).
    ``name``      — the target automation / action name (e.g. ``"standup"``
                    or ``"summarize_commits"``).
    ``app_alias`` — populated for ``"app_action"`` only; the leading
                    ``@app`` token without the leading ``@`` (e.g. ``"app"``,
                    ``"github"``).
    ``args``      — positional args after the command (e.g.
                    ``["tesslate/studio", "yesterday"]``).
    ``raw_text``  — the original payload text, kept for the audit row.
    """

    kind: str
    name: str
    args: list[str]
    raw_text: str
    app_alias: str | None = None


# Allowed in automation / action names: alphanum, hyphen, underscore. Keep
# the regex strict so a malicious slash command can't tunnel arbitrary text
# into a SQL LIKE.
_NAME_RE = re.compile(r"^[A-Za-z0-9_\-\.]{1,128}$")


def _looks_like_name(token: str) -> bool:
    return bool(token) and bool(_NAME_RE.match(token))


def parse_slash_command(text: str) -> ParsedCommand:
    """Parse ``/automation run <name> [args...]`` or ``/automation_run ...``.

    Examples accepted:
      * ``/automation run standup``                         (Slack/Discord)
      * ``/automation_run standup arg1 arg2``               (Telegram)
      * ``/automation run standup arg1 arg2``               (whitespace)
      * ``run standup``                                     (Slack appends
        the subcommand and args as the slash-command "text" parameter, so
        the ``/automation`` prefix is already stripped server-side)

    Anything else returns ``ParsedCommand(kind='unknown', ...)`` so the
    caller can surface a friendly help message instead of silently failing.
    """
    raw = (text or "").strip()
    if not raw:
        return ParsedCommand(kind="unknown", name="", args=[], raw_text=raw)

    tokens = raw.split()
    if not tokens:
        return ParsedCommand(kind="unknown", name="", args=[], raw_text=raw)

    # Strip a leading ``/automation`` or ``/automation_run`` if present.
    head = tokens[0].lower()
    if head in ("/automation", "automation"):
        tokens = tokens[1:]
        if tokens and tokens[0].lower() == "run":
            tokens = tokens[1:]
    elif head in ("/automation_run", "automation_run"):
        tokens = tokens[1:]
    elif head == "run":
        tokens = tokens[1:]

    if not tokens:
        return ParsedCommand(kind="unknown", name="", args=[], raw_text=raw)

    name = tokens[0]
    if not _looks_like_name(name):
        return ParsedCommand(kind="unknown", name="", args=[], raw_text=raw)

    return ParsedCommand(
        kind="automation",
        name=name,
        args=tokens[1:],
        raw_text=raw,
    )


def parse_bot_mention(text: str) -> ParsedCommand:
    """Parse ``@app summarize_commits {repo} {day}`` style mentions.

    Slack mentions arrive as ``<@U12345> summarize_commits foo bar`` where
    the ``<@U12345>`` is the bot's user id. Telegram mentions arrive as
    ``@bot summarize_commits foo bar``. Both reduce to "drop the leading
    mention, the next token is the action name, the rest are args."

    The ``app_alias`` field captures the original mention token without
    the angle brackets / leading ``@`` so the dispatcher can route to the
    correct app instance when multiple are linked into the same workspace.
    """
    raw = (text or "").strip()
    if not raw:
        return ParsedCommand(
            kind="unknown", name="", args=[], raw_text=raw, app_alias=None
        )

    tokens = raw.split()
    if not tokens:
        return ParsedCommand(
            kind="unknown", name="", args=[], raw_text=raw, app_alias=None
        )

    head = tokens[0]
    alias: str | None = None
    if head.startswith("<@") and head.endswith(">"):
        alias = head[2:-1]
        tokens = tokens[1:]
    elif head.startswith("@"):
        alias = head[1:]
        tokens = tokens[1:]
    else:
        return ParsedCommand(
            kind="unknown", name="", args=[], raw_text=raw, app_alias=None
        )

    if not tokens:
        return ParsedCommand(
            kind="unknown", name="", args=[], raw_text=raw, app_alias=alias
        )

    name = tokens[0]
    if not _looks_like_name(name):
        return ParsedCommand(
            kind="unknown", name="", args=[], raw_text=raw, app_alias=alias
        )

    return ParsedCommand(
        kind="app_action",
        name=name,
        args=tokens[1:],
        raw_text=raw,
        app_alias=alias,
    )


# ---------------------------------------------------------------------------
# Resolvers
# ---------------------------------------------------------------------------


async def resolve_platform_identity(
    db: AsyncSession,
    *,
    platform: str,
    platform_user_id: str,
) -> PlatformIdentity | None:
    """Look up the *verified* PlatformIdentity for the inbound user.

    Returns ``None`` if the user has not paired their platform account —
    callers fall back to the channel-config owner in that case.
    """
    if not platform or not platform_user_id:
        return None
    return await db.scalar(
        select(PlatformIdentity).where(
            PlatformIdentity.platform == platform,
            PlatformIdentity.platform_user_id == str(platform_user_id),
            PlatformIdentity.is_verified.is_(True),
        )
    )


async def resolve_automation_by_name(
    db: AsyncSession,
    *,
    name: str,
    owner_user_id: UUID | None = None,
    team_id: UUID | None = None,
) -> AutomationDefinition:
    """Find an *active* automation by name, scoped to the supplied user/team.

    Match priority: user-owned → team-owned. Both filters are AND-applied
    individually; the OR shape lives at the SQL level so a user can run
    automations they own AND ones their team owns.
    """
    if not name:
        raise NoMatchingAutomation("automation name is empty")

    base = select(AutomationDefinition).where(
        AutomationDefinition.name == name,
        AutomationDefinition.is_active.is_(True),
    )

    rows = (await db.execute(base)).scalars().all()
    if not rows:
        raise NoMatchingAutomation(f"no active automation named {name!r}")

    # Prefer user-owned match, then team-scoped match, then any active row.
    if owner_user_id is not None:
        for r in rows:
            if r.owner_user_id == owner_user_id:
                return r
    if team_id is not None:
        for r in rows:
            if r.team_id == team_id:
                return r
    return rows[0]


async def resolve_app_action_by_name(
    db: AsyncSession,
    *,
    name: str,
    app_alias: str | None,
    owner_user_id: UUID | None,
    team_id: UUID | None,
) -> tuple[AppAction, AutomationDefinition]:
    """Resolve an ``@app action`` mention to (AppAction, AutomationDefinition).

    The mapping uses the existing ``automation_actions.app_action_id``
    column: an automation whose first action is ``app.invoke`` of an
    AppAction with the supplied name. Reusing the existing FK keeps the
    dispatch path identical to the cron / webhook flows — the gateway
    trigger is just another way to fire an existing automation.

    Raises :class:`NoMatchingAppAction` if no automation wraps the action
    OR the user can't see it.
    """
    if not name:
        raise NoMatchingAppAction("app action name is empty")

    rows = (
        await db.execute(
            select(AppAction, AutomationAction, AutomationDefinition)
            .join(
                AutomationAction,
                AutomationAction.app_action_id == AppAction.id,
            )
            .join(
                AutomationDefinition,
                AutomationDefinition.id == AutomationAction.automation_id,
            )
            .where(
                AppAction.name == name,
                AutomationAction.action_type == "app.invoke",
                AutomationDefinition.is_active.is_(True),
            )
        )
    ).all()
    if not rows:
        raise NoMatchingAppAction(
            f"no active automation invokes app action {name!r}"
        )

    # Prefer the alias-matched automation if the caller passed one.
    if app_alias is not None:
        for action, _aa, autom in rows:
            if (autom.name or "").lower().startswith(app_alias.lower()):
                return action, autom
    # Then prefer user-owned, then team-scoped, then any.
    if owner_user_id is not None:
        for action, _aa, autom in rows:
            if autom.owner_user_id == owner_user_id:
                return action, autom
    if team_id is not None:
        for action, _aa, autom in rows:
            if autom.team_id == team_id:
                return action, autom
    action, _aa, autom = rows[0]
    return action, autom


# ---------------------------------------------------------------------------
# Common ingest + enqueue
# ---------------------------------------------------------------------------


async def ingest_and_enqueue_command(
    db: AsyncSession,
    arq_pool: Any,
    *,
    automation: AutomationDefinition,
    platform: str,
    invoking_user_id: UUID | None,
    raw_text: str,
    args: list[str],
    extra_payload: dict[str, Any] | None = None,
) -> uuid.UUID:
    """INSERT an ``automation_events`` row and enqueue ``dispatch_automation_task``.

    Returns the new event id. Caller owns no transaction here — this
    helper commits twice (insert, then dispatched-stamp) on purpose so
    the row is durable before the ARQ enqueue, mirroring the contract in
    ``routers/app_triggers.py`` (recovery sweep keys off the durable
    insert).
    """
    payload: dict[str, Any] = {
        "kind": "gateway_command",
        "platform": platform,
        "user_id": str(invoking_user_id) if invoking_user_id else None,
        "raw_text": (raw_text or "")[:8192],
        "args": list(args or []),
    }
    if extra_payload:
        payload.update(extra_payload)

    event_id = await ingest_trigger_event(
        db,
        automation_id=automation.id,
        trigger_id=None,
        trigger_kind="gateway_command",
        payload=payload,
    )
    await db.commit()

    worker_id = f"gateway:{platform}"
    try:
        if arq_pool is not None and hasattr(arq_pool, "enqueue_job"):
            await arq_pool.enqueue_job(
                "dispatch_automation_task",
                str(automation.id),
                str(event_id),
                worker_id,
                _job_id=str(event_id),
            )
        else:
            # Fall back to the unified TaskQueue abstraction so this
            # works in desktop / no-ARQ-pool deployments too.
            from ...task_queue import get_task_queue

            queue = get_task_queue()
            await queue.enqueue(
                "dispatch_automation_task",
                str(automation.id),
                str(event_id),
                worker_id,
            )
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception(
            "[GATEWAY-TRIGGER] failed to enqueue automation=%s event=%s",
            automation.id,
            event_id,
        )
        await mark_failed(db, event_id, repr(exc))
        await db.commit()
        raise GatewayCommandError(f"failed to enqueue: {exc}") from exc

    await mark_dispatched(db, event_id)
    await db.commit()

    logger.info(
        "[GATEWAY-TRIGGER] dispatched automation=%s event=%s platform=%s "
        "invoking_user_id=%s",
        automation.id,
        event_id,
        platform,
        invoking_user_id,
    )
    return event_id
