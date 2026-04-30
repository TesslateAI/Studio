"""
Yank request lifecycle.

Posting a yank flips the targeted (kind, slug[, version]) immediately and emits
a `yank` op into the changes feed so federated orchestrators pick it up via
`/v1/yanks` poll. Critical-severity yanks require a second-admin confirmation
appeal before the resolution becomes terminal — the appeal endpoint records the
second hand and sets `state=resolved`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_session
from ..models import Item, ItemVersion, YankAppeal, YankRequest
from ..schemas import YankAppealCreate, YankAppealOut, YankCreate, YankOut
from ..services import changes_emitter
from ..services.auth import Principal, get_principal
from ..services.capability_router import requires_capability

router = APIRouter(prefix="/v1", tags=["yanks"])


def _serialize_yank(row: YankRequest) -> YankOut:
    return YankOut(
        id=str(row.id),
        kind=row.kind,
        slug=row.slug,
        version=row.version,
        severity=row.severity,
        reason=row.reason,
        requested_by=row.requested_by,
        state=row.state,
        resolved_at=row.resolved_at,
        resolution=row.resolution,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.post("/yanks", response_model=YankOut, status_code=201)
@requires_capability("yanks")
async def create_yank(
    payload: YankCreate,
    db: AsyncSession = Depends(get_session),
    principal: Principal = Depends(get_principal),
) -> YankOut:
    principal.require_scope("yanks.write")

    item = (
        await db.execute(select(Item).where(Item.kind == payload.kind, Item.slug == payload.slug))
    ).scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail={"error": "item_not_found"})

    target_version = None
    if payload.version:
        target_version = (
            await db.execute(
                select(ItemVersion).where(
                    ItemVersion.item_id == item.id, ItemVersion.version == payload.version
                )
            )
        ).scalar_one_or_none()
        if target_version is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "version_not_found", "version": payload.version},
            )

    requester_token_id: uuid.UUID | None = None
    if principal.token_id:
        try:
            requester_token_id = uuid.UUID(principal.token_id)
        except ValueError:
            requester_token_id = None
    yank = YankRequest(
        kind=payload.kind,
        slug=payload.slug,
        version=payload.version,
        severity=payload.severity,
        reason=payload.reason,
        requested_by=payload.requested_by or principal.handle,
        requested_by_token_id=requester_token_id,
        item_version_id=target_version.id if target_version else None,
    )
    db.add(yank)

    if target_version is not None:
        target_version.is_yanked = True
        target_version.yanked_at = datetime.now(timezone.utc)
        target_version.yank_reason = payload.reason
        target_version.yank_severity = payload.severity
    else:
        # Item-level yank — flag every published version.
        await db.execute(
            update(ItemVersion)
            .where(ItemVersion.item_id == item.id)
            .values(
                is_yanked=True,
                yanked_at=datetime.now(timezone.utc),
                yank_reason=payload.reason,
                yank_severity=payload.severity,
            )
        )
        item.is_active = False

    # Critical yanks open with state=open until a second admin appeal/seconds it.
    if payload.severity == "critical":
        yank.state = "open"
    else:
        yank.state = "resolved"
        yank.resolution = "applied"
        yank.resolved_at = datetime.now(timezone.utc)

    await db.flush()
    await changes_emitter.emit(
        db,
        op="yank",
        kind=payload.kind,
        slug=payload.slug,
        version=payload.version,
        payload={
            "reason": payload.reason,
            "severity": payload.severity,
            "yank_id": str(yank.id),
        },
    )
    # Item-level yank flips the parent inactive — surface that as a tombstone so
    # federated orchestrators hide the row from browse without losing references.
    if target_version is None:
        await changes_emitter.emit(
            db,
            op="deactivate",
            kind=payload.kind,
            slug=payload.slug,
            payload={
                "reason": payload.reason,
                "severity": payload.severity,
                "yank_id": str(yank.id),
            },
        )
    await db.commit()
    await db.refresh(yank)
    return _serialize_yank(yank)


@router.get("/yanks/{yank_id}", response_model=YankOut)
@requires_capability("yanks")
async def get_yank(
    yank_id: str,
    db: AsyncSession = Depends(get_session),
) -> YankOut:
    row = (await db.execute(select(YankRequest).where(YankRequest.id == yank_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail={"error": "yank_not_found"})
    return _serialize_yank(row)


@router.post("/yanks/{yank_id}/appeal", response_model=YankAppealOut, status_code=201)
@requires_capability("yanks.appeals")
async def appeal_yank(
    yank_id: str,
    payload: YankAppealCreate,
    db: AsyncSession = Depends(get_session),
    principal: Principal = Depends(get_principal),
) -> YankAppealOut:
    principal.require_scope("yanks.appeal")
    yank = (
        await db.execute(select(YankRequest).where(YankRequest.id == yank_id))
    ).scalar_one_or_none()
    if yank is None:
        raise HTTPException(status_code=404, detail={"error": "yank_not_found"})

    # Two-admin policy on critical yanks: the requester cannot resolve their
    # own appeal. Compare both the human handle and the bearer-token identity
    # so neither bare-handle reuse nor token-id reuse can self-confirm.
    if yank.severity == "critical" and yank.state == "open":
        appellant_token_id: uuid.UUID | None = None
        if principal.token_id:
            try:
                appellant_token_id = uuid.UUID(principal.token_id)
            except ValueError:
                appellant_token_id = None
        same_handle = bool(yank.requested_by) and yank.requested_by == principal.handle
        same_token = (
            yank.requested_by_token_id is not None
            and appellant_token_id is not None
            and yank.requested_by_token_id == appellant_token_id
        )
        if same_handle or same_token:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "cannot_self_appeal_critical_yank",
                    "message": "A second admin must confirm a critical yank.",
                },
            )

    appeal = YankAppeal(
        yank_id=yank.id,
        submitted_by=payload.submitted_by or principal.handle,
        reason=payload.reason,
    )
    db.add(appeal)

    # Critical yanks need exactly one appeal to "second" them; we mark resolved
    # but keep open=False so the audit log shows two distinct hands.
    if yank.severity == "critical" and yank.state == "open":
        yank.state = "resolved"
        yank.resolution = "second_admin_confirmed"
        yank.resolved_at = datetime.now(timezone.utc)

    await db.flush()
    await changes_emitter.emit(
        db,
        op="yank",
        kind=yank.kind,
        slug=yank.slug,
        version=yank.version,
        payload={
            "reason": yank.reason,
            "severity": yank.severity,
            "appeal_id": str(appeal.id),
            "yank_id": str(yank.id),
            "state": yank.state,
        },
    )
    await db.commit()
    await db.refresh(appeal)
    return YankAppealOut.model_validate(appeal, from_attributes=True)
