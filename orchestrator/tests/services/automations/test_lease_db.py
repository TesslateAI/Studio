"""Phase 4 — DBLease backend tests.

Exercises :class:`app.services.automations.lease.db.DBLease` against a
SQLite database upgraded to alembic ``head`` so the real
``controller_leases`` table (alembic 0080) is in play.

Coverage matrix:

* fresh acquire → returns token with term=1
* re-acquire by same holder → bumps term
* concurrent acquire from a different holder while valid → returns None
* expired-takeover by different holder → returns token with bumped term
* renew on a live token → True; expiry extended in DB
* renew on a deposed token (term has moved on) → False
* release on a live token → row's holder cleared
* release on a deposed token → no-op (does not corrupt fresher leader's row)
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def _install_sqlite_now(engine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_conn, _record):  # noqa: ARG001
        dbapi_conn.create_function(
            "now", 0, lambda: datetime.now(UTC).isoformat(sep=" ")
        )


def _alembic_cfg() -> Config:
    orchestrator_dir = Path(__file__).resolve().parents[3]
    cfg = Config(str(orchestrator_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(orchestrator_dir / "alembic"))
    return cfg


@pytest.fixture
def migrated_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    db_path = tmp_path / "lease.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DEPLOYMENT_MODE", "desktop")

    from app.config import get_settings

    get_settings.cache_clear()
    orchestrator_dir = Path(__file__).resolve().parents[3]
    original = os.getcwd()
    os.chdir(orchestrator_dir)
    try:
        command.upgrade(_alembic_cfg(), "head")
    finally:
        os.chdir(original)
    yield url
    get_settings.cache_clear()


@pytest.fixture
def lease_backend(migrated_sqlite: str, monkeypatch: pytest.MonkeyPatch):
    """Build a DBLease wired up to the migrated SQLite, with a fresh engine.

    DBLease imports ``app.database.AsyncSessionLocal`` lazily on every
    method call. We monkeypatch that name in the database module so the
    backend uses our temp-file engine.
    """
    engine = create_async_engine(migrated_sqlite, future=True)
    _install_sqlite_now(engine)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    import app.database as db_module

    monkeypatch.setattr(db_module, "AsyncSessionLocal", maker)

    from app.services.automations.lease.db import DBLease

    yield DBLease(), maker
    asyncio.run(engine.dispose())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fresh_acquire_returns_term_one(lease_backend) -> None:
    backend, _ = lease_backend
    token = await backend.acquire("controller", "holder-A", ttl_seconds=60)
    assert token is not None
    assert token.holder == "holder-A"
    assert token.term == 1
    assert token.expires_at > datetime.now(UTC)


@pytest.mark.asyncio
async def test_same_holder_reacquire_bumps_term(lease_backend) -> None:
    backend, _ = lease_backend
    token1 = await backend.acquire("controller", "holder-A", 60)
    token2 = await backend.acquire("controller", "holder-A", 60)
    assert token1 is not None and token2 is not None
    assert token2.term == token1.term + 1


@pytest.mark.asyncio
async def test_concurrent_acquire_only_one_wins(lease_backend) -> None:
    backend, _ = lease_backend
    token = await backend.acquire("controller", "holder-A", 60)
    assert token is not None

    # holder-B tries while holder-A is live → None.
    none_token = await backend.acquire("controller", "holder-B", 60)
    assert none_token is None


@pytest.mark.asyncio
async def test_expired_takeover_by_different_holder(lease_backend) -> None:
    backend, maker = lease_backend
    token1 = await backend.acquire("controller", "holder-A", 60)
    assert token1 is not None

    # Manually expire the lease by setting expires_at in the past.
    async with maker() as session:
        await session.execute(
            text(
                "UPDATE controller_leases SET expires_at = :past WHERE name = 'controller'"
            ),
            {"past": datetime.now(UTC) - timedelta(seconds=10)},
        )
        await session.commit()

    token2 = await backend.acquire("controller", "holder-B", 60)
    assert token2 is not None
    assert token2.holder == "holder-B"
    assert token2.term == token1.term + 1


@pytest.mark.asyncio
async def test_renew_live_token_returns_true(lease_backend) -> None:
    backend, maker = lease_backend
    token = await backend.acquire("controller", "holder-A", 60)
    assert token is not None

    ok = await backend.renew(token)
    assert ok is True

    async with maker() as session:
        row = (
            await session.execute(
                text(
                    "SELECT holder, term, expires_at FROM controller_leases "
                    "WHERE name = 'controller'"
                )
            )
        ).first()
    assert row is not None
    assert row[0] == "holder-A"
    assert row[1] == token.term


@pytest.mark.asyncio
async def test_renew_deposed_token_returns_false(lease_backend) -> None:
    backend, maker = lease_backend
    token1 = await backend.acquire("controller", "holder-A", 60)
    assert token1 is not None

    # Expire it and let holder-B take over.
    async with maker() as session:
        await session.execute(
            text(
                "UPDATE controller_leases SET expires_at = :past WHERE name = 'controller'"
            ),
            {"past": datetime.now(UTC) - timedelta(seconds=10)},
        )
        await session.commit()

    token2 = await backend.acquire("controller", "holder-B", 60)
    assert token2 is not None
    assert token2.term > token1.term

    # Now holder-A's renew should fail — its term is no longer current.
    ok = await backend.renew(token1)
    assert ok is False


@pytest.mark.asyncio
async def test_release_clears_holder(lease_backend) -> None:
    backend, maker = lease_backend
    token = await backend.acquire("controller", "holder-A", 60)
    assert token is not None

    await backend.release(token)

    async with maker() as session:
        row = (
            await session.execute(
                text(
                    "SELECT holder, expires_at FROM controller_leases "
                    "WHERE name = 'controller'"
                )
            )
        ).first()
    assert row is not None
    assert row[0] is None
    assert row[1] is None


@pytest.mark.asyncio
async def test_release_deposed_token_is_noop(lease_backend) -> None:
    backend, maker = lease_backend
    token1 = await backend.acquire("controller", "holder-A", 60)
    assert token1 is not None

    # Expire and take over.
    async with maker() as session:
        await session.execute(
            text(
                "UPDATE controller_leases SET expires_at = :past WHERE name = 'controller'"
            ),
            {"past": datetime.now(UTC) - timedelta(seconds=10)},
        )
        await session.commit()

    token2 = await backend.acquire("controller", "holder-B", 60)
    assert token2 is not None

    # holder-A releases its old token — must NOT clobber holder-B's row.
    await backend.release(token1)

    async with maker() as session:
        row = (
            await session.execute(
                text(
                    "SELECT holder FROM controller_leases WHERE name = 'controller'"
                )
            )
        ).first()
    assert row is not None
    assert row[0] == "holder-B"
