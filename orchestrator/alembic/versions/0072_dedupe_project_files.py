"""Dedupe project_files and add unique (project_id, file_path).

Revision ID: 0072_dedupe_project_files
Revises: 0071_scrub_git_remote_url_tokens
Create Date: 2026-04-25

Backfill for a TOCTOU race in the project_files upsert path. Two
concurrent saves of the same ``(project_id, file_path)`` could each
SELECT (find nothing), then INSERT — producing duplicate rows that
later cause every save to that path to fail with
``MultipleResultsFound`` from ``scalar_one_or_none()``.

Most observed duplicates came from the design-bridge installer, which
only runs on frontend-framework projects (Next.js / Vite / CRA / Vue /
Svelte / Astro / Angular / plain HTML — see
``app/src/components/views/design/bridgeInstaller.ts``). The underlying
race could in principle hit any caller, so the constraint is added
globally and all writers are routed through
``services.project_files.upsert_project_file()`` which uses
dialect-native ``ON CONFLICT DO UPDATE``.

This migration:
  1. Deletes duplicate rows, keeping the most recent per
     (project_id, file_path) — newest by ``COALESCE(updated_at,
     created_at)``, ties broken by ``id``.
  2. Adds the ``uq_project_files_project_path`` unique constraint.

Cross-DB: the dedup query uses ``ROW_NUMBER()`` (works on PostgreSQL
and SQLite >= 3.25; we ship 3.31+). Constraint creation uses
``batch_alter_table`` so SQLite can rebuild the table.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0072_dedupe_project_files"
down_revision: str | None = "0071_scrub_git_remote_url_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_DEDUP_SQL = """
DELETE FROM project_files
WHERE id IN (
    SELECT id FROM (
        SELECT id, ROW_NUMBER() OVER (
            PARTITION BY project_id, file_path
            ORDER BY COALESCE(updated_at, created_at) DESC, id DESC
        ) AS rn
        FROM project_files
    ) ranked
    WHERE rn > 1
)
"""


def upgrade() -> None:
    # 1. De-dupe in place. Single statement, fully indexable on the
    #    existing PK; brief AccessExclusive on PostgreSQL.
    op.execute(_DEDUP_SQL)

    # 2. Enforce uniqueness going forward. batch mode for SQLite.
    with op.batch_alter_table("project_files") as batch_op:
        batch_op.create_unique_constraint(
            "uq_project_files_project_path",
            ["project_id", "file_path"],
        )


def downgrade() -> None:
    # Constraint-only: dedup cannot be reversed (data loss is permanent
    # by design — duplicates were never wanted).
    with op.batch_alter_table("project_files") as batch_op:
        batch_op.drop_constraint(
            "uq_project_files_project_path", type_="unique"
        )
