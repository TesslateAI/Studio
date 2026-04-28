"""CommunicationDestination CRUD service (Phase 4).

A :class:`CommunicationDestination` is a stored, NAMED delivery target
*inside* a :class:`ChannelConfig`. Today ``ChannelConfig`` is "one
bot/app credential set" (one row per Slack workspace, one row per
Telegram bot). What's missing is a stored, user-facing pointer — so a
user can configure once "send standup digests to #standup" and reference
it by ``destination_id`` from many automations.

This module owns the raw CRUD: create / read / update / delete plus a
``list_for_user`` helper that returns user-owned + team-scoped rows in
one query. The :func:`destination_in_use` predicate exists so the router
can warn before deleting a destination that's still wired into active
automations.

Authorization and HTTP shaping live in
``app.routers.communication_destinations``; this layer is deliberately
DB-only so the dispatcher / gateway can call into it as a library
without dragging FastAPI dependencies along.

See the plan section "CommunicationDestination — gateway delivery target
distinct from ChannelConfig" for the full design.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import ChannelConfig
from ...models_automations import (
    AutomationDefinition,
    AutomationDeliveryTarget,
    CommunicationDestination,
)

logger = logging.getLogger(__name__)


# Allowed destination kinds — kept in sync with the CHECK constraint in
# alembic 0079 + the Pydantic enum mirrored on the frontend.
ALLOWED_KINDS: frozenset[str] = frozenset(
    {
        "slack_channel",
        "slack_dm",
        "slack_thread",
        "telegram_chat",
        "telegram_topic",
        "discord_channel",
        "discord_dm",
        "email",
        "webhook",
        "web_inbox",
    }
)

ALLOWED_FORMATTING_POLICIES: frozenset[str] = frozenset(
    {
        "text",
        "blocks",
        "rich",
        "code_block",
        "inline_table",
        "jinja_template",
    }
)


# ---------------------------------------------------------------------------
# Domain errors — translated to HTTP codes by the router layer.
# ---------------------------------------------------------------------------


class CommunicationDestinationError(Exception):
    """Base error for destination CRUD failures."""


class InvalidDestinationKind(CommunicationDestinationError):
    """The supplied ``kind`` is not in :data:`ALLOWED_KINDS`."""


class InvalidFormattingPolicy(CommunicationDestinationError):
    """The supplied ``formatting_policy`` is not allowed."""


class ChannelConfigNotFound(CommunicationDestinationError):
    """The supplied ``channel_config_id`` does not exist or is not visible."""


class DestinationNotFound(CommunicationDestinationError):
    """No destination with the supplied id exists."""


class DestinationInUse(CommunicationDestinationError):
    """The destination is referenced by one or more active automations.

    Carries the count of referencing definitions so the caller can
    surface a meaningful warning (e.g., "still used by 3 automations").
    """

    def __init__(self, count: int) -> None:
        super().__init__(f"destination is referenced by {count} active automation(s)")
        self.count = count


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------


async def get_destination(
    db: AsyncSession, destination_id: uuid.UUID
) -> CommunicationDestination | None:
    """Return the row by id, or ``None`` if missing.

    The router layer applies authorization on top — this helper does not
    consult ownership / team membership.
    """
    return (
        await db.execute(
            select(CommunicationDestination).where(
                CommunicationDestination.id == destination_id
            )
        )
    ).scalar_one_or_none()


async def list_for_user(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    team_ids: Sequence[uuid.UUID] = (),
    channel_config_id: uuid.UUID | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[CommunicationDestination]:
    """Return user-owned + team-scoped destinations the user can read.

    ``team_ids`` should be the active team-membership ids for the caller.
    Omit / pass ``()`` if the caller has none — the query then degrades
    to "owner only".
    """
    where_clauses = [CommunicationDestination.owner_user_id == user_id]
    if team_ids:
        where_clauses.append(CommunicationDestination.team_id.in_(list(team_ids)))

    query = select(CommunicationDestination).where(or_(*where_clauses))
    if channel_config_id is not None:
        query = query.where(
            CommunicationDestination.channel_config_id == channel_config_id
        )
    query = (
        query.order_by(CommunicationDestination.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list((await db.execute(query)).scalars().all())


async def destination_in_use(
    db: AsyncSession, destination_id: uuid.UUID
) -> int:
    """Return the count of *active* automations referencing this destination.

    Inactive (paused) automations don't block deletion — they're already
    not delivering. Only ``automation_definitions.is_active = true`` rows
    that hold a ``automation_delivery_targets`` row pointing at this
    destination count.
    """
    rows = (
        await db.execute(
            select(AutomationDeliveryTarget.automation_id)
            .join(
                AutomationDefinition,
                AutomationDefinition.id
                == AutomationDeliveryTarget.automation_id,
            )
            .where(
                AutomationDeliveryTarget.destination_id == destination_id,
                AutomationDefinition.is_active.is_(True),
            )
        )
    ).all()
    # Distinct automation count (a single definition could reference the
    # destination from multiple targets if the user duplicates a row).
    return len({r[0] for r in rows})


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------


async def _resolve_channel_config(
    db: AsyncSession,
    *,
    channel_config_id: uuid.UUID,
    user_id: uuid.UUID,
) -> ChannelConfig:
    """Load a ChannelConfig the user owns; raise if missing.

    A destination must be backed by a credential set the caller can
    actually use. We check ``user_id == ChannelConfig.user_id`` because
    today every ``ChannelConfig`` has an owner user. Team-shared
    credentials are out of scope until a future ``ChannelConfig.team_id``
    column lands.
    """
    row = (
        await db.execute(
            select(ChannelConfig).where(
                ChannelConfig.id == channel_config_id,
                ChannelConfig.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise ChannelConfigNotFound(
            f"channel_config {channel_config_id} not found or not owned by user"
        )
    return row


def _validate_kind(kind: str) -> None:
    if kind not in ALLOWED_KINDS:
        raise InvalidDestinationKind(
            f"kind must be one of {sorted(ALLOWED_KINDS)}; got {kind!r}"
        )


def _validate_formatting_policy(policy: str) -> None:
    if policy not in ALLOWED_FORMATTING_POLICIES:
        raise InvalidFormattingPolicy(
            f"formatting_policy must be one of "
            f"{sorted(ALLOWED_FORMATTING_POLICIES)}; got {policy!r}"
        )


async def create_destination(
    db: AsyncSession,
    *,
    owner_user_id: uuid.UUID,
    channel_config_id: uuid.UUID,
    kind: str,
    name: str,
    config: dict[str, Any] | None = None,
    formatting_policy: str = "text",
    team_id: uuid.UUID | None = None,
) -> CommunicationDestination:
    """Create a new destination row.

    Validates ``kind`` / ``formatting_policy`` against the same allow-lists
    the DB CHECK enforces (defence in depth — a clean Pydantic / domain
    error beats a 500 from Postgres).
    """
    _validate_kind(kind)
    _validate_formatting_policy(formatting_policy)

    # Verify the channel_config exists and the user owns it.
    await _resolve_channel_config(
        db, channel_config_id=channel_config_id, user_id=owner_user_id
    )

    if not name or not name.strip():
        raise CommunicationDestinationError("name is required")

    row = CommunicationDestination(
        id=uuid.uuid4(),
        owner_user_id=owner_user_id,
        team_id=team_id,
        channel_config_id=channel_config_id,
        kind=kind,
        name=name.strip(),
        config=dict(config or {}),
        formatting_policy=formatting_policy,
    )
    db.add(row)
    await db.flush()
    logger.info(
        "[CD] Created destination id=%s kind=%s channel_config_id=%s "
        "owner_user_id=%s",
        row.id,
        kind,
        channel_config_id,
        owner_user_id,
    )
    return row


async def update_destination(
    db: AsyncSession,
    *,
    destination: CommunicationDestination,
    name: str | None = None,
    config: dict[str, Any] | None = None,
    formatting_policy: str | None = None,
) -> CommunicationDestination:
    """Patch the mutable fields. Identity / ownership are immutable here."""
    if name is not None:
        if not name.strip():
            raise CommunicationDestinationError("name cannot be empty")
        destination.name = name.strip()

    if config is not None:
        destination.config = dict(config)

    if formatting_policy is not None:
        _validate_formatting_policy(formatting_policy)
        destination.formatting_policy = formatting_policy

    await db.flush()
    return destination


async def delete_destination(
    db: AsyncSession,
    *,
    destination: CommunicationDestination,
    force: bool = False,
) -> None:
    """Delete a destination. Refuses if active automations reference it.

    Pass ``force=True`` to override the in-use check. The router exposes
    this as the ``?force=true`` query parameter so the user gets a clear
    warning + an explicit override.
    """
    if not force:
        in_use = await destination_in_use(db, destination.id)
        if in_use > 0:
            raise DestinationInUse(in_use)

    await db.delete(destination)
    await db.flush()
    logger.info(
        "[CD] Deleted destination id=%s force=%s", destination.id, force
    )


async def touch_last_used(
    db: AsyncSession, *, destination: CommunicationDestination
) -> None:
    """Stamp ``last_used_at`` to ``now()``.

    Called by the gateway delivery path on a successful send so the UI
    can sort destinations by recency. Best-effort: failures are logged
    but never propagated.
    """
    try:
        destination.last_used_at = datetime.now(UTC)
        await db.flush()
    except Exception:  # pragma: no cover - defensive
        logger.warning(
            "[CD] Failed to stamp last_used_at on destination %s",
            destination.id,
            exc_info=True,
        )


__all__ = [
    "ALLOWED_FORMATTING_POLICIES",
    "ALLOWED_KINDS",
    "ChannelConfigNotFound",
    "CommunicationDestinationError",
    "DestinationInUse",
    "DestinationNotFound",
    "InvalidDestinationKind",
    "InvalidFormattingPolicy",
    "create_destination",
    "delete_destination",
    "destination_in_use",
    "get_destination",
    "list_for_user",
    "touch_last_used",
    "update_destination",
]
