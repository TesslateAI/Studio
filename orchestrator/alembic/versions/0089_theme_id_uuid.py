"""theme.id string -> uuid GUID + matching FK swaps (Wave 1.5).

Revision ID: 0089_theme_id_uuid
Revises: 0088_marketplace_sources
Create Date: 2026-04-29

Wave 1.5 of the federated-marketplace decoupling. **Forward-only — there
is no downgrade()**. The plan explicitly designates this as a destructive
sub-wave that ships in its own release with a maintenance window.

Today ``Theme.id`` is a ``String(100)`` PK whose value doubles as the
human-readable slug (e.g. ``"midnight-dark"``). After Wave 1 every other
catalog table (``marketplace_agents``, ``marketplace_apps``, ...) keys on
a real ``GUID`` UUID. This migration brings ``Theme`` in line so the
federation model can talk about every catalog kind uniformly via
``(source_id, slug)``.

Two FKs reference ``themes.id`` and have to be migrated atomically:

  - ``themes.parent_theme_id`` (self-referential, for fork lineage)
  - ``user_library_themes.theme_id`` (user-state)

There is also a unique constraint
``uq_user_library_theme_team(user_id, theme_id, team_id)`` that includes
``theme_id`` and must be rebuilt to reference the new GUID column.

Steps (every step a discrete ``op.execute`` so the swap is observable in
production logs):

  1. Pre-flight backups: ``themes_backup_2026_04_29`` and
     ``user_library_themes_backup_2026_04_29`` via
     ``CREATE TABLE ... AS SELECT *``.

  2. Add new columns:
       - ``themes.uuid``                      GUID NOT NULL DEFAULT random uuid
       - ``themes.parent_theme_uuid``         GUID NULL
       - ``user_library_themes.theme_uuid``   GUID NULL
     ``themes.slug`` already exists (added pre-Wave 1, populated by
     ``app/seeds/themes.py``); do NOT re-add. ``themes.source_id`` is
     already added by alembic 0088_marketplace_sources; do NOT re-add.

  3. Backfill:
       - ``themes.uuid`` is auto-populated by the column DEFAULT on insert,
         but for the existing 43+ rows we must ``UPDATE themes SET uuid =
         <generated>`` per row (Postgres uses ``gen_random_uuid()``;
         SQLite uses Python-generated UUIDs).
       - ``user_library_themes.theme_uuid``  ← lookup via
         ``themes.uuid WHERE themes.id = user_library_themes.theme_id``.
       - ``themes.parent_theme_uuid``        ← same lookup pattern via the
         self-FK.

  4. Integrity verification — hard abort if any of the following fail:
       - row count of ``themes`` matches its backup table
       - row count of ``user_library_themes`` matches its backup table
       - ``user_library_themes.theme_uuid`` IS NULL count is zero
       - ``themes.parent_theme_id IS NOT NULL AND parent_theme_uuid IS NULL``
         count is zero

  5. FK swap — exact ordered steps:
       a. drop ``user_library_themes_theme_id_fkey``
       b. drop ``fk_themes_parent_theme_id``      (Wave 1's name; the plan
          calls this ``themes_parent_theme_id_fkey`` but the actual
          constraint name in our schema follows the
          ``fk_<table>_<col>`` convention — we use the real name here)
       c. drop ``uq_user_library_theme_team``     (the (user_id, theme_id,
          team_id) constraint includes theme_id and must be rebuilt)
       d. drop ``themes_pkey`` + ``ix_themes_id``
       e. rename ``themes.id``                  → ``id_legacy``
       f. rename ``themes.uuid``                → ``id``
       g. add  PRIMARY KEY (id) on themes
       h. recreate ``ix_themes_id`` (UUID-typed, so the old index would
          be width-mismatched anyway)
       i. rename ``themes.parent_theme_id``     → ``parent_theme_id_legacy``
       j. rename ``themes.parent_theme_uuid``   → ``parent_theme_id``
       k. add  ``themes_parent_theme_id_fkey``  (self-FK, ON DELETE SET NULL
          to match the model's ondelete='SET NULL')
       l. rename ``user_library_themes.theme_id``  → ``theme_id_legacy``
       m. rename ``user_library_themes.theme_uuid`` → ``theme_id``
       n. add  ``user_library_themes_theme_id_fkey`` (ON DELETE CASCADE)
       o. recreate ``uq_user_library_theme_team`` on the new GUID
          ``theme_id``

  6. Drop the legacy columns once the new FKs are healthy:
       - ``themes.id_legacy``
       - ``themes.parent_theme_id_legacy``
       - ``user_library_themes.theme_id_legacy``

  7. ``uq_themes_source_slug(source_id, slug)`` is already created by
     alembic 0088_marketplace_sources — verified at migration end and
     skipped if present, created if absent (defensive).

The ``_backup`` tables are deliberately retained for 90 days per the plan
and are NOT cleaned up here.
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.types.guid import GUID

# ---------------------------------------------------------------------------
# Alembic identifiers
# ---------------------------------------------------------------------------

revision: str = "0089_theme_id_uuid"
down_revision: str | Sequence[str] | None = "0088_marketplace_sources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Fixed date suffix for the backup tables. The plan says these stay
# around for 90 days then get dropped via a separate one-shot.
BACKUP_DATE = "2026_04_29"
THEMES_BACKUP = f"themes_backup_{BACKUP_DATE}"
ULT_BACKUP = f"user_library_themes_backup_{BACKUP_DATE}"


# Constraint names — looked up against the live schema. The
# ``fk_themes_parent_theme_id`` variant matches the
# ``fk_<table>_<col>`` convention this project uses (see
# ``alembic/versions/0088_marketplace_sources.py``); the
# ``user_library_themes_theme_id_fkey`` variant matches the legacy
# server-default convention because the FK was created without an
# explicit name in the original migration.
PARENT_FK_NAME_OLD_CANDIDATES = [
    "fk_themes_parent_theme_id",  # explicit-name convention
    "themes_parent_theme_id_fkey",  # server-default name (rarely used here)
]
PARENT_FK_NAME_NEW = "themes_parent_theme_id_fkey"
ULT_FK_NAME = "user_library_themes_theme_id_fkey"
ULT_UNIQUE_NAME = "uq_user_library_theme_team"


def _drop_constraint_if_exists(
    bind: sa.engine.Connection, table: str, name: str, kind: str
) -> bool:
    """Drop a Postgres constraint by name if it exists; return whether it
    was actually dropped. ``kind`` is one of ``foreignkey`` / ``unique`` /
    ``primary``. SQLite doesn't expose constraint names cleanly so we
    branch on dialect at the call site instead.
    """
    if bind.dialect.name != "postgresql":
        # The caller routes SQLite through batch_alter_table; this helper
        # is Postgres-only. Returning False makes the conditional drop a
        # no-op on SQLite without us needing to special-case.
        return False
    exists = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE table_name = :table AND constraint_name = :name"
        ),
        {"table": table, "name": name},
    ).first()
    if exists:
        op.drop_constraint(name, table, type_=kind)
        return True
    return False


def upgrade() -> None:  # noqa: PLR0915 — every step is load-bearing
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    # ------------------------------------------------------------------
    # 1. Pre-flight backups
    # ------------------------------------------------------------------
    # ``CREATE TABLE ... AS SELECT *`` is supported by both Postgres and
    # SQLite. We deliberately don't copy indexes / FKs — these are pure
    # data backups for emergency rollback within the 90-day window.
    op.execute(sa.text(f"CREATE TABLE {THEMES_BACKUP} AS SELECT * FROM themes"))
    op.execute(
        sa.text(f"CREATE TABLE {ULT_BACKUP} AS SELECT * FROM user_library_themes")
    )

    # Snapshot row counts up front for the integrity verification step
    # below. We use the backup tables (not a live re-count) so an
    # in-flight INSERT/DELETE during the maintenance window can never
    # fool the check.
    themes_backup_count = bind.execute(
        sa.text(f"SELECT count(*) FROM {THEMES_BACKUP}")
    ).scalar_one()
    ult_backup_count = bind.execute(
        sa.text(f"SELECT count(*) FROM {ULT_BACKUP}")
    ).scalar_one()
    parent_link_count = bind.execute(
        sa.text(
            f"SELECT count(*) FROM {THEMES_BACKUP} WHERE parent_theme_id IS NOT NULL"
        )
    ).scalar_one()

    # ------------------------------------------------------------------
    # 2. Add new GUID columns. ``themes.slug`` and ``themes.source_id``
    #    already exist (Wave 0 + Wave 1 respectively) — do NOT re-add.
    # ------------------------------------------------------------------
    if is_postgres:
        # Postgres path: use a server-side default so the backfill UPDATE
        # is unnecessary — every existing row gets a fresh UUID at column
        # add time. ``gen_random_uuid()`` is built into Postgres 13+.
        op.execute(
            sa.text(
                "ALTER TABLE themes ADD COLUMN uuid uuid NOT NULL DEFAULT gen_random_uuid()"
            )
        )
    else:
        # SQLite path: add nullable, then UPDATE row-by-row with Python
        # UUIDs (CHAR(36) canonical), then SET NOT NULL via batch.
        with op.batch_alter_table("themes") as batch:
            batch.add_column(sa.Column("uuid", GUID(), nullable=True))
        rows = bind.execute(sa.text("SELECT id FROM themes")).fetchall()
        for (legacy_id,) in rows:
            bind.execute(
                sa.text("UPDATE themes SET uuid = :u WHERE id = :id"),
                {"u": str(uuid.uuid4()), "id": legacy_id},
            )
        with op.batch_alter_table("themes") as batch:
            batch.alter_column("uuid", existing_type=GUID(), nullable=False)

    # parent_theme_uuid is NULL by default; it gets backfilled in step 3.
    with op.batch_alter_table("themes") as batch:
        batch.add_column(sa.Column("parent_theme_uuid", GUID(), nullable=True))

    # user_library_themes.theme_uuid same shape.
    with op.batch_alter_table("user_library_themes") as batch:
        batch.add_column(sa.Column("theme_uuid", GUID(), nullable=True))

    # ------------------------------------------------------------------
    # 3. Backfill the new GUID columns from the old String(100) FKs
    # ------------------------------------------------------------------
    op.execute(
        sa.text(
            "UPDATE user_library_themes SET theme_uuid = ("
            "  SELECT t.uuid FROM themes t WHERE t.id = user_library_themes.theme_id"
            ")"
        )
    )
    op.execute(
        sa.text(
            "UPDATE themes SET parent_theme_uuid = ("
            "  SELECT p.uuid FROM themes p WHERE p.id = themes.parent_theme_id"
            ") WHERE parent_theme_id IS NOT NULL"
        )
    )

    # ------------------------------------------------------------------
    # 4. Integrity verification (hard abort on failure)
    # ------------------------------------------------------------------
    themes_count = bind.execute(sa.text("SELECT count(*) FROM themes")).scalar_one()
    if themes_count != themes_backup_count:
        raise RuntimeError(
            f"Integrity check failed: themes count drifted during migration "
            f"({themes_count} live vs {themes_backup_count} backup). Aborting."
        )

    ult_count = bind.execute(
        sa.text("SELECT count(*) FROM user_library_themes")
    ).scalar_one()
    if ult_count != ult_backup_count:
        raise RuntimeError(
            f"Integrity check failed: user_library_themes count drifted "
            f"({ult_count} live vs {ult_backup_count} backup). Aborting."
        )

    orphan_ult = bind.execute(
        sa.text(
            "SELECT count(*) FROM user_library_themes WHERE theme_uuid IS NULL"
        )
    ).scalar_one()
    if orphan_ult:
        raise RuntimeError(
            f"Integrity check failed: {orphan_ult} user_library_themes rows "
            f"have NULL theme_uuid (no matching themes.uuid for the legacy "
            f"theme_id). Investigate before retrying."
        )

    orphan_parents = bind.execute(
        sa.text(
            "SELECT count(*) FROM themes "
            "WHERE parent_theme_id IS NOT NULL AND parent_theme_uuid IS NULL"
        )
    ).scalar_one()
    if orphan_parents:
        raise RuntimeError(
            f"Integrity check failed: {orphan_parents} themes rows have a "
            f"parent_theme_id with no matching themes.uuid. Investigate."
        )

    # Sanity: every parent_theme_id should have backfilled.
    if parent_link_count and not bind.execute(
        sa.text("SELECT count(*) FROM themes WHERE parent_theme_uuid IS NOT NULL")
    ).scalar_one() == parent_link_count:
        raise RuntimeError(
            "Integrity check failed: parent_theme_uuid backfill did not "
            "match parent_theme_id non-null count from backup."
        )

    # ------------------------------------------------------------------
    # 5. FK swap — every step a discrete op.execute / op.drop_constraint
    # ------------------------------------------------------------------
    if is_postgres:
        # Postgres branch — drop FKs / unique by name, then run the
        # column renames + PK add via raw ALTER (op.execute) so the
        # operation log shows each ALTER individually.
        op.drop_constraint(ULT_FK_NAME, "user_library_themes", type_="foreignkey")
        for candidate in PARENT_FK_NAME_OLD_CANDIDATES:
            if _drop_constraint_if_exists(bind, "themes", candidate, "foreignkey"):
                break
        op.drop_constraint(ULT_UNIQUE_NAME, "user_library_themes", type_="unique")
        op.drop_constraint("themes_pkey", "themes", type_="primary")
        # ix_themes_id was an indexed copy of the old String(100) PK; it
        # gets recreated on the new UUID column post-rename.
        op.execute(sa.text("DROP INDEX IF EXISTS ix_themes_id"))

        op.execute(sa.text("ALTER TABLE themes RENAME COLUMN id TO id_legacy"))
        op.execute(sa.text("ALTER TABLE themes RENAME COLUMN uuid TO id"))
        op.execute(sa.text("ALTER TABLE themes ADD PRIMARY KEY (id)"))
        # Recreate the indexed-PK lookup index.
        op.create_index("ix_themes_id", "themes", ["id"])

        op.execute(
            sa.text("ALTER TABLE themes RENAME COLUMN parent_theme_id TO parent_theme_id_legacy")
        )
        op.execute(
            sa.text("ALTER TABLE themes RENAME COLUMN parent_theme_uuid TO parent_theme_id")
        )
        op.create_foreign_key(
            PARENT_FK_NAME_NEW,
            "themes",
            "themes",
            ["parent_theme_id"],
            ["id"],
            ondelete="SET NULL",
        )

        op.execute(
            sa.text("ALTER TABLE user_library_themes RENAME COLUMN theme_id TO theme_id_legacy")
        )
        op.execute(
            sa.text("ALTER TABLE user_library_themes RENAME COLUMN theme_uuid TO theme_id")
        )
        # New theme_id column is GUID and matches the new themes.id type.
        op.create_foreign_key(
            ULT_FK_NAME,
            "user_library_themes",
            "themes",
            ["theme_id"],
            ["id"],
            ondelete="CASCADE",
        )
        # Make the new theme_id NOT NULL (was nullable while we backfilled).
        op.alter_column(
            "user_library_themes", "theme_id", existing_type=GUID(), nullable=False
        )
        # Rebuild the (user_id, theme_id, team_id) unique constraint on
        # the new GUID column.
        op.create_unique_constraint(
            ULT_UNIQUE_NAME,
            "user_library_themes",
            ["user_id", "theme_id", "team_id"],
        )
    else:
        # SQLite branch — table rebuild via batch_alter_table. SQLite
        # cannot ALTER a column type or add a PK constraint in place, so
        # we rebuild atomically. The batch operation issues a single
        # CREATE TABLE _alembic_tmp ... + INSERT SELECT + DROP + RENAME
        # so the swap is still atomic from an outside observer's view.
        with op.batch_alter_table("user_library_themes") as batch:
            batch.drop_constraint(ULT_FK_NAME, type_="foreignkey")
            batch.drop_constraint(ULT_UNIQUE_NAME, type_="unique")
        with op.batch_alter_table("themes") as batch:
            for candidate in PARENT_FK_NAME_OLD_CANDIDATES:
                try:
                    batch.drop_constraint(candidate, type_="foreignkey")
                    break
                except Exception:  # noqa: BLE001 — drop_constraint raises on missing
                    continue

        # PK swap on themes via batch.
        with op.batch_alter_table("themes") as batch:
            batch.alter_column("id", new_column_name="id_legacy")
            batch.alter_column("uuid", new_column_name="id")
            batch.create_primary_key("themes_pkey", ["id"])
            batch.alter_column("parent_theme_id", new_column_name="parent_theme_id_legacy")
            batch.alter_column("parent_theme_uuid", new_column_name="parent_theme_id")
            batch.create_foreign_key(
                PARENT_FK_NAME_NEW,
                "themes",
                ["parent_theme_id"],
                ["id"],
                ondelete="SET NULL",
            )
        op.create_index("ix_themes_id", "themes", ["id"])

        with op.batch_alter_table("user_library_themes") as batch:
            batch.alter_column("theme_id", new_column_name="theme_id_legacy")
            batch.alter_column("theme_uuid", new_column_name="theme_id")
            batch.alter_column("theme_id", existing_type=GUID(), nullable=False)
            batch.create_foreign_key(
                ULT_FK_NAME,
                "themes",
                ["theme_id"],
                ["id"],
                ondelete="CASCADE",
            )
            batch.create_unique_constraint(
                ULT_UNIQUE_NAME, ["user_id", "theme_id", "team_id"]
            )

    # ------------------------------------------------------------------
    # 6. Drop the legacy String(100) columns
    # ------------------------------------------------------------------
    with op.batch_alter_table("themes") as batch:
        batch.drop_column("id_legacy")
        batch.drop_column("parent_theme_id_legacy")
    with op.batch_alter_table("user_library_themes") as batch:
        batch.drop_column("theme_id_legacy")

    # ------------------------------------------------------------------
    # 7. Verify uq_themes_source_slug exists (created by alembic 0088).
    #    Defensive: if the user is upgrading from a strange branch
    #    where 0088 ran without creating it (shouldn't happen), recreate.
    # ------------------------------------------------------------------
    if is_postgres:
        exists = bind.execute(
            sa.text(
                "SELECT 1 FROM pg_indexes WHERE tablename = 'themes' "
                "AND indexname = 'uq_themes_source_slug'"
            )
        ).first()
        if not exists:
            op.create_index(
                "uq_themes_source_slug",
                "themes",
                ["source_id", "slug"],
                unique=True,
            )
    else:
        # SQLite: pragma_index_list output is what introspection reads.
        rows = bind.execute(
            sa.text("PRAGMA index_list('themes')")
        ).fetchall()
        names = {r[1] for r in rows}  # column 1 is the index name
        if "uq_themes_source_slug" not in names:
            op.create_index(
                "uq_themes_source_slug",
                "themes",
                ["source_id", "slug"],
                unique=True,
            )


# Wave 1.5 is forward-only by explicit plan directive ("destructive
# sub-wave, forward-only"). Restoring the legacy String(100) PK after
# UUID rows have been minted is unsafe and would corrupt downstream
# user_library_themes joins. Use the ``themes_backup_<date>`` /
# ``user_library_themes_backup_<date>`` tables for emergency restore
# instead — they're retained for 90 days per the plan.
def downgrade() -> None:
    raise NotImplementedError(
        "0089_theme_id_uuid is forward-only. Wave 1.5 is a destructive "
        f"sub-wave per the federated-marketplace plan. Restore from "
        f"{THEMES_BACKUP} / {ULT_BACKUP} if rollback is required within "
        "the 90-day backup window."
    )
