"""Automation Runtime + App Runtime Contract models (Phase 1).

These tables land in alembic ``0074_hard_reset_automation_runtime`` as part
of the Phase 1 hard reset. They are intentionally defined in a separate
module from ``app/models.py`` so the Phase 0 attribution columns on
``SpendRecord`` can settle without merge churn.

The full model graph is documented in
``/Users/smirk/.claude/plans/ultrathink-i-want-to-glittery-pond.md`` —
sections "Architecture & Primitives" and "Hard Reset Migration".

All UUID columns use the ``GUID`` ``TypeDecorator`` so the same models
work on Postgres (cloud) and SQLite (desktop sidecar). USD amounts use
``Numeric(12, 4)`` per the plan.

Naming is conservative: ``automation_*`` for runtime tables, ``app_*``
for projection tables. ``app_instances`` and ``app_install_attempts`` are
recreated by the same migration with shapes that mirror their predecessor
plus a ``runtime_deployment_id`` column reserved for Phase 3.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.types.guid import GUID

from .database import Base

# ---------------------------------------------------------------------------
# Automation Runtime — durable execution graph
# ---------------------------------------------------------------------------


class AutomationDefinition(Base):
    """Owner-configurable automation: trigger rules + action graph + contract.

    Replaces the legacy ``agent_schedules`` row under the Phase 1 hard reset.
    A definition is pure configuration; runs live on ``automation_runs``.
    """

    __tablename__ = "automation_definitions"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False)
    owner_user_id = Column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    team_id = Column(
        GUID(), ForeignKey("teams.id", ondelete="CASCADE"), nullable=True, index=True
    )

    # none | user_automation_workspace | team_automation_workspace | target_project
    workspace_scope = Column(String(48), nullable=False, server_default="none")
    workspace_project_id = Column(
        GUID(), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    target_project_id = Column(
        GUID(), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )

    contract = Column(JSON, nullable=False)

    # Compute / spend ceilings — enforced by ContractGate at runtime.
    max_compute_tier = Column(Integer, nullable=False, default=0, server_default="0")
    max_spend_per_run_usd = Column(Numeric(12, 4), nullable=True)
    max_spend_per_day_usd = Column(Numeric(12, 4), nullable=True)

    # Provenance for the agent-builder skill (depth-1 cap).
    parent_automation_id = Column(
        GUID(),
        ForeignKey("automation_definitions.id", ondelete="SET NULL"),
        nullable=True,
    )
    depth = Column(Integer, nullable=False, default=0, server_default="0")

    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    paused_reason = Column(Text, nullable=True)

    # Shared-singleton billing: routes all runs of this definition to one
    # human's wallet/credits regardless of who triggered them.
    attribution_user_id = Column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    created_by_user_id = Column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_by_automation_id = Column(GUID(), nullable=True)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "parent_automation_id IS NULL OR parent_automation_id != id",
            name="ck_automation_definitions_no_self_parent",
        ),
        CheckConstraint(
            "depth IN (0, 1)",
            name="ck_automation_definitions_depth_range",
        ),
        # If workspace_scope is 'none', max_compute_tier MUST be 0 (no pod).
        CheckConstraint(
            "workspace_scope <> 'none' OR max_compute_tier = 0",
            name="ck_automation_definitions_scope_none_tier_zero",
        ),
        Index(
            "ix_automation_definitions_owner_active",
            "owner_user_id",
            "is_active",
        ),
    )


class AutomationTrigger(Base):
    """A trigger rule that wakes an automation.

    The ``kind`` column is a String + CHECK rather than a Postgres ENUM so
    we can extend the set without an ENUM ALTER (which is non-trivial under
    SQLite parity).
    """

    __tablename__ = "automation_triggers"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    automation_id = Column(
        GUID(),
        ForeignKey("automation_definitions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # cron | webhook | app_invocation | manual
    kind = Column(String(16), nullable=False)
    config = Column(JSON, nullable=False)

    next_run_at = Column(DateTime(timezone=True), nullable=True)
    last_run_at = Column(DateTime(timezone=True), nullable=True)

    is_active = Column(Boolean, nullable=False, default=True, server_default="true")

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "kind IN ('cron', 'webhook', 'app_invocation', 'manual')",
            name="ck_automation_triggers_kind",
        ),
    )


class AutomationAction(Base):
    """Action ordered within an automation (v1 = single row, v2 = DAG).

    ``app_action_id`` is set when ``action_type='app.invoke'``; null otherwise.
    """

    __tablename__ = "automation_actions"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    automation_id = Column(
        GUID(),
        ForeignKey("automation_definitions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ordinal = Column(Integer, nullable=False, default=0, server_default="0")

    # agent.run | app.invoke | gateway.send
    action_type = Column(String(32), nullable=False)
    config = Column(JSON, nullable=False)

    app_action_id = Column(
        GUID(), ForeignKey("app_actions.id", ondelete="SET NULL"), nullable=True
    )

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "action_type IN ('agent.run', 'app.invoke', 'gateway.send')",
            name="ck_automation_actions_action_type",
        ),
    )


class AutomationEvent(Base):
    """Immutable wake-up envelope. Replay-safe; the canonical idempotency surface."""

    __tablename__ = "automation_events"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    automation_id = Column(
        GUID(),
        ForeignKey("automation_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    trigger_id = Column(
        GUID(),
        ForeignKey("automation_triggers.id", ondelete="SET NULL"),
        nullable=True,
    )

    payload = Column(JSON, nullable=False, default=dict, server_default="{}")
    idempotency_key = Column(Text, nullable=True)

    received_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    dispatched_at = Column(DateTime(timezone=True), nullable=True)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    failed_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)

    # Denormalized copy of the trigger's kind for cheap filtering.
    trigger_kind = Column(String(16), nullable=False)

    __table_args__ = (
        Index(
            "ix_automation_events_automation_received",
            "automation_id",
            "received_at",
        ),
        # Partial unique on idempotency_key WHERE NOT NULL — created in
        # alembic with a portable expression for SQLite + Postgres.
    )


class AutomationRun(Base):
    """Durable execution attempt for a definition + event pair.

    A worker holding the run heartbeats every 30s; the controller leader
    expires runs whose ``heartbeat_at`` is older than 90s.
    """

    __tablename__ = "automation_runs"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    automation_id = Column(
        GUID(),
        ForeignKey("automation_definitions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_id = Column(
        GUID(),
        ForeignKey("automation_events.id", ondelete="SET NULL"),
        nullable=True,
    )

    # queued | preflight | running | succeeded | failed | cancelled | expired
    # | waiting_approval | waiting_credentials | waiting_credits | failed_preflight
    status = Column(
        String(32), nullable=False, default="queued", server_default="queued"
    )

    retry_count = Column(Integer, nullable=False, default=0, server_default="0")
    lease_term = Column(Integer, nullable=True)
    worker_id = Column(Text, nullable=True)
    heartbeat_at = Column(DateTime(timezone=True), nullable=True)

    spend_usd = Column(Numeric(12, 4), nullable=False, default=0, server_default="0")
    spend_by_source = Column(JSON, nullable=False, default=dict, server_default="{}")
    contract_breaches = Column(Integer, nullable=False, default=0, server_default="0")

    approver_user_id = Column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    paused_reason = Column(Text, nullable=True)

    # Minimal output buffer; large outputs go to automation_run_artifacts.
    raw_output = Column(JSON, nullable=True)

    # Reserved for non-blocking HITL resume in Phase 2; column lands now so
    # writers can persist resume state without another migration round.
    checkpoint = Column(JSON, nullable=True)

    started_at = Column(DateTime(timezone=True), nullable=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "automation_id", "event_id", name="uq_automation_runs_automation_event"
        ),
        Index("ix_automation_runs_automation_status", "automation_id", "status"),
    )


class AutomationRunArtifact(Base):
    """First-class durable record for run outputs (reports, files, deliveries)."""

    __tablename__ = "automation_run_artifacts"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    run_id = Column(
        GUID(),
        ForeignKey("automation_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # text | json | file | log | report | image | screenshot | csv | markdown | delivery_receipt
    kind = Column(String(32), nullable=False)
    name = Column(Text, nullable=False)
    mime_type = Column(Text, nullable=True)

    # inline | cas | s3 | external_url
    storage_mode = Column(String(16), nullable=False)
    storage_ref = Column(Text, nullable=False)
    preview_text = Column(Text, nullable=True)
    size_bytes = Column(BigInteger, nullable=True)

    meta = Column(JSON, nullable=False, default=dict, server_default="{}")
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AutomationDeliveryTarget(Base):
    """Per-automation fan-out edge to a (Phase 4) ``CommunicationDestination``.

    The FK to ``communication_destinations`` is intentionally NOT enforced
    in Phase 1 — that table lands in Phase 4. The column ships now as a
    plain GUID so wiring code can persist destinations between phases.
    """

    __tablename__ = "automation_delivery_targets"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    automation_id = Column(
        GUID(),
        ForeignKey("automation_definitions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    destination_id = Column(GUID(), nullable=False)
    ordinal = Column(Integer, nullable=False, default=0, server_default="0")

    # {kind: drop|retry_n|escalate_to_destination_id, ...}
    on_failure = Column(JSON, nullable=False, default=dict, server_default="{}")
    artifact_filter = Column(
        Text, nullable=False, default="all", server_default="all"
    )


class AutomationApprovalRequest(Base):
    """Canonical approval card for runs that need human input."""

    __tablename__ = "automation_approval_requests"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    run_id = Column(
        GUID(),
        ForeignKey("automation_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    requested_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by_user_id = Column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # contract_violation | budget_exhausted | tier_escalation | credential_missing | manual
    reason = Column(String(48), nullable=False)

    context = Column(JSON, nullable=False, default=dict, server_default="{}")
    # Array of UUIDs persisted as JSON for portability across Postgres + SQLite.
    context_artifacts = Column(JSON, nullable=False, default=list, server_default="[]")
    options = Column(JSON, nullable=False, default=list, server_default="[]")
    delivered_to = Column(JSON, nullable=False, default=list, server_default="[]")
    response = Column(JSON, nullable=True)


# ---------------------------------------------------------------------------
# App Runtime Contract — projection tables
#
# Each row is a cached projection of a block from ``AppVersion.manifest_json``.
# The immutable manifest stays the source of truth; projections speed up
# joins (e.g. ``automation_actions.app_action_id``) and let us put unique
# constraints on (app_version_id, name).
# ---------------------------------------------------------------------------


class AppAction(Base):
    """Typed callable function exposed by an AppVersion. Projection of manifest.actions[]."""

    __tablename__ = "app_actions"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    app_version_id = Column(
        GUID(),
        ForeignKey("app_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(Text, nullable=False)

    handler = Column(JSON, nullable=False)
    input_schema = Column(JSON, nullable=True)
    output_schema = Column(JSON, nullable=True)
    timeout_seconds = Column(Integer, nullable=True)
    idempotency = Column(JSON, nullable=True)

    billing = Column(JSON, nullable=True)
    required_connectors = Column(JSON, nullable=False, default=list, server_default="[]")
    required_grants = Column(JSON, nullable=False, default=list, server_default="[]")

    result_template = Column(Text, nullable=True)
    artifacts = Column(JSON, nullable=False, default=list, server_default="[]")

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("app_version_id", "name", name="uq_app_actions_version_name"),
    )


class AppView(Base):
    """Embeddable UI declared by an AppVersion. Projection of manifest.views[]."""

    __tablename__ = "app_views"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    app_version_id = Column(
        GUID(),
        ForeignKey("app_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(Text, nullable=False)

    # card | full_page | drawer
    kind = Column(String(16), nullable=False)
    entrypoint = Column(Text, nullable=False)
    input_schema = Column(JSON, nullable=True)
    output_schema = Column(JSON, nullable=True)
    cache_ttl_seconds = Column(Integer, nullable=True)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("app_version_id", "name", name="uq_app_views_version_name"),
        CheckConstraint(
            "kind IN ('card', 'full_page', 'drawer')",
            name="ck_app_views_kind",
        ),
    )


class AppDataResource(Base):
    """Typed queryable resource backed by an AppAction. Projection of manifest.data_resources[]."""

    __tablename__ = "app_data_resources"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    app_version_id = Column(
        GUID(),
        ForeignKey("app_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(Text, nullable=False)

    backed_by_action_id = Column(
        GUID(), ForeignKey("app_actions.id", ondelete="CASCADE"), nullable=False
    )
    schema = Column(JSON, nullable=True)
    cache_ttl_seconds = Column(Integer, nullable=True)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "app_version_id", "name", name="uq_app_data_resources_version_name"
        ),
    )


class AppDependency(Base):
    """Declared composition between apps (parent ⇒ child). Projection of manifest.dependencies[]."""

    __tablename__ = "app_dependencies"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    # The PARENT version that declares this dependency.
    app_version_id = Column(
        GUID(),
        ForeignKey("app_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    alias = Column(Text, nullable=False)
    child_app_id = Column(
        GUID(),
        ForeignKey("marketplace_apps.id", ondelete="RESTRICT"),
        nullable=False,
    )
    required = Column(Boolean, nullable=False, default=True, server_default="true")

    needs_actions = Column(JSON, nullable=False, default=list, server_default="[]")
    needs_views = Column(JSON, nullable=False, default=list, server_default="[]")
    needs_data_resources = Column(
        JSON, nullable=False, default=list, server_default="[]"
    )

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "app_version_id", "alias", name="uq_app_dependencies_version_alias"
        ),
    )


class AppConnectorRequirement(Base):
    """Typed connector ask. Projection of manifest.connectors[]."""

    __tablename__ = "app_connector_requirements"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    app_version_id = Column(
        GUID(),
        ForeignKey("app_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    connector_id = Column(Text, nullable=False)

    # mcp | api_key | oauth | webhook
    kind = Column(String(16), nullable=False)
    scopes = Column(JSON, nullable=False, default=list, server_default="[]")

    # proxy | env — REQUIRED in manifest, no implicit default.
    exposure = Column(String(8), nullable=False)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "app_version_id",
            "connector_id",
            name="uq_app_connector_requirements_version_connector",
        ),
        CheckConstraint(
            "exposure IN ('proxy', 'env')",
            name="ck_app_connector_requirements_exposure",
        ),
    )


class AppAutomationTemplate(Base):
    """App-suggested default automation surfaced at install time.

    Apps cannot run schedules autonomously — these are templates the
    installer opts into in the Install Modal. Checked templates create real
    ``AutomationDefinition`` rows owned by the installer.
    """

    __tablename__ = "app_automation_templates"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    app_version_id = Column(
        GUID(),
        ForeignKey("app_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(Text, nullable=False)
    description = Column(Text, nullable=True)

    trigger_config = Column(JSON, nullable=False)
    action_config = Column(JSON, nullable=False)
    delivery_config = Column(JSON, nullable=False, default=dict, server_default="{}")
    contract_template = Column(JSON, nullable=False, default=dict, server_default="{}")

    is_default_enabled = Column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "app_version_id", "name", name="uq_app_automation_templates_version_name"
        ),
    )


# ---------------------------------------------------------------------------
# Recreated tables — same shape as their pre-reset selves, plus a Phase 3 hook.
# ---------------------------------------------------------------------------


class AppRuntimeDeployment(Base):
    """Runtime identity separate from logical install (Phase 3 primitive).

    ``AppInstance`` answers "which user owns this install?" —
    ``AppRuntimeDeployment`` answers "where does this actually run, with
    what replica policy, on whose tenancy?" One install != one runtime in
    shared-singleton mode: many ``AppInstance`` rows can point at the
    same row here via ``AppInstance.runtime_deployment_id``.

    The constraint matrix (``per_install_volume`` ⟹ ``max_replicas=1``;
    same for ``service_pvc``; replica monotonicity; enum CHECKs) is
    enforced at the DB level by ``alembic 0076_app_runtime_deployments``
    so an unsafe row cannot be inserted regardless of which path created
    it. Scaling-shape fields that need CHECKs are real columns; richer
    HPA/custom-metric config lives in ``scaling_config`` JSONB.

    For Phase 3 the row is set up at install time:
      - ``per_install``: one row per ``AppInstance``, ``max_replicas=1``.
      - ``shared_singleton``: one row per (app_id, app_version_id) reused
        across all installs; the K8s namespace + project is materialized
        once.
      - ``per_invocation``: ``min_replicas=0, max_replicas=0`` with no
        persistent pods — each invocation spins a Job.

    The Phase 4 controller's idle reaper acts on this row, not on
    ``AppInstance`` — so reaping shared-singleton scales every install's
    view simultaneously. PVC + namespace + Secrets persist across scale
    events; only pod replicas drop to zero.
    """

    __tablename__ = "app_runtime_deployments"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    app_id = Column(
        GUID(),
        ForeignKey("marketplace_apps.id", ondelete="CASCADE"),
        nullable=False,
    )
    app_version_id = Column(
        GUID(),
        ForeignKey("app_versions.id", ondelete="CASCADE"),
        nullable=False,
    )

    # per_install | shared_singleton | per_invocation
    tenancy_model = Column(String(32), nullable=False)
    # stateless | per_install_volume | service_pvc | shared_volume | external
    state_model = Column(String(32), nullable=False)

    # The K8s project/namespace this runs in. Null for ``per_invocation``
    # deployments that own no persistent pods (the Job runs in some other
    # bookkeeping namespace owned by the dispatcher).
    runtime_project_id = Column(
        GUID(),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    namespace = Column(Text, nullable=True)
    primary_container_id = Column(Text, nullable=True)
    # Volume Hub PVC ref. Null for stateless / external state models.
    volume_id = Column(Text, nullable=True)

    # Scaling fields are REAL COLUMNS (not JSON) so the constraint matrix
    # works portably across Postgres + SQLite.
    min_replicas = Column(Integer, nullable=False, default=0, server_default="0")
    max_replicas = Column(Integer, nullable=False, default=1, server_default="1")
    desired_replicas = Column(
        Integer, nullable=False, default=1, server_default="1"
    )
    idle_timeout_seconds = Column(
        Integer, nullable=False, default=600, server_default="600"
    )
    concurrency_target = Column(
        Integer, nullable=False, default=10, server_default="10"
    )

    # HPA config, custom metrics, and other non-CHECK-enforced scaling
    # shape lives here.
    scaling_config = Column(
        JSON, nullable=False, default=dict, server_default="{}"
    )

    scaled_to_zero_at = Column(DateTime(timezone=True), nullable=True)
    last_activity_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "max_replicas >= min_replicas",
            name="chk_ard_replicas_max_gte_min",
        ),
        CheckConstraint(
            "desired_replicas BETWEEN min_replicas AND max_replicas",
            name="chk_ard_replicas_desired_in_range",
        ),
        CheckConstraint(
            "NOT (state_model = 'per_install_volume' AND max_replicas > 1)",
            name="chk_ard_per_install_volume_max_one",
        ),
        CheckConstraint(
            "NOT (state_model = 'service_pvc' AND max_replicas > 1)",
            name="chk_ard_service_pvc_max_one",
        ),
        CheckConstraint(
            "tenancy_model IN ('per_install', 'shared_singleton', 'per_invocation')",
            name="chk_ard_tenancy",
        ),
        CheckConstraint(
            "state_model IN ('stateless', 'per_install_volume', 'service_pvc', "
            "'shared_volume', 'external')",
            name="chk_ard_state_model",
        ),
        Index("ix_ard_app_id", "app_id"),
        Index("ix_ard_runtime_project_id", "runtime_project_id"),
    )


class AppInstance(Base):
    """Per-install leaf, recreated under the hard reset.

    The ``runtime_deployment_id`` FK to ``AppRuntimeDeployment`` lands in
    ``alembic 0076_app_runtime_deployments`` (Phase 3). The column itself
    was added in 0074 as a nullable reservation; existing rows from
    before Phase 3 have ``runtime_deployment_id=NULL`` and stay that way
    until they're re-installed under the new manifest.
    """

    __tablename__ = "app_instances"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    app_id = Column(
        GUID(),
        ForeignKey("marketplace_apps.id", ondelete="RESTRICT"),
        nullable=False,
    )
    app_version_id = Column(
        GUID(),
        ForeignKey("app_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    installer_user_id = Column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    project_id = Column(
        GUID(), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    state = Column(
        String(24), nullable=False, default="installing", server_default="installing"
    )
    consent_record = Column(JSON, nullable=False, default=dict, server_default="{}")
    wallet_mix = Column(JSON, nullable=False, default=dict, server_default="{}")
    update_policy = Column(
        String(16), nullable=False, default="manual", server_default="manual"
    )
    volume_id = Column(Text, nullable=True)
    feature_set_hash = Column(Text, nullable=True)
    primary_container_id = Column(
        GUID(),
        ForeignKey("containers.id", ondelete="SET NULL"),
        nullable=True,
    )
    # FK to app_runtime_deployments lands in 0076 (Phase 3). ON DELETE
    # SET NULL: deleting a deployment row never destroys install rows.
    runtime_deployment_id = Column(
        GUID(),
        ForeignKey("app_runtime_deployments.id", ondelete="SET NULL"),
        nullable=True,
    )

    installed_at = Column(DateTime(timezone=True), nullable=True)
    uninstalled_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Reverse relationships for back_populates declared on the legacy
    # MarketplaceApp / AppVersion / McpConsentRecord side. Without these
    # SQLAlchemy mapper config raises ArgumentError the first time models
    # are loaded.
    app = relationship("MarketplaceApp", back_populates="instances", foreign_keys=[app_id])
    app_version = relationship("AppVersion", back_populates="instances", foreign_keys=[app_version_id])
    installer = relationship("User", foreign_keys=[installer_user_id])
    project = relationship("Project", foreign_keys=[project_id])
    consents = relationship(
        "McpConsentRecord",
        back_populates="app_instance",
        cascade="all, delete-orphan",
    )


class InvocationSubject(Base):
    """Unified billing + token identity attached to every AutomationRun.

    Phase 2 primitive (see ``/Users/smirk/.claude/plans/ultrathink-i-want-to-glittery-pond.md``
    section "InvocationSubject — unified billing and token identity").

    Today three separate code paths handle billing routing: ``wallet_mix``
    settlement (apps), ``credit_service`` (user OpenSail credits), and
    ``key_lifecycle`` (LiteLLM key minting). ``InvocationSubject`` collapses
    them into a single resolved decision per run. After this lands, every
    ``SpendRecord`` and ``LiteLLMKeyLedger`` row carries
    ``invocation_subject_id`` — joining spend back to billable identity is
    one column, not three lookups.

    The FK constraints from ``spend_records.invocation_subject_id`` and
    ``litellm_key_ledger.invocation_subject_id`` are added in alembic
    ``0075_invocation_subjects`` (Phase 2). The columns themselves were
    added in Phase 0 (spend_records) and the same Phase 2 migration
    (litellm_key_ledger).
    """

    __tablename__ = "invocation_subjects"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)

    # Optional anchors. Direct manual invocations have no ``automation_run_id``.
    automation_run_id = Column(
        GUID(),
        ForeignKey("automation_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    invoking_user_id = Column(
        GUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    team_id = Column(
        GUID(), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True
    )
    app_instance_id = Column(
        GUID(),
        ForeignKey("app_instances.id", ondelete="SET NULL"),
        nullable=True,
    )
    app_action_id = Column(
        GUID(),
        ForeignKey("app_actions.id", ondelete="SET NULL"),
        nullable=True,
    )
    agent_id = Column(
        GUID(),
        ForeignKey("marketplace_agents.id", ondelete="SET NULL"),
        nullable=True,
    )

    # installer | creator | team | platform | byok | parent_run
    payer_policy = Column(String(32), nullable=False)
    parent_run_id = Column(
        GUID(),
        ForeignKey("automation_runs.id", ondelete="SET NULL"),
        nullable=True,
    )

    # opensail_credits | scoped_litellm_key | byok_litellm_key |
    # creator_wallet | team_credits | platform_budget | parent_run
    credit_source = Column(String(48), nullable=False)
    credit_source_ref = Column(Text, nullable=True)

    # {max_usd_per_run, max_usd_per_day} — enforced by ContractGate / dispatcher.
    budget_envelope = Column(JSON, nullable=False, default=dict, server_default="{}")
    spent_so_far_usd = Column(
        Numeric(12, 4), nullable=False, default=0, server_default="0"
    )
    litellm_key_id = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "payer_policy IN ('installer', 'creator', 'team', 'platform', "
            "'byok', 'parent_run')",
            name="ck_invocation_subjects_payer_policy",
        ),
        CheckConstraint(
            "credit_source IN ('opensail_credits', 'scoped_litellm_key', "
            "'byok_litellm_key', 'creator_wallet', 'team_credits', "
            "'platform_budget', 'parent_run')",
            name="ck_invocation_subjects_credit_source",
        ),
    )


class AppInstallAttempt(Base):
    """Saga ledger for the apps installer, recreated under the hard reset.

    Same semantics as the pre-reset table: a row is minted before the Hub
    volume is materialized so a crashed install always has a marker for the
    orphan reaper.
    """

    __tablename__ = "app_install_attempts"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    marketplace_app_id = Column(
        GUID(),
        ForeignKey("marketplace_apps.id", ondelete="SET NULL"),
        nullable=True,
    )
    app_version_id = Column(
        GUID(),
        ForeignKey("app_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    installer_user_id = Column(
        GUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    state = Column(
        String(32), nullable=False, default="hub_created", server_default="hub_created"
    )
    volume_id = Column(String, nullable=True)
    node_name = Column(String, nullable=True)
    bundle_hash = Column(String, nullable=True)
    app_instance_id = Column(
        GUID(),
        ForeignKey("app_instances.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    committed_at = Column(DateTime(timezone=True), nullable=True)
    reaped_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)


# ---------------------------------------------------------------------------
# Connector Proxy — Phase 3 primitives (alembic 0077_connector_proxy_calls).
# ---------------------------------------------------------------------------


class AppConnectorGrant(Base):
    """Per-install consent + resolved-credential pointer for the Connector Proxy.

    Created at install time (or via the Install Modal connector picker), one
    row per ``(app_instance, app_connector_requirement)`` pair while
    ``revoked_at IS NULL``. The Connector Proxy looks this row up on every
    upstream call to find the credential to inject.

    ``resolved_ref`` discriminates by ``kind``::

        {"kind": "oauth_connection", "id": "<mcp_oauth_connections.id>"}
        {"kind": "user_mcp_config",  "id": "<user_mcp_configs.id>"}
        {"kind": "api_key_secret",   "id": "<container_encrypted_secrets.id>"}

    ``exposure_at_grant`` is **pinned at install time**. If a manifest
    upgrade flips the requirement's exposure (``proxy → env`` or back), the
    grant is *not* mutated — that's a re-consent path: the install flow
    revokes the old grant and creates a fresh one with the new value.
    """

    __tablename__ = "app_connector_grants"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    app_instance_id = Column(
        GUID(),
        ForeignKey("app_instances.id", ondelete="CASCADE"),
        nullable=False,
    )
    requirement_id = Column(
        GUID(),
        ForeignKey("app_connector_requirements.id", ondelete="CASCADE"),
        nullable=False,
    )
    resolved_ref = Column(JSON, nullable=False)
    # 'proxy' | 'env' — pinned at install time.
    exposure_at_grant = Column(String(8), nullable=False)
    granted_by_user_id = Column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    granted_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "exposure_at_grant IN ('proxy', 'env')",
            name="ck_app_connector_grants_exposure_at_grant",
        ),
        Index(
            "ix_app_connector_grants_app_instance_id",
            "app_instance_id",
        ),
    )


class ConnectorProxyCall(Base):
    """Append-only audit row written for every Connector Proxy call.

    Lets the platform answer "what has this app done with my Slack token?"
    without instrumenting the app pod. ``error`` carries a 500-char prefix
    of the upstream body when ``status_code >= 400`` — the proxy is
    responsible for stripping the bearer token before persisting.
    """

    __tablename__ = "connector_proxy_calls"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    app_instance_id = Column(
        GUID(),
        ForeignKey("app_instances.id", ondelete="CASCADE"),
        nullable=False,
    )
    requirement_id = Column(
        GUID(),
        # SET NULL so a yanked manifest doesn't cascade-delete the audit
        # trail — the audit must outlive the row it references.
        ForeignKey("app_connector_requirements.id", ondelete="SET NULL"),
        nullable=True,
    )
    connector_id = Column(Text, nullable=False)
    endpoint = Column(Text, nullable=False)
    method = Column(String(8), nullable=False, server_default="POST")
    status_code = Column(Integer, nullable=False)
    bytes_in = Column(BigInteger, nullable=False, server_default="0")
    bytes_out = Column(BigInteger, nullable=False, server_default="0")
    duration_ms = Column(Integer, nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    error = Column(Text, nullable=True)

    __table_args__ = (
        Index(
            "ix_cpc_app_instance_id_created_at",
            "app_instance_id",
            "created_at",
        ),
        Index(
            "ix_cpc_connector_id_created_at",
            "connector_id",
            "created_at",
        ),
    )


# ---------------------------------------------------------------------------
# App Composition — Phase 3 primitives (alembic 0078_app_composition).
#
# Composition contract (load-bearing):
#   parent → child action  via dispatch_app_action gated by app_instance_links
#   parent → child view    via signed JWT minted from app_instance_links + app_embeds
#   parent → child data    via dispatch_app_action on the resource's backed_by_action
#
# There is NO path where a parent reaches into a child's storage, K8s
# namespace, or process. Everything else (billing, auditing, permissions)
# follows from this single rule.
# ---------------------------------------------------------------------------


class AppInstanceLink(Base):
    """Install-time wiring from a parent app install to a child app install.

    One row per ``(parent_install_id, alias)``. Granted scope arrays are
    positive lists drawn from ``manifest.dependencies[].needs`` — the
    parent only gets what it explicitly asked for. Anything outside the
    positive list is rejected at the composition runtime with 403.

    Revocation is a soft-delete: ``UPDATE app_instance_links SET
    revoked_at=now()``. The composition runtime treats a non-NULL
    ``revoked_at`` as alias-not-found (the link is gone from the parent's
    perspective; auditing the historical row is still possible).
    """

    __tablename__ = "app_instance_links"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    parent_install_id = Column(
        GUID(),
        ForeignKey("app_instances.id", ondelete="CASCADE"),
        nullable=False,
    )
    child_install_id = Column(
        GUID(),
        ForeignKey("app_instances.id", ondelete="CASCADE"),
        nullable=False,
    )
    alias = Column(String(64), nullable=False)

    granted_actions = Column(JSON, nullable=False, default=list, server_default="[]")
    granted_views = Column(JSON, nullable=False, default=list, server_default="[]")
    granted_data_resources = Column(
        JSON, nullable=False, default=list, server_default="[]"
    )

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "parent_install_id",
            "alias",
            name="uq_app_instance_links_parent_alias",
        ),
        Index("ix_ail_child_install_id", "child_install_id"),
        Index("ix_ail_parent_install_id", "parent_install_id"),
    )


class AppEmbed(Base):
    """Saved view-embed instance.

    When a user drops a CRM ``account_card`` into a dashboard slot, we
    persist a row here with the bound ``input`` and ``layout_position``.
    The parent dashboard reads its rows at render time, mints a signed
    JWT per row via :mod:`app.services.apps.embed_token`, and renders an
    iframe per token.

    Mint-time validation is run against the matching ``app_instance_links``
    row (alias resolution + ``view_name in granted_views``); the embed
    row itself is just persistent layout state.
    """

    __tablename__ = "app_embeds"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    parent_install_id = Column(
        GUID(),
        ForeignKey("app_instances.id", ondelete="CASCADE"),
        nullable=False,
    )
    child_install_id = Column(
        GUID(),
        ForeignKey("app_instances.id", ondelete="CASCADE"),
        nullable=False,
    )
    view_name = Column(String(128), nullable=False)

    # Bound input (e.g., {"account_id": "1234"}) — included verbatim in
    # the signed embed token at mint time.
    input = Column(JSON, nullable=False, default=dict, server_default="{}")

    # Optional grid placement: { row, col, w, h }. NULL when the embed is
    # rendered without a saved layout (e.g., one-off ad-hoc).
    layout_position = Column(JSON, nullable=True)

    created_by_user_id = Column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_ae_parent_install_id", "parent_install_id"),
    )


__all__ = [
    "AutomationDefinition",
    "AutomationTrigger",
    "AutomationAction",
    "AutomationEvent",
    "AutomationRun",
    "AutomationRunArtifact",
    "AutomationDeliveryTarget",
    "AutomationApprovalRequest",
    "AppAction",
    "AppView",
    "AppDataResource",
    "AppDependency",
    "AppConnectorRequirement",
    "AppAutomationTemplate",
    "AppRuntimeDeployment",
    "AppInstance",
    "AppInstallAttempt",
    "InvocationSubject",
    "AppConnectorGrant",
    "ConnectorProxyCall",
    "AppInstanceLink",
    "AppEmbed",
]
