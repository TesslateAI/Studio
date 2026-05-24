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
        # Secure default: a fresh collection accepts no anonymous traffic
        # until the creator explicitly opts in. See migration 0119.
        assert coll.public_insert is False
        assert coll.public_read is False

        assert len(await wd.list_collections(db, project_id)) == 1

        by_name = await wd.get_collection(db, project_id, "submissions")
        by_id = await wd.get_collection(db, project_id, coll.id)
        assert by_name is not None and by_id is not None
        assert by_name.id == by_id.id == coll.id

        # Flip read open explicitly; insert must stay closed (no leak from
        # update_collection touching unspecified flags).
        updated = await wd.update_collection(db, coll, public_read=True)
        assert updated.public_read is True
        assert updated.public_insert is False  # untouched flag preserved

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


# --- Discovery / analysis ---------------------------------------------------
async def test_summarize_collection_shape(maker) -> None:
    from app.services import workspace_data as wd

    project_id = uuid.uuid4()
    async with maker() as db:
        coll = await wd.create_collection(db, project_id, "events")
        for i in range(7):
            await wd.insert_record(db, coll, {"kind": "click", "user": f"u{i % 3}", "n": i})

        summary = await wd.summarize_collection(db, coll, sample_size=5)
        assert summary["total_records"] == 7
        assert summary["sample_size"] == 5
        assert summary["collection"] == "events"
        # field frequencies cover the three top-level keys we wrote.
        freqs = summary["field_frequencies"]
        for key in ("kind", "user", "n"):
            assert freqs.get(key) == 5


async def test_project_data_summary_collection_count(maker) -> None:
    from app.services import workspace_data as wd

    project_id = uuid.uuid4()
    async with maker() as db:
        c1 = await wd.create_collection(db, project_id, "subs")
        await wd.create_collection(db, project_id, "tasks")
        await wd.insert_record(db, c1, {"email": "a@b.com"})

        summary = await wd.project_data_summary(db, project_id, sample_size=3)
        assert summary["collection_count"] == 2
        assert summary["total_records"] == 1
        names = {c["name"] for c in summary["collections"]}
        assert names == {"subs", "tasks"}
        # The collection with a record reports its top fields.
        subs_entry = next(c for c in summary["collections"] if c["name"] == "subs")
        assert "email" in (subs_entry.get("top_fields") or [])


async def test_infer_schema_per_field_types(maker) -> None:
    from app.services import workspace_data as wd

    project_id = uuid.uuid4()
    async with maker() as db:
        coll = await wd.create_collection(db, project_id, "mixed")
        await wd.insert_record(db, coll, {"a": "x", "b": 1, "c": True})
        await wd.insert_record(db, coll, {"a": 42, "b": 2})  # 'a' is mixed; 'c' absent

        schema = await wd.infer_schema(db, coll)
        fields = schema["fields"]
        # 'a' has both string and integer across records.
        assert set(fields["a"]["types"]) == {"string", "integer"}
        assert fields["a"]["present_in"] == 2
        # 'c' was only on one record.
        assert fields["c"]["present_in"] == 1


async def test_aggregate_field_ops(maker) -> None:
    from app.services import workspace_data as wd

    project_id = uuid.uuid4()
    async with maker() as db:
        coll = await wd.create_collection(db, project_id, "votes")
        for v in ("yes", "yes", "no", "yes", "abstain", "no"):
            await wd.insert_record(db, coll, {"choice": v})

        # count_present
        present = await wd.aggregate_field(db, coll, "choice", "count_present")
        assert present["count_present"] == 6
        assert present["is_full_scan"] is True

        # count_unique
        uniq = await wd.aggregate_field(db, coll, "choice", "count_unique")
        assert uniq["count_unique"] == 3

        # value_distribution
        dist = await wd.aggregate_field(db, coll, "choice", "value_distribution", top_n=2)
        top = {entry["value"]: entry["count"] for entry in dist["top_values"]}
        assert top == {"yes": 3, "no": 2}
        assert dist["distinct_count_in_sample"] == 3

        # Unknown op raises a clear store error.
        with pytest.raises(wd.InvalidRecordError):
            await wd.aggregate_field(db, coll, "choice", "median")


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

    # anon: allowed where the flag is set, blocked otherwise. Blocked ops
    # return an opaque 404 (NOT 403) so anon-key holders can't enumerate
    # which collections exist via the status-code distinction. The detailed
    # status / leak-free body assertions live in
    # test_workspace_data_disclosure.test_enforce_returns_opaque_404_for_anon_on_closed_op.
    _enforce(anon, collection, "insert")  # no raise
    for blocked in ("read", "update", "delete"):
        with pytest.raises(HTTPException) as exc:
            _enforce(anon, collection, blocked)
        assert exc.value.status_code == 404

    # service: bypasses every flag.
    for op in ("insert", "read", "update", "delete"):
        _enforce(service, collection, op)
