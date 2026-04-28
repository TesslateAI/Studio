"""Pydantic schemas for the Automation Runtime + App Action HTTP routers.

Phase 1. Mirrors the SQLAlchemy models in :mod:`app.models_automations` and
the dispatcher contracts in :mod:`app.services.automations.dispatcher` /
:mod:`app.services.apps.action_dispatcher`.

Conventions:

* Request bodies named ``*In`` / ``*Create`` / ``*Update``; response bodies
  named ``*Out``. Symmetric where it makes sense so the OpenAPI surface
  documents itself.
* ``contract`` is JSONB on the model and ``dict[str, Any]`` here. It is
  REQUIRED on create — the dispatcher refuses to run an automation without
  one (see ``dispatcher._validate_contract``); we reject early at the router
  boundary so the user gets a clean 400 instead of a deferred dispatch
  failure.
* Phase 1 single-action limitation is enforced both here (``actions`` must
  have length 1) and in the dispatcher (defence in depth — the router
  refuses bad input, the dispatcher refuses inconsistent rows even if a
  caller bypasses the router).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Trigger / Action / DeliveryTarget — nested input + output shapes
# ---------------------------------------------------------------------------


class AutomationTriggerIn(BaseModel):
    """One trigger rule. ``kind`` must match the model CHECK."""

    kind: str = Field(..., description="cron | webhook | app_invocation | manual")
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("kind")
    @classmethod
    def _validate_kind(cls, v: str) -> str:
        allowed = {"cron", "webhook", "app_invocation", "manual"}
        if v not in allowed:
            raise ValueError(f"trigger.kind must be one of {sorted(allowed)!r}, got {v!r}")
        return v


class AutomationTriggerOut(AutomationTriggerIn):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    is_active: bool
    created_at: datetime


class AutomationActionIn(BaseModel):
    """One action within the graph. Phase 1 = exactly one row, ordinal=0."""

    action_type: str = Field(..., description="agent.run | app.invoke | gateway.send")
    config: dict[str, Any] = Field(default_factory=dict)
    app_action_id: UUID | None = None
    ordinal: int = 0

    @field_validator("action_type")
    @classmethod
    def _validate_type(cls, v: str) -> str:
        allowed = {"agent.run", "app.invoke", "gateway.send"}
        if v not in allowed:
            raise ValueError(
                f"action.action_type must be one of {sorted(allowed)!r}, got {v!r}"
            )
        return v


class AutomationActionOut(AutomationActionIn):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime


class AutomationDeliveryTargetIn(BaseModel):
    destination_id: UUID
    ordinal: int = 0
    on_failure: dict[str, Any] = Field(default_factory=dict)
    artifact_filter: str = "all"


class AutomationDeliveryTargetOut(AutomationDeliveryTargetIn):
    model_config = ConfigDict(from_attributes=True)

    id: UUID


# ---------------------------------------------------------------------------
# AutomationDefinition — top-level CRUD
# ---------------------------------------------------------------------------


class AutomationDefinitionIn(BaseModel):
    """Create payload. Owner is taken from the authenticated user, never the body."""

    name: str = Field(..., max_length=200)
    workspace_scope: str = Field("none", description="none | user_automation_workspace | team_automation_workspace | target_project")
    workspace_project_id: UUID | None = None
    target_project_id: UUID | None = None
    team_id: UUID | None = None
    app_instance_id: UUID | None = None

    contract: dict[str, Any] = Field(
        ...,
        description=(
            "Contract JSONB — REQUIRED. Must include at minimum allowed_tools "
            "and max_compute_tier. The dispatcher validates structurally; the "
            "router rejects None / {} early."
        ),
    )

    max_compute_tier: int = 0
    max_spend_per_run_usd: Decimal | None = None
    max_spend_per_day_usd: Decimal | None = None

    triggers: list[AutomationTriggerIn] = Field(..., min_length=1)
    actions: list[AutomationActionIn] = Field(..., min_length=1, max_length=1)
    delivery_targets: list[AutomationDeliveryTargetIn] = Field(default_factory=list)

    @field_validator("contract")
    @classmethod
    def _contract_non_empty(cls, v: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(v, dict) or not v:
            raise ValueError("contract is required and must be a non-empty object")
        return v

    @field_validator("workspace_scope")
    @classmethod
    def _validate_scope(cls, v: str) -> str:
        allowed = {
            "none",
            "user_automation_workspace",
            "team_automation_workspace",
            "target_project",
        }
        if v not in allowed:
            raise ValueError(
                f"workspace_scope must be one of {sorted(allowed)!r}, got {v!r}"
            )
        return v


class AutomationDefinitionUpdate(BaseModel):
    """Patch payload. Lists ``triggers``/``actions``/``delivery_targets`` are
    replace-by-list when present (matches the UI's edit-modal semantics)."""

    name: str | None = Field(default=None, max_length=200)
    is_active: bool | None = None
    paused_reason: str | None = None
    contract: dict[str, Any] | None = None
    max_compute_tier: int | None = None
    max_spend_per_run_usd: Decimal | None = None
    max_spend_per_day_usd: Decimal | None = None

    triggers: list[AutomationTriggerIn] | None = None
    actions: list[AutomationActionIn] | None = None
    delivery_targets: list[AutomationDeliveryTargetIn] | None = None

    @field_validator("contract")
    @classmethod
    def _contract_non_empty(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        if v is None:
            return v
        if not isinstance(v, dict) or not v:
            raise ValueError("contract, when provided, must be a non-empty object")
        return v

    @field_validator("actions")
    @classmethod
    def _exactly_one_action(
        cls, v: list[AutomationActionIn] | None
    ) -> list[AutomationActionIn] | None:
        if v is None:
            return v
        if len(v) != 1:
            raise ValueError("phase 1 supports exactly one action per automation")
        return v


class AutomationDefinitionOut(BaseModel):
    """Single-row read; nested triggers/actions/delivery_targets included."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    owner_user_id: UUID
    team_id: UUID | None
    workspace_scope: str
    workspace_project_id: UUID | None
    target_project_id: UUID | None
    app_instance_id: UUID | None = None
    contract: dict[str, Any]
    max_compute_tier: int
    max_spend_per_run_usd: Decimal | None
    max_spend_per_day_usd: Decimal | None
    parent_automation_id: UUID | None
    depth: int
    is_active: bool
    paused_reason: str | None
    attribution_user_id: UUID | None
    created_by_user_id: UUID | None
    created_at: datetime
    updated_at: datetime

    triggers: list[AutomationTriggerOut] = Field(default_factory=list)
    actions: list[AutomationActionOut] = Field(default_factory=list)
    delivery_targets: list[AutomationDeliveryTargetOut] = Field(default_factory=list)


class AutomationDefinitionSummary(BaseModel):
    """Lightweight list-row projection (no nested children)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    owner_user_id: UUID
    team_id: UUID | None
    workspace_scope: str
    target_project_id: UUID | None
    app_instance_id: UUID | None = None
    is_active: bool
    paused_reason: str | None
    max_compute_tier: int
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Manual run + run inspection
# ---------------------------------------------------------------------------


class AutomationRunRequest(BaseModel):
    """Manual ``POST /run`` body. ``payload`` is opaque to the router;
    the dispatcher passes it to whichever action handler runs."""

    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None


class AutomationRunResponse(BaseModel):
    """Returned by ``POST /run``. Always 202 — the worker picks up the event."""

    automation_id: UUID
    run_id: UUID
    event_id: UUID
    status: str = "queued"


class AutomationRunArtifactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_id: UUID
    kind: str
    name: str
    mime_type: str | None
    storage_mode: str
    storage_ref: str
    preview_text: str | None
    size_bytes: int | None
    meta: dict[str, Any]
    created_at: datetime


class AutomationApprovalRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_id: UUID
    requested_at: datetime
    expires_at: datetime | None
    resolved_at: datetime | None
    resolved_by_user_id: UUID | None
    reason: str
    context: dict[str, Any]
    context_artifacts: list[Any]
    options: list[Any]
    delivered_to: list[Any]
    response: dict[str, Any] | None


_APPROVAL_CHOICES = frozenset(
    {
        "allow_once",
        "allow_for_run",
        "allow_for_automation",
        "deny",
        "deny_and_disable_automation",
        "cancel_run",
        "restart_from_last_checkpoint",
    }
)


class ApprovalResponseIn(BaseModel):
    """Body of ``POST /api/automations/{id}/approvals/{request_id}/respond``.

    ``choice`` is one of:
    * ``allow_once`` — let this single tool call through; future calls
      re-enter the gate.
    * ``allow_for_run`` — exempt the same tool/MCP/skill identifier for the
      remainder of this run only.
    * ``allow_for_automation`` — merge ``scope_modifications`` into the
      :attr:`AutomationDefinition.contract`. The merge happens in the
      router; the dispatcher reloads the contract on resume.
    * ``deny`` — terminate this run as ``failed``.
    * ``deny_and_disable_automation`` — also flip
      ``AutomationDefinition.is_active=False`` so future events don't fire.
    * ``cancel_run`` — restart-only-options resolution; mark the run
      cancelled.
    * ``restart_from_last_checkpoint`` — restart-only-options resolution;
      relaunch the agent from a clean history.
    """

    choice: str = Field(..., description="One of the approval option strings")
    notes: str | None = Field(default=None, max_length=2000)
    scope_modifications: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional contract delta merged into AutomationDefinition.contract "
            "when choice='allow_for_automation'. Top-level keys are merged "
            "shallowly; list values replace whole-list."
        ),
    )

    @field_validator("choice")
    @classmethod
    def _validate_choice(cls, v: str) -> str:
        if v not in _APPROVAL_CHOICES:
            raise ValueError(
                f"choice must be one of {sorted(_APPROVAL_CHOICES)!r}, got {v!r}"
            )
        return v


class ApprovalResponseOut(BaseModel):
    """Returned by the approval-response endpoint."""

    request_id: UUID
    run_id: UUID
    automation_id: UUID
    choice: str
    resolved_at: datetime
    resume_enqueued: bool
    run_status: str


class AutomationRunSummary(BaseModel):
    """Lightweight list-row projection of an AutomationRun."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    automation_id: UUID
    event_id: UUID | None
    status: str
    retry_count: int
    spend_usd: Decimal
    contract_breaches: int
    paused_reason: str | None
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime


class AutomationRunDetail(AutomationRunSummary):
    """Full run with nested artifacts and approval requests."""

    raw_output: Any | None = None
    artifacts: list[AutomationRunArtifactOut] = Field(default_factory=list)
    approval_requests: list[AutomationApprovalRequestOut] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# App Actions — direct external invocation
# ---------------------------------------------------------------------------


class AppActionInvokeRequest(BaseModel):
    """Body for ``POST /api/apps/{app_instance_id}/actions/{action_name}``."""

    input: dict[str, Any] = Field(default_factory=dict)


class AppActionInvokeResponse(BaseModel):
    """Wraps :class:`ActionDispatchResult`. Strings only for IDs so JSON is
    portable across tenants without Pydantic UUID-coercion drift."""

    output: dict[str, Any]
    artifacts: list[UUID]
    spend_usd: Decimal
    duration_seconds: float
    error: str | None = None


class AppActionRow(BaseModel):
    """One row in the per-install action listing."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    timeout_seconds: int | None = None
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    required_connectors: list[Any] = Field(default_factory=list)
    required_grants: list[Any] = Field(default_factory=list)


class AppActionListResponse(BaseModel):
    app_instance_id: UUID
    app_version_id: UUID
    actions: list[AppActionRow]


__all__ = [
    "AutomationTriggerIn",
    "AutomationTriggerOut",
    "AutomationActionIn",
    "AutomationActionOut",
    "AutomationDeliveryTargetIn",
    "AutomationDeliveryTargetOut",
    "AutomationDefinitionIn",
    "AutomationDefinitionUpdate",
    "AutomationDefinitionOut",
    "AutomationDefinitionSummary",
    "AutomationRunRequest",
    "AutomationRunResponse",
    "AutomationRunSummary",
    "AutomationRunDetail",
    "AutomationRunArtifactOut",
    "AutomationApprovalRequestOut",
    "ApprovalResponseIn",
    "ApprovalResponseOut",
    "AppActionInvokeRequest",
    "AppActionInvokeResponse",
    "AppActionRow",
    "AppActionListResponse",
]
