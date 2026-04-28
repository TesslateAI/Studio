"""Phase 5 — unit tests for ``app.routers.contract_templates``.

Hermetic FastAPI ``TestClient`` tests against a SQLite database upgraded
to alembic ``head`` — same fixture pattern as ``test_automations.py``.

Coverage:

* ``POST /api/contract-templates`` rejects empty / non-object contracts.
* ``POST /api/contract-templates`` round-trips a row owned by the
  current user.
* ``GET  /api/contract-templates`` only returns published templates for
  non-superusers, even if a draft row exists.
* ``GET  /api/contract-templates`` filters by category.
* ``POST /api/contract-templates/{id}/apply`` returns the contract dict
  ready for the AutomationCreatePage form to prefill.
* ``DELETE /api/contract-templates/{id}`` is owner-or-admin gated.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, insert as core_insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def _install_sqlite_now(engine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_conn, _record):  # noqa: ARG001 - SA event signature
        dbapi_conn.create_function(
            "now", 0, lambda: datetime.now(UTC).isoformat(sep=" ")
        )


def _alembic_cfg() -> Config:
    orchestrator_dir = Path(__file__).resolve().parents[2]
    cfg = Config(str(orchestrator_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(orchestrator_dir / "alembic"))
    return cfg


@pytest.fixture
def migrated_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    db_path = tmp_path / "contract_tpl.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DEPLOYMENT_MODE", "desktop")

    from app.config import get_settings

    get_settings.cache_clear()
    orchestrator_dir = Path(__file__).resolve().parents[2]
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


async def _seed_user(db, *, is_superuser: bool = False) -> uuid.UUID:
    from app.models_auth import User

    user_id = uuid.uuid4()
    suffix = uuid.uuid4().hex[:8]
    await db.execute(
        core_insert(User.__table__).values(
            id=user_id,
            email=f"tpl-{suffix}@example.com",
            hashed_password="x",
            is_active=True,
            is_superuser=is_superuser,
            is_verified=True,
            name="Template User",
            username=f"u{suffix}",
            slug=f"u-{suffix}",
        )
    )
    await db.flush()
    return user_id


@pytest.fixture
def app_client(session_maker):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.database import get_db
    from app.models_auth import User
    from app.routers import contract_templates as router_mod
    from app.users import current_active_user

    async def _seed():
        async with session_maker() as db:
            uid = await _seed_user(db)
            await db.commit()
            return uid

    owner_id = asyncio.run(_seed())

    app = FastAPI()
    app.include_router(router_mod.router)

    async def _override_db():
        async with session_maker() as db:
            yield db

    async def _override_user():
        return User(
            id=owner_id,
            email="tpl@example.com",
            hashed_password="",
            is_active=True,
            is_superuser=False,
            is_verified=True,
            name="Template User",
        )

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[current_active_user] = _override_user

    client = TestClient(app)
    yield client, owner_id, session_maker, app


def _good_payload() -> dict:
    return {
        "name": "Web Research",
        "description": "Lightweight research agent",
        "category": "research",
        "contract_json": {
            "allowed_tools": ["web_search", "web_fetch"],
            "max_compute_tier": 0,
            "max_spend_per_run_usd": 0.50,
        },
        "is_published": True,
    }


@pytest.mark.unit
def test_create_rejects_empty_contract(app_client) -> None:
    client, _, _, _ = app_client
    payload = _good_payload()
    payload["contract_json"] = {}
    resp = client.post("/api/contract-templates", json=payload)
    assert resp.status_code == 422, resp.text


@pytest.mark.unit
def test_create_rejects_non_object_contract(app_client) -> None:
    client, _, _, _ = app_client
    payload = _good_payload()
    payload["contract_json"] = ["not", "a", "dict"]  # type: ignore[assignment]
    resp = client.post("/api/contract-templates", json=payload)
    assert resp.status_code == 422


@pytest.mark.unit
def test_create_then_get(app_client) -> None:
    client, owner_id, _, _ = app_client
    resp = client.post("/api/contract-templates", json=_good_payload())
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "Web Research"
    assert body["category"] == "research"
    assert body["created_by_user_id"] == str(owner_id)

    fetched = client.get(f"/api/contract-templates/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["contract_json"]["allowed_tools"] == [
        "web_search",
        "web_fetch",
    ]


@pytest.mark.unit
def test_list_filters_unpublished_for_non_admin(app_client) -> None:
    client, _, _, _ = app_client
    pub = _good_payload()
    pub["name"] = "Pub"
    draft = _good_payload()
    draft["name"] = "Draft"
    draft["is_published"] = False
    client.post("/api/contract-templates", json=pub)
    client.post("/api/contract-templates", json=draft)

    listing = client.get("/api/contract-templates").json()
    names = {row["name"] for row in listing}
    assert "Pub" in names
    assert "Draft" not in names

    # include_unpublished=true is silently ignored for non-superusers.
    listing = client.get(
        "/api/contract-templates", params={"include_unpublished": "true"}
    ).json()
    names = {row["name"] for row in listing}
    assert "Draft" not in names


@pytest.mark.unit
def test_list_filters_by_category(app_client) -> None:
    client, _, _, _ = app_client
    a = _good_payload()
    a["name"] = "A"
    a["category"] = "research"
    b = _good_payload()
    b["name"] = "B"
    b["category"] = "coding"
    client.post("/api/contract-templates", json=a)
    client.post("/api/contract-templates", json=b)

    rows = client.get(
        "/api/contract-templates", params={"category": "coding"}
    ).json()
    assert {r["name"] for r in rows} == {"B"}


@pytest.mark.unit
def test_apply_returns_contract_dict(app_client) -> None:
    client, _, _, _ = app_client
    created = client.post("/api/contract-templates", json=_good_payload()).json()
    resp = client.post(f"/api/contract-templates/{created['id']}/apply")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["template_id"] == created["id"]
    assert body["template_name"] == "Web Research"
    assert body["contract"]["allowed_tools"] == ["web_search", "web_fetch"]


@pytest.mark.unit
def test_delete_owner_succeeds(app_client) -> None:
    client, _, _, _ = app_client
    created = client.post("/api/contract-templates", json=_good_payload()).json()
    resp = client.delete(f"/api/contract-templates/{created['id']}")
    assert resp.status_code == 204
    # Subsequent GET 404s.
    assert client.get(f"/api/contract-templates/{created['id']}").status_code == 404


@pytest.mark.unit
def test_delete_non_owner_forbidden(app_client) -> None:
    client, _, session_maker, app = app_client

    # Insert a template owned by a different user via the seeded session.
    async def _seed_other_template():
        async with session_maker() as db:
            other_id = await _seed_user(db)
            from app.models import ContractTemplate

            tpl = ContractTemplate(
                name="OtherOwned",
                description="not yours",
                category="general",
                contract_json={"allowed_tools": []},
                created_by_user_id=other_id,
                is_published=True,
            )
            db.add(tpl)
            await db.commit()
            return tpl.id

    tpl_id = asyncio.run(_seed_other_template())
    resp = client.delete(f"/api/contract-templates/{tpl_id}")
    assert resp.status_code == 403
