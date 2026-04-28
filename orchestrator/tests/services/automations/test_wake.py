"""Unit tests for ``services.automations.wake.provision_for_run``.

These tests run against a SQLite database upgraded to alembic ``head`` so
the real ``automation_runs`` / ``automation_approval_requests`` tables are
in play (the wake path persists state changes on the run row when a
readiness timeout fires).

Coverage matrix (matches the agent integration spec):

* already-warm endpoints → ready immediately, no scale wait.
* zero-replica scale-up → first poll empty, second poll ready.
* readiness timeout → run flipped to ``waiting_approval``,
  ``AutomationApprovalRequest`` row inserted, result carries the id.
* no runtime / Tier-0 path → ready=True, reason='no_runtime_required'.

The K8s client is a hand-rolled fake so the tests do NOT depend on the
real ``kubernetes`` package being importable. Wake's ``_endpoints_ready``
takes any object exposing ``read_namespaced_endpoints``; ditto for
``apps_v1``.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


# ---------------------------------------------------------------------------
# Fixtures (mirror tests/services/automations/test_invocation_subject.py)
# ---------------------------------------------------------------------------


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
    db_path = tmp_path / "wake.db"
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
def session_maker(migrated_sqlite: str):
    engine = create_async_engine(migrated_sqlite, future=True)
    _install_sqlite_now(engine)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker
    asyncio.run(engine.dispose())


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _seed_user(db) -> uuid.UUID:
    from sqlalchemy import insert as core_insert

    from app.models_auth import User

    user_id = uuid.uuid4()
    suffix = uuid.uuid4().hex[:8]
    await db.execute(
        core_insert(User.__table__).values(
            id=user_id,
            email=f"wake-{suffix}@example.com",
            hashed_password="x",
            is_active=True,
            is_superuser=False,
            is_verified=True,
            name="Wake Tester",
            username=f"u{suffix}",
            slug=f"u-{suffix}",
        )
    )
    await db.flush()
    return user_id


async def _seed_run(db, *, owner_user_id: uuid.UUID) -> uuid.UUID:
    """Insert a minimal automation_definition + automation_run pair."""
    from app.models_automations import (
        AutomationDefinition,
        AutomationEvent,
        AutomationRun,
    )

    autom = AutomationDefinition(
        id=uuid.uuid4(),
        name="wake-test",
        owner_user_id=owner_user_id,
        workspace_scope="none",
        contract={"allowed_tools": [], "max_compute_tier": 0},
        max_compute_tier=0,
        is_active=True,
    )
    db.add(autom)
    evt = AutomationEvent(
        id=uuid.uuid4(),
        automation_id=autom.id,
        payload={},
        trigger_kind="manual",
    )
    db.add(evt)
    await db.flush()
    run = AutomationRun(
        id=uuid.uuid4(),
        automation_id=autom.id,
        event_id=evt.id,
        status="preflight",
    )
    db.add(run)
    await db.flush()
    return run.id


def _make_deployment(
    *,
    namespace: str = "proj-test",
    primary_container_id: str | None = None,
    desired_replicas: int = 1,
):
    """Build an in-memory AppRuntimeDeployment-shaped object.

    The wake path only reads ``namespace``, ``primary_container_id``,
    ``desired_replicas``, and ``id``. Using a SimpleNamespace keeps the
    test independent of FK plumbing.
    """
    return SimpleNamespace(
        id=uuid.uuid4(),
        namespace=namespace,
        primary_container_id=primary_container_id or f"app-{uuid.uuid4().hex[:8]}",
        desired_replicas=desired_replicas,
    )


def _make_k8s_client(*, endpoints_results: list[bool]):
    """Fake k8s client whose ``read_namespaced_endpoints`` returns ready/not-ready.

    ``endpoints_results`` is a queue of booleans; True means a ready
    address subset is present. We rebuild the full V1Endpoints shape (as
    a SimpleNamespace) so wake's ``getattr(ep, 'subsets', ...)`` walks
    correctly without importing kubernetes.
    """
    apps_v1 = MagicMock()
    apps_v1.read_namespaced_deployment = MagicMock(
        return_value=SimpleNamespace(spec=SimpleNamespace(replicas=0))
    )
    apps_v1.patch_namespaced_deployment = MagicMock(return_value=None)

    core_v1 = MagicMock()
    queue = list(endpoints_results)

    def _read_eps(name, namespace):  # noqa: ARG001 — match k8s client sig
        ready = queue.pop(0) if queue else False
        if ready:
            subset = SimpleNamespace(
                addresses=[SimpleNamespace(ip="10.0.0.1")],
                not_ready_addresses=None,
            )
            return SimpleNamespace(subsets=[subset])
        return SimpleNamespace(subsets=[])

    core_v1.read_namespaced_endpoints = _read_eps
    return SimpleNamespace(apps_v1=apps_v1, core_v1=core_v1)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_provision_for_run_already_warm_returns_ready_immediately(
    session_maker,
) -> None:
    """Endpoints come back ready on the first poll → no wait, no approval."""
    from app.models_automations import AutomationRun
    from app.services.automations.wake import provision_for_run

    captured_enqueue = []

    async def _fake_enqueue(name, payload):
        captured_enqueue.append((name, payload))

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            run_id = await _seed_run(db, owner_user_id=user_id)
            await db.commit()

        async with session_maker() as db:
            deployment = _make_deployment()
            k8s = _make_k8s_client(endpoints_results=[True])
            result = await provision_for_run(
                run_id,
                db,
                k8s,
                deployment_override=deployment,
                enqueue_fn=_fake_enqueue,
                timeout_seconds=5,
                poll_interval_seconds=1,
            )
            await db.commit()
            run = (
                await db.execute(
                    select(AutomationRun).where(AutomationRun.id == run_id)
                )
            ).scalar_one()
            return result, run

    result, run = asyncio.run(go())
    assert result.ready is True
    assert result.reason == "ready"
    assert result.approval_request_id is None
    # Endpoints became ready on the first poll — duration well under the
    # 1s poll interval (we slept zero times).
    assert result.duration_seconds < 1.0
    # Run was NOT flipped to waiting_approval.
    assert run.status == "preflight"
    assert run.paused_reason is None
    assert len(captured_enqueue) == 1


@pytest.mark.unit
def test_provision_for_run_scales_then_waits_for_endpoints(
    session_maker,
) -> None:
    """Scale 0→1; first poll empty, second poll ready → ready=True."""
    from app.services.automations.wake import provision_for_run

    async def _noop_enqueue(name, payload):
        return None

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            run_id = await _seed_run(db, owner_user_id=user_id)
            await db.commit()

        async with session_maker() as db:
            deployment = _make_deployment(desired_replicas=1)
            k8s = _make_k8s_client(endpoints_results=[False, True])
            result = await provision_for_run(
                run_id,
                db,
                k8s,
                deployment_override=deployment,
                enqueue_fn=_noop_enqueue,
                timeout_seconds=10,
                poll_interval_seconds=0,  # Fast spin in the test loop.
            )
            await db.commit()
            return result, k8s

    result, k8s = asyncio.run(go())
    assert result.ready is True
    assert result.reason == "ready"
    # Scale was patched (target_replicas = max(1, desired) = 1).
    assert k8s.apps_v1.patch_namespaced_deployment.call_count == 1


@pytest.mark.unit
def test_provision_for_run_timeout_creates_approval_request(
    session_maker,
) -> None:
    """Endpoints never ready → run flips to waiting_approval + approval row."""
    from app.models_automations import AutomationApprovalRequest, AutomationRun
    from app.services.automations.wake import provision_for_run

    async def _noop_enqueue(name, payload):
        return None

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            run_id = await _seed_run(db, owner_user_id=user_id)
            await db.commit()

        async with session_maker() as db:
            deployment = _make_deployment()
            # Endpoints never become ready; the queue keeps returning False.
            k8s = _make_k8s_client(endpoints_results=[False] * 10)
            result = await provision_for_run(
                run_id,
                db,
                k8s,
                deployment_override=deployment,
                enqueue_fn=_noop_enqueue,
                # 0s timeout + 0s interval = bail on the first poll loop
                # tick without burning real wall time.
                timeout_seconds=0,
                poll_interval_seconds=0,
            )
            await db.commit()
            run = (
                await db.execute(
                    select(AutomationRun).where(AutomationRun.id == run_id)
                )
            ).scalar_one()
            approvals = (
                await db.execute(
                    select(AutomationApprovalRequest).where(
                        AutomationApprovalRequest.run_id == run_id
                    )
                )
            ).scalars().all()
            return result, run, approvals

    result, run, approvals = asyncio.run(go())
    assert result.ready is False
    assert result.reason == "readiness_timeout"
    assert result.approval_request_id is not None
    assert run.status == "waiting_approval"
    assert run.paused_reason == "compute_unavailable"
    assert len(approvals) == 1
    approval = approvals[0]
    assert approval.id == result.approval_request_id
    assert approval.context.get("kind") == "compute_unavailable"


@pytest.mark.unit
def test_provision_for_run_no_runtime_required(session_maker) -> None:
    """deployment_override=None → Tier-0 fast path: ready, no wake."""
    from app.services.automations.wake import provision_for_run

    captured = []

    async def _fake_enqueue(name, payload):
        captured.append((name, payload))

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            run_id = await _seed_run(db, owner_user_id=user_id)
            await db.commit()

        async with session_maker() as db:
            # No deployment + no override → wake skips the K8s path entirely.
            k8s = _make_k8s_client(endpoints_results=[])
            result = await provision_for_run(
                run_id,
                db,
                k8s,
                deployment_override=None,
                enqueue_fn=_fake_enqueue,
            )
            await db.commit()
            return result

    result = asyncio.run(go())
    assert result.ready is True
    assert result.reason == "no_runtime_required"
    assert result.approval_request_id is None
    # The execute_action enqueue still fires so the worker picks the run up.
    assert len(captured) == 1
    assert captured[0][0] == "execute_action"
