"""Wave 7 unit tests: stage1 scanner, stage2 sandbox, monitoring sweep,
and schedule trigger ingestion.

These are pure unit tests with a fake DB session — no Postgres required.
Integration coverage belongs to a future marked-``integration`` suite.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import pytest

from app.services.apps import (
    monitoring_sweep,
    schedule_triggers,
    stage1_scanner,
    stage2_sandbox,
)


# ---------------------------------------------------------------------------
# Fake rows
# ---------------------------------------------------------------------------


@dataclass
class _Sub:
    id: UUID
    app_version_id: UUID
    stage: str = "stage1"
    decision: str = "pending"
    reviewer_user_id: UUID | None = None
    decision_notes: str | None = None
    stage_entered_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )


@dataclass
class _AV:
    id: UUID
    manifest_json: dict
    required_features: list[str]
    approval_state: str = "pending_stage1"


@dataclass
class _Suite:
    id: UUID
    created_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))


# ---------------------------------------------------------------------------
# Fake session
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, row: Any):
        self._row = row

    def scalar_one_or_none(self):
        return self._row

    def scalars(self):
        rows = (
            []
            if self._row is None
            else (self._row if isinstance(self._row, list) else [self._row])
        )

        class _S:
            def all(self_inner):
                return rows

        return _S()


class _FakeSession:
    """Deterministic session: returns queued rows in order for execute()."""

    def __init__(self, queue: list[Any]):
        self._queue = list(queue)
        self.added: list[Any] = []
        self.flushed = 0

    async def execute(self, _stmt):
        if not self._queue:
            return _FakeResult(None)
        return _FakeResult(self._queue.pop(0))

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushed += 1


def _manifest(**overrides) -> dict:
    base = {
        "schema_version": "2025-01",
        "source_visibility": "public",
        "forkable": True,
        "billing": {
            "dimensions": [
                {"name": "tokens", "payer": "installer"},
            ]
        },
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Stage1
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stage1_scan_all_pass_advances_to_stage2(monkeypatch):
    sub_id, av_id = uuid.uuid4(), uuid.uuid4()
    sub = _Sub(id=sub_id, app_version_id=av_id, stage="stage1")
    av = _AV(id=av_id, manifest_json=_manifest(), required_features=[])

    # Initial select(sub), select(av), then advance_stage's SELECT FOR UPDATE.
    db = _FakeSession([sub, av, sub])

    # Bypass real manifest parsing and feature diff.
    monkeypatch.setattr(
        stage1_scanner, "parse", lambda _raw: object()
    )
    monkeypatch.setattr(
        "app.config_features.diff", lambda _req: []
    )

    out = await stage1_scanner.run_stage1_scan(db, submission_id=sub_id)

    assert out["advanced_to"] == "stage2"
    assert out["failures"] == []
    assert sub.stage == "stage2"


@pytest.mark.asyncio
async def test_stage1_scan_failure_rejects(monkeypatch):
    sub_id, av_id = uuid.uuid4(), uuid.uuid4()
    sub = _Sub(id=sub_id, app_version_id=av_id, stage="stage1")
    av = _AV(
        id=av_id, manifest_json=_manifest(), required_features=["missing.feature.x"]
    )

    db = _FakeSession([sub, av, sub])

    monkeypatch.setattr(stage1_scanner, "parse", lambda _raw: object())
    monkeypatch.setattr(
        "app.config_features.diff", lambda req: list(req)  # everything "missing"
    )

    out = await stage1_scanner.run_stage1_scan(db, submission_id=sub_id)

    assert out["advanced_to"] == "rejected"
    assert "features_supported" in out["failures"]
    assert sub.stage == "rejected"


# ---------------------------------------------------------------------------
# Stage2
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stage2_sandbox_score_above_threshold_advances_to_stage3(monkeypatch):
    sub_id, av_id, suite_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    sub = _Sub(id=sub_id, app_version_id=av_id, stage="stage2")
    av = _AV(id=av_id, manifest_json=_manifest(), required_features=[])
    suite = _Suite(id=suite_id)

    # execute order: select(sub), select(av), select(latest suite),
    # then advance_stage's SELECT FOR UPDATE on sub.
    db = _FakeSession([sub, av, suite, sub])

    monkeypatch.setattr(stage2_sandbox, "_stub_score", lambda _av: 0.9)

    out = await stage2_sandbox.run_stage2_eval(db, submission_id=sub_id)

    assert out["advanced_to"] == "stage3"
    assert out["passed"] is True
    assert sub.stage == "stage3"


@pytest.mark.asyncio
async def test_stage2_sandbox_no_adversarial_suite_warns_and_advances():
    sub_id, av_id = uuid.uuid4(), uuid.uuid4()
    sub = _Sub(id=sub_id, app_version_id=av_id, stage="stage2")
    av = _AV(id=av_id, manifest_json=_manifest(), required_features=[])

    # Suite query returns None; then advance_stage SELECT FOR UPDATE.
    db = _FakeSession([sub, av, None, sub])

    out = await stage2_sandbox.run_stage2_eval(db, submission_id=sub_id)

    assert out["advanced_to"] == "stage3"
    assert out["suite_id"] is None
    assert sub.stage == "stage3"


# ---------------------------------------------------------------------------
# Monitoring sweep
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_monitoring_sweep_failed_without_admin_logs_and_returns(monkeypatch):
    av_id = uuid.uuid4()

    # finish_monitoring_run does SELECT FOR UPDATE; seed a minimal fake run row.
    @dataclass
    class _Run:
        id: UUID
        status: str = "running"
        finished_at: datetime | None = None
        findings: dict = field(default_factory=dict)

    run_row = _Run(id=uuid.uuid4())
    db = _FakeSession([run_row])

    monkeypatch.setattr(monitoring_sweep, "_stub_score", lambda: 0.1)
    monkeypatch.setattr(monitoring_sweep, "_platform_admin_id", lambda: None)

    out = await monitoring_sweep.run_monitoring_sweep(db, app_version_id=av_id)

    assert out["passed"] is False
    assert out["yank_requested"] is False
    assert out["yank_skipped_reason"] == "no_platform_admin_configured"


# ---------------------------------------------------------------------------
# Schedule trigger ingestion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_trigger_event_writes_row():
    schedule_id = uuid.uuid4()
    db = _FakeSession([])

    event_id = await schedule_triggers.ingest_trigger_event(
        db, schedule_id=schedule_id, payload={"hello": "world"}
    )

    assert isinstance(event_id, UUID)
    assert len(db.added) == 1
    row = db.added[0]
    assert row.schedule_id == schedule_id
    assert row.payload == {"hello": "world"}
    assert db.flushed == 1
