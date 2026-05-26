"""Unit tests for the ``workspace_data`` agent tool executor.

Boundary covered: the tool's per-action handler returns the right
``success_output`` shape and surfaces the right fields to the agent.

This file exists because shipping ``collection=collection.name, **summary``
silently collided when ``summary`` already contained a ``collection`` key
— the store-layer tests caught nothing because they exercise the service,
not the tool. These tests guard the integration seam.
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
    orchestrator_dir = Path(__file__).resolve().parents[3]
    cfg = Config(str(orchestrator_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(orchestrator_dir / "alembic"))
    return cfg


@pytest.fixture
def maker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A session maker bound to a freshly-migrated SQLite database."""
    url = f"sqlite+aiosqlite:///{tmp_path / 'wsdata_tools.db'}"
    monkeypatch.setenv("DATABASE_URL", url)

    from app.config import get_settings

    get_settings.cache_clear()
    orchestrator_dir = Path(__file__).resolve().parents[3]
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


async def _seed(maker, *, records: int = 6) -> tuple[uuid.UUID, str]:
    """Create a project + collection + records; return (project_id, collection_name)."""
    from app.services import workspace_data as wd

    project_id = uuid.uuid4()
    async with maker() as db:
        coll = await wd.create_collection(db, project_id, "subs")
        plans = ["pro", "pro", "free", "pro", "free", "free"][:records]
        for n, plan in enumerate(plans, start=1):
            await wd.insert_record(db, coll, {"email": f"u{n}@x", "plan": plan, "n": n})
    return project_id, "subs"


@pytest.mark.unit
async def test_summarize_action_flat_output_shape(maker) -> None:
    """summarize must return a flat success_output — keys live at top level,
    not nested under ``result`` and not duplicated by **summary collision."""
    from app.agent.tools.workspace_ops.workspace_data import workspace_data_executor

    project_id, name = await _seed(maker, records=6)
    async with maker() as db:
        out = await workspace_data_executor(
            {"action": "summarize", "collection": name},
            {"db": db, "project_id": project_id},
        )

    # success_output shape: flat dict with success/message/...extra
    assert out["success"] is True
    assert "result" not in out, "must not nest under 'result' — flat shape"
    assert out["total_records"] == 6
    assert out["sample_size"] >= 1
    # field_frequencies covers every top-level key we wrote
    assert set(out["field_frequencies"].keys()) == {"email", "plan", "n"}
    # message must quote the actual count, not a placeholder
    assert "6 record" in out["message"]


@pytest.mark.unit
async def test_schema_action_returns_inferred_types(maker) -> None:
    from app.agent.tools.workspace_ops.workspace_data import workspace_data_executor

    project_id, name = await _seed(maker, records=4)
    async with maker() as db:
        out = await workspace_data_executor(
            {"action": "schema", "collection": name},
            {"db": db, "project_id": project_id},
        )

    assert out["success"] is True
    fields = out["fields"]
    assert fields["plan"]["types"] == ["string"]
    assert fields["n"]["types"] == ["integer"]
    assert fields["email"]["present_in"] == 4


@pytest.mark.unit
async def test_aggregate_value_distribution(maker) -> None:
    from app.agent.tools.workspace_ops.workspace_data import workspace_data_executor

    project_id, name = await _seed(maker, records=6)
    async with maker() as db:
        out = await workspace_data_executor(
            {
                "action": "aggregate",
                "collection": name,
                "field": "plan",
                "op": "value_distribution",
                "top_n": 5,
            },
            {"db": db, "project_id": project_id},
        )

    assert out["success"] is True
    assert out["is_full_scan"] is True
    top = {entry["value"]: entry["count"] for entry in out["top_values"]}
    assert top == {"pro": 3, "free": 3}


@pytest.mark.unit
async def test_aggregate_count_unique(maker) -> None:
    from app.agent.tools.workspace_ops.workspace_data import workspace_data_executor

    project_id, name = await _seed(maker, records=6)
    async with maker() as db:
        out = await workspace_data_executor(
            {"action": "aggregate", "collection": name, "field": "plan", "op": "count_unique"},
            {"db": db, "project_id": project_id},
        )

    assert out["success"] is True
    assert out["count_unique"] == 2


@pytest.mark.unit
async def test_aggregate_unknown_op_returns_error(maker) -> None:
    """Unknown op must error cleanly with the valid-ops list, not raise."""
    from app.agent.tools.workspace_ops.workspace_data import workspace_data_executor

    project_id, name = await _seed(maker, records=2)
    async with maker() as db:
        out = await workspace_data_executor(
            {"action": "aggregate", "collection": name, "field": "plan", "op": "median"},
            {"db": db, "project_id": project_id},
        )

    assert out["success"] is False
    # Suggestion enumerates the valid ops
    assert "count_present" in (out.get("suggestion") or "")


@pytest.mark.unit
async def test_summarize_missing_collection_errors(maker) -> None:
    """Missing collection raises CollectionNotFoundError which becomes a
    structured error_output with the next-step suggestion."""
    from app.agent.tools.workspace_ops.workspace_data import workspace_data_executor

    project_id = uuid.uuid4()
    async with maker() as db:
        out = await workspace_data_executor(
            {"action": "summarize", "collection": "does-not-exist"},
            {"db": db, "project_id": project_id},
        )

    assert out["success"] is False
    assert "does-not-exist" in out["message"]
    assert "create_collection" in (out.get("suggestion") or "")


@pytest.mark.unit
async def test_summarize_requires_collection_param(maker) -> None:
    from app.agent.tools.workspace_ops.workspace_data import workspace_data_executor

    project_id = uuid.uuid4()
    async with maker() as db:
        out = await workspace_data_executor(
            {"action": "summarize"},
            {"db": db, "project_id": project_id},
        )

    assert out["success"] is False
    assert "collection" in out["message"]


@pytest.mark.unit
async def test_unknown_action_lists_available(maker) -> None:
    from app.agent.tools.workspace_ops.workspace_data import workspace_data_executor

    project_id = uuid.uuid4()
    async with maker() as db:
        out = await workspace_data_executor(
            {"action": "nope"},
            {"db": db, "project_id": project_id},
        )

    assert out["success"] is False
    # Suggestion must enumerate at least the new analysis actions
    suggestion = out.get("suggestion") or ""
    for action in ("summarize", "schema", "aggregate"):
        assert action in suggestion


# ---------------------------------------------------------------------------
# Schema actions (Group G — agent-side schema editing)
# ---------------------------------------------------------------------------
@pytest.mark.unit
async def test_create_collection_with_schema(maker) -> None:
    """Agent can create a schema-enforced collection in one call."""
    from app.agent.tools.workspace_ops.workspace_data import workspace_data_executor

    pid = uuid.uuid4()
    schema = {
        "type": "object",
        "required": ["email"],
        "properties": {"email": {"type": "string", "format": "email"}},
        "additionalProperties": False,
    }
    async with maker() as db:
        out = await workspace_data_executor(
            {"action": "create_collection", "name": "leads", "schema": schema},
            {"db": db, "project_id": pid},
        )
        assert out["success"] is True
        assert out["schema"] == schema

        # Schema is actually enforced on subsequent inserts.
        bad = await workspace_data_executor(
            {"action": "insert", "collection": "leads", "data": {"no_email": "x"}},
            {"db": db, "project_id": pid},
        )
        assert bad["success"] is False
        assert "schema" in bad["message"].lower()


@pytest.mark.unit
async def test_create_collection_rejects_non_object_schema(maker) -> None:
    from app.agent.tools.workspace_ops.workspace_data import workspace_data_executor

    pid = uuid.uuid4()
    async with maker() as db:
        out = await workspace_data_executor(
            {"action": "create_collection", "name": "x", "schema": "not-a-dict"},
            {"db": db, "project_id": pid},
        )
        assert out["success"] is False
        assert "JSON object" in out["message"]


@pytest.mark.unit
async def test_update_collection_sets_schema(maker) -> None:
    """update_collection can attach a schema to an existing collection."""
    from app.agent.tools.workspace_ops.workspace_data import workspace_data_executor

    pid = uuid.uuid4()
    async with maker() as db:
        await workspace_data_executor(
            {"action": "create_collection", "name": "items"},
            {"db": db, "project_id": pid},
        )
        out = await workspace_data_executor(
            {
                "action": "update_collection",
                "collection": "items",
                "schema": {"type": "object", "required": ["name"]},
            },
            {"db": db, "project_id": pid},
        )
        assert out["success"] is True
        assert out["schema"] == {"type": "object", "required": ["name"]}
        # Validation now active.
        bad = await workspace_data_executor(
            {"action": "insert", "collection": "items", "data": {"x": 1}},
            {"db": db, "project_id": pid},
        )
        assert bad["success"] is False


@pytest.mark.unit
async def test_update_collection_clears_schema(maker) -> None:
    """{'clear': true} on the schema param removes the existing schema."""
    from app.agent.tools.workspace_ops.workspace_data import workspace_data_executor

    pid = uuid.uuid4()
    async with maker() as db:
        await workspace_data_executor(
            {
                "action": "create_collection",
                "name": "items",
                "schema": {"type": "object", "required": ["a"]},
            },
            {"db": db, "project_id": pid},
        )
        out = await workspace_data_executor(
            {"action": "update_collection", "collection": "items", "schema": {"clear": True}},
            {"db": db, "project_id": pid},
        )
        assert out["success"] is True
        assert out["schema"] is None
        # After clearing, the v1 'any object' contract is back.
        ok = await workspace_data_executor(
            {"action": "insert", "collection": "items", "data": {"freeform": True}},
            {"db": db, "project_id": pid},
        )
        assert ok["success"] is True


@pytest.mark.unit
async def test_update_collection_changes_flags(maker) -> None:
    """update_collection also accepts public_* flags."""
    from app.agent.tools.workspace_ops.workspace_data import workspace_data_executor

    pid = uuid.uuid4()
    async with maker() as db:
        await workspace_data_executor(
            {"action": "create_collection", "name": "forms"},
            {"db": db, "project_id": pid},
        )
        out = await workspace_data_executor(
            {
                "action": "update_collection",
                "collection": "forms",
                "public_insert": True,
                "public_read": True,
            },
            {"db": db, "project_id": pid},
        )
        assert out["success"] is True
        assert out["public_insert"] is True
        assert out["public_read"] is True
        assert out["public_update"] is False
        assert out["public_delete"] is False


@pytest.mark.unit
async def test_update_collection_requires_at_least_one_field(maker) -> None:
    """No-op update is a usage error, not a silent success — guards against
    the agent calling update_collection without actually changing anything."""
    from app.agent.tools.workspace_ops.workspace_data import workspace_data_executor

    pid = uuid.uuid4()
    async with maker() as db:
        await workspace_data_executor(
            {"action": "create_collection", "name": "c"},
            {"db": db, "project_id": pid},
        )
        out = await workspace_data_executor(
            {"action": "update_collection", "collection": "c"},
            {"db": db, "project_id": pid},
        )
        assert out["success"] is False
        assert "Nothing to update" in out["message"]


@pytest.mark.unit
async def test_update_collection_rejects_malformed_schema_param(maker) -> None:
    from app.agent.tools.workspace_ops.workspace_data import workspace_data_executor

    pid = uuid.uuid4()
    async with maker() as db:
        await workspace_data_executor(
            {"action": "create_collection", "name": "c"},
            {"db": db, "project_id": pid},
        )
        out = await workspace_data_executor(
            {"action": "update_collection", "collection": "c", "schema": "not-a-dict"},
            {"db": db, "project_id": pid},
        )
        assert out["success"] is False
        assert "schema" in out["message"].lower()
