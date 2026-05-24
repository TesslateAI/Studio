"""Tests for the Workspace Data API tiered rate limiter.

Exercises ``authenticate_data_key`` in isolation with the global token
bucket forced into in-process fallback mode (no Redis required). Verifies
both tiers — per-IP (runs before any DB hit) and per-key (runs after) —
return 429 with the canonical headers, and that the per-IP tier short-circuits
without ever resolving a key.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def _alembic_cfg() -> Config:
    orchestrator_dir = Path(__file__).resolve().parents[2]
    cfg = Config(str(orchestrator_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(orchestrator_dir / "alembic"))
    return cfg


@pytest.fixture
def maker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Session maker bound to a freshly-migrated SQLite database."""
    url = f"sqlite+aiosqlite:///{tmp_path / 'wsdata-ratelimit.db'}"
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


@pytest.fixture(autouse=True)
def _reset_fallback_bucket():
    """Wipe the in-process token-bucket counters between tests.

    The Redis client is unavailable in unit tests, so the bucket falls back
    to a per-process dict; without a reset the counters carry between tests.
    """
    from app.services.rate_limit import _reset_fallback_for_tests

    _reset_fallback_for_tests()
    yield
    _reset_fallback_for_tests()


def _fake_request(ip: str = "10.0.0.1"):
    """Minimal Starlette-like Request stand-in (only ``.client.host`` needed)."""
    return SimpleNamespace(client=SimpleNamespace(host=ip))


async def test_per_ip_429_blocks_before_db_lookup(monkeypatch: pytest.MonkeyPatch, maker) -> None:
    """Per-IP tier must fire before ``resolve_data_key`` — bad-key spammers
    never touch the auth DB."""
    from app.routers import workspace_data as router_mod
    from app.services import workspace_data as wd

    # Tight cap so the third call trips the limiter.
    monkeypatch.setenv("WSDATA_API_PER_IP_CAPACITY", "2")
    monkeypatch.setenv("WSDATA_API_PER_IP_WINDOW_SECONDS", "60")
    from app.config import get_settings

    get_settings.cache_clear()

    request = _fake_request("10.0.0.1")

    async with maker() as db:
        # First two calls land — no key set yet, so they 401 (auth check
        # runs AFTER per-IP throttle but BEFORE per-key throttle).
        for _ in range(2):
            with pytest.raises(HTTPException) as exc:
                await router_mod.authenticate_data_key(request=request, authorization=None, db=db)
            assert exc.value.status_code == 401

        # Third call: per-IP cap busted. Status 429 + Retry-After.
        # Stub resolve_data_key to make sure we never reach it.
        called = {"n": 0}

        async def _spy(*_a, **_kw):
            called["n"] += 1
            return None

        monkeypatch.setattr(wd, "resolve_data_key", _spy)

        with pytest.raises(HTTPException) as exc:
            await router_mod.authenticate_data_key(
                request=request, authorization="Bearer wsk_anon_xx", db=db
            )
        assert exc.value.status_code == 429
        assert "Retry-After" in exc.value.headers
        assert exc.value.headers["X-RateLimit-Remaining"] == "0"
        assert called["n"] == 0, "per-IP tier must short-circuit before DB lookup"


async def test_per_key_429_after_successful_auth(monkeypatch: pytest.MonkeyPatch, maker) -> None:
    """Per-key tier limits a single authenticated key without taking down
    other callers (different IPs / different keys still go through)."""
    from app.routers import workspace_data as router_mod
    from app.services import workspace_data as wd

    # Generous per-IP cap so we hit the per-key cap first.
    monkeypatch.setenv("WSDATA_API_PER_IP_CAPACITY", "1000")
    monkeypatch.setenv("WSDATA_API_PER_KEY_CAPACITY", "2")
    monkeypatch.setenv("WSDATA_API_PER_KEY_WINDOW_SECONDS", "60")
    from app.config import get_settings

    get_settings.cache_clear()

    pid = uuid.uuid4()
    async with maker() as db:
        _key, raw = await wd.create_data_key(db, pid, "rl-test", "service")

    request = _fake_request("10.0.0.2")
    async with maker() as db:
        # First two land.
        for _ in range(2):
            resolved = await router_mod.authenticate_data_key(
                request=request, authorization=f"Bearer {raw}", db=db
            )
            assert resolved.project_id == pid

        # Third — per-key cap.
        with pytest.raises(HTTPException) as exc:
            await router_mod.authenticate_data_key(
                request=request, authorization=f"Bearer {raw}", db=db
            )
        assert exc.value.status_code == 429
        assert "this API key" in exc.value.detail


async def test_bearer_prefix_optional(monkeypatch: pytest.MonkeyPatch, maker) -> None:
    """Raw key without 'Bearer ' prefix still authenticates (back-compat)."""
    from app.routers import workspace_data as router_mod
    from app.services import workspace_data as wd

    monkeypatch.setenv("WSDATA_API_PER_IP_CAPACITY", "1000")
    monkeypatch.setenv("WSDATA_API_PER_KEY_CAPACITY", "1000")
    from app.config import get_settings

    get_settings.cache_clear()

    pid = uuid.uuid4()
    async with maker() as db:
        _key, raw = await wd.create_data_key(db, pid, "raw-test", "service")

    async with maker() as db:
        resolved = await router_mod.authenticate_data_key(
            request=_fake_request(), authorization=raw, db=db
        )
        assert resolved.project_id == pid


async def test_missing_authorization_401(monkeypatch: pytest.MonkeyPatch, maker) -> None:
    """No header → 401 (not 429), even when the IP bucket has budget."""
    from app.routers import workspace_data as router_mod

    monkeypatch.setenv("WSDATA_API_PER_IP_CAPACITY", "1000")
    from app.config import get_settings

    get_settings.cache_clear()

    async with maker() as db:
        with pytest.raises(HTTPException) as exc:
            await router_mod.authenticate_data_key(
                request=_fake_request(), authorization=None, db=db
            )
        assert exc.value.status_code == 401
        assert "API key" in exc.value.detail


async def test_default_public_insert_is_false(maker) -> None:
    """Regression: brand-new collections must be closed-by-default (no
    anonymous insert). Prevents accidental return to the v1 default."""
    from app.services import workspace_data as wd

    pid = uuid.uuid4()
    async with maker() as db:
        coll = await wd.create_collection(db, pid, "secure-by-default")
        assert coll.public_insert is False
        assert coll.public_read is False
        assert coll.public_update is False
        assert coll.public_delete is False
