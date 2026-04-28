"""Tests for ``GET /api/projects/{project_id}/config`` — the persistent
Config tab's source of truth.

Asserts:
  * Response shape: ``{services, deployment_providers}``.
  * One entry per container in the project.
  * Secret values are masked as the ``__SET__`` sentinel — plaintext
    NEVER appears.
  * Internal containers without a known preset get a synthesized schema
    built from their existing env-var keys (so they're still editable as
    cards).
  * ``pending_input_id`` cross-references an active agent pause; null
    otherwise.
  * Sorting: external services first, then internal containers,
    alphabetical within each group.
  * Auth: 403 for non-owner, 401/403 unauthenticated.
"""
from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest


_loop: asyncio.AbstractEventLoop | None = None


def _run(coro):
    """Persistent loop — see notes in ``test_node_config_router.py``."""
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
    return _loop.run_until_complete(coro)


def _reset_manager() -> None:
    from app.agent.tools import approval_manager as am

    am._manager = None


async def _create_project_with_containers(
    owner_id: UUID,
    *,
    containers: list[dict],
) -> tuple[UUID, list[UUID]]:
    """Create one project with N containers per ``containers`` spec.

    Each spec dict accepts: ``name``, ``deployment_mode``, ``container_type``,
    ``service_slug``, ``environment_vars``, ``encrypted_secrets``, ``status``.
    """
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
    cids: list[UUID] = []
    async with Session() as db:
        team_row = (
            await db.execute(
                select(TeamMembership).where(TeamMembership.user_id == owner_id).limit(1)
            )
        ).scalar_one()
        project = Project(
            id=uuid4(),
            name="config-agg-test",
            slug=f"config-agg-{uuid4().hex[:6]}",
            owner_id=owner_id,
            team_id=team_row.team_id,
        )
        db.add(project)
        await db.flush()

        for spec in containers:
            container = Container(
                id=uuid4(),
                project_id=project.id,
                name=spec["name"],
                directory=".",
                container_name=f"{project.slug}-{spec['name']}",
                container_type=spec.get("container_type", "service"),
                service_slug=spec.get("service_slug"),
                deployment_mode=spec.get("deployment_mode", "external"),
                environment_vars=spec.get("environment_vars") or {},
                encrypted_secrets=spec.get("encrypted_secrets"),
                status=spec.get("status", "connected"),
            )
            db.add(container)
            await db.flush()
            cids.append(container.id)
        await db.commit()
        pid = project.id
    await engine.dispose()
    return pid, cids


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_aggregation_requires_auth(api_client):
    _reset_manager()
    resp = api_client.get(f"/api/projects/{uuid4()}/config")
    assert resp.status_code in (401, 403)


@pytest.mark.integration
def test_aggregation_404_for_unknown_project(authenticated_client):
    _reset_manager()
    client, _ = authenticated_client
    resp = client.get(f"/api/projects/{uuid4()}/config")
    assert resp.status_code == 404


@pytest.mark.integration
def test_aggregation_403_for_non_owner(api_client_session, authenticated_client):
    _reset_manager()
    _, owner_user = authenticated_client
    project_id, _ = _run(
        _create_project_with_containers(
            UUID(owner_user["id"]),
            containers=[{"name": "supabase", "service_slug": "supabase"}],
        )
    )
    other_register = {
        "email": f"other-{uuid4().hex}@example.com",
        "password": "TestPassword123!",
        "name": "Other",
    }
    assert (
        api_client_session.post("/api/auth/register", json=other_register).status_code == 201
    )
    r = api_client_session.post(
        "/api/auth/jwt/login",
        data={
            "username": other_register["email"],
            "password": other_register["password"],
        },
    )
    token = r.json()["access_token"]
    resp = api_client_session.get(
        f"/api/projects/{project_id}/config",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code in (403, 404)


# ---------------------------------------------------------------------------
# Shape + masking
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_aggregation_returns_one_entry_per_container_with_masked_secrets(
    authenticated_client,
):
    _reset_manager()
    client, user_data = authenticated_client

    from app.services.deployment_encryption import get_deployment_encryption_service

    enc = get_deployment_encryption_service()
    cipher = enc.encrypt("super-secret-value-do-not-leak")

    project_id, cids = _run(
        _create_project_with_containers(
            UUID(user_data["id"]),
            containers=[
                {
                    "name": "supabase",
                    "service_slug": "supabase",
                    "environment_vars": {"SUPABASE_URL": "https://x.supabase.co"},
                    "encrypted_secrets": {"SUPABASE_ANON_KEY": cipher},
                },
                {
                    "name": "stripe",
                    "service_slug": "stripe",
                    "encrypted_secrets": {"STRIPE_SECRET_KEY": enc.encrypt("sk_test_xx")},
                },
            ],
        )
    )

    resp = client.get(f"/api/projects/{project_id}/config")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert "services" in data
    assert "deployment_providers" in data
    assert isinstance(data["deployment_providers"], list)

    assert len(data["services"]) == 2
    by_id = {s["container_id"]: s for s in data["services"]}
    assert set(by_id.keys()) == {str(cids[0]), str(cids[1])}

    supabase = by_id[str(cids[0])]
    assert supabase["preset"] == "supabase"
    assert supabase["deployment_mode"] == "external"
    assert supabase["initial_values"]["SUPABASE_URL"] == "https://x.supabase.co"
    # Secret masked, never plaintext
    assert supabase["initial_values"]["SUPABASE_ANON_KEY"] == "__SET__"

    # Critical: plaintext must not appear anywhere in the response body
    assert "super-secret-value-do-not-leak" not in resp.text
    assert "sk_test_xx" not in resp.text


@pytest.mark.integration
def test_aggregation_sorts_external_before_internal_then_alphabetical(
    authenticated_client,
):
    _reset_manager()
    client, user_data = authenticated_client
    project_id, _ = _run(
        _create_project_with_containers(
            UUID(user_data["id"]),
            containers=[
                # Mixed insert order; expect deterministic sort on read.
                {"name": "zeta-internal", "deployment_mode": "container", "service_slug": None},
                {"name": "stripe", "service_slug": "stripe", "deployment_mode": "external"},
                {"name": "alpha-internal", "deployment_mode": "container", "service_slug": None},
                {"name": "supabase", "service_slug": "supabase", "deployment_mode": "external"},
            ],
        )
    )
    resp = client.get(f"/api/projects/{project_id}/config")
    assert resp.status_code == 200, resp.text
    names = [s["container_name"] for s in resp.json()["services"]]
    # External services first (alphabetical), then internal (alphabetical).
    assert names == ["stripe", "supabase", "alpha-internal", "zeta-internal"]


@pytest.mark.integration
def test_aggregation_synthesizes_schema_for_unknown_internal_container(
    authenticated_client,
):
    """Internal container with no preset but existing env keys → synthetic
    schema so the user can still edit those keys from the Config tab."""
    _reset_manager()
    client, user_data = authenticated_client

    from app.services.deployment_encryption import get_deployment_encryption_service

    enc = get_deployment_encryption_service()
    project_id, _ = _run(
        _create_project_with_containers(
            UUID(user_data["id"]),
            containers=[
                {
                    "name": "custom-worker",
                    "deployment_mode": "container",
                    "service_slug": None,
                    "container_type": "base",
                    "environment_vars": {
                        "WORKER_QUEUE": "jobs",
                        "WORKER_REGION": "us-east-1",
                    },
                    "encrypted_secrets": {
                        "WORKER_API_TOKEN": enc.encrypt("wrk-token"),
                    },
                },
            ],
        )
    )
    resp = client.get(f"/api/projects/{project_id}/config")
    assert resp.status_code == 200, resp.text
    services = resp.json()["services"]
    assert len(services) == 1
    svc = services[0]
    assert svc["preset"] == "internal_container"
    field_keys = [f["key"] for f in svc["schema"]["fields"]]
    assert set(field_keys) == {"WORKER_QUEUE", "WORKER_REGION", "WORKER_API_TOKEN"}
    # Secret stays masked even on synthesized schemas.
    assert svc["initial_values"]["WORKER_API_TOKEN"] == "__SET__"
    assert "wrk-token" not in resp.text


@pytest.mark.integration
def test_aggregation_surfaces_pending_input_id_when_agent_paused(
    authenticated_client,
):
    """When the agent has registered a pending input for a container, the
    aggregated entry surfaces ``pending_input_id`` so the Config tab can
    flip the matching card into "Agent waiting" mode."""
    _reset_manager()
    client, user_data = authenticated_client
    project_id, cids = _run(
        _create_project_with_containers(
            UUID(user_data["id"]),
            containers=[{"name": "supabase", "service_slug": "supabase"}],
        )
    )

    from app.agent.tools.approval_manager import get_pending_input_manager

    manager = get_pending_input_manager()

    async def _create_pending() -> str:
        input_id = str(uuid4())
        await manager.create_input_request(
            input_id=input_id,
            project_id=str(project_id),
            chat_id="c1",
            container_id=str(cids[0]),
            schema_json={"fields": []},
            mode="create",
            ttl=60,
        )
        return input_id

    input_id = _run(_create_pending())

    resp = client.get(f"/api/projects/{project_id}/config")
    assert resp.status_code == 200, resp.text
    services = resp.json()["services"]
    assert len(services) == 1
    assert services[0]["pending_input_id"] == input_id

    # Cleanup so the manager doesn't bleed into other tests.
    manager._pending.pop(input_id, None)


@pytest.mark.integration
def test_aggregation_pending_input_id_is_null_when_not_paused(authenticated_client):
    _reset_manager()
    client, user_data = authenticated_client
    project_id, _ = _run(
        _create_project_with_containers(
            UUID(user_data["id"]),
            containers=[{"name": "supabase", "service_slug": "supabase"}],
        )
    )
    resp = client.get(f"/api/projects/{project_id}/config")
    assert resp.status_code == 200, resp.text
    assert resp.json()["services"][0]["pending_input_id"] is None


@pytest.mark.integration
def test_aggregation_resolves_rest_api_slug_to_full_schema(authenticated_client):
    """Regression — when an external service was created with
    ``preset='rest_api'``, the GET endpoint must resolve its schema back to
    the full rest_api preset, not silently fall through to the empty
    external_generic template (which would render as "No fields" in the UI)."""
    _reset_manager()
    client, user_data = authenticated_client
    project_id, _ = _run(
        _create_project_with_containers(
            UUID(user_data["id"]),
            containers=[
                {
                    "name": "OpenWeatherMap",
                    "service_slug": "rest_api",
                    "deployment_mode": "external",
                },
            ],
        )
    )
    resp = client.get(f"/api/projects/{project_id}/config")
    assert resp.status_code == 200, resp.text
    services = resp.json()["services"]
    assert len(services) == 1
    svc = services[0]
    assert svc["preset"] == "rest_api"
    field_keys = {f["key"] for f in svc["schema"]["fields"]}
    assert field_keys == {"API_BASE_URL", "API_KEY", "API_AUTH_HEADER"}


@pytest.mark.integration
def test_aggregation_merges_user_added_keys_into_schema(authenticated_client):
    """Powers the "+ Add field" UX: when the user adds a custom key not in
    the preset (e.g. ``OPENWEATHERMAP_DEFAULT_CITY`` on a rest_api card),
    the value lands in ``environment_vars``. The next GET must surface
    that key as a synthesized field so it's editable from the card —
    without this the saved value would orphan in the DB and disappear
    from the UI."""
    _reset_manager()
    client, user_data = authenticated_client

    from app.services.deployment_encryption import get_deployment_encryption_service

    enc = get_deployment_encryption_service()
    project_id, _ = _run(
        _create_project_with_containers(
            UUID(user_data["id"]),
            containers=[
                {
                    "name": "OpenWeatherMap",
                    "service_slug": "rest_api",
                    "deployment_mode": "external",
                    # API_BASE_URL is part of the preset; DEFAULT_CITY is
                    # user-added; CUSTOM_TOKEN is a user-added secret.
                    "environment_vars": {
                        "API_BASE_URL": "https://api.openweathermap.org",
                        "OPENWEATHERMAP_DEFAULT_CITY": "Boston",
                    },
                    "encrypted_secrets": {
                        "OPENWEATHERMAP_CUSTOM_TOKEN": enc.encrypt("custom-secret"),
                    },
                },
            ],
        )
    )
    resp = client.get(f"/api/projects/{project_id}/config")
    assert resp.status_code == 200, resp.text
    svc = resp.json()["services"][0]

    by_key = {f["key"]: f for f in svc["schema"]["fields"]}
    # Preset fields preserved
    assert "API_BASE_URL" in by_key
    assert "API_KEY" in by_key
    assert "API_AUTH_HEADER" in by_key
    # User-added fields synthesized
    assert by_key["OPENWEATHERMAP_DEFAULT_CITY"]["type"] == "text"
    assert by_key["OPENWEATHERMAP_DEFAULT_CITY"]["is_secret"] is False
    assert by_key["OPENWEATHERMAP_CUSTOM_TOKEN"]["type"] == "secret"
    assert by_key["OPENWEATHERMAP_CUSTOM_TOKEN"]["is_secret"] is True

    # Initial values include the user-added plaintext, with the secret masked.
    assert svc["initial_values"]["API_BASE_URL"] == "https://api.openweathermap.org"
    assert svc["initial_values"]["OPENWEATHERMAP_DEFAULT_CITY"] == "Boston"
    assert svc["initial_values"]["OPENWEATHERMAP_CUSTOM_TOKEN"] == "__SET__"
    # Critical: plaintext of the user-added secret never leaks.
    assert "custom-secret" not in resp.text


@pytest.mark.integration
def test_aggregation_resolves_external_generic_slug_to_empty_schema(
    authenticated_client,
):
    """``external_generic`` is the bespoke template — it has no built-in
    fields. The GET endpoint should still resolve it as ``external_generic``
    (not silently fall back), so the frontend can render an "Add field" UI
    or call request_node_config(mode='edit', field_overrides=...) later."""
    _reset_manager()
    client, user_data = authenticated_client
    project_id, _ = _run(
        _create_project_with_containers(
            UUID(user_data["id"]),
            containers=[
                {
                    "name": "Custom",
                    "service_slug": "external_generic",
                    "deployment_mode": "external",
                },
            ],
        )
    )
    resp = client.get(f"/api/projects/{project_id}/config")
    assert resp.status_code == 200, resp.text
    svc = resp.json()["services"][0]
    assert svc["preset"] == "external_generic"
    assert svc["schema"]["fields"] == []


@pytest.mark.integration
def test_aggregation_empty_project_returns_empty_services(authenticated_client):
    _reset_manager()
    client, user_data = authenticated_client
    project_id, _ = _run(
        _create_project_with_containers(UUID(user_data["id"]), containers=[])
    )
    resp = client.get(f"/api/projects/{project_id}/config")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["services"] == []
    assert body["deployment_providers"] == []
