"""backfill app_versions.source_id from the parent marketplace_apps row (Wave 7).

Revision ID: 0092_app_versions_source_id_backfill
Revises: 0091_drop_legacy_slug_uq
Create Date: 2026-04-29

Wave 7 of the federated-marketplace decoupling. The
``app_versions.source_id`` column was added in Wave 1 (alembic 0088) so
the schema could carry per-version provenance, but the publisher only
started stamping it on insert from Wave 5 onwards. Rows published before
Wave 5 (or rows promoted via auto-approve in test setups that bypassed
the publisher) carry ``source_id = NULL``.

Wave 7 promotes the invariant ``app_versions.source_id ==
marketplace_apps.source_id`` to a hard service-level rule (see
``orchestrator/app/services/apps/app_version_source_consistency.py``),
so every existing row needs to be normalised. This migration:

  1. UPDATE app_versions SET source_id = marketplace_apps.source_id
     WHERE app_versions.source_id IS NULL OR app_versions.source_id <>
           marketplace_apps.source_id

  2. After backfill, validates that no orphan rows remain — fails the
     migration loud if any version still disagrees with its parent so
     operators can investigate before the consistency listener starts
     refusing writes at runtime.

This is forward-only; the downgrade is a no-op because re-NULL'ing
``source_id`` rows that were already set would lose provenance data
that downstream code (the Wave-7 install gate, the federation source
chip in the UI) depends on.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0092_app_versions_source_id_backfill"
down_revision: str | Sequence[str] | None = "0091_drop_legacy_slug_uq"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    # ------------------------------------------------------------------
    # 1. Backfill missing / mismatched source_id values from the parent.
    # ------------------------------------------------------------------
    # We do a single UPDATE ... FROM on Postgres and a correlated UPDATE
    # on SQLite (no FROM clause). Both touch the same rows; both are
    # idempotent — re-running the migration is a no-op.
    if is_postgres:
        op.execute(
            sa.text(
                """
                UPDATE app_versions AS av
                SET source_id = ma.source_id
                FROM marketplace_apps AS ma
                WHERE av.app_id = ma.id
                  AND av.source_id IS DISTINCT FROM ma.source_id
                """
            )
        )
    else:
        # SQLite has no UPDATE...FROM (in older versions) — use a
        # correlated subquery. This is slower but correct on the desktop
        # backend where the row count is small.
        op.execute(
            sa.text(
                """
                UPDATE app_versions
                SET source_id = (
                    SELECT marketplace_apps.source_id
                    FROM marketplace_apps
                    WHERE marketplace_apps.id = app_versions.app_id
                )
                WHERE EXISTS (
                    SELECT 1
                    FROM marketplace_apps
                    WHERE marketplace_apps.id = app_versions.app_id
                      AND (
                        app_versions.source_id IS NULL
                        OR app_versions.source_id IS NOT marketplace_apps.source_id
                      )
                )
                """
            )
        )

    # ------------------------------------------------------------------
    # 2. Defense-in-depth: assert the invariant holds after backfill.
    # ------------------------------------------------------------------
    # If any orphan remains the migration MUST fail loud — silently
    # leaving a mismatched row would let the Wave-7 consistency listener
    # raise AppVersionSourceMismatch on the first install attempt that
    # touches the row, with no clear breadcrumb pointing back at the
    # missed migration step.
    if is_postgres:
        result = bind.execute(
            sa.text(
                """
                SELECT COUNT(*)
                FROM app_versions av
                JOIN marketplace_apps ma ON ma.id = av.app_id
                WHERE av.source_id IS DISTINCT FROM ma.source_id
                """
            )
        ).scalar()
    else:
        result = bind.execute(
            sa.text(
                """
                SELECT COUNT(*)
                FROM app_versions av
                JOIN marketplace_apps ma ON ma.id = av.app_id
                WHERE av.source_id IS NOT ma.source_id
                """
            )
        ).scalar()

    orphan_count = int(result or 0)
    if orphan_count > 0:
        raise RuntimeError(
            f"Wave 7 migration 0092 detected {orphan_count} app_versions row(s) "
            "whose source_id still does not match the parent marketplace_apps "
            "row after backfill. This indicates an FK or data-integrity "
            "anomaly that must be resolved before the consistency listener "
            "is enabled at runtime."
        )


def downgrade() -> None:
    """Forward-only — see module docstring.

    Re-NULL-ing ``app_versions.source_id`` would discard provenance that
    Wave-7 install / browse paths now depend on.
    """
    raise NotImplementedError(
        "Wave 7 migration 0092 is forward-only. Restoring NULL source_id "
        "rows would break the install gate's source-trust check."
    )
