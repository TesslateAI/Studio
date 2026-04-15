"""Pydantic mirror of app_manifest_2025_01.schema.json.

The JSON Schema is the source of truth for structural validation (hash-pinned
at test time). This module provides typed access for code that reads a parsed
manifest. Keep field names and enum values identical to the schema.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

MANIFEST_SCHEMA_VERSION: Literal["2025-01"] = "2025-01"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


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
    """Parsed, strongly-typed view of an app.manifest.json (v1 / 2025-01)."""

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
