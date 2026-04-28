"""Phase 4 — backend-agnostic lease matrix tests.

Plan §Phase 4 contract: "the same controller code passes the same
fail-over tests under all three CONTROLLER_LEASE_BACKEND settings (db,
redis, k8s)". Per-backend test files
(``test_lease_db.py`` / ``test_lease_redis.py`` / ``test_lease_k8s.py``)
exercise backend-specific edge cases; this file proves the **shared
contract** by parametrising one fixture across all three backends and
running every fail-over scenario against each.

Scenarios (each runs against every backend):

1. acquire → renew → release succeeds end-to-end.
2. holder dies (no renew) → second holder acquires after TTL expires.
3. two concurrent acquires from different holders → exactly one wins.
4. renew with a stale (deposed) token is rejected.
5. term monotonically increases across fresh acquisitions.

Backend availability:

* ``db``    — SQLite + alembic migrations (always available, mirrors the
  per-backend test fixture).
* ``redis`` — :mod:`fakeredis` if importable; otherwise the parameter
  is skipped (NOT failed) so contributors without Redis tooling can
  still develop.
* ``k8s``   — pure-Python in-memory ``coordination.k8s.io/v1.Lease``
  fake. We do **not** spin up minikube; we monkey-patch
  ``K8sLease._coord_api`` to a tracker that mimics the SDK's CRUD
  behaviour (read 404 → ``None``, replace conflict → exception, …).

The matrix design lets us add a fourth backend (etcd, Consul, …) by
appending a single backend factory below — no new scenario code.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, AsyncIterator, Callable

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.services.automations.lease import Lease, LeaseToken


# ---------------------------------------------------------------------------
# Backend registry — each entry is a ``(id, factory)`` pair.
#
# Factories are async generators yielding ``(Lease, helpers)`` where
# ``helpers`` exposes:
#
#   * ``expire(name)`` — force the named lease to be considered expired
#     by the next ``acquire`` call (without waiting real time).
#
# This indirection lets each scenario use the same scenario code while
# the fixture wiring is backend-specific.
# ---------------------------------------------------------------------------


class _Helpers:
    """Per-backend test helpers passed to scenario functions."""

    def __init__(self, expire: Callable[[str], Any]) -> None:
        self.expire = expire


# ---- DB backend ----------------------------------------------------------


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


def _migrate_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Run alembic upgrade head against a fresh SQLite file (sync).

    Alembic's ``env.py`` calls ``asyncio.run`` internally, so the
    migration MUST run before pytest-asyncio installs an event loop —
    i.e., inside a sync fixture/helper, never inside an async one.
    """
    db_path = tmp_path / "lease_matrix.db"
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
    return url


async def _build_db_backend(
    *, db_url: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[tuple[Lease, _Helpers]]:
    engine = create_async_engine(db_url, future=True)
    _install_sqlite_now(engine)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    import app.database as db_module

    monkeypatch.setattr(db_module, "AsyncSessionLocal", maker)

    from app.services.automations.lease.db import DBLease

    async def expire(name: str) -> None:
        async with maker() as session:
            await session.execute(
                text(
                    "UPDATE controller_leases SET expires_at = :past "
                    "WHERE name = :name"
                ),
                {
                    "past": datetime.now(UTC) - timedelta(seconds=10),
                    "name": name,
                },
            )
            await session.commit()

    try:
        yield DBLease(), _Helpers(expire=expire)
    finally:
        await engine.dispose()
        from app.config import get_settings

        get_settings.cache_clear()


# ---- Redis backend (fakeredis-backed) -----------------------------------


def _fakeredis_available() -> bool:
    try:
        import fakeredis  # noqa: F401

        return True
    except ImportError:
        return False


async def _build_redis_backend(
    *, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[tuple[Lease, _Helpers]]:
    if not _fakeredis_available():
        pytest.skip(
            "fakeredis not installed; redis lease backend cannot be matrix-tested"
        )

    import fakeredis.aioredis as fakeredis_aioredis

    fake_client = fakeredis_aioredis.FakeRedis(decode_responses=True)

    # Patch get_redis_client to hand the lease our fake client.
    from app.services import cache_service

    async def _fake_get_client():
        return fake_client

    monkeypatch.setattr(cache_service, "get_redis_client", _fake_get_client)

    from app.services.automations.lease.redis import RedisLease, _key

    backend = RedisLease()

    async def expire(name: str) -> None:
        # Drop the lock key — equivalent to TTL expiry from the
        # consumer's POV; the term counter is preserved so the next
        # ``acquire`` still bumps monotonically (matches Redis SETEX
        # semantics in production).
        await fake_client.delete(_key(name))

    try:
        yield backend, _Helpers(expire=expire)
    finally:
        await fake_client.aclose()


# ---- K8s backend (in-memory tracker) ------------------------------------


class _FakeK8sLeaseSpec:
    """Minimal stand-in for ``V1LeaseSpec`` — only attrs the backend reads."""

    def __init__(
        self,
        *,
        holder_identity: str | None,
        lease_duration_seconds: int,
        acquire_time: datetime,
        renew_time: datetime | None,
        lease_transitions: int,
    ) -> None:
        self.holder_identity = holder_identity
        self.lease_duration_seconds = lease_duration_seconds
        self.acquire_time = acquire_time
        self.renew_time = renew_time
        self.lease_transitions = lease_transitions


class _FakeK8sLease:
    def __init__(self, *, name: str, namespace: str, spec: _FakeK8sLeaseSpec) -> None:
        self.metadata = type("Meta", (), {"name": name, "namespace": namespace})()
        self.spec = spec


class _FakeApiException(Exception):
    """Mimics ``kubernetes.client.exceptions.ApiException`` (only ``.status``)."""

    def __init__(self, status: int, reason: str = "") -> None:
        super().__init__(reason or f"status={status}")
        self.status = status
        self.reason = reason


class _FakeCoordinationV1Api:
    """In-memory tracker for ``coordination.k8s.io/v1.Lease`` calls.

    Mimics the parts of the K8s sync SDK that :class:`K8sLease` calls:
    ``read_namespaced_lease`` (404 on miss), ``create_namespaced_lease``,
    ``replace_namespaced_lease`` (succeeds always — we don't simulate
    optimistic concurrency conflicts in this matrix; per-backend tests
    cover that), ``delete_namespaced_lease``.
    """

    def __init__(self) -> None:
        # key: (namespace, name) → _FakeK8sLease
        self._store: dict[tuple[str, str], _FakeK8sLease] = {}

    def read_namespaced_lease(self, *, name: str, namespace: str) -> _FakeK8sLease:
        lease = self._store.get((namespace, name))
        if lease is None:
            raise _FakeApiException(status=404, reason="NotFound")
        return lease

    def create_namespaced_lease(
        self, *, namespace: str, body: _FakeK8sLease
    ) -> _FakeK8sLease:
        key = (namespace, body.metadata.name)
        if key in self._store:
            raise _FakeApiException(status=409, reason="AlreadyExists")
        self._store[key] = body
        return body

    def replace_namespaced_lease(
        self, *, name: str, namespace: str, body: _FakeK8sLease
    ) -> _FakeK8sLease:
        self._store[(namespace, name)] = body
        return body

    def delete_namespaced_lease(self, *, name: str, namespace: str) -> None:
        self._store.pop((namespace, name), None)


async def _build_k8s_backend(
    *, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[tuple[Lease, _Helpers]]:
    # The real backend's __init__ tries to load kube config; bypass it
    # entirely by constructing the instance via __new__ and wiring the
    # attributes the methods read.
    from app.services.automations.lease import k8s as k8s_module

    # The backend reads ``self._models.V1Lease`` / ``V1ObjectMeta`` /
    # ``V1LeaseSpec`` to build the body it hands to ``_create``. Ours
    # are plain Python classes that mirror the SDK's keyword API just
    # enough for the spec attributes the backend touches (``read``
    # returns whatever ``_create`` produced, so SDK fidelity at the
    # wire level is irrelevant).
    fake_models_ns = type("FakeModels", (), {})()
    fake_models_ns.V1Lease = lambda metadata, spec: _FakeK8sLease(  # noqa: E731
        name=metadata["name"],
        namespace=metadata["namespace"],
        spec=spec,
    )
    fake_models_ns.V1ObjectMeta = lambda name, namespace: {  # noqa: E731
        "name": name,
        "namespace": namespace,
    }
    fake_models_ns.V1LeaseSpec = lambda **kw: _FakeK8sLeaseSpec(**kw)  # noqa: E731

    api = _FakeCoordinationV1Api()
    namespace = "tesslate-test"

    backend = k8s_module.K8sLease.__new__(k8s_module.K8sLease)
    backend._coord_api = api
    backend._namespace = namespace
    backend._models = fake_models_ns

    # The backend's _read translates the SDK's 404 ApiException into
    # ``None``. Our fake raises an exception with ``.status == 404`` so
    # the existing translation path is exercised.

    async def expire(name: str) -> None:
        lease = api._store.get((namespace, name))
        if lease is None:
            return
        # Move renew_time far enough in the past that
        # ``renew_time + lease_duration_seconds < now``.
        lease.spec.renew_time = datetime.now(UTC) - timedelta(
            seconds=max(60, int(lease.spec.lease_duration_seconds or 0)) + 10
        )

    try:
        yield backend, _Helpers(expire=expire)
    finally:
        api._store.clear()


# ---- Matrix parametrisation ---------------------------------------------


_BACKEND_IDS = ("db", "redis", "k8s")


@pytest.fixture
def db_url_for_matrix(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> str | None:
    """Sync sibling fixture — runs alembic upgrade for the ``db`` backend
    only, returns ``None`` for the other backends.

    Alembic's ``env.py`` calls ``asyncio.run`` which can't run inside a
    pytest-asyncio loop. By splitting migration into a sync fixture, we
    ensure the upgrade happens BEFORE the async ``lease`` fixture's loop
    is established.
    """
    backend_id = request.getfixturevalue("backend_id")
    if backend_id != "db":
        return None
    return _migrate_sqlite(tmp_path, monkeypatch)


@pytest.fixture(params=_BACKEND_IDS)
def backend_id(request: pytest.FixtureRequest) -> str:
    """The backend id under test (sync, so other sync fixtures can read it)."""
    return request.param


@pytest.fixture
async def lease(
    backend_id: str,
    db_url_for_matrix: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[Lease, _Helpers]]:
    """Parametrised across every backend in :data:`_BACKEND_IDS`."""
    if backend_id == "db":
        assert db_url_for_matrix is not None
        agen = _build_db_backend(db_url=db_url_for_matrix, monkeypatch=monkeypatch)
    elif backend_id == "redis":
        agen = _build_redis_backend(monkeypatch=monkeypatch)
    elif backend_id == "k8s":
        agen = _build_k8s_backend(monkeypatch=monkeypatch)
    else:  # pragma: no cover — keyed by parametrize, can't drift
        raise ValueError(f"unknown backend id: {backend_id}")

    backend, helpers = await agen.__anext__()
    try:
        yield backend, helpers
    finally:
        # Drain the async generator's ``finally`` block.
        with pytest.raises(StopAsyncIteration):
            await agen.__anext__()


def _unique_name() -> str:
    """Return a backend-safe unique name for the lease under test.

    Each test gets a fresh name so backend state (especially the in-
    process Redis term counter and the shared K8s tracker) doesn't leak
    between scenarios within the same backend's test session.
    """
    return f"matrix-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Scenarios — each runs once per backend.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acquire_renew_release_round_trip(
    lease: tuple[Lease, _Helpers],
) -> None:
    """1. acquire → renew → release happens cleanly on every backend."""
    backend, _ = lease
    name = _unique_name()

    token = await backend.acquire(name, holder_id="holder-A", ttl_seconds=60)
    assert token is not None, "fresh acquire must succeed"
    assert isinstance(token, LeaseToken)
    assert token.holder == "holder-A"
    assert token.term >= 1

    ok = await backend.renew(token)
    assert ok is True, "renew on a live token must succeed"

    # release is idempotent and returns None — just must not raise.
    await backend.release(token)


@pytest.mark.asyncio
async def test_holder_dies_then_second_acquires_after_ttl_expires(
    lease: tuple[Lease, _Helpers],
) -> None:
    """2. Holder A acquires + dies (no renew) → after expiry, B takes over."""
    backend, helpers = lease
    name = _unique_name()

    token_a = await backend.acquire(name, holder_id="holder-A", ttl_seconds=60)
    assert token_a is not None

    # Holder A dies — no release, no renew. We force expiry instead of
    # waiting real time so the test stays fast and deterministic.
    await helpers.expire(name)

    token_b = await backend.acquire(name, holder_id="holder-B", ttl_seconds=60)
    assert token_b is not None, "holder-B must acquire after expiry"
    assert token_b.holder == "holder-B"
    assert token_b.term > token_a.term, (
        "post-expiry takeover must bump term"
    )


@pytest.mark.asyncio
async def test_concurrent_acquire_only_one_wins(
    lease: tuple[Lease, _Helpers],
) -> None:
    """3. Two concurrent acquires from different holders → exactly one wins."""
    backend, _ = lease
    name = _unique_name()

    # Fire both acquires concurrently. Only one (deterministic by
    # serialisation order at the backend) returns a token; the other
    # MUST return ``None``.
    results = await asyncio.gather(
        backend.acquire(name, holder_id="holder-A", ttl_seconds=60),
        backend.acquire(name, holder_id="holder-B", ttl_seconds=60),
    )

    winners = [t for t in results if t is not None]
    losers = [t for t in results if t is None]
    assert len(winners) == 1, (
        f"exactly one acquire must win, got winners={len(winners)}"
    )
    assert len(losers) == 1, (
        f"the other acquire must return None, got losers={len(losers)}"
    )


@pytest.mark.asyncio
async def test_renew_with_stale_token_is_rejected(
    lease: tuple[Lease, _Helpers],
) -> None:
    """4. Renew with a stale (deposed) token must return False."""
    backend, helpers = lease
    name = _unique_name()

    token_a = await backend.acquire(name, holder_id="holder-A", ttl_seconds=60)
    assert token_a is not None

    await helpers.expire(name)

    token_b = await backend.acquire(name, holder_id="holder-B", ttl_seconds=60)
    assert token_b is not None
    assert token_b.term > token_a.term

    # Holder A wakes up and tries to renew with its old token — must fail.
    ok = await backend.renew(token_a)
    assert ok is False, "stale-token renew must be rejected by every backend"

    # Holder B's renew on its current token still works.
    ok_b = await backend.renew(token_b)
    assert ok_b is True


@pytest.mark.asyncio
async def test_term_is_monotonic_across_acquisitions(
    lease: tuple[Lease, _Helpers],
) -> None:
    """5. Term increases monotonically across a sequence of fresh acquires."""
    backend, helpers = lease
    name = _unique_name()

    terms: list[int] = []
    holder_ids = ["holder-A", "holder-B", "holder-A", "holder-C"]

    for holder in holder_ids:
        token = await backend.acquire(name, holder_id=holder, ttl_seconds=60)
        # Each fresh acquire after expiry must succeed.
        assert token is not None, (
            f"acquire by {holder} after expiry must succeed"
        )
        terms.append(token.term)
        # Force expiry for the next holder to take over.
        await helpers.expire(name)

    # Strictly monotonic — each new term is greater than the previous.
    for i in range(1, len(terms)):
        assert terms[i] > terms[i - 1], (
            f"term sequence must be monotonic; got {terms}"
        )
