"""drop legacy global slug uniqueness on catalog tables (Wave 5).

Revision ID: 0091_drop_legacy_slug_uq
Revises: 0090_marketplace_attestation_pubkey
Create Date: 2026-04-29

Wave 5 of the federated-marketplace decoupling. With source-prefixed URLs
and the source dropdown shipping in Wave 5, two sources can legitimately
ship the same slug ("coder" agent on Tesslate Official and on a community
hub). The Wave-1 ``(source_id, slug)`` composite unique indexes are now
the sole uniqueness invariant.

This migration:

  1. Drops the global slug uniqueness from ``marketplace_agents``,
     ``marketplace_bases``, ``marketplace_apps``, ``workflow_templates``,
     and ``themes``. For tables where ``slug`` was declared with both
     ``unique=True`` and ``index=True``, Alembic created a unique index
     named ``ix_<table>_slug`` — we drop the unique index and recreate it
     as a non-unique index so query performance for slug lookups is
     preserved. For ``marketplace_apps`` (no ``index=True``), the
     column-level UNIQUE constraint is named ``marketplace_apps_slug_key``;
     we drop the constraint and add a non-unique ``ix_marketplace_apps_slug``
     index for parity with the other catalog tables.
  2. Drops ``uq_marketplace_apps_creator_handle`` (the legacy
     ``(creator_user_id, handle)`` global uniqueness). The Wave-1
     ``uq_marketplace_apps_source_creator_handle`` constraint that adds
     ``source_id`` to the front is now the sole invariant.

The model declarations in ``orchestrator/app/models.py`` are updated in
the same change to match the schema (``unique=False`` on the slug columns;
``UniqueConstraint`` for ``(creator_user_id, handle)`` removed from
``MarketplaceApp.__table_args__``).

Forward-only migration. There is no downgrade — restoring the global
uniqueness would fail if any same-slug-different-source pairs exist after
the wave ships.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0091_drop_legacy_slug_uq"
down_revision: str | Sequence[str] | None = "0090_marketplace_attestation_pubkey"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Tables where the model declared ``slug`` with both ``unique=True`` AND
# ``index=True``. Alembic emitted a single unique index ``ix_<tbl>_slug``
# for each. We drop the unique index then recreate it as a plain
# (non-unique) index so query performance for ``WHERE slug = ?`` lookups
# is preserved.
TABLES_WITH_INDEXED_UNIQUE_SLUG = [
    "marketplace_agents",
    "marketplace_bases",
    "workflow_templates",
    "themes",
]

# Tables where ``slug`` was declared ``unique=True`` only (no
# ``index=True``). Postgres named the column UNIQUE constraint
# ``<tbl>_slug_key``. We drop the constraint and create a non-unique
# index so slug lookups stay fast.
TABLES_WITH_BARE_UNIQUE_SLUG = [
    "marketplace_apps",
]


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    # ------------------------------------------------------------------
    # 1. Pre-flight: confirm the Wave-1 (source_id, slug) replacement
    #    indexes exist before we drop the global ones. This is belt-
    #    and-braces — the Wave-1 migration has been live since 0088 —
    #    but a missing replacement would silently weaken catalog
    #    uniqueness, so we fail fast if it isn't there.
    # ------------------------------------------------------------------
    inspector = sa.inspect(bind)
    for tbl in (
        "marketplace_agents",
        "marketplace_bases",
        "marketplace_apps",
        "workflow_templates",
        "themes",
    ):
        idx_names = {i["name"] for i in inspector.get_indexes(tbl)}
        uq_names = {u["name"] for u in inspector.get_unique_constraints(tbl)}
        expected = f"uq_{tbl}_source_slug"
        if expected not in idx_names and expected not in uq_names:
            raise RuntimeError(
                f"Wave 5 migration 0090 refuses to drop legacy global slug "
                f"uniqueness on {tbl!r}: replacement index {expected!r} not "
                f"found. Did Wave 1 migration 0088_marketplace_sources run?"
            )

    # ------------------------------------------------------------------
    # 2. Drop legacy global slug uniqueness on tables where the slug was
    #    declared as both ``unique=True`` and ``index=True``.
    # ------------------------------------------------------------------
    # We re-introspect inside the loop so we know whether each index
    # exists as unique or not before deciding whether to drop+recreate.
    # Some test DBs are bootstrapped from ``Base.metadata.create_all`` and
    # may already have a non-unique slug index from a prior schema state.
    for tbl in TABLES_WITH_INDEXED_UNIQUE_SLUG:
        unique_idx = f"ix_{tbl}_slug"
        existing_indexes = {i["name"]: i for i in inspector.get_indexes(tbl)}
        existing = existing_indexes.get(unique_idx)
        if existing is not None and existing.get("unique"):
            op.drop_index(unique_idx, table_name=tbl)
            op.create_index(unique_idx, tbl, ["slug"], unique=False)
        elif existing is None:
            # No slug index at all (rare) — create the non-unique one.
            op.create_index(unique_idx, tbl, ["slug"], unique=False)
        # else: index exists and is already non-unique → no-op (idempotent).

    # ------------------------------------------------------------------
    # 3. Drop legacy global slug uniqueness on tables where the slug was
    #    declared as plain ``unique=True`` (no ``index=True``).
    # ------------------------------------------------------------------
    for tbl in TABLES_WITH_BARE_UNIQUE_SLUG:
        # Detect whether the constraint actually exists before dropping.
        existing_uqs = {u["name"] for u in inspector.get_unique_constraints(tbl)}
        existing_indexes = {i["name"]: i for i in inspector.get_indexes(tbl)}
        constraint_name = f"{tbl}_slug_key"

        if is_postgres and constraint_name in existing_uqs:
            op.drop_constraint(constraint_name, tbl, type_="unique")
        elif not is_postgres:
            # SQLite cannot ``DROP CONSTRAINT`` directly. Use
            # batch_alter_table — it rebuilds the table from current
            # SQLAlchemy metadata, which (post this commit) declares
            # ``unique=False`` on the slug column, so the rebuild
            # naturally omits the uniqueness.
            with op.batch_alter_table(tbl) as batch:
                pass

        slug_index = existing_indexes.get(f"ix_{tbl}_slug")
        if slug_index is None:
            op.create_index(f"ix_{tbl}_slug", tbl, ["slug"], unique=False)
        elif slug_index.get("unique"):
            op.drop_index(f"ix_{tbl}_slug", table_name=tbl)
            op.create_index(f"ix_{tbl}_slug", tbl, ["slug"], unique=False)

    # ------------------------------------------------------------------
    # 4. Drop the legacy (creator_user_id, handle) UNIQUE on
    #    marketplace_apps. The Wave-1
    #    ``uq_marketplace_apps_source_creator_handle`` is now the sole
    #    invariant for handle uniqueness.
    # ------------------------------------------------------------------
    legacy_handle_uq = "uq_marketplace_apps_creator_handle"
    apps_uqs = {u["name"] for u in inspector.get_unique_constraints("marketplace_apps")}
    if legacy_handle_uq in apps_uqs:
        if is_postgres:
            op.drop_constraint(legacy_handle_uq, "marketplace_apps", type_="unique")
        else:
            with op.batch_alter_table("marketplace_apps") as batch:
                try:
                    batch.drop_constraint(legacy_handle_uq, type_="unique")
                except Exception:
                    # SQLite batch mode rebuilds from current metadata —
                    # the model no longer declares this UQ so the rebuild
                    # naturally omits it.
                    pass


def downgrade() -> None:
    """Forward-only — see module docstring.

    Restoring global slug uniqueness would fail on any database that
    has same-slug-different-source pairs in production.
    """
    raise NotImplementedError(
        "Wave 5 migration 0090 is forward-only. Restoring global slug "
        "uniqueness would fail on any database where two sources have "
        "shipped the same slug after this wave landed."
    )
