"""Yank workflow service with two-admin rule for critical severity.

A critical yank requires two *distinct* admins to approve before the
request transitions to 'approved'. The DB CHECK constraint
`ck_yank_critical_two_admin` is a defense-in-depth net — this service
layer rejects bad state transitions *before* they reach the DB.

Wave 7 adds :func:`publish_yank_upstream` which propagates an
orchestrator-side yank decision to the source hub via
``MarketplaceClient.publish_yank``. The orchestrator MUST call this
after a yank approval finalizes for any AppVersion whose underlying
MarketplaceApp is sourced from a non-local marketplace source — without
the propagation, other orchestrators consuming the same hub's
``/v1/yanks`` feed never see the yank.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import (
    AppVersion,
    MarketplaceApp,
    MarketplaceSource,
    YankAppeal,
    YankRequest,
)

__all__ = [
    "YankError",
    "NeedsSecondAdminError",
    "YankNotFoundError",
    "AlreadyDecidedError",
    "request_yank",
    "approve_yank",
    "reject_yank",
    "file_appeal",
    "publish_yank_upstream",
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


async def publish_yank_upstream(
    db: AsyncSession,
    *,
    yank_request_id: UUID,
    client_factory: Any | None = None,
) -> dict[str, Any] | None:
    """Propagate an approved yank to the source hub's ``POST /v1/yanks``.

    Wave 7: when the orchestrator approves a :class:`YankRequest` for a
    federated app version (one whose parent ``MarketplaceApp.source_id``
    points at a non-local hub), it MUST publish the decision back to
    that hub so other orchestrators consuming the hub's ``/v1/yanks``
    feed pick up the yank on their next sync tick.

    Returns the hub's response envelope on success, ``None`` when:

      * the yank's status is not ``'approved'`` (we only propagate
        finalised decisions),
      * the underlying app has no source row,
      * the source row is the local sentinel (``trust_level='local'``
        or ``base_url`` starts with ``local://``) — local sources don't
        run a federated hub,
      * the propagation HTTP call fails (logged + swallowed; the local
        yank is already authoritative for this orchestrator's runtime
        gate via :func:`_finalize_approved`).

    The caller controls when this runs. The recommended placement is
    immediately after the router commits the approve transaction so the
    local catalog reflects the yank before the upstream POST fires.
    """
    yank = (
        await db.execute(
            select(YankRequest).where(YankRequest.id == yank_request_id)
        )
    ).scalar_one_or_none()
    if yank is None or yank.status != "approved":
        return None

    join_row = (
        await db.execute(
            select(AppVersion, MarketplaceApp, MarketplaceSource)
            .join(MarketplaceApp, MarketplaceApp.id == AppVersion.app_id)
            .outerjoin(
                MarketplaceSource, MarketplaceSource.id == MarketplaceApp.source_id
            )
            .where(AppVersion.id == yank.app_version_id)
        )
    ).first()
    if join_row is None:
        return None
    av, app_row, source_row = join_row

    # Skip non-federated apps: no source row, the local sentinel source,
    # or anything not advertising a real upstream hub.
    if source_row is None:
        return None
    if source_row.trust_level == "local":
        return None
    base_url = source_row.base_url or ""
    if base_url.startswith("local://"):
        return None

    # Decrypt the per-source bearer token. Failures here are non-fatal —
    # we still attempt the unauthenticated POST, which the hub will reject
    # with 401 if its policy requires auth. The point is we don't hide
    # crypto errors behind "yank propagation succeeded".
    decrypted_token: str | None = None
    if source_row.encrypted_token:
        try:
            from ..credential_manager import get_credential_manager

            decrypted_token = get_credential_manager().decrypt_token(
                source_row.encrypted_token
            )
        except Exception:
            logger.warning(
                "publish_yank_upstream: token decrypt failed for source=%s",
                source_row.handle,
                exc_info=True,
            )

    severity = str(yank.severity)
    reason_text = str(yank.reason or "upstream yank")

    if client_factory is None:
        from ..marketplace_client import MarketplaceClient

        def _default_factory() -> Any:
            return MarketplaceClient(
                base_url=source_row.base_url,
                token=decrypted_token,
                pinned_hub_id=source_row.pinned_hub_id,
            )

        client_factory = _default_factory

    client = client_factory()
    try:
        try:
            return await client.publish_yank(
                kind="app",
                slug=app_row.slug,
                version=av.version,
                reason=reason_text,
                severity=severity,
                requested_by=str(yank.primary_admin_id) if yank.primary_admin_id else None,
            )
        except Exception:
            logger.warning(
                "publish_yank_upstream: POST /v1/yanks failed for source=%s "
                "kind=app slug=%s version=%s; local yank already in effect",
                source_row.handle,
                app_row.slug,
                av.version,
                exc_info=True,
            )
            return None
    finally:
        aclose = getattr(client, "aclose", None)
        if callable(aclose):
            try:
                await aclose()
            except Exception:  # pragma: no cover
                logger.debug(
                    "publish_yank_upstream: client aclose failed", exc_info=True
                )


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
