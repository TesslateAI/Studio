"""Partial UNIQUE on app_instances(installer_user_id, app_id) WHERE installed.

Revision ID: 0085_install_user_app_unique
Revises: 0084_contract_templates
Create Date: 2026-04-27

Closes a TOCTOU race in the install path. ``installer.install_app`` does a
SELECT to dedupe by ``(installer_user_id, app_id, state='installed')``,
then much later inserts the AppInstance. Two concurrent click-to-install
requests from the same user (e.g. an over-eager double-click while the
slow first install is in flight) both pass the SELECT and both succeed —
because the existing partial UNIQUE on ``app_instances(project_id) WHERE
state='installed' AND project_id IS NOT NULL`` only catches
shared_singleton reuse races, not per_install where each install gets a
fresh project_id.

This migration adds the missing partial UNIQUE on
``(installer_user_id, app_id) WHERE state='installed'``. Combined with
the Postgres advisory lock the install path now takes
(``pg_advisory_xact_lock`` keyed on the same tuple), concurrent installs
serialize cleanly: the second waits for the first, sees the freshly-
installed row, and bails before any side effects (Hub volume, project
create, namespace mint).

Pre-step: dedupe existing data
------------------------------
If duplicate ``state='installed'`` rows exist for the same
``(installer_user_id, app_id)`` (legacy state from before this fix), the
``CREATE UNIQUE INDEX`` would fail. We resolve by keeping the OLDEST
``installed`` row per pair and marking the rest ``state='uninstalled'``
with a clear ``uninstalled_at`` timestamp. The K8s namespace + PVC + Hub
volume for the soft-uninstalled rows are NOT released by this migration —
the orphan-namespace reaper handles that on its next sweep, and the
``app_install_attempts`` saga ledger keeps the volume_id linkage so the
Hub-side volume gets reaped once no live AppInstance points at it.

"Oldest survives" is the principled rule because it matches user intent:
when a user double-clicks install, the first click is the one they meant;
the second is accidental.

Portability
-----------
Partial unique indexes work on Postgres and SQLite (3.8+). The same
``WHERE state = 'installed'`` predicate is portable across both. Alembic
``op.create_index(..., postgresql_where=..., sqlite_where=...)`` would
double-up the predicate; we use ``postgresql_where`` for prod and rely on
the SQLAlchemy model ``Index(...)`` definition to mirror the constraint
on SQLite-backed test fixtures.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0085_install_user_app_unique"
down_revision: str | Sequence[str] | None = "0084_contract_templates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_INDEX_NAME = "uq_app_instances_user_app_installed"


def upgrade() -> None:
    bind = op.get_bind()

    # Step 1 — collapse existing duplicates so the unique index can be
    # created without an operator data-fixup. Keep the oldest (by
    # ``installed_at`` then ``created_at``) installed row per (user, app);
    # mark the rest uninstalled with a recognizable timestamp.
    #
    # Run this on every backend (Postgres and SQLite) so dev-mode test
    # fixtures behave the same as prod after migrating.
    bind.exec_driver_sql(
        """
        WITH ranked AS (
            SELECT
                id,
                installer_user_id,
                app_id,
                ROW_NUMBER() OVER (
                    PARTITION BY installer_user_id, app_id
                    ORDER BY
                        COALESCE(installed_at, created_at) ASC,
                        id ASC
                ) AS rn
            FROM app_instances
            WHERE state = 'installed'
        )
        UPDATE app_instances
           SET state = 'uninstalled',
               uninstalled_at = COALESCE(uninstalled_at, CURRENT_TIMESTAMP),
               project_id = NULL
         WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
        """
    )

    # Step 2 — partial UNIQUE index. ``postgresql_where`` ensures the
    # predicate is emitted on Postgres; for SQLite we issue raw DDL since
    # alembic ``op.create_index`` doesn't accept a ``sqlite_where``
    # argument and the predicate is required for the per_install
    # tenancy model (a user CAN have one ``installed`` + several
    # ``uninstalled`` rows for the same app — each uninstall keeps the
    # historical row around).
    if bind.dialect.name == "sqlite":
        bind.exec_driver_sql(
            f"CREATE UNIQUE INDEX {_INDEX_NAME} "
            "ON app_instances (installer_user_id, app_id) "
            "WHERE state = 'installed'"
        )
    else:
        op.create_index(
            _INDEX_NAME,
            "app_instances",
            ["installer_user_id", "app_id"],
            unique=True,
            postgresql_where="state = 'installed'",
        )


def downgrade() -> None:
    op.drop_index(_INDEX_NAME, table_name="app_instances")
    # No data-restore step on downgrade — the soft-uninstalled rows stay
    # uninstalled. Re-installing remains a one-click action through the
    # install router.
