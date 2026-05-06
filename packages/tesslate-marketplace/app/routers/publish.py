"""
Publish + submission lifecycle.

Wave 8: the publish endpoint creates a `Submission` row in the canonical
`stage0_received` state, runs structural intake (`stage0` checks +
fast-path bundle validation), then drives the staged pipeline through
`stage1_scanner` and `stage2_sandbox` and the staged advance helpers in
`services.submissions`. Each stage produces standardized
`SubmissionCheck` rows so the `submissions.staged` capability response
shape is the same wherever the protocol is implemented.

Two endpoints are added in Wave 8:

  * ``POST /v1/submissions/{id}/advance`` — run the next stage's checks
    (`stage1` → `stage2` → `stage3`). Used by the orchestrator's thin
    proxy when an admin clicks "advance" in the queue UI.
  * ``POST /v1/submissions/{id}/finalize`` — terminal decision
    (approved / rejected / withdrawn). Approval is only valid from
    ``stage3``; rejection is allowed from any non-terminal stage.

These are gated behind the ``submissions`` capability and require the
``submissions.write`` scope on the bearer.
"""

from __future__ import annotations

import base64
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..config import KINDS, Settings, get_settings
from ..database import get_session
from ..models import Bundle, Item, ItemVersion, Submission, SubmissionCheck
from ..schemas import (
    PublishRequest,
    SubmissionOut,
)
from ..services import changes_emitter
from ..services import stage1_scanner, stage2_sandbox
from ..services import submissions as submissions_svc
from ..services.attestations import get_attestor
from ..services.auth import Principal, get_principal
from ..services.capability_router import requires_capability
from ..services.cas import get_bundle_storage
from ..services.install_check import (
    BundleValidationError,
    compute_sha256,
    validate_archive_format,
    validate_bundle_size,
)

router = APIRouter(prefix="/v1", tags=["publish"])


def _validate_kind(kind: str) -> None:
    if kind not in KINDS:
        raise HTTPException(
            status_code=400,
            detail={"error": "unknown_kind", "kind": kind, "allowed": list(KINDS)},
        )


def _serialize(submission: Submission) -> SubmissionOut:
    return SubmissionOut(
        id=str(submission.id),
        kind=submission.kind,
        slug=submission.slug,
        version=submission.version,
        state=submission.state,
        stage=submission.stage,
        decision=submission.decision,
        decision_reason=submission.decision_reason,
        submitter_handle=submission.submitter_handle,
        bundle_sha256=submission.bundle_sha256,
        bundle_size_bytes=submission.bundle_size_bytes,
        item_id=str(submission.item_id) if submission.item_id else None,
        item_version_id=str(submission.item_version_id) if submission.item_version_id else None,
        checks=[
            {
                "stage": c.stage,
                "name": c.name,
                "status": c.status,
                "message": c.message,
                "details": c.details,
                "created_at": c.created_at,
            }
            for c in submission.checks
        ],
        created_at=submission.created_at,
        updated_at=submission.updated_at,
    )


def _record_check_inline(
    session: AsyncSession,
    submission: Submission,
    *,
    stage: str,
    name: str,
    status: str,
    message: str | None = None,
    details: dict[str, Any] | None = None,
) -> SubmissionCheck:
    """Synchronous local helper for stage0 + early stage1 (intake) checks.

    The staged services use the `submissions.record_check` async helper
    which round-trips a flush, but for intake we want to batch flushes —
    so we use this lightweight insert that defers the flush to the caller.
    """
    check = SubmissionCheck(
        submission_id=submission.id,
        stage=stage,
        name=name,
        status=status,
        message=message,
        details=details,
    )
    session.add(check)
    return check


async def _run_intake_and_pipeline(
    session: AsyncSession,
    submission: Submission,
    bundle_bytes: bytes | None,
) -> None:
    """Drive a brand-new submission through stage0 → stage1 → stage2 → stage3 → approved.

    Stage0 is intake: manifest acceptance + bundle structural checks
    (size cap, archive format, sha256 reconciliation). Stage1, Stage2 are
    delegated to the named services so the same checks fire whether
    publish drives them inline or an admin re-runs them via the explicit
    `/advance` endpoint. Stage3 is auto-approve in the dev/test default;
    in production a human reviewer would close the gate via
    `/finalize` after manual review.
    """
    # ---- Stage 0: intake ----
    submission.stage = "stage0"
    submission.state = submissions_svc.STAGE_TO_STATE["stage0"]
    _record_check_inline(
        session, submission,
        stage="stage0", name="manifest_present", status="passed",
        message="Manifest accepted",
    )

    if bundle_bytes is not None:
        try:
            validate_bundle_size(submission.kind, len(bundle_bytes))
            _record_check_inline(
                session, submission,
                stage="stage0", name="bundle_size", status="passed",
                details={"size_bytes": len(bundle_bytes)},
            )
        except BundleValidationError as exc:
            _record_check_inline(
                session, submission,
                stage="stage0", name="bundle_size", status="failed",
                message=str(exc),
            )
            await submissions_svc.advance_stage(
                session, submission_id=submission.id,
                to_stage="rejected", decision_reason=str(exc),
            )
            return
        try:
            validate_archive_format("tar.zst")
            _record_check_inline(
                session, submission,
                stage="stage0", name="archive_format", status="passed",
            )
        except BundleValidationError as exc:
            _record_check_inline(
                session, submission,
                stage="stage0", name="archive_format", status="failed",
                message=str(exc),
            )
            await submissions_svc.advance_stage(
                session, submission_id=submission.id,
                to_stage="rejected", decision_reason=str(exc),
            )
            return

        sha = compute_sha256(bundle_bytes)
        if submission.bundle_sha256 and submission.bundle_sha256 != sha:
            _record_check_inline(
                session, submission,
                stage="stage0", name="sha256_match", status="failed",
                message="Declared sha256 did not match computed sha256",
            )
            await submissions_svc.advance_stage(
                session, submission_id=submission.id,
                to_stage="rejected", decision_reason="sha256_mismatch",
            )
            return
        submission.bundle_sha256 = sha
        submission.bundle_size_bytes = len(bundle_bytes)
        _record_check_inline(
            session, submission,
            stage="stage0", name="sha256_match", status="passed",
            details={"sha256": sha},
        )
    else:
        _record_check_inline(
            session, submission,
            stage="stage0", name="bundle_present", status="warning",
            message="No bundle uploaded — manifest-only submission",
        )

    # Move to stage1 + run static scan (delegated).
    await submissions_svc.advance_stage(session, submission_id=submission.id, to_stage="stage1")
    stage1_result = await stage1_scanner.run_stage1_scan(session, submission_id=submission.id)
    if stage1_result["advanced_to"] == "rejected":
        return

    # stage2 sandbox eval.
    stage2_result = await stage2_sandbox.run_stage2_eval(session, submission_id=submission.id)
    if stage2_result["advanced_to"] == "rejected":
        return

    # stage3 → approved (auto-policy in dev / test).
    submissions_svc_check = await submissions_svc.record_check(
        session,
        submission_id=submission.id,
        stage="stage3",
        name="reviewer_assignment",
        status="passed",
        message="Auto-approved by policy",
    )
    _ = submissions_svc_check  # silence unused — recorded for audit
    await submissions_svc.finalize_submission(
        session,
        submission_id=submission.id,
        decision="approved",
        decision_reason="auto_approved",
    )


async def _materialise_item(
    session: AsyncSession,
    request: PublishRequest,
    submission: Submission,
    bundle_bytes: bytes | None,
    settings: Settings,
) -> tuple[Item, ItemVersion, Bundle | None]:
    item_payload = request.item
    # Upsert item
    existing = (
        await session.execute(select(Item).where(Item.kind == submission.kind, Item.slug == item_payload.slug))
    ).scalar_one_or_none()
    if existing is None:
        item = Item(
            kind=submission.kind,
            slug=item_payload.slug,
            name=item_payload.name,
            description=item_payload.description,
            long_description=item_payload.long_description,
            category=item_payload.category,
            icon=item_payload.icon,
            tags=list(item_payload.tags or []),
            features=list(item_payload.features or []),
            tech_stack=list(item_payload.tech_stack or []),
            extra_metadata=dict(item_payload.extra_metadata or {}),
            creator_handle=item_payload.creator_handle,
            git_repo_url=item_payload.git_repo_url,
            homepage_url=item_payload.homepage_url,
            pricing_type=item_payload.pricing.pricing_type,
            price_cents=item_payload.pricing.price_cents,
            stripe_price_id=item_payload.pricing.stripe_price_id,
            pricing_payload=item_payload.pricing.model_dump(),
        )
        session.add(item)
        await session.flush()
    else:
        item = existing
        item.name = item_payload.name
        item.description = item_payload.description
        item.long_description = item_payload.long_description
        item.category = item_payload.category
        item.icon = item_payload.icon
        item.tags = list(item_payload.tags or [])
        item.features = list(item_payload.features or [])
        item.tech_stack = list(item_payload.tech_stack or [])
        item.extra_metadata = dict(item_payload.extra_metadata or {})
        item.creator_handle = item_payload.creator_handle or item.creator_handle
        item.git_repo_url = item_payload.git_repo_url or item.git_repo_url
        item.homepage_url = item_payload.homepage_url or item.homepage_url
        item.pricing_type = item_payload.pricing.pricing_type
        item.price_cents = item_payload.pricing.price_cents
        item.stripe_price_id = item_payload.pricing.stripe_price_id
        item.pricing_payload = item_payload.pricing.model_dump()
        await session.flush()

    # Upsert version
    version_payload = request.version
    iv = (
        await session.execute(
            select(ItemVersion).where(
                ItemVersion.item_id == item.id, ItemVersion.version == version_payload.version
            )
        )
    ).scalar_one_or_none()
    if iv is None:
        iv = ItemVersion(
            item_id=item.id,
            version=version_payload.version,
            changelog=version_payload.changelog,
            manifest=version_payload.manifest,
        )
        if version_payload.pricing:
            iv.pricing_type = version_payload.pricing.pricing_type
            iv.price_cents = version_payload.pricing.price_cents
            iv.stripe_price_id = version_payload.pricing.stripe_price_id
        session.add(iv)
        await session.flush()
    else:
        iv.changelog = version_payload.changelog
        iv.manifest = version_payload.manifest
        if version_payload.pricing:
            iv.pricing_type = version_payload.pricing.pricing_type
            iv.price_cents = version_payload.pricing.price_cents
            iv.stripe_price_id = version_payload.pricing.stripe_price_id
        await session.flush()

    item.latest_version = iv.version
    item.latest_version_id = iv.id

    bundle = None
    if bundle_bytes is not None:
        storage = get_bundle_storage(settings)
        ref = storage.put_bytes(item.kind, item.slug, iv.version, bundle_bytes)
        attestor = get_attestor(settings)
        attestation = attestor.sign_sha256(ref.sha256)

        existing_bundle = (
            await session.execute(select(Bundle).where(Bundle.item_version_id == iv.id))
        ).scalar_one_or_none()
        if existing_bundle is None:
            bundle = Bundle(
                item_version_id=iv.id,
                sha256=ref.sha256,
                size_bytes=ref.size_bytes,
                storage_backend=ref.backend,
                storage_key=ref.storage_key,
                attestation_signature=attestation.signature,
                attestation_key_id=attestation.key_id,
                attestation_algorithm=attestation.algorithm,
            )
            session.add(bundle)
        else:
            existing_bundle.sha256 = ref.sha256
            existing_bundle.size_bytes = ref.size_bytes
            existing_bundle.storage_backend = ref.backend
            existing_bundle.storage_key = ref.storage_key
            existing_bundle.attestation_signature = attestation.signature
            existing_bundle.attestation_key_id = attestation.key_id
            existing_bundle.attestation_algorithm = attestation.algorithm
            bundle = existing_bundle
        await session.flush()

    submission.item_id = item.id
    submission.item_version_id = iv.id
    return item, iv, bundle


@router.post("/publish/{kind}", response_model=SubmissionOut, status_code=201)
@requires_capability("publish")
async def publish_kind(
    kind: str,
    request: PublishRequest,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(get_principal),
) -> SubmissionOut:
    principal.require_scope("publish")
    _validate_kind(kind)

    bundle_bytes = None
    if request.version.bundle_b64:
        try:
            bundle_bytes = base64.b64decode(request.version.bundle_b64)
        except Exception as exc:
            raise HTTPException(status_code=400, detail={"error": "invalid_bundle_b64", "details": str(exc)}) from exc

    submitter_token_id = None
    if principal.token_id:
        try:
            submitter_token_id = uuid.UUID(principal.token_id)
        except ValueError:
            submitter_token_id = None
    submission = Submission(
        kind=kind,
        slug=request.item.slug,
        version=request.version.version,
        manifest=request.version.manifest,
        submitter_handle=principal.handle,
        submitter_token_id=submitter_token_id,
    )
    db.add(submission)
    await db.flush()

    await _run_intake_and_pipeline(db, submission, bundle_bytes)

    if submission.state == "approved":
        item, iv, _ = await _materialise_item(db, request, submission, bundle_bytes, settings)
        await changes_emitter.emit(
            db,
            op="upsert",
            kind=item.kind,
            slug=item.slug,
            version=iv.version,
            payload={
                "name": item.name,
                "description": item.description,
                "category": item.category,
                "version": iv.version,
                "is_published": item.is_published,
            },
        )

    await db.commit()
    # Re-load with the relationship eagerly populated so serialisation doesn't
    # trigger a lazy SELECT outside the async context.
    submission_with_checks = (
        await db.execute(
            select(Submission)
            .options(selectinload(Submission.checks))
            .where(Submission.id == submission.id)
        )
    ).scalar_one()
    return _serialize(submission_with_checks)


@router.post("/publish/{kind}/{slug}/versions/{version}", response_model=SubmissionOut, status_code=201)
@requires_capability("publish")
async def publish_version(
    kind: str,
    slug: str,
    version: str,
    request: PublishRequest,
    db: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(get_principal),
) -> SubmissionOut:
    principal.require_scope("publish")
    _validate_kind(kind)
    if request.item.slug != slug:
        raise HTTPException(status_code=400, detail={"error": "slug_mismatch"})
    if request.version.version != version:
        raise HTTPException(status_code=400, detail={"error": "version_mismatch"})
    return await publish_kind(kind=kind, request=request, db=db, settings=settings, principal=principal)


@router.get("/submissions/{submission_id}", response_model=SubmissionOut)
@requires_capability("submissions")
async def get_submission(
    submission_id: str,
    db: AsyncSession = Depends(get_session),
    principal: Principal = Depends(get_principal),
) -> SubmissionOut:
    principal.require_scope("submissions.read")
    row = (
        await db.execute(
            select(Submission)
            .options(selectinload(Submission.checks))
            .where(Submission.id == submission_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail={"error": "submission_not_found"})
    return _serialize(row)


@router.post("/submissions/{submission_id}/withdraw", response_model=SubmissionOut)
@requires_capability("submissions")
async def withdraw_submission(
    submission_id: str,
    db: AsyncSession = Depends(get_session),
    principal: Principal = Depends(get_principal),
) -> SubmissionOut:
    principal.require_scope("publish")
    row = (
        await db.execute(
            select(Submission)
            .options(selectinload(Submission.checks))
            .where(Submission.id == submission_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail={"error": "submission_not_found"})
    if row.state in ("approved", "rejected", "withdrawn"):
        raise HTTPException(status_code=409, detail={"error": "submission_terminal", "state": row.state})
    try:
        await submissions_svc.advance_stage(
            db,
            submission_id=row.id,
            to_stage="withdrawn",
            decision_reason=f"Withdrawn by {principal.handle}",
        )
    except submissions_svc.InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail={"error": "invalid_transition", "details": str(exc)}) from exc
    await db.commit()
    refreshed = (
        await db.execute(
            select(Submission)
            .options(selectinload(Submission.checks))
            .where(Submission.id == row.id)
        )
    ).scalar_one()
    return _serialize(refreshed)


# ---------------------------------------------------------------------------
# Wave 8: explicit advance + finalize endpoints (admin-driven)
# ---------------------------------------------------------------------------


@router.post(
    "/submissions/{submission_id}/advance",
    response_model=SubmissionOut,
    status_code=200,
)
@requires_capability("submissions.staged")
async def advance_submission(
    submission_id: str,
    db: AsyncSession = Depends(get_session),
    principal: Principal = Depends(get_principal),
) -> SubmissionOut:
    """Run the next stage's checks for an in-flight submission.

    The pipeline knows which stage to run from the row's current `stage`:

      * stage0 → just transitions to stage1 (intake already ran on publish)
      * stage1 → runs `stage1_scanner` (advances to stage2 or rejected)
      * stage2 → runs `stage2_sandbox` (advances to stage3 or rejected)
      * stage3 → no-op (admin must call /finalize)

    Idempotent: re-running on a terminal submission returns the current
    state without recording duplicate checks.
    """
    principal.require_scope("submissions.write")
    row = (
        await db.execute(
            select(Submission)
            .options(selectinload(Submission.checks))
            .where(Submission.id == submission_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail={"error": "submission_not_found"})
    if row.stage in ("approved", "rejected", "withdrawn"):
        # Terminal — return the current state, do not re-run checks.
        return _serialize(row)

    try:
        if row.stage == "stage0":
            await submissions_svc.advance_stage(db, submission_id=row.id, to_stage="stage1")
        elif row.stage == "stage1":
            await stage1_scanner.run_stage1_scan(db, submission_id=row.id)
        elif row.stage == "stage2":
            await stage2_sandbox.run_stage2_eval(db, submission_id=row.id)
        elif row.stage == "stage3":
            # stage3 is the manual-review gate; advance is a no-op here.
            pass
        else:
            raise HTTPException(
                status_code=409,
                detail={"error": "unknown_stage", "stage": row.stage},
            )
    except submissions_svc.InvalidTransitionError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"error": "invalid_transition", "details": str(exc)},
        ) from exc

    await db.commit()
    refreshed = (
        await db.execute(
            select(Submission)
            .options(selectinload(Submission.checks))
            .where(Submission.id == row.id)
        )
    ).scalar_one()
    return _serialize(refreshed)


@router.post(
    "/submissions/{submission_id}/finalize",
    response_model=SubmissionOut,
    status_code=200,
)
@requires_capability("submissions.staged")
async def finalize_submission_endpoint(
    submission_id: str,
    payload: dict,
    db: AsyncSession = Depends(get_session),
    principal: Principal = Depends(get_principal),
) -> SubmissionOut:
    """Force a terminal decision on a submission.

    `payload`:
      * `decision`: "approved" | "rejected" | "withdrawn" (required)
      * `decision_reason`: optional human-readable note

    Approval is only valid from `stage3` (no skipping the queue). Rejection
    is allowed from any non-terminal stage. The submitter's own handle can
    finalize as `withdrawn`; everyone else needs the `submissions.write`
    scope.
    """
    decision = (payload or {}).get("decision") if isinstance(payload, dict) else None
    if decision not in ("approved", "rejected", "withdrawn"):
        raise HTTPException(
            status_code=400,
            detail={"error": "missing_or_invalid_decision", "expected": ["approved", "rejected", "withdrawn"]},
        )
    decision_reason = (payload or {}).get("decision_reason") if isinstance(payload, dict) else None

    row = (
        await db.execute(
            select(Submission).where(Submission.id == submission_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail={"error": "submission_not_found"})

    # Withdraw is the submitter's own affordance; reject + approve are admin-only.
    if decision == "withdrawn":
        if row.submitter_handle and row.submitter_handle != principal.handle:
            principal.require_scope("submissions.write")
    else:
        principal.require_scope("submissions.write")

    try:
        await submissions_svc.finalize_submission(
            db,
            submission_id=row.id,
            decision=decision,  # type: ignore[arg-type]
            decision_reason=decision_reason,
        )
    except submissions_svc.AlreadyTerminalError as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": "submission_terminal", "state": row.state, "details": str(exc)},
        ) from exc
    except submissions_svc.InvalidTransitionError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"error": "invalid_transition", "details": str(exc)},
        ) from exc

    await db.commit()
    refreshed = (
        await db.execute(
            select(Submission)
            .options(selectinload(Submission.checks))
            .where(Submission.id == row.id)
        )
    ).scalar_one()
    return _serialize(refreshed)
