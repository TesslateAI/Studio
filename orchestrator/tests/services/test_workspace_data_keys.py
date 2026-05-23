"""Tests for Workspace Data API key management — service layer + agent tool.

Covers create/list/get/revoke, resolve-by-raw, the deploy-key rotation used
by deploy-time injection, quota/validation, and the agent tool's
``list_keys`` / ``create_key`` / ``revoke_key`` actions.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def _alembic_cfg() -> Config:
    orchestrator_dir = Path(__file__).resolve().parents[2]
    cfg = Config(str(orchestrator_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(orchestrator_dir / "alembic"))
    return cfg


@pytest.fixture
def maker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    url = f"sqlite+aiosqlite:///{tmp_path / 'wsdata-keys.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    from app.config import get_settings

    get_settings.cache_clear()
    orchestrator_dir = Path(__file__).resolve().parents[2]
    original = os.getcwd()
    os.chdir(orchestrator_dir)
    try:
        command.upgrade(_alembic_cfg(), "head")
    finally:
        os.chdir(original)
    engine = create_async_engine(url, future=True)

    @event.listens_for(engine.sync_engine, "connect")
    def _now(dbapi_conn, _record):
        dbapi_conn.create_function("now", 0, lambda: datetime.now(UTC).isoformat(sep=" "))

    yield async_sessionmaker(engine, expire_on_commit=False)
    get_settings.cache_clear()


# --- Key service ------------------------------------------------------------
async def test_create_list_get_revoke_keys(maker) -> None:
    from app.services import workspace_data as wd

    pid = uuid.uuid4()
    async with maker() as db:
        anon, anon_raw = await wd.create_data_key(db, pid, "browser", "anon")
        svc, svc_raw = await wd.create_data_key(db, pid, "server", "service")
        assert anon.kind == "anon" and anon_raw.startswith("wsk_anon_")
        assert svc.kind == "service" and svc_raw.startswith("wsk_svc_")
        assert anon.key_prefix == anon_raw[:20]

        keys = await wd.list_data_keys(db, pid)
        assert {k.name for k in keys} == {"browser", "server"}

        got = await wd.get_data_key(db, pid, anon.id)
        assert got is not None and got.id == anon.id
        # Wrong project scope -> not found.
        assert await wd.get_data_key(db, uuid.uuid4(), anon.id) is None

        assert await wd.revoke_data_key(db, pid, anon.id) is True
        assert await wd.revoke_data_key(db, pid, anon.id) is False  # already gone
        assert {k.name for k in await wd.list_data_keys(db, pid)} == {"server"}


async def test_key_validation(maker) -> None:
    from app.services import workspace_data as wd

    pid = uuid.uuid4()
    async with maker() as db:
        with pytest.raises(wd.InvalidKeyError):
            await wd.create_data_key(db, pid, "x", "bogus")
        with pytest.raises(wd.InvalidKeyError):
            await wd.create_data_key(db, pid, "   ", "anon")
        with pytest.raises(wd.InvalidKeyError):
            await wd.create_data_key(db, pid, "z" * 101, "anon")


async def test_key_quota(maker, monkeypatch) -> None:
    from app.services import workspace_data as wd

    monkeypatch.setattr("app.services.workspace_data.keys.MAX_KEYS_PER_PROJECT", 3)
    pid = uuid.uuid4()
    async with maker() as db:
        for i in range(3):
            await wd.create_data_key(db, pid, f"k{i}", "anon")
        with pytest.raises(wd.QuotaExceededError):
            await wd.create_data_key(db, pid, "k3", "anon")


async def test_resolve_data_key(maker) -> None:
    from app.services import workspace_data as wd

    pid = uuid.uuid4()
    async with maker() as db:
        key, raw = await wd.create_data_key(db, pid, "resolver", "service")
        resolved = await wd.resolve_data_key(db, raw)
        assert resolved is not None and resolved.id == key.id
        assert resolved.last_used_at is not None  # stamped on resolve
        assert await wd.resolve_data_key(db, "wsk_anon_not_a_real_key") is None
        assert await wd.resolve_data_key(db, "") is None
        # A revoked key no longer resolves.
        await wd.revoke_data_key(db, pid, key.id)
        assert await wd.resolve_data_key(db, raw) is None


async def test_rotate_deploy_key(maker) -> None:
    from app.services import workspace_data as wd
    from app.services.workspace_data.keys import DEPLOY_KEY_NAME

    pid = uuid.uuid4()
    async with maker() as db:
        k1, raw1 = await wd.rotate_deploy_key(db, pid, None)
        assert k1.name == DEPLOY_KEY_NAME and k1.kind == "anon"
        # Rotating again replaces it — still exactly one deploy key, new secret.
        k2, raw2 = await wd.rotate_deploy_key(db, pid, None)
        assert raw2 != raw1
        deploy_keys = [k for k in await wd.list_data_keys(db, pid) if k.name == DEPLOY_KEY_NAME]
        assert len(deploy_keys) == 1 and deploy_keys[0].id == k2.id
        # The superseded key no longer resolves; the fresh one does.
        assert await wd.resolve_data_key(db, raw1) is None
        assert await wd.resolve_data_key(db, raw2) is not None


# --- Agent tool key actions -------------------------------------------------
async def test_agent_tool_key_actions(maker) -> None:
    from app.agent.tools.workspace_ops.workspace_data import workspace_data_executor

    pid = uuid.uuid4()
    async with maker() as db:
        ctx = {"db": db, "project_id": pid, "user_id": uuid.uuid4()}

        # create_key
        out = await workspace_data_executor(
            {"action": "create_key", "name": "agentkey", "kind": "anon"}, ctx
        )
        assert out["success"] is True
        assert out["key"].startswith("wsk_anon_")
        assert out["kind"] == "anon"
        key_id = out["id"]

        # create_key missing name
        out = await workspace_data_executor({"action": "create_key"}, ctx)
        assert out["success"] is False

        # create_key bad kind -> typed store error surfaced
        out = await workspace_data_executor(
            {"action": "create_key", "name": "x", "kind": "bogus"}, ctx
        )
        assert out["success"] is False

        # list_keys
        out = await workspace_data_executor({"action": "list_keys"}, ctx)
        assert out["success"] is True
        assert any(k["id"] == key_id for k in out["keys"])

        # revoke_key
        out = await workspace_data_executor({"action": "revoke_key", "key_id": key_id}, ctx)
        assert out["success"] is True
        out = await workspace_data_executor({"action": "revoke_key", "key_id": key_id}, ctx)
        assert out["success"] is False  # already revoked

        out = await workspace_data_executor({"action": "list_keys"}, ctx)
        assert out["keys"] == []


# --- Autoinject key (stable, deterministic) --------------------------------
async def test_autoinject_key_is_deterministic(maker, monkeypatch: pytest.MonkeyPatch) -> None:
    """Same project_id under same SECRET_KEY → same plaintext, always."""
    from app.services import workspace_data as wd

    monkeypatch.setenv("SECRET_KEY", "test-secret-for-determinism-checks")
    from app.config import get_settings
    get_settings.cache_clear()

    project_id = uuid.uuid4()
    async with maker() as db:
        raw_a = await wd.get_or_create_autoinject_key(db, project_id)
        raw_b = await wd.get_or_create_autoinject_key(db, project_id)
    assert raw_a == raw_b
    assert raw_a.startswith("wsk_anon_")


async def test_autoinject_key_differs_per_project(maker, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import workspace_data as wd

    monkeypatch.setenv("SECRET_KEY", "test-secret-for-determinism-checks")
    from app.config import get_settings
    get_settings.cache_clear()

    p1, p2 = uuid.uuid4(), uuid.uuid4()
    async with maker() as db:
        raw_p1 = await wd.get_or_create_autoinject_key(db, p1)
        raw_p2 = await wd.get_or_create_autoinject_key(db, p2)
    assert raw_p1 != raw_p2


async def test_autoinject_key_idempotent_no_quota_blowup(maker, monkeypatch: pytest.MonkeyPatch) -> None:
    """100 calls must NOT mint 100 keys — the prod-hazard fix being exercised."""
    from app.services import workspace_data as wd

    monkeypatch.setenv("SECRET_KEY", "test-secret-for-determinism-checks")
    from app.config import get_settings
    get_settings.cache_clear()

    project_id = uuid.uuid4()
    async with maker() as db:
        for _ in range(100):
            await wd.get_or_create_autoinject_key(db, project_id)
        # Exactly ONE row for autoinject — quota stays safe.
        assert await wd.count_data_keys(db, project_id) == 1
        keys = await wd.list_data_keys(db, project_id)
        assert keys[0].name == wd.AUTOINJECT_KEY_NAME


async def test_autoinject_key_authenticates(maker, monkeypatch: pytest.MonkeyPatch) -> None:
    """The derived plaintext must resolve through resolve_data_key — i.e.
    the SDK can actually authenticate with it."""
    from app.services import workspace_data as wd

    monkeypatch.setenv("SECRET_KEY", "test-secret-for-determinism-checks")
    from app.config import get_settings
    get_settings.cache_clear()

    project_id = uuid.uuid4()
    async with maker() as db:
        raw = await wd.get_or_create_autoinject_key(db, project_id)
        resolved = await wd.resolve_data_key(db, raw)
        assert resolved is not None
        assert resolved.project_id == project_id
        assert resolved.kind == "anon"
