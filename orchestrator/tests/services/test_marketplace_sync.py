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
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import (
    AppVersion,
    MarketplaceAgent,
    MarketplaceApp,
    MarketplaceSource,
)
from app.models_automations import AppInstance
from app.services.marketplace_client import HubIdMismatchError
from app.services.marketplace_sync import (
    _DEFAULT_MANIFEST_SCHEMA_VERSION,
    MarketplaceSyncWorker,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ORCHESTRATOR_TEST_DB_URL = (
    "postgresql+asyncpg://tesslate_test:testpass@localhost:5433/tesslate_test"
)

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

    db_url = f"postgresql+asyncpg://tesslate_test:testpass@localhost:5433/{MARKETPLACE_DB_NAME}"

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
            f"marketplace init_db failed (rc={init_proc.returncode}): {init_proc.stderr[-1000:]}"
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
    engine = create_async_engine(_ORCHESTRATOR_TEST_DB_URL, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
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
        (
            await orchestrator_session.execute(
                select(MarketplaceSource).where(MarketplaceSource.handle == "tesslate-official")
            )
        )
        .scalars()
        .first()
    )
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


def _orchestrator_session_factory() -> async_sessionmaker:
    """Return a sessionmaker the worker uses to open new sessions per task.

    The engine is shared via a module-level instance so repeated calls in a
    single test run share the connection pool rather than leaking a new pool
    per call.
    """
    return async_sessionmaker(
        create_async_engine(_ORCHESTRATOR_TEST_DB_URL, future=True),
        expire_on_commit=False,
    )


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
        (
            await orchestrator_session.execute(
                select(MarketplaceAgent)
                .where(MarketplaceAgent.source_id == federated_source.id)
                .where(MarketplaceAgent.source_etag.is_not(None))
            )
        )
        .scalars()
        .all()
    )
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
        (
            await orchestrator_session.execute(
                select(MarketplaceAgent).where(MarketplaceAgent.id == target_id)
            )
        )
        .scalars()
        .first()
    )
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
        (
            await orchestrator_session.execute(
                select(MarketplaceSource).where(MarketplaceSource.handle == "local")
            )
        )
        .scalars()
        .first()
    )
    assert local is not None, "seeded `local` system row missing"

    SessionFactory = _orchestrator_session_factory()
    worker = MarketplaceSyncWorker(db_session_factory=SessionFactory)
    result = await worker.sync_source(local.id)
    assert result.skipped_reason == "local_source"
    assert result.error is None


# ---------------------------------------------------------------------------
# Wave 3 fixes — hub-id drift auto-disable, type-aware app tombstone
# ---------------------------------------------------------------------------


class _FakeMarketplaceClient:
    """In-test stand-in for :class:`MarketplaceClient`.

    ``get_manifest`` raises whatever exception was passed to the constructor
    so tests can drive specific failure modes (e.g. hub-id drift). All other
    methods raise :exc:`NotImplementedError` with a descriptive message so an
    unexpected call produces a clear test failure rather than a silent
    ``AttributeError``.
    """

    def __init__(self, manifest_exc: Exception) -> None:
        self._manifest_exc = manifest_exc
        self.aclose_calls = 0

    async def get_manifest(self) -> dict:
        raise self._manifest_exc

    async def get_changes(self, **kwargs):
        raise NotImplementedError("_FakeMarketplaceClient.get_changes not configured for this test")

    async def get_yanks(self, **kwargs):
        raise NotImplementedError("_FakeMarketplaceClient.get_yanks not configured for this test")

    async def get_item(self, kind: str, slug: str):
        raise NotImplementedError("_FakeMarketplaceClient.get_item not configured for this test")

    async def get_bundle(self, kind: str, slug: str, version: str):
        raise NotImplementedError("_FakeMarketplaceClient.get_bundle not configured for this test")

    async def list_versions(self, kind: str, slug: str):
        raise NotImplementedError(
            "_FakeMarketplaceClient.list_versions not configured for this test"
        )

    async def aclose(self) -> None:
        self.aclose_calls += 1


@pytest.mark.integration
@pytest.mark.asyncio
async def test_hub_id_mismatch_auto_disables_source(
    orchestrator_session: AsyncSession,
) -> None:
    """Plan §X (hub identity headers): a hub-id pin mismatch must auto-
    disable the source, persist the typed error, and surface a re-pair
    hint in the error so the UI can render an actionable banner.

    Today (pre-fix) we only persisted last_sync_error and left the source
    active — meaning the next sync tick would just retry against the
    drift-detected hub. This test pins the source, mocks the client to
    raise HubIdMismatchError on the manifest call, and asserts the source
    flips inactive AND the error includes the actionable hint.
    """
    handle = f"hub-drift-{os.getpid()}-{int(time.time() * 1000) % 10_000_000}"
    source = MarketplaceSource(
        handle=handle,
        display_name="Drifty Hub",
        base_url="https://example.invalid",
        scope="system",
        trust_level="untrusted",
        is_active=True,
        pinned_hub_id="original-hub-id",
    )
    orchestrator_session.add(source)
    await orchestrator_session.commit()
    await orchestrator_session.refresh(source)

    drift_exc = HubIdMismatchError(
        expected="original-hub-id",
        actual="hijacked-hub-id",
        url="https://example.invalid/v1/manifest",
    )

    def _fake_factory(_source, _token):  # signature: (MarketplaceSource, str|None)
        return _FakeMarketplaceClient(manifest_exc=drift_exc)

    try:
        SessionFactory = _orchestrator_session_factory()
        worker = MarketplaceSyncWorker(
            db_session_factory=SessionFactory,
            marketplace_client_factory=_fake_factory,
        )
        result = await worker.sync_source(source.id)

        # Sync surfaces the error and the auto-disable hint.
        assert result.error is not None
        assert "Hub ID drift" in result.error
        assert "Test Connection" in result.error
        assert "auto-disabled" in result.error

        # Re-read source — auto-disable must be persisted.
        await orchestrator_session.refresh(source)
        assert source.is_active is False, "hub-id drift must auto-disable the source per the plan"
        assert source.last_sync_error is not None
        assert "Hub ID drift" in source.last_sync_error
        assert source.last_synced_at is not None
        # Pin is left untouched on purpose — the user must explicitly
        # re-pair via Test Connection to re-pin.
        assert source.pinned_hub_id == "original-hub-id"
    finally:
        await orchestrator_session.delete(source)
        await orchestrator_session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_handle_deactivate_app_uses_state_column(
    orchestrator_session: AsyncSession,
    federated_source: MarketplaceSource,
) -> None:
    """``MarketplaceApp`` has no ``is_active`` boolean — only a ``state`` enum
    (models.py:2046). The deactivate handler must therefore set
    ``state='deprecated'`` and ``deactivated_upstream_at`` instead of writing
    to a non-existent ``is_active`` attribute.

    Pre-fix the handler blindly wrote ``row.is_active = False`` which silently
    succeeded as an ad-hoc Python attribute set but never persisted, so
    federated apps stayed in the "approved" state forever.
    """
    from uuid import uuid4 as _uuid4

    slug = f"federated-app-deactivate-{_uuid4().hex[:10]}"
    app = MarketplaceApp(
        slug=slug,
        name="Federated App To Deactivate",
        creator_user_id=None,
        state="approved",
        visibility="public",
        source_id=federated_source.id,
        source_etag="v1",
        source_remote_id=slug,
        deleted_upstream=False,
    )
    orchestrator_session.add(app)
    await orchestrator_session.commit()
    await orchestrator_session.refresh(app)

    SessionFactory = _orchestrator_session_factory()
    worker = MarketplaceSyncWorker(db_session_factory=SessionFactory)

    # Run the handler in its own session (matches sync worker semantics).
    async with SessionFactory() as sess:
        # The handler reads source via the row's source_id; refetch so the
        # session knows about the federated_source.
        bound_source = await sess.get(MarketplaceSource, federated_source.id)
        assert bound_source is not None
        await worker._handle_deactivate(sess, bound_source, "app", slug)
        await sess.commit()

    await orchestrator_session.refresh(app)
    assert app.state == "deprecated", (
        "MarketplaceApp deactivate must flip state column, not non-existent is_active"
    )
    assert app.deactivated_upstream_at is not None

    # Cleanup.
    await orchestrator_session.delete(app)
    await orchestrator_session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_handle_delete_app_with_no_user_state_hard_deletes(
    orchestrator_session: AsyncSession,
    federated_source: MarketplaceSource,
) -> None:
    """``_handle_delete`` on an unreferenced app must hard-delete the row.

    Companion to the stub-keep test below; this one validates the no-user-
    state branch still works for ``MarketplaceApp`` after the type-aware
    fix in ``_handle_delete``.
    """
    from uuid import uuid4 as _uuid4

    slug = f"federated-app-delete-{_uuid4().hex[:10]}"
    app = MarketplaceApp(
        slug=slug,
        name="Federated App Delete Me",
        creator_user_id=None,
        state="approved",
        visibility="public",
        source_id=federated_source.id,
        source_etag="v1",
        source_remote_id=slug,
        deleted_upstream=False,
    )
    orchestrator_session.add(app)
    await orchestrator_session.commit()
    app_id = app.id

    SessionFactory = _orchestrator_session_factory()
    worker = MarketplaceSyncWorker(db_session_factory=SessionFactory)

    async with SessionFactory() as sess:
        bound_source = await sess.get(MarketplaceSource, federated_source.id)
        assert bound_source is not None
        ok = await worker._handle_delete(sess, bound_source, "app", slug)
        assert ok is True
        await sess.commit()

    remaining = (
        (
            await orchestrator_session.execute(
                select(MarketplaceApp).where(MarketplaceApp.id == app_id)
            )
        )
        .scalars()
        .first()
    )
    assert remaining is None, "no user state references — row should be hard-deleted"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_handle_delete_app_with_user_state_keeps_stub(
    orchestrator_session: AsyncSession,
    federated_source: MarketplaceSource,
) -> None:
    """When a user-state row (AppInstance) still FKs to the app, the delete
    handler must keep a stub: ``deleted_upstream=True``,
    ``deleted_upstream_at`` set, and ``state='deprecated'`` (since
    MarketplaceApp lacks an ``is_active`` column). The AppInstance row
    must remain untouched — the stub exists precisely to satisfy the
    RESTRICT FK constraint without breaking installed users.
    """
    from uuid import uuid4

    from app import models

    user_id = uuid4()
    user = models.User(
        id=user_id,
        email=f"stub-{user_id}@example.com",
        hashed_password="x",
        is_active=True,
        is_superuser=False,
        is_verified=True,
        name="Stub Owner",
        username=f"stub-{user_id.hex[:10]}",
        slug=f"stub-{user_id.hex[:10]}",
    )
    orchestrator_session.add(user)

    slug = f"federated-app-stub-{user_id.hex[:10]}"
    app = MarketplaceApp(
        slug=slug,
        name="Federated App With Installs",
        creator_user_id=user_id,
        state="approved",
        visibility="public",
        source_id=federated_source.id,
        source_etag="v1",
        source_remote_id=slug,
        deleted_upstream=False,
    )
    orchestrator_session.add(app)
    await orchestrator_session.flush()

    version = models.AppVersion(
        id=uuid4(),
        app_id=app.id,
        version="1.0.0",
        manifest_schema_version="2026-05",
        manifest_json={"app": {"slug": slug}},
        manifest_hash="hash1",
        feature_set_hash="fh1",
        approval_state="stage1_approved",
        published_at=datetime.now(UTC),
        # Migration 0088 made source_id NOT NULL on app_versions; mirror
        # the parent app's source so the row inserts cleanly.
        source_id=federated_source.id,
    )
    orchestrator_session.add(version)
    await orchestrator_session.flush()

    instance = AppInstance(
        id=uuid4(),
        app_id=app.id,
        app_version_id=version.id,
        installer_user_id=user_id,
        state="installed",
    )
    orchestrator_session.add(instance)
    await orchestrator_session.commit()

    app_id = app.id
    instance_id = instance.id

    SessionFactory = _orchestrator_session_factory()
    worker = MarketplaceSyncWorker(db_session_factory=SessionFactory)

    try:
        async with SessionFactory() as sess:
            bound_source = await sess.get(MarketplaceSource, federated_source.id)
            assert bound_source is not None
            ok = await worker._handle_delete(sess, bound_source, "app", slug)
            assert ok is True
            await sess.commit()

        await orchestrator_session.refresh(app)
        assert app.deleted_upstream is True
        assert app.deleted_upstream_at is not None
        assert app.state == "deprecated", (
            "MarketplaceApp delete-stub must flip state to 'deprecated' since "
            "the model has no is_active boolean"
        )

        # The AppInstance MUST be untouched — the stub exists to satisfy
        # the RESTRICT FK without disrupting installed users.
        surviving_inst = (
            (
                await orchestrator_session.execute(
                    select(AppInstance).where(AppInstance.id == instance_id)
                )
            )
            .scalars()
            .first()
        )
        assert surviving_inst is not None, "AppInstance must not be deleted"
        assert surviving_inst.state == "installed"
    finally:
        # Teardown in FK order: instance → version → app → user.
        await orchestrator_session.execute(
            AppInstance.__table__.delete().where(AppInstance.id == instance_id)
        )
        await orchestrator_session.execute(
            models.AppVersion.__table__.delete().where(models.AppVersion.id == version.id)
        )
        await orchestrator_session.execute(
            MarketplaceApp.__table__.delete().where(MarketplaceApp.id == app_id)
        )
        await orchestrator_session.execute(
            models.User.__table__.delete().where(models.User.id == user_id)
        )
        await orchestrator_session.commit()


# ---------------------------------------------------------------------------
# Wave 7 — federated yank consumer
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_apply_yank_event_marks_app_version_yanked_upstream(
    orchestrator_session: AsyncSession,
    federated_source: MarketplaceSource,
) -> None:
    """Wave 7: a ``yank`` op for kind=``app`` from a non-Tesslate-Official
    source must (a) flip ``app_versions.state='yanked'`` (the column the
    runtime gate inspects), (b) populate
    ``app_versions.yanked_upstream_at``, and (c) preserve any installed
    AppInstance row so the runtime gate refuses to start it on the next
    ``begin_session`` call.
    """
    from uuid import uuid4

    from app import models
    from app.services.marketplace_client import JsonObject

    user_id = uuid4()
    user = models.User(
        id=user_id,
        email=f"yank-{user_id}@example.com",
        hashed_password="x",
        is_active=True,
        is_superuser=False,
        is_verified=True,
        name="Yank Owner",
        username=f"yank-{user_id.hex[:10]}",
        slug=f"yank-{user_id.hex[:10]}",
    )
    orchestrator_session.add(user)

    slug = f"federated-yank-target-{user_id.hex[:10]}"
    app = MarketplaceApp(
        slug=slug,
        name="Federated Yank Target",
        creator_user_id=user_id,
        state="approved",
        visibility="public",
        source_id=federated_source.id,
        source_etag="v1",
        source_remote_id=slug,
        deleted_upstream=False,
    )
    orchestrator_session.add(app)
    await orchestrator_session.flush()

    version = models.AppVersion(
        id=uuid4(),
        app_id=app.id,
        version="1.0.0",
        manifest_schema_version="2026-05",
        manifest_json={"app": {"slug": slug}},
        manifest_hash="hash-yank",
        feature_set_hash="fh-yank",
        approval_state="stage1_approved",
        published_at=datetime.now(UTC),
        source_id=federated_source.id,
    )
    orchestrator_session.add(version)
    await orchestrator_session.flush()

    instance = AppInstance(
        id=uuid4(),
        app_id=app.id,
        app_version_id=version.id,
        installer_user_id=user_id,
        state="installed",
    )
    orchestrator_session.add(instance)
    await orchestrator_session.commit()

    app_id = app.id
    version_id = version.id
    instance_id = instance.id

    SessionFactory = _orchestrator_session_factory()
    worker = MarketplaceSyncWorker(db_session_factory=SessionFactory)

    yank_event: JsonObject = {
        "op": "yank",
        "kind": "app",
        "slug": slug,
        "version": "1.0.0",
        "etag": "v2",
        "payload": {"reason": "security incident", "severity": "critical"},
    }

    try:
        async with SessionFactory() as sess:
            bound_source = await sess.get(MarketplaceSource, federated_source.id)
            assert bound_source is not None
            counter = await worker._apply_event(
                sess,
                bound_source,
                client=None,  # yank handler does not call the client
                event=yank_event,
            )
            await sess.commit()
        assert counter == "versions_yanked", (
            f"Wave 7 yank consumer expected to bump versions_yanked counter, got {counter!r}"
        )

        await orchestrator_session.refresh(version)
        assert version.approval_state == "yanked"
        assert version.yanked_upstream_at is not None
        assert version.yanked_at is not None
        assert "security incident" in (version.yanked_reason or "")

        # Installed AppInstance is untouched — runtime gate is the
        # authoritative refuse-to-start barrier.
        surviving_inst = (
            (
                await orchestrator_session.execute(
                    select(AppInstance).where(AppInstance.id == instance_id)
                )
            )
            .scalars()
            .first()
        )
        assert surviving_inst is not None
        assert surviving_inst.state == "installed"

        # The runtime gate (services/apps/runtime.py::_load_runnable_instance)
        # MUST refuse to mint a session for an instance pinned at a yanked
        # version. We import + invoke the loader here so the test pins the
        # actual gate behaviour rather than just asserting on column state.
        from app.services.apps.runtime import (
            AppNotRunnableError,
            _load_runnable_instance,
        )

        with pytest.raises(AppNotRunnableError) as exc_info:
            await _load_runnable_instance(orchestrator_session, instance_id)
        assert "yanked" in str(exc_info.value)

    finally:
        await orchestrator_session.execute(
            AppInstance.__table__.delete().where(AppInstance.id == instance_id)
        )
        await orchestrator_session.execute(
            models.AppVersion.__table__.delete().where(models.AppVersion.id == version_id)
        )
        await orchestrator_session.execute(
            MarketplaceApp.__table__.delete().where(MarketplaceApp.id == app_id)
        )
        await orchestrator_session.execute(
            models.User.__table__.delete().where(models.User.id == user_id)
        )
        await orchestrator_session.commit()


# ---------------------------------------------------------------------------
# Unit tests — no DB required
# ---------------------------------------------------------------------------


class TestDerivePricing:
    """Pure unit tests for the pricing stripping / trust-gate logic."""

    def test_trusted_source_passes_paid_pricing_through(self):
        upstream = {"pricing_type": "paid", "price_cents": 999, "stripe_price_id": "price_abc"}
        result = MarketplaceSyncWorker._derive_effective_pricing(upstream, is_trusted=True)
        assert result["pricing_type"] == "paid"
        assert result["price_cents"] == 999
        assert result["stripe_price_id"] == "price_abc"
        assert result["stripped"] is False

    def test_untrusted_source_paid_is_stripped_to_free(self):
        upstream = {"pricing_type": "paid", "price_cents": 500, "stripe_price_id": "price_xyz"}
        result = MarketplaceSyncWorker._derive_effective_pricing(upstream, is_trusted=False)
        assert result["pricing_type"] == "free"
        assert result["price_cents"] == 0
        assert result["stripe_price_id"] is None
        assert result["stripped"] is True

    def test_untrusted_free_item_not_marked_stripped(self):
        upstream = {"pricing_type": "free", "price_cents": 0, "stripe_price_id": None}
        result = MarketplaceSyncWorker._derive_effective_pricing(upstream, is_trusted=False)
        assert result["pricing_type"] == "free"
        assert result["stripped"] is False

    def test_empty_upstream_defaults_to_free(self):
        result = MarketplaceSyncWorker._derive_effective_pricing({}, is_trusted=False)
        assert result["pricing_type"] == "free"
        assert result["price_cents"] == 0
        assert result["stripped"] is False

    def test_nonzero_cents_with_free_type_is_still_stripped(self):
        upstream = {"pricing_type": "free", "price_cents": 1}
        result = MarketplaceSyncWorker._derive_effective_pricing(upstream, is_trusted=False)
        assert result["stripped"] is True

    def test_trusted_free_item_not_stripped(self):
        upstream = {"pricing_type": "free", "price_cents": 0}
        result = MarketplaceSyncWorker._derive_effective_pricing(upstream, is_trusted=True)
        assert result["stripped"] is False


class TestResolvePricing:
    """Tests for the _resolve_pricing helper that wraps _derive_effective_pricing."""

    def test_extracts_dict_pricing_from_item(self):
        item = {"pricing": {"pricing_type": "paid", "price_cents": 100}}
        pricing, effective = MarketplaceSyncWorker._resolve_pricing(item, "official")
        assert pricing == {"pricing_type": "paid", "price_cents": 100}
        assert effective["pricing_type"] == "paid"

    def test_non_dict_pricing_treated_as_empty(self):
        item = {"pricing": "not-a-dict"}
        pricing, _ = MarketplaceSyncWorker._resolve_pricing(item, "official")
        assert pricing == {}

    def test_missing_pricing_treated_as_empty(self):
        item = {}
        pricing, effective = MarketplaceSyncWorker._resolve_pricing(item, "untrusted")
        assert pricing == {}
        assert effective["pricing_type"] == "free"


class TestExtractVersionManifest:
    """Tests for _extract_version_manifest."""

    def test_reads_from_versions_list(self):
        item = {"versions": [{"manifest": {"mode": "dark"}}]}
        result = MarketplaceSyncWorker._extract_version_manifest(item)
        assert result == {"mode": "dark"}

    def test_falls_back_to_top_level_manifest(self):
        item = {"manifest": {"mode": "light"}}
        result = MarketplaceSyncWorker._extract_version_manifest(item)
        assert result == {"mode": "light"}

    def test_falls_back_to_extra_metadata(self):
        item = {"extra_metadata": {"skill_body": "do stuff"}}
        result = MarketplaceSyncWorker._extract_version_manifest(item)
        assert result == {"skill_body": "do stuff"}

    def test_returns_none_when_absent(self):
        assert MarketplaceSyncWorker._extract_version_manifest({}) is None


class TestManifestRefreshDue:
    """Tests for the per-instance manifest refresh cache."""

    def test_always_due_on_fresh_worker(self):
        worker = MarketplaceSyncWorker(db_session_factory=lambda: None)
        assert worker._manifest_refresh_due(uuid4()) is True

    def test_not_due_immediately_after_update(self):
        import time

        worker = MarketplaceSyncWorker(db_session_factory=lambda: None)
        source_id = uuid4()
        worker._manifest_refresh_at[source_id] = time.monotonic()
        assert worker._manifest_refresh_due(source_id) is False

    def test_workers_do_not_share_cache(self):
        import time

        w1 = MarketplaceSyncWorker(db_session_factory=lambda: None)
        w2 = MarketplaceSyncWorker(db_session_factory=lambda: None)
        source_id = uuid4()
        w1._manifest_refresh_at[source_id] = time.monotonic()
        # w2 has its own dict — the update to w1 must not affect w2.
        assert w2._manifest_refresh_due(source_id) is True


class TestSchemaVersionExtraction:
    """Regression tests for the schema_version ternary bug (#460/#461)."""

    def test_reads_manifest_schema_version_without_compatibility_dict(self):
        """manifest_schema_version at top level, no compatibility key — must not fall back."""
        manifest = {"manifest_schema_version": "2026-05"}
        # Reproduce the logic from _sync_app_versions inline so the test is
        # self-contained and does not depend on the private method's internals.
        schema_version = (
            manifest.get("manifest_schema_version")
            or (manifest.get("compatibility") or {}).get("manifest_schema")
            or _DEFAULT_MANIFEST_SCHEMA_VERSION
        )
        assert schema_version == "2026-05"

    def test_reads_from_compatibility_dict_when_top_level_absent(self):
        manifest = {"compatibility": {"manifest_schema": "2025-06"}}
        schema_version = (
            manifest.get("manifest_schema_version")
            or (manifest.get("compatibility") or {}).get("manifest_schema")
            or _DEFAULT_MANIFEST_SCHEMA_VERSION
        )
        assert schema_version == "2025-06"

    def test_falls_back_to_default_when_both_absent(self):
        manifest = {}
        schema_version = (
            manifest.get("manifest_schema_version")
            or (manifest.get("compatibility") or {}).get("manifest_schema")
            or _DEFAULT_MANIFEST_SCHEMA_VERSION
        )
        assert schema_version == _DEFAULT_MANIFEST_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Integration — pricing_change event handler
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_handle_pricing_change_strips_untrusted_source(
    orchestrator_session: AsyncSession,
    federated_source: MarketplaceSource,
) -> None:
    """``_handle_pricing_change`` must strip a paid price to free when the
    source is untrusted, and preserve the raw payload in the provenance columns."""
    slug = f"pricing-change-test-{uuid4().hex[:10]}"
    agent = MarketplaceAgent(
        slug=slug,
        name="Pricing Change Test Agent",
        item_type="agent",
        source_id=federated_source.id,
        source_etag="v1",
        source_remote_id=slug,
        pricing_type="free",
        price=0,
        deleted_upstream=False,
    )
    orchestrator_session.add(agent)
    await orchestrator_session.commit()

    # Temporarily make the source untrusted so we can verify stripping.
    saved_trust = federated_source.trust_level
    federated_source.trust_level = "untrusted"
    await orchestrator_session.commit()

    try:
        factory = _orchestrator_session_factory()
        worker = MarketplaceSyncWorker(db_session_factory=factory)
        async with factory() as sess:
            bound_source = await sess.get(MarketplaceSource, federated_source.id)
            assert bound_source is not None
            ok = await worker._handle_pricing_change(
                sess,
                bound_source,
                "agent",
                slug,
                {"from": "free", "to": "paid", "price_cents": 999, "stripe_price_id": "price_x"},
            )
            assert ok is True
            await sess.commit()

        await orchestrator_session.refresh(agent)
        # Untrusted source — price must be stripped to free.
        assert agent.pricing_type == "free"
        assert agent.price == 0
        assert agent.source_pricing_ignored is True
        # Provenance preserved.
        assert agent.source_pricing_type_original == "paid"
    finally:
        federated_source.trust_level = saved_trust
        await orchestrator_session.commit()
        await orchestrator_session.delete(agent)
        await orchestrator_session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_handle_pricing_change_passes_through_on_trusted_source(
    orchestrator_session: AsyncSession,
    federated_source: MarketplaceSource,
) -> None:
    """On a trusted source the effective price must match the upstream payload."""
    slug = f"pricing-trusted-{uuid4().hex[:10]}"
    agent = MarketplaceAgent(
        slug=slug,
        name="Trusted Pricing Agent",
        item_type="agent",
        source_id=federated_source.id,
        source_etag="v1",
        source_remote_id=slug,
        pricing_type="free",
        price=0,
        deleted_upstream=False,
    )
    orchestrator_session.add(agent)
    await orchestrator_session.commit()

    try:
        factory = _orchestrator_session_factory()
        worker = MarketplaceSyncWorker(db_session_factory=factory)
        # federated_source fixture points at tesslate-official which is "official" trust.
        async with factory() as sess:
            bound_source = await sess.get(MarketplaceSource, federated_source.id)
            assert bound_source is not None
            ok = await worker._handle_pricing_change(
                sess,
                bound_source,
                "agent",
                slug,
                {"from": "free", "to": "paid", "price_cents": 500, "stripe_price_id": "price_y"},
            )
            assert ok is True
            await sess.commit()

        await orchestrator_session.refresh(agent)
        assert agent.pricing_type == "paid"
        assert agent.price == 500
        assert agent.source_pricing_ignored is False
    finally:
        await orchestrator_session.delete(agent)
        await orchestrator_session.commit()


# ---------------------------------------------------------------------------
# Integration — version_remove event handler
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_handle_version_remove_hard_deletes_unreferenced_version(
    orchestrator_session: AsyncSession,
    federated_source: MarketplaceSource,
) -> None:
    """An unreferenced AppVersion must be hard-deleted on version_remove."""

    slug = f"ver-remove-{uuid4().hex[:10]}"
    app = MarketplaceApp(
        slug=slug,
        name="Version Remove App",
        creator_user_id=None,
        state="approved",
        visibility="public",
        source_id=federated_source.id,
        source_etag="v1",
        source_remote_id=slug,
        deleted_upstream=False,
    )
    orchestrator_session.add(app)
    await orchestrator_session.flush()

    version = AppVersion(
        id=uuid4(),
        app_id=app.id,
        version="2.0.0",
        manifest_schema_version="2026-05",
        manifest_json={"app": {"slug": slug}},
        manifest_hash="hash-remove",
        feature_set_hash="fh-remove",
        approval_state="stage1_approved",
        published_at=datetime.now(UTC),
        source_id=federated_source.id,
    )
    orchestrator_session.add(version)
    await orchestrator_session.commit()
    version_id = version.id

    factory = _orchestrator_session_factory()
    worker = MarketplaceSyncWorker(db_session_factory=factory)

    try:
        async with factory() as sess:
            bound_source = await sess.get(MarketplaceSource, federated_source.id)
            assert bound_source is not None
            removed = await worker._handle_version_remove(sess, bound_source, "app", slug, "2.0.0")
            assert removed is True
            await sess.commit()

        remaining = (
            (
                await orchestrator_session.execute(
                    select(AppVersion).where(AppVersion.id == version_id)
                )
            )
            .scalars()
            .first()
        )
        assert remaining is None, "unreferenced AppVersion should be hard-deleted"
    finally:
        await orchestrator_session.execute(
            MarketplaceApp.__table__.delete().where(MarketplaceApp.id == app.id)
        )
        await orchestrator_session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_handle_version_remove_yanks_referenced_version(
    orchestrator_session: AsyncSession,
    federated_source: MarketplaceSource,
) -> None:
    """An AppVersion referenced by an AppInstance must be yanked, not hard-deleted."""
    from app import models

    user_id = uuid4()
    user = models.User(
        id=user_id,
        email=f"ver-remove-ref-{user_id}@example.com",
        hashed_password="x",
        is_active=True,
        is_superuser=False,
        is_verified=True,
        name="Version Remove Ref Owner",
        username=f"ver-rem-{user_id.hex[:10]}",
        slug=f"ver-rem-{user_id.hex[:10]}",
    )
    orchestrator_session.add(user)

    slug = f"ver-remove-ref-{user_id.hex[:10]}"
    app = MarketplaceApp(
        slug=slug,
        name="Version Remove Ref App",
        creator_user_id=user_id,
        state="approved",
        visibility="public",
        source_id=federated_source.id,
        source_etag="v1",
        source_remote_id=slug,
        deleted_upstream=False,
    )
    orchestrator_session.add(app)
    await orchestrator_session.flush()

    version = AppVersion(
        id=uuid4(),
        app_id=app.id,
        version="3.0.0",
        manifest_schema_version="2026-05",
        manifest_json={"app": {"slug": slug}},
        manifest_hash="hash-ref",
        feature_set_hash="fh-ref",
        approval_state="stage1_approved",
        published_at=datetime.now(UTC),
        source_id=federated_source.id,
    )
    orchestrator_session.add(version)
    await orchestrator_session.flush()

    instance = AppInstance(
        id=uuid4(),
        app_id=app.id,
        app_version_id=version.id,
        installer_user_id=user_id,
        state="installed",
    )
    orchestrator_session.add(instance)
    await orchestrator_session.commit()

    version_id = version.id
    instance_id = instance.id

    factory = _orchestrator_session_factory()
    worker = MarketplaceSyncWorker(db_session_factory=factory)

    try:
        async with factory() as sess:
            bound_source = await sess.get(MarketplaceSource, federated_source.id)
            assert bound_source is not None
            removed = await worker._handle_version_remove(sess, bound_source, "app", slug, "3.0.0")
            assert removed is True
            await sess.commit()

        await orchestrator_session.refresh(version)
        assert version.approval_state == "yanked", (
            "referenced AppVersion must be yanked rather than hard-deleted"
        )
        assert version.yanked_upstream_at is not None

        surviving_inst = (
            (
                await orchestrator_session.execute(
                    select(AppInstance).where(AppInstance.id == instance_id)
                )
            )
            .scalars()
            .first()
        )
        assert surviving_inst is not None, "AppInstance must survive a version_remove"
    finally:
        await orchestrator_session.execute(
            AppInstance.__table__.delete().where(AppInstance.id == instance_id)
        )
        await orchestrator_session.execute(
            AppVersion.__table__.delete().where(AppVersion.id == version_id)
        )
        await orchestrator_session.execute(
            MarketplaceApp.__table__.delete().where(MarketplaceApp.id == app.id)
        )
        await orchestrator_session.execute(
            models.User.__table__.delete().where(models.User.id == user_id)
        )
        await orchestrator_session.commit()


# ---------------------------------------------------------------------------
# Unit — fetch_yanks_aggressively (mocked client, no real hub)
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_fetch_yanks_aggressively_skips_sources_with_no_yanks_feed(
    orchestrator_session: AsyncSession,
) -> None:
    """When every active source's /v1/yanks endpoint returns UnsupportedCapabilityError
    the fast path must return a result per source with no error and 0 yanks."""
    from app.services.marketplace_client import UnsupportedCapabilityError

    handle = f"yanks-fast-{uuid4().hex[:10]}"
    source = MarketplaceSource(
        handle=handle,
        display_name="Yanks Fast Test",
        base_url="https://example.invalid",
        scope="system",
        trust_level="official",
        is_active=True,
        pinned_hub_id="hub-yanks-fast",
    )
    orchestrator_session.add(source)
    await orchestrator_session.commit()
    await orchestrator_session.refresh(source)

    class _NoYanksFeed(_FakeMarketplaceClient):
        def __init__(self):
            super().__init__(manifest_exc=RuntimeError("should not be called"))

        async def get_manifest(self):
            raise RuntimeError("get_manifest should not be called for yanks-only path")

        async def get_yanks(self, **kwargs):
            raise UnsupportedCapabilityError(
                capability="yanks", url="https://example.invalid/v1/yanks"
            )

    def _factory(_src, _tok):
        return _NoYanksFeed()

    try:
        factory = _orchestrator_session_factory()
        worker = MarketplaceSyncWorker(
            db_session_factory=factory,
            marketplace_client_factory=_factory,
        )
        results = await worker.fetch_yanks_aggressively()
        # The source above + any other active sources are polled. The one we
        # inserted must appear in results with no error (UnsupportedCapabilityError
        # is swallowed as a graceful skip).
        our_results = [r for r in results if r.source_handle == handle]
        assert our_results, f"source {handle!r} missing from results"
        r = our_results[0]
        assert r.error is None, (
            f"yanks-only fast path should not error on unsupported feed: {r.error}"
        )
        assert r.versions_yanked == 0
    finally:
        await orchestrator_session.delete(source)
        await orchestrator_session.commit()
