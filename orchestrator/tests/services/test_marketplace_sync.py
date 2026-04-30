"""
Integration tests for ``app.services.marketplace_sync``.

Boots the real Wave-2 marketplace service against a fresh per-test DB,
inserts a :class:`MarketplaceSource` row pointing at it, runs the sync
worker once, and asserts:

  - federated catalog rows landed in the orchestrator's tables tagged
    with the source_id and source_etag,
  - source.sync_etag advanced past v0,
  - source.last_synced_at is set + last_sync_error is NULL,
  - source.pinned_hub_id was populated on first sync (verifying the
    auto-pin behavior),
  - source.capabilities_cache and policies_cache snapshot landed.

A second part of the suite emits a ``delete`` tombstone via the
marketplace service's ``changes_emitter`` and re-runs the worker; the
catalog row is expected to be gone (or stub-marked deleted_upstream when
user state references it).
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import (
    MarketplaceAgent,
    MarketplaceBase,
    MarketplaceSource,
    Theme,
    WorkflowTemplate,
)
from app.services.marketplace_sync import MarketplaceSyncWorker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_for_port(port: int, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError(f"port {port} did not open within {timeout}s")


def _run_psql(sql: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "docker",
            "exec",
            "tesslate-postgres-test",
            "psql",
            "-U",
            "tesslate_test",
            "-d",
            "postgres",
            "-c",
            sql,
        ],
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# Fixtures (module-scoped boot of the marketplace service + per-test DB)
# ---------------------------------------------------------------------------


MARKETPLACE_DB_NAME = "marketplace_sync_test"


@pytest.fixture(scope="module")
def marketplace_service():
    repo_root = Path(__file__).resolve().parents[3]
    pkg_dir = repo_root / "packages" / "tesslate-marketplace"
    venv_python = pkg_dir / ".venv" / "bin" / "python"
    if not venv_python.exists():
        pytest.skip(f"marketplace venv not found at {venv_python}")

    try:
        with socket.create_connection(("localhost", 5433), timeout=2):
            pass
    except OSError:
        pytest.skip("postgres test container not reachable on :5433")

    db_url = (
        f"postgresql+asyncpg://tesslate_test:testpass@localhost:5433/{MARKETPLACE_DB_NAME}"
    )

    # Provision a clean DB. DROP/CREATE require autocommit (no transaction).
    for stmt in (
        f"DROP DATABASE IF EXISTS {MARKETPLACE_DB_NAME};",
        f"CREATE DATABASE {MARKETPLACE_DB_NAME};",
    ):
        result = _run_psql(stmt)
        if result.returncode != 0:
            pytest.skip(f"DB provisioning failed: {result.stderr}")

    # Init schema + seed data.
    init_proc = subprocess.run(
        [str(venv_python), "scripts/init_db.py"],
        cwd=pkg_dir,
        capture_output=True,
        text=True,
        env={**os.environ, "DATABASE_URL": db_url},
        timeout=600,
    )
    if init_proc.returncode != 0:
        pytest.skip(
            f"marketplace init_db failed (rc={init_proc.returncode}): "
            f"{init_proc.stderr[-1000:]}"
        )

    port = _free_port()
    log_path = Path("/tmp") / f"marketplace-sync-test-{port}.log"
    log_file = log_path.open("w")
    proc = subprocess.Popen(
        [
            str(venv_python),
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=pkg_dir,
        stdout=log_file,
        stderr=log_file,
        env={**os.environ, "DATABASE_URL": db_url},
    )
    try:
        _wait_for_port(port)
        yield {
            "port": port,
            "base_url": f"http://127.0.0.1:{port}",
            "db_url": db_url,
            "pkg_dir": pkg_dir,
            "venv_python": venv_python,
        }
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log_file.close()


@pytest_asyncio.fixture
async def orchestrator_session() -> AsyncSession:
    """Per-test orchestrator AsyncSession bound to the standard test DB.

    The integration conftest already runs alembic upgrade head against
    `tesslate_test` on session start, so the marketplace_sources table is
    present.
    """
    engine = create_async_engine(
        "postgresql+asyncpg://tesslate_test:testpass@localhost:5433/tesslate_test",
        future=True,
    )
    SessionFactory = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionFactory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def federated_source(
    marketplace_service, orchestrator_session: AsyncSession
) -> MarketplaceSource:
    """Hijack the seeded ``tesslate-official`` system row to point at the
    locally-booted Wave-2 marketplace service for the duration of the test.

    Per the Wave-1/Wave-3 plan, federated sync runs against Tesslate Official
    only until Wave 5 drops the global slug uniqueness constraint. Adding a
    second federated source for the same slugs would collide with that
    legacy invariant — the sync worker handles those collisions defensively
    (per-event SAVEPOINT + skip), but the deterministic positive-path
    assertions need a source that can actually upsert without colliding.

    Use the canonical official row, swap its base_url, run the worker, and
    restore the original URL on teardown.
    """
    official = (
        await orchestrator_session.execute(
            select(MarketplaceSource).where(MarketplaceSource.handle == "tesslate-official")
        )
    ).scalars().first()
    assert official is not None, "seeded `tesslate-official` system row missing"

    saved_base_url = official.base_url
    saved_etag = official.sync_etag
    saved_pin = official.pinned_hub_id
    saved_caps = official.capabilities_cache
    saved_policies = official.policies_cache
    saved_last_synced_at = official.last_synced_at
    saved_last_error = official.last_sync_error

    official.base_url = marketplace_service["base_url"]
    # Reset sync state so the test starts from v0 against the fresh hub.
    official.sync_etag = None
    official.pinned_hub_id = None
    official.last_sync_error = None
    await orchestrator_session.commit()
    await orchestrator_session.refresh(official)

    yield official

    # Restore original state on teardown so subsequent tests + the live
    # production state (when this DB is shared) aren't affected.
    official.base_url = saved_base_url
    official.sync_etag = saved_etag
    official.pinned_hub_id = saved_pin
    official.capabilities_cache = saved_caps
    official.policies_cache = saved_policies
    official.last_synced_at = saved_last_synced_at
    official.last_sync_error = saved_last_error
    await orchestrator_session.commit()


def _orchestrator_session_factory():
    """Factory the worker uses to open new sessions per task."""
    engine = create_async_engine(
        "postgresql+asyncpg://tesslate_test:testpass@localhost:5433/tesslate_test",
        future=True,
    )
    return async_sessionmaker(engine, expire_on_commit=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sync_source_lands_federated_rows(
    marketplace_service, orchestrator_session: AsyncSession, federated_source: MarketplaceSource
) -> None:
    """First sync_source call must:

    - call get_manifest, populate pinned_hub_id, capabilities_cache,
      policies_cache,
    - drain /v1/changes,
    - upsert MarketplaceAgent rows tagged with source_id == federated_source.id.
    """
    SessionFactory = _orchestrator_session_factory()
    worker = MarketplaceSyncWorker(db_session_factory=SessionFactory)

    result = await worker.sync_source(federated_source.id)

    # Sync result is non-error.
    assert result.error is None, f"sync error: {result.error}"
    assert result.skipped_reason is None
    # First poll on a fresh source must process at least the seed events.
    # (init_db emits one upsert per seed item; the marketplace ships ~150 seeds.)
    assert result.items_upserted > 0
    # etag advanced past v0.
    assert result.etag_advanced_to is not None
    assert result.etag_advanced_to.startswith("v")

    # Re-read the source to verify side effects.
    await orchestrator_session.refresh(federated_source)
    assert federated_source.pinned_hub_id is not None
    assert federated_source.last_synced_at is not None
    assert federated_source.last_sync_error is None
    assert isinstance(federated_source.capabilities_cache, list)
    assert "catalog.read" in federated_source.capabilities_cache
    assert isinstance(federated_source.policies_cache, dict)
    assert federated_source.sync_etag is not None
    assert federated_source.sync_etag.startswith("v")

    # Catalog rows landed for the source. Sync upserts every event the
    # marketplace's /v1/changes feed advertised; some legacy seed rows
    # tagged with TESSLATE_OFFICIAL but not present in the marketplace
    # service's seeds remain unmodified — we filter to rows the sync
    # actually touched (source_etag IS NOT NULL).
    synced_agents = (
        await orchestrator_session.execute(
            select(MarketplaceAgent)
            .where(MarketplaceAgent.source_id == federated_source.id)
            .where(MarketplaceAgent.source_etag.is_not(None))
        )
    ).scalars().all()
    assert len(synced_agents) >= 5, (
        f"expected at least 5 federated agents synced, got {len(synced_agents)}"
    )

    for row in synced_agents:
        assert row.source_etag, f"row {row.slug!r} missing source_etag"
        assert row.source_remote_id, f"row {row.slug!r} missing source_remote_id"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sync_source_handles_delete_tombstone(
    marketplace_service, orchestrator_session: AsyncSession, federated_source: MarketplaceSource
) -> None:
    """Emit a delete tombstone in the marketplace's changes feed; verify
    the local catalog row is removed (no user-state FKs in this test)."""
    SessionFactory = _orchestrator_session_factory()
    worker = MarketplaceSyncWorker(db_session_factory=SessionFactory)

    # Run an initial sync so the catalog is populated.
    first = await worker.sync_source(federated_source.id)
    assert first.error is None, first.error

    # Pick a real seeded slug to delete.
    seeded = (
        await orchestrator_session.execute(
            select(MarketplaceAgent.slug, MarketplaceAgent.id)
            .where(MarketplaceAgent.source_id == federated_source.id)
            .where(MarketplaceAgent.item_type == "agent")
            .limit(1)
        )
    ).first()
    assert seeded is not None, "no seeded agent rows to delete"
    target_slug, target_id = seeded

    # Emit a delete tombstone on the marketplace side via its changes_emitter.
    pkg_dir = marketplace_service["pkg_dir"]
    venv_python = marketplace_service["venv_python"]
    db_url = marketplace_service["db_url"]

    emit_script = f"""
import asyncio
import sys
sys.path.insert(0, {str(pkg_dir)!r})
from app.database import get_session_factory
from app.services import changes_emitter

async def main():
    factory = get_session_factory()
    async with factory() as session:
        await changes_emitter.emit(session, op='delete', kind='agent', slug={target_slug!r})
        await session.commit()

asyncio.run(main())
"""
    proc = subprocess.run(
        [str(venv_python), "-c", emit_script],
        cwd=pkg_dir,
        capture_output=True,
        text=True,
        env={**os.environ, "DATABASE_URL": db_url},
        timeout=30,
    )
    assert proc.returncode == 0, f"emitter failed: {proc.stderr}"

    # Run sync again — the delete event applies.
    second = await worker.sync_source(federated_source.id)
    assert second.error is None, second.error
    assert second.items_deleted >= 1

    # The row is either hard-deleted (no user state references) OR
    # stub-marked deleted_upstream=True (some user-state row still FK
    # references it). Both outcomes are correct per the plan; the
    # behaviour split is the worker's _has_user_state_reference check.
    remaining = (
        await orchestrator_session.execute(
            select(MarketplaceAgent).where(MarketplaceAgent.id == target_id)
        )
    ).scalars().first()
    if remaining is None:
        # Hard-deleted path
        return
    # Stub path — must have deleted_upstream tombstone fields set.
    assert remaining.deleted_upstream is True, (
        "row was not hard-deleted; expected deleted_upstream=True stub"
    )
    assert remaining.deleted_upstream_at is not None
    assert remaining.is_active is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sync_source_records_error_on_unreachable_hub(
    orchestrator_session: AsyncSession,
) -> None:
    """If the hub is unreachable, sync_source must persist last_sync_error
    on the row rather than crash — UI surfaces it via the source list."""
    # Build a source pointing at a port that nothing is listening on.
    handle = f"unreach-{os.getpid()}-{int(time.time() * 1000) % 10_000_000}"
    source = MarketplaceSource(
        handle=handle,
        display_name="Unreachable",
        base_url="http://127.0.0.1:1",
        scope="system",
        trust_level="untrusted",
        is_active=True,
    )
    orchestrator_session.add(source)
    await orchestrator_session.commit()
    await orchestrator_session.refresh(source)

    try:
        SessionFactory = _orchestrator_session_factory()
        worker = MarketplaceSyncWorker(db_session_factory=SessionFactory)
        result = await worker.sync_source(source.id)
        assert result.error is not None
        # Re-read the source to confirm the error landed on the row.
        await orchestrator_session.refresh(source)
        assert source.last_sync_error is not None
        assert source.last_synced_at is not None
    finally:
        await orchestrator_session.delete(source)
        await orchestrator_session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sync_source_skips_local_sources(
    orchestrator_session: AsyncSession,
) -> None:
    """A `local`/`local://` source must short-circuit with the typed
    skipped_reason and never hit the network."""
    # Look up the seeded `local` system row.
    local = (
        await orchestrator_session.execute(
            select(MarketplaceSource).where(MarketplaceSource.handle == "local")
        )
    ).scalars().first()
    assert local is not None, "seeded `local` system row missing"

    SessionFactory = _orchestrator_session_factory()
    worker = MarketplaceSyncWorker(db_session_factory=SessionFactory)
    result = await worker.sync_source(local.id)
    assert result.skipped_reason == "local_source"
    assert result.error is None
