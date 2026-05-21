"""Raise app runtime idle timeout default to 2 days.

Revision ID: 0117_idle_timeout_two_days
Revises: 0116_seed_system_internal
Create Date: 2026-05-20

App runtime deployments (``app_runtime_deployments``) scale to zero once
``idle_timeout_seconds`` of inactivity elapses with no active run. The
column default was 600s (10 min), which hibernates installed apps far
too aggressively. The platform default is moving to 2 days (172800s),
matching the project/container hibernation window.

This migration:

1. Alters the column ``server_default`` from ``600`` to ``172800`` so
   any future row inserted without an explicit value picks up the new
   default. (The model's Python-side ``default`` is changed alongside
   this in ``models_automations.py``.)

2. Bumps existing rows that still carry the OLD default (exactly 600)
   to 172800. Rows with any other value were an explicit per-app choice
   from the manifest's ``scaling.idle_timeout_seconds`` and are left
   untouched.

Postgres-only path; SQLite-backed tests/desktop build fresh schemas via
``Base.metadata.create_all`` and pick up the new default directly from
the model.
"""

import logging

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = "0117_idle_timeout_two_days"
down_revision = "0116_seed_system_internal"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.migration.0117")

_OLD_DEFAULT = 600
_NEW_DEFAULT = 172800  # 2 days


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.alter_column(
        "app_runtime_deployments",
        "idle_timeout_seconds",
        existing_type=sa.Integer(),
        existing_nullable=False,
        server_default=str(_NEW_DEFAULT),
    )

    result = bind.execute(
        text(
            """
            UPDATE app_runtime_deployments
            SET idle_timeout_seconds = :new_default
            WHERE idle_timeout_seconds = :old_default
            """
        ),
        {"new_default": _NEW_DEFAULT, "old_default": _OLD_DEFAULT},
    )
    logger.info(
        "0117: raised idle_timeout_seconds to %s on %s deployment(s) previously on the old default",
        _NEW_DEFAULT,
        result.rowcount,
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.alter_column(
        "app_runtime_deployments",
        "idle_timeout_seconds",
        existing_type=sa.Integer(),
        existing_nullable=False,
        server_default=str(_OLD_DEFAULT),
    )
    # Data is left as-is: a row at 172800 cannot be reliably told apart
    # from one a creator set explicitly. Re-running upgrade() is
    # idempotent if the default needs restoring.
