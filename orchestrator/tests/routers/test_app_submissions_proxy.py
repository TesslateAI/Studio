"""
Wave 8 — orchestrator's app_submissions router as a thin proxy.

The router's reads continue to serve the local cache; mutating endpoints
forward to the marketplace via ``marketplace_governance`` and mirror the
authoritative response back into the local cache.

These tests stub out the marketplace HTTP round-trip by patching
``marketplace_governance.proxy_advance_submission`` /
``proxy_finalize_submission`` and assert:
  * The router calls the proxy with the right ids + source.
  * The local cache row reflects the marketplace's mirrored state after
    a successful round-trip.
  * Marketplace 5xx / auth errors propagate cleanly with 502/503.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


_ASYNC_DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://tesslate_test:testpass@localhost:5433/tesslate_test",
)


def _run_db(coro_fn, *args, **kwargs):
    async def _inner():
        engine = create_async_engine(_ASYNC_DB_URL, pool_pre_ping=False)
        try:
            session_maker = async_sessionmaker(engine, expire_on_commit=False)
            async with session_maker() as db:
                return await coro_fn(db, *args, **kwargs)
        finally:
            await engine.dispose()

    return asyncio.run(_inner())


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------


async def _seed_federated_submission(db, *, source_id: uuid.UUID) -> dict:
    """Create user + source + app + version + submission rows.

    Returns dict with ids so the test can call routes against them.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app import models

    ux = uuid.uuid4().hex[:8]
    user = models.User(
        id=uuid.uuid4(),
        username=f"u-{ux}",
        name=f"User {ux}",
        slug=f"user-{ux}",
        email=f"{ux}@example.com",
        hashed_password="x",
    )
    db.add(user)
    await db.flush()

    src_stmt = pg_insert(models.MarketplaceSource).values(
        {
            "id": source_id,
            "handle": f"hub-{source_id.hex[:6]}",
            "display_name": "Test Hub",
            "base_url": "https://hub.example.com",
            "scope": "system",
            "trust_level": "admin_trusted",
            "is_active": True,
            "pinned_hub_id": "hub-x",
        }
    ).on_conflict_do_update(
        index_elements=[models.MarketplaceSource.id],
        set_={"is_active": True},
    )
    await db.execute(src_stmt)

    app_id = uuid.uuid4()
    app = models.MarketplaceApp(
        id=app_id,
        slug=f"hub/{uuid.uuid4().hex[:8]}",
        name="Federated App",
        source_id=source_id,
    )
    db.add(app)
    await db.flush()
    av = models.AppVersion(
        id=uuid.uuid4(),
        app_id=app_id,
        version="0.0.1",
        manifest_schema_version="2025-01",
        manifest_json={},
        manifest_hash="sha256:" + uuid.uuid4().hex + uuid.uuid4().hex[:32],
        feature_set_hash="sha256:" + ("0" * 64),
        approval_state="pending_stage1",
        source_id=source_id,
    )
    db.add(av)
    sub = models.AppSubmission(
        id=uuid.uuid4(),
        app_version_id=av.id,
        submitter_user_id=user.id,
        stage="stage1",
    )
    db.add(sub)
    await db.commit()

    return {
        "user_id": user.id,
        "source_id": source_id,
        "app_id": app_id,
        "app_version_id": av.id,
        "submission_id": sub.id,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_proxy_advance_routes_through_marketplace_and_mirrors(api_client_session):
    """Authenticated superuser advance forwards to marketplace + mirrors response."""
    from app.services import marketplace_governance as gov

    source_id = uuid.uuid4()
    seeded = _run_db(_seed_federated_submission, source_id=source_id)

    # Build a superuser-authenticated session by promoting our user.
    async def _promote(db):
        from app import models
        from sqlalchemy import update

        await db.execute(
            update(models.User)
            .where(models.User.id == seeded["user_id"])
            .values(is_superuser=True)
        )
        await db.commit()

    _run_db(_promote)

    # Mock the marketplace round-trip — also asserts mirror_submission_into_cache
    # is invoked with the response envelope.
    captured = {}

    async def _fake_proxy_advance(
        db, *, local_submission_id, upstream_submission_id, source, client_factory=None
    ):
        captured["called_with"] = {
            "local": local_submission_id,
            "upstream": upstream_submission_id,
            "source_id": source.id,
        }
        envelope = {
            "id": upstream_submission_id,
            "state": "stage2_dynamic",
            "stage": "stage2",
            "checks": [
                {"stage": "stage1", "name": "slug_format", "status": "passed", "details": {}},
            ],
        }
        await gov.mirror_submission_into_cache(
            db,
            local_submission_id=local_submission_id,
            marketplace_envelope=envelope,
        )
        return envelope

    # Authenticate via the standard JWT flow — we re-use authenticated_client's
    # registration code path.
    register = {
        "email": f"sup-{uuid.uuid4().hex[:8]}@example.com",
        "password": "Sup-Test-1234!",
        "name": "Sup",
    }
    r = api_client_session.post("/api/auth/register", json=register)
    assert r.status_code == 201
    su_id = r.json()["id"]

    async def _make_super(db):
        from app import models
        from sqlalchemy import update

        await db.execute(
            update(models.User).where(models.User.id == su_id).values(is_superuser=True)
        )
        await db.commit()

    _run_db(_make_super)

    login = api_client_session.post(
        "/api/auth/jwt/login",
        data={"username": register["email"], "password": register["password"]},
    )
    api_client_session.headers["Authorization"] = f"Bearer {login.json()['access_token']}"

    import unittest.mock as mock
    with mock.patch.object(gov, "proxy_advance_submission", side_effect=_fake_proxy_advance):
        res = api_client_session.post(
            f"/api/app-submissions/{seeded['submission_id']}/advance",
            json={},
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["stage"] == "stage2"
    assert captured["called_with"]["local"] == seeded["submission_id"]
    assert captured["called_with"]["source_id"] == source_id

    api_client_session.headers.pop("Authorization", None)


@pytest.mark.integration
def test_proxy_advance_returns_502_on_marketplace_5xx(api_client_session):
    """A MarketplaceServerError surfaces as 502 to the caller."""
    from app.services import marketplace_governance as gov
    from app.services.marketplace_client import MarketplaceServerError

    source_id = uuid.uuid4()
    seeded = _run_db(_seed_federated_submission, source_id=source_id)

    register = {
        "email": f"sup502-{uuid.uuid4().hex[:8]}@example.com",
        "password": "Sup-Test-1234!",
        "name": "Sup",
    }
    r = api_client_session.post("/api/auth/register", json=register)
    assert r.status_code == 201
    su_id = r.json()["id"]

    async def _make_super(db):
        from app import models
        from sqlalchemy import update

        await db.execute(
            update(models.User).where(models.User.id == su_id).values(is_superuser=True)
        )
        await db.commit()

    _run_db(_make_super)

    login = api_client_session.post(
        "/api/auth/jwt/login",
        data={"username": register["email"], "password": register["password"]},
    )
    api_client_session.headers["Authorization"] = f"Bearer {login.json()['access_token']}"

    async def _boom(*_args, **_kwargs):
        raise MarketplaceServerError("hub down", status_code=503)

    import unittest.mock as mock
    with mock.patch.object(gov, "proxy_advance_submission", side_effect=_boom):
        res = api_client_session.post(
            f"/api/app-submissions/{seeded['submission_id']}/advance",
            json={},
        )
    assert res.status_code == 502
    assert res.json()["detail"]["error"] == "marketplace_unavailable"

    api_client_session.headers.pop("Authorization", None)


@pytest.mark.integration
def test_proxy_advance_returns_503_when_admin_token_missing(api_client_session):
    """AdminTokenMissingError surfaces as 503 with operational message."""
    from app.services import marketplace_governance as gov

    source_id = uuid.uuid4()
    seeded = _run_db(_seed_federated_submission, source_id=source_id)

    register = {
        "email": f"sup503-{uuid.uuid4().hex[:8]}@example.com",
        "password": "Sup-Test-1234!",
        "name": "Sup",
    }
    r = api_client_session.post("/api/auth/register", json=register)
    assert r.status_code == 201
    su_id = r.json()["id"]

    async def _make_super(db):
        from app import models
        from sqlalchemy import update

        await db.execute(
            update(models.User).where(models.User.id == su_id).values(is_superuser=True)
        )
        await db.commit()

    _run_db(_make_super)

    login = api_client_session.post(
        "/api/auth/jwt/login",
        data={"username": register["email"], "password": register["password"]},
    )
    api_client_session.headers["Authorization"] = f"Bearer {login.json()['access_token']}"

    async def _missing_token(*_args, **_kwargs):
        raise gov.AdminTokenMissingError("admin token unset")

    import unittest.mock as mock
    with mock.patch.object(gov, "proxy_advance_submission", side_effect=_missing_token):
        res = api_client_session.post(
            f"/api/app-submissions/{seeded['submission_id']}/advance",
            json={},
        )
    assert res.status_code == 503
    assert res.json()["detail"]["error"] == "marketplace_admin_token_missing"

    api_client_session.headers.pop("Authorization", None)
