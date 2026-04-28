"""Unit-level coverage for the rewritten webhook trigger handler.

These tests exercise the handler with stubbed DB + ARQ dependencies so the
hot-path latency contract (handler holds the worker for ~ms, not seconds)
can be verified without real Postgres or Redis. The integration variant
(real DB, real worker) lives under ``tests/integration/``.

Behaviors covered:

1. Happy path — webhook fires, returns 202 with the event id, the row is
   inserted with ``dispatched_at`` stamped, and the ARQ pool received the
   ``dispatch_automation_task`` enqueue with ``_job_id`` set to the event
   id (so concurrent in-flight enqueues collapse).
2. ARQ enqueue failure — handler returns 500, ``failed_at`` is stamped,
   ``last_error`` carries the truncated repr, no run is materialized.
3. Concurrent fires — two separate webhook fires for the same trigger
   each get their own event id and each generates an ARQ enqueue; ARQ
   ``_job_id`` collides only when the event id repeats (defense-in-depth
   only — primary safety is the dispatcher's run-level upsert).
4. Bad signature — handler returns 401 and never INSERTs an event.
5. Missing trigger — handler returns 404 cleanly without touching ARQ.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.routers import app_triggers


# ---------------------------------------------------------------------------
# Lightweight stand-ins for the SQLAlchemy models — they only need the
# attributes the handler reads/writes. Keeping them out of the real ORM
# avoids loading the full models graph (and its Postgres-only types) for a
# unit test.
# ---------------------------------------------------------------------------


@dataclass
class _StubAutomation:
    id: uuid.UUID
    is_active: bool = True
    owner_user_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    target_project_id: uuid.UUID | None = None


@dataclass
class _StubTrigger:
    id: uuid.UUID
    automation_id: uuid.UUID
    kind: str = "webhook"
    is_active: bool = True
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class _StubEventRow:
    id: uuid.UUID
    automation_id: uuid.UUID
    trigger_id: uuid.UUID | None
    trigger_kind: str
    payload: dict[str, Any]
    received_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    dispatched_at: datetime | None = None
    failed_at: datetime | None = None
    last_error: str | None = None
    idempotency_key: str | None = None


# ---------------------------------------------------------------------------
# Stub session — collects state mutations so assertions can inspect them
# without a real database. The handler only ever calls:
#
# * ``execute(stmt)`` — for the trigger lookup and for UPDATE statements
# * ``add(row)``       — for INSERTing the event row
# * ``flush()`` / ``commit()`` / ``rollback()``
# * ``get(model, id)`` — for the team-id resolve helper (always None here)
# ---------------------------------------------------------------------------


class _StubScalarResult:
    def __init__(self, rows: list[Any]):
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)

    def scalar_one_or_none(self) -> Any | None:
        return self._rows[0] if self._rows else None


class _StubSession:
    def __init__(
        self,
        *,
        triggers: list[tuple[_StubTrigger, _StubAutomation]] | None = None,
    ):
        self._lookup_rows = triggers or []
        self.events: list[_StubEventRow] = []
        self.commits = 0
        self.rollbacks = 0
        self.update_calls: list[dict[str, Any]] = []

    async def execute(self, stmt: Any) -> _StubScalarResult:
        # We only need to recognize three statement classes:
        #  - SELECT for trigger lookup → returns the prepared rows
        #  - UPDATE on automation_events → mutates the in-memory event
        #  - SELECT on AutomationEvent (recovery sweep, not exercised here)
        compiled = str(stmt)
        if compiled.startswith("UPDATE automation_events"):
            params = stmt.compile().params  # type: ignore[attr-defined]
            self.update_calls.append(dict(params))
            event_id = params.get("id_1") or params.get("automation_events_id")
            for evt in self.events:
                if str(evt.id) == str(event_id):
                    if "dispatched_at" in params:
                        evt.dispatched_at = params["dispatched_at"]
                    if "failed_at" in params:
                        evt.failed_at = params["failed_at"]
                    if "last_error" in params:
                        evt.last_error = params["last_error"]
            return _StubScalarResult([])
        if compiled.startswith("SELECT") and "automation_triggers" in compiled:
            return _StubScalarResult(self._lookup_rows)
        return _StubScalarResult([])

    def add(self, row: Any) -> None:
        # The handler only ``add``s AutomationEvent rows; the stub mirrors
        # the relevant columns into our dataclass for assertions.
        self.events.append(
            _StubEventRow(
                id=getattr(row, "id"),
                automation_id=getattr(row, "automation_id"),
                trigger_id=getattr(row, "trigger_id"),
                trigger_kind=getattr(row, "trigger_kind"),
                payload=getattr(row, "payload"),
                idempotency_key=getattr(row, "idempotency_key", None),
            )
        )

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def get(self, _model: Any, _id: Any) -> None:
        return None


# ---------------------------------------------------------------------------
# Fixture factory — every test wires its own session + ARQ pool, then mounts
# them on a fresh FastAPI app. Keeps tests independent of module-level state
# in ``app_triggers._arq_pool``.
# ---------------------------------------------------------------------------


def _build_app(
    *,
    triggers: list[tuple[_StubTrigger, _StubAutomation]],
    arq_pool: Any,
) -> tuple[FastAPI, _StubSession]:
    session = _StubSession(triggers=triggers)
    app = FastAPI()
    app.include_router(app_triggers.router)

    async def _stub_db():
        yield session

    async def _stub_pool():
        return arq_pool

    app.dependency_overrides[get_db] = _stub_db
    app.dependency_overrides[app_triggers.get_arq_pool] = _stub_pool
    return app, session


def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.fixture
def instance_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def automation() -> _StubAutomation:
    return _StubAutomation(id=uuid.uuid4())


@pytest.fixture
def trigger(automation: _StubAutomation, instance_id: uuid.UUID) -> _StubTrigger:
    return _StubTrigger(
        id=uuid.uuid4(),
        automation_id=automation.id,
        config={
            "app_instance_id": str(instance_id),
            "name": "fire",
            "webhook_secrets": [
                {"kid": "v1", "secret": "topsecret"},
            ],
        },
    )


def test_webhook_happy_path_enqueues_and_marks_dispatched(
    instance_id: uuid.UUID, automation: _StubAutomation, trigger: _StubTrigger
):
    pool = AsyncMock()
    pool.enqueue_job = AsyncMock()
    app, session = _build_app(triggers=[(trigger, automation)], arq_pool=pool)
    client = TestClient(app)

    body = json.dumps({"foo": "bar"}).encode()
    resp = client.post(
        f"/api/app-instances/{instance_id}/trigger/fire",
        content=body,
        headers={"x-tesslate-signature": _sign("topsecret", body)},
    )

    assert resp.status_code == 202, resp.text
    body_json = resp.json()
    assert "event_id" in body_json
    assert body_json["event_id"] == body_json["trigger_event_id"]
    assert body_json["status"] == "enqueued"

    # Exactly one event row, dispatched_at stamped.
    assert len(session.events) == 1
    evt = session.events[0]
    assert str(evt.id) == body_json["event_id"]
    assert evt.dispatched_at is not None
    assert evt.failed_at is None
    assert evt.payload == {"foo": "bar"}
    assert evt.trigger_kind == "webhook"

    # ARQ pool received the enqueue with _job_id == event id.
    pool.enqueue_job.assert_awaited_once()
    args, kwargs = pool.enqueue_job.call_args
    assert args[0] == "dispatch_automation_task"
    assert args[1] == str(automation.id)
    assert args[2] == str(evt.id)
    assert kwargs.get("_job_id") == str(evt.id)


def test_webhook_arq_failure_marks_event_failed(
    instance_id: uuid.UUID, automation: _StubAutomation, trigger: _StubTrigger
):
    pool = AsyncMock()
    pool.enqueue_job = AsyncMock(side_effect=RuntimeError("redis unreachable"))
    app, session = _build_app(triggers=[(trigger, automation)], arq_pool=pool)
    client = TestClient(app)

    body = json.dumps({"hello": "world"}).encode()
    resp = client.post(
        f"/api/app-instances/{instance_id}/trigger/fire",
        content=body,
        headers={"x-tesslate-signature": _sign("topsecret", body)},
    )

    assert resp.status_code == 500, resp.text

    # Event row exists but was stamped failed, not dispatched.
    assert len(session.events) == 1
    evt = session.events[0]
    assert evt.dispatched_at is None
    assert evt.failed_at is not None
    assert evt.last_error and "redis unreachable" in evt.last_error


def test_webhook_concurrent_fires_get_distinct_event_ids(
    instance_id: uuid.UUID, automation: _StubAutomation, trigger: _StubTrigger
):
    pool = AsyncMock()
    pool.enqueue_job = AsyncMock()
    app, session = _build_app(triggers=[(trigger, automation)], arq_pool=pool)
    client = TestClient(app)

    body = json.dumps({"n": 1}).encode()
    sig = _sign("topsecret", body)

    r1 = client.post(
        f"/api/app-instances/{instance_id}/trigger/fire",
        content=body,
        headers={"x-tesslate-signature": sig},
    )
    r2 = client.post(
        f"/api/app-instances/{instance_id}/trigger/fire",
        content=body,
        headers={"x-tesslate-signature": sig},
    )

    assert r1.status_code == 202 and r2.status_code == 202
    e1 = r1.json()["event_id"]
    e2 = r2.json()["event_id"]
    assert e1 != e2  # ingest mints a fresh UUID per request

    # Both fires reached ARQ; each used its own event id as _job_id.
    assert pool.enqueue_job.await_count == 2
    job_ids = {call.kwargs["_job_id"] for call in pool.enqueue_job.call_args_list}
    assert job_ids == {e1, e2}


def test_webhook_bad_signature_returns_401_and_creates_no_event(
    instance_id: uuid.UUID, automation: _StubAutomation, trigger: _StubTrigger
):
    pool = AsyncMock()
    pool.enqueue_job = AsyncMock()
    app, session = _build_app(triggers=[(trigger, automation)], arq_pool=pool)
    client = TestClient(app)

    body = json.dumps({"x": 1}).encode()
    resp = client.post(
        f"/api/app-instances/{instance_id}/trigger/fire",
        content=body,
        headers={"x-tesslate-signature": _sign("WRONG-secret", body)},
    )

    assert resp.status_code == 401
    assert session.events == []
    pool.enqueue_job.assert_not_awaited()


def test_webhook_missing_trigger_returns_404(instance_id: uuid.UUID):
    pool = AsyncMock()
    pool.enqueue_job = AsyncMock()
    # No triggers registered → resolver returns (None, None) → 404.
    app, session = _build_app(triggers=[], arq_pool=pool)
    client = TestClient(app)

    body = b"{}"
    resp = client.post(
        f"/api/app-instances/{instance_id}/trigger/anything",
        content=body,
        headers={"x-tesslate-signature": _sign("ignored", body)},
    )

    assert resp.status_code == 404
    assert session.events == []
    pool.enqueue_job.assert_not_awaited()
