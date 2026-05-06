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
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ... import config_features
from ...models import (
    PROJECT_KIND_APP_SOURCE,
    AppSubmission,
    AppVersion,
    MarketplaceApp,
    Project,
)
from ...utils.slug_generator import slugify
from ..hub_client import HubClient
from ..marketplace_constants import LOCAL_SOURCE_ID
from . import compatibility
from .manifest_parser import ManifestValidationError
from .manifest_parser import parse as parse_manifest
from .manifest_parser import validate_result_templates

__all__ = [
    "PublishError",
    "DuplicateVersionError",
    "CompatibilityError",
    "SourceNotPublishableError",
    "PublishResult",
    "publish_version",
]

logger = logging.getLogger(__name__)


# Allowed values for MarketplaceApp.forkable (String(16) column documented as
# "true | restricted | no" in models.py).
_FORKABLE_STRING_VALUES = ("true", "restricted", "no")


def _coerce_forkable(raw_value: Any) -> str:
    """Normalize manifest.app.forkable to the column's string enum.

    2025-01 declares forkable as Literal["true","restricted","no"]; 2026-05
    declares it as bool. The DB column is the 2025-01 string enum, so we
    coerce here once at the publish boundary.

    True → "true", False → "no", a valid string passes through, everything
    else falls back to the conservative "restricted".
    """
    if isinstance(raw_value, bool):
        return "true" if raw_value else "no"
    if isinstance(raw_value, str) and raw_value in _FORKABLE_STRING_VALUES:
        return raw_value
    return "restricted"


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
    # Dry-render every action.result_template against the sandboxed
    # render worker. Catches RCE patterns (e.g. dunder-walks via
    # __class__.__mro__), unsafe filters/globals, syntax errors,
    # and runaway loops at publish time rather than at first invocation.
    try:
        await validate_result_templates(parsed)
    except ManifestValidationError:
        logger.info("publish_version: result_template validation failed")
        raise
    # All metadata reads go through the validated raw dict. The typed mirror
    # (parsed.manifest) varies in shape across schema versions — 2025-01
    # carries `compatibility` and `listing` blocks, 2026-05 dropped both —
    # so reading via the typed model couples the publisher to a specific
    # version. parse_manifest already validated structurally; raw access is
    # uniform across versions.
    raw = parsed.raw
    app_dict = raw.get("app") or {}
    compat_dict = raw.get("compatibility") or {}
    listing_dict = raw.get("listing") or {}

    version_str = app_dict.get("version") or ""
    if not version_str:
        raise PublishError("manifest.app.version must be non-empty")

    manifest_schema_version = raw.get("manifest_schema_version", "")
    # `compatibility.required_features` and `compatibility.manifest_schema`
    # exist in 2025-01 only. For 2026-05 the compatibility block is gone;
    # creators no longer declare runtime features per-manifest, and the
    # schema version itself is the gating signal we feed compatibility.check.
    required_features = list(compat_dict.get("required_features") or [])
    manifest_schema_str = (
        compat_dict.get("manifest_schema") or manifest_schema_version
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
    if project.project_kind != PROJECT_KIND_APP_SOURCE:
        raise SourceNotPublishableError(
            f"project {project_id} has project_kind={project.project_kind!r}, "
            f"expected 'app_source'"
        )
    if not project.volume_id:
        raise SourceNotPublishableError(
            f"project {project_id} has no volume_id; provision storage before publishing"
        )

    # 4) Get-or-create MarketplaceApp.
    if app_id is None:
        # First publish — create the hub row.
        app_slug = app_dict.get("slug") or ""
        if not app_slug:
            # 2026-05 made app.slug optional (creators only need to declare
            # the reverse-DNS app.id). Derive a slug from the id's last
            # segment so the unique-NOT-NULL column always has a value.
            raw_id = app_dict.get("id") or ""
            if raw_id:
                last_segment = raw_id.rsplit(".", 1)[-1]
                app_slug = slugify(last_segment, max_length=80)
        app_name = app_dict.get("name") or ""
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
            description=app_dict.get("description"),
            category=app_dict.get("category"),
            icon_ref=app_dict.get("icon_ref"),
            forkable=_coerce_forkable(app_dict.get("forkable")),
            # 2026-05 removed the listing block; defaulting to "private" is
            # the safest first-publish posture (creators promote via the
            # marketplace UI). 2025-01 manifests carry listing.visibility
            # explicitly, which lands here unchanged.
            visibility=listing_dict.get("visibility", "private"),
            state="draft",
            source_id=LOCAL_SOURCE_ID,
        )
        db.add(new_app)
        try:
            await db.flush()
        except IntegrityError as e:
            await db.rollback()
            raise DuplicateVersionError(f"slug already taken: {app_slug!r}") from e
        app_row = new_app
    else:
        app_row = (
            await db.execute(select(MarketplaceApp).where(MarketplaceApp.id == app_id))
        ).scalar_one_or_none()
        if app_row is None:
            raise PublishError(f"MarketplaceApp {app_id} not found")
        if app_row.creator_user_id != creator_user_id:
            raise PublishError(f"user {creator_user_id} is not the creator of app {app_id}")

    # 5) Guard duplicate (app_id, version).
    existing = (
        await db.execute(
            select(AppVersion.id).where(
                AppVersion.app_id == app_row.id, AppVersion.version == version_str
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise DuplicateVersionError(f"app {app_row.id} already has version {version_str!r}")

    # 6) Publish bundle via Hub (CAS). Outside the DB round-trip loop.
    bundle_hash = await hub_client.publish_bundle(
        volume_id=project.volume_id,
        app_id=str(app_row.id),
        version=version_str,
    )

    # 7) Insert AppVersion.
    now = datetime.now(UTC)
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
        source_id=app_row.source_id,
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
        raise DuplicateVersionError(f"app {app_row.id} already has version {version_str!r}") from e

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
