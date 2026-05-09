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
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Trigger / Action / DeliveryTarget — nested input + output shapes
# ---------------------------------------------------------------------------


class AutomationTriggerIn(BaseModel):
    """One trigger rule. ``kind`` must match the model CHECK.

    ``app_invocation`` is reserved in the DB CHECK constraint and the
    feature-flag registry (``apps.triggers.app_invocation``, default OFF —
    see ``config_features.py``) but has **no producer** in this codebase
    today: nothing writes ``automation_events`` rows with
    ``trigger_kind='app_invocation'``. To prevent silently-dead trigger
    rows, the API rejects the kind here. Re-add to the allowed-set when
    the producer lands; the DB CHECK already permits it so no migration
    is needed at that point.

    Tracking: TesslateAI/OpenSail-Enterprise#408 (Phase 1 follow-up —
    "unified dispatch_automation for cron/webhook/app_invocation" was
    scoped but the app_invocation producer never landed).
    """

    kind: str = Field(..., description="cron | webhook | manual")
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("kind")
    @classmethod
    def _validate_kind(cls, v: str) -> str:
        allowed = {"cron", "webhook", "manual"}
        if v == "app_invocation":
            # See class docstring + TesslateAI/OpenSail-Enterprise#408.
            raise ValueError(
                "trigger.kind='app_invocation' is reserved but not yet wired — "
                "no producer exists. Use 'cron', 'webhook', or 'manual'."
            )
        if v not in allowed:
            raise ValueError(f"trigger.kind must be one of {sorted(allowed)!r}, got {v!r}")
        return v

    @model_validator(mode="after")
    def _validate_cron_config(self) -> AutomationTriggerIn:
        # Without this, a typo like ``* * * *`` (4 fields) was silently coerced
        # to an empty string at save and combined with ``next_run_at IS NULL``
        # in cron_producer, fired on every leader-tick.
        if self.kind != "cron":
            return self
        cfg = self.config or {}
        expr = cfg.get("expression") or cfg.get("cron_expression") or ""
        if not isinstance(expr, str) or not expr.strip():
            raise ValueError(
                "cron trigger requires a non-empty 'expression' in config "
                "(e.g. '*/5 * * * *' for every five minutes)"
            )
        # croniter accepts 6-field (seconds-first) and 7-field
        # (seconds + year) forms, but the producer ticks every 15s and
        # next_run_at is computed at minute resolution — sub-minute schedules
        # were silently rounded to multi-minute fires. Reject anything other
        # than the standard 5-field grammar so user intent matches behavior.
        field_count = len(expr.strip().split())
        if field_count != 5:
            raise ValueError(
                f"cron trigger has invalid expression {expr!r}: "
                "must use the 5-field format 'minute hour day month weekday' "
                "(sub-minute schedules are not supported)"
            )
        try:
            croniter(expr.strip())
        except (ValueError, KeyError) as exc:
            raise ValueError(
                f"cron trigger has invalid expression {expr!r}: {exc}"
            ) from exc
        # Symmetrically with expression: a missing / empty timezone used
        # to silently fall back to UTC at evaluation time, which made DST
        # and "9 AM local" semantics invisible. Require an explicit IANA
        # name (or "UTC") on the wire so the user's intent is recorded.
        tz = cfg.get("timezone")
        if not isinstance(tz, str) or not tz.strip():
            raise ValueError(
                "cron trigger requires a non-empty 'timezone' in config "
                "(e.g. 'America/New_York' or 'UTC')"
            )
        if tz != "UTC":
            try:
                ZoneInfo(tz)
            except (ZoneInfoNotFoundError, KeyError, ValueError) as exc:
                raise ValueError(
                    f"cron trigger has invalid timezone {tz!r}: {exc}"
                ) from exc
        return self


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
            raise ValueError(f"action.action_type must be one of {sorted(allowed)!r}, got {v!r}")
        return v

    @model_validator(mode="after")
    def _validate_action_config(self) -> AutomationActionIn:
        # gateway.send must have a message body — without this, actions
        # could save with config={} and runs completed in ms with
        # status=succeeded while never sending anything. The dispatcher
        # reads ``config.body`` / ``config.body_template``; rejecting both
        # empty here keeps the run from looking "Done" when it had nothing
        # to deliver.
        if self.action_type == "gateway.send":
            cfg = self.config or {}
            body = cfg.get("body") or cfg.get("body_template")
            if not isinstance(body, str) or not body.strip():
                raise ValueError(
                    "gateway.send action requires a non-empty 'body' "
                    "(the message to send)"
                )
        return self


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
    workspace_scope: str = Field(
        "none",
        description="none | user_automation_workspace | team_automation_workspace | target_project",
    )
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
            raise ValueError(f"workspace_scope must be one of {sorted(allowed)!r}, got {v!r}")
        return v

    @model_validator(mode="after")
    def _validate_gateway_send_has_target(self) -> AutomationDefinitionIn:
        # Refuse to mark an automation Active when it has a gateway.send
        # action but no delivery target wired up. The dispatcher would
        # otherwise return ``delivered: True`` against an empty set and the
        # run shows "succeeded" with $0 spend.
        has_gateway_send = any(a.action_type == "gateway.send" for a in self.actions)
        if has_gateway_send and not self.delivery_targets:
            raise ValueError(
                "Automations with a 'gateway.send' action require at least one "
                "delivery target (set 'Where to send the result')."
            )
        return self


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

    @model_validator(mode="after")
    def _validate_gateway_send_has_target(self) -> AutomationDefinitionUpdate:
        # Mirror of the create-time check — only enforce when the caller is
        # actually replacing both lists in the same patch. Replacing only
        # ``actions`` means the existing delivery_targets stay; we trust
        # those (the create-time validator already guarded them).
        if self.actions is None or self.delivery_targets is None:
            return self
        has_gateway_send = any(a.action_type == "gateway.send" for a in self.actions)
        if has_gateway_send and not self.delivery_targets:
            raise ValueError(
                "Automations with a 'gateway.send' action require at least one "
                "delivery target (set 'Where to send the result')."
            )
        return self


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
            raise ValueError(f"choice must be one of {sorted(_APPROVAL_CHOICES)!r}, got {v!r}")
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
