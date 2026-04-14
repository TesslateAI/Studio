"""
Desktop pairing / auth handoff.

Two endpoints with different auth models:

- `POST /api/desktop/pair/complete` (session-authenticated) — user has logged in
  to the cloud via the browser; this mint endpoint issues a `tsk_` API key
  scoped for desktop use and records a `DeviceRegistration` row. The raw token
  is returned **once** for the `tesslate://auth/callback?token=...` deep link.

- `POST /api/v1/desktop/pair/revoke` (tsk-authenticated) — desktop logs out and
  asks the cloud to revoke its own key + device registration.

The session-auth mint lives outside `routers/public/` because that package is
tsk-only. The revoke lives in this file (not in `public/`) to co-locate the
pairing lifecycle.
"""

from __future__ import annotations

import hashlib
import logging
import secrets as _secrets
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth_external import require_api_scope
from ..database import get_db
from ..models import DeviceRegistration, ExternalAPIKey, User
from ..permissions import (
    ROLE_PERMISSIONS,
    Permission,
    get_team_membership,
)
from ..users import current_active_user

logger = logging.getLogger(__name__)

REQUIRED_SCOPE = Permission.DESKTOP_PAIR

# Default scopes minted for a desktop pairing when the client doesn't ask for
# a specific subset. Keep this lean; the client can request a narrower set.
_DEFAULT_DESKTOP_SCOPES: list[str] = [
    Permission.DESKTOP_PAIR.value,
    Permission.MARKETPLACE_READ.value,
    Permission.MODELS_PROXY.value,
    Permission.USAGE_READ.value,
    Permission.AGENTS_READ.value,
]

_MAX_DEVICES_PER_USER = 10


session_router = APIRouter(prefix="/api/desktop", tags=["desktop-pair"])
public_router = APIRouter(prefix="/api/v1/desktop", tags=["desktop-pair"])


# ---------------------------------------------------------------------------
# Schemas (inline per public-router convention)
# ---------------------------------------------------------------------------


class PairCompleteRequest(BaseModel):
    device_name: str = Field(..., min_length=1, max_length=200)
    device_platform: str | None = Field(default=None, max_length=40)
    device_fingerprint: str | None = Field(default=None, max_length=128)
    app_version: str | None = Field(default=None, max_length=40)
    scopes: list[str] | None = None


class PairCompleteResponse(BaseModel):
    device_id: UUID
    api_key_id: UUID
    token: str
    scopes: list[str]
    expires_at: datetime | None


class PairRevokeResponse(BaseModel):
    revoked: bool
    device_id: UUID | None
    api_key_id: UUID


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _resolve_owner_scopes(
    db: AsyncSession, user: User, requested: list[str] | None
) -> list[str]:
    """Clamp requested scopes to the owner's role ceiling. Defaults to
    `_DEFAULT_DESKTOP_SCOPES` when `requested` is falsy."""
    owner_role = "admin"
    if user.default_team_id:
        membership = await get_team_membership(db, user.default_team_id, user.id)
        if membership:
            owner_role = membership.role
    owner_perms = ROLE_PERMISSIONS.get(owner_role, frozenset())
    owner_perm_values = {p.value for p in owner_perms}

    candidate = requested if requested else list(_DEFAULT_DESKTOP_SCOPES)
    for s in candidate:
        try:
            Permission(s)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Unknown scope: {s}") from exc
        if s not in owner_perm_values:
            raise HTTPException(
                status_code=403,
                detail=f"Scope '{s}' exceeds your role (role: {owner_role})",
            )
    # Always include desktop.pair so the key can later call /revoke
    if Permission.DESKTOP_PAIR.value not in candidate:
        candidate.append(Permission.DESKTOP_PAIR.value)
    return candidate


# ---------------------------------------------------------------------------
# POST /api/desktop/pair/complete   — session auth
# ---------------------------------------------------------------------------


@session_router.post("/pair/complete", response_model=PairCompleteResponse)
async def pair_complete(
    body: PairCompleteRequest,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> PairCompleteResponse:
    """Mint a desktop-scoped `tsk_` key + device registration for the caller."""
    # Cap active desktop registrations per user
    count_q = await db.execute(
        select(DeviceRegistration).where(
            DeviceRegistration.user_id == user.id,
            DeviceRegistration.revoked_at.is_(None),
        )
    )
    active = count_q.scalars().all()
    if len(active) >= _MAX_DEVICES_PER_USER:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum of {_MAX_DEVICES_PER_USER} paired devices allowed.",
        )

    scopes = await _resolve_owner_scopes(db, user, body.scopes)

    raw_key = f"tsk_{_secrets.token_hex(16)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:8]

    api_key = ExternalAPIKey(
        user_id=user.id,
        key_hash=key_hash,
        key_prefix=key_prefix,
        name=f"Desktop: {body.device_name}",
        scopes=scopes,
        project_ids=None,
        expires_at=None,
    )
    db.add(api_key)
    await db.flush()

    device = DeviceRegistration(
        user_id=user.id,
        api_key_id=api_key.id,
        device_name=body.device_name,
        device_platform=body.device_platform,
        device_fingerprint=body.device_fingerprint,
        app_version=body.app_version,
        last_seen_at=datetime.now(UTC),
    )
    db.add(device)
    await db.commit()
    await db.refresh(api_key)
    await db.refresh(device)

    logger.info("[DESKTOP-PAIR] Minted key %s for user %s device=%s", key_prefix, user.id, body.device_name)

    return PairCompleteResponse(
        device_id=device.id,
        api_key_id=api_key.id,
        token=raw_key,
        scopes=scopes,
        expires_at=api_key.expires_at,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/desktop/pair/revoke  — tsk auth
# ---------------------------------------------------------------------------


@public_router.post("/pair/revoke", response_model=PairRevokeResponse)
async def pair_revoke(
    user: User = Depends(require_api_scope(Permission.DESKTOP_PAIR)),
    db: AsyncSession = Depends(get_db),
) -> PairRevokeResponse:
    """Revoke the calling `tsk_` key plus its `DeviceRegistration` (if any)."""
    key: ExternalAPIKey = user._api_key_record  # type: ignore[attr-defined]
    now = datetime.now(UTC)

    device_id: UUID | None = None
    dev_q = await db.execute(
        select(DeviceRegistration).where(DeviceRegistration.api_key_id == key.id)
    )
    device = dev_q.scalar_one_or_none()
    if device is not None:
        device.revoked_at = now
        device_id = device.id

    # Refetch key from this session to flip is_active (auth loaded via a different
    # dependency session in some paths)
    key_q = await db.execute(select(ExternalAPIKey).where(ExternalAPIKey.id == key.id))
    key_row = key_q.scalar_one_or_none()
    if key_row is None:
        raise HTTPException(status_code=404, detail="API key not found")
    key_row.is_active = False
    await db.commit()

    logger.info("[DESKTOP-PAIR] Revoked key %s user=%s device=%s", key.key_prefix, user.id, device_id)

    return PairRevokeResponse(revoked=True, device_id=device_id, api_key_id=key.id)
