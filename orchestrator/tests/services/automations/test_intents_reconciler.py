"""Phase 4 — controller intent reconciler tests.

Exercises :func:`app.services.automations.intents.reconciler.tick`:

* stale lease_term → marks intent as ``superseded``, reconciler.apply NOT called
* current lease_term → marks intent as ``applied``, reconciler.apply called once
* :class:`K8sConflictError` → leaves intent ``pending`` (retry next tick),
  attempts NOT incremented (conflicts are explicitly cheap retries)
* generic exception → increments attempts, leaves ``pending``; >=5 attempts → ``failed``
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
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def _install_sqlite_now(engine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_conn, _record):  # noqa: ARG001
        dbapi_conn.create_function(
            "now", 0, lambda: datetime.now(UTC).isoformat(sep=" ")
        )


def _alembic_cfg() -> Config:
    orchestrator_dir = Path(__file__).resolve().parents[3]
    cfg = Config(str(orchestrator_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(orchestrator_dir / "alembic"))
    return cfg


@pytest.fixture
def migrated_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    db_path = tmp_path / "intents.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DEPLOYMENT_MODE", "desktop")

    from app.config import get_settings

    get_settings.cache_clear()
    orchestrator_dir = Path(__file__).resolve().parents[3]
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_intent(
    maker, *, lease_term: int, attempts: int = 0
) -> uuid.UUID:
    from app.models_automations import ControllerIntent

    intent_id = uuid.uuid4()
    async with maker() as db:
        db.add(
            ControllerIntent(
                id=intent_id,
                kind="scale_to_zero",
                target_ref={"namespace": "proj-x", "deployment": "app-foo"},
                lease_term=lease_term,
                status="pending",
                attempts=attempts,
            )
        )
        await db.commit()
    return intent_id


class _FakeReconciler:
    def __init__(self, *, raises: Exception | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.raises = raises

    async def apply(self, kind: str, target_ref: dict) -> None:
        self.calls.append((kind, dict(target_ref)))
        if self.raises is not None:
            raise self.raises


def _token(term: int):
    from app.services.automations.lease import LeaseToken

    return LeaseToken(
        name="controller",
        holder="test",
        term=term,
        expires_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stale_term_marks_superseded(session_maker) -> None:
    from app.models_automations import ControllerIntent
    from app.services.automations.intents.reconciler import tick

    intent_id = await _seed_intent(session_maker, lease_term=5)
    rec = _FakeReconciler()

    counts = await tick(
        db_factory=session_maker,
        current_term=10,
        reconciler=rec,
    )
    assert counts["superseded"] == 1
    assert counts["applied"] == 0
    assert rec.calls == []

    async with session_maker() as db:
        row = (
            await db.execute(
                select(ControllerIntent).where(ControllerIntent.id == intent_id)
            )
        ).scalar_one()
        assert row.status == "superseded"


@pytest.mark.asyncio
async def test_current_term_marks_applied(session_maker) -> None:
    from app.models_automations import ControllerIntent
    from app.services.automations.intents.reconciler import tick

    intent_id = await _seed_intent(session_maker, lease_term=7)
    rec = _FakeReconciler()

    counts = await tick(
        db_factory=session_maker,
        current_term=7,
        reconciler=rec,
    )
    assert counts["applied"] == 1
    assert len(rec.calls) == 1
    assert rec.calls[0][0] == "scale_to_zero"

    async with session_maker() as db:
        row = (
            await db.execute(
                select(ControllerIntent).where(ControllerIntent.id == intent_id)
            )
        ).scalar_one()
        assert row.status == "applied"
        assert row.applied_by_term == 7
        assert row.applied_at is not None


@pytest.mark.asyncio
async def test_conflict_retries_without_incrementing_attempts(
    session_maker,
) -> None:
    from app.models_automations import ControllerIntent
    from app.services.automations.intents.reconciler import (
        K8sConflictError,
        tick,
    )

    intent_id = await _seed_intent(session_maker, lease_term=1)
    rec = _FakeReconciler(raises=K8sConflictError("resourceVersion mismatch"))

    counts = await tick(
        db_factory=session_maker,
        current_term=1,
        reconciler=rec,
    )
    assert counts["retried"] == 1
    assert counts["applied"] == 0
    assert counts["failed"] == 0

    async with session_maker() as db:
        row = (
            await db.execute(
                select(ControllerIntent).where(ControllerIntent.id == intent_id)
            )
        ).scalar_one()
        # Conflict path leaves the row pending without bumping attempts.
        assert row.status == "pending"
        assert row.attempts == 0


@pytest.mark.asyncio
async def test_generic_exception_increments_attempts_until_failed(
    session_maker,
) -> None:
    from app.models_automations import ControllerIntent
    from app.services.automations.intents.reconciler import tick

    intent_id = await _seed_intent(session_maker, lease_term=1, attempts=4)
    # On attempt 5 (>= MAX_ATTEMPTS=5) the intent flips to failed.
    rec = _FakeReconciler(raises=RuntimeError("k8s API down"))

    counts = await tick(
        db_factory=session_maker,
        current_term=1,
        reconciler=rec,
    )
    assert counts["failed"] == 1

    async with session_maker() as db:
        row = (
            await db.execute(
                select(ControllerIntent).where(ControllerIntent.id == intent_id)
            )
        ).scalar_one()
        assert row.status == "failed"
        assert row.attempts >= 5
        assert "k8s API down" in (row.last_error or "")
