"""Stress, edge-case, big-data and chaos tests for the Workspace Data Store.

Complements ``test_workspace_data.py`` (happy-path CRUD) with boundary
conditions, quota enforcement, large/volume data, concurrency races and a
soak loop. Runs against a freshly-migrated SQLite database with WAL +
busy-timeout so concurrent writers queue rather than fail.
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
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def _alembic_cfg() -> Config:
    orchestrator_dir = Path(__file__).resolve().parents[2]
    cfg = Config(str(orchestrator_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(orchestrator_dir / "alembic"))
    return cfg


@pytest.fixture
def maker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Session maker on a migrated SQLite DB tuned for concurrent writers."""
    url = f"sqlite+aiosqlite:///{tmp_path / 'wsdata-stress.db'}"
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
    def _on_connect(dbapi_conn, _record):
        dbapi_conn.create_function("now", 0, lambda: datetime.now(UTC).isoformat(sep=" "))
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA busy_timeout=15000")  # let concurrent writers queue
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

    yield async_sessionmaker(engine, expire_on_commit=False)
    get_settings.cache_clear()


# ===========================================================================
# Edge cases — collection names
# ===========================================================================
async def test_collection_name_length_boundary(maker) -> None:
    from app.services import workspace_data as wd

    pid = uuid.uuid4()
    async with maker() as db:
        ok = await wd.create_collection(db, pid, "a" * 64)  # exactly 64 — valid
        assert ok.name == "a" * 64
        with pytest.raises(wd.InvalidNameError):
            await wd.create_collection(db, pid, "a" * 65)  # 65 — invalid


async def test_collection_name_allowed_and_rejected(maker) -> None:
    from app.services import workspace_data as wd

    pid = uuid.uuid4()
    async with maker() as db:
        # Allowed: alphanumeric start, then letters/digits/-/_.
        for good in ("a", "A1", "my_collection", "my-collection", "9lives"):
            coll = await wd.create_collection(db, pid, good)
            assert coll.name == good
        # Whitespace is trimmed.
        trimmed = await wd.create_collection(db, pid, "  spaced  ")
        assert trimmed.name == "spaced"
        # Rejected: spaces, dots, slashes, punctuation, non-ASCII, leading -/_.
        for bad in ("a.b", "a/b", "a b", "a!b", "-lead", "_lead", "café", "tab\tname"):
            with pytest.raises(wd.InvalidNameError):
                await wd.create_collection(db, pid, bad)


# ===========================================================================
# Edge cases — record payloads
# ===========================================================================
async def test_record_empty_object_is_valid(maker) -> None:
    from app.services import workspace_data as wd

    pid = uuid.uuid4()
    async with maker() as db:
        coll = await wd.create_collection(db, pid, "c")
        rec = await wd.insert_record(db, coll, {})
        assert rec.data == {}


async def test_record_nested_arrays_and_unicode(maker) -> None:
    from app.services import workspace_data as wd

    pid = uuid.uuid4()
    payload = {
        "nested": {"deep": {"list": [1, 2, {"k": "v"}]}},
        "unicode": "café 日本語 😀 -ish",
        "types": {"i": 1, "f": 1.5, "b": True, "n": None},
        "arr": [[1], [2], [3]],
    }
    async with maker() as db:
        coll = await wd.create_collection(db, pid, "c")
        rec = await wd.insert_record(db, coll, payload)
    async with maker() as db:
        again = await wd.get_record(db, coll.id, rec.id)
        assert again is not None
        assert again.data == payload  # round-trips byte-for-byte


async def test_record_rejects_non_serializable(maker) -> None:
    from app.services import workspace_data as wd

    pid = uuid.uuid4()
    async with maker() as db:
        coll = await wd.create_collection(db, pid, "c")
        # A set is a dict at the top level? No — wrap it as a value.
        with pytest.raises(wd.InvalidRecordError):
            await wd.insert_record(db, coll, {"bad": {1, 2, 3}})
        with pytest.raises(wd.InvalidRecordError):
            await wd.insert_record(db, coll, {"when": datetime.now(UTC)})


async def test_record_size_boundary_counts_utf8_bytes(maker) -> None:
    from app.services import workspace_data as wd

    pid = uuid.uuid4()
    async with maker() as db:
        coll = await wd.create_collection(db, pid, "c")
        # Just under the cap (account for the {"blob": "..."} envelope).
        envelope = len('{"blob": ""}')
        under = {"blob": "a" * (wd.MAX_RECORD_BYTES - envelope)}
        rec = await wd.insert_record(db, coll, under)
        assert rec.id is not None
        # Just over the cap.
        with pytest.raises(wd.InvalidRecordError):
            await wd.insert_record(db, coll, {"blob": "a" * wd.MAX_RECORD_BYTES})
        # Multi-byte: a string that fits in chars but not in UTF-8 bytes.
        # '€' is 3 bytes; (MAX/2) of them exceeds the byte cap.
        with pytest.raises(wd.InvalidRecordError):
            await wd.insert_record(db, coll, {"blob": "€" * (wd.MAX_RECORD_BYTES // 2)})


async def test_record_deep_nesting_does_not_crash(maker) -> None:
    """A pathologically deep document is rejected as 400 (InvalidRecordError),
    never as 500 (RecursionError from the json encoder or _hashable).

    The store's MAX_RECORD_NESTING_DEPTH cap fires well before either of
    those C-implemented recursive paths could blow the stack.
    """
    from app.services import workspace_data as wd

    pid = uuid.uuid4()
    deep: dict = {}
    cur = deep
    for _ in range(2000):
        nxt: dict = {}
        cur["n"] = nxt
        cur = nxt
    async with maker() as db:
        coll = await wd.create_collection(db, pid, "c")
        with pytest.raises(wd.InvalidRecordError) as exc:
            await wd.insert_record(db, coll, deep)
        # Must fail on the structural cap, not somewhere downstream.
        assert "nesting" in str(exc.value).lower()


# ===========================================================================
# Edge cases — pagination & lookups
# ===========================================================================
async def test_pagination_clamps_limit_and_offset(maker) -> None:
    from app.services import workspace_data as wd

    pid = uuid.uuid4()
    async with maker() as db:
        coll = await wd.create_collection(db, pid, "c")
        for i in range(5):
            await wd.insert_record(db, coll, {"i": i})
        # limit below 1 clamps to 1.
        page, total = await wd.list_records(db, coll.id, limit=0)
        assert len(page) == 1 and total == 5
        page, _ = await wd.list_records(db, coll.id, limit=-10)
        assert len(page) == 1
        # limit above MAX clamps to MAX_PAGE_SIZE.
        page, _ = await wd.list_records(db, coll.id, limit=10_000)
        assert len(page) == 5  # only 5 exist, but no error
        # negative offset clamps to 0.
        page, _ = await wd.list_records(db, coll.id, offset=-5)
        assert len(page) == 5


async def test_pagination_offset_beyond_total(maker) -> None:
    from app.services import workspace_data as wd

    pid = uuid.uuid4()
    async with maker() as db:
        coll = await wd.create_collection(db, pid, "c")
        for i in range(3):
            await wd.insert_record(db, coll, {"i": i})
        page, total = await wd.list_records(db, coll.id, limit=10, offset=999)
        assert page == [] and total == 3


async def test_pagination_walks_every_record_once(maker) -> None:
    from app.services import workspace_data as wd

    pid = uuid.uuid4()
    n = 137
    async with maker() as db:
        coll = await wd.create_collection(db, pid, "c")
        for i in range(n):
            await wd.insert_record(db, coll, {"seq": i})
        seen: set[int] = set()
        offset = 0
        while True:
            page, total = await wd.list_records(db, coll.id, limit=25, offset=offset)
            assert total == n
            if not page:
                break
            for r in page:
                seen.add(r.data["seq"])
            offset += 25
        assert seen == set(range(n))  # every record, exactly once


async def test_lookup_unknown_refs_return_none(maker) -> None:
    from app.services import workspace_data as wd

    pid = uuid.uuid4()
    async with maker() as db:
        assert await wd.get_collection(db, pid, "does-not-exist") is None
        assert await wd.get_collection(db, pid, uuid.uuid4()) is None
        coll = await wd.create_collection(db, pid, "c")
        assert await wd.get_record(db, coll.id, "not-a-uuid") is None
        assert await wd.get_record(db, coll.id, uuid.uuid4()) is None


async def test_record_scoped_to_its_collection(maker) -> None:
    from app.services import workspace_data as wd

    pid = uuid.uuid4()
    async with maker() as db:
        coll_a = await wd.create_collection(db, pid, "a")
        coll_b = await wd.create_collection(db, pid, "b")
        rec = await wd.insert_record(db, coll_a, {"in": "a"})
        # Same record id, wrong collection → not found.
        assert await wd.get_record(db, coll_b.id, rec.id) is None
        assert await wd.get_record(db, coll_a.id, rec.id) is not None


# ===========================================================================
# Quota enforcement
# ===========================================================================
async def test_collection_quota_enforced(maker, monkeypatch) -> None:
    from app.services import workspace_data as wd

    monkeypatch.setattr("app.services.workspace_data.store.MAX_COLLECTIONS_PER_PROJECT", 3)
    pid = uuid.uuid4()
    async with maker() as db:
        for i in range(3):
            await wd.create_collection(db, pid, f"c{i}")
        with pytest.raises(wd.QuotaExceededError):
            await wd.create_collection(db, pid, "c3")


async def test_record_quota_enforced(maker, monkeypatch) -> None:
    from app.services import workspace_data as wd

    monkeypatch.setattr("app.services.workspace_data.store.MAX_RECORDS_PER_PROJECT", 5)
    pid = uuid.uuid4()
    async with maker() as db:
        coll = await wd.create_collection(db, pid, "c")
        for i in range(5):
            await wd.insert_record(db, coll, {"i": i})
        with pytest.raises(wd.QuotaExceededError):
            await wd.insert_record(db, coll, {"i": 5})


async def test_record_quota_spans_collections(maker, monkeypatch) -> None:
    """The record quota is per-project, not per-collection."""
    from app.services import workspace_data as wd

    monkeypatch.setattr("app.services.workspace_data.store.MAX_RECORDS_PER_PROJECT", 4)
    pid = uuid.uuid4()
    async with maker() as db:
        c1 = await wd.create_collection(db, pid, "c1")
        c2 = await wd.create_collection(db, pid, "c2")
        await wd.insert_record(db, c1, {"x": 1})
        await wd.insert_record(db, c1, {"x": 2})
        await wd.insert_record(db, c2, {"x": 3})
        await wd.insert_record(db, c2, {"x": 4})
        with pytest.raises(wd.QuotaExceededError):
            await wd.insert_record(db, c2, {"x": 5})


# ===========================================================================
# Cross-project isolation
# ===========================================================================
async def test_cross_project_isolation(maker) -> None:
    from app.services import workspace_data as wd

    project_a, project_b = uuid.uuid4(), uuid.uuid4()
    async with maker() as db:
        coll_a = await wd.create_collection(db, project_a, "shared-name")
        await wd.insert_record(db, coll_a, {"owner": "a"})
        # Project B can reuse the name and sees none of A's data.
        coll_b = await wd.create_collection(db, project_b, "shared-name")
        assert coll_b.id != coll_a.id
        # A's collection is invisible from B's project scope.
        assert await wd.get_collection(db, project_b, coll_a.id) is None
        assert await wd.project_record_count(db, project_b) == 0
        assert await wd.project_record_count(db, project_a) == 1
        # require_collection raises for the wrong project.
        with pytest.raises(wd.CollectionNotFoundError):
            await wd.require_collection(db, project_b, coll_a.id)


# ===========================================================================
# Big data / volume
# ===========================================================================
async def test_big_data_many_records(maker) -> None:
    from app.services import workspace_data as wd

    pid = uuid.uuid4()
    n = 600
    async with maker() as db:
        coll = await wd.create_collection(db, pid, "events")
        for i in range(n):
            await wd.insert_record(db, coll, {"seq": i, "payload": f"event-{i}"})
        assert await wd.collection_record_count(db, coll.id) == n
        assert await wd.project_record_count(db, pid) == n
        # Counts and last page are consistent.
        page, total = await wd.list_records(db, coll.id, limit=200, offset=400)
        assert total == n
        assert len(page) == 200


async def test_big_data_large_records(maker) -> None:
    from app.services import workspace_data as wd

    pid = uuid.uuid4()
    big_value = "x" * (60 * 1024)  # ~60 KB, under the 64 KB cap
    async with maker() as db:
        coll = await wd.create_collection(db, pid, "blobs")
        for i in range(20):
            await wd.insert_record(db, coll, {"i": i, "blob": big_value})
        page, total = await wd.list_records(db, coll.id, limit=200)
        assert total == 20
        assert all(len(r.data["blob"]) == 60 * 1024 for r in page)


# ===========================================================================
# Keys
# ===========================================================================
def test_generated_keys_are_unique() -> None:
    from app.services import workspace_data as wd

    hashes = set()
    raws = set()
    for _ in range(500):
        raw, h, _ = wd.generate_key("anon")
        hashes.add(h)
        raws.add(raw)
    assert len(hashes) == 500  # no hash collisions
    assert len(raws) == 500  # no raw-key collisions


# ===========================================================================
# Concurrency / chaos
# ===========================================================================
async def test_concurrent_duplicate_collection_creation(maker) -> None:
    """8 racers create the same collection — exactly one wins, cleanly."""
    from app.services import workspace_data as wd

    pid = uuid.uuid4()

    async def racer():
        async with maker() as db:
            try:
                await wd.create_collection(db, pid, "contended")
                return "created"
            except wd.CollectionExistsError:
                return "exists"

    results = await asyncio.gather(*[racer() for _ in range(8)])
    assert results.count("created") == 1
    assert results.count("exists") == 7  # every loser raised the typed error
    async with maker() as db:
        assert len(await wd.list_collections(db, pid)) == 1


async def test_concurrent_inserts_all_land(maker) -> None:
    from app.services import workspace_data as wd

    pid = uuid.uuid4()
    async with maker() as db:
        coll = await wd.create_collection(db, pid, "c")

    async def insert(i: int):
        async with maker() as db:
            fresh = await wd.require_collection(db, pid, coll.id)
            await wd.insert_record(db, fresh, {"worker": i})

    await asyncio.gather(*[insert(i) for i in range(40)])
    async with maker() as db:
        page, total = await wd.list_records(db, coll.id, limit=200)
        assert total == 40
        assert {r.data["worker"] for r in page} == set(range(40))


async def test_concurrent_mixed_ops_stay_consistent(maker) -> None:
    """Interleaved insert/list/count from many tasks — no corruption, no crash."""
    from app.services import workspace_data as wd

    pid = uuid.uuid4()
    async with maker() as db:
        coll = await wd.create_collection(db, pid, "c")

    async def worker(i: int):
        async with maker() as db:
            fresh = await wd.require_collection(db, pid, coll.id)
            await wd.insert_record(db, fresh, {"i": i})
        async with maker() as db:
            await wd.list_records(db, coll.id, limit=10)
            await wd.collection_record_count(db, coll.id)

    await asyncio.gather(*[worker(i) for i in range(50)])
    async with maker() as db:
        assert await wd.collection_record_count(db, coll.id) == 50


async def test_soak_insert_query_delete_cycles(maker) -> None:
    """Sustained insert→read→update→delete cycles leave a consistent store."""
    from app.services import workspace_data as wd

    pid = uuid.uuid4()
    async with maker() as db:
        coll = await wd.create_collection(db, pid, "soak")

    cycles = 200
    for i in range(cycles):
        async with maker() as db:
            fresh = await wd.require_collection(db, pid, coll.id)
            rec = await wd.insert_record(db, fresh, {"cycle": i})
            got = await wd.get_record(db, coll.id, rec.id)
            assert got is not None and got.data["cycle"] == i
            updated = await wd.update_record(db, got, {"cycle": i, "done": True})
            assert updated.data["done"] is True
            await wd.delete_record(db, updated)

    async with maker() as db:
        # Every cycle cleaned up after itself — store is empty, counts agree.
        assert await wd.collection_record_count(db, coll.id) == 0
        assert await wd.project_record_count(db, pid) == 0
        page, total = await wd.list_records(db, coll.id)
        assert page == [] and total == 0
