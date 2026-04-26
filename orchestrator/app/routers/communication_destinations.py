"""CommunicationDestination CRUD endpoints (Phase 4).

A :class:`CommunicationDestination` is a stored, NAMED gateway delivery
target inside a :class:`ChannelConfig`. The user creates one per
channel/DM/email/etc. they want to deliver to and references it from
many automations by id.

Endpoints
---------
* ``POST   /api/destinations``           — create
* ``GET    /api/destinations``           — list (owner + team-scoped)
* ``GET    /api/destinations/{id}``      — fetch
* ``PATCH  /api/destinations/{id}``      — update name / formatting / config
* ``DELETE /api/destinations/{id}``      — delete (refuses if in active use
                                            unless ``?force=true``)

Auth model
----------
Mirrors ``app.routers.automations``: the row's ``owner_user_id`` always
wins; otherwise team membership (editor+) is checked when ``team_id`` is
set. We 404 rather than 403 on missing read access to avoid leaking
existence (same pattern as ``get_project_with_access``).

Heavy lifting (validation, FK resolution, in-use check) lives in
``app.services.automations.communication_destinations`` so the
dispatcher / gateway can call into the same primitives without dragging
HTTP machinery along.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import User
from ..models_automations import CommunicationDestination
from ..permissions import get_team_membership
from ..services.automations import communication_destinations as cd_service
from ..users import current_active_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/destinations", tags=["destinations"])


_TEAM_WRITE_ROLES = frozenset({"admin", "editor"})
_TEAM_READ_ROLES = frozenset({"admin", "editor", "viewer"})


# ---------------------------------------------------------------------------
# Pydantic schemas — kept inline since this router owns the only HTTP
# surface that touches ``communication_destinations``. If a second caller
# emerges they should be promoted to ``schemas_automations.py``.
# ---------------------------------------------------------------------------


class CommunicationDestinationCreate(BaseModel):
    """POST /api/destinations request body."""

    channel_config_id: UUID
    kind: str = Field(..., max_length=32)
    name: str = Field(..., min_length=1, max_length=128)
    config: dict[str, Any] = Field(default_factory=dict)
    formatting_policy: str = Field(default="text", max_length=32)
    team_id: UUID | None = None

    @field_validator("kind")
    @classmethod
    def _check_kind(cls, v: str) -> str:
        if v not in cd_service.ALLOWED_KINDS:
            raise ValueError(
                f"kind must be one of {sorted(cd_service.ALLOWED_KINDS)}"
            )
        return v

    @field_validator("formatting_policy")
    @classmethod
    def _check_policy(cls, v: str) -> str:
        if v not in cd_service.ALLOWED_FORMATTING_POLICIES:
            raise ValueError(
                f"formatting_policy must be one of "
                f"{sorted(cd_service.ALLOWED_FORMATTING_POLICIES)}"
            )
        return v


class CommunicationDestinationUpdate(BaseModel):
    """PATCH /api/destinations/{id} — every field optional."""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    config: dict[str, Any] | None = None
    formatting_policy: str | None = Field(default=None, max_length=32)

    @field_validator("formatting_policy")
    @classmethod
    def _check_policy(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v not in cd_service.ALLOWED_FORMATTING_POLICIES:
            raise ValueError(
                f"formatting_policy must be one of "
                f"{sorted(cd_service.ALLOWED_FORMATTING_POLICIES)}"
            )
        return v


class CommunicationDestinationOut(BaseModel):
    """GET / POST / PATCH response body."""

    id: UUID
    owner_user_id: UUID | None
    team_id: UUID | None
    channel_config_id: UUID
    kind: str
    name: str
    config: dict[str, Any]
    formatting_policy: str
    created_at: Any
    last_used_at: Any | None
    in_use_count: int = 0

    class Config:
        from_attributes = True


def _project(row: CommunicationDestination, *, in_use_count: int = 0) -> CommunicationDestinationOut:
    return CommunicationDestinationOut(
        id=row.id,
        owner_user_id=row.owner_user_id,
        team_id=row.team_id,
        channel_config_id=row.channel_config_id,
        kind=row.kind,
        name=row.name,
        config=row.config or {},
        formatting_policy=row.formatting_policy,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        in_use_count=in_use_count,
    )


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


async def _user_team_ids(db: AsyncSession, user: User) -> list[UUID]:
    """Return the team ids the user has any active membership in."""
    from ..models_team import TeamMembership

    rows = (
        await db.execute(
            select(TeamMembership.team_id).where(
                TeamMembership.user_id == user.id,
                TeamMembership.is_active.is_(True),
            )
        )
    ).scalars().all()
    return list(rows)


async def _authorize_destination(
    db: AsyncSession,
    destination: CommunicationDestination,
    user: User,
    *,
    write: bool,
) -> None:
    """Owner / team-role gate — mirrors ``automations._authorize_definition``."""
    if getattr(user, "is_superuser", False):
        return
    if destination.owner_user_id is not None and destination.owner_user_id == user.id:
        return

    if destination.team_id is not None:
        membership = await get_team_membership(db, destination.team_id, user.id)
        if membership is not None:
            if write:
                if membership.role in _TEAM_WRITE_ROLES:
                    return
                raise HTTPException(
                    status_code=403,
                    detail=f"Role '{membership.role}' may not edit this destination",
                )
            if membership.role in _TEAM_READ_ROLES:
                return

    raise HTTPException(status_code=404, detail="Destination not found")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=list[CommunicationDestinationOut])
async def list_destinations(
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
    channel_config_id: UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[CommunicationDestinationOut]:
    """List the caller's destinations + any team destinations they can read."""
    team_ids = await _user_team_ids(db, user)
    rows = await cd_service.list_for_user(
        db,
        user_id=user.id,
        team_ids=team_ids,
        channel_config_id=channel_config_id,
        limit=limit,
        offset=offset,
    )
    # in_use_count is best-effort; we issue one query per row but only on
    # the rows being returned (limit-bounded). A bulk JOIN would be a
    # micro-optimization not worth the schema coupling at this stage.
    out: list[CommunicationDestinationOut] = []
    for row in rows:
        in_use = await cd_service.destination_in_use(db, row.id)
        out.append(_project(row, in_use_count=in_use))
    return out


@router.post(
    "",
    response_model=CommunicationDestinationOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_destination(
    payload: CommunicationDestinationCreate,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> CommunicationDestinationOut:
    """Create a destination owned by the calling user."""
    if payload.team_id is not None:
        membership = await get_team_membership(db, payload.team_id, user.id)
        if membership is None or membership.role not in _TEAM_WRITE_ROLES:
            raise HTTPException(
                status_code=403,
                detail="Cannot create a team-scoped destination without editor+ role",
            )

    try:
        row = await cd_service.create_destination(
            db,
            owner_user_id=user.id,
            channel_config_id=payload.channel_config_id,
            kind=payload.kind,
            name=payload.name,
            config=payload.config,
            formatting_policy=payload.formatting_policy,
            team_id=payload.team_id,
        )
    except cd_service.ChannelConfigNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except cd_service.CommunicationDestinationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await db.commit()
    await db.refresh(row)
    return _project(row, in_use_count=0)


@router.get("/{destination_id}", response_model=CommunicationDestinationOut)
async def get_destination(
    destination_id: UUID,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> CommunicationDestinationOut:
    row = await cd_service.get_destination(db, destination_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Destination not found")
    await _authorize_destination(db, row, user, write=False)
    in_use = await cd_service.destination_in_use(db, row.id)
    return _project(row, in_use_count=in_use)


@router.patch("/{destination_id}", response_model=CommunicationDestinationOut)
async def update_destination(
    destination_id: UUID,
    payload: CommunicationDestinationUpdate,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> CommunicationDestinationOut:
    row = await cd_service.get_destination(db, destination_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Destination not found")
    await _authorize_destination(db, row, user, write=True)

    try:
        updated = await cd_service.update_destination(
            db,
            destination=row,
            name=payload.name,
            config=payload.config,
            formatting_policy=payload.formatting_policy,
        )
    except cd_service.CommunicationDestinationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await db.commit()
    await db.refresh(updated)
    in_use = await cd_service.destination_in_use(db, updated.id)
    return _project(updated, in_use_count=in_use)


@router.delete("/{destination_id}")
async def delete_destination(
    destination_id: UUID,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
    force: bool = Query(
        default=False,
        description="Override the in-use check and delete anyway.",
    ),
) -> dict[str, Any]:
    row = await cd_service.get_destination(db, destination_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Destination not found")
    await _authorize_destination(db, row, user, write=True)

    try:
        await cd_service.delete_destination(db, destination=row, force=force)
    except cd_service.DestinationInUse as exc:
        # 409 Conflict — caller must pass ``?force=true`` to override.
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Destination is referenced by active automations",
                "in_use_count": exc.count,
                "hint": "Pass ?force=true to delete anyway.",
            },
        ) from exc

    await db.commit()
    return {"status": "deleted", "id": str(destination_id)}
