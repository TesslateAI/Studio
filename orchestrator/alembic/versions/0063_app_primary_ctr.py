"""Add container.is_primary + app_instance.primary_container_id.

Revision ID: 0063_app_primary_ctr
Revises: 0062_drop_base64_secret_codec
Create Date: 2026-04-14 12:00:00.000000

Replaces the implicit "first container / port=3000" rule with an explicit
``containers.is_primary`` flag plus a partial-unique index to enforce at
most one primary per project. Adds
``app_instances.primary_container_id`` so the runtime can resolve the UI
surface for an installed app without re-querying.

Backfill picks the port=3000 container if any, otherwise the earliest
``created_at``. Idempotent — re-running a project that already has a
primary leaves it alone.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0063_app_primary_ctr"
down_revision: str | Sequence[str] | None = "0062_drop_base64_secret_codec"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1) containers.is_primary
    op.add_column(
        "containers",
        sa.Column(
            "is_primary",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    # Partial unique: at most one primary per project.
    op.create_index(
        "ix_containers_one_primary",
        "containers",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
    )

    # 2) app_instances.primary_container_id
    _is_sqlite = op.get_bind().dialect.name == "sqlite"
    _ctr_fk = [] if _is_sqlite else [sa.ForeignKey("containers.id", ondelete="SET NULL")]
    op.add_column(
        "app_instances",
        sa.Column(
            "primary_container_id",
            sa.dialects.postgresql.UUID(as_uuid=True).with_variant(sa.Text(), "sqlite"),
            *_ctr_fk,
            nullable=True,
        ),
    )

    # 3) Backfill primary-per-project.
    # Idempotent: skip any project that already has a primary. For the rest,
    # pick the container with port=3000 if any, else the earliest created_at.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(
            sa.text(
                """
                WITH candidates AS (
                    SELECT DISTINCT ON (c.project_id) c.id, c.project_id
                    FROM containers c
                    WHERE c.project_id NOT IN (
                        SELECT project_id FROM containers WHERE is_primary
                    )
                    ORDER BY
                        c.project_id,
                        CASE WHEN c.port = 3000 THEN 0 ELSE 1 END,
                        c.created_at ASC,
                        c.id ASC
                )
                UPDATE containers
                SET is_primary = TRUE
                FROM candidates
                WHERE containers.id = candidates.id
                """
            )
        )
    else:
        # SQLite: no DISTINCT ON or UPDATE FROM; use a subquery approach
        bind.execute(
            sa.text(
                """
                UPDATE containers
                SET is_primary = TRUE
                WHERE id IN (
                    SELECT id FROM (
                        SELECT c.id,
                               ROW_NUMBER() OVER (
                                   PARTITION BY c.project_id
                                   ORDER BY CASE WHEN c.port = 3000 THEN 0 ELSE 1 END,
                                            c.created_at ASC, c.id ASC
                               ) AS rn
                        FROM containers c
                        WHERE c.project_id NOT IN (
                            SELECT project_id FROM containers WHERE is_primary = TRUE
                        )
                    ) sub WHERE rn = 1
                )
                """
            )
        )


def downgrade() -> None:
    op.drop_column("app_instances", "primary_container_id")
    op.drop_index("ix_containers_one_primary", table_name="containers")
    op.drop_column("containers", "is_primary")
