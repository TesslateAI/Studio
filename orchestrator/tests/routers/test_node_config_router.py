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
