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
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
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
