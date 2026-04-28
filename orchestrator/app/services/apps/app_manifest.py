"""Pydantic mirror of the app manifest schemas.

The JSON Schema files (``app_manifest_<version>.schema.json``) are the
structural source of truth (hash-pinned in tests). This module provides
typed access for code that reads a parsed manifest. Keep field names and
enum values identical to the corresponding schema.

Two manifest models live here:

* :class:`AppManifest` — legacy 2025-01 / 2025-02 shape (compute/state/listing).
* :class:`AppManifest2026_05` — App Runtime Contract (runtime/billing/actions/
  views/data_resources/dependencies/connectors[].exposure/automation_templates).

Phase 0 ships the 2026-05 mirror alongside the legacy model so installers and
projection writers can begin reading typed fields without breaking the
existing 2025-01 / 2025-02 install paths.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# The literal that newly-emitted manifests carry. Existing 2025-01 / 2025-02
# manifests remain valid for read; only new publishes target this version.
MANIFEST_SCHEMA_VERSION: Literal["2026-05"] = "2026-05"

# Every manifest_schema_version the parser knows how to validate.
SUPPORTED_SCHEMA_VERSIONS: tuple[str, ...] = ("2025-01", "2025-02", "2026-05")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# 2025-01 mirror (legacy — kept verbatim for backward compatibility).
# ---------------------------------------------------------------------------


class AppMeta(_StrictModel):
    id: str
    name: str
    slug: str
    version: str
    creator_id: str | None = None
    description: str | None = None
    category: str | None = None
    icon_ref: str | None = None
    changelog: str | None = None
    forkable: Literal["true", "restricted", "no"] = "restricted"
    forked_from: str | None = None


class SourceVisibility(_StrictModel):
    level: Literal["public", "installers", "private"] = "installers"
    excluded_paths: list[str] = Field(
        default_factory=lambda: [".env*", "secrets/**", ".git/**", ".tesslate/internal/**"]
    )
    manifest_always_public: bool = True


class StudioRange(_StrictModel):
    min: str
    max: str | None = None


class Compatibility(_StrictModel):
    studio: StudioRange
    manifest_schema: Literal["2025-01"]
    runtime_api: str
    required_features: list[str] = Field(default_factory=list)


class SurfaceSpec(_StrictModel):
    kind: Literal["ui", "chat", "scheduled", "triggered", "mcp-tool"]
    entrypoint: str
    tool_schema: dict[str, Any] | None = None


class ContainerSpec(BaseModel):
    """Lax container spec — existing .tesslate/config.json containers may include
    fields not enumerated here; we intentionally allow extras to avoid coupling
    manifest v1 to today's base_config_parser shape."""

    model_config = ConfigDict(extra="allow")

    name: str
    image: str


class HostedAgentSpec(_StrictModel):
    id: str
    system_prompt_ref: str
    model_pref: str | None = None
    tools_ref: list[str] = Field(default_factory=list)
    mcps_ref: list[str] = Field(default_factory=list)
    temperature: float | None = None
    max_tokens: int | None = None
    thinking_effort: str | None = None
    warm_pool_size: int | None = None


class Compute(_StrictModel):
    tier: Literal[0, 1, 2] = 0
    compute_model: Literal["per-invocation", "per-installer", "shared-singleton"] = "per-invocation"
    containers: list[ContainerSpec] = Field(default_factory=list)
    hosted_agents: list[HostedAgentSpec] = Field(default_factory=list)


class ByoDatabase(_StrictModel):
    # `schema_` with alias keeps the JSON key `schema` while avoiding the
    # pydantic v2 warning about shadowing BaseModel.schema.
    schema_: str | None = Field(default=None, alias="schema")
    connection_env: str | None = None
    external_db_version: str | None = None

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class StateSpec(_StrictModel):
    model: Literal["stateless", "per-install-volume", "byo-database"]
    volume_size: str | None = None
    byo_database: ByoDatabase | None = None


class ConnectorSpec(_StrictModel):
    id: str
    kind: Literal["mcp", "api_key", "oauth", "webhook"]
    scopes: list[str] = Field(default_factory=list)
    required: bool = True
    oauth: bool = False
    secret_key: str | None = None


class ScheduleSpec(_StrictModel):
    name: str
    entrypoint: str
    default_cron: str | None = None
    editable: bool = True
    optional: bool = True


class MigrationSpec(_StrictModel):
    from_: str = Field(alias="from")
    to: str
    auto_safe: bool = False
    up: str | None = None
    down: str | None = None

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class FreeTier(BaseModel):
    model_config = ConfigDict(extra="allow")

    cpu_seconds_per_month: int | None = None
    volume_gb: float | None = None


class DimensionBilling(_StrictModel):
    payer: Literal["creator", "platform", "installer", "byok"]
    markup_pct: float = 0
    cap_usd_per_session: float | None = None
    cap_usd_per_month_per_install: float | None = None
    on_cap: Literal["pause", "degrade", "notify-only"] = "pause"
    free_tier: FreeTier | None = None


class PlatformFee(_StrictModel):
    model: Literal["free", "one_time", "subscription", "per_invocation"]
    price_usd: float = 0
    billing_period: Literal["monthly", "yearly"] | None = None
    trial_days: int = 0


class PromotionalBudget(_StrictModel):
    fund_usd: float = 0
    covers: list[Literal["ai_compute", "general_compute", "platform_fee"]] = Field(default_factory=list)
    on_exhaust: Literal["disable", "flip_to_installer", "degrade_to_free"] = "flip_to_installer"


class Billing(_StrictModel):
    ai_compute: DimensionBilling
    general_compute: DimensionBilling
    platform_fee: PlatformFee
    promotional_budget: PromotionalBudget | None = None


class Listing(_StrictModel):
    visibility: str  # "public" | "private" | "team:<uuid>"
    update_policy_default: Literal["manual", "patch-auto", "minor-auto", "pinned"] = "manual"
    minimum_rollback_version: str | None = None


class EvalScenario(_StrictModel):
    entrypoint: str
    input: Any
    expected_behavior: str


class AppManifest(_StrictModel):
    """Parsed, strongly-typed view of a 2025-01 app.manifest.json.

    2025-02 manifests are validated structurally only; they continue to
    parse via the JSON Schema and consumers fall back to the raw dict for
    fields not modeled here (this preserves the prior behavior).
    """

    manifest_schema_version: Literal["2025-01"]
    app: AppMeta
    compatibility: Compatibility
    surfaces: list[SurfaceSpec] = Field(min_length=1)
    state: StateSpec
    billing: Billing
    listing: Listing
    source_visibility: SourceVisibility = Field(default_factory=SourceVisibility)
    compute: Compute = Field(default_factory=Compute)
    connectors: list[ConnectorSpec] = Field(default_factory=list)
    schedules: list[ScheduleSpec] = Field(default_factory=list)
    migrations: list[MigrationSpec] = Field(default_factory=list)
    eval_scenarios: list[EvalScenario] = Field(default_factory=list, min_length=0)


# ---------------------------------------------------------------------------
# 2026-05 mirror — App Runtime Contract.
#
# Field names and enum values mirror app_manifest_2026_05.schema.json
# verbatim. Cross-field validators below enforce the rules the JSON Schema
# cannot express (oauth+env rejection, state_model⟹max_replicas, and
# data_resources[].backed_by_action referential integrity).
# ---------------------------------------------------------------------------


class AppMeta2026(_StrictModel):
    """App identity block. ``slug`` is optional in 2026-05 — derived at
    publish time from ``id`` when omitted (matches the v9 spec where the
    creator-facing manifest carries reverse-DNS id only)."""

    id: str
    name: str
    version: str
    slug: str | None = None
    description: str | None = None
    category: str | None = None
    icon_ref: str | None = None
    changelog: str | None = None
    forkable: bool = False
    forked_from: str | None = None


class RuntimeScalingSpec(_StrictModel):
    min_replicas: int = 0
    max_replicas: int = 1
    target_concurrency: int = 10
    idle_timeout_seconds: int = 600


class RuntimeStorageSpec(_StrictModel):
    """Required when ``runtime.state_model`` references a volume
    (``per_install_volume`` | ``service_pvc`` | ``shared_volume``)."""

    write_scope: list[str] = Field(min_length=1)


# Top-level enum aliases — surfaced for code that needs to type-check values
# without importing the inner Literal.
TenancyModel = Literal["per_install", "shared_singleton", "per_invocation"]
StateModel = Literal[
    "stateless", "per_install_volume", "service_pvc", "shared_volume", "external"
]


class RuntimeSpec(_StrictModel):
    tenancy_model: TenancyModel
    state_model: StateModel
    scaling: RuntimeScalingSpec = Field(default_factory=RuntimeScalingSpec)
    storage: RuntimeStorageSpec | None = None


PayerPolicyChoice = Literal["creator", "platform", "installer", "byok", "team"]


class PayerPolicySpec(_StrictModel):
    """Payer routing for a billable dimension (ai_compute / general_compute)."""

    payer_default: PayerPolicyChoice | None = None
    rate_percent: float | None = None


class PlatformFeeSpec(_StrictModel):
    rate_percent: float = 0
    model: Literal["free", "one_time", "subscription", "per_invocation"] = "free"
    price_usd: float = 0
    billing_period: Literal["monthly", "yearly"] | None = None
    trial_days: int = 0


class BillingSpec(_StrictModel):
    ai_compute: PayerPolicySpec
    general_compute: PayerPolicySpec
    platform_fee: PlatformFeeSpec


SurfaceKind2026 = Literal["ui", "chat", "full_page", "card", "drawer", "mcp_tool"]


class SurfaceSpec2026(_StrictModel):
    kind: SurfaceKind2026
    name: str | None = None
    description: str | None = None
    entrypoint: str | None = None
    container: str | None = None
    tool_schema: dict[str, Any] | None = None


class ActionHandlerSpec(_StrictModel):
    kind: Literal["http_post", "k8s_job", "hosted_agent"]
    container: str | None = None
    path: str | None = None


class ActionIdempotencySpec(_StrictModel):
    """Idempotency policy for an action invocation. ``kind`` is the strategy
    (``input_hash`` is the most common — derive a key from canonical input
    bytes; ``explicit_key`` lets the caller supply one; ``none`` opts out)."""

    kind: Literal["none", "input_hash", "explicit_key"]
    ttl_seconds: int | None = None


class ActionBillingDimensionSpec(_StrictModel):
    dimension: Literal["ai_compute", "general_compute"] | None = None
    payer_default: PayerPolicyChoice | None = None


class ActionBillingSpec(_StrictModel):
    ai_compute: ActionBillingDimensionSpec | None = None
    general_compute: ActionBillingDimensionSpec | None = None


class ActionRequiredGrantResource(_StrictModel):
    kind: str
    id: str


class ActionRequiredGrantSpec(_StrictModel):
    capability: str
    resource: ActionRequiredGrantResource


ArtifactKind = Literal[
    "text",
    "json",
    "file",
    "log",
    "report",
    "image",
    "screenshot",
    "csv",
    "markdown",
    "delivery_receipt",
]


class ActionArtifactSpec(_StrictModel):
    name: str
    kind: ArtifactKind
    from_: str | None = Field(default=None, alias="from")
    mime_type: str | None = None

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ActionSpec(_StrictModel):
    name: str
    description: str | None = None
    handler: ActionHandlerSpec
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    timeout_seconds: int = 60
    idempotency: ActionIdempotencySpec | None = None
    billing: ActionBillingSpec | None = None
    required_connectors: list[str] = Field(default_factory=list)
    required_grants: list[ActionRequiredGrantSpec] = Field(default_factory=list)
    result_template: str | None = None
    artifacts: list[ActionArtifactSpec] = Field(default_factory=list)


class ViewSpec(_StrictModel):
    name: str
    kind: Literal["card", "full_page", "drawer"]
    entrypoint: str
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    cache_ttl_seconds: int = 0


class DataResourceSpec(_StrictModel):
    name: str
    backed_by_action: str
    # ``schema_`` aliased to ``schema`` for the same reason as ByoDatabase:
    # avoid pydantic v2's BaseModel.schema shadow warning.
    schema_: dict[str, Any] = Field(alias="schema")
    cache_ttl_seconds: int = 0

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class DependencyNeedsSpec(_StrictModel):
    actions: list[str] = Field(default_factory=list)
    views: list[str] = Field(default_factory=list)
    data_resources: list[str] = Field(default_factory=list)


class DependencySpec(_StrictModel):
    alias: str
    app_id: str
    required: bool = True
    needs: DependencyNeedsSpec | None = None


ConnectorKind = Literal["mcp", "api_key", "oauth", "webhook"]
ConnectorExposure = Literal["proxy", "env"]


class ConnectorSpec2026(_StrictModel):
    """Connector requirement. ``exposure`` is REQUIRED — no implicit default.

    ``kind='oauth'`` + ``exposure='env'`` is rejected at validation: handing
    a rotating OAuth token to the app process defeats rotation and risks
    the token leaking in logs/error traces.
    """

    id: str
    kind: ConnectorKind
    exposure: ConnectorExposure
    scopes: list[str] = Field(default_factory=list)
    required: bool = True
    secret_key: str | None = None

    @model_validator(mode="after")
    def _reject_oauth_env(self) -> "ConnectorSpec2026":
        if self.kind == "oauth" and self.exposure == "env":
            raise ValueError(
                "connectors[].exposure='env' is not allowed when kind='oauth' "
                "(OAuth tokens rotate; env injection defeats rotation)"
            )
        return self


class AutomationTriggerSpec(BaseModel):
    """Trigger definition for an app-suggested automation. ``kind`` is
    constrained but the surrounding payload is free-form (cron expressions,
    webhook config, app-event filters) — extras allowed for forward compat."""

    model_config = ConfigDict(extra="allow")

    kind: Literal["cron", "webhook", "app_event", "manual"]
    expression: str | None = None


class AutomationActionSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    kind: Literal["app.invoke", "agent.run", "gateway.send", "workflow.run"]
    action: str | None = None
    input: dict[str, Any] | None = None


class AutomationDeliverySpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    kind: str | None = None


class AutomationTemplateSpec(_StrictModel):
    name: str
    description: str | None = None
    trigger: AutomationTriggerSpec
    action: AutomationActionSpec
    delivery: AutomationDeliverySpec | None = None
    contract_template: dict[str, Any] | None = None
    is_default_enabled: bool = False


class AppManifest2026_05(_StrictModel):
    """Parsed, strongly-typed view of a 2026-05 App Runtime Contract manifest.

    Only ``manifest_schema_version``, ``app``, ``runtime``, and ``billing``
    are required at the top level; every other block defaults to an empty
    list when omitted, matching the v9 spec rule that the parser does not
    punish a creator who writes an app with no actions/views/etc.
    """

    manifest_schema_version: Literal["2026-05"]
    app: AppMeta2026
    runtime: RuntimeSpec
    billing: BillingSpec
    surfaces: list[SurfaceSpec2026] = Field(default_factory=list)
    actions: list[ActionSpec] = Field(default_factory=list)
    views: list[ViewSpec] = Field(default_factory=list)
    data_resources: list[DataResourceSpec] = Field(default_factory=list)
    dependencies: list[DependencySpec] = Field(default_factory=list)
    connectors: list[ConnectorSpec2026] = Field(default_factory=list)
    automation_templates: list[AutomationTemplateSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_data_resource_action_refs(self) -> "AppManifest2026_05":
        action_names = {a.name for a in self.actions}
        for resource in self.data_resources:
            if resource.backed_by_action not in action_names:
                raise ValueError(
                    f"data_resources[].backed_by_action={resource.backed_by_action!r} "
                    f"does not reference any name in actions[]"
                )
        return self

    @model_validator(mode="after")
    def _check_state_model_replica_constraints(self) -> "AppManifest2026_05":
        # per_install_volume and service_pvc both pin replicas to <= 1 because
        # there is exactly one PVC and replicas would race over it. Other
        # state models (stateless / shared_volume RWX / external) are
        # unbounded by this rule.
        max_one_state_models = {"per_install_volume", "service_pvc"}
        if self.runtime.state_model in max_one_state_models:
            if self.runtime.scaling.max_replicas > 1:
                raise ValueError(
                    f"runtime.state_model={self.runtime.state_model!r} requires "
                    f"runtime.scaling.max_replicas <= 1 (got "
                    f"{self.runtime.scaling.max_replicas})"
                )
        return self
