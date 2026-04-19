"""App bundles service — creator-curated collections of AppVersions.

A bundle groups multiple AppVersions that install together as a single
unit. The `consolidated_manifest_hash` is order-independent (sorted member
hashes) to enable dedup across semantically identical bundles.

Scope: draft → approved | yanked transitions, plus read helper. Router
layer is responsible for authz (admin gate on publish / yank).
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...models import AppBundle, AppBundleItem, AppVersion

__all__ = [
    "BundleError",
    "BundleNotFoundError",
    "BundleSlugTakenError",
    "BundleItemSpec",
    "create_bundle",
    "publish_bundle",
    "yank_bundle",
    "get_bundle",
]

logger = logging.getLogger(__name__)


class BundleError(Exception):
    """Base class for bundle service errors."""


class BundleNotFoundError(BundleError):
    """No AppBundle row with the given id."""


class BundleSlugTakenError(BundleError):
    """Slug already in use by another bundle."""


_APPROVED_AV_STATES = {"stage1_approved", "stage2_approved"}


@dataclass(frozen=True)
class BundleItemSpec:
    app_version_id: UUID
    order_index: int = 0
    default_enabled: bool = True
    required: bool = False


def _consolidated_hash(member_hashes: list[str]) -> str:
    """Order-independent sha256 over sorted member manifest_hashes."""
    h = hashlib.sha256()
    for mh in sorted(member_hashes):
        h.update(mh.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


async def create_bundle(
    db: AsyncSession,
    *,
    owner_user_id: UUID,
    slug: str,
    display_name: str,
    items: list[BundleItemSpec],
    summary: str | None = None,
    description: str | None = None,
) -> UUID:
    """Insert AppBundle + AppBundleItem rows in one transaction."""
    if not items:
        raise BundleError("bundle must contain at least one item")

    av_ids = [it.app_version_id for it in items]
    rows = (
        await db.execute(
            select(AppVersion.id, AppVersion.manifest_hash).where(AppVersion.id.in_(av_ids))
        )
    ).all()
    found = {row.id: row.manifest_hash for row in rows}
    missing = [str(i) for i in av_ids if i not in found]
    if missing:
        raise BundleError(f"unknown app_version_id(s): {missing}")

    consolidated = _consolidated_hash([found[i] for i in av_ids])

    bundle_id = uuid.uuid4()
    bundle = AppBundle(
        id=bundle_id,
        slug=slug,
        owner_user_id=owner_user_id,
        display_name=display_name,
        summary=summary,
        description=description,
        status="draft",
        consolidated_manifest_hash=consolidated,
    )
    db.add(bundle)

    for it in items:
        db.add(
            AppBundleItem(
                id=uuid.uuid4(),
                bundle_id=bundle_id,
                app_version_id=it.app_version_id,
                order_index=it.order_index,
                default_enabled=it.default_enabled,
                required=it.required,
            )
        )

    try:
        await db.flush()
    except IntegrityError as e:
        if "app_bundles_slug_key" in str(e.orig) or "slug" in str(e.orig).lower():
            raise BundleSlugTakenError(slug) from e
        raise

    return bundle_id


async def _load_bundle(db: AsyncSession, bundle_id: UUID) -> AppBundle:
    row = (
        await db.execute(select(AppBundle).where(AppBundle.id == bundle_id).with_for_update())
    ).scalar_one_or_none()
    if row is None:
        raise BundleNotFoundError(str(bundle_id))
    return row


async def publish_bundle(
    db: AsyncSession,
    *,
    bundle_id: UUID,
    actor_user_id: UUID,
) -> None:
    """Transition draft → approved iff every member AV is approved."""
    bundle = await _load_bundle(db, bundle_id)
    if bundle.status == "approved":
        return
    if bundle.status == "yanked":
        raise BundleError("cannot publish a yanked bundle")

    states = (
        (
            await db.execute(
                select(AppVersion.approval_state)
                .join(AppBundleItem, AppBundleItem.app_version_id == AppVersion.id)
                .where(AppBundleItem.bundle_id == bundle_id)
            )
        )
        .scalars()
        .all()
    )

    if not states:
        raise BundleError("bundle has no items")
    if any(s not in _APPROVED_AV_STATES for s in states):
        raise BundleError("cannot publish bundle with unapproved items")

    bundle.status = "approved"
    bundle.updated_at = datetime.now(tz=UTC)
    await db.flush()
    logger.info("bundle.publish bundle_id=%s actor=%s", bundle_id, actor_user_id)


async def yank_bundle(
    db: AsyncSession,
    *,
    bundle_id: UUID,
    actor_user_id: UUID,
    reason: str,
) -> None:
    """Idempotent transition to 'yanked'."""
    bundle = await _load_bundle(db, bundle_id)
    if bundle.status == "yanked":
        return
    bundle.status = "yanked"
    bundle.updated_at = datetime.now(tz=UTC)
    await db.flush()
    logger.info(
        "bundle.yank bundle_id=%s actor=%s reason=%s",
        bundle_id,
        actor_user_id,
        reason,
    )


async def get_bundle(db: AsyncSession, *, bundle_id: UUID) -> dict:
    """Fetch bundle header + ordered item list."""
    bundle = (
        await db.execute(select(AppBundle).where(AppBundle.id == bundle_id))
    ).scalar_one_or_none()
    if bundle is None:
        raise BundleNotFoundError(str(bundle_id))

    items = (
        (
            await db.execute(
                select(AppBundleItem)
                .where(AppBundleItem.bundle_id == bundle_id)
                .order_by(AppBundleItem.order_index)
            )
        )
        .scalars()
        .all()
    )

    return {
        "id": bundle.id,
        "slug": bundle.slug,
        "display_name": bundle.display_name,
        "status": bundle.status,
        "consolidated_manifest_hash": bundle.consolidated_manifest_hash,
        "items": [
            {
                "app_version_id": it.app_version_id,
                "order_index": it.order_index,
                "default_enabled": it.default_enabled,
                "required": it.required,
            }
            for it in items
        ],
    }
