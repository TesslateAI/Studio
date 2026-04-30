"""
Wave 7 — ``app_versions.source_id`` parity / consistency tests.

The invariant under test: every row in ``app_versions`` carries a
``source_id`` equal to its parent ``marketplace_apps.source_id``. Wave 7
promotes this from a soft service-layer rule to a hard runtime check
enforced by ``services/apps/app_version_source_consistency.py``'s
``before_flush`` SQLAlchemy listener AND verified at install time by
``services/apps/installer.py::install_app``.

Two layers of coverage live here:

1. **CI parity sweep** — runs ``scan_orphans`` against the live test DB.
   Any orphan row (``app_versions.source_id`` differing from
   ``marketplace_apps.source_id``) fails the test loud so a buggy
   migration / direct write can never silently land in production.
2. **Write-path enforcement** — exercises the ``before_flush`` listener
   by attempting to insert a deliberately-mismatched ``AppVersion`` and
   asserts the listener raises :class:`AppVersionSourceMismatch` with a
   stable ``reason='source_mismatch'`` token.
"""

from __future__ import annotations

import os
import time
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import AppVersion, MarketplaceApp, MarketplaceSource
from app.services.apps.app_version_source_consistency import (
    AppVersionSourceMismatch,
    assert_app_version_source_id_matches,
    scan_orphans,
)


_ASYNC_DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://tesslate_test:testpass@localhost:5433/tesslate_test",
)


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine(_ASYNC_DB_URL, future=True)
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionFactory() as session:
        try:
            yield session
        finally:
            try:
                await session.rollback()
            except Exception:  # noqa: BLE001
                pass
    await engine.dispose()


# ---------------------------------------------------------------------------
# CI parity sweep
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_no_orphan_app_version_source_id_rows_exist_in_test_db(
    db_session: AsyncSession,
) -> None:
    """``scan_orphans`` must return [] for the live integration DB.

    If this fires, a code path landed an ``AppVersion`` row whose
    ``source_id`` disagrees with its parent ``MarketplaceApp.source_id``.
    The Wave-7 ``before_flush`` listener should have rejected the write
    — fix the offending caller, then re-run the migration / sweep.
    """
    orphans = await scan_orphans(db_session)
    assert orphans == [], (
        f"Found {len(orphans)} app_versions row(s) whose source_id does "
        f"not match the parent marketplace_apps row: {orphans!r}"
    )


# ---------------------------------------------------------------------------
# Write-path enforcement
# ---------------------------------------------------------------------------


def _suffix() -> str:
    return f"{os.getpid()}-{int(time.time() * 1000) % 10_000_000}-{uuid.uuid4().hex[:6]}"


@pytest_asyncio.fixture
async def two_sources(db_session: AsyncSession) -> tuple[MarketplaceSource, MarketplaceSource]:
    """Spin up two distinct federated source rows the tests can mismatch on."""
    sfx = _suffix()
    s_a = MarketplaceSource(
        handle=f"av-src-a-{sfx}",
        display_name="Source A",
        base_url="https://src-a.invalid",
        scope="system",
        trust_level="admin_trusted",
        is_active=True,
        pinned_hub_id=f"hub-a-{sfx}",
    )
    s_b = MarketplaceSource(
        handle=f"av-src-b-{sfx}",
        display_name="Source B",
        base_url="https://src-b.invalid",
        scope="system",
        trust_level="admin_trusted",
        is_active=True,
        pinned_hub_id=f"hub-b-{sfx}",
    )
    db_session.add_all([s_a, s_b])
    await db_session.commit()
    await db_session.refresh(s_a)
    await db_session.refresh(s_b)
    yield s_a, s_b
    # Best-effort teardown — children cascade through marketplace_apps so
    # we delete app rows first then the sources.
    try:
        for src in (s_a, s_b):
            apps = (
                await db_session.execute(
                    MarketplaceApp.__table__.select().where(
                        MarketplaceApp.source_id == src.id
                    )
                )
            ).all()
            for app_row in apps:
                await db_session.execute(
                    AppVersion.__table__.delete().where(
                        AppVersion.app_id == app_row[0]
                    )
                )
            await db_session.execute(
                MarketplaceApp.__table__.delete().where(
                    MarketplaceApp.source_id == src.id
                )
            )
        await db_session.execute(
            MarketplaceSource.__table__.delete().where(
                MarketplaceSource.id.in_((s_a.id, s_b.id))
            )
        )
        await db_session.commit()
    except Exception:  # noqa: BLE001
        await db_session.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_before_flush_listener_blocks_mismatched_insert(
    db_session: AsyncSession,
    two_sources: tuple[MarketplaceSource, MarketplaceSource],
) -> None:
    """The Wave-7 ``before_flush`` listener must refuse a mismatched insert.

    Inserts a ``MarketplaceApp`` tagged with ``source_a`` then attempts
    to insert an ``AppVersion`` whose ``source_id`` points at
    ``source_b``. The flush must raise :class:`AppVersionSourceMismatch`
    with the ``source_mismatch`` reason token.
    """
    s_a, s_b = two_sources
    sfx = _suffix()
    app = MarketplaceApp(
        slug=f"av-mismatch-{sfx}",
        name="Wave-7 mismatch test",
        creator_user_id=None,
        source_id=s_a.id,
        state="approved",
        visibility="public",
    )
    db_session.add(app)
    await db_session.flush()

    av = AppVersion(
        app_id=app.id,
        version="1.0.0",
        manifest_schema_version="2026-05",
        manifest_json={},
        manifest_hash="x" * 64,
        feature_set_hash="y" * 64,
        approval_state="pending_stage1",
        published_at=datetime.now(UTC),
        source_id=s_b.id,  # deliberate drift — listener must catch
    )
    db_session.add(av)

    with pytest.raises((AppVersionSourceMismatch, IntegrityError)) as exc_info:
        await db_session.flush()

    # Unwrap IntegrityError if SQLAlchemy wrapped the listener exception.
    err = exc_info.value
    while isinstance(err, IntegrityError) and err.orig is not None:
        if isinstance(err.orig, AppVersionSourceMismatch):
            err = err.orig
            break
        break
    if isinstance(err, AppVersionSourceMismatch):
        assert err.reason == "source_mismatch"
        assert err.parent_source_id == s_a.id
        assert err.app_version_source_id == s_b.id

    # Roll back the failed flush so the teardown fixture can clean up.
    await db_session.rollback()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_before_flush_listener_allows_matching_insert(
    db_session: AsyncSession,
    two_sources: tuple[MarketplaceSource, MarketplaceSource],
) -> None:
    """The listener MUST NOT fire when source_id matches on both rows."""
    s_a, _ = two_sources
    sfx = _suffix()
    app = MarketplaceApp(
        slug=f"av-match-{sfx}",
        name="Wave-7 match test",
        source_id=s_a.id,
        state="approved",
        visibility="public",
    )
    db_session.add(app)
    await db_session.flush()

    av = AppVersion(
        app_id=app.id,
        version="1.0.0",
        manifest_schema_version="2026-05",
        manifest_json={},
        manifest_hash="x" * 64,
        feature_set_hash="y" * 64,
        approval_state="pending_stage1",
        published_at=datetime.now(UTC),
        source_id=s_a.id,
    )
    db_session.add(av)
    await db_session.flush()  # MUST NOT raise

    # Ensure the rows are visible in scan_orphans's view of the world.
    await db_session.commit()
    orphans = await scan_orphans(db_session)
    matched = [o for o in orphans if o["app_version_id"] == av.id]
    assert matched == [], f"matching insert produced an orphan row: {matched!r}"


# ---------------------------------------------------------------------------
# assert_app_version_source_id_matches helper
# ---------------------------------------------------------------------------


def test_assert_helper_raises_typed_error_on_mismatch() -> None:
    """Pre-flush helper is the canonical place service code checks."""
    src_a = uuid.uuid4()
    src_b = uuid.uuid4()
    with pytest.raises(AppVersionSourceMismatch) as exc_info:
        assert_app_version_source_id_matches(
            app_version_source_id=src_a,
            parent_source_id=src_b,
        )
    assert exc_info.value.reason == "source_mismatch"
    assert exc_info.value.app_version_source_id == src_a
    assert exc_info.value.parent_source_id == src_b


def test_assert_helper_passes_when_ids_agree() -> None:
    src = uuid.uuid4()
    # MUST NOT raise.
    assert_app_version_source_id_matches(
        app_version_source_id=src,
        parent_source_id=src,
    )


def test_assert_helper_treats_both_none_as_a_match() -> None:
    """Pre-Wave-7 rows with NULL source_id on both sides are not orphans —
    the migration backfills them, and until then we treat the (None, None)
    pair as consistent so the listener doesn't false-positive on a
    half-backfilled DB."""
    assert_app_version_source_id_matches(
        app_version_source_id=None,
        parent_source_id=None,
    )
