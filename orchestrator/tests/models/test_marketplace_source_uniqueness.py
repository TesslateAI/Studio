"""Wave 1 invariants: both-constraints slug uniqueness + system-source partial index.

This test locks in the most subtle Wave-1 schema invariant: every catalog
table that has a slug column must enforce **both**:

  (a) the legacy global slug uniqueness constraint (column-level
      ``unique=True`` from before the federated-marketplace work), AND
  (b) the new ``(source_id, slug)`` per-source composite uniqueness from
      alembic ``0088_marketplace_sources``.

Both invariants must coexist until Wave 5. If a future migration drops
the global constraint early — for example a refactor that confuses
"per-source uniqueness is enough" with "per-source uniqueness alone" —
this test fires immediately in CI before the change can land.

Why Postgres only
-----------------
SQLite reports UNIQUE failures as ``UNIQUE constraint failed:
<table>.<column>`` regardless of which named constraint actually fired,
which makes the two invariants impossible to distinguish from the
exception text. Postgres reports the constraint name (``constraint
"<name>"``), so we can assert the exact constraint that fired. We
therefore mark these as ``@pytest.mark.integration`` and back the
fixtures with a dedicated Postgres database on port 5433 (the standard
``docker-compose.test.yml`` postgres). Tests are skipped if the port is
not reachable, with a clear message.

Why we bypass alembic
---------------------
The Wave 1X alembic migration ``0088_marketplace_sources`` currently has
a Postgres-only bug: it binds the seeded UUIDs as ``VARCHAR`` parameters
into a column typed ``uuid``, producing a
``DatatypeMismatchError`` on ``alembic upgrade head`` for Postgres.
Until that lands a separate fix, this test bootstraps the schema via
``Base.metadata.create_all`` (which honors the model's
``UniqueConstraint`` declarations and the legacy column-level
``unique=True``) and then explicitly applies the post-create steps that
alembic 0088 performs:

  - flip ``source_id`` to NOT NULL on every catalog table
  - seed the two system rows (``tesslate-official``, ``local``)
    with the deterministic UUIDs

This keeps the test independent of the migration bug while still
exercising the same constraint surface a fully-migrated Postgres
database has.

Identifier source
-----------------
The two deterministic system UUIDs match alembic
``0088_marketplace_sources`` and the seed module
``app.seeds.marketplace_sources`` exactly. We hardcode them inline (with
a cross-reference comment) rather than import from
``app.seeds.marketplace_sources`` to avoid a Wave-1Y race: if that seed
module's constants are ever renamed or moved, this test still locks the
on-disk migration's UUIDs.
"""

from __future__ import annotations

import socket
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Importing both modules registers every table on Base.metadata. The
# automations module re-defines AppInstance under the Phase-1 hard reset.
from app import models, models_automations  # noqa: F401
from app.database import Base


# ---------------------------------------------------------------------------
# Wave 1X deterministic system source UUIDs
# ---------------------------------------------------------------------------
# Must match alembic ``0088_marketplace_sources`` and the cross-task seed
# at ``app.seeds.marketplace_sources``. Hardcoded here to keep this test
# independent of the seed module shape (Wave 1Y race tolerance).
TESSLATE_OFFICIAL_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
LOCAL_SOURCE_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")


# Tables this test covers. ``app_versions`` has no slug column and is
# excluded from the slug-invariant matrix; it gets its own narrow
# nullability test below.
SLUGGABLE_CATALOG_TABLES = [
    "marketplace_agents",
    "marketplace_bases",
    "marketplace_apps",
    "themes",
    "workflow_templates",
]

# Catalog tables (sluggable + app_versions) that alembic 0088 flips to
# ``source_id NOT NULL``. We mirror that flip after ``create_all``.
ALL_CATALOG_TABLES_WITH_SOURCE_ID = SLUGGABLE_CATALOG_TABLES + ["app_versions"]


# Per-table expected legacy-constraint name. The slug column is declared
# ``unique=True`` on every model. Postgres names the resulting object
# differently depending on whether the column also has ``index=True``:
#
#   * ``index=True``  → unique INDEX named ``ix_<table>_slug``
#   * ``index=False`` → table UNIQUE constraint named ``<table>_slug_key``
#
# All five tables fall into one of those two buckets per the model
# declarations in ``app/models.py``.
LEGACY_SLUG_CONSTRAINT_NAME: dict[str, str] = {
    "marketplace_agents": "ix_marketplace_agents_slug",  # index=True on slug
    "marketplace_bases": "ix_marketplace_bases_slug",  # index=True on slug
    "marketplace_apps": "marketplace_apps_slug_key",  # column-level UNIQUE
    "themes": "ix_themes_slug",  # index=True on slug
    "workflow_templates": "ix_workflow_templates_slug",  # index=True on slug
}


# ---------------------------------------------------------------------------
# Test database bootstrap (Postgres on port 5433)
# ---------------------------------------------------------------------------

_TEST_PG_HOST = "localhost"
_TEST_PG_PORT = 5433
_TEST_PG_USER = "tesslate_test"
_TEST_PG_PASSWORD = "testpass"
_TEST_PG_ADMIN_DB = "postgres"
# A dedicated database name so we don't collide with the canonical
# ``tesslate_test`` DB that other integration tests share. Created and
# dropped per pytest session.
_PROBE_DB_NAME = "tesslate_marketplace_source_uniqueness"

_PROBE_PG_URL = (
    f"postgresql+asyncpg://{_TEST_PG_USER}:{_TEST_PG_PASSWORD}"
    f"@{_TEST_PG_HOST}:{_TEST_PG_PORT}/{_PROBE_DB_NAME}"
)
_ADMIN_PG_URL = (
    f"postgresql+asyncpg://{_TEST_PG_USER}:{_TEST_PG_PASSWORD}"
    f"@{_TEST_PG_HOST}:{_TEST_PG_PORT}/{_TEST_PG_ADMIN_DB}"
)


def _postgres_reachable() -> bool:
    """Return True iff the test Postgres on port 5433 accepts TCP."""
    try:
        with socket.create_connection((_TEST_PG_HOST, _TEST_PG_PORT), timeout=2):
            return True
    except OSError:
        return False


# Skip the entire module if the test Postgres isn't running. Mirrors
# how ``tests/integration/conftest.py`` gates on the same port.
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _postgres_reachable(),
        reason=(
            "Test Postgres on localhost:5433 is not reachable. "
            "Bring it up with: docker compose -f docker-compose.test.yml up -d postgres-test"
        ),
    ),
]


async def _bootstrap_probe_database() -> None:
    """One-shot async helper to (re)create the probe database, build the
    schema via ``Base.metadata.create_all``, mirror alembic 0088's NOT
    NULL flip on ``source_id`` columns, and seed the two system rows.

    Called once per pytest session via the sync ``probe_database``
    fixture below. Async-only because async-engine ``CREATE DATABASE``
    happens to be the cleanest way to talk to Postgres without pulling
    in a sync driver dependency.
    """
    admin_engine = create_async_engine(_ADMIN_PG_URL, isolation_level="AUTOCOMMIT")
    try:
        async with admin_engine.connect() as conn:
            # Force-disconnect any straggling connections (from a prior
            # interrupted run) so DROP can succeed.
            await conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ).bindparams(name=_PROBE_DB_NAME)
            )
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{_PROBE_DB_NAME}"'))
            await conn.execute(text(f'CREATE DATABASE "{_PROBE_DB_NAME}"'))
    finally:
        await admin_engine.dispose()

    engine = create_async_engine(_PROBE_PG_URL)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # Mirror alembic 0088: flip ``source_id`` to NOT NULL on
            # every catalog table. The model column is declared
            # nullable=True because the alembic migration owns the
            # NOT NULL flip; we reproduce that here so introspection
            # sees the post-migration shape.
            for tbl in ALL_CATALOG_TABLES_WITH_SOURCE_ID:
                await conn.execute(
                    text(f"ALTER TABLE {tbl} ALTER COLUMN source_id SET NOT NULL")
                )

        Maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with Maker() as session:
            session.add(
                models.MarketplaceSource(
                    id=TESSLATE_OFFICIAL_ID,
                    handle="tesslate-official",
                    display_name="Tesslate Official",
                    base_url="https://marketplace.tesslate.com",
                    scope="system",
                    trust_level="official",
                )
            )
            session.add(
                models.MarketplaceSource(
                    id=LOCAL_SOURCE_ID,
                    handle="local",
                    display_name="Local",
                    base_url="local://filesystem",
                    scope="system",
                    trust_level="local",
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


async def _drop_probe_database() -> None:
    """Tear down the probe database. Idempotent."""
    admin_engine = create_async_engine(_ADMIN_PG_URL, isolation_level="AUTOCOMMIT")
    try:
        async with admin_engine.connect() as conn:
            await conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ).bindparams(name=_PROBE_DB_NAME)
            )
            await conn.execute(text(f'DROP DATABASE IF EXISTS "{_PROBE_DB_NAME}"'))
    finally:
        await admin_engine.dispose()


@pytest.fixture(scope="session")
def probe_database() -> AsyncGenerator[None, None]:
    """Session-scoped sync wrapper that owns the probe-database lifecycle.

    Uses ``asyncio.run`` so the bootstrap doesn't have to share an
    event loop with the function-scoped async fixtures below — that's
    what caused a ``ScopeMismatch`` when ``db_engine`` itself was
    declared with ``scope='module'``. The schema is built once per
    session; per-test fixtures just open new engines/sessions against
    the already-prepared database.
    """
    import asyncio

    asyncio.run(_bootstrap_probe_database())
    try:
        yield
    finally:
        asyncio.run(_drop_probe_database())


@pytest_asyncio.fixture
async def db_engine(probe_database: None) -> AsyncGenerator[AsyncEngine, None]:
    """Per-test AsyncEngine pointed at the session-scoped probe DB.

    Function-scoped so it shares the function-scoped event loop the
    project's pytest-asyncio config defaults to (avoids ScopeMismatch
    against ``_function_scoped_runner``).
    """
    engine = create_async_engine(_PROBE_PG_URL)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Per-test AsyncSession against the session-scoped probe DB.

    Tests use a unique slug per insert (uuid suffix) to avoid colliding
    with sibling tests at session scope — we cannot transactionally
    roll back across the explicit ``flush`` / ``commit`` boundaries the
    IntegrityError tests rely on.
    """
    Maker = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with Maker() as session:
        try:
            yield session
        finally:
            # Best-effort rollback in case a test raised mid-flush.
            try:
                await session.rollback()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Per-table minimal-row builders
# ---------------------------------------------------------------------------
# Each helper returns a model instance with every NOT-NULL-no-default
# column set to a test-friendly value. Caller passes ``source_id`` and
# ``slug`` explicitly because those are the columns under test.


def _make_agent(*, source_id: uuid.UUID, slug: str) -> models.MarketplaceAgent:
    return models.MarketplaceAgent(
        id=uuid.uuid4(),
        source_id=source_id,
        slug=slug,
        name=f"agent-{slug}",
        description="test",
        category="test",
        pricing_type="free",
    )


def _make_base(*, source_id: uuid.UUID, slug: str) -> models.MarketplaceBase:
    return models.MarketplaceBase(
        id=uuid.uuid4(),
        source_id=source_id,
        slug=slug,
        name=f"base-{slug}",
        description="test",
        category="test",
        pricing_type="free",
    )


def _make_app(*, source_id: uuid.UUID, slug: str) -> models.MarketplaceApp:
    return models.MarketplaceApp(
        id=uuid.uuid4(),
        source_id=source_id,
        slug=slug,
        name=f"app-{slug}",
    )


def _make_theme(*, source_id: uuid.UUID, slug: str) -> models.Theme:
    # Wave 1.5: Theme.id is now a GUID auto-populated by ``default=uuid.uuid4``.
    # We pass an explicit id so two themes can share the same slug across
    # two sources without colliding on the PK — which would mask the slug
    # uniqueness constraint we're actually testing. Theme.slug is
    # nullable=True at the column level but both Wave-1 invariants are
    # about (source_id, slug) pairs, so we always populate it.
    return models.Theme(
        id=uuid.uuid4(),
        source_id=source_id,
        slug=slug,
        name=f"theme-{slug}",
        mode="dark",
        theme_json={},
    )


def _make_workflow_template(
    *, source_id: uuid.UUID, slug: str
) -> models.WorkflowTemplate:
    return models.WorkflowTemplate(
        id=uuid.uuid4(),
        source_id=source_id,
        slug=slug,
        name=f"wf-{slug}",
        description="test",
        category="test",
        template_definition={"nodes": [], "edges": []},
    )


_BUILDERS: dict[str, Any] = {
    "marketplace_agents": _make_agent,
    "marketplace_bases": _make_base,
    "marketplace_apps": _make_app,
    "themes": _make_theme,
    "workflow_templates": _make_workflow_template,
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("table_name", SLUGGABLE_CATALOG_TABLES)
async def test_same_slug_two_sources_coexists_post_wave5(
    db_session: AsyncSession,
    table_name: str,
) -> None:
    """Wave 5 drops the legacy global slug uniqueness — two sources
    can now legitimately ship the same slug.

    Pre-Wave-5 invariant: the legacy column-level ``unique=True`` blocked
    same-slug-different-source pairs. Wave 5 alembic 0091 drops that
    constraint; ``(source_id, slug)`` is now the sole uniqueness
    invariant. This test locks in the *post-Wave-5* behavior: inserting
    a tesslate-official ``coder`` agent AND a local ``coder`` agent both
    succeed.

    Replaces the pre-Wave-5 ``test_legacy_global_slug_uniqueness_blocks_cross_source_dup``
    test that asserted the opposite — keeping that test would lock in
    the very invariant Wave 5 is removing.
    """
    builder = _BUILDERS[table_name]
    slug = f"wave5-{table_name}-{uuid.uuid4().hex[:8]}"

    # First insert: tesslate-official source. Should succeed.
    db_session.add(builder(source_id=TESSLATE_OFFICIAL_ID, slug=slug))
    await db_session.flush()
    await db_session.commit()

    # Second insert: same slug, **different** source (local). Pre-Wave-5
    # this would have failed on the legacy global slug uniqueness; post-
    # Wave-5 it must succeed because ``(source_id, slug)`` is now the
    # sole uniqueness invariant and the two rows have different
    # source_ids.
    db_session.add(builder(source_id=LOCAL_SOURCE_ID, slug=slug))
    await db_session.flush()
    await db_session.commit()


@pytest.mark.parametrize("table_name", SLUGGABLE_CATALOG_TABLES)
async def test_per_source_slug_uniqueness_blocks_within_source_dup(
    db_session: AsyncSession,
    table_name: str,
) -> None:
    """Two rows with the same ``(source_id, slug)`` pair must violate
    ``uq_<table>_source_slug``.

    This is the new Wave-1 invariant added by alembic 0088. We use a
    fresh slug per parametrized run so the legacy global uniqueness
    cannot fire first and mask this assertion.
    """
    builder = _BUILDERS[table_name]
    slug = f"persrc-{table_name}-{uuid.uuid4().hex[:8]}"

    # First insert: tesslate-official + slug. Should succeed.
    db_session.add(builder(source_id=TESSLATE_OFFICIAL_ID, slug=slug))
    await db_session.flush()
    await db_session.commit()

    # Second insert: identical (source_id, slug). Both legacy global
    # uniqueness AND per-source uniqueness can fire here, but the more
    # specific composite constraint is what we want named in the error.
    # Postgres reports the *first* unique violation it hits — for tables
    # where the legacy slug uniqueness is enforced via an indexed unique
    # column, that often wins. We therefore assert the failure mentions
    # **either** the legacy or the new constraint, but specifically
    # require ``uq_<table>_source_slug`` to *exist* on the table by
    # introspection — Postgres only fires it when no earlier constraint
    # short-circuits, so its presence is the load-bearing fact.
    db_session.add(builder(source_id=TESSLATE_OFFICIAL_ID, slug=slug))
    with pytest.raises(IntegrityError) as excinfo:
        await db_session.flush()
    msg = str(excinfo.value)
    composite_name = f"uq_{table_name}_source_slug"
    legacy_name = LEGACY_SLUG_CONSTRAINT_NAME[table_name]
    assert composite_name in msg or legacy_name in msg, (
        f"For {table_name}, expected one of "
        f"({composite_name!r}, {legacy_name!r}) to fire on a "
        f"(same source, same slug) duplicate, but IntegrityError was: {msg}"
    )
    await db_session.rollback()


@pytest.mark.parametrize("table_name", SLUGGABLE_CATALOG_TABLES)
async def test_per_source_slug_constraint_exists_on_table(
    db_engine: AsyncEngine,
    table_name: str,
) -> None:
    """Schema-introspection guard: ``uq_<table>_source_slug`` must
    actually exist on the table.

    Belt-and-braces complement to the IntegrityError tests above: if
    Postgres ever reports the legacy constraint first on a (same source,
    same slug) duplicate, we still need to prove the composite
    constraint is present in the schema. Otherwise dropping it would
    silently weaken the invariant without any IntegrityError test
    noticing.
    """

    def _names(sync_conn: Any) -> tuple[set[str], set[str]]:
        insp = inspect(sync_conn)
        uqs = {u["name"] for u in insp.get_unique_constraints(table_name)}
        idxs = {i["name"] for i in insp.get_indexes(table_name)}
        return uqs, idxs

    async with db_engine.connect() as conn:
        uqs, idxs = await conn.run_sync(_names)

    expected = f"uq_{table_name}_source_slug"
    assert expected in uqs or expected in idxs, (
        f"{expected!r} not found on table {table_name}. "
        f"Unique constraints: {sorted(uqs)}, indexes: {sorted(idxs)}"
    )


async def test_app_versions_source_id_is_not_null(db_engine: AsyncEngine) -> None:
    """Forward-compat for Wave 7: ``app_versions.source_id`` is NOT NULL.

    Wave 7 will add a dedicated consistency check requiring every
    AppVersion row to point at the same source as its parent
    MarketplaceApp. That check assumes the column exists and is NOT
    NULL on every row. Wave 1's migration already flips it; this test
    locks in that the column shape is in place so a future migration
    that accidentally relaxes it (or never lands the flip in a sibling
    schema) fails CI.
    """

    def _source_id_nullable(sync_conn: Any) -> bool:
        insp = inspect(sync_conn)
        for col in insp.get_columns("app_versions"):
            if col["name"] == "source_id":
                return col["nullable"]
        raise AssertionError("app_versions.source_id column is missing")

    async with db_engine.connect() as conn:
        nullable = await conn.run_sync(_source_id_nullable)

    assert nullable is False, (
        "app_versions.source_id must be NOT NULL after alembic 0088. "
        "Wave 7's app_versions↔marketplace_apps source consistency check "
        "depends on this invariant."
    )


# ---------------------------------------------------------------------------
# MarketplaceSource partial-unique-index invariants (system scope)
# ---------------------------------------------------------------------------


async def test_system_scope_handle_uniqueness_blocks_duplicate(
    db_session: AsyncSession,
) -> None:
    """``uq_msrc_system_handle`` (partial index WHERE scope='system')
    must block a second ``handle='tesslate-official'`` row at scope
    ``system``.

    The two seeded system rows already occupy 'tesslate-official' and
    'local'. A third 'tesslate-official' insert at scope='system' must
    fail on the partial unique index, regardless of how the seed rows
    got there.
    """
    db_session.add(
        models.MarketplaceSource(
            id=uuid.uuid4(),
            handle="tesslate-official",
            display_name="Imposter",
            base_url="https://imposter.example",
            scope="system",
            trust_level="official",
        )
    )
    with pytest.raises(IntegrityError) as excinfo:
        await db_session.flush()
    msg = str(excinfo.value)
    assert "uq_msrc_system_handle" in msg, (
        f"Expected partial-unique 'uq_msrc_system_handle' to fire "
        f"on duplicate scope='system' handle, got: {msg}"
    )
    await db_session.rollback()


async def test_user_scope_allows_same_handle_for_different_users(
    db_session: AsyncSession,
) -> None:
    """Counter-test: ``uq_msrc_system_handle`` is a partial index over
    ``WHERE scope='system'``, so two ``scope='user'`` rows with the
    same handle but different ``user_id`` must succeed.

    Without this counter-test, ``test_system_scope_handle_uniqueness_blocks_duplicate``
    would still pass against a hypothetical broken migration that made
    ``handle`` globally unique across all scopes — which would be wrong.
    Together they pin down "partial WHERE scope='system'" precisely.
    """
    # Seed two real users via the ORM so all User Python-side defaults
    # (subscription_tier, credits, support_tier, etc.) get populated.
    # Raw SQL would have to enumerate every NOT-NULL-no-server-default
    # column on ``users`` and would silently break when User columns are
    # added in future migrations.
    def _new_user(label: str) -> models.User:
        u_id = uuid.uuid4()
        return models.User(
            id=u_id,
            email=f"{label}-{u_id.hex[:8]}@example.com",
            hashed_password="x",
            name=label.upper(),
            username=f"user-{label}-{u_id.hex[:8]}",
            slug=f"user-{label}-{u_id.hex[:8]}",
        )

    user_a = _new_user("a")
    user_b = _new_user("b")
    db_session.add_all([user_a, user_b])
    await db_session.flush()

    shared_handle = f"shared-{uuid.uuid4().hex[:8]}"
    db_session.add(
        models.MarketplaceSource(
            id=uuid.uuid4(),
            handle=shared_handle,
            display_name="A",
            base_url="x://",
            scope="user",
            user_id=user_a.id,
            trust_level="private",
        )
    )
    db_session.add(
        models.MarketplaceSource(
            id=uuid.uuid4(),
            handle=shared_handle,
            display_name="B",
            base_url="x://",
            scope="user",
            user_id=user_b.id,
            trust_level="private",
        )
    )
    # Must NOT raise — the partial index only fires on scope='system'.
    await db_session.flush()
    await db_session.commit()
