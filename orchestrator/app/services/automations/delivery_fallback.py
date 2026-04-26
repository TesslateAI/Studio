"""Approval-card delivery with fallback chain (Phase 4).

When the dispatcher needs human input it builds an
``automation_approval_requests`` row, then this module decides *where*
to deliver the card. The chain (per the plan §"HITL via gateway —
fallback chain when no PlatformIdentity exists"):

    1. paired Slack DM   (PlatformIdentity{platform='slack'})
    2. paired Telegram DM (PlatformIdentity{platform='telegram'})
    3. transactional email (existing platform SMTP)
    4. web-only badge    (in-app notification — best-effort)
    5. **hard-fail**     — write
       ``automation_runs.paused_reason='no_delivery_channel'`` and
       return ``{kind: 'failed'}``. Never silently time out.

Each step records the channel that succeeded into
``automation_approval_requests.delivered_to`` (a JSON list) so the
audit trail captures the actual delivery surface.

The module is intentionally side-effecty (it writes DB rows, hits the
gateway delivery stream, sends email) but it accepts a ``gateway_client``
dependency so unit tests can inject a fake. The gateway client must
expose ``async send_approval_card_to_dm(platform, platform_user_id,
input_id, automation_id, tool_name, summary, actions)`` returning
``True`` on success.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import PlatformIdentity
from ...models_auth import User
from ...models_automations import (
    AutomationApprovalRequest,
    AutomationDefinition,
    AutomationRun,
)

logger = logging.getLogger(__name__)


__all__ = [
    "DeliveryResult",
    "GatewayClientProtocol",
    "send_with_fallback",
]


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class DeliveryResult:
    """What the fallback chain ended up doing.

    ``kind``     — ``"slack_dm"`` · ``"telegram_dm"`` · ``"email"`` ·
                   ``"web_only"`` · ``"failed"``.
    ``surface``  — human-readable surface description (channel name,
                   email address, ...).
    ``attempts`` — every step we tried, in order, with success/failure
                   so the run-history UI can show the chain.
    """

    kind: str
    surface: str | None = None
    attempts: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Protocol — lets unit tests inject a stub without booting adapters.
# ---------------------------------------------------------------------------


class GatewayClientProtocol(Protocol):
    async def send_approval_card_to_dm(
        self,
        *,
        platform: str,
        platform_user_id: str,
        input_id: str,
        automation_id: str,
        tool_name: str,
        summary: str,
        actions: list[str],
    ) -> bool: ...


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load_approval_context(
    db: AsyncSession, approval_request_id: UUID
) -> tuple[
    AutomationApprovalRequest, AutomationRun, AutomationDefinition
] | None:
    """Load the approval request + parent run + definition in one shot.

    Returns ``None`` if the request was deleted between when the caller
    grabbed the id and when we tried to load it.
    """
    request = await db.scalar(
        select(AutomationApprovalRequest).where(
            AutomationApprovalRequest.id == approval_request_id
        )
    )
    if request is None:
        return None

    run = await db.scalar(
        select(AutomationRun).where(AutomationRun.id == request.run_id)
    )
    if run is None:
        return None

    definition = await db.scalar(
        select(AutomationDefinition).where(
            AutomationDefinition.id == run.automation_id
        )
    )
    if definition is None:
        return None

    return request, run, definition


async def _find_platform_identity(
    db: AsyncSession, *, user_id: UUID, platform: str
) -> PlatformIdentity | None:
    return await db.scalar(
        select(PlatformIdentity).where(
            PlatformIdentity.user_id == user_id,
            PlatformIdentity.platform == platform,
            PlatformIdentity.is_verified.is_(True),
        )
    )


async def _record_delivery(
    db: AsyncSession,
    *,
    request: AutomationApprovalRequest,
    kind: str,
    surface: str | None,
) -> None:
    """Append a delivery record to ``approval_request.delivered_to``."""
    entry = {
        "kind": kind,
        "surface": surface,
        "delivered_at": datetime.now(UTC).isoformat(),
    }
    existing = list(request.delivered_to or [])
    existing.append(entry)
    request.delivered_to = existing
    await db.flush()


def _approval_summary(
    request: AutomationApprovalRequest,
) -> tuple[str, str, list[str]]:
    """Extract (tool_name, summary, actions) from the approval request.

    The dispatcher writes these into ``context`` (free-form JSON) and
    ``options`` (canonical action list); we tolerate either shape so
    older rows still render correctly.
    """
    ctx = request.context or {}
    tool_name = (
        ctx.get("tool_name")
        or ctx.get("tool")
        or ctx.get("kind")
        or "unknown_tool"
    )
    summary = (
        ctx.get("summary")
        or ctx.get("message")
        or ctx.get("reason_detail")
        or ""
    )
    options = list(request.options or []) or [
        "allow_once",
        "allow_for_run",
        "allow_permanently",
        "deny",
    ]
    return str(tool_name), str(summary), [str(o) for o in options]


# ---------------------------------------------------------------------------
# Fallback chain
# ---------------------------------------------------------------------------


async def send_with_fallback(
    approval_request_id: UUID,
    db: AsyncSession,
    gateway_client: GatewayClientProtocol | None = None,
    *,
    email_service: Any = None,
) -> DeliveryResult:
    """Walk the fallback chain until something delivers (or hard-fail).

    ``gateway_client`` may be ``None`` in unit-test paths or in
    deployment modes without a gateway (Slack/Telegram steps then skip
    cleanly to email/web).
    """
    loaded = await _load_approval_context(db, approval_request_id)
    if loaded is None:
        return DeliveryResult(
            kind="failed",
            surface="approval_request_missing",
            attempts=[
                {"step": "load", "ok": False, "reason": "approval_request_missing"}
            ],
        )

    request, run, definition = loaded
    tool_name, summary, options = _approval_summary(request)
    owner_user_id = definition.owner_user_id
    automation_id_str = str(definition.id)
    input_id_str = str(request.id)

    attempts: list[dict[str, Any]] = []

    # ---- Step 1: Slack DM -------------------------------------------------
    slack_identity = await _find_platform_identity(
        db, user_id=owner_user_id, platform="slack"
    )
    if slack_identity is not None and gateway_client is not None:
        try:
            ok = await gateway_client.send_approval_card_to_dm(
                platform="slack",
                platform_user_id=slack_identity.platform_user_id,
                input_id=input_id_str,
                automation_id=automation_id_str,
                tool_name=tool_name,
                summary=summary,
                actions=options,
            )
        except Exception as exc:
            logger.warning(
                "[DELIVERY] slack DM raised: %s", exc, exc_info=True
            )
            ok = False
        attempts.append(
            {
                "step": "slack_dm",
                "ok": ok,
                "platform_user_id": slack_identity.platform_user_id,
            }
        )
        if ok:
            await _record_delivery(
                db,
                request=request,
                kind="slack_dm",
                surface=slack_identity.platform_user_id,
            )
            await db.commit()
            return DeliveryResult(
                kind="slack_dm",
                surface=slack_identity.platform_user_id,
                attempts=attempts,
            )
    else:
        attempts.append(
            {
                "step": "slack_dm",
                "ok": False,
                "reason": (
                    "no_platform_identity"
                    if slack_identity is None
                    else "no_gateway_client"
                ),
            }
        )

    # ---- Step 2: Telegram DM ----------------------------------------------
    telegram_identity = await _find_platform_identity(
        db, user_id=owner_user_id, platform="telegram"
    )
    if telegram_identity is not None and gateway_client is not None:
        try:
            ok = await gateway_client.send_approval_card_to_dm(
                platform="telegram",
                platform_user_id=telegram_identity.platform_user_id,
                input_id=input_id_str,
                automation_id=automation_id_str,
                tool_name=tool_name,
                summary=summary,
                actions=options,
            )
        except Exception as exc:
            logger.warning(
                "[DELIVERY] telegram DM raised: %s", exc, exc_info=True
            )
            ok = False
        attempts.append(
            {
                "step": "telegram_dm",
                "ok": ok,
                "platform_user_id": telegram_identity.platform_user_id,
            }
        )
        if ok:
            await _record_delivery(
                db,
                request=request,
                kind="telegram_dm",
                surface=telegram_identity.platform_user_id,
            )
            await db.commit()
            return DeliveryResult(
                kind="telegram_dm",
                surface=telegram_identity.platform_user_id,
                attempts=attempts,
            )
    else:
        attempts.append(
            {
                "step": "telegram_dm",
                "ok": False,
                "reason": (
                    "no_platform_identity"
                    if telegram_identity is None
                    else "no_gateway_client"
                ),
            }
        )

    # ---- Step 3: transactional email --------------------------------------
    owner = await db.scalar(select(User).where(User.id == owner_user_id))
    owner_email = getattr(owner, "email", None) if owner else None
    if owner_email:
        from ..channels.email.approval_email import send_approval_email

        try:
            ok = await send_approval_email(
                to_email=owner_email,
                input_id=input_id_str,
                automation_id=automation_id_str,
                tool_name=tool_name,
                summary=summary,
                actions=options,
                automation_name=definition.name,
                email_service=email_service,
            )
        except Exception as exc:
            logger.warning("[DELIVERY] email raised: %s", exc, exc_info=True)
            ok = False
        attempts.append({"step": "email", "ok": ok, "to": owner_email})
        if ok:
            await _record_delivery(
                db, request=request, kind="email", surface=owner_email
            )
            await db.commit()
            return DeliveryResult(
                kind="email", surface=owner_email, attempts=attempts
            )
    else:
        attempts.append({"step": "email", "ok": False, "reason": "no_email"})

    # ---- Step 4: web-only badge -------------------------------------------
    # The web approval drawer is always available — this step is the
    # "best-effort" insertion of a notification row so the user sees a
    # badge on next visit. We don't have a dedicated web_inbox table yet
    # (it lands later in Phase 5), so today this is logged + recorded as
    # a successful "web_only" delivery. The drawer surfaces every
    # ``automation_approval_requests`` row regardless, so the user can
    # still respond from the web UI even with no notification badge.
    logger.info(
        "[DELIVERY] web_only fallback for approval_request=%s automation=%s "
        "(no Slack/Telegram/email); user can resolve via web drawer.",
        input_id_str,
        automation_id_str,
    )
    attempts.append({"step": "web_only", "ok": True})
    await _record_delivery(
        db, request=request, kind="web_only", surface=None
    )
    await db.commit()

    # If we reached here at all, we recorded a web_only delivery — that's
    # not a hard fail. The plan reserves the hard-fail path for "no
    # delivery channel could be reached". Web is always reachable, so
    # the "failed" terminal is only triggered when the request itself
    # disappeared above (handled at the top of the function).
    return DeliveryResult(
        kind="web_only", surface=None, attempts=attempts
    )


async def mark_no_delivery_channel(
    db: AsyncSession, run_id: UUID
) -> None:
    """Helper for the controller: stamp ``paused_reason`` on a run that
    truly cannot be delivered (every step in the chain raised, including
    the web fallback). Today only ``send_with_fallback``'s internal
    "approval row deleted" path returns ``failed``; the controller may
    still call this to mark a run that ran out of options."""
    await db.execute(
        update(AutomationRun)
        .where(AutomationRun.id == run_id)
        .values(
            paused_reason="no_delivery_channel",
            status="failed",
            ended_at=datetime.now(UTC),
        )
    )
    await db.commit()
    logger.warning(
        "[DELIVERY] hard-fail run=%s with paused_reason='no_delivery_channel'",
        run_id,
    )
