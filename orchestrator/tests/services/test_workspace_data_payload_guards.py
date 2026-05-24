"""Tests for Group C1 hardening: record payload structural guards.

Three guards beyond the existing size cap, all in ``validate_record_data``:

* depth cap (``MAX_RECORD_NESTING_DEPTH``) — prevents RecursionError in
  ``json.dumps`` (C encoder) and in the ``_hashable`` aggregate helper.
* top-level key cap (``MAX_RECORD_TOP_LEVEL_KEYS``) — bounds the work
  ``infer_schema`` / ``_field_frequencies`` do per record.
* NUL byte / lone-surrogate scrub — Postgres ``text`` rejects ``\\u0000``
  mid-INSERT (turns into a 500); lone surrogates aren't UTF-8 encodable.
  Catch both at the API boundary so callers get a 400 with a clear message.
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
    url = f"sqlite+aiosqlite:///{tmp_path / 'wsdata-payload.db'}"
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


# ---------------------------------------------------------------------------
# Depth cap
# ---------------------------------------------------------------------------
def test_validator_rejects_overdeep_nesting() -> None:
    from app.services import workspace_data as wd

    deep: dict = {}
    cur = deep
    # One deeper than the cap so the *first* over-cap level trips.
    for _ in range(wd.MAX_RECORD_NESTING_DEPTH + 5):
        nxt: dict = {}
        cur["n"] = nxt
        cur = nxt
    with pytest.raises(wd.InvalidRecordError) as exc:
        wd.validate_record_data(deep)
    assert "nesting" in str(exc.value).lower()


def test_validator_accepts_at_cap_depth() -> None:
    """A record exactly at the depth cap must still validate (off-by-one guard)."""
    from app.services import workspace_data as wd

    payload: dict = {}
    cur = payload
    for _ in range(wd.MAX_RECORD_NESTING_DEPTH - 1):
        nxt: dict = {}
        cur["n"] = nxt
        cur = nxt
    wd.validate_record_data(payload)  # must not raise


def test_validator_handles_deep_lists_not_just_dicts() -> None:
    """Arrays count toward depth too — otherwise the cap is trivially bypassable."""
    from app.services import workspace_data as wd

    nested: list = []
    cur = nested
    for _ in range(wd.MAX_RECORD_NESTING_DEPTH + 5):
        nxt: list = []
        cur.append(nxt)
        cur = nxt
    with pytest.raises(wd.InvalidRecordError):
        wd.validate_record_data({"deep": nested})


# ---------------------------------------------------------------------------
# Top-level key cap
# ---------------------------------------------------------------------------
def test_validator_rejects_too_many_top_level_keys() -> None:
    from app.services import workspace_data as wd

    payload = {f"k{i}": 1 for i in range(wd.MAX_RECORD_TOP_LEVEL_KEYS + 1)}
    with pytest.raises(wd.InvalidRecordError) as exc:
        wd.validate_record_data(payload)
    assert "top-level-key" in str(exc.value).lower()


def test_validator_accepts_at_cap_key_count() -> None:
    from app.services import workspace_data as wd

    payload = {f"k{i}": 1 for i in range(wd.MAX_RECORD_TOP_LEVEL_KEYS)}
    wd.validate_record_data(payload)


# ---------------------------------------------------------------------------
# NUL byte + lone surrogate
# ---------------------------------------------------------------------------
def test_validator_rejects_nul_in_string_value() -> None:
    from app.services import workspace_data as wd

    with pytest.raises(wd.InvalidRecordError) as exc:
        wd.validate_record_data({"k": "hello\x00world"})
    assert "nul" in str(exc.value).lower()


def test_validator_rejects_nul_in_key() -> None:
    from app.services import workspace_data as wd

    with pytest.raises(wd.InvalidRecordError):
        wd.validate_record_data({"bad\x00key": "v"})


def test_validator_rejects_lone_surrogate() -> None:
    from app.services import workspace_data as wd

    # U+D800 is a high surrogate that has no low-surrogate pair → not valid Unicode.
    with pytest.raises(wd.InvalidRecordError) as exc:
        wd.validate_record_data({"k": "broken\ud800"})
    assert "surrogate" in str(exc.value).lower()


def test_validator_walks_into_nested_strings() -> None:
    """NUL inside a nested value must also fail, not just at the top level."""
    from app.services import workspace_data as wd

    with pytest.raises(wd.InvalidRecordError):
        wd.validate_record_data({"outer": {"inner": ["ok", "bad\x00"]}})


# ---------------------------------------------------------------------------
# End-to-end through insert_record (the actual API entry point)
# ---------------------------------------------------------------------------
async def test_insert_record_propagates_payload_guards(maker) -> None:
    from app.services import workspace_data as wd

    pid = uuid.uuid4()
    async with maker() as db:
        coll = await wd.create_collection(db, pid, "guarded")
        with pytest.raises(wd.InvalidRecordError):
            await wd.insert_record(db, coll, {"k": "\x00"})
        with pytest.raises(wd.InvalidRecordError):
            await wd.insert_record(
                db, coll, {f"k{i}": 1 for i in range(wd.MAX_RECORD_TOP_LEVEL_KEYS + 1)}
            )
        # Sanity: a normal record still inserts.
        rec = await wd.insert_record(db, coll, {"normal": "value"})
        assert rec.data == {"normal": "value"}
