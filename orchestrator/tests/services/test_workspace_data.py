"""Tests for the Workspace Data Store service (store + keys).

Exercises the store against a migrated SQLite database — the single source
of truth for collection/record CRUD, validation and quotas — plus key
generation and the router's access-flag enforcement.
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
    """A session maker bound to a freshly-migrated SQLite database."""
    url = f"sqlite+aiosqlite:///{tmp_path / 'wsdata.db'}"
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
    def _now(dbapi_conn, _record):  # SQLite has no built-in now()
        dbapi_conn.create_function("now", 0, lambda: datetime.now(UTC).isoformat(sep=" "))

    yield async_sessionmaker(engine, expire_on_commit=False)
    get_settings.cache_clear()


# --- Keys -------------------------------------------------------------------
def test_generate_key_kinds_and_hash() -> None:
    from app.services import workspace_data as wd

    raw_anon, hash_anon, prefix_anon = wd.generate_key("anon")
    assert raw_anon.startswith("wsk_anon_")
    assert prefix_anon == raw_anon[:20]
    assert len(hash_anon) == 64
    assert wd.hash_key(raw_anon) == hash_anon  # deterministic

    raw_svc, _, _ = wd.generate_key("service")
    assert raw_svc.startswith("wsk_svc_")
    assert raw_svc != raw_anon

    with pytest.raises(wd.InvalidKeyError):
        wd.generate_key("bogus")


# --- Collections ------------------------------------------------------------
async def test_collection_crud(maker) -> None:
    from app.services import workspace_data as wd

    project_id = uuid.uuid4()
    async with maker() as db:
        coll = await wd.create_collection(db, project_id, "submissions")
        assert coll.name == "submissions"
        assert coll.public_insert is True
        assert coll.public_read is False

        assert len(await wd.list_collections(db, project_id)) == 1

        by_name = await wd.get_collection(db, project_id, "submissions")
        by_id = await wd.get_collection(db, project_id, coll.id)
        assert by_name is not None and by_id is not None
        assert by_name.id == by_id.id == coll.id

        updated = await wd.update_collection(db, coll, public_read=True)
        assert updated.public_read is True
        assert updated.public_insert is True  # untouched flag preserved

        await wd.delete_collection(db, coll)
        assert await wd.get_collection(db, project_id, "submissions") is None


async def test_create_collection_rejects_duplicate(maker) -> None:
    from app.services import workspace_data as wd

    project_id = uuid.uuid4()
    async with maker() as db:
        await wd.create_collection(db, project_id, "dup")
        with pytest.raises(wd.CollectionExistsError):
            await wd.create_collection(db, project_id, "dup")


async def test_create_collection_rejects_bad_names(maker) -> None:
    from app.services import workspace_data as wd

    project_id = uuid.uuid4()
    async with maker() as db:
        for bad in ("", "has space", "-leading-dash", "x" * 65, "bad/slash"):
            with pytest.raises(wd.InvalidNameError):
                await wd.create_collection(db, project_id, bad)


async def test_collections_scoped_per_project(maker) -> None:
    from app.services import workspace_data as wd

    project_a, project_b = uuid.uuid4(), uuid.uuid4()
    async with maker() as db:
        await wd.create_collection(db, project_a, "shared")
        # Same name is fine in a different project.
        await wd.create_collection(db, project_b, "shared")
        assert len(await wd.list_collections(db, project_a)) == 1
        assert len(await wd.list_collections(db, project_b)) == 1
        assert await wd.get_collection(db, project_b, "shared") is not None


# --- Records ----------------------------------------------------------------
async def test_record_lifecycle(maker) -> None:
    from app.services import workspace_data as wd

    project_id = uuid.uuid4()
    async with maker() as db:
        coll = await wd.create_collection(db, project_id, "items")
        r1 = await wd.insert_record(db, coll, {"n": 1})
        await wd.insert_record(db, coll, {"n": 2})

        records, total = await wd.list_records(db, coll.id)
        assert total == 2
        assert {r.data["n"] for r in records} == {1, 2}

        fetched = await wd.get_record(db, coll.id, r1.id)
        assert fetched is not None and fetched.data == {"n": 1}

        updated = await wd.update_record(db, r1, {"n": 99})
        assert updated.data == {"n": 99}

        await wd.delete_record(db, updated)
        _, total_after = await wd.list_records(db, coll.id)
        assert total_after == 1
        assert await wd.collection_record_count(db, coll.id) == 1
        assert await wd.project_record_count(db, project_id) == 1


async def test_record_validation(maker) -> None:
    from app.services import workspace_data as wd

    project_id = uuid.uuid4()
    async with maker() as db:
        coll = await wd.create_collection(db, project_id, "v")
        for bad in (["not", "a", "dict"], "a string", 42, None):
            with pytest.raises(wd.InvalidRecordError):
                await wd.insert_record(db, coll, bad)
        # Oversized payload is rejected.
        oversized = {"blob": "z" * (wd.MAX_RECORD_BYTES + 100)}
        with pytest.raises(wd.InvalidRecordError):
            await wd.insert_record(db, coll, oversized)


async def test_records_scoped_per_collection(maker) -> None:
    from app.services import workspace_data as wd

    project_id = uuid.uuid4()
    async with maker() as db:
        coll_a = await wd.create_collection(db, project_id, "a")
        coll_b = await wd.create_collection(db, project_id, "b")
        await wd.insert_record(db, coll_a, {"in": "a"})
        await wd.insert_record(db, coll_b, {"in": "b"})

        _, total_a = await wd.list_records(db, coll_a.id)
        _, total_b = await wd.list_records(db, coll_b.id)
        assert total_a == 1 and total_b == 1
        # Project-wide count spans both collections.
        assert await wd.project_record_count(db, project_id) == 2


async def test_delete_collection_removes_records(maker) -> None:
    from app.services import workspace_data as wd

    project_id = uuid.uuid4()
    async with maker() as db:
        coll = await wd.create_collection(db, project_id, "c")
        await wd.insert_record(db, coll, {"a": 1})
        await wd.insert_record(db, coll, {"a": 2})
        coll_id = coll.id
        await wd.delete_collection(db, coll)

    async with maker() as db:
        assert await wd.collection_record_count(db, coll_id) == 0
        assert await wd.project_record_count(db, project_id) == 0


async def test_require_helpers_raise(maker) -> None:
    from app.services import workspace_data as wd

    project_id = uuid.uuid4()
    async with maker() as db:
        with pytest.raises(wd.CollectionNotFoundError):
            await wd.require_collection(db, project_id, "missing")
        coll = await wd.create_collection(db, project_id, "present")
        with pytest.raises(wd.RecordNotFoundError):
            await wd.require_record(db, coll.id, uuid.uuid4())


# --- Access-flag enforcement (Data API gate) --------------------------------
def test_enforce_access_flags() -> None:
    from fastapi import HTTPException

    from app.models_workspace_data import WorkspaceCollection, WorkspaceDataKey
    from app.routers.workspace_data import _enforce

    collection = WorkspaceCollection(
        name="forms",
        public_insert=True,
        public_read=False,
        public_update=False,
        public_delete=False,
    )
    anon = WorkspaceDataKey(kind="anon")
    service = WorkspaceDataKey(kind="service")

    # anon: allowed where the flag is set, blocked otherwise.
    _enforce(anon, collection, "insert")  # no raise
    for blocked in ("read", "update", "delete"):
        with pytest.raises(HTTPException) as exc:
            _enforce(anon, collection, blocked)
        assert exc.value.status_code == 403

    # service: bypasses every flag.
    for op in ("insert", "read", "update", "delete"):
        _enforce(service, collection, op)
