"""Wave 1.5 integration: Theme.id String → GUID end-to-end.

Boots a fresh Postgres database (separate name from the shared
``tesslate_test`` integration DB), runs ``alembic upgrade head`` so
0089_theme_id_uuid is exercised against a clean Wave-0 → Wave-1 → Wave-1.5
chain, and asserts:

  - ``themes.id``, ``themes.parent_theme_id``, and
    ``user_library_themes.theme_id`` are now ``uuid`` columns
  - The ``themes_backup_<date>`` and ``user_library_themes_backup_<date>``
    tables exist (90-day retention per the plan)
  - A new Theme row gets a GUID PK from ``default=uuid.uuid4`` on the
    model
  - UserLibraryTheme.theme_id FK works against the new GUID column
  - Theme.parent_theme_id self-FK works
  - The legacy theme-detail redirect returns 301 with the
    Wave-5-stable URL shape

Why the dedicated DB
--------------------
Sharing ``tesslate_test`` with the rest of the integration suite would
mean we can't observe the migration from a clean baseline — by the time
this test runs, alembic 0089 has already been applied to that DB by some
other test's session-scoped ``setup_database`` fixture, so the
``themes_backup_*`` tables either pre-exist (silent pass) or never
existed (silent fail). A purpose-built DB lets the test prove the
``alembic upgrade`` actually performed the swap.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


# Ensure orchestrator is importable.
ORCHESTRATOR_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ORCHESTRATOR_DIR))

from app import models, models_automations  # noqa: E402,F401 — register tables
from app.types.guid import GUID  # noqa: E402


# ---------------------------------------------------------------------------
# Test database (independent of the shared ``tesslate_test`` so the alembic
# upgrade can run from a clean state).
# ---------------------------------------------------------------------------

_TEST_PG_HOST = "localhost"
_TEST_PG_PORT = 5433
_TEST_PG_USER = "tesslate_test"
_TEST_PG_PASSWORD = "testpass"
_TEST_PG_ADMIN_DB = "postgres"
_PROBE_DB_NAME = "tesslate_theme_uuid_migration"

_PROBE_PG_URL = (
    f"postgresql+asyncpg://{_TEST_PG_USER}:{_TEST_PG_PASSWORD}"
    f"@{_TEST_PG_HOST}:{_TEST_PG_PORT}/{_PROBE_DB_NAME}"
)
_ADMIN_PG_URL = (
    f"postgresql+asyncpg://{_TEST_PG_USER}:{_TEST_PG_PASSWORD}"
    f"@{_TEST_PG_HOST}:{_TEST_PG_PORT}/{_TEST_PG_ADMIN_DB}"
)


def _postgres_reachable() -> bool:
    try:
        with socket.create_connection((_TEST_PG_HOST, _TEST_PG_PORT), timeout=2):
            return True
    except OSError:
        return False


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


async def _bootstrap_probe_database_then_alembic() -> None:
    """Drop+recreate the probe DB, then run ``alembic upgrade head`` to
    exercise the full Wave 0 → Wave 1 → Wave 1.5 migration chain on a
    clean baseline.
    """
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
            await conn.execute(text(f'CREATE DATABASE "{_PROBE_DB_NAME}"'))
    finally:
        await admin_engine.dispose()

    # Run alembic upgrade head against the probe DB. Invoke via the
    # current Python interpreter's ``-m alembic`` so we don't rely on the
    # ``alembic`` script being on $PATH (it isn't when pytest is run from
    # a venv-isolated subprocess environment).
    sync_url = _PROBE_PG_URL  # alembic env.py uses async_engine_from_config
    import os as _os

    env = {
        "DATABASE_URL": sync_url,
        # Required-but-irrelevant settings for app.config.Settings;
        # alembic env.py imports the settings object even though it only
        # uses database_url.
        "SECRET_KEY": "x" * 32,
        "INTERNAL_API_SECRET": "y" * 32,
        # Carry through PATH + the venv pythonpath so alembic can find
        # its dependencies + the `app` package.
        "PATH": _os.environ.get("PATH", ""),
        "PYTHONPATH": str(ORCHESTRATOR_DIR),
        "VIRTUAL_ENV": _os.environ.get("VIRTUAL_ENV", ""),
    }
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ORCHESTRATOR_DIR,
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "alembic upgrade head failed for theme-uuid migration test:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


async def _drop_probe_database() -> None:
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


@pytest.fixture(scope="module")
def probe_database() -> Any:
    import asyncio

    asyncio.run(_bootstrap_probe_database_then_alembic())
    try:
        yield
    finally:
        asyncio.run(_drop_probe_database())


@pytest_asyncio.fixture
async def db_engine(probe_database: None) -> AsyncGenerator[AsyncEngine, None]:
    engine = create_async_engine(_PROBE_PG_URL)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    Maker = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with Maker() as session:
        try:
            yield session
        finally:
            try:
                await session.rollback()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Schema-shape assertions
# ---------------------------------------------------------------------------


def _column_type(sync_conn: Any, table: str, col: str) -> str | None:
    insp = inspect(sync_conn)
    for c in insp.get_columns(table):
        if c["name"] == col:
            t = c["type"]
            # Postgres reports the type as a SQLAlchemy ``UUID`` instance;
            # ``str(UUID())`` yields ``"UUID"``. Lower-case for stability.
            return str(t).lower()
    return None


async def test_themes_id_is_now_uuid(db_engine: AsyncEngine) -> None:
    async with db_engine.connect() as conn:
        themes_id_type = await conn.run_sync(_column_type, "themes", "id")
        parent_id_type = await conn.run_sync(_column_type, "themes", "parent_theme_id")
        ult_theme_id_type = await conn.run_sync(
            _column_type, "user_library_themes", "theme_id"
        )

    assert themes_id_type == "uuid", (
        f"themes.id should be UUID after Wave 1.5, got {themes_id_type!r}"
    )
    assert parent_id_type == "uuid", (
        f"themes.parent_theme_id should be UUID, got {parent_id_type!r}"
    )
    assert ult_theme_id_type == "uuid", (
        f"user_library_themes.theme_id should be UUID, got {ult_theme_id_type!r}"
    )


async def test_backup_tables_exist_with_fixed_date_suffix(
    db_engine: AsyncEngine,
) -> None:
    """Wave 1.5 plan: pre-flight ``CREATE TABLE ... AS SELECT *`` snapshots
    must remain in the schema for 90 days post-migration so emergency
    restore is possible."""
    expected_themes = "themes_backup_2026_04_29"
    expected_ult = "user_library_themes_backup_2026_04_29"

    async with db_engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' "
                "AND tablename IN (:t1, :t2)"
            ).bindparams(t1=expected_themes, t2=expected_ult)
        )
        present = {row[0] for row in rows}

    assert expected_themes in present, (
        f"{expected_themes!r} backup table missing — Wave 1.5 pre-flight backup "
        "did not survive the migration."
    )
    assert expected_ult in present, (
        f"{expected_ult!r} backup table missing — Wave 1.5 pre-flight backup "
        "did not survive the migration."
    )


async def test_create_theme_with_default_guid_pk(db_session: AsyncSession) -> None:
    """A fresh Theme row should auto-populate ``id`` from
    ``default=uuid.uuid4`` on the model."""
    # Look up the seeded ``local`` source so the FK is satisfied.
    src = (
        await db_session.execute(
            text(
                "SELECT id FROM marketplace_sources WHERE handle='local' "
                "AND scope='system'"
            )
        )
    ).first()
    assert src is not None, "alembic 0088 should have seeded the 'local' system source"
    local_source_id = src[0]

    theme = models.Theme(
        slug=f"wave15-{uuid.uuid4().hex[:8]}",
        name="Wave 1.5 test",
        mode="dark",
        theme_json={},
        source_id=local_source_id,
    )
    db_session.add(theme)
    await db_session.flush()

    assert isinstance(theme.id, uuid.UUID), (
        f"Theme.id should default to a UUID, got {type(theme.id).__name__}"
    )
    await db_session.rollback()


async def test_user_library_theme_fk_works_with_guid(
    db_session: AsyncSession,
) -> None:
    """End-to-end: insert Theme with GUID PK, then UserLibraryTheme that
    FKs into it. Both inserts must succeed and the relationship must
    resolve."""
    src = (
        await db_session.execute(
            text(
                "SELECT id FROM marketplace_sources WHERE handle='local' "
                "AND scope='system'"
            )
        )
    ).first()
    local_source_id = src[0]

    # Need a real user for UserLibraryTheme.user_id (FK constraint).
    user = models.User(
        id=uuid.uuid4(),
        email=f"wave15-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="x",
        name="Wave 1.5",
        username=f"w15-{uuid.uuid4().hex[:8]}",
        slug=f"w15-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(user)
    await db_session.flush()

    theme = models.Theme(
        slug=f"w15-fk-{uuid.uuid4().hex[:8]}",
        name="FK test",
        mode="dark",
        theme_json={},
        source_id=local_source_id,
    )
    db_session.add(theme)
    await db_session.flush()

    lib = models.UserLibraryTheme(
        user_id=user.id,
        theme_id=theme.id,  # GUID → GUID
        purchase_type="free",
        is_active=True,
    )
    db_session.add(lib)
    await db_session.flush()

    # Read it back via ORM to verify the FK survives a round-trip.
    fetched = (
        await db_session.execute(
            text("SELECT theme_id FROM user_library_themes WHERE id = :id").bindparams(
                id=lib.id
            )
        )
    ).first()
    assert fetched is not None
    assert uuid.UUID(str(fetched[0])) == theme.id
    await db_session.rollback()


async def test_parent_theme_self_fk_works_with_guid(
    db_session: AsyncSession,
) -> None:
    """Self-FK ``themes.parent_theme_id → themes.id`` works on the new
    GUID column."""
    src = (
        await db_session.execute(
            text(
                "SELECT id FROM marketplace_sources WHERE handle='local' "
                "AND scope='system'"
            )
        )
    ).first()
    local_source_id = src[0]

    parent = models.Theme(
        slug=f"w15-parent-{uuid.uuid4().hex[:6]}",
        name="Parent",
        mode="dark",
        theme_json={},
        source_id=local_source_id,
    )
    db_session.add(parent)
    await db_session.flush()

    child = models.Theme(
        slug=f"w15-child-{uuid.uuid4().hex[:6]}",
        name="Child",
        mode="dark",
        theme_json={},
        source_id=local_source_id,
        parent_theme_id=parent.id,
    )
    db_session.add(child)
    await db_session.flush()

    fetched = (
        await db_session.execute(
            text("SELECT parent_theme_id FROM themes WHERE id = :id").bindparams(
                id=child.id
            )
        )
    ).first()
    assert fetched is not None
    assert uuid.UUID(str(fetched[0])) == parent.id
    await db_session.rollback()


async def test_uq_themes_source_slug_present(db_engine: AsyncEngine) -> None:
    """``uq_themes_source_slug`` should still exist post-migration. Wave
    1 (alembic 0088) created it; Wave 1.5 must not have dropped it."""

    def _names(sync_conn: Any) -> set[str]:
        insp = inspect(sync_conn)
        names: set[str] = set()
        for u in insp.get_unique_constraints("themes"):
            names.add(u["name"])
        for i in insp.get_indexes("themes"):
            names.add(i["name"])
        return names

    async with db_engine.connect() as conn:
        names = await conn.run_sync(_names)

    assert "uq_themes_source_slug" in names, (
        f"uq_themes_source_slug missing post-Wave-1.5; got {sorted(names)}"
    )


# ---------------------------------------------------------------------------
# Legacy redirect — Wave 1.5 plan section 5
# ---------------------------------------------------------------------------


async def test_legacy_theme_detail_returns_301_to_source_prefixed_url() -> None:
    """``GET /api/marketplace/themes/legacy/{old_id}`` returns 301 to
    the Wave-5-stable URL shape ``/api/marketplace/tesslate-official/theme/{slug}``.

    This locks in the public-URL contract Wave 5 will satisfy with a
    real source-aware handler. Today the redirect target is a thin alias
    that calls back into the existing ``GET /marketplace/themes/{slug}``
    handler — the URL shape is what's load-bearing for stability.
    """
    # Late-import the FastAPI app so the test DB env is set first by
    # the parent integration conftest.
    from fastapi.testclient import TestClient

    # Use the orchestrator's app factory; we don't need DB here, just
    # the route resolution.
    from app.main import app

    client = TestClient(app)
    legacy_id = "midnight-dark"
    resp = client.get(
        f"/api/marketplace/themes/legacy/{legacy_id}",
        follow_redirects=False,
    )
    assert resp.status_code == 301, (
        f"Legacy theme URL should 301, got {resp.status_code}: {resp.text}"
    )
    location = resp.headers.get("location", "")
    assert "/marketplace/tesslate-official/theme/" in location, (
        f"Redirect target {location!r} does not match the Wave-5 source-prefixed shape"
    )
    assert legacy_id in location, (
        f"Redirect target {location!r} should preserve the slug ({legacy_id})"
    )


# Forward-compat sanity check on the GUID TypeDecorator with the new
# Theme model — guards against drift if someone ever swaps GUID for a
# plain Postgres UUID column directly on the model and breaks SQLite
# desktop builds.
def test_guid_typedecorator_still_used_on_theme_id() -> None:
    col = models.Theme.__table__.c.id
    assert isinstance(col.type, GUID), (
        f"Theme.id must use the GUID TypeDecorator (cross-dialect); got "
        f"{type(col.type).__name__}. Switching to a raw Postgres UUID type "
        "breaks the SQLite desktop sidecar."
    )
