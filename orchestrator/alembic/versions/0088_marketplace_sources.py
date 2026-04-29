"""marketplace sources + catalog cache columns (Wave 1).

Revision ID: 0088_marketplace_sources
Revises: 0087_automation_app_inst
Create Date: 2026-04-29

Wave 1 of the federated-marketplace decoupling. Purely additive:

1. Creates ``marketplace_sources`` — the registry of which hubs each
   user/team can pull catalog content from. Two immutable system rows are
   seeded with deterministic UUIDs so application code can look them up
   without a handle query:

     - tesslate-official  (00000000-0000-0000-0000-000000000001)
     - local              (00000000-0000-0000-0000-000000000002)

2. Adds source-tracking + provenance + cache cleanup columns to every
   catalog table:

     marketplace_agents, marketplace_bases, marketplace_apps,
     app_versions, themes, workflow_templates

   ``source_id`` is FK-RESTRICT against marketplace_sources.id (we never
   want to silently delete catalog rows when a source is removed — admin
   action is required first).

3. Backfills ``source_id`` so it can be flipped NOT NULL:

     - rows with a non-null creator FK    → ``local``
     - rows with no creator (or workflow_templates, which has no creator
       column)                              → ``tesslate-official``
     - app_versions inherit from parent app

4. Adds ``(source_id, slug)`` composite unique indexes on the five
   sluggable catalog tables, alongside the existing global ``slug
   unique=True`` constraint. Both invariants coexist until Wave 5.
   ``marketplace_apps`` also gets ``(source_id, creator_user_id, handle)``
   alongside the existing ``(creator_user_id, handle)``.

   Postgres uses ``CREATE UNIQUE INDEX CONCURRENTLY`` (non-blocking, big
   table safe). SQLite uses plain ``CREATE UNIQUE INDEX``.

Wave 1 deliberately does NOT change ``Theme.id`` from String(100) to GUID
(that's Wave 1.5) and does NOT drop any existing global slug uniqueness
constraint (that's Wave 5).
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.types.guid import GUID

revision: str = "0088_marketplace_sources"
down_revision: str | Sequence[str] | None = "0087_automation_app_inst"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Deterministic UUIDs for the two seeded system rows. Application code
# references these constants; do NOT regenerate them.
TESSLATE_OFFICIAL_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
LOCAL_SOURCE_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")


# (table_name, has_creator_fk_column) — workflow_templates has no creator
# column, so all its rows backfill to tesslate-official.
CATALOG_TABLES_WITH_SLUG: list[tuple[str, bool]] = [
    ("marketplace_agents", True),  # created_by_user_id
    ("marketplace_bases", True),  # created_by_user_id
    ("marketplace_apps", True),  # creator_user_id (different name)
    ("themes", True),  # created_by_user_id
    ("workflow_templates", False),  # no creator column
]


def _cache_columns(table_name: str) -> list[sa.Column]:
    """Cache + provenance columns added to every catalog table.

    ``source_id`` ships nullable here; the migration backfills it then
    flips NOT NULL inside a batch_alter_table block (so SQLite is happy
    too). The FK constraint is explicitly named — SQLite batch mode
    rebuilds the table on every alter and refuses to inline an unnamed
    constraint.
    """
    return [
        sa.Column(
            "source_id",
            GUID(),
            sa.ForeignKey(
                "marketplace_sources.id",
                name=f"fk_{table_name}_source_id",
                ondelete="RESTRICT",
            ),
            nullable=True,
        ),
        sa.Column("source_etag", sa.String(128), nullable=True),
        sa.Column("source_remote_id", sa.String(128), nullable=True),
        sa.Column("source_pricing_type_original", sa.String(32), nullable=True),
        sa.Column("source_pricing_payload_original", sa.JSON(), nullable=True),
        sa.Column("source_pricing_stripped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "source_pricing_ignored",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "deleted_upstream",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("deleted_upstream_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deactivated_upstream_at", sa.DateTime(timezone=True), nullable=True),
    ]


CACHE_COLUMN_NAMES = [
    "source_id",
    "source_etag",
    "source_remote_id",
    "source_pricing_type_original",
    "source_pricing_payload_original",
    "source_pricing_stripped_at",
    "source_pricing_ignored",
    "deleted_upstream",
    "deleted_upstream_at",
    "deactivated_upstream_at",
]


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    # ------------------------------------------------------------------
    # 1. Create marketplace_sources
    # ------------------------------------------------------------------
    op.create_table(
        "marketplace_sources",
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("handle", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("encrypted_token", sa.Text(), nullable=True),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column(
            "user_id",
            GUID(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "team_id",
            GUID(),
            sa.ForeignKey("teams.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("trust_level", sa.String(16), nullable=False),
        sa.Column("pinned_hub_id", sa.String(128), nullable=True),
        sa.Column("capabilities_cache", sa.JSON(), nullable=True),
        sa.Column("policies_cache", sa.JSON(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sync_etag", sa.String(128), nullable=True),
        sa.Column("last_sync_error", sa.Text(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "(scope = 'system' AND user_id IS NULL AND team_id IS NULL) OR "
            "(scope = 'user'   AND user_id IS NOT NULL AND team_id IS NULL) OR "
            "(scope = 'team'   AND team_id IS NOT NULL AND user_id IS NULL)",
            name="ck_msrc_scope_owner",
        ),
    )

    # Partial unique indexes per scope. Both Postgres and SQLite support
    # ``CREATE UNIQUE INDEX ... WHERE ...``.
    op.create_index(
        "uq_msrc_system_handle",
        "marketplace_sources",
        ["handle"],
        unique=True,
        postgresql_where=sa.text("scope = 'system'"),
        sqlite_where=sa.text("scope = 'system'"),
    )
    op.create_index(
        "uq_msrc_user_handle",
        "marketplace_sources",
        ["user_id", "handle"],
        unique=True,
        postgresql_where=sa.text("scope = 'user'"),
        sqlite_where=sa.text("scope = 'user'"),
    )
    op.create_index(
        "uq_msrc_team_handle",
        "marketplace_sources",
        ["team_id", "handle"],
        unique=True,
        postgresql_where=sa.text("scope = 'team'"),
        sqlite_where=sa.text("scope = 'team'"),
    )

    # ------------------------------------------------------------------
    # 2. Seed the two immutable system rows (deterministic UUIDs)
    # ------------------------------------------------------------------
    op.execute(
        sa.text(
            """
            INSERT INTO marketplace_sources
                (id, handle, display_name, base_url, scope, trust_level, is_active)
            VALUES
                (:tesslate_id, 'tesslate-official', 'Tesslate Official',
                 'https://marketplace.tesslate.com', 'system', 'official', :is_active_true),
                (:local_id, 'local', 'Local',
                 'local://filesystem', 'system', 'local', :is_active_true)
            """
        ).bindparams(
            tesslate_id=str(TESSLATE_OFFICIAL_ID),
            local_id=str(LOCAL_SOURCE_ID),
            is_active_true=True,
        )
    )

    # ------------------------------------------------------------------
    # 3. Add cache + provenance columns to every catalog table
    # ------------------------------------------------------------------
    all_catalog_tables = [t for t, _ in CATALOG_TABLES_WITH_SLUG] + ["app_versions"]

    for tbl in all_catalog_tables:
        with op.batch_alter_table(tbl) as batch:
            for col in _cache_columns(tbl):
                batch.add_column(col)
            if tbl == "app_versions":
                batch.add_column(
                    sa.Column("yanked_upstream_at", sa.DateTime(timezone=True), nullable=True)
                )

    # Plain (non-unique) index on source_id for join performance.
    for tbl in all_catalog_tables:
        op.create_index(f"ix_{tbl}_source_id", tbl, ["source_id"])

    # ------------------------------------------------------------------
    # 4. Backfill source_id
    # ------------------------------------------------------------------
    # Tesslate-authored rows (no creator FK) → tesslate-official.
    # All remaining rows                       → local.
    # Order matters: WHERE creator IS NULL first, then WHERE source_id IS NULL.
    tess_param = {"tess_id": str(TESSLATE_OFFICIAL_ID)}
    local_param = {"local_id": str(LOCAL_SOURCE_ID)}

    op.execute(
        sa.text(
            "UPDATE marketplace_agents SET source_id = :tess_id WHERE created_by_user_id IS NULL"
        ).bindparams(**tess_param)
    )
    op.execute(
        sa.text(
            "UPDATE marketplace_agents SET source_id = :local_id WHERE source_id IS NULL"
        ).bindparams(**local_param)
    )

    op.execute(
        sa.text(
            "UPDATE marketplace_bases SET source_id = :tess_id WHERE created_by_user_id IS NULL"
        ).bindparams(**tess_param)
    )
    op.execute(
        sa.text(
            "UPDATE marketplace_bases SET source_id = :local_id WHERE source_id IS NULL"
        ).bindparams(**local_param)
    )

    # marketplace_apps uses creator_user_id (different name)
    op.execute(
        sa.text(
            "UPDATE marketplace_apps SET source_id = :tess_id WHERE creator_user_id IS NULL"
        ).bindparams(**tess_param)
    )
    op.execute(
        sa.text(
            "UPDATE marketplace_apps SET source_id = :local_id WHERE source_id IS NULL"
        ).bindparams(**local_param)
    )

    op.execute(
        sa.text(
            "UPDATE themes SET source_id = :tess_id WHERE created_by_user_id IS NULL"
        ).bindparams(**tess_param)
    )
    op.execute(
        sa.text(
            "UPDATE themes SET source_id = :local_id WHERE source_id IS NULL"
        ).bindparams(**local_param)
    )

    # workflow_templates has no creator column → all to tesslate-official.
    op.execute(
        sa.text(
            "UPDATE workflow_templates SET source_id = :tess_id WHERE source_id IS NULL"
        ).bindparams(**tess_param)
    )

    # app_versions inherit from parent marketplace_apps. Run AFTER the
    # marketplace_apps backfill above so the parent row's source_id is set.
    op.execute(
        sa.text(
            """
            UPDATE app_versions
            SET source_id = (
                SELECT source_id FROM marketplace_apps
                WHERE marketplace_apps.id = app_versions.app_id
            )
            """
        )
    )

    # ------------------------------------------------------------------
    # 5. Flip source_id NOT NULL on every catalog table
    # ------------------------------------------------------------------
    for tbl in all_catalog_tables:
        with op.batch_alter_table(tbl) as batch:
            batch.alter_column("source_id", nullable=False, existing_type=GUID())

    # ------------------------------------------------------------------
    # 6. Composite (source_id, slug) unique indexes — five sluggable tables
    # ------------------------------------------------------------------
    # Postgres prod gets CONCURRENTLY (no table lock). SQLite cannot run
    # CONCURRENTLY and the desktop catalog tables are tiny, so a plain
    # CREATE UNIQUE INDEX is fine.
    sluggable = [t for t, _ in CATALOG_TABLES_WITH_SLUG]
    for tbl in sluggable:
        idx_name = f"uq_{tbl}_source_slug"
        if is_postgres:
            with op.get_context().autocommit_block():
                op.execute(
                    sa.text(
                        f"CREATE UNIQUE INDEX CONCURRENTLY {idx_name} "
                        f"ON {tbl} (source_id, slug)"
                    )
                )
        else:
            op.create_index(idx_name, tbl, ["source_id", "slug"], unique=True)

    # marketplace_apps additionally gets (source_id, creator_user_id, handle)
    # alongside the existing (creator_user_id, handle) — both invariants
    # coexist until Wave 5.
    apps_handle_idx = "uq_marketplace_apps_source_creator_handle"
    if is_postgres:
        with op.get_context().autocommit_block():
            op.execute(
                sa.text(
                    f"CREATE UNIQUE INDEX CONCURRENTLY {apps_handle_idx} "
                    f"ON marketplace_apps (source_id, creator_user_id, handle)"
                )
            )
    else:
        op.create_index(
            apps_handle_idx,
            "marketplace_apps",
            ["source_id", "creator_user_id", "handle"],
            unique=True,
        )


def downgrade() -> None:
    sluggable = [t for t, _ in CATALOG_TABLES_WITH_SLUG]
    all_catalog_tables = sluggable + ["app_versions"]

    # Drop the (source_id, slug) composite unique indexes first; they
    # reference source_id so they must go before the column.
    op.drop_index(
        "uq_marketplace_apps_source_creator_handle",
        table_name="marketplace_apps",
    )
    for tbl in sluggable:
        op.drop_index(f"uq_{tbl}_source_slug", table_name=tbl)

    # Drop ix_<tbl>_source_id then the cache columns themselves.
    for tbl in all_catalog_tables:
        op.drop_index(f"ix_{tbl}_source_id", table_name=tbl)
        with op.batch_alter_table(tbl) as batch:
            if tbl == "app_versions":
                batch.drop_column("yanked_upstream_at")
            for col_name in reversed(CACHE_COLUMN_NAMES):
                batch.drop_column(col_name)

    # Drop marketplace_sources (indexes auto-drop with the table on
    # Postgres; explicit drops keep parity for SQLite + readability).
    op.drop_index("uq_msrc_team_handle", table_name="marketplace_sources")
    op.drop_index("uq_msrc_user_handle", table_name="marketplace_sources")
    op.drop_index("uq_msrc_system_handle", table_name="marketplace_sources")
    op.drop_table("marketplace_sources")
