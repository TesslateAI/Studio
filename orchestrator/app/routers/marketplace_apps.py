"""Marketplace Apps — browse, inspect, fork.

Wave 7 federation cuts:

* Every list/detail endpoint accepts ``?source=<handle>`` and filters
  cached app rows down to that source. Omitted ``?source=`` returns rows
  interleaved across every active source (the federation dropdown's
  "All sources" mode), matching the patterns in ``routers/marketplace.py``.
* The fork endpoint refuses to fork apps from sources whose
  ``trust_level`` is below ``admin_trusted`` so the strict app install
  gate (see ``services/marketplace_federation.py::install_guard``) is not
  side-stepped via the fork seam.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from typing import cast as type_cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_db
from ..models import (
    AppInstance,
    AppVersion,
    MarketplaceApp,
    MarketplaceSource,
    User,
)
from ..services.apps.fork import ForkError, NotForkableError, fork_app
from ..services.hub_client import HubClient
from ..services.marketplace_federation import dispatch_purchase, install_guard
from ..users import current_active_user

logger = logging.getLogger(__name__)
router = APIRouter()


class MarketplaceAppResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    name: str
    description: str | None = None
    category: str | None = None
    icon_ref: str | None = None
    forkable: str
    forked_from: UUID | None = None
    visibility: str
    state: str
    reputation: dict[str, Any] = Field(default_factory=dict)
    creator_user_id: UUID | None = None
    created_at: datetime
    updated_at: datetime
    # Wave 7: source provenance surfaced on every browse row so the
    # frontend can render the source chip + drive the federation dropdown.
    source_id: UUID | None = None
    source_handle: str | None = None
    source_display_name: str | None = None
    source_trust_level: str | None = None


class AppVersionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    app_id: UUID
    version: str
    manifest_schema_version: str
    manifest_hash: str
    bundle_hash: str | None = None
    approval_state: str
    yanked_at: datetime | None = None
    yanked_reason: str | None = None
    yanked_is_critical: bool = False
    yanked_upstream_at: datetime | None = None
    published_at: datetime | None = None
    created_at: datetime
    source_id: UUID | None = None


class AppListEnvelope(BaseModel):
    items: list[MarketplaceAppResponse]
    total: int
    limit: int
    offset: int


class AppVersionListEnvelope(BaseModel):
    items: list[AppVersionSummary]
    total: int
    limit: int
    offset: int


class ForkRequest(BaseModel):
    source_app_version_id: UUID
    new_slug: str
    new_name: str
    team_id: UUID | None = None


class ForkResponse(MarketplaceAppResponse):
    project_id: UUID | None = None
    project_slug: str | None = None


def _get_hub_client() -> HubClient:
    settings = get_settings()
    return HubClient(settings.volume_hub_address)


# ---------------------------------------------------------------------------
# Wave 7 federation helpers
# ---------------------------------------------------------------------------


async def _resolve_source_filter(
    db: AsyncSession, source_handle: str | None
) -> UUID | None:
    """Resolve a ``?source=<handle>`` query param to a ``source_id``.

    Returns ``None`` when the caller did not supply ``source_handle``
    (cross-source mode — the dropdown's "All sources"). Raises 404 when
    the handle is unknown so the UI surfaces a typed error rather than
    silently returning an empty result set.

    Mirrors the helper in ``routers/marketplace.py`` Wave 4 — apps stayed
    on the legacy code path until Wave 7, so we lift the same pattern
    here rather than sharing module state.
    """
    if not source_handle:
        return None
    result = await db.execute(
        select(MarketplaceSource).where(MarketplaceSource.handle == source_handle)
    )
    source = result.scalar_one_or_none()
    if source is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown marketplace source handle: {source_handle!r}",
        )
    return type_cast(UUID, source.id)


async def _bulk_load_sources(
    db: AsyncSession, source_ids: set[Any]
) -> dict[UUID, MarketplaceSource]:
    """One-shot load of every distinct source referenced by a list result.

    Avoids N+1 lookups when serializing list responses with per-row
    source chips.
    """
    cleaned: set[UUID] = {
        type_cast(UUID, sid) for sid in source_ids if sid is not None
    }
    if not cleaned:
        return {}
    result = await db.execute(
        select(MarketplaceSource).where(MarketplaceSource.id.in_(cleaned))
    )
    out: dict[UUID, MarketplaceSource] = {}
    for src in result.scalars().all():
        out[type_cast(UUID, src.id)] = src
    return out


def _attach_source_meta(
    payload: MarketplaceAppResponse,
    sources: dict[UUID, MarketplaceSource],
    source_id: Any,
) -> MarketplaceAppResponse:
    """Splice source provenance fields onto a serialized app response."""
    if source_id is None:
        return payload
    src = sources.get(type_cast(UUID, source_id))
    if src is None:
        return payload
    payload.source_handle = type_cast(str, src.handle)
    payload.source_display_name = type_cast(str | None, src.display_name)
    payload.source_trust_level = type_cast(str, src.trust_level)
    return payload


async def _user_can_see_app(db: AsyncSession, app_row: MarketplaceApp, user: User) -> bool:
    if user.is_superuser:
        return True
    if app_row.creator_user_id == user.id:
        return True
    if app_row.visibility == "public" and app_row.state == "approved":
        return True
    # Installer with an instance can see the app row.
    inst_id = (
        await db.execute(
            select(AppInstance.id)
            .where(
                AppInstance.app_id == app_row.id,
                AppInstance.installer_user_id == user.id,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return inst_id is not None


@router.get("", response_model=AppListEnvelope)
async def list_apps(
    q: str | None = Query(None, description="Substring match on name or slug"),
    category: str | None = Query(None),
    creator_user_id: UUID | None = Query(None),
    source: str | None = Query(
        None,
        description=(
            "Filter cached app rows down to a single marketplace source by "
            "handle. Omit for cross-source results (the dropdown's "
            "'All sources' mode). Returns 404 on unknown handle."
        ),
    ),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> AppListEnvelope:
    source_id_filter = await _resolve_source_filter(db, source)

    stmt = select(MarketplaceApp)
    count_stmt = select(func.count()).select_from(MarketplaceApp)

    filters = []
    if not user.is_superuser:
        filters.append(MarketplaceApp.visibility == "public")
        filters.append(MarketplaceApp.state == "approved")
    # Federated apps the upstream hub deleted (or asked us to deactivate)
    # should disappear from browse for everyone — even superusers — to
    # avoid surfacing tombstoned rows that no longer have a live upstream.
    # Owner-direct lookups via /{app_id} still resolve since we only filter
    # the list endpoint here.
    filters.append(MarketplaceApp.deleted_upstream.is_(False))
    if q:
        pat = f"%{q}%"
        filters.append(or_(MarketplaceApp.name.ilike(pat), MarketplaceApp.slug.ilike(pat)))
    if category:
        filters.append(MarketplaceApp.category == category)
    if creator_user_id:
        filters.append(MarketplaceApp.creator_user_id == creator_user_id)
    if source_id_filter is not None:
        filters.append(MarketplaceApp.source_id == source_id_filter)

    for f in filters:
        stmt = stmt.where(f)
        count_stmt = count_stmt.where(f)

    total = (await db.execute(count_stmt)).scalar_one()
    stmt = stmt.order_by(MarketplaceApp.created_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()

    sources = await _bulk_load_sources(db, {r.source_id for r in rows})
    items = [
        _attach_source_meta(
            MarketplaceAppResponse.model_validate(r), sources, r.source_id
        )
        for r in rows
    ]
    return AppListEnvelope(
        items=items,
        total=int(total),
        limit=limit,
        offset=offset,
    )


@router.get("/{app_id}", response_model=MarketplaceAppResponse)
async def get_app(
    app_id: UUID,
    source: str | None = Query(
        None,
        description=(
            "Optional source-handle scope. When supplied, returns 404 if "
            "the app was synced from a different source — prevents a "
            "deep-link from one hub from leaking into another's view."
        ),
    ),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> MarketplaceAppResponse:
    source_id_filter = await _resolve_source_filter(db, source)

    stmt = select(MarketplaceApp).where(MarketplaceApp.id == app_id)
    if source_id_filter is not None:
        stmt = stmt.where(MarketplaceApp.source_id == source_id_filter)

    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="app not found")
    if not await _user_can_see_app(db, row, user):
        raise HTTPException(status_code=404, detail="app not found")

    sources = await _bulk_load_sources(db, {row.source_id})
    return _attach_source_meta(
        MarketplaceAppResponse.model_validate(row), sources, row.source_id
    )


@router.get("/{app_id}/versions", response_model=AppVersionListEnvelope)
async def list_app_versions(
    app_id: UUID,
    source: str | None = Query(
        None,
        description=(
            "Optional source-handle scope. Returns 404 when the app's "
            "source_id does not match the requested handle."
        ),
    ),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> AppVersionListEnvelope:
    source_id_filter = await _resolve_source_filter(db, source)

    app_stmt = select(MarketplaceApp).where(MarketplaceApp.id == app_id)
    if source_id_filter is not None:
        app_stmt = app_stmt.where(MarketplaceApp.source_id == source_id_filter)
    app_row = (await db.execute(app_stmt)).scalar_one_or_none()
    if app_row is None:
        raise HTTPException(status_code=404, detail="app not found")
    if not await _user_can_see_app(db, app_row, user):
        raise HTTPException(status_code=404, detail="app not found")

    is_owner_or_admin = user.is_superuser or app_row.creator_user_id == user.id

    stmt = select(AppVersion).where(AppVersion.app_id == app_id)
    count_stmt = select(func.count()).select_from(AppVersion).where(AppVersion.app_id == app_id)
    if not is_owner_or_admin:
        stmt = stmt.where(
            AppVersion.approval_state.in_(("stage1_approved", "stage2_approved")),
            AppVersion.yanked_at.is_(None),
        )
        count_stmt = count_stmt.where(
            AppVersion.approval_state.in_(("stage1_approved", "stage2_approved")),
            AppVersion.yanked_at.is_(None),
        )

    total = (await db.execute(count_stmt)).scalar_one()
    stmt = stmt.order_by(AppVersion.created_at.desc()).limit(limit).offset(offset)
    rows = (await db.execute(stmt)).scalars().all()
    return AppVersionListEnvelope(
        items=[AppVersionSummary.model_validate(r) for r in rows],
        total=int(total),
        limit=limit,
        offset=offset,
    )


@router.post(
    "/{app_id}/fork",
    response_model=ForkResponse,
    status_code=status.HTTP_201_CREATED,
)
async def fork_marketplace_app(
    app_id: UUID,
    payload: ForkRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
    hub_client: HubClient = Depends(_get_hub_client),
) -> ForkResponse:
    # Ensure the source version belongs to the declared app (caller-supplied
    # source_app_version_id is the authoritative fork root per service API).
    src = (
        await db.execute(select(AppVersion).where(AppVersion.id == payload.source_app_version_id))
    ).scalar_one_or_none()
    if src is None or src.app_id != app_id:
        raise HTTPException(status_code=404, detail="source app_version not found for app")

    # Wave 7: refuse to fork an app from a source whose trust level is below
    # the install gate. Forking is a stand-in install (it copies the bundle
    # into a new project under the user's ownership), so the same trust
    # gating applies — otherwise community-hub apps could be installed by
    # round-tripping through fork.
    parent_app = (
        await db.execute(select(MarketplaceApp).where(MarketplaceApp.id == app_id))
    ).scalar_one_or_none()
    if parent_app is None:
        raise HTTPException(status_code=404, detail="app not found")

    if parent_app.source_id is not None:
        source = (
            await db.execute(
                select(MarketplaceSource).where(MarketplaceSource.id == parent_app.source_id)
            )
        ).scalar_one_or_none()
        if source is not None:
            decision = install_guard(source, "app", requester_user_id=user.id)
            if not decision.allowed:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "error": "install_blocked",
                        "reason": decision.reason,
                        "source_handle": source.handle,
                        "kind": "app",
                    },
                )

    try:
        result = await fork_app(
            db,
            forker_user_id=user.id,
            source_app_version_id=payload.source_app_version_id,
            new_slug=payload.new_slug,
            new_name=payload.new_name,
            team_id=payload.team_id,
            hub_client=hub_client,
        )
        await db.commit()
    except NotForkableError as e:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ForkError as e:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(e)) from e

    new_app = (
        await db.execute(select(MarketplaceApp).where(MarketplaceApp.id == result.new_app_id))
    ).scalar_one()
    sources = await _bulk_load_sources(db, {new_app.source_id})
    base = _attach_source_meta(
        MarketplaceAppResponse.model_validate(new_app), sources, new_app.source_id
    )
    return ForkResponse(
        **base.model_dump(),
        project_id=result.project_id,
        project_slug=result.project_slug,
    )


# ---------------------------------------------------------------------------
# Wave 9 — paid-app purchase routing via dispatch_purchase
# ---------------------------------------------------------------------------


class AppPurchaseResponse(BaseModel):
    """Outcome of POST /marketplace/apps/{app_id}/purchase.

    Mirrors the shape returned by ``dispatch_purchase``; routers don't
    insert any AppInstance row here — that lands when the install
    endpoint or the entitlements webhook fires after Stripe redirects
    the user back. This endpoint is purely "give me the URL".
    """

    action: str  # "free_install" | "hub_checkout" | "orchestrator_stripe" | "refused"
    checkout_url: str | None = None
    session_id: str | None = None
    via: str | None = None
    reason: str | None = None
    source_handle: str | None = None
    app_id: UUID
    app_slug: str


@router.post("/{app_id}/purchase", response_model=AppPurchaseResponse)
async def purchase_app(
    app_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> AppPurchaseResponse:
    """Wave-9 — gate paid-app installs through ``dispatch_purchase``.

    For free apps, returns ``free_install`` immediately so the client
    proceeds to ``POST /api/app-installs/install`` for the existing
    installer flow. For paid apps, the federation dispatcher picks
    between hub-owned Stripe Connect checkout (rule 1), the
    orchestrator-owned Stripe path (rule 2), or refusal (rule 3).
    """
    app_row = (
        await db.execute(select(MarketplaceApp).where(MarketplaceApp.id == app_id))
    ).scalar_one_or_none()
    if app_row is None:
        raise HTTPException(status_code=404, detail="app not found")

    src: MarketplaceSource | None = None
    if app_row.source_id is not None:
        src = (
            await db.execute(
                select(MarketplaceSource).where(MarketplaceSource.id == app_row.source_id)
            )
        ).scalar_one_or_none()

    # Pull pricing provenance from the federation cache. Apps don't
    # carry pricing on the model itself today; the sync worker stashes
    # the upstream pricing payload in ``source_pricing_payload_original``
    # for trusted sources and strips effective price to free for the
    # rest. Honour ``source_pricing_ignored`` so stripped sources never
    # accidentally route through paid checkout.
    pricing_payload: dict[str, Any] = {"pricing_type": "free"}
    if src is not None and not getattr(app_row, "source_pricing_ignored", False):
        raw = getattr(app_row, "source_pricing_payload_original", None)
        if isinstance(raw, dict):
            pricing_payload = dict(raw)
        # The sync worker mirrors `pricing_type` separately so a typed
        # field is always present even when payload is empty.
        if app_row.source_pricing_type_original:
            pricing_payload.setdefault("pricing_type", app_row.source_pricing_type_original)

    item: dict[str, Any] = {
        "kind": "app",
        "slug": app_row.slug,
        "pricing": pricing_payload,
    }

    origin = (
        request.headers.get("origin")
        or request.headers.get("referer", "").rstrip("/").split("?")[0].rsplit("/", 1)[0]
        or get_settings().get_app_base_url
    )
    success_url = (
        f"{origin}/marketplace/apps/{app_row.slug}/purchase/success"
        f"?session_id={{CHECKOUT_SESSION_ID}}"
    )
    cancel_url = f"{origin}/marketplace/apps/{app_row.slug}"

    decrypted_token: str | None = None
    if src is not None and src.encrypted_token:
        try:
            from ..services.credential_manager import get_credential_manager

            decrypted_token = (
                get_credential_manager().decrypt_token(src.encrypted_token) or None
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "purchase_app: failed to decrypt source token for source=%s",
                src.handle,
            )

    if src is None:
        # Pre-Wave-1 backfill safety: rows with no source can't dispatch;
        # treat as free (legacy app rows were always installable).
        return AppPurchaseResponse(
            action="free_install",
            via="legacy_no_source",
            app_id=app_row.id,
            app_slug=app_row.slug,
        )

    action = await dispatch_purchase(
        src,
        kind="app",
        slug=app_row.slug,
        version=None,
        requester=user,
        item=item,
        success_url=success_url,
        cancel_url=cancel_url,
        decrypted_token=decrypted_token,
    )

    if action["action"] == "refused":
        # Surface as 402 so the client UI can render the
        # pricing-not-supported banner. Same shape as the agents path.
        raise HTTPException(
            status_code=402,
            detail={
                "error": "pricing_not_supported",
                "reason": action.get("reason", "pricing_not_supported"),
                "source_handle": src.handle,
                "kind": "app",
                "slug": app_row.slug,
            },
        )

    return AppPurchaseResponse(
        action=action["action"],
        checkout_url=action.get("checkout_url"),
        session_id=action.get("session_id"),
        via=action.get("via"),
        reason=action.get("reason"),
        source_handle=action.get("source_handle") or src.handle,
        app_id=app_row.id,
        app_slug=app_row.slug,
    )
