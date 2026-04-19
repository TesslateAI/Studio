"""Yank workflow service with two-admin rule for critical severity.

A critical yank requires two *distinct* admins to approve before the
request transitions to 'approved'. The DB CHECK constraint
`ck_yank_critical_two_admin` is a defense-in-depth net — this service
layer rejects bad state transitions *before* they reach the DB.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AppVersion, YankAppeal, YankRequest

__all__ = [
    "YankError",
    "NeedsSecondAdminError",
    "YankNotFoundError",
    "AlreadyDecidedError",
    "request_yank",
    "approve_yank",
    "reject_yank",
    "file_appeal",
]

logger = logging.getLogger(__name__)

Severity = Literal["low", "medium", "critical"]


class YankError(Exception):
    """Base class for yank service errors."""


class NeedsSecondAdminError(YankError):
    """Critical yank cannot be double-signed by the same admin."""


class YankNotFoundError(YankError):
    """No YankRequest with the given id."""


class AlreadyDecidedError(YankError):
    """Yank request is already in a terminal status."""


async def _load(db: AsyncSession, yank_request_id: UUID) -> YankRequest:
    row = (
        await db.execute(
            select(YankRequest).where(YankRequest.id == yank_request_id).with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise YankNotFoundError(str(yank_request_id))
    return row


async def request_yank(
    db: AsyncSession,
    *,
    requester_user_id: UUID,
    app_version_id: UUID,
    severity: Severity,
    reason: str,
) -> UUID:
    """Insert a pending YankRequest row."""
    yank_id = uuid.uuid4()
    db.add(
        YankRequest(
            id=yank_id,
            app_version_id=app_version_id,
            requester_user_id=requester_user_id,
            severity=severity,
            reason=reason,
            status="pending",
        )
    )
    await db.flush()
    logger.info(
        "yank.request id=%s av=%s severity=%s requester=%s",
        yank_id,
        app_version_id,
        severity,
        requester_user_id,
    )
    return yank_id


async def _finalize_approved(db: AsyncSession, yank: YankRequest, admin_user_id: UUID) -> None:
    """Common path: flip yank.status='approved' and cascade to AppVersion."""
    now = datetime.now(tz=UTC)
    yank.status = "approved"
    yank.decided_at = now

    av = (
        await db.execute(
            select(AppVersion).where(AppVersion.id == yank.app_version_id).with_for_update()
        )
    ).scalar_one_or_none()
    if av is not None:
        av.approval_state = "yanked"
        av.yanked_at = now
        av.yanked_reason = yank.reason
        av.yanked_by_user_id = yank.primary_admin_id
        if yank.severity == "critical":
            av.yanked_is_critical = True
            av.yanked_second_admin_id = yank.secondary_admin_id


async def approve_yank(
    db: AsyncSession,
    *,
    yank_request_id: UUID,
    admin_user_id: UUID,
) -> dict:
    """Approve a yank. Critical severity requires two distinct admins.

    Returns:
        {'status': 'approved'} on final approval.
        {'needs_second_admin': True} if this was the first admin on a
        critical yank (status stays 'pending').
    """
    yank = await _load(db, yank_request_id)

    if yank.status in ("approved", "rejected"):
        raise AlreadyDecidedError(f"yank already {yank.status}")

    if yank.severity != "critical":
        yank.primary_admin_id = admin_user_id
        await _finalize_approved(db, yank, admin_user_id)
        await db.flush()
        logger.info(
            "yank.approve id=%s severity=%s admin=%s",
            yank_request_id,
            yank.severity,
            admin_user_id,
        )
        return {"status": "approved"}

    # Critical severity: two-admin protocol.
    if yank.primary_admin_id is None:
        yank.primary_admin_id = admin_user_id
        await db.flush()
        logger.info(
            "yank.approve.primary id=%s admin=%s (awaiting second admin)",
            yank_request_id,
            admin_user_id,
        )
        return {"needs_second_admin": True}

    if yank.primary_admin_id == admin_user_id:
        raise NeedsSecondAdminError("critical yank requires a second distinct admin")

    yank.secondary_admin_id = admin_user_id
    await _finalize_approved(db, yank, admin_user_id)
    await db.flush()
    logger.info(
        "yank.approve.final id=%s primary=%s secondary=%s",
        yank_request_id,
        yank.primary_admin_id,
        admin_user_id,
    )
    return {"status": "approved"}


async def reject_yank(
    db: AsyncSession,
    *,
    yank_request_id: UUID,
    admin_user_id: UUID,
    note: str | None = None,
) -> None:
    """Reject a pending yank request. Idempotent on already-rejected rows."""
    yank = await _load(db, yank_request_id)
    if yank.status == "rejected":
        return
    if yank.status == "approved":
        raise AlreadyDecidedError("cannot reject an approved yank")
    yank.status = "rejected"
    yank.decided_at = datetime.now(tz=UTC)
    if yank.primary_admin_id is None:
        yank.primary_admin_id = admin_user_id
    await db.flush()
    logger.info("yank.reject id=%s admin=%s note=%s", yank_request_id, admin_user_id, note)


async def file_appeal(
    db: AsyncSession,
    *,
    yank_request_id: UUID,
    appellant_user_id: UUID,
    reason: str,
) -> UUID:
    """File a YankAppeal. Requires the yank to be in 'approved' status."""
    yank = await _load(db, yank_request_id)
    if yank.status != "approved":
        raise YankError("can only appeal an approved yank")
    appeal_id = uuid.uuid4()
    db.add(
        YankAppeal(
            id=appeal_id,
            yank_request_id=yank_request_id,
            appellant_user_id=appellant_user_id,
            reason=reason,
            status="pending",
        )
    )
    yank.status = "appealed"
    await db.flush()
    logger.info(
        "yank.appeal id=%s yank=%s appellant=%s",
        appeal_id,
        yank_request_id,
        appellant_user_id,
    )
    return appeal_id
