"""Automation Runtime — Phase 1 HTTP router.

CRUD on :class:`AutomationDefinition` plus a manual-run trigger that mints an
:class:`AutomationEvent` (with ``trigger_kind='manual'``) and enqueues
``dispatch_automation_task`` against the shared task queue.

Auth model
----------
Every endpoint accepts a session-authenticated user (``current_active_user``).
External API key access is also accepted via the same dependency — the
``ExternalAPIKey`` middleware mounts the resolved user onto the request so
both auth modes converge here. Per-endpoint ownership / team-membership gates
live in :func:`_authorize_definition` and reuse :func:`get_team_membership`
from ``app.permissions`` so we don't reinvent the role wheel.

Phase 1 limitations enforced at this layer
------------------------------------------
* ``actions`` must contain exactly one row (the dispatcher also refuses
  multi-action sets — defence in depth).
* ``contract`` is REQUIRED on create. None / ``{}`` returns 400.
* Manual runs use ``trigger_kind='manual'`` (already in the model CHECK).
  No synthetic NULL ``event_id`` — the run row always carries the manufactured
  event UUID so the existing dispatcher idempotency upsert works unchanged.

Out of scope for Phase 1
------------------------
* Webhook trigger endpoints (Phase 2 ``/api/automations/{id}/webhook/{token}``).
* Approval resolution (Phase 2 ``/api/automations/runs/{run_id}/approvals``).
* CommunicationDestination CRUD (Phase 4).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import User
from ..models_automations import (
    AutomationAction,
    AutomationApprovalRequest,
    AutomationDefinition,
    AutomationDeliveryTarget,
    AutomationEvent,
    AutomationRun,
    AutomationRunArtifact,
    AutomationTrigger,
)
from ..permissions import Permission, get_team_membership
from ..schemas_automations import (
    ApprovalResponseIn,
    ApprovalResponseOut,
    AutomationApprovalRequestOut,
    AutomationActionIn,
    AutomationActionOut,
    AutomationDefinitionIn,
    AutomationDefinitionOut,
    AutomationDefinitionSummary,
    AutomationDefinitionUpdate,
    AutomationDeliveryTargetIn,
    AutomationDeliveryTargetOut,
    AutomationRunArtifactOut,
    AutomationRunDetail,
    AutomationRunRequest,
    AutomationRunResponse,
    AutomationRunSummary,
    AutomationTriggerIn,
    AutomationTriggerOut,
)
from ..users import current_active_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/automations", tags=["automations"])


# ---------------------------------------------------------------------------
# Authorization helpers
# ---------------------------------------------------------------------------


# Roles that may mutate a team-scoped automation. Viewers get read-only.
_TEAM_WRITE_ROLES = frozenset({"admin", "editor"})
_TEAM_READ_ROLES = frozenset({"admin", "editor", "viewer"})


async def _authorize_definition(
    db: AsyncSession,
    definition: AutomationDefinition,
    user: User,
    *,
    write: bool,
) -> None:
    """Owner / team-role gate for a definition.

    Owner always wins. Otherwise consult team membership when the definition
    is team-scoped. Superusers bypass.

    Raises
    ------
    HTTPException(404)
        When the user has no read access (we 404 rather than 403 to avoid
        leaking existence — same pattern as ``get_project_with_access``).
    HTTPException(403)
        When the user has read access but no write access.
    """
    if getattr(user, "is_superuser", False):
        return
    if definition.owner_user_id == user.id:
        return

    # Team membership path: allow editors+ to mutate, viewers read only.
    if definition.team_id is not None:
        membership = await get_team_membership(db, definition.team_id, user.id)
        if membership is not None:
            if write:
                if membership.role in _TEAM_WRITE_ROLES:
                    return
                raise HTTPException(
                    status_code=403,
                    detail=(
                        f"Role '{membership.role}' may not edit this automation"
                    ),
                )
            if membership.role in _TEAM_READ_ROLES:
                return

    raise HTTPException(status_code=404, detail="Automation not found")


# ---------------------------------------------------------------------------
# Definition projection
# ---------------------------------------------------------------------------


async def _project_definition(
    db: AsyncSession, definition: AutomationDefinition
) -> AutomationDefinitionOut:
    """Load a definition with its trigger / action / delivery_target children."""
    triggers = (
        (
            await db.execute(
                select(AutomationTrigger)
                .where(AutomationTrigger.automation_id == definition.id)
                .order_by(AutomationTrigger.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    actions = (
        (
            await db.execute(
                select(AutomationAction)
                .where(AutomationAction.automation_id == definition.id)
                .order_by(AutomationAction.ordinal.asc())
            )
        )
        .scalars()
        .all()
    )
    targets = (
        (
            await db.execute(
                select(AutomationDeliveryTarget)
                .where(AutomationDeliveryTarget.automation_id == definition.id)
                .order_by(AutomationDeliveryTarget.ordinal.asc())
            )
        )
        .scalars()
        .all()
    )

    return AutomationDefinitionOut(
        id=definition.id,
        name=definition.name,
        owner_user_id=definition.owner_user_id,
        team_id=definition.team_id,
        workspace_scope=definition.workspace_scope,
        workspace_project_id=definition.workspace_project_id,
        target_project_id=definition.target_project_id,
        contract=definition.contract or {},
        max_compute_tier=definition.max_compute_tier,
        max_spend_per_run_usd=definition.max_spend_per_run_usd,
        max_spend_per_day_usd=definition.max_spend_per_day_usd,
        parent_automation_id=definition.parent_automation_id,
        depth=definition.depth,
        is_active=definition.is_active,
        paused_reason=definition.paused_reason,
        attribution_user_id=definition.attribution_user_id,
        created_by_user_id=definition.created_by_user_id,
        created_at=definition.created_at,
        updated_at=definition.updated_at,
        triggers=[AutomationTriggerOut.model_validate(t) for t in triggers],
        actions=[AutomationActionOut.model_validate(a) for a in actions],
        delivery_targets=[
            AutomationDeliveryTargetOut.model_validate(t) for t in targets
        ],
    )


# ---------------------------------------------------------------------------
# Child-row replacement (used by create + patch when caller supplies lists)
# ---------------------------------------------------------------------------


async def _replace_triggers(
    db: AsyncSession,
    automation_id: UUID,
    triggers: list[AutomationTriggerIn],
) -> None:
    await db.execute(
        delete(AutomationTrigger).where(
            AutomationTrigger.automation_id == automation_id
        )
    )
    for trig in triggers:
        db.add(
            AutomationTrigger(
                id=uuid4(),
                automation_id=automation_id,
                kind=trig.kind,
                config=trig.config or {},
                is_active=True,
            )
        )


async def _replace_actions(
    db: AsyncSession,
    automation_id: UUID,
    actions: list[AutomationActionIn],
) -> None:
    await db.execute(
        delete(AutomationAction).where(
            AutomationAction.automation_id == automation_id
        )
    )
    for action in actions:
        db.add(
            AutomationAction(
                id=uuid4(),
                automation_id=automation_id,
                ordinal=action.ordinal,
                action_type=action.action_type,
                config=action.config or {},
                app_action_id=action.app_action_id,
            )
        )


async def _replace_delivery_targets(
    db: AsyncSession,
    automation_id: UUID,
    targets: list[AutomationDeliveryTargetIn],
) -> None:
    await db.execute(
        delete(AutomationDeliveryTarget).where(
            AutomationDeliveryTarget.automation_id == automation_id
        )
    )
    for target in targets:
        db.add(
            AutomationDeliveryTarget(
                id=uuid4(),
                automation_id=automation_id,
                destination_id=target.destination_id,
                ordinal=target.ordinal,
                on_failure=target.on_failure or {},
                artifact_filter=target.artifact_filter or "all",
            )
        )


async def _load_definition_or_404(
    db: AsyncSession, automation_id: UUID
) -> AutomationDefinition:
    row = (
        await db.execute(
            select(AutomationDefinition).where(
                AutomationDefinition.id == automation_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Automation not found")
    return row


# ---------------------------------------------------------------------------
# CRUD: AutomationDefinition
# ---------------------------------------------------------------------------


@router.get("", response_model=list[AutomationDefinitionSummary])
async def list_automations(
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
    is_active: bool | None = Query(default=None),
    workspace_scope: str | None = Query(default=None),
    team_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[AutomationDefinitionSummary]:
    """List the caller's automations + any team automations they can read.

    No N+1 child fetch — list view is the lightweight projection. Drill into
    ``GET /{id}`` for full triggers / actions / delivery_targets.
    """
    # The user's own definitions are always visible. We additionally surface
    # team-scoped definitions where the user has any active membership in
    # the team. Building the team-id list once keeps the SQL cheap.
    from ..models_team import TeamMembership

    team_rows = (
        (
            await db.execute(
                select(TeamMembership.team_id).where(
                    TeamMembership.user_id == user.id,
                    TeamMembership.is_active.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )

    query = select(AutomationDefinition)
    if team_rows:
        query = query.where(
            (AutomationDefinition.owner_user_id == user.id)
            | (AutomationDefinition.team_id.in_(team_rows))
        )
    else:
        query = query.where(AutomationDefinition.owner_user_id == user.id)

    if is_active is not None:
        query = query.where(AutomationDefinition.is_active.is_(is_active))
    if workspace_scope is not None:
        query = query.where(AutomationDefinition.workspace_scope == workspace_scope)
    if team_id is not None:
        query = query.where(AutomationDefinition.team_id == team_id)

    query = (
        query.order_by(AutomationDefinition.created_at.desc())
        .limit(limit)
        .offset(offset)
    )

    rows = (await db.execute(query)).scalars().all()
    return [AutomationDefinitionSummary.model_validate(r) for r in rows]


@router.post(
    "",
    response_model=AutomationDefinitionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_automation(
    payload: AutomationDefinitionIn,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> AutomationDefinitionOut:
    """Create an AutomationDefinition + child rows in a single transaction."""
    # Belt-and-suspenders contract guard. Pydantic validator already rejects
    # None / {}, but keep this here so a bad call from inside the process
    # (e.g. the agent-builder skill) still gets the same 400.
    if not isinstance(payload.contract, dict) or not payload.contract:
        raise HTTPException(
            status_code=400,
            detail="contract is required and must be a non-empty object",
        )

    # If team-scoped, verify the user is a member with write rights. Owner
    # of the definition is always the calling user; team_id only opts the
    # definition into team visibility.
    if payload.team_id is not None:
        membership = await get_team_membership(db, payload.team_id, user.id)
        if membership is None or membership.role not in _TEAM_WRITE_ROLES:
            raise HTTPException(
                status_code=403,
                detail="Cannot create a team-scoped automation without editor+ role",
            )

    automation = AutomationDefinition(
        id=uuid4(),
        name=payload.name,
        owner_user_id=user.id,
        team_id=payload.team_id,
        workspace_scope=payload.workspace_scope,
        workspace_project_id=payload.workspace_project_id,
        target_project_id=payload.target_project_id,
        contract=payload.contract,
        max_compute_tier=payload.max_compute_tier,
        max_spend_per_run_usd=payload.max_spend_per_run_usd,
        max_spend_per_day_usd=payload.max_spend_per_day_usd,
        is_active=True,
        created_by_user_id=user.id,
        depth=0,
    )
    db.add(automation)
    await db.flush()

    await _replace_triggers(db, automation.id, payload.triggers)
    await _replace_actions(db, automation.id, payload.actions)
    await _replace_delivery_targets(db, automation.id, payload.delivery_targets)

    await db.commit()
    await db.refresh(automation)

    logger.info(
        "[AUTOMATIONS] created id=%s name=%s owner=%s team=%s scope=%s",
        automation.id,
        automation.name,
        user.id,
        automation.team_id,
        automation.workspace_scope,
    )
    return await _project_definition(db, automation)


@router.get("/{automation_id}", response_model=AutomationDefinitionOut)
async def get_automation(
    automation_id: UUID,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> AutomationDefinitionOut:
    automation = await _load_definition_or_404(db, automation_id)
    await _authorize_definition(db, automation, user, write=False)
    return await _project_definition(db, automation)


@router.patch("/{automation_id}", response_model=AutomationDefinitionOut)
async def update_automation(
    automation_id: UUID,
    payload: AutomationDefinitionUpdate,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> AutomationDefinitionOut:
    automation = await _load_definition_or_404(db, automation_id)
    await _authorize_definition(db, automation, user, write=True)

    if payload.name is not None:
        automation.name = payload.name
    if payload.is_active is not None:
        automation.is_active = payload.is_active
    if payload.paused_reason is not None:
        automation.paused_reason = payload.paused_reason
    if payload.contract is not None:
        # Re-check non-empty here; Pydantic validator handles the literal
        # ``{}`` case but a caller with model_config bypass could still slip
        # an empty dict through.
        if not payload.contract:
            raise HTTPException(
                status_code=400,
                detail="contract, when provided, must be a non-empty object",
            )
        automation.contract = payload.contract
    if payload.max_compute_tier is not None:
        automation.max_compute_tier = payload.max_compute_tier
    if payload.max_spend_per_run_usd is not None:
        automation.max_spend_per_run_usd = payload.max_spend_per_run_usd
    if payload.max_spend_per_day_usd is not None:
        automation.max_spend_per_day_usd = payload.max_spend_per_day_usd

    if payload.triggers is not None:
        await _replace_triggers(db, automation.id, payload.triggers)
    if payload.actions is not None:
        await _replace_actions(db, automation.id, payload.actions)
    if payload.delivery_targets is not None:
        await _replace_delivery_targets(
            db, automation.id, payload.delivery_targets
        )

    await db.commit()
    await db.refresh(automation)
    return await _project_definition(db, automation)


@router.delete("/{automation_id}")
async def delete_automation(
    automation_id: UUID,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
    hard: bool = Query(default=False, description="Hard delete only allowed when no runs exist"),
) -> dict[str, Any]:
    """Soft-delete (set ``is_active=False``) by default.

    ``hard=true`` removes the row outright. Hard delete is REJECTED with 409
    when any ``automation_runs`` row exists for this definition — those rows
    carry billing, audit, and artifact references that would orphan.
    """
    automation = await _load_definition_or_404(db, automation_id)
    await _authorize_definition(db, automation, user, write=True)

    if hard:
        count = (
            await db.scalar(
                select(func.count(AutomationRun.id)).where(
                    AutomationRun.automation_id == automation.id
                )
            )
            or 0
        )
        if count > 0:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Cannot hard-delete: {count} run(s) reference this "
                    "automation. Use soft delete (default) instead."
                ),
            )
        await db.delete(automation)
        await db.commit()
        logger.info(
            "[AUTOMATIONS] hard-deleted id=%s by user=%s", automation_id, user.id
        )
        return {"status": "deleted", "id": str(automation_id), "hard": True}

    automation.is_active = False
    automation.paused_reason = "deleted_by_user"
    await db.commit()
    logger.info(
        "[AUTOMATIONS] soft-deleted id=%s by user=%s", automation_id, user.id
    )
    return {"status": "deactivated", "id": str(automation_id), "hard": False}


# ---------------------------------------------------------------------------
# Manual run
# ---------------------------------------------------------------------------


@router.post(
    "/{automation_id}/run",
    response_model=AutomationRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_automation(
    automation_id: UUID,
    payload: AutomationRunRequest | None = None,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> AutomationRunResponse:
    """Manually trigger an automation.

    Implementation note (``trigger_kind='manual'`` vs ``event_id=NULL``):

    The ``automation_triggers.kind`` CHECK already includes ``'manual'`` (see
    migration 0074), and the ``automation_events`` table has no NOT NULL
    constraint on ``trigger_id`` — so we mint a fresh
    :class:`AutomationEvent` with ``trigger_kind='manual'`` and a NULL
    ``trigger_id``. The dispatcher's idempotency upsert keys off
    ``(automation_id, event_id)``, which means each manual run gets its own
    independent run row without colliding with cron / webhook runs. We chose
    this over ``event_id=NULL`` runs because the dispatcher's UPSERT branch
    table assumes every run has a non-null event_id (NULL would silently
    short-circuit the idempotency surface and let two concurrent manual runs
    both win the insert race).
    """
    payload = payload or AutomationRunRequest()
    automation = await _load_definition_or_404(db, automation_id)
    await _authorize_definition(db, automation, user, write=True)

    if not automation.is_active:
        raise HTTPException(
            status_code=409, detail="Automation is paused / inactive"
        )

    event = AutomationEvent(
        id=uuid4(),
        automation_id=automation.id,
        trigger_id=None,  # manual runs have no trigger row
        trigger_kind="manual",
        payload=payload.payload or {},
        idempotency_key=payload.idempotency_key,
        received_at=datetime.now(tz=UTC),
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)

    # Eagerly create the run row so the response includes a real ``run_id``.
    # The dispatcher's upsert is idempotent — if it picks up the event before
    # this row commits, both arrive at the same ``(automation_id, event_id)``
    # unique key and the dispatcher takes the existing row.
    run = AutomationRun(
        id=uuid4(),
        automation_id=automation.id,
        event_id=event.id,
        status="queued",
        worker_id=None,
        heartbeat_at=datetime.now(tz=UTC),
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    # Enqueue the dispatcher task. ARQ accepts any string handler name; the
    # worker registers ``dispatch_automation_task`` in Wave 3B. If the task
    # isn't registered yet, ARQ holds the job in the queue until it is.
    try:
        from ..services.task_queue import get_task_queue

        await get_task_queue().enqueue(
            "dispatch_automation_task",
            str(automation.id),
            str(event.id),
            None,  # worker_id — dispatcher synthesizes one if missing
        )
    except Exception as exc:  # noqa: BLE001 — enqueue must never fail the run record
        logger.warning(
            "[AUTOMATIONS] enqueue failed automation=%s event=%s err=%r — "
            "run row persisted; controller / cron sweep will retry",
            automation.id,
            event.id,
            exc,
        )

    logger.info(
        "[AUTOMATIONS] manual run automation=%s run=%s event=%s by user=%s",
        automation.id,
        run.id,
        event.id,
        user.id,
    )
    return AutomationRunResponse(
        automation_id=automation.id,
        run_id=run.id,
        event_id=event.id,
        status=run.status,
    )


# ---------------------------------------------------------------------------
# Run inspection
# ---------------------------------------------------------------------------


@router.get(
    "/{automation_id}/runs", response_model=list[AutomationRunSummary]
)
async def list_runs(
    automation_id: UUID,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    status_filter: str | None = Query(default=None, alias="status"),
) -> list[AutomationRunSummary]:
    automation = await _load_definition_or_404(db, automation_id)
    await _authorize_definition(db, automation, user, write=False)

    query = (
        select(AutomationRun)
        .where(AutomationRun.automation_id == automation_id)
        .order_by(AutomationRun.created_at.desc())
    )
    if status_filter is not None:
        query = query.where(AutomationRun.status == status_filter)
    query = query.limit(limit).offset(offset)

    rows = (await db.execute(query)).scalars().all()
    return [AutomationRunSummary.model_validate(r) for r in rows]


@router.get(
    "/{automation_id}/runs/{run_id}", response_model=AutomationRunDetail
)
async def get_run(
    automation_id: UUID,
    run_id: UUID,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> AutomationRunDetail:
    automation = await _load_definition_or_404(db, automation_id)
    await _authorize_definition(db, automation, user, write=False)

    run = (
        await db.execute(
            select(AutomationRun).where(
                AutomationRun.id == run_id,
                AutomationRun.automation_id == automation_id,
            )
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    artifacts = (
        (
            await db.execute(
                select(AutomationRunArtifact)
                .where(AutomationRunArtifact.run_id == run_id)
                .order_by(AutomationRunArtifact.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    approvals = (
        (
            await db.execute(
                select(AutomationApprovalRequest)
                .where(AutomationApprovalRequest.run_id == run_id)
                .order_by(AutomationApprovalRequest.requested_at.asc())
            )
        )
        .scalars()
        .all()
    )

    return AutomationRunDetail(
        id=run.id,
        automation_id=run.automation_id,
        event_id=run.event_id,
        status=run.status,
        retry_count=run.retry_count,
        spend_usd=run.spend_usd,
        contract_breaches=run.contract_breaches,
        paused_reason=run.paused_reason,
        started_at=run.started_at,
        ended_at=run.ended_at,
        created_at=run.created_at,
        raw_output=run.raw_output,
        artifacts=[AutomationRunArtifactOut.model_validate(a) for a in artifacts],
        approval_requests=[
            AutomationApprovalRequestOut.model_validate(a) for a in approvals
        ],
    )


@router.get(
    "/{automation_id}/runs/{run_id}/artifacts",
    response_model=list[AutomationRunArtifactOut],
)
async def list_run_artifacts(
    automation_id: UUID,
    run_id: UUID,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> list[AutomationRunArtifactOut]:
    automation = await _load_definition_or_404(db, automation_id)
    await _authorize_definition(db, automation, user, write=False)

    # Verify the run actually belongs to the automation so a leaked run_id
    # from another tenant can't be used to enumerate artifacts.
    run = (
        await db.execute(
            select(AutomationRun.id).where(
                AutomationRun.id == run_id,
                AutomationRun.automation_id == automation_id,
            )
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    artifacts = (
        (
            await db.execute(
                select(AutomationRunArtifact)
                .where(AutomationRunArtifact.run_id == run_id)
                .order_by(AutomationRunArtifact.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    return [AutomationRunArtifactOut.model_validate(a) for a in artifacts]


@router.get("/{automation_id}/runs/{run_id}/artifacts/{artifact_id}")
async def download_artifact(
    automation_id: UUID,
    run_id: UUID,
    artifact_id: UUID,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Return artifact content based on ``storage_mode``.

    * ``inline`` — return ``storage_ref`` as response body. Mime from
      ``mime_type`` if set, otherwise ``application/octet-stream``.
    * ``s3``     — 307 redirect to the signed URL stored in ``storage_ref``.
    * ``cas``    — Phase 1 returns the CAS payload as the body when small,
      mirroring inline. Phase 3 will route via the CAS gateway.
    * ``external_url`` — 307 redirect.
    """
    automation = await _load_definition_or_404(db, automation_id)
    await _authorize_definition(db, automation, user, write=False)

    artifact = (
        await db.execute(
            select(AutomationRunArtifact).where(
                AutomationRunArtifact.id == artifact_id,
                AutomationRunArtifact.run_id == run_id,
            )
        )
    ).scalar_one_or_none()
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")

    # Defence against cross-automation artifact lookups.
    run_owner = (
        await db.execute(
            select(AutomationRun.automation_id).where(AutomationRun.id == run_id)
        )
    ).scalar_one_or_none()
    if run_owner != automation_id:
        raise HTTPException(status_code=404, detail="Artifact not found")

    mode = artifact.storage_mode
    if mode in {"s3", "external_url"}:
        return RedirectResponse(url=artifact.storage_ref, status_code=307)

    if mode in {"inline", "cas"}:
        body = artifact.storage_ref or ""
        media = artifact.mime_type or "application/octet-stream"
        return Response(content=body, media_type=media)

    # Unknown storage mode — should never happen but fail loudly.
    raise HTTPException(
        status_code=500,
        detail=f"unsupported storage_mode={mode!r}",
    )


# ---------------------------------------------------------------------------
# Non-blocking HITL — approval response (Phase 2 Wave 2A)
# ---------------------------------------------------------------------------


def _merge_scope_modifications(
    contract: dict[str, Any], delta: dict[str, Any]
) -> dict[str, Any]:
    """Shallow-merge ``delta`` into ``contract``.

    Top-level keys overwrite; list values replace whole-list (no append),
    matching the plan's "scope_modifications" semantics. We deliberately do
    NOT deep-merge — a runaway agent could otherwise persist arbitrary
    nested keys via a benign-looking approval response.
    """
    merged = dict(contract or {})
    for k, v in (delta or {}).items():
        if isinstance(v, list):
            merged[k] = list(v)
        elif isinstance(v, dict):
            merged[k] = dict(v)
        else:
            merged[k] = v
    return merged


@router.post(
    "/{automation_id}/approvals/{request_id}/respond",
    response_model=ApprovalResponseOut,
)
async def respond_to_approval(
    automation_id: UUID,
    request_id: UUID,
    body: ApprovalResponseIn,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> ApprovalResponseOut:
    """Resolve an :class:`AutomationApprovalRequest` and (when allowed)
    enqueue ``resume_automation_run`` to continue the paused run.

    Concurrent resolutions are guarded by the ``resolved_at`` IS NOT NULL
    check — the second caller gets a 409. Resolutions are recorded as the
    canonical audit row on the request itself; the resume worker reads
    the response from the resolved row before re-entering the dispatcher.
    """
    automation = await _load_definition_or_404(db, automation_id)
    # Write access required — viewers can see approvals but not resolve them.
    await _authorize_definition(db, automation, user, write=True)

    request = (
        await db.execute(
            select(AutomationApprovalRequest).where(
                AutomationApprovalRequest.id == request_id
            )
        )
    ).scalar_one_or_none()
    if request is None:
        raise HTTPException(status_code=404, detail="Approval request not found")

    # Defence against cross-automation request_id lookups.
    run = (
        await db.execute(
            select(AutomationRun).where(AutomationRun.id == request.run_id)
        )
    ).scalar_one_or_none()
    if run is None or run.automation_id != automation_id:
        raise HTTPException(status_code=404, detail="Approval request not found")

    if request.resolved_at is not None:
        raise HTTPException(
            status_code=409, detail="Approval request already resolved"
        )

    if body.choice not in (request.options or []):
        raise HTTPException(
            status_code=400,
            detail=(
                f"choice {body.choice!r} not in offered options "
                f"{request.options!r}"
            ),
        )

    now = datetime.now(tz=UTC)
    request.resolved_at = now
    request.resolved_by_user_id = user.id
    request.response = {
        "choice": body.choice,
        "notes": body.notes,
        "scope_modifications": body.scope_modifications,
    }

    resume_enqueued = False
    new_run_status = run.status

    if body.choice == "allow_for_automation" and body.scope_modifications:
        automation.contract = _merge_scope_modifications(
            automation.contract or {}, body.scope_modifications
        )

    if body.choice in {
        "allow_once",
        "allow_for_run",
        "allow_for_automation",
        "restart_from_last_checkpoint",
    }:
        # Flag the run as queued so concurrent observers see the transition;
        # the resume worker flips it back to 'running' after hydrating.
        run.status = "queued"
        run.heartbeat_at = now
        run.paused_reason = None
        new_run_status = "queued"
    elif body.choice == "cancel_run":
        run.status = "cancelled"
        run.paused_reason = "cancelled via approval response"
        run.ended_at = now
        run.heartbeat_at = now
        new_run_status = "cancelled"
    elif body.choice == "deny":
        run.status = "failed"
        run.paused_reason = "denied via approval response"
        run.ended_at = now
        run.heartbeat_at = now
        new_run_status = "failed"
    elif body.choice == "deny_and_disable_automation":
        run.status = "failed"
        run.paused_reason = "denied + automation disabled"
        run.ended_at = now
        run.heartbeat_at = now
        automation.is_active = False
        automation.paused_reason = (
            f"disabled via approval response by user {user.id}"
        )
        new_run_status = "failed"

    await db.commit()

    if body.choice in {
        "allow_once",
        "allow_for_run",
        "allow_for_automation",
        "restart_from_last_checkpoint",
    }:
        try:
            from ..services.task_queue import get_task_queue

            await get_task_queue().enqueue(
                "resume_automation_run", str(run.id)
            )
            resume_enqueued = True
        except Exception as exc:  # noqa: BLE001 — enqueue must never fail the resolve
            logger.warning(
                "[AUTOMATIONS] resume enqueue failed run=%s err=%r — "
                "request resolved; controller / cron sweep will retry",
                run.id,
                exc,
            )

    logger.info(
        "[AUTOMATIONS] approval resolved automation=%s run=%s request=%s "
        "choice=%s by user=%s resume_enqueued=%s",
        automation.id,
        run.id,
        request.id,
        body.choice,
        user.id,
        resume_enqueued,
    )

    return ApprovalResponseOut(
        request_id=request.id,
        run_id=run.id,
        automation_id=automation.id,
        choice=body.choice,
        resolved_at=now,
        resume_enqueued=resume_enqueued,
        run_status=new_run_status,
    )


# Re-export Permission so tests can monkeypatch without import gymnastics.
__all__ = ["router", "Permission"]
