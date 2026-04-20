"""Wave 3 router unit tests: submissions / yanks / admin-marketplace.

These are unit tests only — FastAPI deps (`get_db`, `current_active_user`,
`current_superuser`) are overridden; service-layer calls are monkey-patched.
Integration round-trips are deliberately skipped — they live in the
service-layer integration suites.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5433/test")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("DEPLOYMENT_MODE", "docker")
os.environ.setdefault("LITELLM_API_BASE", "http://localhost:4000/v1")
os.environ.setdefault("LITELLM_MASTER_KEY", "test-key")


pytestmark = pytest.mark.asyncio


def _make_user(superuser: bool = False) -> MagicMock:
    u = MagicMock()
    u.id = uuid.uuid4()
    u.is_active = True
    u.is_superuser = superuser
    return u


_ROUTES_MOUNTED = False


def _ensure_routes():
    """Include Wave 3 routers onto the main app (idempotent per-process).

    We intentionally do NOT edit main.py — this helper mounts the new
    routers in the test process only so endpoint paths resolve.
    """
    global _ROUTES_MOUNTED
    if _ROUTES_MOUNTED:
        return
    from app.main import app
    from app.routers import admin_marketplace, app_submissions, app_yanks

    app.include_router(
        app_submissions.router, prefix="/api/app-submissions", tags=["app-submissions"]
    )
    app.include_router(app_yanks.router, prefix="/api/app-yanks", tags=["app-yanks"])
    app.include_router(
        admin_marketplace.router,
        prefix="/api/admin-marketplace",
        tags=["admin-marketplace"],
    )
    _ROUTES_MOUNTED = True


@pytest.fixture(autouse=True)
def _mount_routes():
    _ensure_routes()
    yield


# ---------------------------------------------------------------------------
# 1. Submission advance requires admin
# ---------------------------------------------------------------------------


async def test_submission_advance_requires_admin():
    # Force superuser dep to raise 403 (fastapi_users default).
    from fastapi import HTTPException

    from app.database import get_db
    from app.main import app
    from app.users import current_active_user, current_superuser

    def _forbid():
        raise HTTPException(status_code=403, detail="forbidden")

    regular = _make_user(superuser=False)
    mock_db = AsyncMock()

    async def _get_db():
        yield mock_db

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[current_active_user] = lambda: regular
    app.dependency_overrides[current_superuser] = _forbid
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer test-dummy"},
        ) as ac:
            r = await ac.post(
                f"/api/app-submissions/{uuid.uuid4()}/advance",
                json={"to_stage": "stage1"},
            )
        assert r.status_code == 403
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 2. Submission advance translates InvalidTransitionError -> 409
# ---------------------------------------------------------------------------


async def test_submission_advance_409_on_invalid_transition(monkeypatch):
    from app.database import get_db
    from app.main import app
    from app.services.apps import submissions as submissions_svc
    from app.users import current_active_user, current_superuser

    admin = _make_user(superuser=True)
    mock_db = AsyncMock()

    async def _get_db():
        yield mock_db

    async def _raise(*a, **kw):
        raise submissions_svc.InvalidTransitionError("bad jump")

    monkeypatch.setattr(submissions_svc, "advance_stage", _raise)

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[current_active_user] = lambda: admin
    app.dependency_overrides[current_superuser] = lambda: admin
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer test-dummy"},
        ) as ac:
            r = await ac.post(
                f"/api/app-submissions/{uuid.uuid4()}/advance",
                json={"to_stage": "approved"},
            )
        assert r.status_code == 409
        assert "bad jump" in r.json()["detail"]
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 3. Yank request — any authenticated user may file
# ---------------------------------------------------------------------------


async def test_yank_request_any_user_ok(monkeypatch):
    from app.database import get_db
    from app.main import app
    from app.services.apps import yanks as yanks_svc
    from app.users import current_active_user

    user = _make_user(superuser=False)
    mock_db = AsyncMock()

    async def _get_db():
        yield mock_db

    new_id = uuid.uuid4()

    async def _req(*a, **kw):
        return new_id

    monkeypatch.setattr(yanks_svc, "request_yank", _req)

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[current_active_user] = lambda: user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer test-dummy"},
        ) as ac:
            r = await ac.post(
                "/api/app-yanks/",
                json={
                    "app_version_id": str(uuid.uuid4()),
                    "severity": "low",
                    "reason": "broken",
                },
            )
        assert r.status_code == 200
        assert r.json()["yank_request_id"] == str(new_id)
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 4. Yank approve — NeedsSecondAdminError -> 409 with specific detail
# ---------------------------------------------------------------------------


async def test_yank_approve_409_needs_second_admin(monkeypatch):
    from app.database import get_db
    from app.main import app
    from app.services.apps import yanks as yanks_svc
    from app.users import current_active_user, current_superuser

    admin = _make_user(superuser=True)
    mock_db = AsyncMock()

    async def _get_db():
        yield mock_db

    async def _approve(*a, **kw):
        raise yanks_svc.NeedsSecondAdminError("same admin")

    monkeypatch.setattr(yanks_svc, "approve_yank", _approve)

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[current_active_user] = lambda: admin
    app.dependency_overrides[current_superuser] = lambda: admin
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer test-dummy"},
        ) as ac:
            r = await ac.post(f"/api/app-yanks/{uuid.uuid4()}/approve")
        assert r.status_code == 409
        assert r.json()["detail"] == "second admin required"
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 5. Yank appeal requires creator-owner (join AppVersion -> MarketplaceApp)
# ---------------------------------------------------------------------------


async def test_yank_appeal_requires_creator_owner():
    from app.database import get_db
    from app.main import app
    from app.users import current_active_user

    caller = _make_user(superuser=False)
    other_creator_id = uuid.uuid4()

    # Mock the creator-owner join: returns (YankRequest, creator_user_id)
    # where creator_user_id != caller.id.
    row = (MagicMock(), other_creator_id)
    first_result = MagicMock()
    first_result.first.return_value = row

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=first_result)

    async def _get_db():
        yield mock_db

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[current_active_user] = lambda: caller
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer test-dummy"},
        ) as ac:
            r = await ac.post(
                f"/api/app-yanks/{uuid.uuid4()}/appeal",
                json={"reason": "unfair"},
            )
        assert r.status_code == 403
        assert "creator" in r.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 6. Admin queue returns rows in order (mocked)
# ---------------------------------------------------------------------------


async def test_admin_queue_returns_sorted():
    from app.database import get_db
    from app.main import app
    from app.users import current_superuser

    admin = _make_user(superuser=True)

    from datetime import datetime

    now = datetime.now(tz=UTC)
    sid1, sid2 = uuid.uuid4(), uuid.uuid4()
    avid1, avid2 = uuid.uuid4(), uuid.uuid4()
    appid1, appid2 = uuid.uuid4(), uuid.uuid4()
    rows = [
        # (sub_id, av_id, stage, sla, stage_entered, app_id, version, name, cnt)
        (sid1, avid1, "stage1", now, now, appid1, "0.1", "Earliest", 2),
        (sid2, avid2, "stage2", now, now, appid2, "0.2", "Later", 0),
    ]
    exec_result = MagicMock()
    exec_result.all.return_value = rows
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=exec_result)

    async def _get_db():
        yield mock_db

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[current_superuser] = lambda: admin
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer test-dummy"},
        ) as ac:
            r = await ac.get("/api/admin-marketplace/queue")
        assert r.status_code == 200
        body = r.json()
        assert len(body["items"]) == 2
        assert body["items"][0]["submission_id"] == str(sid1)
        assert body["items"][0]["app_name"] == "Earliest"
        assert body["items"][0]["check_count"] == 2
        assert body["items"][1]["submission_id"] == str(sid2)
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 7. Admin stats — aggregates
# ---------------------------------------------------------------------------


async def test_admin_stats_aggregates():
    from app.database import get_db
    from app.main import app
    from app.users import current_superuser

    admin = _make_user(superuser=True)

    # Six scalar_one() counts in order: apps_total, apps_approved, apps_pending,
    # yanks_pending, submissions_in_flight, monitoring_runs_24h.
    values = [10, 4, 3, 2, 5, 7]
    calls = {"i": 0}

    def _next_result(*a, **kw):
        r = MagicMock()
        r.scalar_one.return_value = values[calls["i"]]
        calls["i"] += 1
        return r

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=_next_result)

    async def _get_db():
        yield mock_db

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[current_superuser] = lambda: admin
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer test-dummy"},
        ) as ac:
            r = await ac.get("/api/admin-marketplace/stats")
        assert r.status_code == 200
        body = r.json()
        assert body == {
            "apps_total": 10,
            "apps_approved": 4,
            "apps_pending": 3,
            "yanks_pending": 2,
            "submissions_in_flight": 5,
            "monitoring_runs_24h": 7,
        }
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 8. Scan endpoints — stage preconditions + superuser gate
# ---------------------------------------------------------------------------


async def _run_scan_test(
    *,
    endpoint: str,
    current_stage: str | None,
    expected_status: int,
    superuser: bool = True,
    stub_scanner: bool = False,
    monkeypatch=None,
):
    """Shared driver for stage1/stage2 scan endpoint tests."""
    from app.database import get_db
    from app.main import app
    from app.users import current_active_user, current_superuser

    user = _make_user(superuser=superuser)
    sub_id = uuid.uuid4()

    call_count = {"i": 0}

    def _execute_side_effect(*_a, **_kw):
        """First call = stage precondition query; later calls = scanner internals
        (ignored — scanner is monkey-patched when stub_scanner=True)."""
        call_count["i"] += 1
        r = MagicMock()
        if call_count["i"] == 1:
            r.scalar_one_or_none.return_value = current_stage
        else:
            r.scalar_one_or_none.return_value = None
        return r

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=_execute_side_effect)
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

    async def _get_db():
        yield mock_db

    if stub_scanner and monkeypatch is not None:
        from app.services.apps import stage1_scanner as s1
        from app.services.apps import stage2_sandbox as s2

        async def _ok_s1(_db, *, submission_id):
            return {"checks_run": 5, "failures": [], "advanced_to": "stage2"}

        async def _ok_s2(_db, *, submission_id):
            return {"advanced_to": "stage3", "suite_id": None, "score": None}

        monkeypatch.setattr(s1, "run_stage1_scan", _ok_s1)
        monkeypatch.setattr(s2, "run_stage2_eval", _ok_s2)

        # Post-scan detail fetch: return a SubmissionDetailOut-shaped row.
        class _Row:
            id = sub_id
            app_version_id = uuid.uuid4()
            submitter_user_id = None
            stage = "stage2" if endpoint.endswith("stage1") else "stage3"
            decision = "pending"
            reviewer_user_id = None
            decision_notes = None
            checks: list = []

        # Overwrite so the post-commit detail re-read returns this row.
        second = MagicMock()
        second.scalar_one_or_none.return_value = _Row()

        def _execute_with_detail(*_a, **_kw):
            call_count["i"] += 1
            r = MagicMock()
            if call_count["i"] == 1:
                r.scalar_one_or_none.return_value = current_stage
                return r
            return second

        mock_db.execute = AsyncMock(side_effect=_execute_with_detail)

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[current_active_user] = lambda: user
    if superuser:
        app.dependency_overrides[current_superuser] = lambda: user
    else:
        from fastapi import HTTPException

        def _forbid():
            raise HTTPException(status_code=403, detail="forbidden")

        app.dependency_overrides[current_superuser] = _forbid

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer test-dummy"},
        ) as ac:
            r = await ac.post(f"/api/app-submissions/{sub_id}{endpoint}")
        assert r.status_code == expected_status, r.text
    finally:
        app.dependency_overrides.clear()


async def test_run_stage1_scan_requires_admin():
    await _run_scan_test(
        endpoint="/scan/stage1",
        current_stage="stage1",
        expected_status=403,
        superuser=False,
    )


async def test_run_stage1_scan_rejects_wrong_stage():
    await _run_scan_test(
        endpoint="/scan/stage1",
        current_stage="stage0",
        expected_status=409,
    )


async def test_run_stage1_scan_404_when_missing():
    await _run_scan_test(
        endpoint="/scan/stage1",
        current_stage=None,
        expected_status=404,
    )


async def test_run_stage1_scan_ok_at_stage1(monkeypatch):
    await _run_scan_test(
        endpoint="/scan/stage1",
        current_stage="stage1",
        expected_status=200,
        stub_scanner=True,
        monkeypatch=monkeypatch,
    )


async def test_run_stage2_eval_rejects_wrong_stage():
    await _run_scan_test(
        endpoint="/scan/stage2",
        current_stage="stage1",
        expected_status=409,
    )


async def test_run_stage2_eval_ok_at_stage2(monkeypatch):
    await _run_scan_test(
        endpoint="/scan/stage2",
        current_stage="stage2",
        expected_status=200,
        stub_scanner=True,
        monkeypatch=monkeypatch,
    )
