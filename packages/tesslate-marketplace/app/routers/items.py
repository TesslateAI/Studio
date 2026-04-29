"""
Catalog read endpoints — items, versions, bundles, attestations.

Bundles are served via the local CAS adapter using HMAC-signed URLs that
point back at this service. The download endpoint (`GET /v1/bundles/...`)
verifies the signature before streaming the bytes.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import KINDS, Settings, get_settings
from ..database import get_session
from ..models import Bundle, Item, ItemVersion
from ..schemas import (
    AttestationEnvelope,
    BundleEnvelope,
    ItemDetail,
    ItemList,
    ItemSummary,
    ItemVersionOut,
    PricingPayload,
)
from ..services.capability_router import requires_capability
from ..services.cas import LocalBundleStorage, get_bundle_storage
from ..services.install_check import validate_archive_format, validate_bundle_size
from ..services.sync_helpers import clamp_limit, decode_cursor, encode_cursor

router = APIRouter(prefix="/v1", tags=["items"])


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _pricing_from_item(item: Item) -> PricingPayload:
    payload = item.pricing_payload or {}
    return PricingPayload(
        pricing_type=item.pricing_type or payload.get("pricing_type", "free"),
        price_cents=item.price_cents or payload.get("price_cents", 0),
        currency=payload.get("currency", "usd"),
        stripe_price_id=item.stripe_price_id or payload.get("stripe_price_id"),
        interval=payload.get("interval"),
        extras=payload.get("extras"),
    )


def _pricing_from_version(version: ItemVersion, fallback: Item) -> PricingPayload:
    if version.pricing_type or version.price_cents or version.stripe_price_id:
        return PricingPayload(
            pricing_type=version.pricing_type or fallback.pricing_type,
            price_cents=version.price_cents or 0,
            currency="usd",
            stripe_price_id=version.stripe_price_id,
        )
    return _pricing_from_item(fallback)


def _to_summary(item: Item) -> ItemSummary:
    return ItemSummary(
        id=str(item.id),
        kind=item.kind,
        slug=item.slug,
        name=item.name,
        description=item.description,
        category=item.category,
        icon=item.icon,
        avatar_url=item.avatar_url,
        is_active=item.is_active,
        is_featured=item.is_featured,
        is_published=item.is_published,
        pricing=_pricing_from_item(item),
        tags=list(item.tags or []),
        rating=item.rating,
        reviews_count=item.reviews_count,
        downloads=item.downloads,
        install_count=item.install_count,
        latest_version=item.latest_version,
        creator_handle=item.creator_handle,
        updated_at=item.updated_at,
    )


def _to_detail(item: Item, versions: list[ItemVersion]) -> ItemDetail:
    summary = _to_summary(item)
    detail = ItemDetail(
        **summary.model_dump(),
        long_description=item.long_description,
        features=list(item.features or []),
        tech_stack=list(item.tech_stack or []),
        extra_metadata=dict(item.extra_metadata or {}),
        homepage_url=item.homepage_url,
        git_repo_url=item.git_repo_url,
        versions=[_to_version(v, item) for v in versions],
    )
    return detail


def _to_version(version: ItemVersion, item: Item) -> ItemVersionOut:
    return ItemVersionOut(
        id=str(version.id),
        version=version.version,
        changelog=version.changelog,
        is_yanked=version.is_yanked,
        yanked_at=version.yanked_at,
        yank_reason=version.yank_reason,
        yank_severity=version.yank_severity,
        is_published=version.is_published,
        pricing=_pricing_from_version(version, item),
        manifest=version.manifest,
        created_at=version.created_at,
    )


# ---------------------------------------------------------------------------
# List + detail
# ---------------------------------------------------------------------------


def _validate_kind(kind: str | None) -> None:
    if kind is not None and kind not in KINDS:
        raise HTTPException(
            status_code=400, detail={"error": "unknown_kind", "kind": kind, "allowed": list(KINDS)}
        )


@router.get("/items", response_model=ItemList)
@requires_capability("catalog.read")
async def list_items(
    kind: str | None = Query(None),
    category: str | None = Query(None),
    q: str | None = Query(None, alias="q"),
    cursor: str | None = Query(None),
    limit: int | None = Query(None),
    sort: str | None = Query(None),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ItemList:
    _validate_kind(kind)
    page_limit = clamp_limit(limit, settings.pagination_default_limit, settings.pagination_max_limit)

    stmt = select(Item).where(Item.is_active.is_(True), Item.is_published.is_(True))
    if kind:
        stmt = stmt.where(Item.kind == kind)
    if category:
        stmt = stmt.where(Item.category == category)
    if q:
        # `catalog.search` capability gate — when disabled we fall back to a
        # simple substring filter so cache-fed clients keep working.
        if "catalog.search" in settings.capabilities:
            term = f"%{q.lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Item.name).like(term),
                    func.lower(func.coalesce(Item.description, "")).like(term),
                )
            )
        else:
            term = f"%{q.lower()}%"
            stmt = stmt.where(func.lower(Item.name).like(term))

    sort_key = (sort or "featured").lower()
    if sort_key == "newest":
        stmt = stmt.order_by(desc(Item.created_at), desc(Item.id))
    elif sort_key == "popular":
        stmt = stmt.order_by(desc(Item.downloads), desc(Item.id))
    elif sort_key == "name":
        stmt = stmt.order_by(asc(Item.name), asc(Item.id))
    elif sort_key == "rating":
        stmt = stmt.order_by(desc(Item.rating), desc(Item.id))
    else:
        # featured-first then newest
        stmt = stmt.order_by(desc(Item.is_featured), desc(Item.created_at), desc(Item.id))

    cursor_payload = decode_cursor(cursor)
    after_id = cursor_payload.get("after_id")
    if after_id:
        # Cursor encodes the last-seen id; re-issue the same sort and skip
        # rows where id <= after_id (works with the secondary id sort key).
        stmt = stmt.where(Item.id > after_id) if sort_key == "name" else stmt.where(Item.id != after_id)

    # We paginate one extra row to determine `has_more`.
    rows = (await db.execute(stmt.limit(page_limit + 1))).scalars().all()
    has_more = len(rows) > page_limit
    rows = rows[:page_limit]

    next_cursor = None
    if has_more and rows:
        next_cursor = encode_cursor({"after_id": str(rows[-1].id)})

    return ItemList(
        items=[_to_summary(r) for r in rows],
        next_cursor=next_cursor,
        has_more=has_more,
    )


async def _load_item_or_404(db: AsyncSession, kind: str, slug: str) -> Item:
    _validate_kind(kind)
    result = await db.execute(select(Item).where(Item.kind == kind, Item.slug == slug))
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail={"error": "item_not_found", "kind": kind, "slug": slug})
    return item


@router.get("/items/{kind}/{slug}", response_model=ItemDetail)
@requires_capability("catalog.read")
async def get_item(
    kind: str,
    slug: str,
    db: AsyncSession = Depends(get_session),
) -> ItemDetail:
    item = await _load_item_or_404(db, kind, slug)
    versions = (
        await db.execute(
            select(ItemVersion)
            .where(ItemVersion.item_id == item.id)
            .order_by(desc(ItemVersion.created_at))
        )
    ).scalars().all()
    return _to_detail(item, list(versions))


@router.get("/items/{kind}/{slug}/versions", response_model=list[ItemVersionOut])
@requires_capability("catalog.read")
async def list_versions(
    kind: str,
    slug: str,
    db: AsyncSession = Depends(get_session),
) -> list[ItemVersionOut]:
    item = await _load_item_or_404(db, kind, slug)
    versions = (
        await db.execute(
            select(ItemVersion)
            .where(ItemVersion.item_id == item.id)
            .order_by(desc(ItemVersion.created_at))
        )
    ).scalars().all()
    return [_to_version(v, item) for v in versions]


@router.get("/items/{kind}/{slug}/versions/{version}", response_model=ItemVersionOut)
@requires_capability("catalog.read")
async def get_version(
    kind: str,
    slug: str,
    version: str,
    db: AsyncSession = Depends(get_session),
) -> ItemVersionOut:
    item = await _load_item_or_404(db, kind, slug)
    result = await db.execute(
        select(ItemVersion).where(ItemVersion.item_id == item.id, ItemVersion.version == version)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "version_not_found", "kind": kind, "slug": slug, "version": version},
        )
    return _to_version(row, item)


# ---------------------------------------------------------------------------
# Bundles
# ---------------------------------------------------------------------------


async def _bundle_for(db: AsyncSession, item: Item, version: str) -> tuple[ItemVersion, Bundle]:
    result = await db.execute(
        select(ItemVersion).where(ItemVersion.item_id == item.id, ItemVersion.version == version)
    )
    iv = result.scalar_one_or_none()
    if iv is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "version_not_found", "kind": item.kind, "slug": item.slug, "version": version},
        )
    if iv.is_yanked:
        raise HTTPException(
            status_code=410,
            detail={
                "error": "version_yanked",
                "kind": item.kind,
                "slug": item.slug,
                "version": version,
                "reason": iv.yank_reason,
                "severity": iv.yank_severity,
            },
        )
    bundle_result = await db.execute(select(Bundle).where(Bundle.item_version_id == iv.id))
    bundle = bundle_result.scalar_one_or_none()
    if bundle is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "bundle_not_available", "kind": item.kind, "slug": item.slug, "version": version},
        )
    return iv, bundle


def _envelope_for(
    item: Item, version: ItemVersion, bundle: Bundle, settings: Settings
) -> BundleEnvelope:
    storage = get_bundle_storage(settings)
    if isinstance(storage, LocalBundleStorage) or hasattr(storage, "signed_url"):
        url, expires_epoch = storage.signed_url(item.kind, item.slug, version.version, bundle.storage_key)
    else:  # pragma: no cover - covered by adapter-specific tests
        raise HTTPException(status_code=500, detail={"error": "storage_backend_misconfigured"})

    validate_archive_format(bundle.archive_format)
    validate_bundle_size(item.kind, bundle.size_bytes)

    attestation = None
    if bundle.attestation_signature and bundle.attestation_key_id and bundle.attestation_algorithm:
        attestation = AttestationEnvelope(
            signature=bundle.attestation_signature,
            key_id=bundle.attestation_key_id,
            algorithm=bundle.attestation_algorithm,
        )

    return BundleEnvelope(
        url=url,
        sha256=bundle.sha256,
        size_bytes=bundle.size_bytes,
        content_type=bundle.content_type,
        archive_format=bundle.archive_format,
        expires_at=datetime.fromtimestamp(expires_epoch, tz=timezone.utc),
        attestation=attestation,
    )


@router.get("/items/{kind}/{slug}/versions/{version}/bundle", response_model=BundleEnvelope)
@requires_capability("bundles.signed_url")
async def get_bundle(
    kind: str,
    slug: str,
    version: str,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> BundleEnvelope:
    item = await _load_item_or_404(db, kind, slug)
    iv, bundle = await _bundle_for(db, item, version)
    return _envelope_for(item, iv, bundle, settings)


@router.get("/items/{kind}/{slug}/versions/{version}/attestation", response_model=AttestationEnvelope)
@requires_capability("attestations")
async def get_attestation(
    kind: str,
    slug: str,
    version: str,
    db: AsyncSession = Depends(get_session),
) -> AttestationEnvelope:
    item = await _load_item_or_404(db, kind, slug)
    iv, bundle = await _bundle_for(db, item, version)
    if not bundle.attestation_signature:
        raise HTTPException(
            status_code=404,
            detail={"error": "attestation_not_available", "kind": kind, "slug": slug, "version": version},
        )
    return AttestationEnvelope(
        signature=bundle.attestation_signature,
        key_id=bundle.attestation_key_id or "",
        algorithm=bundle.attestation_algorithm or "ed25519",
    )


# ---------------------------------------------------------------------------
# Local CAS download endpoint — verified by HMAC signature
# ---------------------------------------------------------------------------


@router.get("/bundles/{kind}/{slug}/{version}")
async def download_bundle(
    kind: str,
    slug: str,
    version: str,
    request: Request,
    sig: str = Query(...),
    exp: int = Query(...),
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    storage = get_bundle_storage(settings)
    if not isinstance(storage, LocalBundleStorage):
        # When using S3 / Volume Hub the URLs point straight at the backend;
        # this endpoint is only meaningful for the local adapter.
        raise HTTPException(
            status_code=404,
            detail={"error": "bundle_endpoint_not_available_for_backend", "backend": storage.backend_name},
        )
    if not storage.verify_signed_url(kind, slug, version, exp, sig):
        raise HTTPException(status_code=403, detail={"error": "invalid_or_expired_signature"})

    item = await _load_item_or_404(db, kind, slug)
    _, bundle = await _bundle_for(db, item, version)

    file_handle = storage.open_stream(bundle.storage_key)

    def _iter():
        try:
            while True:
                chunk = file_handle.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            file_handle.close()

    headers = {
        "Content-Length": str(bundle.size_bytes),
        "X-Tesslate-Bundle-Sha256": bundle.sha256,
        "X-Tesslate-Bundle-Archive-Format": bundle.archive_format,
    }
    return StreamingResponse(_iter(), media_type=bundle.content_type, headers=headers)


__all__ = ["router"]
