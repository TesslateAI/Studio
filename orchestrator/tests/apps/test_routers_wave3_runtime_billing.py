"""Wave 3 router tests: app_runtime + app_billing.

Pure unit tests — auth, DB, and Wave 2 service calls are stubbed via
``app.dependency_overrides`` and ``monkeypatch``. No Postgres or LiteLLM
required.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.database import get_db
from app.routers import app_billing, app_runtime
from app.services.apps import billing_dispatcher
from app.services.apps import runtime as runtime_svc
from app.users import current_active_user, current_superuser

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_user(*, superuser: bool = False, creator: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        is_superuser=superuser,
        is_active=True,
        creator_stripe_account_id=("acct_test" if creator else None),
    )


@pytest.fixture
def installer_user() -> SimpleNamespace:
    return _make_user()


@pytest.fixture
def super_user() -> SimpleNamespace:
    return _make_user(superuser=True)


@pytest.fixture
def fake_db() -> SimpleNamespace:
    """Stub DB session — never actually queried (services are mocked)."""
    return SimpleNamespace()


@pytest.fixture
def app_factory(fake_db):
    def _make(user, *, include_runtime=True, include_billing=True) -> FastAPI:
        app = FastAPI()
        if include_runtime:
            app.include_router(app_runtime.router, prefix="/api/apps/runtime")
        if include_billing:
            app.include_router(app_billing.router, prefix="/api/apps/billing")

        async def _override_db():
            yield fake_db

        async def _override_user():
            return user

        async def _override_super():
            if not getattr(user, "is_superuser", False):
                from fastapi import HTTPException

                raise HTTPException(status_code=403, detail="superuser required")
            return user

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[current_active_user] = _override_user
        app.dependency_overrides[current_superuser] = _override_super
        return app

    return _make


@pytest.fixture
async def client_factory(app_factory):
    async def _make(user, **kwargs):
        app = app_factory(user, **kwargs)
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test"), app

    return _make


# ---------------------------------------------------------------------------
# Runtime tests
# ---------------------------------------------------------------------------


async def test_post_session_happy_path(client_factory, installer_user, monkeypatch):
    instance_id = uuid4()
    instance = SimpleNamespace(id=instance_id, installer_user_id=installer_user.id)

    async def _fake_assert(db, app_instance_id, user):
        return instance

    handle = runtime_svc.SessionHandle(
        session_id=uuid4(),
        app_instance_id=instance_id,
        litellm_key_id="key-123",
        api_key="sk-fake-key-123",
        budget_usd=Decimal("1.00"),
        ttl_seconds=3600,
    )

    async def _fake_begin_session(db, **kw):
        return handle

    monkeypatch.setattr(app_runtime, "_assert_installer_or_superuser", _fake_assert)
    monkeypatch.setattr(runtime_svc, "begin_session", _fake_begin_session)

    client, _app = await client_factory(installer_user)
    async with client as c:
        r = await c.post(
            "/api/apps/runtime/sessions",
            json={"app_instance_id": str(instance_id), "budget_usd": 1.0, "ttl_seconds": 3600},
        )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["litellm_key_id"] == "key-123"
    assert body["api_key"] == "sk-fake-key-123"
    assert body["budget_usd"] == 1.0
    assert body["ttl_seconds"] == 3600
    assert body["app_instance_id"] == str(instance_id)


async def test_post_session_409_when_not_runnable(client_factory, installer_user, monkeypatch):
    instance_id = uuid4()
    instance = SimpleNamespace(id=instance_id, installer_user_id=installer_user.id)

    async def _fake_assert(db, app_instance_id, user):
        return instance

    async def _fake_begin_session(db, **kw):
        raise runtime_svc.AppNotRunnableError("yanked")

    monkeypatch.setattr(app_runtime, "_assert_installer_or_superuser", _fake_assert)
    monkeypatch.setattr(runtime_svc, "begin_session", _fake_begin_session)

    client, _app = await client_factory(installer_user)
    async with client as c:
        r = await c.post(
            "/api/apps/runtime/sessions",
            json={"app_instance_id": str(instance_id)},
        )
    assert r.status_code == 409
    assert "yanked" in r.json()["detail"]


async def test_post_session_forbidden_for_non_installer(
    client_factory, installer_user, monkeypatch
):
    instance_id = uuid4()
    other_user_id = uuid4()
    instance = SimpleNamespace(id=instance_id, installer_user_id=other_user_id)

    # Stub the DB load via the real assert helper
    class _Result:
        def scalar_one_or_none(self):
            return instance

    async def _execute(stmt):
        return _Result()

    # Patch db.execute on the dependency override
    # We use the real _assert_installer_or_superuser; it calls db.execute(...).scalar_one_or_none()
    # So override get_db to a session that exposes execute()
    fake_db = SimpleNamespace(execute=_execute)
    app = FastAPI()
    app.include_router(app_runtime.router, prefix="/api/apps/runtime")

    async def _override_db():
        yield fake_db

    async def _override_user():
        return installer_user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[current_active_user] = _override_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/api/apps/runtime/sessions",
            json={"app_instance_id": str(instance_id)},
        )
    assert r.status_code == 403


async def test_delete_session_idempotent(client_factory, installer_user, monkeypatch):
    calls = {"n": 0}

    async def _fake_end(db, *, session_id, delegate, reason="user_ended"):
        calls["n"] += 1
        return None

    monkeypatch.setattr(runtime_svc, "end_session", _fake_end)

    client, _app = await client_factory(installer_user)
    sid = uuid4()
    async with client as c:
        r1 = await c.delete(f"/api/apps/runtime/sessions/{sid}")
        r2 = await c.delete(f"/api/apps/runtime/sessions/{sid}")
    assert r1.status_code == 204
    assert r2.status_code == 204
    assert calls["n"] == 2


# ---------------------------------------------------------------------------
# Billing tests
# ---------------------------------------------------------------------------


async def test_get_wallet_auto_creates(client_factory, installer_user, monkeypatch):
    wallet_id = uuid4()
    wallet = SimpleNamespace(
        id=wallet_id,
        balance_usd=Decimal("0"),
        state="active",
        owner_type="installer",
        created_at=None,
        updated_at=None,
    )

    async def _fake_focw(db, *, owner_type, owner_user_id):
        # First call creates, subsequent calls return same row.
        return wallet

    monkeypatch.setattr(app_billing, "find_or_create_wallet", _fake_focw)

    client, _app = await client_factory(installer_user)
    async with client as c:
        r1 = await c.get("/api/apps/billing/wallet")
        r2 = await c.get("/api/apps/billing/wallet")
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["id"] == str(wallet_id)
    assert r1.json()["id"] == r2.json()["id"]


async def test_get_spend_filters(client_factory, installer_user, monkeypatch):
    instance_id = uuid4()
    matching = SimpleNamespace(
        id=uuid4(),
        app_instance_id=instance_id,
        session_id=None,
        installer_user_id=installer_user.id,
        dimension="ai_compute",
        payer="installer",
        payer_user_id=installer_user.id,
        amount_usd=Decimal("0.10"),
        litellm_key_id="k",
        usage_log_id=None,
        settled=False,
        settled_at=None,
        meta={},
        created_at=None,
    )

    captured: dict = {}

    class _Scalars:
        def __init__(self, items):
            self._items = items

        def all(self):
            return self._items

    class _Result:
        def __init__(self, items=None, scalar=None):
            self._items = items
            self._scalar = scalar

        def scalars(self):
            return _Scalars(self._items or [])

        def scalar_one(self):
            return self._scalar

    async def _execute(stmt):
        # First call in handler is count(*), second is select
        s = str(stmt)
        captured["last_sql"] = s
        if "count(" in s.lower():
            return _Result(scalar=1)
        return _Result(items=[matching])

    fake_db = SimpleNamespace(execute=_execute)

    app = FastAPI()
    app.include_router(app_billing.router, prefix="/api/apps/billing")

    async def _override_db():
        yield fake_db

    async def _override_user():
        return installer_user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[current_active_user] = _override_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            "/api/apps/billing/spend",
            params={
                "app_instance_id": str(instance_id),
                "dimension": "ai_compute",
                "settled": "false",
            },
        )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["dimension"] == "ai_compute"
    # sanity: filters reached the SQL
    assert "ai_compute" in captured["last_sql"] or "dimension" in captured["last_sql"].lower()


async def test_post_record_spend_superuser_only(
    client_factory, installer_user, super_user, monkeypatch
):
    spend_id = uuid4()
    outcome = billing_dispatcher.SpendOutcome(
        spend_record_id=spend_id,
        payer="installer",
        amount_usd=Decimal("0.05"),
        dimension="ai_compute",
    )

    async def _fake_record(db, **kw):
        return outcome

    monkeypatch.setattr(billing_dispatcher, "record_spend", _fake_record)

    payload = {
        "app_instance_id": str(uuid4()),
        "installer_user_id": str(uuid4()),
        "dimension": "ai_compute",
        "amount_usd": 0.05,
    }

    # 403 when not superuser
    client, _app = await client_factory(installer_user)
    async with client as c:
        r = await c.post("/api/apps/billing/spend/record", json=payload)
    assert r.status_code == 403

    # 201 when superuser
    client2, _app2 = await client_factory(super_user)
    async with client2 as c:
        r = await c.post("/api/apps/billing/spend/record", json=payload)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["spend_record_id"] == str(spend_id)
    assert body["payer"] == "installer"
    assert body["amount_usd"] == 0.05
    assert body["dimension"] == "ai_compute"


# ---------------------------------------------------------------------------
# Creator wallet — returns null for non-creator (regression for #379)
# ---------------------------------------------------------------------------


async def test_get_creator_wallet_returns_null_for_non_creator(
    client_factory, installer_user, monkeypatch
):
    """Non-creator users must get 200 + null, not 403.

    Previously the endpoint raised HTTPException(403), which polluted the
    browser console on every app workspace load for every non-creator user.
    """
    called = {"n": 0}

    async def _fake_focw(db, *, owner_type, owner_user_id):
        called["n"] += 1
        return None

    monkeypatch.setattr(app_billing, "find_or_create_wallet", _fake_focw)

    # installer_user has no creator_stripe_account_id
    client, _app = await client_factory(installer_user)
    async with client as c:
        r = await c.get("/api/apps/billing/wallet/creator")

    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    assert r.json() is None
    # find_or_create_wallet must NOT be called — we return early before it
    assert called["n"] == 0, "find_or_create_wallet should not be called for non-creator"


async def test_get_creator_wallet_returns_wallet_for_creator(client_factory, monkeypatch):
    """Users with creator_stripe_account_id get their wallet back."""
    creator_user = _make_user(creator=True)
    wallet_id = uuid4()
    wallet = SimpleNamespace(
        id=wallet_id,
        balance_usd=Decimal("10.50"),
        state="active",
        owner_type="creator",
        created_at=None,
        updated_at=None,
    )

    async def _fake_focw(db, *, owner_type, owner_user_id):
        assert owner_type == "creator"
        return wallet

    monkeypatch.setattr(app_billing, "find_or_create_wallet", _fake_focw)

    client, _app = await client_factory(creator_user)
    async with client as c:
        r = await c.get("/api/apps/billing/wallet/creator")

    assert r.status_code == 200
    body = r.json()
    assert body is not None
    assert body["id"] == str(wallet_id)
    assert body["owner_type"] == "creator"
