"""Integration tests for the built-in skill mutation guards.

Built-ins must be unreachable from every user/admin UI mutation path:
  * PATCH /agents/{id}  — rejected 403
  * DELETE /agents/{id} — rejected 403
  * Attempt to inject ``is_builtin=True`` via any payload field — silently
    dropped before hitting the DB
  * POST /agents/{id}/fork — allowed; forked row is NOT a built-in

The one write path that sets ``is_builtin=True`` is seed code, which is
exercised end-to-end by the integration test below via direct DB write.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import MarketplaceAgent, User, UserPurchasedAgent

# Mixing the app's AsyncSessionLocal with the TestClient's own event loop
# produces "Future attached to a different loop" errors, so we use a
# dedicated engine + run every helper on a short-lived event loop via
# ``asyncio.run()``. That loop terminates before the TestClient's request
# runs, so no Future leaks across loops.
_ASYNC_DB_URL = "postgresql+asyncpg://tesslate_test:testpass@localhost:5433/tesslate_test"


def _run_db(coro_fn, *args, **kwargs):
    """Run a DB coroutine on a throwaway event loop with a fresh engine.

    A new engine per call keeps asyncpg's connection pool bound to the loop
    that's about to close, avoiding cross-loop coupling.
    """
    async def _inner():
        engine = create_async_engine(_ASYNC_DB_URL, pool_pre_ping=False)
        try:
            session_maker = async_sessionmaker(engine, expire_on_commit=False)
            async with session_maker() as db:
                return await coro_fn(db, *args, **kwargs)
        finally:
            await engine.dispose()

    return asyncio.run(_inner())


@pytest.fixture
def admin_client(authenticated_client):
    """Promote the authenticated user to superuser for admin-endpoint tests."""
    client, user_data = authenticated_client

    async def _promote(db: AsyncSession) -> None:
        result = await db.execute(
            select(User).where(User.id == uuid.UUID(user_data["id"]))
        )
        user = result.scalar_one()
        user.is_superuser = True
        await db.commit()

    _run_db(_promote)
    return client


def _insert_builtin_skill(slug: str | None = None, is_forkable: bool = False) -> str:
    async def _do(db: AsyncSession) -> str:
        agent = MarketplaceAgent(
            name="Test Builtin Skill",
            slug=slug or f"test-builtin-{uuid.uuid4().hex[:8]}",
            description="guard-test builtin",
            category="infrastructure",
            item_type="skill",
            pricing_type="free",
            price=0,
            is_active=True,
            is_published=True,
            is_forkable=is_forkable,
            is_builtin=True,
            skill_body="plain body, no markers",
            created_by_user_id=None,
            icon="🧪",
        )
        db.add(agent)
        await db.commit()
        await db.refresh(agent)
        return str(agent.id)

    return _run_db(_do)


def _insert_regular_user_skill(user_id: uuid.UUID) -> str:
    async def _do(db: AsyncSession) -> str:
        agent = MarketplaceAgent(
            name="User Skill",
            slug=f"user-skill-{uuid.uuid4().hex[:8]}",
            description="not a builtin",
            category="custom",
            item_type="skill",
            pricing_type="free",
            price=0,
            is_active=True,
            is_published=False,
            is_forkable=False,
            forked_by_user_id=user_id,
            skill_body="user-authored body",
            icon="📝",
        )
        db.add(agent)
        await db.commit()
        await db.refresh(agent)
        return str(agent.id)

    return _run_db(_do)


def _get_is_builtin(skill_id: str) -> bool:
    async def _do(db: AsyncSession) -> bool:
        result = await db.execute(
            select(MarketplaceAgent.is_builtin).where(
                MarketplaceAgent.id == uuid.UUID(skill_id)
            )
        )
        return bool(result.scalar_one())

    return _run_db(_do)


def _get_name_and_is_builtin(skill_id: str) -> tuple[str, bool]:
    async def _do(db: AsyncSession) -> tuple[str, bool]:
        row = await db.execute(
            select(MarketplaceAgent.name, MarketplaceAgent.is_builtin).where(
                MarketplaceAgent.id == uuid.UUID(skill_id)
            )
        )
        name, ib = row.one()
        return name, bool(ib)

    return _run_db(_do)


def _row_exists(skill_id: str) -> bool:
    async def _do(db: AsyncSession) -> bool:
        result = await db.execute(
            select(MarketplaceAgent.id).where(
                MarketplaceAgent.id == uuid.UUID(skill_id)
            )
        )
        return result.scalar_one_or_none() is not None

    return _run_db(_do)


def _give_user_agent(user_id: uuid.UUID, skill_id: str) -> None:
    async def _do(db: AsyncSession) -> None:
        purchase = UserPurchasedAgent(
            user_id=user_id,
            agent_id=uuid.UUID(skill_id),
            purchase_type="free",
            is_active=True,
        )
        db.add(purchase)
        await db.commit()

    _run_db(_do)


# ---------------------------------------------------------------------------
# User PATCH guard
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_user_patch_rejects_builtin(authenticated_client):
    client, user_data = authenticated_client
    skill_id = _insert_builtin_skill()
    _give_user_agent(uuid.UUID(user_data["id"]), skill_id)

    resp = client.patch(
        f"/api/marketplace/agents/{skill_id}",
        json={"name": "Hacker Rename"},
    )
    assert resp.status_code == 403, resp.text
    assert "seed code" in resp.json()["detail"].lower()

    # Nothing on the row should have changed.
    name, is_builtin = _get_name_and_is_builtin(skill_id)
    assert name == "Test Builtin Skill"
    assert is_builtin is True


@pytest.mark.integration
def test_user_patch_pops_is_builtin_on_regular_skill(authenticated_client):
    """``is_builtin=True`` in a user payload is stripped, even on their own skill."""
    client, user_data = authenticated_client
    skill_id = _insert_regular_user_skill(uuid.UUID(user_data["id"]))
    _give_user_agent(uuid.UUID(user_data["id"]), skill_id)

    resp = client.patch(
        f"/api/marketplace/agents/{skill_id}",
        json={"name": "Renamed", "is_builtin": True},
    )
    # Not a built-in → the name update should succeed. The handler only
    # updates whitelisted fields explicitly; is_builtin is popped first.
    assert resp.status_code in (200, 204), resp.text
    # DB row still has is_builtin=False.
    assert _get_is_builtin(skill_id) is False


# ---------------------------------------------------------------------------
# User DELETE guard
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_user_delete_rejects_builtin(authenticated_client):
    client, user_data = authenticated_client
    skill_id = _insert_builtin_skill()
    _give_user_agent(uuid.UUID(user_data["id"]), skill_id)

    resp = client.delete(f"/api/marketplace/agents/{skill_id}")
    assert resp.status_code == 403, resp.text

    # Row still exists.
    assert _row_exists(skill_id)


# ---------------------------------------------------------------------------
# Fork semantics — allowed, but fork is NOT a built-in
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_fork_of_builtin_produces_non_builtin(authenticated_client):
    """Forking a forkable built-in creates a new row with is_builtin=False.

    Built-in skills in seed are typically ``is_forkable=False`` (so the fork
    endpoint returns 403). We insert a fork-allowed built-in here so we can
    exercise the fork path. The invariant under test is: if a fork IS
    permitted, the resulting child row is never a built-in.
    """
    parent_id = _insert_builtin_skill(is_forkable=True)

    client, _user = authenticated_client
    resp = client.post(f"/api/marketplace/agents/{parent_id}/fork")
    assert resp.status_code == 200, resp.text
    forked_id = resp.json()["agent_id"]

    # Parent is still a built-in.
    assert _get_is_builtin(parent_id) is True
    # Fork is NOT a built-in.
    assert _get_is_builtin(forked_id) is False


# ---------------------------------------------------------------------------
# Admin PUT guard
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_admin_put_rejects_builtin(admin_client):
    """Admin PUT /api/admin/agents/{id} must also refuse built-ins."""
    client = admin_client
    skill_id = _insert_builtin_skill()

    resp = client.put(
        f"/api/admin/agents/{skill_id}",
        json={"name": "Admin Rename", "description": "xxx"},
    )
    assert resp.status_code == 403, resp.text
    assert "seed" in resp.json()["detail"].lower()


@pytest.mark.integration
def test_admin_delete_rejects_builtin(admin_client):
    """Admin DELETE /api/admin/agents/{id} must also refuse built-ins."""
    client = admin_client
    skill_id = _insert_builtin_skill()

    resp = client.delete(f"/api/admin/agents/{skill_id}")
    assert resp.status_code == 403, resp.text


@pytest.mark.integration
def test_admin_remove_from_marketplace_rejects_builtin(admin_client):
    """Admin remove-from-marketplace endpoint must refuse built-ins — a
    built-in's ``is_active`` is owned by seed code, not the UI.
    """
    client = admin_client
    skill_id = _insert_builtin_skill()

    resp = client.patch(f"/api/admin/agents/{skill_id}/remove-from-marketplace")
    assert resp.status_code == 403, resp.text
    assert _get_is_builtin(skill_id) is True


@pytest.mark.integration
def test_admin_restore_to_marketplace_rejects_builtin(admin_client):
    """Admin restore-to-marketplace endpoint must refuse built-ins too."""
    client = admin_client
    skill_id = _insert_builtin_skill()

    resp = client.patch(f"/api/admin/agents/{skill_id}/restore-to-marketplace")
    assert resp.status_code == 403, resp.text
