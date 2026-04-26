"""Publish-as-App endpoints — power the Architecture Canvas drawer.

Two endpoints:

* ``POST /api/projects/{slug}/publish-app/draft`` — read project structure and
  return a draft 2026-05 manifest plus a checklist describing what's ready and
  what needs the creator's attention. This is non-mutating: nothing is
  created, no marketplace row is touched.
* ``POST /api/projects/{slug}/publish-app`` — accept a (possibly creator-edited)
  manifest, re-validate it, and run it through the existing
  :func:`services.apps.publisher.publish_version` pipeline. The Project's
  ``project_kind`` is promoted to ``app_source`` on first successful publish.

Both endpoints require ``Permission.PROJECT_EDIT``. We intentionally reuse the
existing publisher so this router is just an ergonomic alias for the canvas
flow — the underlying logic (CAS bundle, AppSubmission, compatibility check,
result_template dry-render) is shared with the lower-level
``/api/app-versions/publish`` endpoint.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_db
from ..models import (
    PROJECT_KIND_APP_SOURCE,
    PROJECT_KIND_WORKSPACE,
    User,
)
from ..permissions import Permission
from ..services.apps.app_manifest import AppManifest2026_05
from ..services.apps.manifest_parser import (
    ManifestValidationError,
    parse as parse_manifest,
)
from ..services.apps.managed_resources import ManagedDbResult, add_postgres
from ..services.apps.publish_checker import (
    StateModelVerdict,
    check_state_model,
)
from ..services.apps.publish_inferrer import (
    ChecklistItem,
    find_existing_app_for_project,
    infer_draft,
)
from ..services.apps.publisher import (
    CompatibilityError,
    DuplicateVersionError,
    PublishError,
    SourceNotPublishableError,
    publish_version,
)
from ..services.hub_client import HubClient
from ..users import current_active_user

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Response / request schemas
# ---------------------------------------------------------------------------


class ChecklistItemResponse(BaseModel):
    id: str
    title: str
    status: str  # 'pass' | 'warn' | 'fail'
    detail: str
    fix_action: dict[str, Any] | None = None


class DraftResponse(BaseModel):
    yaml: str
    manifest: dict[str, Any]
    checklist: list[ChecklistItemResponse]
    # Hint for the drawer's "Republish" affordance.
    existing_app_id: str | None = None


class PublishRequest(BaseModel):
    # The user-edited manifest. Accepted as either a dict (parsed YAML/JSON)
    # or a YAML/JSON string — the publisher handles both.
    manifest: Any
    # Optional override for republish — the inferrer surfaces this in the
    # draft response, the drawer round-trips it.
    app_id: UUID | None = None


class PublishResponse(BaseModel):
    app_id: UUID
    app_version_id: UUID
    version: str
    bundle_hash: str
    manifest_hash: str
    submission_id: UUID
    marketplace_url: str | None = None


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


def _get_hub_client() -> HubClient:
    """Dependency factory — override in tests."""
    settings = get_settings()
    return HubClient(settings.volume_hub_address)


async def _get_project_for_edit(slug: str, db: AsyncSession, user: User):
    """Resolve the Project + RBAC for PROJECT_EDIT.

    Imported lazily here (not at module load) so the router stays cheap to
    import in test contexts where the projects router isn't registered.
    """
    from .projects import get_project_by_slug

    return await get_project_by_slug(db, slug, user, Permission.PROJECT_EDIT)


def _checklist_to_response(items: list[ChecklistItem]) -> list[ChecklistItemResponse]:
    return [
        ChecklistItemResponse(
            id=i.id,
            title=i.title,
            status=i.status,
            detail=i.detail,
            fix_action=i.fix_action,
        )
        for i in items
    ]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/projects/{slug}/publish-app/draft",
    response_model=DraftResponse,
)
async def publish_draft(
    slug: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> DraftResponse:
    """Infer a draft 2026-05 manifest + checklist for the given project."""
    project = await _get_project_for_edit(slug, db, user)
    result = await infer_draft(db, project=project)

    existing = await find_existing_app_for_project(db, project=project, user_id=user.id)

    return DraftResponse(
        yaml=result.yaml_str,
        manifest=result.parsed,
        checklist=_checklist_to_response(result.checklist),
        existing_app_id=str(existing.id) if existing else None,
    )


@router.post(
    "/projects/{slug}/publish-app",
    response_model=PublishResponse,
    status_code=status.HTTP_201_CREATED,
)
async def publish_app(
    slug: str,
    body: PublishRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
    hub_client: HubClient = Depends(_get_hub_client),
) -> PublishResponse:
    """Publish the project as a new AppVersion.

    The user-edited manifest is re-validated server-side via the publisher
    pipeline (which runs the JSON Schema check, the compatibility check, and
    the sandboxed result_template dry-render). On the first successful
    publish, ``project_kind`` is promoted from ``workspace`` → ``app_source``.
    """
    project = await _get_project_for_edit(slug, db, user)

    # Resolve republish target: the body's app_id wins; otherwise look up an
    # existing app owned by this user with the same derived slug.
    target_app_id: UUID | None = body.app_id
    if target_app_id is None:
        existing = await find_existing_app_for_project(
            db, project=project, user_id=user.id
        )
        if existing is not None:
            target_app_id = existing.id

    # Promote workspace → app_source so the publisher's source-validation
    # check passes (it requires project.project_kind == 'app_source'). We do
    # this *before* publish_version() opens its transaction so a failed
    # publish leaves the project in app_source mode (the user can retry the
    # publish without re-promoting). Workspaces only get promoted, never
    # demoted — once an app, always an app.
    if project.project_kind == PROJECT_KIND_WORKSPACE:
        project.project_kind = PROJECT_KIND_APP_SOURCE
        await db.flush()

    try:
        try:
            result = await publish_version(
                db,
                creator_user_id=user.id,
                project_id=project.id,
                manifest_source=body.manifest,
                hub_client=hub_client,
                app_id=target_app_id,
            )
            await db.commit()
        except ManifestValidationError as e:
            await db.rollback()
            raise HTTPException(
                status_code=422,
                detail={"message": "manifest invalid", "errors": e.errors},
            ) from e
        except SourceNotPublishableError as e:
            await db.rollback()
            raise HTTPException(status_code=422, detail=str(e)) from e
        except CompatibilityError as e:
            await db.rollback()
            raise HTTPException(status_code=422, detail=str(e)) from e
        except DuplicateVersionError as e:
            await db.rollback()
            raise HTTPException(status_code=409, detail=str(e)) from e
        except PublishError as e:
            await db.rollback()
            raise HTTPException(status_code=400, detail=str(e)) from e
    finally:
        close = getattr(hub_client, "close", None)
        if callable(close):
            try:
                await close()
            except Exception:  # pragma: no cover
                logger.debug("hub_client close failed", exc_info=True)

    # Best-effort marketplace URL for the drawer to deep-link to.
    marketplace_url = f"/marketplace/apps/{result.app_id}"

    return PublishResponse(
        app_id=result.app_id,
        app_version_id=result.app_version_id,
        version=result.version,
        bundle_hash=result.bundle_hash,
        manifest_hash=result.manifest_hash,
        submission_id=result.submission_id,
        marketplace_url=marketplace_url,
    )


# ---------------------------------------------------------------------------
# Per-Replica Safety endpoints (Phase 5)
# ---------------------------------------------------------------------------
#
# These two endpoints sit in front of the Publish Drawer's "Make scalable"
# section. They never mutate the marketplace — the upgrade route writes a
# K8s Secret + a manifest patch into the workspace, but no AppVersion / app
# row is touched. Wave 5A's publish flow above is the path that finalises
# any of this into a real publish.


class StateModelWarningOut(BaseModel):
    kind: str
    message: str
    detected_at: str


class UpgradeOfferOut(BaseModel):
    kind: str
    title: str
    description: str
    manifest_patch: dict[str, Any]


class StateModelVerdictOut(BaseModel):
    detected_state_model: str
    pinned_max_replicas: int
    warnings: list[StateModelWarningOut] = []
    upgrade_offers: list[UpgradeOfferOut] = []


class CheckRequest(BaseModel):
    """Optional manifest override for the checker.

    When omitted the route loads ``opensail.app.yaml`` from the workspace
    (or, when none exists yet, falls back to a stub that triggers the
    "unknown" branch — pin to 1, offer postgres). When supplied the
    Publish Drawer's in-memory draft is used verbatim.
    """

    manifest: Any | None = None


class CheckResponse(BaseModel):
    verdict: StateModelVerdictOut


class UpgradeAddPostgresResponse(BaseModel):
    secret_name: str
    secret_namespace: str
    manifest_patch: dict[str, Any]
    manifest_path: str | None
    migration_script_path: str | None
    is_stub_provisioner: bool
    notes: list[str]


async def _load_or_infer_manifest_for_check(
    project, override: Any | None
) -> AppManifest2026_05:
    """Resolve a 2026-05 manifest for the per-replica-safety check.

    Resolution order:
      1. Caller-supplied ``override`` (PublishDrawer's draft).
      2. ``opensail.app.yaml`` in the workspace.
      3. A stub manifest declaring ``state_model='per_install_volume'``,
         ``max_replicas=1``. The checker's "unknown evidence" branch then
         pins replicas to 1 and surfaces the postgres upgrade offer.
    """
    if override is not None:
        try:
            parsed = parse_manifest(override)
        except ManifestValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "manifest validation failed",
                    "errors": exc.errors,
                },
            ) from exc
        if not isinstance(parsed.manifest, AppManifest2026_05):
            raise HTTPException(
                status_code=422,
                detail=(
                    "manifest must be schema version 2026-05 for the publish-time "
                    "state-model checker"
                ),
            )
        return parsed.manifest

    # Try the workspace file.
    from pathlib import Path

    from ..utils.resource_naming import get_project_path

    manifest_path = (
        Path(get_project_path(project.owner_id, project.id)) / "opensail.app.yaml"
    )
    if manifest_path.exists():
        try:
            with manifest_path.open("r", encoding="utf-8") as f:
                source = f.read()
            parsed = parse_manifest(source)
            if isinstance(parsed.manifest, AppManifest2026_05):
                return parsed.manifest
        except ManifestValidationError as exc:
            logger.info(
                "publish-check: workspace opensail.app.yaml failed validation "
                "for project=%s: %s",
                project.id,
                exc,
            )
        except OSError as exc:
            logger.warning(
                "publish-check: failed to read %s: %r", manifest_path, exc
            )

    # Conservative fallback — see docstring.
    raw = {
        "manifest_schema_version": "2026-05",
        "app": {
            "id": "stub.local.unannotated",
            "name": "Unannotated draft",
            "version": "0.0.0",
        },
        "runtime": {
            "tenancy_model": "per_install",
            "state_model": "per_install_volume",
            "scaling": {"max_replicas": 1},
        },
        "billing": {
            "ai_compute": {"payer_default": "installer"},
            "general_compute": {"payer_default": "installer"},
            "platform_fee": {"rate_percent": 0, "model": "free"},
        },
    }
    return AppManifest2026_05.model_validate(raw)


def _verdict_to_schema(verdict: StateModelVerdict) -> StateModelVerdictOut:
    return StateModelVerdictOut(
        detected_state_model=verdict.detected_state_model,
        pinned_max_replicas=verdict.pinned_max_replicas,
        warnings=[
            StateModelWarningOut(
                kind=w.kind, message=w.message, detected_at=w.detected_at
            )
            for w in verdict.warnings
        ],
        upgrade_offers=[
            UpgradeOfferOut(
                kind=o.kind,
                title=o.title,
                description=o.description,
                manifest_patch=o.manifest_patch,
            )
            for o in verdict.upgrade_offers
        ],
    )


@router.post(
    "/projects/{slug}/publish-app/check",
    response_model=CheckResponse,
    summary="Run the per-replica safety check on a project",
)
async def publish_check(
    slug: str,
    payload: CheckRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> CheckResponse:
    """Return the state-model verdict for a project's draft manifest.

    Permission: PROJECT_EDIT. Idempotent — repeated calls are safe.
    """
    project = await _get_project_for_edit(slug, db, user)
    payload = payload or CheckRequest()
    manifest = await _load_or_infer_manifest_for_check(project, payload.manifest)
    verdict = await check_state_model(db, project=project, manifest=manifest)
    return CheckResponse(verdict=_verdict_to_schema(verdict))


@router.post(
    "/projects/{slug}/publish-app/upgrade/add-postgres",
    response_model=UpgradeAddPostgresResponse,
    summary="Provision per-app Postgres + patch the manifest",
)
async def upgrade_add_postgres(
    slug: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> UpgradeAddPostgresResponse:
    """Provision per-app Postgres and patch the workspace manifest.

    Permission: PROJECT_EDIT. The K8s Secret write is real (when a
    kubeconfig is loadable); the actual Postgres provisioning is
    STUBBED in Phase 5 — see :mod:`services.apps.managed_resources` for
    the explicit contract.
    """
    project = await _get_project_for_edit(slug, db, user)
    result: ManagedDbResult = await add_postgres(db, project=project, user=user)
    return UpgradeAddPostgresResponse(
        secret_name=result.secret_name,
        secret_namespace=result.secret_namespace,
        manifest_patch=result.manifest_patch,
        manifest_path=result.manifest_path,
        migration_script_path=result.migration_script_path,
        is_stub_provisioner=result.is_stub_provisioner,
        notes=result.notes,
    )
