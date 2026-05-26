"""Tests for Group B hardening: information disclosure + RBAC tightening.

Three orthogonal checks:

1. ``_enforce`` returns an opaque 404 (NOT 403) for anon keys hitting a
   closed-flag operation, with the same detail as a true "missing"
   response — so anon-key holders can't enumerate which collections exist
   in a project via the 404/403 distinction.
2. The destructive mgmt-route ``_require_uuid`` helper rejects non-UUID
   refs with 400, blocking accidental name-based deletes.
3. ``validate_collection_name`` rejects ``collections`` (and any other
   reserved literal path segment), preventing route-alias ambiguity in
   the public Data API.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

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
    url = f"sqlite+aiosqlite:///{tmp_path / 'wsdata-disclosure.db'}"
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
# 1. Closed-flag 404 vs missing-collection 404 — same detail, no leak
# ---------------------------------------------------------------------------
def test_enforce_returns_opaque_404_for_anon_on_closed_op() -> None:
    """An anon key hitting a closed operation must see the same opaque 404
    as it would for a non-existent collection — no name in the body,
    no 403 status to distinguish."""
    from app.models_workspace_data import WorkspaceCollection, WorkspaceDataKey
    from app.routers.workspace_data import _DATA_API_NOT_FOUND, _enforce

    coll = WorkspaceCollection(
        name="private-prod-data",
        public_insert=False,
        public_read=False,
        public_update=False,
        public_delete=False,
    )
    anon = WorkspaceDataKey(kind="anon")

    for op in ("insert", "read", "update", "delete"):
        with pytest.raises(HTTPException) as exc:
            _enforce(anon, coll, op)
        assert exc.value.status_code == 404, op
        assert exc.value.detail == _DATA_API_NOT_FOUND, op
        # Crucially: the collection name does NOT appear in the response.
        assert "private-prod-data" not in str(exc.value.detail), op


def test_enforce_service_key_bypasses_completely() -> None:
    """Service keys must still pass every op unchanged — no 404."""
    from app.models_workspace_data import WorkspaceCollection, WorkspaceDataKey
    from app.routers.workspace_data import _enforce

    coll = WorkspaceCollection(
        name="anything",
        public_insert=False,
        public_read=False,
        public_update=False,
        public_delete=False,
    )
    svc = WorkspaceDataKey(kind="service")
    for op in ("insert", "read", "update", "delete"):
        _enforce(svc, coll, op)  # must not raise


def test_enforce_anon_passes_open_op() -> None:
    """Sanity: a flag-permitted op still returns cleanly (no false-positive 404)."""
    from app.models_workspace_data import WorkspaceCollection, WorkspaceDataKey
    from app.routers.workspace_data import _enforce

    coll = WorkspaceCollection(name="public-form", public_insert=True, public_read=False)
    _enforce(WorkspaceDataKey(kind="anon"), coll, "insert")  # must not raise


# ---------------------------------------------------------------------------
# 2. UUID-only destructive mgmt routes
# ---------------------------------------------------------------------------
def test_require_uuid_accepts_valid_uuid() -> None:
    from app.routers.workspace_data import _require_uuid

    valid = str(uuid.uuid4())
    assert _require_uuid(valid, "collection") == valid


@pytest.mark.parametrize(
    "bad",
    [
        "my-collection-name",  # plausible collection name
        "submissions",  # what the agent might emit
        "not-a-uuid",
        "",
        "12345",
        "../../etc/passwd",
    ],
)
def test_require_uuid_rejects_non_uuid_with_400(bad: str) -> None:
    """Destructive DELETE routes must refuse name-based refs — no silent
    "wrong-object delete by typo" footgun."""
    from app.routers.workspace_data import _require_uuid

    with pytest.raises(HTTPException) as exc:
        _require_uuid(bad, "collection")
    assert exc.value.status_code == 400
    assert "must be a UUID" in exc.value.detail


# ---------------------------------------------------------------------------
# 3. Reserved-name guard for route-layout safety
# ---------------------------------------------------------------------------
async def test_reserved_collection_names_rejected(maker) -> None:
    """``collections`` (and any other Data API path-segment literal) must
    be unreachable as a collection name — would alias the REST prefix."""
    from app.services import workspace_data as wd

    pid = uuid.uuid4()
    async with maker() as db:
        for reserved in ("collections", "Collections", "COLLECTIONS"):
            with pytest.raises(wd.InvalidNameError) as exc:
                await wd.create_collection(db, pid, reserved)
            assert "reserved" in str(exc.value).lower()


async def test_non_reserved_names_still_accepted(maker) -> None:
    """Regression guard: the new reserved check must not over-block."""
    from app.services import workspace_data as wd

    pid = uuid.uuid4()
    async with maker() as db:
        # ``collection`` (singular) is fine — only the plural collides with
        # the REST alias prefix.
        ok = await wd.create_collection(db, pid, "collection")
        assert ok.name == "collection"
        # Substring containing the reserved word is fine too.
        ok2 = await wd.create_collection(db, pid, "my-collections-list")
        assert ok2.name == "my-collections-list"
