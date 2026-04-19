"""Add containers.image and backfill from TSL_CONTAINER_IMAGE env hack.

Revision ID: 0064_container_image
Revises: 0063_app_primary_ctr
Create Date: 2026-04-15 10:00:00.000000

Before this migration, the Apps installer smuggled the manifest-declared
container image through ``environment_vars["TSL_CONTAINER_IMAGE"]`` and
compute_manager stripped the key at pod-spec build time. Any future
pod-spec path (init container, sidecar, Job) that forgot the strip would
leak the sentinel env var into the running pod.

This migration adds a dedicated nullable ``containers.image`` column,
backfills it from the env-var hack for all existing Containers, and
removes the TSL_CONTAINER_IMAGE key from their ``environment_vars``. The
compute_manager keeps a one-release read-time fallback to the env var so
any in-flight install that pre-dates this migration still boots.

Online-safe: column is nullable; backfill is a single UPDATE guarded by a
JSON predicate; idempotent on re-run.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0064_container_image"
down_revision: str | Sequence[str] | None = "0063_app_primary_ctr"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "containers",
        sa.Column("image", sa.String(), nullable=True),
    )

    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql":
        bind.execute(
            sa.text(
                """
                UPDATE containers
                SET
                    image = (environment_vars::jsonb)->>'TSL_CONTAINER_IMAGE',
                    environment_vars = ((environment_vars::jsonb) - 'TSL_CONTAINER_IMAGE')::json
                WHERE (environment_vars::jsonb) ? 'TSL_CONTAINER_IMAGE'
                  AND image IS NULL
                """
            )
        )
    else:
        # SQLite: json_extract / json_remove are available since 3.38.
        # Desktop installs are fresh — no legacy TSL_CONTAINER_IMAGE rows.
        bind.execute(
            sa.text(
                """
                UPDATE containers
                SET
                    image = json_extract(environment_vars, '$.TSL_CONTAINER_IMAGE'),
                    environment_vars = json_remove(environment_vars, '$.TSL_CONTAINER_IMAGE')
                WHERE json_extract(environment_vars, '$.TSL_CONTAINER_IMAGE') IS NOT NULL
                  AND image IS NULL
                """
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql":
        bind.execute(
            sa.text(
                """
                UPDATE containers
                SET environment_vars = (COALESCE(environment_vars::jsonb, '{}'::jsonb)
                                        || jsonb_build_object('TSL_CONTAINER_IMAGE', image))::json
                WHERE image IS NOT NULL
                """
            )
        )
    else:
        bind.execute(
            sa.text(
                """
                UPDATE containers
                SET environment_vars = json_patch(
                    COALESCE(environment_vars, '{}'),
                    json_object('TSL_CONTAINER_IMAGE', image)
                )
                WHERE image IS NOT NULL
                """
            )
        )
    op.drop_column("containers", "image")
