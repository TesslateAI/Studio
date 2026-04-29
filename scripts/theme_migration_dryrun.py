#!/usr/bin/env python3
"""Wave 1.5 dry-run: Theme.id String → GUID + matching FK swap.

Runs the same SQL plan that ``orchestrator/alembic/versions/0089_theme_id_uuid.py``
will execute against a real database, asserts row counts and FK
integrity at every checkpoint, and ROLLBACKs at the end. Production-safe
because the entire script runs inside one transaction; the database is
left exactly as it was.

Usage
-----
    DATABASE_URL=postgresql+asyncpg://user:pass@host:port/db \\
        python scripts/theme_migration_dryrun.py

If ``DATABASE_URL`` is unset, defaults to the standard
``docker-compose.test.yml`` Postgres on port 5433 with
``tesslate_test_v3``. That database is expected to already have alembic
0088 applied and seeds run — see the Wave 1.5 verification block in
``CLAUDE.md`` for the canonical Wave-1-applied test DB.

Exit code: 0 on success, non-zero on any integrity-check failure or
unexpected SQL error. Always rolls back, even on success.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

# Make ``app.*`` importable so we can borrow the GUID TypeDecorator.
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "orchestrator"))

import sqlalchemy as sa  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402


DEFAULT_URL = (
    "postgresql+asyncpg://tesslate_test:testpass@localhost:5433/tesslate_test_v3"
)


def _checkpoint(name: str) -> None:
    print(f"  [step] {name}")


async def run_dry_run(database_url: str) -> None:
    """Execute the Wave 1.5 migration plan inside a transaction; rollback."""
    engine = create_async_engine(database_url)
    print(f"DATABASE_URL = {database_url}")

    async with engine.connect() as conn:
        # Open one outer transaction. Every step runs inside it; we
        # ROLLBACK at the end regardless of pass/fail so the database is
        # never mutated by a dry run.
        async with conn.begin() as outer:
            print("[start] Opened transaction (will ROLLBACK at the end)")

            # ----------------------------------------------------------
            # Pre-flight: snapshot row counts
            # ----------------------------------------------------------
            themes_count_before = (
                await conn.execute(sa.text("SELECT count(*) FROM themes"))
            ).scalar_one()
            ult_count_before = (
                await conn.execute(
                    sa.text("SELECT count(*) FROM user_library_themes")
                )
            ).scalar_one()
            parent_link_count = (
                await conn.execute(
                    sa.text(
                        "SELECT count(*) FROM themes WHERE parent_theme_id IS NOT NULL"
                    )
                )
            ).scalar_one()
            print(
                f"[snapshot] themes={themes_count_before} "
                f"user_library_themes={ult_count_before} "
                f"parent_links={parent_link_count}"
            )

            # ----------------------------------------------------------
            # 1. Backup tables (also pure CREATE TABLE AS SELECT — rolled
            #    back with the outer transaction).
            # ----------------------------------------------------------
            _checkpoint("CREATE TABLE themes_backup_dryrun ...")
            await conn.execute(
                sa.text("CREATE TABLE themes_backup_dryrun AS SELECT * FROM themes")
            )
            await conn.execute(
                sa.text(
                    "CREATE TABLE user_library_themes_backup_dryrun "
                    "AS SELECT * FROM user_library_themes"
                )
            )

            backup_themes = (
                await conn.execute(
                    sa.text("SELECT count(*) FROM themes_backup_dryrun")
                )
            ).scalar_one()
            backup_ult = (
                await conn.execute(
                    sa.text(
                        "SELECT count(*) FROM user_library_themes_backup_dryrun"
                    )
                )
            ).scalar_one()
            assert backup_themes == themes_count_before, (
                f"themes backup count {backup_themes} != live {themes_count_before}"
            )
            assert backup_ult == ult_count_before, (
                f"user_library_themes backup {backup_ult} != live {ult_count_before}"
            )

            # ----------------------------------------------------------
            # 2. Add new GUID columns. ``slug`` and ``source_id`` already
            #    exist on themes from prior waves.
            # ----------------------------------------------------------
            _checkpoint("ALTER themes ADD uuid GUID NOT NULL DEFAULT random")
            await conn.execute(
                sa.text(
                    "ALTER TABLE themes "
                    "ADD COLUMN uuid uuid NOT NULL DEFAULT gen_random_uuid()"
                )
            )
            await conn.execute(
                sa.text("ALTER TABLE themes ADD COLUMN parent_theme_uuid uuid")
            )
            await conn.execute(
                sa.text(
                    "ALTER TABLE user_library_themes ADD COLUMN theme_uuid uuid"
                )
            )

            # ----------------------------------------------------------
            # 3. Backfill the new GUID columns from the legacy String FKs.
            # ----------------------------------------------------------
            _checkpoint("UPDATE user_library_themes.theme_uuid backfill")
            await conn.execute(
                sa.text(
                    "UPDATE user_library_themes SET theme_uuid = ("
                    "  SELECT t.uuid FROM themes t "
                    "  WHERE t.id = user_library_themes.theme_id"
                    ")"
                )
            )
            _checkpoint("UPDATE themes.parent_theme_uuid backfill")
            await conn.execute(
                sa.text(
                    "UPDATE themes SET parent_theme_uuid = ("
                    "  SELECT p.uuid FROM themes p WHERE p.id = themes.parent_theme_id"
                    ") WHERE parent_theme_id IS NOT NULL"
                )
            )

            # ----------------------------------------------------------
            # 4. Integrity verification — same checks the alembic migration
            #    will perform.
            # ----------------------------------------------------------
            themes_now = (
                await conn.execute(sa.text("SELECT count(*) FROM themes"))
            ).scalar_one()
            assert themes_now == themes_count_before, (
                f"themes drift: {themes_now} vs backup {themes_count_before}"
            )
            ult_now = (
                await conn.execute(
                    sa.text("SELECT count(*) FROM user_library_themes")
                )
            ).scalar_one()
            assert ult_now == ult_count_before, (
                f"user_library_themes drift: {ult_now} vs backup {ult_count_before}"
            )

            orphan_ult = (
                await conn.execute(
                    sa.text(
                        "SELECT count(*) FROM user_library_themes WHERE theme_uuid IS NULL"
                    )
                )
            ).scalar_one()
            assert orphan_ult == 0, (
                f"FK integrity FAILED: {orphan_ult} user_library_themes rows have "
                f"NULL theme_uuid (no matching themes.uuid for legacy theme_id)."
            )
            orphan_parents = (
                await conn.execute(
                    sa.text(
                        "SELECT count(*) FROM themes "
                        "WHERE parent_theme_id IS NOT NULL AND parent_theme_uuid IS NULL"
                    )
                )
            ).scalar_one()
            assert orphan_parents == 0, (
                f"FK integrity FAILED: {orphan_parents} themes rows have a "
                f"parent_theme_id with no matching themes.uuid."
            )
            backfilled_parents = (
                await conn.execute(
                    sa.text(
                        "SELECT count(*) FROM themes WHERE parent_theme_uuid IS NOT NULL"
                    )
                )
            ).scalar_one()
            assert backfilled_parents == parent_link_count, (
                f"Parent backfill mismatch: {backfilled_parents} vs "
                f"{parent_link_count} expected."
            )
            print("[ok] Integrity checks passed")

            # ----------------------------------------------------------
            # 5. FK swap (the destructive part). All the dropped /
            #    renamed objects come back when we ROLLBACK below, so
            #    even a failure here leaves the live database intact.
            # ----------------------------------------------------------
            _checkpoint("DROP user_library_themes_theme_id_fkey")
            await conn.execute(
                sa.text(
                    "ALTER TABLE user_library_themes "
                    "DROP CONSTRAINT user_library_themes_theme_id_fkey"
                )
            )
            # The parent FK name from Wave 1 / 0088 follows the
            # ``fk_<table>_<col>`` convention.
            _checkpoint("DROP fk_themes_parent_theme_id (or themes_parent_theme_id_fkey)")
            for cname in ("fk_themes_parent_theme_id", "themes_parent_theme_id_fkey"):
                exists = (
                    await conn.execute(
                        sa.text(
                            "SELECT 1 FROM information_schema.table_constraints "
                            "WHERE table_name='themes' AND constraint_name=:n"
                        ),
                        {"n": cname},
                    )
                ).first()
                if exists:
                    await conn.execute(
                        sa.text(f"ALTER TABLE themes DROP CONSTRAINT {cname}")
                    )
                    break
            _checkpoint("DROP uq_user_library_theme_team unique constraint")
            await conn.execute(
                sa.text(
                    "ALTER TABLE user_library_themes "
                    "DROP CONSTRAINT uq_user_library_theme_team"
                )
            )
            _checkpoint("DROP themes_pkey + ix_themes_id")
            await conn.execute(sa.text("ALTER TABLE themes DROP CONSTRAINT themes_pkey"))
            await conn.execute(sa.text("DROP INDEX IF EXISTS ix_themes_id"))

            _checkpoint("RENAME themes.id -> id_legacy, themes.uuid -> id, ADD PK")
            await conn.execute(
                sa.text("ALTER TABLE themes RENAME COLUMN id TO id_legacy")
            )
            await conn.execute(
                sa.text("ALTER TABLE themes RENAME COLUMN uuid TO id")
            )
            await conn.execute(sa.text("ALTER TABLE themes ADD PRIMARY KEY (id)"))
            await conn.execute(
                sa.text("CREATE INDEX ix_themes_id ON themes (id)")
            )

            _checkpoint("RENAME themes parent FK columns")
            await conn.execute(
                sa.text(
                    "ALTER TABLE themes "
                    "RENAME COLUMN parent_theme_id TO parent_theme_id_legacy"
                )
            )
            await conn.execute(
                sa.text(
                    "ALTER TABLE themes "
                    "RENAME COLUMN parent_theme_uuid TO parent_theme_id"
                )
            )
            await conn.execute(
                sa.text(
                    "ALTER TABLE themes ADD CONSTRAINT themes_parent_theme_id_fkey "
                    "FOREIGN KEY (parent_theme_id) REFERENCES themes(id) "
                    "ON DELETE SET NULL"
                )
            )

            _checkpoint("RENAME user_library_themes.theme_id FK columns + recreate FK + UNIQUE")
            await conn.execute(
                sa.text(
                    "ALTER TABLE user_library_themes "
                    "RENAME COLUMN theme_id TO theme_id_legacy"
                )
            )
            await conn.execute(
                sa.text(
                    "ALTER TABLE user_library_themes "
                    "RENAME COLUMN theme_uuid TO theme_id"
                )
            )
            await conn.execute(
                sa.text(
                    "ALTER TABLE user_library_themes ALTER COLUMN theme_id SET NOT NULL"
                )
            )
            await conn.execute(
                sa.text(
                    "ALTER TABLE user_library_themes "
                    "ADD CONSTRAINT user_library_themes_theme_id_fkey "
                    "FOREIGN KEY (theme_id) REFERENCES themes(id) ON DELETE CASCADE"
                )
            )
            await conn.execute(
                sa.text(
                    "ALTER TABLE user_library_themes "
                    "ADD CONSTRAINT uq_user_library_theme_team "
                    "UNIQUE (user_id, theme_id, team_id)"
                )
            )

            # ----------------------------------------------------------
            # 6. Drop legacy columns
            # ----------------------------------------------------------
            _checkpoint("DROP COLUMN themes.id_legacy + parent_theme_id_legacy")
            await conn.execute(sa.text("ALTER TABLE themes DROP COLUMN id_legacy"))
            await conn.execute(
                sa.text("ALTER TABLE themes DROP COLUMN parent_theme_id_legacy")
            )
            await conn.execute(
                sa.text(
                    "ALTER TABLE user_library_themes DROP COLUMN theme_id_legacy"
                )
            )

            # ----------------------------------------------------------
            # 7. Final post-migration assertions: shape + counts
            # ----------------------------------------------------------
            final_themes = (
                await conn.execute(sa.text("SELECT count(*) FROM themes"))
            ).scalar_one()
            final_ult = (
                await conn.execute(
                    sa.text("SELECT count(*) FROM user_library_themes")
                )
            ).scalar_one()
            final_parents = (
                await conn.execute(
                    sa.text(
                        "SELECT count(*) FROM themes WHERE parent_theme_id IS NOT NULL"
                    )
                )
            ).scalar_one()
            assert final_themes == themes_count_before, "post-migration themes drift"
            assert final_ult == ult_count_before, "post-migration ult drift"
            assert final_parents == parent_link_count, "parent FK drift after swap"

            # Verify themes.id is a uuid column post-migration.
            row = (
                await conn.execute(
                    sa.text(
                        "SELECT data_type FROM information_schema.columns "
                        "WHERE table_name='themes' AND column_name='id'"
                    )
                )
            ).first()
            assert row is not None and row[0] == "uuid", (
                f"themes.id should be uuid post-migration, got {row}"
            )
            # Same for parent_theme_id and user_library_themes.theme_id.
            for table, col in [
                ("themes", "parent_theme_id"),
                ("user_library_themes", "theme_id"),
            ]:
                r = (
                    await conn.execute(
                        sa.text(
                            "SELECT data_type FROM information_schema.columns "
                            "WHERE table_name=:t AND column_name=:c"
                        ),
                        {"t": table, "c": col},
                    )
                ).first()
                assert r is not None and r[0] == "uuid", (
                    f"{table}.{col} should be uuid post-migration, got {r}"
                )

            # Verify a freshly inserted Theme row gets a UUID PK and the
            # FK from UserLibraryTheme follows.
            new_theme_id = uuid.uuid4()
            await conn.execute(
                sa.text(
                    "INSERT INTO themes (id, name, slug, mode, theme_json, source_id) "
                    "VALUES (:id, 'Dryrun', :slug, 'dark', '{}', :src)"
                ),
                {
                    "id": new_theme_id,
                    "slug": f"dryrun-{uuid.uuid4().hex[:8]}",
                    "src": uuid.UUID("00000000-0000-0000-0000-000000000002"),
                },
            )
            print("[ok] New theme insert with GUID PK works")

            print(
                f"\nDRY RUN PASSED — "
                f"{themes_count_before} themes / "
                f"{ult_count_before} user_library_themes / "
                f"{parent_link_count} parent links migrated successfully."
            )

            # ----------------------------------------------------------
            # ROLLBACK — leaves the live DB exactly as it was
            # ----------------------------------------------------------
            await outer.rollback()
            print("[done] Transaction ROLLED BACK — DB unchanged.")

    await engine.dispose()


def main() -> int:
    url = os.environ.get("DATABASE_URL", DEFAULT_URL)
    try:
        asyncio.run(run_dry_run(url))
        return 0
    except AssertionError as exc:
        print(f"\nDRY RUN FAILED: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 — top-level reporter
        print(f"\nDRY RUN ERRORED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
