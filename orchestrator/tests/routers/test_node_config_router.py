"""Integration tests for ``app.routers.node_config``.

Covers:
  * ``POST /api/chat/node-config/{input_id}/submit|cancel`` — auth, ownership,
    and manager resolution.
  * ``GET/PATCH /api/projects/{project_id}/containers/{container_id}/config``.
  * ``POST .../secrets/{key}/reveal`` — plaintext decrypt + audit write.

Uses the shared Postgres test DB (port 5433) and the authenticated_client
fixture. Fresh PendingUserInputManager state is created per test by resetting
the module-level singleton.
"""
from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_manager() -> None:
    """Force a fresh PendingUserInputManager singleton per test."""
    from app.agent.tools import approval_manager as am

    am._manager = None


async def _create_project_and_container(
    owner_id: UUID,
    *,
    encrypted_secrets: dict | None = None,
    environment_vars: dict | None = None,
) -> tuple[UUID, UUID]:
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    from sqlalchemy import select

    from app.models import Container, Project
    from app.models_team import TeamMembership

    # Own engine per call, bound to the current test loop — avoids leaking
    # asyncpg connections across the TestClient and test loops.
    engine = create_async_engine(
        "postgresql+asyncpg://tesslate_test:testpass@localhost:5433/tesslate_test",
        pool_pre_ping=True,
    )
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as db:
        # Every user has a personal team created at registration; fetch it so
        # the project's NOT NULL team_id is satisfied.
        team_row = (
            await db.execute(
                select(TeamMembership).where(TeamMembership.user_id == owner_id).limit(1)
            )
        ).scalar_one()

        project = Project(
            id=uuid4(),
            name="node-config-test",
            slug=f"node-config-test-{uuid4().hex[:6]}",
            owner_id=owner_id,
            team_id=team_row.team_id,
        )
        db.add(project)
        await db.flush()

        container = Container(
            id=uuid4(),
            project_id=project.id,
            name="supabase",
            directory=".",
            container_name=f"{project.slug}-supabase",
            container_type="service",
            service_slug="supabase",
            deployment_mode="external",
            environment_vars=environment_vars or {},
            encrypted_secrets=encrypted_secrets,
            status="connected",
        )
        db.add(container)
        await db.commit()
        pid, cid = project.id, container.id
    await engine.dispose()
    return pid, cid


_loop: asyncio.AbstractEventLoop | None = None


def _run(coro):
    """Run ``coro`` on a persistent test-session loop.

    asyncpg connections are loop-bound. The TestClient's ``portal`` runs in
    its own loop, and if we spin up fresh loops per helper call the connection
    pool created by AsyncSessionLocal will leak tasks bound to the dying
    loop. One persistent loop for all DB helpers avoids that.
    """
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
    return _loop.run_until_complete(coro)


# ---------------------------------------------------------------------------
# Submit / Cancel
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_submit_requires_auth(api_client):
    _reset_manager()
    response = api_client.post(
        "/api/chat/node-config/some-id/submit",
        json={"values": {}},
    )
    assert response.status_code in (401, 403)


@pytest.mark.integration
def test_submit_unknown_input_returns_404(authenticated_client):
    _reset_manager()
    client, _ = authenticated_client
    response = client.post(
        "/api/chat/node-config/unknown-id/submit",
        json={"values": {"FOO": "bar"}},
    )
    assert response.status_code == 404


@pytest.mark.integration
def test_submit_resolves_pending_input(authenticated_client):
    _reset_manager()
    client, user_data = authenticated_client
    project_id, container_id = _run(
        _create_project_and_container(UUID(user_data["id"]))
    )

    from app.agent.tools.approval_manager import get_pending_input_manager

    manager = get_pending_input_manager()

    async def _create() -> str:
        input_id = str(uuid4())
        await manager.create_input_request(
            input_id=input_id,
            project_id=str(project_id),
            chat_id="chat-x",
            container_id=str(container_id),
            schema_json={"fields": []},
            mode="create",
            ttl=60,
        )
        return input_id

    input_id = _run(_create())

    response = client.post(
        f"/api/chat/node-config/{input_id}/submit",
        json={"values": {"SUPABASE_URL": "https://x.supabase.co"}},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True}

    # Manager future was delivered
    assert input_id not in manager._pending


@pytest.mark.integration
def test_submit_rejects_non_owner(api_client_session, authenticated_client):
    _reset_manager()
    owner_client, owner_user = authenticated_client
    project_id, container_id = _run(
        _create_project_and_container(UUID(owner_user["id"]))
    )

    from app.agent.tools.approval_manager import get_pending_input_manager

    manager = get_pending_input_manager()

    async def _create() -> str:
        input_id = str(uuid4())
        await manager.create_input_request(
            input_id=input_id,
            project_id=str(project_id),
            chat_id="chat-x",
            container_id=str(container_id),
            schema_json={"fields": []},
            mode="create",
            ttl=60,
        )
        return input_id

    input_id = _run(_create())

    # Register a DIFFERENT user and attempt to submit
    other_register = {
        "email": f"other-{uuid4().hex}@example.com",
        "password": "TestPassword123!",
        "name": "Other",
    }
    r = api_client_session.post("/api/auth/register", json=other_register)
    assert r.status_code == 201
    r = api_client_session.post(
        "/api/auth/jwt/login",
        data={"username": other_register["email"], "password": other_register["password"]},
    )
    assert r.status_code == 200
    token = r.json()["access_token"]

    response = api_client_session.post(
        f"/api/chat/node-config/{input_id}/submit",
        json={"values": {"FOO": "bar"}},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code in (403, 404)


@pytest.mark.integration
def test_cancel_resolves_pending_input(authenticated_client):
    _reset_manager()
    client, user_data = authenticated_client
    project_id, container_id = _run(
        _create_project_and_container(UUID(user_data["id"]))
    )
    from app.agent.tools.approval_manager import get_pending_input_manager

    manager = get_pending_input_manager()

    async def _create() -> str:
        input_id = str(uuid4())
        await manager.create_input_request(
            input_id=input_id,
            project_id=str(project_id),
            chat_id="c",
            container_id=str(container_id),
            schema_json={},
            mode="create",
            ttl=60,
        )
        return input_id

    input_id = _run(_create())
    resp = client.post(f"/api/chat/node-config/{input_id}/cancel")
    assert resp.status_code == 200
    assert input_id not in manager._pending


# ---------------------------------------------------------------------------
# GET /projects/{pid}/containers/{cid}/config
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_get_config_masks_secret_values_as_sentinel(authenticated_client):
    _reset_manager()
    client, user_data = authenticated_client

    from app.services.deployment_encryption import get_deployment_encryption_service

    enc = get_deployment_encryption_service()
    cipher = enc.encrypt("super-secret-value")

    project_id, container_id = _run(
        _create_project_and_container(
            UUID(user_data["id"]),
            environment_vars={"SUPABASE_URL": "https://x.supabase.co"},
            encrypted_secrets={"SUPABASE_ANON_KEY": cipher},
        )
    )

    resp = client.get(
        f"/api/projects/{project_id}/containers/{container_id}/config"
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["preset"] == "supabase"
    # Plaintext values visible for non-secrets
    assert data["values"]["SUPABASE_URL"] == "https://x.supabase.co"
    # Secret value masked as the __SET__ sentinel — never the plaintext
    assert data["values"]["SUPABASE_ANON_KEY"] == "__SET__"
    # Critical: the plaintext must never appear in the response
    assert "super-secret-value" not in resp.text


@pytest.mark.integration
def test_get_config_403_for_non_owner(api_client_session, authenticated_client):
    _reset_manager()
    _, owner_user = authenticated_client
    project_id, container_id = _run(
        _create_project_and_container(UUID(owner_user["id"]))
    )

    # Register a different user
    other_register = {
        "email": f"other-{uuid4().hex}@example.com",
        "password": "TestPassword123!",
        "name": "Other",
    }
    assert api_client_session.post("/api/auth/register", json=other_register).status_code == 201
    r = api_client_session.post(
        "/api/auth/jwt/login",
        data={"username": other_register["email"], "password": other_register["password"]},
    )
    token = r.json()["access_token"]

    resp = api_client_session.get(
        f"/api/projects/{project_id}/containers/{container_id}/config",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code in (403, 404)


# ---------------------------------------------------------------------------
# PATCH /projects/{pid}/containers/{cid}/config
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_patch_config_applies_merge_semantics(authenticated_client):
    _reset_manager()
    client, user_data = authenticated_client
    project_id, container_id = _run(
        _create_project_and_container(UUID(user_data["id"]))
    )

    resp = client.patch(
        f"/api/projects/{project_id}/containers/{container_id}/config",
        json={
            "preset": "supabase",
            "values": {
                "SUPABASE_URL": "https://new.supabase.co",
                "SUPABASE_ANON_KEY": "anon-secret-123456",
            },
        },
    )
    assert resp.status_code == 200, resp.text
    summary = resp.json()
    assert "SUPABASE_URL" in summary["updated_keys"]
    assert "SUPABASE_ANON_KEY" in summary["rotated_secrets"]

    # Verify DB state: secret encrypted, non-secret plaintext
    async def _verify() -> None:
        from sqlalchemy.ext.asyncio import (
            AsyncSession,
            async_sessionmaker,
            create_async_engine,
        )

        from app.models import Container
        from app.services.deployment_encryption import (
            get_deployment_encryption_service,
        )

        engine = create_async_engine(
            "postgresql+asyncpg://tesslate_test:testpass@localhost:5433/tesslate_test",
            pool_pre_ping=True,
        )
        Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with Session() as db:
            container = await db.get(Container, container_id)
            assert container is not None
            assert container.environment_vars["SUPABASE_URL"] == "https://new.supabase.co"
            assert "SUPABASE_ANON_KEY" not in (container.environment_vars or {})
            enc = get_deployment_encryption_service()
            assert (
                enc.decrypt(container.encrypted_secrets["SUPABASE_ANON_KEY"])
                == "anon-secret-123456"
            )
            assert container.needs_restart is True
        await engine.dispose()

    _run(_verify())


# ---------------------------------------------------------------------------
# Reveal secret
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_reveal_secret_returns_plaintext_for_owner(authenticated_client):
    _reset_manager()
    client, user_data = authenticated_client

    from app.services.deployment_encryption import get_deployment_encryption_service

    enc = get_deployment_encryption_service()
    cipher = enc.encrypt("revealed-plaintext-value")

    project_id, container_id = _run(
        _create_project_and_container(
            UUID(user_data["id"]),
            encrypted_secrets={"SUPABASE_ANON_KEY": cipher},
        )
    )

    resp = client.post(
        f"/api/projects/{project_id}/containers/{container_id}"
        f"/secrets/SUPABASE_ANON_KEY/reveal"
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"value": "revealed-plaintext-value"}


@pytest.mark.integration
def test_reveal_missing_key_returns_404(authenticated_client):
    _reset_manager()
    client, user_data = authenticated_client
    project_id, container_id = _run(
        _create_project_and_container(UUID(user_data["id"]))
    )
    resp = client.post(
        f"/api/projects/{project_id}/containers/{container_id}"
        f"/secrets/DOES_NOT_EXIST/reveal"
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Restart-on-save hook
# ---------------------------------------------------------------------------


async def _create_consumer_with_env_injection(
    project_id: UUID,
    source_container_id: UUID,
    *,
    consumer_name: str = "backend",
    consumer_deployment_mode: str = "container",
) -> UUID:
    """Add a sibling container connected to ``source`` via env_injection."""
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    from app.models import Container, ContainerConnection

    engine = create_async_engine(
        "postgresql+asyncpg://tesslate_test:testpass@localhost:5433/tesslate_test",
        pool_pre_ping=True,
    )
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as db:
        consumer = Container(
            id=uuid4(),
            project_id=project_id,
            name=consumer_name,
            directory=".",
            container_name=f"proj-{consumer_name}",
            container_type="base",
            deployment_mode=consumer_deployment_mode,
            environment_vars={},
            status="stopped",
        )
        db.add(consumer)
        await db.flush()
        connection = ContainerConnection(
            id=uuid4(),
            project_id=project_id,
            source_container_id=source_container_id,
            target_container_id=consumer.id,
            connector_type="env_injection",
            config={},
        )
        db.add(connection)
        await db.commit()
        consumer_id = consumer.id
    await engine.dispose()
    return consumer_id


@pytest.mark.integration
def test_patch_dispatches_restart_to_env_injection_consumer(
    authenticated_client, monkeypatch
):
    """PATCHing an external service that's wired into a container via
    env_injection should schedule a restart of that consumer and emit a
    `containers_restarting` SSE event with the consumer in ``restart_target_ids``.
    """
    _reset_manager()
    client, user_data = authenticated_client
    project_id, source_id = _run(
        _create_project_and_container(UUID(user_data["id"]))
    )
    consumer_id = _run(_create_consumer_with_env_injection(project_id, source_id))

    # Replace the orchestrator-touching restart with a no-op so we don't
    # actually try to start docker containers in tests. We assert
    # `dispatch_restart_after_config_change` correctly identifies + schedules.
    scheduled: list[UUID] = []

    async def _fake_restart_one(container_id, *args, **kwargs):
        scheduled.append(container_id)

    from app.routers import node_config as node_config_router

    monkeypatch.setattr(node_config_router, "_restart_one", _fake_restart_one)

    # Capture the SSE event emitted on restart dispatch.
    class _Recorder:
        def __init__(self) -> None:
            self.events: list[tuple[str, dict]] = []

        async def publish_agent_event(self, target: str, event: dict) -> None:
            self.events.append((target, event))

    recorder = _Recorder()
    from app.services import pubsub as pubsub_module

    monkeypatch.setattr(pubsub_module, "get_pubsub", lambda: recorder)

    resp = client.patch(
        f"/api/projects/{project_id}/containers/{source_id}/config",
        json={
            "preset": "supabase",
            "values": {
                "SUPABASE_URL": "https://restart.supabase.co",
                "SUPABASE_ANON_KEY": "anon-restart-key-1234",
            },
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Restart payload merged into the response shape
    assert consumer_id is not None
    assert str(consumer_id) in body["restart_target_ids"]
    assert "backend" in body["container_names"]

    # Background restart task fired against the consumer, not the source
    # (source is external — we never restart externals).
    # The asyncio.create_task is fire-and-forget; flush the loop briefly.
    async def _drain() -> None:
        for _ in range(10):
            if scheduled:
                return
            await asyncio.sleep(0.01)

    _run(_drain())
    assert consumer_id in scheduled
    assert source_id not in scheduled  # external source is never a target

    # And a `containers_restarting` event was published on the project channel.
    types = [ev[1].get("type") for ev in recorder.events]
    assert "containers_restarting" in types
    restart_ev = next(ev[1] for ev in recorder.events if ev[1]["type"] == "containers_restarting")
    assert str(consumer_id) in restart_ev["data"]["restart_target_ids"]


@pytest.mark.integration
def test_patch_internal_container_restarts_itself(authenticated_client, monkeypatch):
    """Editing env on an internal container (deployment_mode=container) restarts
    that container itself — even with no env_injection consumers."""
    _reset_manager()
    client, user_data = authenticated_client

    # Build an internal Postgres-style container (no preset; synthetic schema).
    async def _create_internal() -> tuple[UUID, UUID]:
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import (
            AsyncSession,
            async_sessionmaker,
            create_async_engine,
        )

        from app.models import Container, Project
        from app.models_team import TeamMembership

        engine = create_async_engine(
            "postgresql+asyncpg://tesslate_test:testpass@localhost:5433/tesslate_test",
            pool_pre_ping=True,
        )
        Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with Session() as db:
            team_row = (
                await db.execute(
                    select(TeamMembership)
                    .where(TeamMembership.user_id == UUID(user_data["id"]))
                    .limit(1)
                )
            ).scalar_one()
            project = Project(
                id=uuid4(),
                name="internal-restart-test",
                slug=f"internal-restart-{uuid4().hex[:6]}",
                owner_id=UUID(user_data["id"]),
                team_id=team_row.team_id,
            )
            db.add(project)
            await db.flush()
            container = Container(
                id=uuid4(),
                project_id=project.id,
                name="postgres",
                directory=".",
                container_name=f"{project.slug}-postgres",
                container_type="base",
                deployment_mode="container",
                environment_vars={"POSTGRES_DB": "old"},
                status="running",
            )
            db.add(container)
            await db.commit()
            ids = (project.id, container.id)
        await engine.dispose()
        return ids

    project_id, container_id = _run(_create_internal())

    scheduled: list[UUID] = []

    async def _fake_restart_one(cid, *args, **kwargs):
        scheduled.append(cid)

    from app.routers import node_config as node_config_router

    monkeypatch.setattr(node_config_router, "_restart_one", _fake_restart_one)

    class _Recorder:
        def __init__(self) -> None:
            self.events: list[dict] = []

        async def publish_agent_event(self, _target, event):
            self.events.append(event)

    recorder = _Recorder()
    from app.services import pubsub as pubsub_module

    monkeypatch.setattr(pubsub_module, "get_pubsub", lambda: recorder)

    resp = client.patch(
        f"/api/projects/{project_id}/containers/{container_id}/config",
        json={
            # No preset — exercise the synthetic-schema path on edit.
            "overrides": [
                {"key": "POSTGRES_DB", "label": "DB", "type": "text"},
            ],
            "values": {"POSTGRES_DB": "newdb"},
        },
    )
    assert resp.status_code == 200, resp.text
    assert str(container_id) in resp.json()["restart_target_ids"]

    async def _drain() -> None:
        for _ in range(10):
            if scheduled:
                return
            await asyncio.sleep(0.01)

    _run(_drain())
    assert container_id in scheduled


@pytest.mark.integration
def test_patch_external_with_no_consumers_schedules_no_restarts(
    authenticated_client, monkeypatch
):
    """External service with zero env_injection consumers → no restart targets,
    no ``containers_restarting`` event."""
    _reset_manager()
    client, user_data = authenticated_client
    project_id, container_id = _run(
        _create_project_and_container(UUID(user_data["id"]))
    )

    scheduled: list[UUID] = []

    async def _fake_restart_one(cid, *args, **kwargs):
        scheduled.append(cid)

    from app.routers import node_config as node_config_router

    monkeypatch.setattr(node_config_router, "_restart_one", _fake_restart_one)

    class _Recorder:
        def __init__(self) -> None:
            self.events: list[dict] = []

        async def publish_agent_event(self, _target, event):
            self.events.append(event)

    recorder = _Recorder()
    from app.services import pubsub as pubsub_module

    monkeypatch.setattr(pubsub_module, "get_pubsub", lambda: recorder)

    resp = client.patch(
        f"/api/projects/{project_id}/containers/{container_id}/config",
        json={
            "preset": "supabase",
            "values": {"SUPABASE_URL": "https://lonely.supabase.co"},
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["restart_target_ids"] == []
    assert body["container_names"] == []

    # Give any (non-)scheduled tasks a tick — there should be none.
    async def _settle() -> None:
        await asyncio.sleep(0.02)

    _run(_settle())
    assert scheduled == []

    types = [ev.get("type") for ev in recorder.events]
    assert "containers_restarting" not in types


@pytest.mark.integration
def test_patch_with_no_changed_keys_skips_restart_dispatch(
    authenticated_client, monkeypatch
):
    """If the merge produced an empty ``updated_keys`` set (e.g. only the
    sentinel was sent), restart dispatch is a no-op — neither targets nor
    SSE event."""
    _reset_manager()
    client, user_data = authenticated_client
    project_id, source_id = _run(
        _create_project_and_container(UUID(user_data["id"]))
    )
    # Add a consumer so we'd notice if the dispatch fired incorrectly.
    _run(_create_consumer_with_env_injection(project_id, source_id))

    scheduled: list[UUID] = []

    async def _fake_restart_one(cid, *args, **kwargs):
        scheduled.append(cid)

    from app.routers import node_config as node_config_router

    monkeypatch.setattr(node_config_router, "_restart_one", _fake_restart_one)

    class _Recorder:
        def __init__(self) -> None:
            self.events: list[dict] = []

        async def publish_agent_event(self, _target, event):
            self.events.append(event)

    recorder = _Recorder()
    from app.services import pubsub as pubsub_module

    monkeypatch.setattr(pubsub_module, "get_pubsub", lambda: recorder)

    # Submit only the sentinel for the secret + omit URL — no changes apply.
    resp = client.patch(
        f"/api/projects/{project_id}/containers/{source_id}/config",
        json={
            "preset": "supabase",
            "values": {"SUPABASE_ANON_KEY": "__SET__"},
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["updated_keys"] == []
    assert body["restart_target_ids"] == []

    async def _settle() -> None:
        await asyncio.sleep(0.02)

    _run(_settle())
    assert scheduled == []
    assert "containers_restarting" not in [ev.get("type") for ev in recorder.events]


@pytest.mark.integration
def test_reveal_rejects_external_api_key_auth(authenticated_client):
    """Plan invariant: reveal is user-JWT-only. A session holding an
    ExternalAPIKey must be rejected with 403 even if the underlying user
    owns the project."""
    _reset_manager()
    client, user_data = authenticated_client

    from app.services.deployment_encryption import get_deployment_encryption_service

    enc = get_deployment_encryption_service()
    cipher = enc.encrypt("must-not-be-revealed")

    project_id, container_id = _run(
        _create_project_and_container(
            UUID(user_data["id"]),
            encrypted_secrets={"SUPABASE_ANON_KEY": cipher},
        )
    )

    # Override the JWT dependency to simulate an API-key-authenticated user
    # (current_active_user returns a User with ._api_key_record set by
    # auth_external when the bearer token is an API key).
    from app.main import app
    from app.models import User
    from app.users import current_active_user

    async def _api_key_user():
        user = User(
            id=UUID(user_data["id"]),
            email=user_data["email"],
            hashed_password="",
            is_active=True,
            is_superuser=False,
            is_verified=True,
        )
        user._api_key_record = object()  # any truthy sentinel
        return user

    app.dependency_overrides[current_active_user] = _api_key_user
    try:
        resp = client.post(
            f"/api/projects/{project_id}/containers/{container_id}"
            f"/secrets/SUPABASE_ANON_KEY/reveal"
        )
    finally:
        app.dependency_overrides.pop(current_active_user, None)

    assert resp.status_code == 403, resp.text
    assert "api key" in resp.json()["detail"].lower()
