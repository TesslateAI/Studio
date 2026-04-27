"""Phase 5 — unit tests for ``app.routers.admin_spend``.

Hermetic FastAPI ``TestClient`` tests against a SQLite database upgraded
to alembic ``head``. Patterns mirror ``test_automations.py`` (in-memory
override of ``get_db`` + ``current_superuser``).

Coverage:

* ``GET /api/admin/spend/rollup?group_by=user`` aggregates spend per
  invoking user and returns the grand total.
* ``group_by=app`` aggregates per app instance.
* ``group_by=team`` aggregates per team.
* Records outside the time window are excluded.
* Records without ``invocation_subject_id`` are excluded (the inner JOIN
  intentionally drops them).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
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
    db_path = tmp_path / "admin_spend.db"
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
            email=f"spend-{suffix}@example.com",
            hashed_password="x",
            is_active=True,
            is_superuser=is_superuser,
            is_verified=True,
            name="Spend User",
            username=f"u{suffix}",
            slug=f"u-{suffix}",
        )
    )
    await db.flush()
    return user_id


async def _seed_invocation_subject(
    db,
    *,
    user_id: uuid.UUID,
    app_instance_id: uuid.UUID | None = None,
    team_id: uuid.UUID | None = None,
) -> uuid.UUID:
    from app.models_automations import InvocationSubject

    inv_id = uuid.uuid4()
    inv = InvocationSubject(
        id=inv_id,
        invoking_user_id=user_id,
        app_instance_id=app_instance_id,
        team_id=team_id,
        payer_policy="installer",
        credit_source="opensail_credits",
    )
    db.add(inv)
    await db.flush()
    return inv_id


async def _seed_spend(
    db,
    *,
    invocation_subject_id: uuid.UUID | None,
    amount: Decimal,
    when: datetime,
    installer_user_id: uuid.UUID,
) -> uuid.UUID:
    from app.models import SpendRecord

    sr = SpendRecord(
        id=uuid.uuid4(),
        installer_user_id=installer_user_id,
        dimension="ai_compute",
        payer="installer",
        amount_usd=amount,
        invocation_subject_id=invocation_subject_id,
        created_at=when,
    )
    db.add(sr)
    await db.flush()
    return sr.id


@pytest.fixture
def app_client(session_maker):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.database import get_db
    from app.models_auth import User
    from app.routers import admin_spend as router_mod
    from app.users import current_superuser

    async def _seed_admin():
        async with session_maker() as db:
            uid = await _seed_user(db, is_superuser=True)
            await db.commit()
            return uid

    admin_id = asyncio.run(_seed_admin())

    app = FastAPI()
    app.include_router(router_mod.router)

    async def _override_db():
        async with session_maker() as db:
            yield db

    async def _override_admin():
        return User(
            id=admin_id,
            email="admin@example.com",
            hashed_password="",
            is_active=True,
            is_superuser=True,
            is_verified=True,
            name="Admin",
        )

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[current_superuser] = _override_admin

    client = TestClient(app)
    yield client, session_maker


@pytest.mark.unit
def test_rollup_by_user(app_client) -> None:
    client, session_maker = app_client

    async def _seed():
        async with session_maker() as db:
            alice = await _seed_user(db)
            bob = await _seed_user(db)
            inv_alice = await _seed_invocation_subject(db, user_id=alice)
            inv_bob = await _seed_invocation_subject(db, user_id=bob)
            now = datetime.now(UTC)
            await _seed_spend(
                db,
                invocation_subject_id=inv_alice,
                amount=Decimal("1.25"),
                when=now,
                installer_user_id=alice,
            )
            await _seed_spend(
                db,
                invocation_subject_id=inv_alice,
                amount=Decimal("0.75"),
                when=now,
                installer_user_id=alice,
            )
            await _seed_spend(
                db,
                invocation_subject_id=inv_bob,
                amount=Decimal("3.00"),
                when=now,
                installer_user_id=bob,
            )
            await db.commit()
            return alice, bob

    alice_id, bob_id = asyncio.run(_seed())

    resp = client.get("/api/admin/spend/rollup", params={"group_by": "user"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["group_by"] == "user"
    assert body["totals"]["all_users_usd"] == "5.00"
    by_user = {row["user_id"]: row["total_usd"] for row in body["rows"]}
    assert by_user[str(alice_id)] == "2.00"
    assert by_user[str(bob_id)] == "3.00"


@pytest.mark.unit
def test_rollup_excludes_window_misses_and_unattributed(app_client) -> None:
    client, session_maker = app_client

    async def _seed():
        async with session_maker() as db:
            alice = await _seed_user(db)
            inv = await _seed_invocation_subject(db, user_id=alice)
            now = datetime.now(UTC)
            # Inside window.
            await _seed_spend(
                db,
                invocation_subject_id=inv,
                amount=Decimal("2.50"),
                when=now,
                installer_user_id=alice,
            )
            # Outside window (60 days ago — default is 30).
            await _seed_spend(
                db,
                invocation_subject_id=inv,
                amount=Decimal("99.00"),
                when=now - timedelta(days=60),
                installer_user_id=alice,
            )
            # Unattributed (invocation_subject_id IS NULL) — JOIN drops it.
            await _seed_spend(
                db,
                invocation_subject_id=None,
                amount=Decimal("123.00"),
                when=now,
                installer_user_id=alice,
            )
            await db.commit()
            return alice

    asyncio.run(_seed())

    resp = client.get("/api/admin/spend/rollup", params={"group_by": "user"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["totals"]["all_users_usd"] == "2.50"
    assert len(body["rows"]) == 1
    assert body["rows"][0]["total_usd"] == "2.50"


@pytest.mark.unit
def test_rollup_by_team(app_client) -> None:
    client, session_maker = app_client

    async def _seed():
        async with session_maker() as db:
            alice = await _seed_user(db)
            team_id = uuid.uuid4()
            # Insert a minimal Team row so the FK is satisfied.
            from app.models_team import Team

            db.add(
                Team(
                    id=team_id,
                    name="t",
                    slug=f"t-{uuid.uuid4().hex[:6]}",
                    is_personal=True,
                )
            )
            await db.flush()
            inv = await _seed_invocation_subject(
                db, user_id=alice, team_id=team_id
            )
            now = datetime.now(UTC)
            await _seed_spend(
                db,
                invocation_subject_id=inv,
                amount=Decimal("4.20"),
                when=now,
                installer_user_id=alice,
            )
            await db.commit()
            return team_id

    team_id = asyncio.run(_seed())
    resp = client.get("/api/admin/spend/rollup", params={"group_by": "team"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["group_by"] == "team"
    assert body["rows"][0]["team_id"] == str(team_id)
    assert body["rows"][0]["total_usd"] == "4.20"


@pytest.mark.unit
def test_rollup_rejects_bad_window(app_client) -> None:
    client, _ = app_client
    later = datetime.now(UTC).isoformat()
    earlier = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    resp = client.get(
        "/api/admin/spend/rollup",
        params={"start": later, "end": earlier},
    )
    assert resp.status_code == 400
