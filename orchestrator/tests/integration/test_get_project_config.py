"""Unit tests for the ``get_project_config`` agent tool.

Read-only inspection of every container in the project. Critical security
assertion: it returns key names only — no plaintext values, no ``__SET__``
sentinels, nothing the agent could leak into chat or code.
"""
from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest


_loop: asyncio.AbstractEventLoop | None = None


def _run(coro):
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
    return _loop.run_until_complete(coro)


async def _create_project_with_containers(
    owner_id: UUID,
    *,
    containers: list[dict],
) -> tuple[UUID, list[UUID]]:
    """Same shape as ``test_config_aggregation`` helper. Inlined to keep the
    agent-tool tests self-contained — the path under test is different."""
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
            name="agent-tool-test",
            slug=f"agent-tool-{uuid4().hex[:6]}",
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


async def _exec(project_id: UUID) -> dict:
    """Invoke the executor with a fresh DB session bound to the test loop."""
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    from app.agent.tools.node_config.get_project_config import (
        get_project_config_executor,
    )

    engine = create_async_engine(
        "postgresql+asyncpg://tesslate_test:testpass@localhost:5433/tesslate_test",
        pool_pre_ping=True,
    )
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as db:
        result = await get_project_config_executor(
            {},
            {"db": db, "project_id": project_id, "user_id": uuid4()},
        )
    await engine.dispose()
    return result


@pytest.mark.integration
def test_lists_external_and_internal_with_key_names_only(authenticated_client):
    _, user_data = authenticated_client

    from app.services.deployment_encryption import get_deployment_encryption_service

    enc = get_deployment_encryption_service()
    project_id, cids = _run(
        _create_project_with_containers(
            UUID(user_data["id"]),
            containers=[
                {
                    "name": "supabase",
                    "service_slug": "supabase",
                    "deployment_mode": "external",
                    "environment_vars": {"SUPABASE_URL": "https://x.supabase.co"},
                    "encrypted_secrets": {
                        "SUPABASE_ANON_KEY": enc.encrypt("super-secret-anon-do-not-leak"),
                    },
                },
                {
                    "name": "redis",
                    "deployment_mode": "container",
                    "container_type": "base",
                    "service_slug": None,
                    "environment_vars": {"REDIS_PORT": "6379"},
                },
            ],
        )
    )

    result = _run(_exec(project_id))
    assert result["success"] is True
    services = result["services"]
    assert len(services) == 2

    by_id = {s["container_id"]: s for s in services}
    supabase = by_id[str(cids[0])]
    redis = by_id[str(cids[1])]

    # External service surfaces preset + secret key names but not values.
    assert supabase["preset"] == "supabase"
    assert supabase["deployment_mode"] == "external"
    assert "SUPABASE_URL" in supabase["configured_env_keys"]
    assert "SUPABASE_ANON_KEY" in supabase["configured_secret_keys"]
    assert "SUPABASE_ANON_KEY" not in supabase["configured_env_keys"]

    # Internal container without a preset → external_generic fallback;
    # configured_env_keys reflects what's actually stored.
    assert redis["deployment_mode"] == "container"
    assert "REDIS_PORT" in redis["configured_env_keys"]
    assert redis["configured_secret_keys"] == []


@pytest.mark.integration
def test_never_leaks_plaintext_or_sentinel(authenticated_client):
    """The agent-side tool must never expose the encrypted ciphertext, the
    plaintext, OR the ``__SET__`` sentinel — only key names."""
    _, user_data = authenticated_client

    from app.services.deployment_encryption import get_deployment_encryption_service

    enc = get_deployment_encryption_service()
    project_id, _ = _run(
        _create_project_with_containers(
            UUID(user_data["id"]),
            containers=[
                {
                    "name": "stripe",
                    "service_slug": "stripe",
                    "encrypted_secrets": {
                        "STRIPE_SECRET_KEY": enc.encrypt(
                            "sk_test_PLAINTEXT_MUST_NOT_LEAK"
                        ),
                    },
                },
            ],
        )
    )
    result = _run(_exec(project_id))
    payload = repr(result)
    assert "sk_test_PLAINTEXT_MUST_NOT_LEAK" not in payload
    assert "__SET__" not in payload
    # Encrypted ciphertext must never appear either.
    assert "gAAAA" not in payload  # Fernet ciphertext prefix


@pytest.mark.integration
def test_sorts_external_first_then_internal_alphabetical(authenticated_client):
    _, user_data = authenticated_client
    project_id, _ = _run(
        _create_project_with_containers(
            UUID(user_data["id"]),
            containers=[
                {"name": "zeta", "deployment_mode": "container", "service_slug": None},
                {"name": "stripe", "service_slug": "stripe", "deployment_mode": "external"},
                {"name": "alpha", "deployment_mode": "container", "service_slug": None},
                {"name": "supabase", "service_slug": "supabase", "deployment_mode": "external"},
            ],
        )
    )
    result = _run(_exec(project_id))
    names = [s["container_name"] for s in result["services"]]
    assert names == ["stripe", "supabase", "alpha", "zeta"]


@pytest.mark.integration
def test_empty_project_returns_empty_services(authenticated_client):
    _, user_data = authenticated_client
    project_id, _ = _run(
        _create_project_with_containers(UUID(user_data["id"]), containers=[])
    )
    result = _run(_exec(project_id))
    assert result["success"] is True
    assert result["services"] == []
    assert result["deployment_providers"] == []


@pytest.mark.integration
def test_missing_context_returns_error():
    from app.agent.tools.node_config.get_project_config import (
        get_project_config_executor,
    )

    async def _go() -> dict:
        return await get_project_config_executor({}, {})

    result = _run(_go())
    assert result["success"] is False
    assert "context" in result["message"].lower()
