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

import contextlib
import logging
import secrets as _stdlib_secrets
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import MarketplaceAgent, User
from ..models_automations import (
    AppAction,
    AutomationAction,
    AutomationApprovalRequest,
    AutomationDefinition,
    AutomationDeliveryTarget,
    AutomationEvent,
    AutomationRun,
    AutomationRunArtifact,
    AutomationTrigger,
    InvocationSubject,
)
from ..permissions import Permission, get_team_membership
from ..schemas_automations import (
    ApprovalResponseIn,
    ApprovalResponseOut,
    AutomationActionIn,
    AutomationActionOut,
    AutomationApprovalRequestOut,
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
from ..services.marketplace_agent_scope import (
    AgentScopeError,
    resolve_agent_in_user_scope,
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
                    detail=(f"Role '{membership.role}' may not edit this automation"),
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
        app_instance_id=definition.app_instance_id,
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
        delivery_targets=[AutomationDeliveryTargetOut.model_validate(t) for t in targets],
    )


# ---------------------------------------------------------------------------
# Child-row replacement (used by create + patch when caller supplies lists)
# ---------------------------------------------------------------------------


def _compute_next_run_at(config: dict[str, Any]) -> datetime | None:
    """Compute the next cron boundary for a trigger config, in UTC.

    Returns ``None`` for non-cron / malformed triggers — callers persist
    ``next_run_at`` only when this returns a real datetime. The schema
    validator already rejects malformed cron, so reaching here with bad
    input is defensive (callers that bypass the schema still don't trip).
    """
    expr = (config.get("expression") or config.get("cron_expression") or "").strip()
    if not expr:
        return None
    tz_name = config.get("timezone") or "UTC"
    try:
        tz = ZoneInfo(tz_name) if tz_name and tz_name != "UTC" else UTC
    except (ZoneInfoNotFoundError, KeyError, ValueError):
        return None
    now = datetime.now(UTC)
    try:
        local_now = now.astimezone(tz)
        iter_ = croniter(expr, local_now)
        local_next = iter_.get_next(datetime)
    except (ValueError, KeyError):
        return None
    if local_next.tzinfo is None:
        local_next = local_next.replace(tzinfo=tz)
    return local_next.astimezone(UTC)


def _mint_webhook_secret() -> dict[str, Any]:
    """Generate a fresh entry for ``config.webhook_secrets[]``.

    Matches the rotation-friendly shape consumed by
    :func:`app.routers.app_triggers._candidate_secrets`. The secret is a
    URL-safe 32-byte token; ``kid='v1'`` for the first-mint case (rotation
    is appended by a future endpoint, not by this helper).
    """
    return {
        "kid": "v1",
        "secret": _stdlib_secrets.token_urlsafe(32),
        "created_at": datetime.now(tz=UTC).isoformat(),
        "revoked_at": None,
    }


async def _replace_triggers(
    db: AsyncSession,
    automation_id: UUID,
    triggers: list[AutomationTriggerIn],
) -> None:
    """Replace the trigger rows for an automation.

    Standalone webhook triggers (``kind='webhook'`` and no
    ``config.app_instance_id``) are auto-provisioned with a URL path
    ``token`` and an HMAC ``webhook_secrets[]`` entry on first save. The
    pair is **preserved across PATCH**: we read existing webhook rows
    before the wholesale delete and reuse their token/secrets when the
    incoming config doesn't carry them. Without this preservation, every
    PATCH to a webhook automation would rotate the URL and break
    deployed callers — silently.
    """
    # Snapshot existing webhook tokens/secrets BEFORE the wholesale delete
    # so PATCH calls that round-trip the trigger don't regenerate them.
    existing_webhook_token: str | None = None
    existing_webhook_secrets: list[Any] | None = None
    existing_rows = (
        (
            await db.execute(
                select(AutomationTrigger).where(
                    AutomationTrigger.automation_id == automation_id,
                    AutomationTrigger.kind == "webhook",
                )
            )
        )
        .scalars()
        .all()
    )
    for row in existing_rows:
        cfg = row.config or {}
        if not isinstance(cfg, dict):
            continue
        if existing_webhook_token is None and isinstance(cfg.get("token"), str):
            existing_webhook_token = cfg["token"]
        if existing_webhook_secrets is None and isinstance(
            cfg.get("webhook_secrets"), list
        ):
            existing_webhook_secrets = cfg["webhook_secrets"]

    await db.execute(
        delete(AutomationTrigger).where(AutomationTrigger.automation_id == automation_id)
    )
    for trig in triggers:
        config = dict(trig.config or {})
        # Pre-compute next_run_at on insert so the cron producer doesn't
        # treat the row as "due now" on the next leader-tick. Without
        # this, a freshly-saved cron fires once ~30-60s after save
        # regardless of schedule.
        next_run_at = (
            _compute_next_run_at(config) if trig.kind == "cron" else None
        )
        if trig.kind == "webhook" and not config.get("app_instance_id"):
            # Standalone webhook — keyed by automation_id + path token. The
            # public ingest route is mounted by ``routers/app_triggers.py``
            # at ``POST /api/automations/{automation_id}/webhook/{token}``.
            if not isinstance(config.get("token"), str) or not config["token"].strip():
                config["token"] = (
                    existing_webhook_token or _stdlib_secrets.token_urlsafe(16)
                )
            has_list = isinstance(config.get("webhook_secrets"), list) and config["webhook_secrets"]
            has_legacy = isinstance(config.get("webhook_secret"), str) and config["webhook_secret"]
            if not has_list and not has_legacy:
                config["webhook_secrets"] = (
                    existing_webhook_secrets
                    if existing_webhook_secrets
                    else [_mint_webhook_secret()]
                )
        db.add(
            AutomationTrigger(
                id=uuid4(),
                automation_id=automation_id,
                kind=trig.kind,
                config=config,
                is_active=True,
                next_run_at=next_run_at,
            )
        )


async def _replace_actions(
    db: AsyncSession,
    automation_id: UUID,
    actions: list[AutomationActionIn],
    *,
    user: User,
) -> None:
    """Replace the action rows for an automation.

    For ``agent.run`` actions, the agent UUID must be reachable for the
    caller (existence + correct ``item_type`` + active + library scope).
    The schema validator already enforces the wire shape (present,
    UUID-parseable); this is the DB-aware second layer the schema can't
    do — it needs the session and the caller identity. Resolution is
    delegated to :func:`resolve_agent_in_user_scope` so the picker, the
    automation API, and the apps installer all agree on what "in scope"
    means (TC-03 Bug #21).
    """
    # Validate every agent.run binding BEFORE we delete the existing rows.
    # A partial-validation failure on row N would otherwise leave the
    # automation actionless mid-PATCH.
    for action in actions:
        if action.action_type != "agent.run":
            continue
        cfg = action.config or {}
        # Schema validator already rejects missing / non-UUID values;
        # this UUID(...) call is total under that contract.
        agent_uuid = UUID(str(cfg["agent_id"]))
        try:
            await resolve_agent_in_user_scope(db, agent_id=agent_uuid, user=user)
        except AgentScopeError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Validate every app.invoke binding's ``config.input`` against the
    # referenced AppAction's ``input_schema``. The dispatcher does this at
    # run time (``services/apps/action_dispatcher._validate_schema``); doing
    # it again at save time fails the user fast — at the edit surface —
    # instead of N minutes later inside a queued run.
    for action in actions:
        if action.action_type != "app.invoke":
            continue
        if action.app_action_id is None:
            # Schema-level guard would normally catch this; leave to the
            # existing wire-shape validator and skip here. ``None`` means
            # the user hasn't picked an action yet — defer to run-time.
            continue
        row = (
            await db.execute(
                select(AppAction).where(AppAction.id == action.app_action_id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(
                status_code=422,
                detail=f"app_action {action.app_action_id} not found",
            )
        schema = row.input_schema
        if not schema:
            continue
        input_value = (action.config or {}).get("input")
        if input_value is None:
            input_value = {}
        try:
            import jsonschema
            from jsonschema.exceptions import ValidationError as _JSV

            jsonschema.Draft202012Validator(schema).validate(input_value)
        except _JSV as exc:
            # Structured-detail shape: include path + message so the UI
            # can render a per-field error inline instead of one toast.
            raise HTTPException(
                status_code=422,
                detail={
                    "message": (
                        f"action.config.input fails {row.name!r} input_schema: "
                        f"{exc.message}"
                    ),
                    "errors": [
                        {
                            "path": list(exc.absolute_path),
                            "message": exc.message,
                            "validator": exc.validator,
                        }
                    ],
                },
            ) from exc

    await db.execute(
        delete(AutomationAction).where(AutomationAction.automation_id == automation_id)
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


async def _load_definition_or_404(db: AsyncSession, automation_id: UUID) -> AutomationDefinition:
    row = (
        await db.execute(
            select(AutomationDefinition).where(AutomationDefinition.id == automation_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Automation not found")
    return row


# ---------------------------------------------------------------------------
# Cross-automation run listing (must be registered before the
# ``/{automation_id}`` dynamic routes so FastAPI matches the static segment
# first).
# ---------------------------------------------------------------------------


@router.get(
    "/runs/by-install/{app_instance_id}",
    response_model=list[AutomationRunSummary],
)
async def list_runs_by_install(
    app_instance_id: UUID,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    status_filter: str | None = Query(default=None, alias="status"),
) -> list[AutomationRunSummary]:
    """Recent runs across every automation linked to one ``AppInstance``.

    Surfaces in the per-app drawer's "Runs" tab. Without this the UI would
    have to fan out one ``listRuns(automation_id)`` call per automation
    (N+1) and merge — this single query keeps the drawer cheap regardless
    of how many automations the user has wired into the install.

    Auth model: the caller must own the install (``installer_user_id``).
    Team-shared installs are out of scope here — the per-app drawer is
    always rendered for the install's owner. We 404 (not 403) on miss to
    match the existing leak-resistant pattern in this router.
    """
    from ..models_automations import AppInstance

    ai = (
        await db.execute(select(AppInstance).where(AppInstance.id == app_instance_id))
    ).scalar_one_or_none()
    if ai is None or (ai.installer_user_id != user.id and not getattr(user, "is_superuser", False)):
        raise HTTPException(status_code=404, detail="App install not found")

    query = (
        select(AutomationRun)
        .join(
            AutomationDefinition,
            AutomationDefinition.id == AutomationRun.automation_id,
        )
        .where(AutomationDefinition.app_instance_id == app_instance_id)
        .order_by(AutomationRun.created_at.desc())
    )
    if status_filter is not None:
        query = query.where(AutomationRun.status == status_filter)
    query = query.limit(limit).offset(offset)

    rows = (await db.execute(query)).scalars().all()
    return [AutomationRunSummary.model_validate(r) for r in rows]


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
    app_instance_id: UUID | None = Query(
        default=None,
        description=(
            "Scope the list to automations linked to a specific AppInstance. "
            "Used by the per-app drawer in the workspace UI."
        ),
    ),
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
    if app_instance_id is not None:
        query = query.where(AutomationDefinition.app_instance_id == app_instance_id)

    query = query.order_by(AutomationDefinition.created_at.desc()).limit(limit).offset(offset)

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

    # Validate the app_instance_id (when provided) is one the caller can
    # see. Reusing the same 404 pattern as ``_authorize_definition`` so we
    # don't leak existence of someone else's install.
    if payload.app_instance_id is not None:
        from ..models_automations import AppInstance

        ai = (
            await db.execute(select(AppInstance).where(AppInstance.id == payload.app_instance_id))
        ).scalar_one_or_none()
        if ai is None or ai.installer_user_id != user.id:
            raise HTTPException(
                status_code=404,
                detail="App install not found",
            )

    automation = AutomationDefinition(
        id=uuid4(),
        name=payload.name,
        owner_user_id=user.id,
        team_id=payload.team_id,
        workspace_scope=payload.workspace_scope,
        workspace_project_id=payload.workspace_project_id,
        target_project_id=payload.target_project_id,
        app_instance_id=payload.app_instance_id,
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
    await _replace_actions(db, automation.id, payload.actions, user=user)
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
        await _replace_actions(db, automation.id, payload.actions, user=user)
    if payload.delivery_targets is not None:
        await _replace_delivery_targets(db, automation.id, payload.delivery_targets)

    # Mirrors the create-time scope/tier check against the *merged* row state
    # (Pydantic on the update payload can't see fields the patch didn't touch).
    # Without this an existing scope='none' row patched to tier=2, or a
    # scope='none' patched onto a tier=2 row, hits the DB CHECK
    # ``ck_automation_definitions_scope_none_tier_zero`` and surfaces as a
    # raw HTTP 500 (Bug #31).
    if automation.workspace_scope == "none" and automation.max_compute_tier > 0:
        raise HTTPException(
            status_code=422,
            detail=(
                f"max_compute_tier={automation.max_compute_tier} requires a "
                f"workspace_scope other than 'none' (Tier-1+ runs need a "
                f"workspace to mount). Either pick a workspace scope or drop "
                f"the power level to Light (max_compute_tier=0)."
            ),
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
        logger.info("[AUTOMATIONS] hard-deleted id=%s by user=%s", automation_id, user.id)
        return {"status": "deleted", "id": str(automation_id), "hard": True}

    automation.is_active = False
    automation.paused_reason = "deleted_by_user"
    await db.commit()
    logger.info("[AUTOMATIONS] soft-deleted id=%s by user=%s", automation_id, user.id)
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

    Flow: insert :class:`AutomationEvent`, then call
    :func:`dispatch_automation` **synchronously** so the response carries a
    real ``run_id`` for the UI to navigate to.

    Why synchronous (not enqueue-and-return): the manual-run UX navigates the
    user straight to the run page. An enqueue-only path would have to either
    omit ``run_id`` (UI poll required) or pre-create the run row at
    ``status='queued'`` — but a pre-created queued row collides with the
    dispatcher's idempotency branch table (``existing_status == 'queued'`` →
    ``NOOP_INFLIGHT``), so the dispatcher would refuse to progress it past
    queued. Calling the dispatcher inline lets it own the run row creation
    (``_upsert_run`` with ``inserted=True``) and continue through Phase B
    preflight + executor enqueue in one shot. Webhook / cron / gateway
    triggers all go through the ARQ wrapper for the same dispatcher; only
    this user-initiated path runs sync because the user is waiting.

    ``trigger_kind='manual'`` and ``trigger_id=None`` are valid — the events
    table has no NOT NULL on ``trigger_id`` and the kind CHECK includes
    ``'manual'`` (migration 0074).
    """
    payload = payload or AutomationRunRequest()
    automation = await _load_definition_or_404(db, automation_id)
    await _authorize_definition(db, automation, user, write=True)

    if not automation.is_active:
        raise HTTPException(status_code=409, detail="Automation is paused / inactive")

    # Snapshot the user PK *before* any commit. ``user`` is a SQLAlchemy ORM
    # instance attached to this async session; ``db.rollback()`` in the
    # idempotency-dedup branch below expires every loaded attribute, and the
    # next ``user.id`` access would trigger a sync refresh via the asyncpg
    # cursor → ``MissingGreenlet``. Holding a plain UUID sidesteps the
    # descriptor entirely (same value, no lifecycle).
    user_id = user.id

    event = AutomationEvent(
        id=uuid4(),
        automation_id=automation_id,
        trigger_id=None,  # manual runs have no trigger row
        trigger_kind="manual",
        payload=payload.payload or {},
        idempotency_key=payload.idempotency_key,
        received_at=datetime.now(tz=UTC),
    )
    # Capture the new event id BEFORE the commit so the downstream dispatch
    # path doesn't have to read it back off an ORM instance — that read
    # would hit a sync lazy-load after a rollback in the dedup branch and
    # trigger ``MissingGreenlet`` in async context.
    event_id = event.id
    db.add(event)
    try:
        await db.commit()
    except IntegrityError:
        # ``uq_automation_events_idempotency_key`` is partial-unique on
        # ``idempotency_key WHERE NOT NULL`` — a collision means the caller
        # is replaying a manual run with the same key. Resolve by routing
        # through the existing event so the dispatcher's idempotent run
        # upsert returns the original run unchanged. Without this branch
        # the asyncpg ``UniqueViolationError`` propagated as a bare 500
        # and the caller had no way to recover.
        await db.rollback()
        if payload.idempotency_key is None:
            # No key on the payload but a unique constraint fired — the
            # only such constraint is the idempotency-key index, so this
            # is unreachable in practice. Re-raise rather than mask.
            raise
        # Column-level select to avoid post-rollback ORM lazy-load. After
        # ``db.rollback()`` SQLAlchemy expires every loaded attribute on
        # any orphaned ORM instance; the next ``existing.automation_id``
        # access would otherwise trigger a sync refresh via the asyncpg
        # cursor and raise ``MissingGreenlet``. Returning scalars sidesteps
        # the descriptor entirely.
        row = (
            await db.execute(
                select(
                    AutomationEvent.id, AutomationEvent.automation_id
                ).where(AutomationEvent.idempotency_key == payload.idempotency_key)
            )
        ).first()
        if row is None:
            # Constraint fired but the row vanished (e.g. concurrent delete).
            # Surface a typed 409 — clearer than a 500.
            raise HTTPException(
                status_code=409,
                detail="idempotency_key conflict and original event no longer exists",
            ) from None
        existing_event_id, existing_automation_id = row
        # Use the route parameter ``automation_id`` (a plain UUID) for the
        # comparison and the log below — ``automation.id`` would trigger a
        # post-rollback ORM lazy-load on the still-in-scope ``automation``
        # instance and raise ``MissingGreenlet`` in the async session.
        if existing_automation_id != automation_id:
            raise HTTPException(
                status_code=409,
                detail="idempotency_key already used on a different automation",
            ) from None
        event_id = existing_event_id
        logger.info(
            "[AUTOMATIONS] manual run idempotent replay automation=%s "
            "event=%s key=%r user=%s",
            automation_id,
            event_id,
            payload.idempotency_key,
            user_id,
        )

    # Synchronously dispatch. The dispatcher creates the run row via its own
    # idempotent upsert (Phase A) and proceeds through Phase B preflight,
    # routing to the executor (``agent.run`` enqueues ``execute_agent_task``;
    # ``app.invoke`` calls the action handler; ``gateway.send`` writes to the
    # delivery stream). The ``DispatchResult.run_id`` is always populated.
    from ..services.automations.dispatcher import dispatch_automation

    try:
        result = await dispatch_automation(
            db,
            automation_id=automation_id,
            event_id=event_id,
            worker_id=f"manual:{user_id}",
        )
    except Exception:
        logger.exception(
            "[AUTOMATIONS] manual dispatch failed automation=%s event=%s "
            "user=%s — event row persists; controller sweep will retry",
            automation_id,
            event_id,
            user_id,
        )
        # Best-effort rollback of any half-applied dispatcher state. The event
        # row is already committed above, so the missed-event drain
        # (``services.automations.missed_event_drain``) will pick it up.
        with contextlib.suppress(Exception):  # pragma: no cover — defensive
            await db.rollback()
        raise HTTPException(
            status_code=500,
            detail="dispatch failed — run will be retried by the controller",
        ) from None

    logger.info(
        "[AUTOMATIONS] manual run automation=%s run=%s event=%s status=%s by user=%s",
        automation_id,
        result.run_id,
        event_id,
        result.run_status,
        user_id,
    )
    return AutomationRunResponse(
        automation_id=automation_id,
        run_id=result.run_id,
        event_id=event_id,
        status=result.run_status,
    )


# ---------------------------------------------------------------------------
# Run inspection
# ---------------------------------------------------------------------------


@router.get("/{automation_id}/runs", response_model=list[AutomationRunSummary])
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


@router.get("/{automation_id}/runs/{run_id}", response_model=AutomationRunDetail)
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

    # Resolve the agent identity from the InvocationSubject row written
    # by the worker when the agent loaded. Single SELECT so we don't
    # pay an N+1 across the runs list. ``ORDER BY id`` is a stable tie-break
    # in the unlikely event a future Phase writes more than one subject
    # per run (parent-run rollup).
    subject_row = (
        await db.execute(
            select(InvocationSubject.agent_id, MarketplaceAgent.name)
            .outerjoin(
                MarketplaceAgent, MarketplaceAgent.id == InvocationSubject.agent_id
            )
            .where(InvocationSubject.automation_run_id == run_id)
            .order_by(InvocationSubject.created_at.asc())
            .limit(1)
        )
    ).first()
    agent_id = subject_row[0] if subject_row else None
    agent_name = subject_row[1] if subject_row else None

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
        approval_requests=[AutomationApprovalRequestOut.model_validate(a) for a in approvals],
        agent_id=agent_id,
        agent_name=agent_name,
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


@router.get("/{automation_id}/runs/{run_id}/steps")
async def list_run_steps(
    automation_id: UUID,
    run_id: UUID,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Append-only agent step trace for a run.

    Only ``agent.run`` actions produce steps — the worker writes one
    :class:`AgentStep` per iteration tied to the assistant ``Message``
    it created (the message's ``message_metadata.task_id`` carries the
    automation run id). ``app.invoke`` and ``gateway.send`` runs return
    ``[]`` (the UI surfaces their data via ``raw_output`` / artifacts).

    Without this endpoint the RunDetailPage's Steps tab silently rendered
    "No steps recorded" because its fetch hit a 404 that the client
    swallowed.
    """
    automation = await _load_definition_or_404(db, automation_id)
    await _authorize_definition(db, automation, user, write=False)

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

    from ..models import AgentStep, Message

    # The worker stamps ``message_metadata.task_id = str(run.id)`` on the
    # assistant message it creates. Prefer the direct link the worker
    # writes into ``automation_runs.raw_output['message_id']`` at finalize
    # time — it's a string-equality lookup with no JSON-path coercion
    # and works on every backend (TC-04 Bug #23 saw the JSONB ``->>``
    # cast silently miss when the metadata column type differed across
    # alembic revisions). The metadata lookup is kept as a fallback for
    # mid-flight runs that haven't finalised yet.
    run_row = (
        await db.execute(select(AutomationRun.raw_output).where(AutomationRun.id == run_id))
    ).scalar_one_or_none()

    message_id = None
    if isinstance(run_row, dict):
        raw_message_id = run_row.get("message_id")
        if raw_message_id:
            try:
                message_id = UUID(str(raw_message_id))
            except (TypeError, ValueError):
                message_id = None

    if message_id is None:
        message_id = (
            await db.execute(
                select(Message.id).where(
                    Message.message_metadata["task_id"].as_string() == str(run_id)
                )
            )
        ).scalar_one_or_none()
    if message_id is None:
        return []

    rows = (
        (
            await db.execute(
                select(AgentStep)
                .where(AgentStep.message_id == message_id)
                .order_by(AgentStep.step_index.asc())
            )
        )
        .scalars()
        .all()
    )

    return _serialize_agent_steps(rows)


def _serialize_agent_steps(rows: list[Any]) -> list[dict[str, Any]]:
    """Render ``AgentStep`` rows for the Steps tab.

    Fans out one entry per tool call so multi-tool iterations are not
    silently collapsed to the first call (TC-04 Bug #25). Each entry
    carries an explicit ``status`` derived from the captured tool
    result so completed tool calls don't sit at ``running`` forever
    (TC-04 Bug #24).
    """
    out: list[dict[str, Any]] = []
    for row in rows:
        data = row.step_data or {}
        tool_calls = list(data.get("tool_calls") or [])
        tool_results = list(data.get("tool_results") or [])
        thought = data.get("thought")
        response_text = data.get("response_text") or ""
        name = data.get("name") or data.get("step_name")
        created_at = row.created_at.isoformat() if row.created_at else None
        is_complete = bool(data.get("is_complete"))

        if tool_calls:
            for sub_idx, tc in enumerate(tool_calls):
                # Tool call entries embedded under ``step_data.tool_calls``
                # may already carry their own result via the worker's
                # ``_build_step_dict`` shape (``{name, parameters, result}``)
                # OR be paired through a sibling ``tool_results`` array.
                # Tolerate both so older + newer rows render the same way.
                if isinstance(tc, dict) and "result" in tc:
                    tool_result = tc.get("result")
                elif sub_idx < len(tool_results):
                    tool_result = tool_results[sub_idx]
                else:
                    tool_result = None

                out.append(
                    {
                        "id": f"{row.id}:{sub_idx}",
                        "ordinal": row.step_index,
                        "name": name,
                        # Surface the thought once per row so the UI keeps
                        # the iteration narrative without duplicating it
                        # across every fan-out entry.
                        "thought": thought if sub_idx == 0 else None,
                        "tool_name": tc.get("name") if isinstance(tc, dict) else None,
                        "input": tc.get("parameters") if isinstance(tc, dict) else None,
                        "output": tool_result,
                        "status": _derive_step_status(
                            tool_call=tc,
                            tool_result=tool_result,
                            is_complete=is_complete,
                        ),
                        "created_at": created_at,
                    }
                )
            continue

        # Thought-only / response-only iteration — keep one entry so the
        # narrative doesn't drop turns where the model only spoke.
        out.append(
            {
                "id": str(row.id),
                "ordinal": row.step_index,
                "name": name,
                "thought": thought,
                "tool_name": None,
                "input": None,
                "output": response_text or None,
                "status": "complete" if is_complete or response_text else "running",
                "created_at": created_at,
            }
        )
    return out


def _derive_step_status(
    *,
    tool_call: Any,
    tool_result: Any,
    is_complete: bool,
) -> str:
    """Derive a tool-call step's terminal status from the captured result.

    Worker-side ``_build_step_dict`` does not stamp a status field on
    each tool entry — without this derivation every tool row sits at
    ``running`` forever even though the run is terminal. The shape
    inside ``tool_result`` mirrors ``ToolRegistry.execute``: a dict with
    ``success`` (success / failure), ``approval_required`` (paused),
    or empty ``{}`` (still in flight before the worker captured a
    result).
    """
    if isinstance(tool_result, dict):
        if tool_result.get("approval_required"):
            return "waiting_approval"
        if tool_result.get("contract_breach"):
            return "denied"
        if tool_result.get("success") is False:
            return "failed"
        if "success" in tool_result or "result" in tool_result or tool_result.get("error"):
            return "complete"
    if is_complete:
        return "complete"
    # No captured result yet and the run hasn't completed — genuinely
    # in-flight. Mid-flight polling lands here.
    return "running"


@router.get("/{automation_id}/runs/{run_id}/spend")
async def get_run_spend(
    automation_id: UUID,
    run_id: UUID,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Spend rollup for a single run.

    Phase 5 surfaces ``automation_runs.spend_by_source`` (the JSON blob
    written by the dispatcher) plus a per-app breakdown joined from
    :class:`SpendRecord`. The full join is intentionally minimal here —
    the UI handles missing dimensions gracefully and shows an empty-state
    when the rollup is not yet available.

    The endpoint is read-only and inherits the same ownership/team-membership
    gates as the rest of the automation routes.
    """
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

    spend_by_source: dict[str, Any] = run.spend_by_source or {}

    # Per-app breakdown — best-effort SpendRecord join. We do not import
    # SpendRecord at module level to avoid a circular import at startup
    # (the model graph crosses billing/automation packages); a deferred
    # import keeps the route resilient when the table is absent in older
    # alembic revisions.
    per_app: list[dict[str, Any]] = []
    try:
        from ..models import SpendRecord  # local import — see comment above

        rows = (
            await db.execute(
                select(
                    SpendRecord.app_instance_id,
                    func.sum(SpendRecord.amount_usd).label("total"),
                )
                .where(SpendRecord.automation_run_id == run_id)
                .group_by(SpendRecord.app_instance_id)
            )
        ).all()
        for app_instance_id, total in rows:
            per_app.append(
                {
                    "app_instance_id": (
                        str(app_instance_id) if app_instance_id is not None else None
                    ),
                    # Phase 5 stub: name resolution lives in the apps router;
                    # leaving null lets the UI fall back to the id.
                    "app_name": None,
                    "amount_usd": str(total) if total is not None else "0",
                }
            )
    except Exception as exc:  # noqa: BLE001 — never block the rollup on join issues
        logger.debug("[AUTOMATIONS] spend per-app join skipped run=%s err=%r", run_id, exc)

    return {"spend_by_source": spend_by_source, "per_app": per_app}


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
        await db.execute(select(AutomationRun.automation_id).where(AutomationRun.id == run_id))
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


def _merge_scope_modifications(contract: dict[str, Any], delta: dict[str, Any]) -> dict[str, Any]:
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
            select(AutomationApprovalRequest).where(AutomationApprovalRequest.id == request_id)
        )
    ).scalar_one_or_none()
    if request is None:
        raise HTTPException(status_code=404, detail="Approval request not found")

    # Defence against cross-automation request_id lookups.
    run = (
        await db.execute(select(AutomationRun).where(AutomationRun.id == request.run_id))
    ).scalar_one_or_none()
    if run is None or run.automation_id != automation_id:
        raise HTTPException(status_code=404, detail="Approval request not found")

    if request.resolved_at is not None:
        raise HTTPException(status_code=409, detail="Approval request already resolved")

    if body.choice not in (request.options or []):
        raise HTTPException(
            status_code=400,
            detail=(f"choice {body.choice!r} not in offered options {request.options!r}"),
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
        automation.paused_reason = f"disabled via approval response by user {user.id}"
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

            await get_task_queue().enqueue("resume_automation_run", str(run.id))
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
