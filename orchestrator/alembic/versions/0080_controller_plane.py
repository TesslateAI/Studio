"""Controller plane — leases + intents.

Revision ID: 0080_controller_plane
Revises: 0079_comm_destinations
Create Date: 2026-04-26

Phase 4 of the OpenSail Automation Runtime — the ``automations-controller``
plane (see ``/Users/smirk/.claude/plans/ultrathink-i-want-to-glittery-pond.md``
sections "Controller leasing" and "Intent rows + idempotent reconciler").

Adds two tables:

1. ``controller_leases`` — single-leader coordination row (one per
   controller name, e.g., 'cron', 'reaper', 'drain'). Holds ``term INT``
   monotonically incremented on each acquire so deposed leaders can't
   write through with stale state. Used by ``DBLease`` (the default
   backend, works on Postgres + SQLite). RedisLease and K8sLease use
   their native primitives instead but the schema is here for the DB
   default path.

2. ``controller_intents`` — durable intent rows. Reconciler reads
   ``status='pending'`` rows, filters out stale ``lease_term``, applies
   idempotent K8s/Docker mutations, marks ``applied`` or ``superseded``.
   Crash-safe: a reconciler crash leaves rows ``pending`` for the next
   leader to pick up. Idempotent mutations ride this contract.

Down revision is ``0079_comm_destinations`` (Phase 4 destinations).
Portable across Postgres + SQLite via the ``GUID`` TypeDecorator.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.types.guid import GUID

# revision identifiers, used by Alembic.
revision: str = "0080_controller_plane"
down_revision: str | Sequence[str] | None = "0079_comm_destinations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # controller_leases — leader election rows.
    #
    # ``name``   — logical lease name ('cron', 'reaper', 'drain', ...).
    # ``holder`` — opaque holder id (pod name + pid).
    # ``term``   — monotonically incremented on each fresh acquire. Lease
    #              fencing reads this in the same TXN that records intents.
    # ``expires_at`` — TTL; expired leases are claimable.
    # ``acquired_at`` — bookkeeping for diagnostics.
    # ------------------------------------------------------------------
    op.create_table(
        "controller_leases",
        sa.Column("name", sa.String(64), primary_key=True),
        sa.Column("holder", sa.Text(), nullable=True),
        sa.Column("term", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "acquired_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # ------------------------------------------------------------------
    # controller_intents — durable intent rows.
    #
    # ``kind``       — 'scale_to_zero' | 'scale_up' | 'delete_pod' |
    #                  'rotate_secret' | 'reap_namespace' | …
    # ``target_ref`` — opaque JSONB pointer (e.g.,
    #                  {"deployment": "app-foo", "namespace": "proj-x"}).
    # ``lease_term`` — the term the leader held when writing this intent.
    #                  Reconciler filters mismatches to ``superseded``.
    # ``status``     — pending | applied | superseded | failed.
    # ``applied_by_term`` — which leader actually applied the mutation.
    # ``last_error`` — short error if reconciliation failed last time.
    # ``attempts`` — retry counter; controller decides when to give up.
    # ``created_at`` / ``applied_at`` — bookkeeping.
    # ------------------------------------------------------------------
    op.create_table(
        "controller_intents",
        sa.Column(
            "id",
            GUID(),
            primary_key=True,
        ),
        sa.Column("kind", sa.String(48), nullable=False),
        sa.Column("target_ref", sa.JSON(), nullable=False),
        sa.Column("lease_term", sa.BigInteger(), nullable=False),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("applied_by_term", sa.BigInteger(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "applied_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'applied', 'superseded', 'failed')",
            name="chk_ci_status",
        ),
    )
    op.create_index(
        "ix_controller_intents_status_created",
        "controller_intents",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_controller_intents_kind",
        "controller_intents",
        ["kind"],
    )


def downgrade() -> None:
    op.drop_index("ix_controller_intents_kind", table_name="controller_intents")
    op.drop_index(
        "ix_controller_intents_status_created", table_name="controller_intents"
    )
    op.drop_table("controller_intents")
    op.drop_table("controller_leases")
