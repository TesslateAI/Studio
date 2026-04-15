"""Unit tests for the ``request_node_config`` agent tool.

These tests drive the executor with a mocked DB session + real in-memory
``PendingUserInputManager`` (no Redis needed) and record every event it
publishes through ``pubsub.publish_agent_event``. The critical security
assertion is that secret *values* never appear in the tool's return value or
in any event payload — only key names do.
"""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.agent.tools.approval_manager import PendingUserInputManager
from app.agent.tools.node_config.request_node_config import (
    request_node_config_executor,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


class _EventRecorder:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def publish_agent_event(self, task_id: str, event: dict) -> None:
        self.events.append(event)

    def types(self) -> list[str]:
        return [e["type"] for e in self.events]

    def by_type(self, type_name: str) -> dict | None:
        for ev in self.events:
            if ev["type"] == type_name:
                return ev
        return None


def _make_container(
    *,
    project_id: UUID,
    container_id: UUID | None = None,
    environment_vars: dict | None = None,
    encrypted_secrets: dict | None = None,
    name: str = "supabase",
) -> MagicMock:
    """A Container-shaped MagicMock that behaves like a mutable ORM row."""
    from app.models import Container

    c = MagicMock(spec=Container)
    c.id = container_id or uuid4()
    c.project_id = project_id
    c.name = name
    c.container_name = f"proj-{name}"
    c.service_slug = "supabase"
    c.deployment_mode = "external"
    c.environment_vars = dict(environment_vars or {})
    c.encrypted_secrets = dict(encrypted_secrets) if encrypted_secrets else None
    c.needs_restart = False
    c.position_x = 100.0
    c.position_y = 200.0
    return c


def _make_project(project_id: UUID) -> MagicMock:
    from app.models import Project

    p = MagicMock(spec=Project)
    p.id = project_id
    p.slug = "proj"
    p.team_id = uuid4()
    p.owner_id = uuid4()
    return p


@pytest.fixture
def manager() -> PendingUserInputManager:
    return PendingUserInputManager()


@pytest.fixture
def pubsub_recorder(monkeypatch: pytest.MonkeyPatch) -> _EventRecorder:
    rec = _EventRecorder()
    from app.agent.tools.node_config import request_node_config as rnc

    monkeypatch.setattr(rnc, "get_pubsub", lambda: rec)
    # apply_node_config calls flag_modified on a detached mock Container —
    # it requires a real SA-mapped instance. For these unit tests we bypass
    # that by making flag_modified a no-op.
    from app.routers import node_config as node_config_router

    monkeypatch.setattr(node_config_router, "flag_modified", lambda *a, **k: None)
    return rec


@pytest.fixture
def patch_manager_singleton(
    monkeypatch: pytest.MonkeyPatch, manager: PendingUserInputManager
) -> PendingUserInputManager:
    """Make the executor + router use the same per-test manager instance."""
    from app.agent.tools import approval_manager as am
    from app.agent.tools.node_config import request_node_config as rnc

    monkeypatch.setattr(am, "_manager", manager, raising=False)
    monkeypatch.setattr(am, "get_approval_manager", lambda: manager)
    monkeypatch.setattr(am, "get_pending_input_manager", lambda: manager)
    monkeypatch.setattr(rnc, "get_pubsub", rnc.get_pubsub)  # no-op anchor
    return manager


@pytest.fixture
def patch_audit(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Capture audit events by patching ``log_event`` in audit_service."""
    captured: list[dict] = []

    async def fake_log_event(**kwargs: Any) -> None:
        captured.append(kwargs)

    from app.services import audit_service

    monkeypatch.setattr(audit_service, "log_event", fake_log_event)
    return captured


def _build_context(
    db: Any, project_id: UUID, user_id: UUID, task_id: str = "task-1"
) -> dict:
    return {
        "db": db,
        "project_id": project_id,
        "user_id": user_id,
        "task_id": task_id,
        "chat_id": "chat-1",
    }


# ---------------------------------------------------------------------------
# Create mode: supabase preset
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_supabase_persists_encrypted_secrets_and_returns_no_plaintext(
    pubsub_recorder: _EventRecorder,
    patch_manager_singleton: PendingUserInputManager,
    patch_audit: list[dict],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    user_id = uuid4()
    project = _make_project(project_id)
    created_container = _make_container(project_id=project_id)

    db = MagicMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    pos_result = MagicMock()
    pos_result.all = MagicMock(return_value=[])
    db.execute = AsyncMock(return_value=pos_result)
    db.add = MagicMock()

    # Intercept container load/create so the executor operates on our mock.
    from app.agent.tools.node_config import request_node_config as rnc

    async def _fake_load_or_create(db_, **kwargs: Any) -> MagicMock:
        return created_container

    monkeypatch.setattr(rnc, "_load_or_create_container", _fake_load_or_create)

    from app.models import Container, Project

    async def _db_get(model_cls: type, _id: UUID) -> Any:
        if model_cls is Container:
            return created_container
        if model_cls is Project:
            return project
        return None

    db.get = AsyncMock(side_effect=_db_get)

    # Schedule the user's submit after the executor emits user_input_required.
    async def _submit_when_ready() -> None:
        # Wait for the tool to publish user_input_required
        for _ in range(200):
            ev = pubsub_recorder.by_type("user_input_required")
            if ev is not None:
                patch_manager_singleton.submit_input(
                    ev["data"]["input_id"],
                    {
                        "SUPABASE_URL": "https://proj.supabase.co",
                        "SUPABASE_ANON_KEY": "anon-secret-abcdefghij",
                        "SUPABASE_SERVICE_KEY": "service-secret-0123456789",
                    },
                )
                return
            await asyncio.sleep(0.01)

    submit_task = asyncio.create_task(_submit_when_ready())
    result = await request_node_config_executor(
        {"node_name": "supabase", "preset": "supabase"},
        _build_context(db, project_id, user_id),
    )
    await submit_task

    # --- 1. Event ordering: architecture_node_added before user_input_required
    types = pubsub_recorder.types()
    assert "architecture_node_added" in types
    assert "user_input_required" in types
    assert types.index("architecture_node_added") < types.index("user_input_required")

    # --- 2. user_input_required schema matches supabase preset
    uir = pubsub_recorder.by_type("user_input_required")
    assert uir is not None
    schema_keys = [f["key"] for f in uir["data"]["schema"]["fields"]]
    assert schema_keys == [
        "SUPABASE_URL",
        "SUPABASE_ANON_KEY",
        "SUPABASE_SERVICE_KEY",
    ]
    # No secret values leak into initial_values in create mode
    assert uir["data"]["initial_values"] == {}

    # --- 3. Container state: non-secrets on environment_vars, secrets encrypted
    assert created_container.environment_vars.get("SUPABASE_URL") == "https://proj.supabase.co"
    assert "SUPABASE_ANON_KEY" not in created_container.environment_vars
    assert "SUPABASE_SERVICE_KEY" not in created_container.environment_vars

    encrypted = created_container.encrypted_secrets or {}
    assert set(encrypted.keys()) == {"SUPABASE_ANON_KEY", "SUPABASE_SERVICE_KEY"}

    from app.services.deployment_encryption import get_deployment_encryption_service

    enc = get_deployment_encryption_service()
    assert enc.decrypt(encrypted["SUPABASE_ANON_KEY"]) == "anon-secret-abcdefghij"
    assert enc.decrypt(encrypted["SUPABASE_SERVICE_KEY"]) == "service-secret-0123456789"

    # --- 4. needs_restart flipped on rotation
    assert created_container.needs_restart is True

    # --- 5. Tool return value: NO secret plaintext; correct summary
    assert result["success"] is True
    assert result["created"] is True
    assert set(result["secret_keys"]) == {"SUPABASE_ANON_KEY", "SUPABASE_SERVICE_KEY"}
    assert result["non_secret_values"] == {"SUPABASE_URL": "https://proj.supabase.co"}
    assert set(result["rotated_secrets"]) == {
        "SUPABASE_ANON_KEY",
        "SUPABASE_SERVICE_KEY",
    }
    # Deep-scan for secret plaintext anywhere in the result
    _assert_no_plaintext_in(result, {"anon-secret-abcdefghij", "service-secret-0123456789"})

    # And in every published event
    for ev in pubsub_recorder.events:
        _assert_no_plaintext_in(
            ev, {"anon-secret-abcdefghij", "service-secret-0123456789"}
        )

    # --- 6. Audit log written with node_config_updated + rotated_secrets
    assert len(patch_audit) == 1
    audit = patch_audit[0]
    assert audit["action"] == "node_config_updated"
    assert audit["resource_type"] == "container"
    assert set(audit["details"]["rotated_secrets"]) == {
        "SUPABASE_ANON_KEY",
        "SUPABASE_SERVICE_KEY",
    }


def _assert_no_plaintext_in(obj: Any, forbidden: set[str]) -> None:
    """Recursively walk *obj* and assert none of the forbidden strings appear."""
    if isinstance(obj, str):
        for s in forbidden:
            assert s not in obj, f"Secret plaintext {s!r} leaked in {obj!r}"
    elif isinstance(obj, dict):
        for v in obj.values():
            _assert_no_plaintext_in(v, forbidden)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _assert_no_plaintext_in(v, forbidden)


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancellation_returns_cancelled_and_skips_audit(
    pubsub_recorder: _EventRecorder,
    patch_manager_singleton: PendingUserInputManager,
    patch_audit: list[dict],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    user_id = uuid4()
    project = _make_project(project_id)
    created_container = _make_container(project_id=project_id)

    db = MagicMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    pos_result = MagicMock()
    pos_result.all = MagicMock(return_value=[])
    db.execute = AsyncMock(return_value=pos_result)
    db.add = MagicMock()

    from app.agent.tools.node_config import request_node_config as rnc

    async def _fake_load_or_create(db_, **kwargs: Any) -> MagicMock:
        return created_container

    monkeypatch.setattr(rnc, "_load_or_create_container", _fake_load_or_create)

    from app.models import Container, Project

    async def _db_get(model_cls: type, _id: UUID) -> Any:
        if model_cls is Container:
            return created_container
        if model_cls is Project:
            return project
        return None

    db.get = AsyncMock(side_effect=_db_get)

    async def _cancel_when_ready() -> None:
        for _ in range(200):
            ev = pubsub_recorder.by_type("user_input_required")
            if ev is not None:
                patch_manager_singleton.cancel_input(ev["data"]["input_id"])
                return
            await asyncio.sleep(0.01)

    cancel_task = asyncio.create_task(_cancel_when_ready())
    result = await request_node_config_executor(
        {"node_name": "supabase", "preset": "supabase"},
        _build_context(db, project_id, user_id),
    )
    await cancel_task

    assert result["success"] is True
    assert result["cancelled"] is True
    assert result["timed_out"] is False
    # No audit entry on cancel
    assert patch_audit == []
    # node_config_cancelled emitted; resumed NOT emitted
    assert pubsub_recorder.by_type("node_config_cancelled") is not None
    assert pubsub_recorder.by_type("node_config_resumed") is None


# ---------------------------------------------------------------------------
# Edit mode
# ---------------------------------------------------------------------------


async def _run_edit(
    *,
    existing_env: dict,
    existing_encrypted: dict,
    submit_values: dict,
    pubsub_recorder: _EventRecorder,
    patch_manager_singleton: PendingUserInputManager,
    patch_audit: list[dict],
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict, MagicMock]:
    project_id = uuid4()
    user_id = uuid4()
    project = _make_project(project_id)
    container = _make_container(
        project_id=project_id,
        environment_vars=existing_env,
        encrypted_secrets=existing_encrypted,
    )

    db = MagicMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    pos_result = MagicMock()
    pos_result.all = MagicMock(return_value=[])
    db.execute = AsyncMock(return_value=pos_result)
    db.add = MagicMock()

    from app.agent.tools.node_config import request_node_config as rnc

    async def _fake_load_or_create(db_, **kwargs: Any) -> MagicMock:
        return container

    monkeypatch.setattr(rnc, "_load_or_create_container", _fake_load_or_create)

    from app.models import Container, Project

    async def _db_get(model_cls: type, _id: UUID) -> Any:
        if model_cls is Container:
            return container
        if model_cls is Project:
            return project
        return None

    db.get = AsyncMock(side_effect=_db_get)

    async def _submit_when_ready() -> None:
        for _ in range(200):
            ev = pubsub_recorder.by_type("user_input_required")
            if ev is not None:
                patch_manager_singleton.submit_input(ev["data"]["input_id"], submit_values)
                return
            await asyncio.sleep(0.01)

    submit_task = asyncio.create_task(_submit_when_ready())
    result = await request_node_config_executor(
        {
            "node_name": "supabase",
            "preset": "supabase",
            "mode": "edit",
            "container_id": str(container.id),
        },
        _build_context(db, project_id, user_id),
    )
    await submit_task
    return result, container


@pytest.mark.asyncio
async def test_edit_preserves_existing_secret_when_not_provided(
    pubsub_recorder: _EventRecorder,
    patch_manager_singleton: PendingUserInputManager,
    patch_audit: list[dict],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.deployment_encryption import get_deployment_encryption_service

    enc = get_deployment_encryption_service()
    original_cipher = enc.encrypt("original-anon-value-xyz")

    _, container = await _run_edit(
        existing_env={"SUPABASE_URL": "https://old.supabase.co"},
        existing_encrypted={"SUPABASE_ANON_KEY": original_cipher},
        submit_values={
            # Use the "__SET__" sentinel — tells the tool to keep existing.
            "SUPABASE_URL": "https://new.supabase.co",
            "SUPABASE_ANON_KEY": "__SET__",
        },
        pubsub_recorder=pubsub_recorder,
        patch_manager_singleton=patch_manager_singleton,
        patch_audit=patch_audit,
        monkeypatch=monkeypatch,
    )

    # URL updated, secret preserved (decrypt still yields original plaintext).
    assert container.environment_vars["SUPABASE_URL"] == "https://new.supabase.co"
    assert enc.decrypt(container.encrypted_secrets["SUPABASE_ANON_KEY"]) == (
        "original-anon-value-xyz"
    )


@pytest.mark.asyncio
async def test_edit_clears_secret_with_explicit_clear_flag(
    pubsub_recorder: _EventRecorder,
    patch_manager_singleton: PendingUserInputManager,
    patch_audit: list[dict],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.deployment_encryption import get_deployment_encryption_service

    enc = get_deployment_encryption_service()
    original_cipher = enc.encrypt("to-be-cleared-value-abc")

    _, container = await _run_edit(
        existing_env={},
        existing_encrypted={"SUPABASE_ANON_KEY": original_cipher},
        submit_values={"SUPABASE_ANON_KEY": {"clear": True}},
        pubsub_recorder=pubsub_recorder,
        patch_manager_singleton=patch_manager_singleton,
        patch_audit=patch_audit,
        monkeypatch=monkeypatch,
    )

    assert "SUPABASE_ANON_KEY" not in (container.encrypted_secrets or {})


@pytest.mark.asyncio
async def test_edit_rotates_secret_with_new_value(
    pubsub_recorder: _EventRecorder,
    patch_manager_singleton: PendingUserInputManager,
    patch_audit: list[dict],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.deployment_encryption import get_deployment_encryption_service

    enc = get_deployment_encryption_service()
    old_cipher = enc.encrypt("old-anon-value-xyz")

    _, container = await _run_edit(
        existing_env={},
        existing_encrypted={"SUPABASE_ANON_KEY": old_cipher},
        submit_values={"SUPABASE_ANON_KEY": "new-anon-value-qrstuv"},
        pubsub_recorder=pubsub_recorder,
        patch_manager_singleton=patch_manager_singleton,
        patch_audit=patch_audit,
        monkeypatch=monkeypatch,
    )

    new_cipher = container.encrypted_secrets["SUPABASE_ANON_KEY"]
    assert new_cipher != old_cipher
    assert enc.decrypt(new_cipher) == "new-anon-value-qrstuv"


# ---------------------------------------------------------------------------
# Invalid-mode guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_edit_without_container_id_errors(
    pubsub_recorder: _EventRecorder,
    patch_manager_singleton: PendingUserInputManager,
    patch_audit: list[dict],
) -> None:
    project_id = uuid4()
    user_id = uuid4()
    db = MagicMock()
    result = await request_node_config_executor(
        {"node_name": "x", "preset": "supabase", "mode": "edit"},
        _build_context(db, project_id, user_id),
    )
    assert result["success"] is False
    assert "container_id" in result["message"]
