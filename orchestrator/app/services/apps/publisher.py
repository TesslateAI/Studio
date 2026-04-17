"""App publisher — promotes an `app_source` Project into a new AppVersion.

Flow (single transaction):
    parse manifest -> compat check -> load/assert project -> get-or-create
    MarketplaceApp -> guard duplicate version -> publish bundle via Hub ->
    insert AppVersion (pending_stage1) -> insert AppSubmission (stage0).

This module is pure orchestration: no router, no background task. Callers
(router, worker, CLI) are responsible for `await db.commit()` after the call.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ... import config_features
from ...models import AppSubmission, AppVersion, MarketplaceApp, Project
from ...utils.slug_generator import slugify
from ..hub_client import HubClient
from . import compatibility
from .manifest_parser import ManifestValidationError, parse as parse_manifest

__all__ = [
    "PublishError",
    "DuplicateVersionError",
    "CompatibilityError",
    "SourceNotPublishableError",
    "PublishResult",
    "publish_version",
]

logger = logging.getLogger(__name__)


class PublishError(Exception):
    """Base for publish-time failures."""


class DuplicateVersionError(PublishError):
    """(app_id, version) already exists in app_versions, or slug is taken."""


class CompatibilityError(PublishError):
    """Manifest declares features this deployment doesn't support."""

    def __init__(self, message: str, report: compatibility.CompatReport) -> None:
        super().__init__(message)
        self.report = report


class SourceNotPublishableError(PublishError):
    """Source Project can't be published (wrong role, no volume, etc.)."""


@dataclass(frozen=True)
class PublishResult:
    app_id: UUID
    app_version_id: UUID
    version: str
    bundle_hash: str
    manifest_hash: str
    submission_id: UUID


async def publish_version(
    db: AsyncSession,
    *,
    creator_user_id: UUID,
    project_id: UUID,
    manifest_source: str | bytes | dict[str, Any],
    hub_client: HubClient,
    app_id: UUID | None = None,
) -> PublishResult:
    # 1) Parse + typed-validate manifest.
    try:
        parsed = parse_manifest(manifest_source)
    except ManifestValidationError:
        logger.info("publish_version: manifest validation failed")
        raise
    manifest = parsed.manifest
    # For schema versions without a typed Pydantic mirror (e.g. 2025-02),
    # read directly from the raw validated dict. All required keys are
    # guaranteed present by JSON Schema validation in parse_manifest.
    raw = parsed.raw
    app_dict = raw.get("app") or {}
    compat_dict = raw.get("compatibility") or {}
    listing_dict = raw.get("listing") or {}
    version_str = (manifest.app.version if manifest else app_dict.get("version")) or ""
    if not version_str:
        raise PublishError("manifest.app.version must be non-empty")
    required_features = (
        list(manifest.compatibility.required_features) if manifest
        else list(compat_dict.get("required_features") or [])
    )
    manifest_schema_str = (
        manifest.compatibility.manifest_schema if manifest
        else compat_dict.get("manifest_schema", "")
    )
    manifest_schema_version = (
        manifest.manifest_schema_version if manifest
        else raw.get("manifest_schema_version", "")
    )

    # 2) Compat check vs server feature set.
    report = compatibility.check(
        required_features=required_features,
        manifest_schema=manifest_schema_str,
    )
    if not report.compatible:
        raise CompatibilityError(
            f"manifest incompatible with server: missing={report.missing_features} "
            f"unsupported_schema={report.unsupported_manifest_schema}",
            report,
        )

    # 3) Load + validate source project.
    project = (
        await db.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if project is None:
        raise SourceNotPublishableError(f"project {project_id} not found")
    if project.app_role != "app_source":
        raise SourceNotPublishableError(
            f"project {project_id} has app_role={project.app_role!r}, expected 'app_source'"
        )
    if not project.volume_id:
        raise SourceNotPublishableError(
            f"project {project_id} has no volume_id; provision storage before publishing"
        )

    # 4) Get-or-create MarketplaceApp.
    if app_id is None:
        # First publish — create the hub row.
        app_slug = (manifest.app.slug if manifest else app_dict.get("slug")) or ""
        app_name = (manifest.app.name if manifest else app_dict.get("name")) or ""
        # Auto-derive handle from slug; (creator_user_id, handle) unique
        # constraint catches in-creator duplicates via IntegrityError below.
        from .reserved_handles import is_reserved as _is_reserved_handle
        derived_handle = slugify(app_slug, max_length=48) if app_slug else ""
        if _is_reserved_handle(derived_handle):
            derived_handle = f"{derived_handle[:40]}-app"
        new_app = MarketplaceApp(
            slug=app_slug,
            name=app_name,
            handle=derived_handle or None,
            creator_user_id=creator_user_id,
            description=(manifest.app.description if manifest else app_dict.get("description")),
            category=(manifest.app.category if manifest else app_dict.get("category")),
            icon_ref=(manifest.app.icon_ref if manifest else app_dict.get("icon_ref")),
            forkable=(manifest.app.forkable if manifest else app_dict.get("forkable", "restricted")),
            visibility=(manifest.listing.visibility if manifest else listing_dict.get("visibility", "private")),
            state="draft",
        )
        db.add(new_app)
        try:
            await db.flush()
        except IntegrityError as e:
            await db.rollback()
            raise DuplicateVersionError(
                f"slug already taken: {app_slug!r}"
            ) from e
        app_row = new_app
    else:
        app_row = (
            await db.execute(select(MarketplaceApp).where(MarketplaceApp.id == app_id))
        ).scalar_one_or_none()
        if app_row is None:
            raise PublishError(f"MarketplaceApp {app_id} not found")
        if app_row.creator_user_id != creator_user_id:
            raise PublishError(
                f"user {creator_user_id} is not the creator of app {app_id}"
            )

    # 5) Guard duplicate (app_id, version).
    existing = (
        await db.execute(
            select(AppVersion.id).where(
                AppVersion.app_id == app_row.id, AppVersion.version == version_str
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise DuplicateVersionError(
            f"app {app_row.id} already has version {version_str!r}"
        )

    # 6) Publish bundle via Hub (CAS). Outside the DB round-trip loop.
    bundle_hash = await hub_client.publish_bundle(
        volume_id=project.volume_id,
        app_id=str(app_row.id),
        version=version_str,
    )

    # 7) Insert AppVersion.
    now = datetime.now(timezone.utc)
    manifest_hash = parsed.canonical_hash
    version_row = AppVersion(
        app_id=app_row.id,
        version=version_str,
        manifest_schema_version=manifest_schema_version,
        manifest_json=parsed.raw,
        manifest_hash=manifest_hash,
        bundle_hash=bundle_hash,
        feature_set_hash=config_features.feature_set_hash(),
        required_features=required_features,
        approval_state="pending_stage1",
        published_at=now,
    )
    from ._auto_approve_flag import is_auto_approve_enabled

    skip_approval = is_auto_approve_enabled()
    if skip_approval:
        version_row.approval_state = "stage1_approved"
        app_row.state = "approved"
        app_row.visibility = "public"
    db.add(version_row)
    try:
        await db.flush()
    except IntegrityError as e:
        await db.rollback()
        raise DuplicateVersionError(
            f"app {app_row.id} already has version {version_str!r}"
        ) from e

    # 8) Insert AppSubmission (stage0) for the approval pipeline.
    submission = AppSubmission(
        app_version_id=version_row.id,
        submitter_user_id=creator_user_id,
        stage="stage0",
    )
    db.add(submission)
    await db.flush()

    logger.info(
        "publish_version: app=%s version=%s bundle=%s submission=%s",
        app_row.id,
        version_str,
        bundle_hash[:16] if isinstance(bundle_hash, str) else bundle_hash,
        submission.id,
    )

    return PublishResult(
        app_id=app_row.id,
        app_version_id=version_row.id,
        version=version_str,
        bundle_hash=bundle_hash,
        manifest_hash=manifest_hash,
        submission_id=submission.id,
    )
