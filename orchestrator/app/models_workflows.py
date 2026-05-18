"""Workflow-engine self-evolution models (G-track, issue #469).

Lives in its own module so ``models_automations.py`` keeps its focus
on runtime execution state. G1 ships ``WorkflowVersion``: immutable
snapshots of a definition's contract + actions + triggers +
delivery_targets. Future G phases will add ``WorkflowProposal``
(G2), ``WorkflowHealthSnapshot`` (G4), ``WorkflowLearning`` (G6),
``WorkflowVersionHealth`` (G7) to this file.

Why a separate file: models_automations.py is already 1500+ lines and
the self-evolution surface is conceptually post-Phase-A. Importing
this module after ``app.models`` is sufficient for the mapper graph;
the model is re-exported from ``app.models`` so existing
``from .models import ...`` callers can find it once we add re-exports.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    JSON,
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
from sqlalchemy.sql import func

from app.types.guid import GUID

from .database import Base


class WorkflowVersion(Base):
    """Immutable snapshot of an automation's full definition (G1, issue #469).

    Written on every meaningful change to an ``AutomationDefinition``
    (create, PATCH that touches contract/actions/triggers/targets, or
    an applied agent proposal). ``AutomationDefinition.head_version_id``
    is the live pointer; ``AutomationRun.workflow_version_id`` records
    which version a run executed against.

    ``payload`` is a complete shape:

        {
            "contract": {...},
            "max_compute_tier": 0,
            "max_spend_per_run_usd": "...",
            "max_spend_per_day_usd": "...",
            "compute_profile": "persistent_workspace",
            "workspace_scope": "none",
            "actions": [
                {"ordinal": 0, "action_type": "...", "config": {...},
                 "app_action_id": "..." | null, ...},
                ...
            ],
            "triggers": [{"kind": "...", "config": {...}, "is_active": true}, ...],
            "delivery_targets": [{"destination_id": "...", "ordinal": 0, ...}, ...]
        }

    The dispatcher and engine read from this snapshot when a run is
    version-bound (``automation_runs.workflow_version_id`` not null).
    Live ``AutomationAction``/``AutomationTrigger``/``AutomationDeliveryTarget``
    rows continue to back un-bound calls (cron_producer, inbound
    triggers, brand-new runs before the pointer is set on a definition
    created prior to G1).
    """

    __tablename__ = "workflow_versions"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    automation_id = Column(
        GUID(),
        ForeignKey("automation_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Generation is monotonically increasing per automation. Used by
    # the G7 rollback sweep + by the doctor agent to count "how many
    # times have I tried fixing this."
    generation = Column(Integer, nullable=False)
    parent_version_id = Column(
        GUID(),
        ForeignKey("workflow_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    payload = Column(JSON, nullable=False)
    # SHA-256 of the canonical JSON payload. UNIQUE per (automation_id,
    # payload_sha256) so an idempotent PATCH never multiplies rows.
    payload_sha256 = Column(String(64), nullable=False)

    # Exactly one of the two below is non-null in normal use:
    #   * created_by_user_id: a human authored this via the API.
    #   * created_by_run_id: an agent run authored this via an applied
    #     WorkflowProposal (G2+).
    # Both null is the system-bootstrap path (lazy-create generation 1
    # for definitions that pre-date G1).
    created_by_user_id = Column(GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_by_run_id = Column(
        GUID(),
        ForeignKey("automation_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    rationale = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "automation_id",
            "payload_sha256",
            name="uq_workflow_versions_automation_sha",
        ),
        Index(
            "ix_workflow_versions_automation_generation",
            "automation_id",
            "generation",
        ),
    )


class WorkflowProposal(Base):
    """Draft change to an AutomationDefinition awaiting decision (G2, issue #469).

    The author (agent or human) writes the proposal; the platform
    decides how to apply it:

    * approval-required → an :class:`AutomationApprovalRequest` row
      surfaces the proposal in the existing Slack / email / web
      approval queue. On approve, the proposal applies: write a new
      WorkflowVersion (or reuse if SHA-deduped), flip head_version_id,
      replace child rows. Reject closes the proposal without effect.
    * auto-apply (G3) → bypass the approval card after a dry-run
      against ``automation_definitions.auto_apply_policy`` (which
      lands in G3). G2 always routes through approval.

    The diff_summary is structured (list of {path, op, before, after})
    so the UI can render a compact diff. The to_payload is the FULL
    proposed shape, identical schema to ``WorkflowVersion.payload``,
    so applying is "write a version with this payload."
    """

    __tablename__ = "workflow_proposals"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    automation_id = Column(
        GUID(),
        ForeignKey("automation_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    from_version_id = Column(
        GUID(),
        ForeignKey("workflow_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    to_payload = Column(JSON, nullable=False)
    diff_summary = Column(JSON, nullable=False)
    rationale = Column(Text, nullable=False)
    # low | medium | high. Used by G3 auto-apply to decide whether
    # to bypass approval; G2 surfaces it on the approval card for
    # the user's context.
    risk_class = Column(String(16), nullable=False, default="medium", server_default="medium")

    # submitted | approved | rejected | applied | reverted | expired | withdrawn.
    status = Column(String(16), nullable=False, default="submitted", server_default="submitted")
    approval_request_id = Column(
        GUID(),
        ForeignKey("automation_approval_requests.id", ondelete="SET NULL"),
        nullable=True,
    )
    applied_version_id = Column(
        GUID(),
        ForeignKey("workflow_versions.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Provenance: exactly one of proposer_run_id / proposer_user_id is
    # non-null. Both null is rejected at create time.
    proposer_run_id = Column(
        GUID(),
        ForeignKey("automation_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    proposer_user_id = Column(
        GUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    reviewer_user_id = Column(
        GUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewer_comment = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    # The expiry sweep marks stale rows so the queue can't grow
    # unbounded. Default at create time is +7 days.
    expires_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "status IN ('submitted', 'approved', 'rejected', 'applied', "
            "'reverted', 'expired', 'withdrawn')",
            name="ck_workflow_proposals_status",
        ),
        CheckConstraint(
            "risk_class IN ('low', 'medium', 'high')",
            name="ck_workflow_proposals_risk_class",
        ),
        Index(
            "ix_workflow_proposals_automation_status",
            "automation_id",
            "status",
        ),
        Index("ix_workflow_proposals_expires", "expires_at"),
    )


class WorkflowHealthSnapshot(Base):
    """Periodic per-workflow health rollup (G4, issue #469).

    The doctor agent (G5) reads from here to decide whether
    intervention is needed. A small cron sweep recomputes per
    (automation_id, window) pair on a schedule (short ~ every
    15 min, long ~ hourly). UNIQUE on (automation_id, window) so
    the sweep upserts in place.
    """

    __tablename__ = "workflow_health_snapshots"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    automation_id = Column(
        GUID(),
        ForeignKey("automation_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 'short' (last 24h) or 'long' (last 7d).
    window = Column(String(16), nullable=False)
    computed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    run_count = Column(Integer, nullable=False, default=0, server_default="0")
    success_count = Column(Integer, nullable=False, default=0, server_default="0")
    failure_count = Column(Integer, nullable=False, default=0, server_default="0")
    awaiting_approval_count = Column(Integer, nullable=False, default=0, server_default="0")
    success_rate = Column(Numeric(4, 3), nullable=True)
    median_duration_ms = Column(Integer, nullable=True)
    p95_duration_ms = Column(Integer, nullable=True)
    spend_p50_usd = Column(Numeric(12, 4), nullable=True)
    spend_p95_usd = Column(Numeric(12, 4), nullable=True)
    most_common_error_kind = Column(Text, nullable=True)
    most_common_failed_step_ordinal = Column(Integer, nullable=True)
    last_failed_run_id = Column(
        GUID(),
        ForeignKey("automation_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_failed_step_ordinal = Column(Integer, nullable=True)
    last_error_message = Column(Text, nullable=True)
    runs_since_last_change = Column(Integer, nullable=False, default=0, server_default="0")
    open_proposal_count = Column(Integer, nullable=False, default=0, server_default="0")
    generation_at_window_start = Column(Integer, nullable=True)
    generation_at_window_end = Column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint("automation_id", "window", name="uq_workflow_health_automation_window"),
        CheckConstraint(
            "\"window\" IN ('short', 'long')",
            name="ck_workflow_health_window",
        ),
    )


class WorkflowLearning(Base):
    """Cross-workflow pattern memory (G6, issue #469).

    The doctor agent records what worked on workflow X (after a
    proposal it applied succeeds N times); future doctor runs on
    workflow Y can look it up by tag and try a similar fix. Team-
    scoped by default; cross-team sharing is opt-in (not in this
    phase).
    """

    __tablename__ = "workflow_learnings"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    team_id = Column(GUID(), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True)
    tag = Column(String(64), nullable=False)
    symptom_pattern = Column(JSON, nullable=True)
    proposed_fix = Column(JSON, nullable=True)
    success_count = Column(Integer, nullable=False, default=0, server_default="0")
    failure_count = Column(Integer, nullable=False, default=0, server_default="0")
    last_applied_run_id = Column(
        GUID(),
        ForeignKey("automation_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by_run_id = Column(
        GUID(),
        ForeignKey("automation_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (Index("ix_workflow_learnings_team_tag", "team_id", "tag"),)
