"""
Federated marketplace source CRUD (Wave 5).

Exposes ``/api/marketplace/sources`` so users (and admins) can register,
test, sync, and tear down additional federated marketplace hubs from the
Settings UI. System rows seeded by alembic 0088 (``tesslate-official`` and
``local``) are returned by the list endpoint but are immutable — every
write that targets them returns 403.

Endpoints:

  GET    /api/marketplace/sources                    — list user-visible
  POST   /api/marketplace/sources                    — create user/team source
  PATCH  /api/marketplace/sources/{id}               — edit display/token/active
  DELETE /api/marketplace/sources/{id}               — soft-delete (is_active=false)
  POST   /api/marketplace/sources/{id}/test          — pin hub_id + cache manifest
  POST   /api/marketplace/sources/{id}/sync          — manual one-shot sync
  POST   /api/marketplace/sources/{id}/promote       — superuser-only trust promote

Trust auto-classification at create / test time:

  - no token            → ``untrusted``  (mcp_server / app installs blocked)
  - bearer token given  → ``private``    (per-install confirmation prompt)
  - admin promotion     → ``admin_trusted`` (only via /promote)

Visibility is enforced server-side: every list / write / test / sync call
filters on (system row | row I own | row owned by my team). Cross-user /
cross-team access returns 404.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_db
from ..models import (
    AgentMcpAssignment,
    AgentSkillAssignment,
    MarketplaceAgent,
    MarketplaceApp,
    MarketplaceBase,
    MarketplaceSource,
    Theme,
    User,
    UserLibraryTheme,
    UserMcpConfig,
    UserPurchasedAgent,
    UserPurchasedBase,
    WorkflowTemplate,
)
from ..models_team import TeamMembership
from ..services.credential_manager import get_credential_manager
from ..services.marketplace_client import (
    LOCAL_URL_PREFIX,
    HubIdMismatchError,
    MarketplaceClient,
    MarketplaceClientError,
)
from ..services.marketplace_sync import MarketplaceSyncWorker
from ..users import current_active_user, current_superuser

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/marketplace/sources", tags=["marketplace-sources"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class MarketplaceSourceResponse(BaseModel):
    """Public projection of a :class:`MarketplaceSource` row.

    The encrypted token is never returned. ``has_token`` lets the UI know
    whether to render the "Token saved" badge without leaking the value.
    """

    id: UUID
    handle: str
    display_name: str
    base_url: str
    scope: str
    user_id: UUID | None = None
    team_id: UUID | None = None
    trust_level: str
    is_system: bool
    is_active: bool
    has_token: bool
    pinned_hub_id: str | None
    capabilities: list[str]
    policies: dict[str, Any]
    # Wave 9 — per-source hub-checkout opt-in. The UI surfaces this as
    # an admin-only toggle on the sources settings row.
    checkout_via_hub_enabled: bool = False
    last_synced_at: datetime | None
    last_sync_error: str | None
    sync_etag: str | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SourceCreatePayload(BaseModel):
    handle: str = Field(..., min_length=1, max_length=64)
    display_name: str = Field(..., min_length=1, max_length=128)
    base_url: str = Field(..., min_length=1, max_length=500)
    encrypted_token: str | None = None
    scope: str = Field(..., pattern="^(user|team)$")

    @field_validator("handle")
    @classmethod
    def _validate_handle(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("handle cannot be blank")
        # Must be URL-safe: lowercase, digits, hyphens, no spaces.
        for ch in v:
            if not (ch.isalnum() or ch in "-_"):
                raise ValueError(
                    "handle must contain only alphanumerics, hyphen, or underscore"
                )
        # Reserve the well-known system handles so users cannot shadow them
        # in their own scope (the partial unique index on system scope
        # already prevents the cross-scope collision, but a clear early
        # error is a better UX than the IntegrityError mid-create).
        if v in {"tesslate-official", "local"}:
            raise ValueError(f"{v!r} is a reserved system handle")
        return v

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, v: str) -> str:
        v = v.strip()
        # ``local://`` is a service-internal sentinel. Users cannot create
        # local sources via this API — those are seeded by alembic 0088
        # (desktop) or auto-created lazily by the future draft-save path
        # (cloud). Reject upfront so a curl-driven attacker can't smuggle
        # a local-trust row through the create endpoint.
        if v.startswith(LOCAL_URL_PREFIX):
            raise ValueError(
                "local:// sources are system-managed and cannot be created via this API"
            )
        # Production: must be HTTPS. dev/test/desktop allow HTTP for
        # localhost so contributors can run the marketplace service on
        # 127.0.0.1 without having to set up TLS.
        settings = get_settings()
        env = settings.deployment_env or "docker"
        is_production = env == "production"
        if v.startswith("https://"):
            return v
        if v.startswith("http://"):
            if is_production:
                # Production allows http only for explicit localhost loopback
                # (no point disallowing it because nothing else can resolve
                # in prod).
                lower = v.lower()
                if lower.startswith("http://localhost") or lower.startswith(
                    "http://127.0.0.1"
                ):
                    return v
                raise ValueError(
                    "base_url must use https:// in production "
                    "(http:// allowed only for localhost loopback)"
                )
            return v
        raise ValueError("base_url must start with http:// or https://")


class SourceUpdatePayload(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    encrypted_token: str | None = None
    is_active: bool | None = None
    # ``clear_token=True`` explicitly removes a stored bearer token. This
    # cannot be expressed via ``encrypted_token=None`` because that means
    # "leave unchanged".
    clear_token: bool = False


class SourcePromotePayload(BaseModel):
    trust_level: str = Field(..., pattern="^(admin_trusted|private|untrusted)$")


class SourceTestResponse(BaseModel):
    """Result of POST /api/marketplace/sources/{id}/test.

    Returns the pinned manifest summary plus the auto-classified trust
    level so the UI can update the row chip without a second list call.
    """

    hub_id: str
    api_version: str | None = None
    display_name: str | None = None
    capabilities: list[str]
    policies: dict[str, Any]
    auto_trust_level: str
    pinned_hub_id_changed: bool


class SourceSyncResponse(BaseModel):
    source_id: UUID
    source_handle: str
    events_processed: int
    items_upserted: int
    items_deleted: int
    items_deactivated: int
    versions_yanked: int
    versions_removed: int
    pricing_changes: int
    etag_advanced_to: str | None
    error: str | None
    skipped_reason: str | None
    last_sync_error: str | None
    last_synced_at: datetime | None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


SYSTEM_HANDLES: frozenset[str] = frozenset({"tesslate-official", "local"})


def _is_system_row(source: MarketplaceSource) -> bool:
    return source.scope == "system"


def _serialize(source: MarketplaceSource) -> MarketplaceSourceResponse:
    caps_raw = source.capabilities_cache
    if isinstance(caps_raw, list):
        capabilities = [str(c) for c in caps_raw]
    elif isinstance(caps_raw, dict):
        sub = caps_raw.get("capabilities")
        capabilities = [str(c) for c in sub] if isinstance(sub, list) else []
    else:
        capabilities = []
    policies_raw = source.policies_cache
    policies: dict[str, Any] = (
        dict(policies_raw) if isinstance(policies_raw, dict) else {}
    )
    return MarketplaceSourceResponse(
        id=source.id,
        handle=source.handle,
        display_name=source.display_name,
        base_url=source.base_url,
        scope=source.scope,
        user_id=source.user_id,
        team_id=source.team_id,
        trust_level=source.trust_level,
        is_system=_is_system_row(source),
        is_active=bool(source.is_active),
        has_token=bool(source.encrypted_token),
        pinned_hub_id=source.pinned_hub_id,
        capabilities=capabilities,
        policies=policies,
        checkout_via_hub_enabled=bool(
            getattr(source, "checkout_via_hub_enabled", False)
        ),
        last_synced_at=source.last_synced_at,
        last_sync_error=source.last_sync_error,
        sync_etag=source.sync_etag,
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


async def _user_team_ids(db: AsyncSession, user_id: UUID) -> list[UUID]:
    """Active team memberships for the requester."""
    result = await db.execute(
        select(TeamMembership.team_id).where(
            TeamMembership.user_id == user_id,
            TeamMembership.is_active.is_(True),
        )
    )
    return [row[0] for row in result.all()]


def _decrypt_token_or_none(encrypted: str | None) -> str | None:
    if not encrypted:
        return None
    try:
        decrypted = get_credential_manager().decrypt_token(encrypted)
        return decrypted or None
    except Exception:  # noqa: BLE001
        # Fail closed — a token we cannot decrypt is a token we cannot use.
        # The /test endpoint will surface this via its 400 response.
        logger.warning("marketplace_sources: failed to decrypt stored token")
        return None


async def _load_visible_source(
    db: AsyncSession, source_id: UUID, user: User
) -> MarketplaceSource:
    """Load a source the requester is allowed to see, else 404.

    Visibility = system rows OR (scope='user' AND user_id == me) OR
    (scope='team' AND team_id IN my active teams). Superusers see every
    row regardless of scope (consistent with permissions.py policy).
    """
    src = await db.get(MarketplaceSource, source_id)
    if src is None:
        raise HTTPException(status_code=404, detail="Marketplace source not found")
    if user.is_superuser:
        return src
    if src.scope == "system":
        return src
    if src.scope == "user" and src.user_id == user.id:
        return src
    if src.scope == "team":
        team_ids = await _user_team_ids(db, user.id)
        if src.team_id in team_ids:
            return src
    raise HTTPException(status_code=404, detail="Marketplace source not found")


def _classify_trust(*, has_token: bool) -> str:
    """Auto-classify trust at create/test time.

    The plan's source-trust matrix decides install gating; ``admin_trusted``
    is reachable only via the /promote endpoint by a superuser.
    """
    return "private" if has_token else "untrusted"


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


@router.get("", response_model=list[MarketplaceSourceResponse])
async def list_sources(
    include_inactive: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> list[MarketplaceSourceResponse]:
    """List the marketplace sources visible to the requester.

    Always includes system rows (tesslate-official + local). Adds the
    requester's own user-scope rows and the team-scope rows for every
    team the requester actively belongs to.
    """
    team_ids = await _user_team_ids(db, user.id)

    visibility_clauses = [
        MarketplaceSource.scope == "system",
        and_(MarketplaceSource.scope == "user", MarketplaceSource.user_id == user.id),
    ]
    if team_ids:
        visibility_clauses.append(
            and_(
                MarketplaceSource.scope == "team",
                MarketplaceSource.team_id.in_(team_ids),
            )
        )

    stmt = select(MarketplaceSource).where(or_(*visibility_clauses))
    if not include_inactive:
        # System rows are always returned even if a future admin disables
        # them — the UI needs to render them as warnings rather than hide
        # them silently.
        stmt = stmt.where(
            or_(
                MarketplaceSource.is_active.is_(True),
                MarketplaceSource.scope == "system",
            )
        )
    stmt = stmt.order_by(
        MarketplaceSource.scope.desc(),  # 'user' < 'team' < 'system' lexicographically — descending puts system first
        MarketplaceSource.handle,
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [_serialize(r) for r in rows]


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


@router.post("", response_model=MarketplaceSourceResponse, status_code=status.HTTP_201_CREATED)
async def create_source(
    payload: SourceCreatePayload,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> MarketplaceSourceResponse:
    """Create a new federated marketplace source.

    Server picks ``trust_level``: ``untrusted`` if no token, ``private``
    when a bearer is supplied. Promotion to ``admin_trusted`` is a
    superuser-only operation via /promote (separate endpoint).

    For ``scope='team'`` the requester must belong to a team. We pick
    ``user.default_team_id`` so the UI doesn't have to surface a team
    picker on the create modal — the UI already constrains this option
    to teams the user is on. Users with no team get a clear 400.
    """
    handle = payload.handle.strip()
    display_name = payload.display_name.strip()
    base_url = payload.base_url.strip()
    has_token = bool(payload.encrypted_token)
    trust_level = _classify_trust(has_token=has_token)

    # Encrypt the token at the boundary so we never store plaintext. The
    # frontend sends the *plaintext* token in ``encrypted_token`` for API
    # symmetry with other token endpoints — naming is a UX hint, the
    # actual encryption happens here.
    encrypted_token: str | None = None
    if has_token and payload.encrypted_token:
        encrypted_token = get_credential_manager().encrypt_token(
            payload.encrypted_token
        )

    if payload.scope == "team":
        team_id = user.default_team_id
        if team_id is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Cannot create a team-scope source: requester has no "
                    "default team. Switch to a team first."
                ),
            )
        team_ids = await _user_team_ids(db, user.id)
        if team_id not in team_ids:
            raise HTTPException(
                status_code=403,
                detail="Requester is not an active member of the default team",
            )
        source = MarketplaceSource(
            handle=handle,
            display_name=display_name,
            base_url=base_url,
            encrypted_token=encrypted_token,
            scope="team",
            user_id=None,
            team_id=team_id,
            trust_level=trust_level,
            is_active=True,
        )
    else:
        source = MarketplaceSource(
            handle=handle,
            display_name=display_name,
            base_url=base_url,
            encrypted_token=encrypted_token,
            scope="user",
            user_id=user.id,
            team_id=None,
            trust_level=trust_level,
            is_active=True,
        )

    db.add(source)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        # Most likely the partial unique index on the requester's scope
        # bucket fired (same handle already exists for this user/team).
        raise HTTPException(
            status_code=409,
            detail=(
                f"A marketplace source with handle {handle!r} already "
                f"exists in your {payload.scope} scope"
            ),
        ) from exc
    await db.refresh(source)
    logger.info(
        "marketplace_sources: created handle=%s scope=%s trust=%s by user=%s",
        handle,
        payload.scope,
        trust_level,
        user.id,
    )
    return _serialize(source)


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


@router.patch("/{source_id}", response_model=MarketplaceSourceResponse)
async def update_source(
    source_id: UUID,
    payload: SourceUpdatePayload,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> MarketplaceSourceResponse:
    """Update display name, token, or active flag on a non-system source.

    System rows (tesslate-official, local) are immutable: 403.
    """
    source = await _load_visible_source(db, source_id, user)
    if _is_system_row(source):
        raise HTTPException(
            status_code=403,
            detail="System marketplace sources are immutable",
        )

    changed = False
    token_changed = False

    if payload.display_name is not None:
        new_name = payload.display_name.strip()
        if not new_name:
            raise HTTPException(status_code=400, detail="display_name cannot be blank")
        source.display_name = new_name
        changed = True

    if payload.clear_token:
        if source.encrypted_token is not None:
            source.encrypted_token = None
            changed = True
            token_changed = True
    elif payload.encrypted_token is not None:
        encrypted = get_credential_manager().encrypt_token(payload.encrypted_token)
        source.encrypted_token = encrypted
        changed = True
        token_changed = True

    if payload.is_active is not None:
        if bool(source.is_active) != bool(payload.is_active):
            source.is_active = bool(payload.is_active)
            changed = True

    # Token presence flips the auto-trust classification, but only for
    # rows that haven't been admin-promoted to ``admin_trusted``. We
    # never auto-demote a promoted row — only /promote can do that.
    if token_changed and source.trust_level not in {"admin_trusted", "official", "local"}:
        source.trust_level = _classify_trust(has_token=bool(source.encrypted_token))

    if changed:
        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise HTTPException(
                status_code=409,
                detail="Update conflicted with an existing source",
            ) from exc
        await db.refresh(source)
    return _serialize(source)


# ---------------------------------------------------------------------------
# Delete (soft)
# ---------------------------------------------------------------------------


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(
    source_id: UUID,
    hard: bool = False,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> Response:
    """Soft-delete a non-system source (sets ``is_active=false``).

    Hard deletion is supported only when the source has zero referencing
    catalog rows AND zero referencing user-state rows. The default soft
    delete is the recommended path: it preserves audit history, lets
    install endpoints surface "source disabled" errors, and is reversible
    via PATCH ``is_active=true``.

    System rows immutable: 403.
    """
    source = await _load_visible_source(db, source_id, user)
    if _is_system_row(source):
        raise HTTPException(
            status_code=403,
            detail="System marketplace sources are immutable",
        )

    if hard:
        # Cascade-clean references before deletion. We only allow hard
        # delete when no user-state references exist (the conservative
        # path — anything else risks orphaning purchase / install
        # history). Catalog rows synced from this source are deleted
        # because their primary key is local and they have no upstream
        # truth post-deactivation.
        if not await _can_hard_delete(db, source):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Cannot hard-delete this source: user-state rows still "
                    "reference catalog rows synced from it. Soft-delete "
                    "(hard=false) instead, then revisit after user-state "
                    "is cleaned up."
                ),
            )
        await _hard_delete_source(db, source)
    else:
        if source.is_active:
            source.is_active = False
            await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _can_hard_delete(db: AsyncSession, source: MarketplaceSource) -> bool:
    """Return True when no user-state rows reference this source's catalog rows."""
    src_id = source.id

    # Cheap helper: count non-zero user-state references for any catalog
    # row that points at this source. We short-circuit on the first hit.
    queries = [
        select(UserPurchasedAgent.id)
        .join(MarketplaceAgent, MarketplaceAgent.id == UserPurchasedAgent.agent_id)
        .where(MarketplaceAgent.source_id == src_id)
        .limit(1),
        select(UserPurchasedBase.id)
        .join(MarketplaceBase, MarketplaceBase.id == UserPurchasedBase.base_id)
        .where(MarketplaceBase.source_id == src_id)
        .limit(1),
        select(UserMcpConfig.id)
        .join(
            MarketplaceAgent,
            MarketplaceAgent.id == UserMcpConfig.marketplace_agent_id,
        )
        .where(MarketplaceAgent.source_id == src_id)
        .limit(1),
        select(UserLibraryTheme.id)
        .join(Theme, Theme.id == UserLibraryTheme.theme_id)
        .where(Theme.source_id == src_id)
        .limit(1),
        select(AgentSkillAssignment.id)
        .join(
            MarketplaceAgent,
            MarketplaceAgent.id == AgentSkillAssignment.skill_id,
        )
        .where(MarketplaceAgent.source_id == src_id)
        .limit(1),
        # AgentMcpAssignment links agents (whose source_id we filter on)
        # to a user-owned MCP config. The agent FK is what ties the
        # assignment to a federated source.
        select(AgentMcpAssignment.id)
        .join(
            MarketplaceAgent,
            MarketplaceAgent.id == AgentMcpAssignment.agent_id,
        )
        .where(MarketplaceAgent.source_id == src_id)
        .limit(1),
    ]
    for q in queries:
        result = await db.execute(q)
        if result.scalar_one_or_none() is not None:
            return False
    return True


async def _hard_delete_source(db: AsyncSession, source: MarketplaceSource) -> None:
    """Delete a source plus its catalog cache rows.

    Caller must have already validated via :func:`_can_hard_delete` that
    no user-state references remain. This helper is the rare cascade
    path documented in the plan: "soft-delete + cascade-clean any
    user-state references that ONLY came from this source (rare;
    document the path)".
    """
    src_id = source.id
    # Order matters: drop AppVersion before MarketplaceApp, etc. SQLA
    # sets ondelete=RESTRICT on source_id FKs (alembic 0088), so we
    # delete the catalog rows manually.
    for model in (
        WorkflowTemplate,
        Theme,
        MarketplaceApp,
        MarketplaceBase,
        MarketplaceAgent,
    ):
        await db.execute(delete(model).where(model.source_id == src_id))
    await db.delete(source)
    await db.commit()


# ---------------------------------------------------------------------------
# Test connection (pin hub_id, snapshot manifest)
# ---------------------------------------------------------------------------


@router.post("/{source_id}/test", response_model=SourceTestResponse)
async def test_source(
    source_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> SourceTestResponse:
    """Fetch ``/v1/manifest`` from the source and pin its hub_id.

    Snapshots ``capabilities_cache`` + ``policies_cache`` so the source
    list UI can render advertised capabilities without a per-row live
    fetch. Mirrors the auto-pin behavior in
    ``services.marketplace_federation.live_resolve``: on first contact
    the hub_id is recorded; subsequent calls verify the X-Tesslate-Hub-Id
    header against this pin. A mismatch on the *test* call (when the pin
    was set previously) auto-disables the source and records the error.
    """
    source = await _load_visible_source(db, source_id, user)

    if source.base_url.startswith(LOCAL_URL_PREFIX):
        raise HTTPException(
            status_code=400,
            detail="Local sources do not have a remote manifest; nothing to test",
        )

    decrypted = _decrypt_token_or_none(source.encrypted_token)

    client = MarketplaceClient(
        base_url=source.base_url,
        token=decrypted,
        # Pass the existing pin so the client enforces it on the manifest
        # response. If we have no pin yet, the first manifest call simply
        # records one — see ``HubIdMismatchError`` handling below.
        pinned_hub_id=source.pinned_hub_id,
    )
    try:
        try:
            manifest = await client.get_manifest()
        except HubIdMismatchError as exc:
            # Hijack-or-relocation guard: pre-existing pin says one
            # hub_id, the URL now serves a different one. Auto-disable
            # and surface the error so the user can investigate.
            source.is_active = False
            source.last_sync_error = (
                f"Hub identity changed: pinned={source.pinned_hub_id!r} "
                f"saw={exc.actual!r}. Source has been disabled."
            )
            await db.commit()
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "hub_id_mismatch",
                    "pinned_hub_id": source.pinned_hub_id,
                    "actual_hub_id": exc.actual,
                    "message": "Source disabled. Re-add with the correct URL.",
                },
            ) from exc
        except MarketplaceClientError as exc:
            source.last_sync_error = f"manifest fetch failed: {exc}"[:1000]
            await db.commit()
            raise HTTPException(
                status_code=502,
                detail={"error": "test_failed", "message": str(exc)},
            ) from exc

        hub_id = manifest.get("hub_id")
        if not isinstance(hub_id, str) or not hub_id:
            source.last_sync_error = (
                "manifest response missing hub_id (protocol violation)"
            )
            await db.commit()
            raise HTTPException(
                status_code=502,
                detail={
                    "error": "manifest_missing_hub_id",
                    "message": "The hub returned a manifest without a hub_id.",
                },
            )

        pinned_changed = (
            source.pinned_hub_id is None or source.pinned_hub_id != hub_id
        )
        source.pinned_hub_id = hub_id

        capabilities_raw = manifest.get("capabilities") or []
        policies_raw = manifest.get("policies") or {}
        source.capabilities_cache = (
            list(capabilities_raw) if isinstance(capabilities_raw, list) else []
        )
        source.policies_cache = (
            dict(policies_raw) if isinstance(policies_raw, dict) else {}
        )
        # Successful test clears any previous sync error.
        source.last_sync_error = None
        # Don't bump last_synced_at — that's strictly the sync worker's
        # field. The "test connection" UX is about identity verification
        # and capability discovery, not catalog freshness.
        await db.commit()
        await db.refresh(source)
    finally:
        await client.aclose()

    auto_trust = source.trust_level
    if source.trust_level not in {"admin_trusted", "official", "local"}:
        auto_trust = _classify_trust(has_token=bool(source.encrypted_token))
        if auto_trust != source.trust_level:
            source.trust_level = auto_trust
            await db.commit()
            await db.refresh(source)

    capabilities_list = source.capabilities_cache or []
    if isinstance(capabilities_list, dict):
        capabilities_list = capabilities_list.get("capabilities") or []

    policies_dict = source.policies_cache if isinstance(source.policies_cache, dict) else {}

    return SourceTestResponse(
        hub_id=hub_id,
        api_version=manifest.get("api_version") if isinstance(manifest.get("api_version"), str) else None,
        display_name=manifest.get("display_name") if isinstance(manifest.get("display_name"), str) else None,
        capabilities=[str(c) for c in capabilities_list],
        policies=policies_dict,
        auto_trust_level=auto_trust,
        pinned_hub_id_changed=pinned_changed,
    )


# ---------------------------------------------------------------------------
# Manual sync trigger
# ---------------------------------------------------------------------------


@router.post("/{source_id}/sync", response_model=SourceSyncResponse)
async def sync_source(
    source_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> SourceSyncResponse:
    """Run the marketplace sync worker against this single source.

    Returns the per-source sync result: events processed, items
    upserted/deleted/deactivated, version yanks/removes, pricing
    changes, and the resulting ``last_sync_error`` (if any).

    The sync worker is intentionally tolerant — failures are recorded
    on the source row rather than raised, so the response always carries
    a usable result envelope.
    """
    source = await _load_visible_source(db, source_id, user)

    if not source.is_active:
        raise HTTPException(
            status_code=409,
            detail="Cannot sync an inactive source. PATCH is_active=true first.",
        )

    # Local sources are populated by ``marketplace_local.sync_local`` (a
    # filesystem scan), not the HTTP changes-feed worker. Dispatch to the
    # right backend transparently so the UI calls one endpoint regardless.
    if source.base_url.startswith(LOCAL_URL_PREFIX):
        from ..services import marketplace_local as _local

        try:
            local_result = await _local.sync_local(db, source_id=source.id)
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"local sync failed: {exc}",
            ) from exc

        await db.refresh(source)
        return SourceSyncResponse(
            source_id=local_result.source_id,
            source_handle=source.handle,
            events_processed=len(local_result.events),
            items_upserted=local_result.items_upserted,
            items_deleted=local_result.items_deleted,
            items_deactivated=0,
            versions_yanked=0,
            versions_removed=local_result.versions_removed,
            pricing_changes=0,
            etag_advanced_to=None,
            error=local_result.error,
            skipped_reason=None,
            last_sync_error=source.last_sync_error,
            last_synced_at=source.last_synced_at,
        )

    from ..database import AsyncSessionLocal

    worker = MarketplaceSyncWorker(db_session_factory=AsyncSessionLocal)
    result = await worker.sync_source(source.id)

    # Refresh from DB — the worker uses its own session and updates
    # last_synced_at / last_sync_error there.
    await db.refresh(source)

    return SourceSyncResponse(
        source_id=result.source_id,
        source_handle=result.source_handle,
        events_processed=result.events_processed,
        items_upserted=result.items_upserted,
        items_deleted=result.items_deleted,
        items_deactivated=result.items_deactivated,
        versions_yanked=result.versions_yanked,
        versions_removed=result.versions_removed,
        pricing_changes=result.pricing_changes,
        etag_advanced_to=result.etag_advanced_to,
        error=result.error,
        skipped_reason=result.skipped_reason,
        last_sync_error=source.last_sync_error,
        last_synced_at=source.last_synced_at,
    )


# ---------------------------------------------------------------------------
# Promote (superuser only)
# ---------------------------------------------------------------------------


@router.post("/{source_id}/promote", response_model=MarketplaceSourceResponse)
async def promote_source(
    source_id: UUID,
    payload: SourcePromotePayload,
    db: AsyncSession = Depends(get_db),
    superuser: User = Depends(current_superuser),
) -> MarketplaceSourceResponse:
    """Promote (or demote) a source's trust level. Superuser only.

    Allowed transitions:
      - any → ``admin_trusted``  (promote: opens MCP/app installs without
        per-install confirmation)
      - any → ``private``        (demote to per-install-confirm gate)
      - any → ``untrusted``      (demote: blocks MCP/app installs)

    System rows (``official``, ``local``) cannot be repointed via this
    endpoint — they have specialized trust semantics elsewhere.
    """
    source = await db.get(MarketplaceSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Marketplace source not found")
    if _is_system_row(source):
        raise HTTPException(
            status_code=403,
            detail="System marketplace sources have fixed trust levels",
        )
    source.trust_level = payload.trust_level
    await db.commit()
    await db.refresh(source)
    logger.info(
        "marketplace_sources: superuser %s promoted source %s to trust=%s",
        superuser.id,
        source.id,
        payload.trust_level,
    )
    return _serialize(source)


# ---------------------------------------------------------------------------
# Wave 9 — per-source hub-checkout opt-in
# ---------------------------------------------------------------------------


class CheckoutFlagPayload(BaseModel):
    enabled: bool


@router.post(
    "/{source_id}/checkout-flag",
    response_model=MarketplaceSourceResponse,
)
async def set_checkout_flag(
    source_id: UUID,
    payload: CheckoutFlagPayload,
    db: AsyncSession = Depends(get_db),
    superuser: User = Depends(current_superuser),
) -> MarketplaceSourceResponse:
    """Flip the per-source ``checkout_via_hub_enabled`` dial. Superuser only.

    The Wave-9 cutover happens item-by-item via this endpoint plus the
    runtime feature flag and the global setting. All three must be on
    before ``dispatch_purchase`` routes a purchase through the hub-owned
    Stripe Connect path.

    Operators flip this true after parity tests pass for the source
    (Stripe checkout session creation, webhook reconciliation,
    subscription cancel, refund, customer-portal access). Setting it
    false instantly reverts the source to the orchestrator-owned Stripe
    safety fallback.

    System rows (``official``, ``local``) are allowed because Tesslate
    Official IS the canonical hub that owns the rollout.
    """
    source = await db.get(MarketplaceSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Marketplace source not found")
    # Per-source dial only meaningful for sources that can host paid checkout.
    if source.trust_level not in {"official", "admin_trusted"}:
        raise HTTPException(
            status_code=409,
            detail=(
                "checkout_via_hub_enabled requires trust_level >= admin_trusted; "
                f"source has trust_level={source.trust_level!r}"
            ),
        )
    source.checkout_via_hub_enabled = bool(payload.enabled)
    await db.commit()
    await db.refresh(source)
    logger.info(
        "marketplace_sources: superuser %s set checkout_via_hub_enabled=%s on source=%s",
        superuser.id,
        payload.enabled,
        source.handle,
    )
    return _serialize(source)


# ---------------------------------------------------------------------------
# Wave 9 — entitlements grant (hub → orchestrator webhook reconciliation)
# ---------------------------------------------------------------------------


class EntitlementGrantPayload(BaseModel):
    """Shape the hub POSTs to /entitlements/grant after Stripe Connect succeeds.

    The hub owns its own Stripe webhook; once the checkout completes the
    hub signs this payload with HMAC-SHA256 (using
    ``MARKETPLACE_HUB_ENTITLEMENT_SECRET`` + the source's pinned hub_id)
    and POSTs it to the orchestrator. The orchestrator verifies the
    signature, looks up the cached catalog row, and inserts the
    appropriate entitlement (``UserPurchasedAgent`` for agents).
    """

    kind: str = Field(..., description="agent | app | base | etc — the catalog kind")
    slug: str = Field(..., description="The item slug within (source, kind)")
    user_id: UUID = Field(..., description="Orchestrator user receiving the entitlement")
    purchase_type: str = Field(default="purchased", description="free | purchased | subscription")
    stripe_session_id: str | None = None
    stripe_subscription_id: str | None = None
    stripe_payment_intent: str | None = None
    expires_at: datetime | None = None
    metadata: dict[str, Any] | None = None


class EntitlementGrantResponse(BaseModel):
    granted: bool
    entitlement_id: UUID | None = None
    already_granted: bool = False
    kind: str
    slug: str


def _verify_entitlement_signature(
    *,
    raw_body: bytes,
    signature_header: str | None,
    secret: str,
    hub_id: str | None,
) -> bool:
    """HMAC-SHA256 verification of an entitlement-grant body.

    Hub computes ``HMAC-SHA256(secret + ":" + hub_id, raw_body)`` and
    sends the hex digest in ``X-Tesslate-Entitlement-Signature``. We
    re-compute and ``hmac.compare_digest`` to thwart timing oracles.
    Returns False on any input mismatch — caller raises 401.
    """
    if not signature_header or not secret or not hub_id:
        return False
    keying = f"{secret}:{hub_id}".encode()
    expected = hmac.new(keying, raw_body, hashlib.sha256).hexdigest()
    # Accept both ``hex`` and ``sha256=<hex>`` framings.
    received = signature_header.strip()
    if received.startswith("sha256="):
        received = received[len("sha256=") :]
    try:
        return hmac.compare_digest(expected, received)
    except Exception:  # noqa: BLE001 — defensive, treat any error as mismatch
        return False


@router.post(
    "/{source_id}/entitlements/grant",
    response_model=EntitlementGrantResponse,
)
async def grant_entitlement(
    source_id: UUID,
    payload: EntitlementGrantPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> EntitlementGrantResponse:
    """Wave-9 webhook: federated hub reports a successful Stripe Connect grant.

    Authentication: HMAC-SHA256 signature in
    ``X-Tesslate-Entitlement-Signature`` over the raw request body, keyed
    on ``MARKETPLACE_HUB_ENTITLEMENT_SECRET`` + the source's pinned
    ``hub_id``. Sources without a pinned hub_id are refused (the pin is
    the orchestrator's identity anchor — without it any third party
    could impersonate the hub).

    Idempotency: if a ``UserPurchasedAgent`` row for ``(user_id,
    agent_id)`` already exists and is active, we return
    ``already_granted=true`` without inserting. This matches the
    orchestrator-Stripe path's idempotency in
    ``stripe_service._handle_agent_purchase_checkout``.

    Note: per the Wave-9 plan we use this push-from-hub pattern (rather
    than forwarding webhooks blindly) so source-of-truth boundaries
    are preserved — the hub owns its Stripe events, the orchestrator
    only learns about granted entitlements.
    """
    source = await db.get(MarketplaceSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Marketplace source not found")
    if not source.is_active:
        raise HTTPException(status_code=409, detail="source_inactive")
    if source.trust_level not in {"official", "admin_trusted"}:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "trust_level_too_low",
                "trust_level": source.trust_level,
                "required": "admin_trusted",
            },
        )
    if not source.pinned_hub_id:
        # Without a pinned hub_id the signature key is not anchored, and
        # any URL hijack could mint entitlements at will.
        raise HTTPException(status_code=409, detail="source_unpinned")

    settings = get_settings()
    secret = (settings.marketplace_hub_entitlement_secret or "").strip()
    if not secret:
        # Never accept an unsigned grant — fail closed.
        raise HTTPException(
            status_code=503,
            detail={
                "error": "entitlement_secret_unconfigured",
                "message": (
                    "MARKETPLACE_HUB_ENTITLEMENT_SECRET is empty; orchestrator "
                    "cannot verify hub-issued entitlement grants."
                ),
            },
        )

    raw_body = await request.body()
    signature = request.headers.get("X-Tesslate-Entitlement-Signature")
    if not _verify_entitlement_signature(
        raw_body=raw_body,
        signature_header=signature,
        secret=secret,
        hub_id=source.pinned_hub_id,
    ):
        raise HTTPException(
            status_code=401,
            detail={
                "error": "invalid_signature",
                "source_handle": source.handle,
            },
        )

    # The user MUST exist locally; pairing is the orchestrator's job, not
    # the hub's. If the hub references a user the orchestrator doesn't
    # know we 404 so a misconfigured hub can't insert orphan rows.
    user = await db.get(User, payload.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")

    if payload.kind == "agent":
        agent = (
            await db.execute(
                select(MarketplaceAgent).where(
                    MarketplaceAgent.source_id == source.id,
                    MarketplaceAgent.slug == payload.slug,
                )
            )
        ).scalar_one_or_none()
        if agent is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "agent_not_found",
                    "source_handle": source.handle,
                    "slug": payload.slug,
                },
            )

        existing = (
            await db.execute(
                select(UserPurchasedAgent).where(
                    and_(
                        UserPurchasedAgent.user_id == user.id,
                        UserPurchasedAgent.agent_id == agent.id,
                    )
                )
            )
        ).scalar_one_or_none()
        if existing is not None and existing.is_active:
            return EntitlementGrantResponse(
                granted=True,
                entitlement_id=existing.id,
                already_granted=True,
                kind="agent",
                slug=agent.slug,
            )

        if existing is not None:
            # Re-activate stale row instead of inserting a duplicate.
            existing.is_active = True
            existing.purchase_date = datetime.now(UTC)
            existing.purchase_type = payload.purchase_type
            existing.stripe_payment_intent = payload.stripe_payment_intent
            existing.stripe_subscription_id = payload.stripe_subscription_id
            existing.expires_at = payload.expires_at
            await db.commit()
            await db.refresh(existing)
            entitlement_id = existing.id
        else:
            row = UserPurchasedAgent(
                user_id=user.id,
                team_id=getattr(user, "default_team_id", None),
                agent_id=agent.id,
                purchase_type=payload.purchase_type,
                stripe_payment_intent=payload.stripe_payment_intent,
                stripe_subscription_id=payload.stripe_subscription_id,
                expires_at=payload.expires_at,
                is_active=True,
            )
            db.add(row)
            agent.downloads += 1
            await db.commit()
            await db.refresh(row)
            entitlement_id = row.id

        logger.info(
            "marketplace_sources: hub %s granted agent entitlement user=%s agent=%s",
            source.handle,
            user.id,
            agent.id,
        )
        return EntitlementGrantResponse(
            granted=True,
            entitlement_id=entitlement_id,
            already_granted=False,
            kind="agent",
            slug=agent.slug,
        )

    # Other kinds (app, base, theme, ...) follow when their respective
    # entitlement tables get the source_id linkage. For Wave 9 only the
    # agent kind has a Stripe-driven entitlement table.
    raise HTTPException(
        status_code=501,
        detail={
            "error": "kind_not_implemented",
            "kind": payload.kind,
            "supported": ["agent"],
        },
    )


# ---------------------------------------------------------------------------
# Wave 8 — submission state-change webhook (hub → orchestrator)
# ---------------------------------------------------------------------------


def _verify_submission_signature(
    *,
    raw_body: bytes,
    signature_header: str | None,
    secret: str,
    hub_id: str | None,
) -> bool:
    """HMAC-SHA256 verification of a submission state-change payload.

    Reuses the entitlement-grant pattern: hub computes
    ``HMAC-SHA256(secret + ':' + hub_id, raw_body)`` and sends the hex
    digest in ``X-Tesslate-Submission-Signature``. The keying pair
    (``secret`` is ``MARKETPLACE_SUBMISSION_WEBHOOK_SECRET``,
    ``hub_id`` is the source's pinned hub_id) is shared out-of-band when
    the source is paired.
    """
    if not signature_header or not secret or not hub_id:
        return False
    keying = f"{secret}:{hub_id}".encode()
    expected = hmac.new(keying, raw_body, hashlib.sha256).hexdigest()
    received = signature_header.strip()
    if received.startswith("sha256="):
        received = received[len("sha256="):]
    try:
        return hmac.compare_digest(expected, received)
    except Exception:  # noqa: BLE001
        return False


class SubmissionStateChangePayload(BaseModel):
    """Body the marketplace POSTs when a submission state advances.

    Mirrors the ``submissions.staged`` envelope so the orchestrator can
    push it directly through ``mirror_submission_into_cache`` without
    re-shaping the data.
    """

    id: str = Field(..., description="Marketplace submission UUID")
    kind: str
    slug: str
    version: str | None = None
    state: str
    stage: str
    decision: str | None = None
    decision_reason: str | None = None
    bundle_sha256: str | None = None
    bundle_size_bytes: int | None = None
    item_id: str | None = None
    item_version_id: str | None = None
    checks: list[dict[str, Any]] = Field(default_factory=list)


@router.post(
    "/{source_id}/submissions/{submission_id}/state-change",
)
async def submission_state_change(
    source_id: UUID,
    submission_id: UUID,
    payload: SubmissionStateChangePayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Wave 8 webhook: marketplace pushes submission state advancements back.

    The orchestrator's local cache row (``app_submissions``) is mirrored
    from the marketplace's authoritative state. The HMAC signature is
    verified against the source's pinned ``hub_id`` so a misconfigured
    URL can't be used to spoof governance state.
    """
    from ..services.marketplace_governance import mirror_submission_into_cache

    source = await db.get(MarketplaceSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="source not found")
    if not source.is_active:
        raise HTTPException(status_code=409, detail="source_inactive")
    if not source.pinned_hub_id:
        raise HTTPException(status_code=409, detail="source_unpinned")

    settings = get_settings()
    secret = (settings.marketplace_submission_webhook_secret or "").strip()
    if not secret:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "submission_webhook_secret_unconfigured",
                "message": (
                    "MARKETPLACE_SUBMISSION_WEBHOOK_SECRET is empty; orchestrator "
                    "cannot verify hub-issued submission state changes."
                ),
            },
        )

    raw_body = await request.body()
    signature = request.headers.get("X-Tesslate-Submission-Signature")
    if not _verify_submission_signature(
        raw_body=raw_body,
        signature_header=signature,
        secret=secret,
        hub_id=source.pinned_hub_id,
    ):
        raise HTTPException(
            status_code=401,
            detail={
                "error": "invalid_signature",
                "source_handle": source.handle,
            },
        )

    envelope = payload.model_dump(exclude_none=False)
    mirrored = await mirror_submission_into_cache(
        db,
        local_submission_id=submission_id,
        marketplace_envelope=envelope,
    )
    await db.commit()

    return {
        "mirrored": mirrored is not None,
        "submission_id": str(submission_id),
        "source_handle": source.handle,
        "state": payload.state,
        "stage": payload.stage,
    }
