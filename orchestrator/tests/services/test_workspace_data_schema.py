"""Tests for Group C2: per-collection JSON Schema validation.

Optional schema (Draft 2020-12) on each ``WorkspaceCollection``. NULL =
no schema (any well-formed object), non-NULL = every insert / update
validates against it.
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
    url = f"sqlite+aiosqlite:///{tmp_path / 'wsdata-schema.db'}"
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
# Schema-itself validation (write-time)
# ---------------------------------------------------------------------------
def test_validate_collection_schema_accepts_none_and_empty() -> None:
    from app.services import workspace_data as wd

    assert wd.validate_collection_schema(None) is None
    assert wd.validate_collection_schema({}) is None  # empty dict ≡ no schema


def test_validate_collection_schema_accepts_a_valid_schema() -> None:
    from app.services import workspace_data as wd

    out = wd.validate_collection_schema(
        {"type": "object", "properties": {"email": {"type": "string"}}}
    )
    assert out == {"type": "object", "properties": {"email": {"type": "string"}}}


def test_validate_collection_schema_rejects_malformed() -> None:
    from app.services import workspace_data as wd

    # Typo in keyword → Draft202012Validator.check_schema rejects.
    with pytest.raises(wd.InvalidSchemaError):
        wd.validate_collection_schema({"type": "objct"})  # 'objct' not a type
    with pytest.raises(wd.InvalidSchemaError):
        wd.validate_collection_schema("not a dict")
    with pytest.raises(wd.InvalidSchemaError):
        wd.validate_collection_schema({"properties": "not-an-object"})


# ---------------------------------------------------------------------------
# Insert/update enforcement
# ---------------------------------------------------------------------------
async def test_insert_enforces_schema_when_set(maker) -> None:
    from app.services import workspace_data as wd

    pid = uuid.uuid4()
    schema = {
        "type": "object",
        "required": ["email"],
        "properties": {
            "email": {"type": "string", "format": "email"},
            "count": {"type": "integer", "minimum": 0},
        },
        "additionalProperties": False,
    }
    async with maker() as db:
        coll = await wd.create_collection(db, pid, "forms", schema=schema)
        # Conforming → OK.
        await wd.insert_record(db, coll, {"email": "a@b.com", "count": 3})
        # Missing required field.
        with pytest.raises(wd.SchemaValidationError) as exc:
            await wd.insert_record(db, coll, {"count": 1})
        assert "email" in str(exc.value) or "required" in str(exc.value)
        # Extra field rejected by additionalProperties=False.
        with pytest.raises(wd.SchemaValidationError):
            await wd.insert_record(db, coll, {"email": "a@b.com", "evil": "x"})
        # Wrong type.
        with pytest.raises(wd.SchemaValidationError):
            await wd.insert_record(db, coll, {"email": "a@b.com", "count": -5})


async def test_insert_skips_schema_when_none(maker) -> None:
    """No schema → v1 behaviour: any well-formed object accepted."""
    from app.services import workspace_data as wd

    pid = uuid.uuid4()
    async with maker() as db:
        coll = await wd.create_collection(db, pid, "freeform")
        await wd.insert_record(db, coll, {"anything": "goes", "n": 1})


async def test_update_enforces_schema_when_collection_supplied(maker) -> None:
    from app.services import workspace_data as wd

    pid = uuid.uuid4()
    schema = {"type": "object", "required": ["name"], "additionalProperties": True}
    async with maker() as db:
        coll = await wd.create_collection(db, pid, "items", schema=schema)
        rec = await wd.insert_record(db, coll, {"name": "first"})
        # Conforming replacement.
        await wd.update_record(db, rec, {"name": "renamed", "extra": 1}, collection=coll)
        # Violation.
        with pytest.raises(wd.SchemaValidationError):
            await wd.update_record(db, rec, {"extra": "no name"}, collection=coll)


async def test_update_skips_schema_when_collection_omitted(maker) -> None:
    """Back-compat: callers that don't pass ``collection`` get the v1
    structural-only validation (no schema check)."""
    from app.services import workspace_data as wd

    pid = uuid.uuid4()
    async with maker() as db:
        coll = await wd.create_collection(db, pid, "back-compat", schema={"required": ["x"]})
        rec = await wd.insert_record(db, coll, {"x": 1})
        # Missing required 'x' — should NOT raise when collection is omitted.
        await wd.update_record(db, rec, {"unrelated": True})


# ---------------------------------------------------------------------------
# Schema lifecycle: update / clear via update_collection
# ---------------------------------------------------------------------------
async def test_update_collection_can_set_and_clear_schema(maker) -> None:
    from app.services import workspace_data as wd

    pid = uuid.uuid4()
    async with maker() as db:
        coll = await wd.create_collection(db, pid, "lifecycle")
        assert coll.schema is None

        coll = await wd.update_collection(db, coll, schema={"type": "object"})
        assert coll.schema == {"type": "object"}

        # Schema kwarg with None clears it.
        coll = await wd.update_collection(db, coll, schema=None)
        assert coll.schema is None

        # Omitting schema kwarg entirely leaves it alone (sentinel pattern).
        coll = await wd.update_collection(db, coll, schema={"type": "object"})
        coll = await wd.update_collection(db, coll, public_read=True)  # no schema kwarg
        assert coll.schema == {"type": "object"}
        assert coll.public_read is True


async def test_create_collection_rejects_invalid_schema(maker) -> None:
    from app.services import workspace_data as wd

    pid = uuid.uuid4()
    async with maker() as db:
        with pytest.raises(wd.InvalidSchemaError):
            await wd.create_collection(db, pid, "bad", schema={"type": "objct"})
