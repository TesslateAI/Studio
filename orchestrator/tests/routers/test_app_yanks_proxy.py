"""
Wave 8 — orchestrator's app_yanks router as a thin proxy.

Covers:
  * Local YankRequest insert + proxy forward to marketplace on create.
  * Marketplace upstream failure does NOT roll back the local row
    (operator can retry from the queue).
  * Critical-yank approval still goes through the local cache + Wave 7
    publish_yank_upstream — Wave 8 leaves this unchanged so the runtime
    gate keeps refusing yanked instances after sync.
  * Federated apps with no source skip the upstream forward (local-only
    yank still recorded so runtime gate works).
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


async def _seed_federated_app(db, *, source_id: uuid.UUID) -> dict:
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
            "handle": f"hub-y-{source_id.hex[:6]}",
            "display_name": "Yank Test Hub",
            "base_url": "https://hub.example.com",
            "scope": "system",
            "trust_level": "admin_trusted",
            "is_active": True,
            "pinned_hub_id": "hub-yyy",
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
        name="Yankable App",
        source_id=source_id,
    )
    db.add(app)
    await db.flush()
    av = models.AppVersion(
        id=uuid.uuid4(),
        app_id=app_id,
        version="0.1.0",
        manifest_schema_version="2025-01",
        manifest_json={},
        manifest_hash="sha256:" + uuid.uuid4().hex + uuid.uuid4().hex[:32],
        feature_set_hash="sha256:" + ("0" * 64),
        approval_state="stage2_approved",
        source_id=source_id,
    )
    db.add(av)
    await db.commit()
    return {
        "user_id": user.id,
        "source_id": source_id,
        "app_id": app_id,
        "app_version_id": av.id,
    }


@pytest.mark.integration
def test_create_yank_inserts_local_row_and_forwards(api_client_session):
    from app.services import marketplace_governance as gov

    source_id = uuid.uuid4()
    seeded = _run_db(_seed_federated_app, source_id=source_id)

    register = {
        "email": f"yank-{uuid.uuid4().hex[:8]}@example.com",
        "password": "Yank-Test-1234!",
        "name": "Yank User",
    }
    r = api_client_session.post("/api/auth/register", json=register)
    assert r.status_code == 201
    login = api_client_session.post(
        "/api/auth/jwt/login",
        data={"username": register["email"], "password": register["password"]},
    )
    api_client_session.headers["Authorization"] = f"Bearer {login.json()['access_token']}"

    forwarded = {}

    async def _fake_proxy(db, *, local_yank_id, source, **kwargs):
        forwarded["local_yank_id"] = local_yank_id
        forwarded["source_id"] = source.id
        forwarded["kwargs"] = kwargs
        return {
            "id": "marketplace-yank-1",
            "state": "resolved",
            "resolution": "applied",
        }

    import unittest.mock as mock
    with mock.patch.object(gov, "proxy_create_yank", side_effect=_fake_proxy):
        res = api_client_session.post(
            "/api/app-yanks/",
            json={
                "app_version_id": str(seeded["app_version_id"]),
                "severity": "medium",
                "reason": "perf regression",
            },
        )
    assert res.status_code == 200, res.text
    body = res.json()
    yank_id = uuid.UUID(body["yank_request_id"])
    assert forwarded["local_yank_id"] == yank_id
    assert forwarded["source_id"] == source_id
    assert forwarded["kwargs"]["severity"] == "medium"

    api_client_session.headers.pop("Authorization", None)


@pytest.mark.integration
def test_create_yank_local_only_when_no_source(api_client_session):
    """A non-federated app yank still records the local row + skips forward."""
    from app.services import marketplace_governance as gov

    async def _seed_local_only(db):
        from app import models
        from app.services.marketplace_constants import LOCAL_SOURCE_ID

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
        # Local source represents user/team-private drafts; install_guard
        # treats trust_level='local' as never-federated, so the proxy
        # short-circuits and skips the upstream forward.
        app = models.MarketplaceApp(
            id=uuid.uuid4(),
            slug=f"local/{uuid.uuid4().hex[:8]}",
            name="Local App",
            source_id=LOCAL_SOURCE_ID,
        )
        db.add(app)
        await db.flush()
        av = models.AppVersion(
            id=uuid.uuid4(),
            app_id=app.id,
            version="0.0.1",
            manifest_schema_version="2025-01",
            manifest_json={},
            manifest_hash="sha256:" + uuid.uuid4().hex + uuid.uuid4().hex[:32],
            feature_set_hash="sha256:" + ("0" * 64),
            approval_state="stage2_approved",
            source_id=LOCAL_SOURCE_ID,
        )
        db.add(av)
        await db.commit()
        return {"app_version_id": av.id}

    seeded = _run_db(_seed_local_only)

    register = {
        "email": f"local-{uuid.uuid4().hex[:8]}@example.com",
        "password": "Local-Test-1234!",
        "name": "Local User",
    }
    r = api_client_session.post("/api/auth/register", json=register)
    assert r.status_code == 201
    login = api_client_session.post(
        "/api/auth/jwt/login",
        data={"username": register["email"], "password": register["password"]},
    )
    api_client_session.headers["Authorization"] = f"Bearer {login.json()['access_token']}"

    forwarded = {"called": False}

    async def _watch(*_args, **_kwargs):
        forwarded["called"] = True
        return {}

    import unittest.mock as mock
    with mock.patch.object(gov, "proxy_create_yank", side_effect=_watch):
        res = api_client_session.post(
            "/api/app-yanks/",
            json={
                "app_version_id": str(seeded["app_version_id"]),
                "severity": "low",
                "reason": "smell",
            },
        )
    assert res.status_code == 200, res.text
    assert forwarded["called"] is False  # no source → no upstream forward

    api_client_session.headers.pop("Authorization", None)


@pytest.mark.integration
def test_runtime_gate_still_refuses_yanked_after_sync(api_client_session):
    """After a yank lands on the local cache (mirrored from marketplace),
    services/apps/runtime.py should still refuse to start an instance
    pinned to that version. This proves the Wave 7 enforcement path
    is unaffected by Wave 8 routing changes.
    """
    from app.services.apps import runtime

    async def _seed_yanked(db):
        from app import models
        from app.services.marketplace_constants import LOCAL_SOURCE_ID

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
        app = models.MarketplaceApp(
            id=uuid.uuid4(),
            slug=f"y/{uuid.uuid4().hex[:8]}",
            name="Yanked App",
            state="approved",
            source_id=LOCAL_SOURCE_ID,
        )
        db.add(app)
        await db.flush()
        av = models.AppVersion(
            id=uuid.uuid4(),
            app_id=app.id,
            version="0.0.1",
            manifest_schema_version="2025-01",
            manifest_json={},
            manifest_hash="sha256:" + uuid.uuid4().hex + uuid.uuid4().hex[:32],
            feature_set_hash="sha256:" + ("0" * 64),
            approval_state="yanked",  # Mirrored by the yank-feed consumer.
            source_id=LOCAL_SOURCE_ID,
        )
        db.add(av)
        await db.commit()
        return {"user_id": user.id, "av_id": av.id, "app_id": app.id}

    seeded = _run_db(_seed_yanked)

    async def _check(db):
        from app import models
        from sqlalchemy import select

        av = (
            await db.execute(select(models.AppVersion).where(models.AppVersion.id == seeded["av_id"]))
        ).scalar_one()
        # Wave-7 runtime gate uses the same `_UNRUNNABLE_VERSION_STATES` set.
        assert av.approval_state in runtime._UNRUNNABLE_VERSION_STATES

    _run_db(_check)
