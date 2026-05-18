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

    kind: str = Field(
        ...,
        description="cron | webhook | manual | slack_message | email_inbound | workflow_event",
    )
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("kind")
    @classmethod
    def _validate_kind(cls, v: str) -> str:
        # Phase E (#474) added slack_message + email_inbound as
        # user-facing trigger kinds. Internally those will be wrapped on
        # save into the canonical kind='webhook' with config.source so
        # they ride on develop's per-automation /webhook/{token} +
        # HMAC infrastructure (follow-up adapter refactor).
        # Phase G6 (#473) added workflow_event for inter-workflow
        # subscriptions (used by the per-workflow doctor and any
        # sub-workflow that watches another's lifecycle events). This
        # one is internal pub/sub, NOT an HTTP transport, so it stays a
        # first-class kind.
        allowed = {
            "cron",
            "webhook",
            "manual",
            "slack_message",
            "email_inbound",
            "workflow_event",
        }
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
        # Phase D (#473) added ``deliver``. Phase F (#475) added
        # ``sub_workflow`` and ``branch`` (engine wires them);
        # ``parallel`` is reserved for a Phase F follow-up.
        allowed = {
            "agent.run",
            "app.invoke",
            "gateway.send",
            "deliver",
            "sub_workflow",
            "branch",
            "parallel",
        }
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
        # agent.run must declare which agent runs. Without this, the worker
        # historically (a) crashed on ``UUID(None)`` for a missing key, (b)
        # crashed on a non-UUID string with a leaked ValueError, or (c)
        # silently fell back to "the first active IterativeAgent" — running
        # the wrong agent on the user's behalf with no warning. Catch all
        # three at the wire so the failure is a clean 422 at assign time.
        # Existence/scope/type checks live one layer up in
        # ``routers/automations._replace_actions`` because they need the
        # DB session + caller identity (which Pydantic validators can't
        # see). Order is intentional: parse here, authorize there.
        if self.action_type == "agent.run":
            cfg = self.config or {}
            raw = cfg.get("agent_id")
            if raw is None or (isinstance(raw, str) and not raw.strip()):
                raise ValueError(
                    "agent.run action requires 'config.agent_id' (the "
                    "marketplace agent UUID)"
                )
            if not isinstance(raw, str | UUID):
                raise ValueError(
                    f"agent.run action 'config.agent_id' must be a UUID "
                    f"string, got {type(raw).__name__}"
                )
            try:
                UUID(str(raw))
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"agent.run action 'config.agent_id' is not a valid "
                    f"UUID: {raw!r}"
                ) from exc
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


# Contract keys mirrored from the AutomationDefinition columns so the
# dispatcher (which reads ``contract.get(...)``) and the column-level
# enforcement stay in sync. Adding a new key here is a one-liner; every
# reconciliation path picks it up automatically.
_SPEND_CAP_CONTRACT_KEYS: tuple[str, ...] = (
    "max_spend_per_run_usd",
    "max_spend_per_day_usd",
)


def _reconcile_spend_cap(
    *,
    column_value: Decimal | None,
    contract_value: Any,
    key: str,
) -> Decimal | None:
    """Reconcile a single spend-cap surface between column and contract.

    Returns the merged value as ``Decimal`` (or ``None`` when neither
    side set it). Raises ``ValueError`` if both sides are set and they
    disagree — same pattern as ``_reconcile_compute_tier``. Whichever
    side the caller populated is honored; the other side gets the same
    value written into it by the validators that call this helper.
    """
    if contract_value is None:
        return column_value
    try:
        contract_decimal = Decimal(str(contract_value))
    except (TypeError, ValueError, ArithmeticError) as exc:
        raise ValueError(f"contract.{key} must be a numeric value") from exc
    if column_value is None:
        return contract_decimal
    if Decimal(column_value) != contract_decimal:
        raise ValueError(
            f"contract.{key}={contract_decimal} disagrees with column "
            f"{key}={column_value}; remove one or set them equal."
        )
    return contract_decimal


def _decimal_to_json_safe(value: Decimal | None) -> float | None:
    """Convert a ``Decimal`` cap to a JSON-serializable scalar.

    The ``automation_definitions.contract`` column is a JSON dict that
    serializes via ``json.dumps`` — which has no native ``Decimal`` codec.
    Cast to ``float`` so the value round-trips through Postgres and the
    dispatcher's ``Decimal(str(value))`` coercion picks it back up
    cleanly. ``None`` passes through.
    """
    return None if value is None else float(value)


def _enforce_spend_cap_invariants(
    *,
    per_run: Decimal | None,
    per_day: Decimal | None,
) -> None:
    """Reject zero caps and per-run > per-day inversions.

    Called from both Create and Update validators. Keeping the rule set in
    one place means the same 422 surface appears for both write paths.
    """
    if per_run is not None and per_run <= 0:
        raise ValueError(
            "max_spend_per_run_usd must be strictly positive; omit the "
            "field to disable the cap."
        )
    if per_day is not None and per_day <= 0:
        raise ValueError(
            "max_spend_per_day_usd must be strictly positive; omit the "
            "field to disable the cap."
        )
    if per_run is not None and per_day is not None and per_run > per_day:
        raise ValueError(
            f"max_spend_per_run_usd (${per_run}) cannot exceed "
            f"max_spend_per_day_usd (${per_day}); raise the daily cap "
            f"or lower the per-run cap."
        )


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

    # Phase B (#471). Default persistent_workspace keeps existing
    # callers unchanged; connector_only opts into the lightweight tier.
    compute_profile: str = "persistent_workspace"

    triggers: list[AutomationTriggerIn] = Field(..., min_length=1)
    # Phase A (#470) lifted the 1-action cap. The workflow engine in
    # services/workflows/ walks ordinal-ordered actions when there are
    # more than one; single-action automations stay on the legacy path.
    actions: list[AutomationActionIn] = Field(..., min_length=1, max_length=64)
    delivery_targets: list[AutomationDeliveryTargetIn] = Field(default_factory=list)

    @field_validator("contract")
    @classmethod
    def _validate_contract_schema(cls, v: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(v, dict) or not v:
            raise ValueError("contract is required and must be a non-empty object")
        # Defer the structural rules to the dispatcher's validator so the
        # router and run-time agree on the schema. Without this the user
        # could persist a malformed contract via POST/PATCH and only see
        # the failure on the next dispatch (TC-04 Bug #28).
        from .services.automations.dispatcher import (
            ContractInvalid,
            validate_contract,
        )

        try:
            validate_contract(v)
        except ContractInvalid as exc:
            raise ValueError(str(exc)) from exc
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

    @field_validator("compute_profile")
    @classmethod
    def _validate_profile(cls, v: str) -> str:
        # Phase B (#471). Mirrors the CHECK on automation_definitions.
        allowed = {"connector_only", "ephemeral_workspace", "persistent_workspace"}
        if v not in allowed:
            raise ValueError(f"compute_profile must be one of {sorted(allowed)!r}, got {v!r}")
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

    @model_validator(mode="after")
    def _reconcile_compute_tier(self) -> AutomationDefinitionIn:
        # The dispatcher branches on the column ``automation_definitions
        # .max_compute_tier`` to pick Tier-0 vs Tier-1+ routing, while
        # ContractGate enforces ``contract.max_compute_tier`` per tool.
        # If they disagree the routing tier and the per-tool cap drift
        # apart silently — see TC-04 Bug #29. Force them equal at write
        # time so there's a single source of truth.
        from .services.automations.dispatcher import MAX_KNOWN_COMPUTE_TIER

        if self.max_compute_tier < 0:
            raise ValueError("max_compute_tier must be non-negative")
        if self.max_compute_tier > MAX_KNOWN_COMPUTE_TIER:
            raise ValueError(
                f"max_compute_tier={self.max_compute_tier} exceeds the highest "
                f"wired tier ({MAX_KNOWN_COMPUTE_TIER})."
            )

        contract_tier = self.contract.get("max_compute_tier")
        if contract_tier is not None and contract_tier != self.max_compute_tier:
            raise ValueError(
                f"contract.max_compute_tier={contract_tier} disagrees with "
                f"max_compute_tier={self.max_compute_tier}; remove one or "
                f"set them equal."
            )
        # Mirror the column into the contract so the gate cap and the
        # dispatcher routing always match for downstream readers.
        self.contract["max_compute_tier"] = self.max_compute_tier
        return self

    @model_validator(mode="after")
    def _reconcile_spend_caps(self) -> AutomationDefinitionIn:
        # Mirror the AutomationDefinition column values into the contract
        # JSONB so the dispatcher's ``contract.get("max_spend_per_run_usd")``
        # gate (services/automations/dispatcher.py and budget.py) sees what
        # the user actually configured. Without this mirror the UI form
        # silently dropped budget caps because it submits the column-level
        # field outside the contract dict.
        column_pair = {
            "max_spend_per_run_usd": self.max_spend_per_run_usd,
            "max_spend_per_day_usd": self.max_spend_per_day_usd,
        }
        merged: dict[str, Decimal | None] = {}
        for key in _SPEND_CAP_CONTRACT_KEYS:
            merged[key] = _reconcile_spend_cap(
                column_value=column_pair[key],
                contract_value=self.contract.get(key),
                key=key,
            )

        _enforce_spend_cap_invariants(
            per_run=merged["max_spend_per_run_usd"],
            per_day=merged["max_spend_per_day_usd"],
        )

        # Propagate merged values to both surfaces so downstream readers
        # (which may use either) stay in lockstep. The contract dict is
        # JSON-serialized; use a float scalar so ``json.dumps`` doesn't
        # choke on ``Decimal`` — the dispatcher re-coerces via
        # ``Decimal(str(value))`` on read so precision is preserved.
        self.max_spend_per_run_usd = merged["max_spend_per_run_usd"]
        self.max_spend_per_day_usd = merged["max_spend_per_day_usd"]
        for key, value in merged.items():
            json_value = _decimal_to_json_safe(value)
            if json_value is None:
                self.contract.pop(key, None)
            else:
                self.contract[key] = json_value
        return self

    @model_validator(mode="after")
    def _validate_scope_tier_constraint(self) -> AutomationDefinitionIn:
        # Mirrors the DB CHECK ``ck_automation_definitions_scope_none_tier_zero``
        # so the user gets a typed 422 with field-level guidance instead of
        # an unhandled IntegrityError surfaced as raw HTTP 500 (Bug #31).
        # ``workspace_scope='none'`` means the automation has no associated
        # storage — there's nothing for a Tier-1+ ephemeral pod to mount, so
        # the dispatcher's tier routing has no destination.
        if self.workspace_scope == "none" and self.max_compute_tier > 0:
            raise ValueError(
                f"max_compute_tier={self.max_compute_tier} requires a "
                f"workspace_scope other than 'none' (Tier-1+ runs need a "
                f"workspace to mount). Either pick a workspace scope (personal "
                f"folder, team folder, or target project) or drop the power "
                f"level to Light (max_compute_tier=0)."
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
    compute_profile: str | None = None

    triggers: list[AutomationTriggerIn] | None = None
    actions: list[AutomationActionIn] | None = None
    delivery_targets: list[AutomationDeliveryTargetIn] | None = None

    @field_validator("contract")
    @classmethod
    def _validate_contract_schema(
        cls, v: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if v is None:
            return v
        if not isinstance(v, dict) or not v:
            raise ValueError("contract, when provided, must be a non-empty object")
        # Mirror of the create-time validator so PATCH gets the same 422
        # surface — see TC-04 Bug #28.
        from .services.automations.dispatcher import (
            ContractInvalid,
            validate_contract,
        )

        try:
            validate_contract(v)
        except ContractInvalid as exc:
            raise ValueError(str(exc)) from exc
        return v

    @field_validator("actions")
    @classmethod
    def _actions_within_cap(
        cls, v: list[AutomationActionIn] | None
    ) -> list[AutomationActionIn] | None:
        # Phase A (#470) lifted the 1-action cap. The workflow engine
        # walks ordinal-ordered actions when there is more than one.
        if v is None:
            return v
        if len(v) > 64:
            raise ValueError("automation may not have more than 64 actions")
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

    @model_validator(mode="after")
    def _reconcile_compute_tier(self) -> AutomationDefinitionUpdate:
        # Same reconciliation as the create-time validator — kicks in
        # only when the caller actually patched at least one of the two
        # tier surfaces. See TC-04 Bug #29.
        from .services.automations.dispatcher import MAX_KNOWN_COMPUTE_TIER

        contract_tier = (
            self.contract.get("max_compute_tier") if self.contract is not None else None
        )
        column_tier = self.max_compute_tier

        if column_tier is None and contract_tier is None:
            return self

        # Whichever side the caller set, validate range and propagate to
        # the other so the dispatcher and gate stay in sync.
        if column_tier is not None:
            if column_tier < 0:
                raise ValueError("max_compute_tier must be non-negative")
            if column_tier > MAX_KNOWN_COMPUTE_TIER:
                raise ValueError(
                    f"max_compute_tier={column_tier} exceeds the highest "
                    f"wired tier ({MAX_KNOWN_COMPUTE_TIER})."
                )

        if column_tier is not None and contract_tier is not None:
            if column_tier != contract_tier:
                raise ValueError(
                    f"contract.max_compute_tier={contract_tier} disagrees with "
                    f"max_compute_tier={column_tier}; remove one or set them equal."
                )
        elif column_tier is not None and self.contract is not None:
            self.contract["max_compute_tier"] = column_tier
        return self

    @model_validator(mode="after")
    def _reconcile_spend_caps(self) -> AutomationDefinitionUpdate:
        # Mirror of the create-time spend-cap reconciliation. PATCH semantics:
        # only enforce when the caller actually touched at least one of the
        # four surfaces (column per-run, column per-day, or either contract
        # key). If the caller only patches ``contract`` and leaves the
        # columns out, we still mirror the contract values back into the
        # column-typed fields so the projector / dispatcher see a single
        # source of truth.
        column_pair = {
            "max_spend_per_run_usd": self.max_spend_per_run_usd,
            "max_spend_per_day_usd": self.max_spend_per_day_usd,
        }
        contract_pair = {
            key: (self.contract.get(key) if self.contract is not None else None)
            for key in _SPEND_CAP_CONTRACT_KEYS
        }
        if all(v is None for v in column_pair.values()) and all(
            v is None for v in contract_pair.values()
        ):
            return self

        merged: dict[str, Decimal | None] = {}
        for key in _SPEND_CAP_CONTRACT_KEYS:
            merged[key] = _reconcile_spend_cap(
                column_value=column_pair[key],
                contract_value=contract_pair[key],
                key=key,
            )

        _enforce_spend_cap_invariants(
            per_run=merged["max_spend_per_run_usd"],
            per_day=merged["max_spend_per_day_usd"],
        )

        # Propagate merged values back into the patch payload so the router
        # writes both surfaces consistently. The router applies non-None
        # fields, so we only set what we have. The contract dict is JSON-
        # serialized; mirror the Decimal as a float so ``json.dumps``
        # round-trips safely.
        for key, value in merged.items():
            if value is not None:
                setattr(self, key, value)
        if self.contract is not None:
            for key, value in merged.items():
                json_value = _decimal_to_json_safe(value)
                if json_value is None:
                    self.contract.pop(key, None)
                else:
                    self.contract[key] = json_value
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
    compute_profile: str = "persistent_workspace"
    # G1 (#469): live version pointer. Null only for definitions
    # that pre-date G1 and haven't dispatched yet.
    head_version_id: UUID | None = None
    # G5 (#473): self-healing doctor wiring. doctor_enabled mirrors the
    # column; doctor_automation_id points at the child workflow that
    # watches this one's failures.
    doctor_enabled: bool = False
    doctor_automation_id: UUID | None = None
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
    # Resolved at read time from the run's :class:`InvocationSubject` row.
    # ``None`` means the worker never wrote the subject — typically because
    # the agent failed to load (see ``raw_output.error``) or because the
    # row predates the audit-identity wiring (TC-03 Bug #19). Surfacing
    # both lets the UI render "Ran as: <name>" without an extra round-trip
    # and lets manager dashboards attribute spend by agent without joining
    # client-side.
    agent_id: UUID | None = None
    agent_name: str | None = None


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
