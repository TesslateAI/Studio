"""End-to-end pause/resume test for the node-config flow.

Invokes the ``request_node_config`` tool against the real DB + real
``PendingUserInputManager`` (in-memory, no Redis). A background coroutine
simulates the user submitting via the router's ``submit`` endpoint after
the tool has parked. We assert:

  * the tool returns a success result with the expected summary
  * the event stream fires ``architecture_node_added`` →
    ``user_input_required`` → ``node_config_resumed`` in that order
"""
from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest


class _EventRecorder:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def publish_agent_event(self, task_id: str, event: dict) -> None:
        self.events.append(event)


async def _create_project(
    owner_id: UUID,
) -> UUID:
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    from app.models import Project
    from app.models_team import TeamMembership

    engine = create_async_engine(
        "postgresql+asyncpg://tesslate_test:testpass@localhost:5433/tesslate_test",
        pool_pre_ping=True,
    )
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as db:
        team_row = (
            await db.execute(
                select(TeamMembership).where(TeamMembership.user_id == owner_id).limit(1)
            )
        ).scalar_one()
        project = Project(
            id=uuid4(),
            name="e2e-node-config",
            slug=f"e2e-node-{uuid4().hex[:6]}",
            owner_id=owner_id,
            team_id=team_row.team_id,
        )
        db.add(project)
        await db.commit()
        pid = project.id
    await engine.dispose()
    return pid


@pytest.mark.integration
def test_end_to_end_pause_and_resume_via_router(authenticated_client, monkeypatch):
    """Full pause/resume: tool → router submit → tool resumes."""
    from app.agent.tools import approval_manager as am
    from app.agent.tools.node_config import request_node_config as rnc

    # Fresh manager singleton per test
    am._manager = None
    manager = am.get_pending_input_manager()

    # Record events instead of publishing to Redis
    recorder = _EventRecorder()
    monkeypatch.setattr(rnc, "get_pubsub", lambda: recorder)

    # flag_modified needs a real SA-mapped instance — the tool DOES use real
    # Containers here (loaded from the DB), so no patch required.

    client, user_data = authenticated_client
    user_id = UUID(user_data["id"])

    # Build a single persistent loop to drive DB + executor so asyncpg
    # connections stay bound.
    loop = asyncio.new_event_loop()

    try:
        project_id = loop.run_until_complete(_create_project(user_id))

        async def _run_flow() -> dict:
            from sqlalchemy.ext.asyncio import (
                AsyncSession,
                async_sessionmaker,
                create_async_engine,
            )

            engine = create_async_engine(
                "postgresql+asyncpg://tesslate_test:testpass@localhost:5433/tesslate_test",
                pool_pre_ping=True,
            )
            Session = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )

            async def _submitter() -> None:
                # Wait until the tool emits user_input_required
                for _ in range(400):
                    ev = next(
                        (
                            e
                            for e in recorder.events
                            if e.get("type") == "user_input_required"
                        ),
                        None,
                    )
                    if ev is not None:
                        input_id = ev["data"]["input_id"]
                        # Use the router endpoint as the real user would
                        resp = client.post(
                            f"/api/chat/node-config/{input_id}/submit",
                            json={
                                "values": {
                                    "SUPABASE_URL": "https://e2e.supabase.co",
                                    "SUPABASE_ANON_KEY": "anon-e2e-1234567890",
                                }
                            },
                        )
                        assert resp.status_code == 200, resp.text
                        return
                    await asyncio.sleep(0.01)
                raise AssertionError("tool never emitted user_input_required")

            async with Session() as db:
                submitter = asyncio.create_task(_submitter())
                context = {
                    "db": db,
                    "project_id": project_id,
                    "user_id": user_id,
                    "task_id": "e2e-task-1",
                    "chat_id": "e2e-chat-1",
                }
                result = await rnc.request_node_config_executor(
                    {"node_name": "supabase", "preset": "supabase"},
                    context,
                )
                await submitter

            await engine.dispose()
            return result

        result = loop.run_until_complete(_run_flow())
    finally:
        loop.close()

    # --- Assertions ---
    assert result["success"] is True
    assert result["created"] is True
    assert "SUPABASE_URL" in result["non_secret_values"]
    assert "SUPABASE_ANON_KEY" in result["secret_keys"]
    # No plaintext leak in the result
    assert "anon-e2e-1234567890" not in str(result)

    # Event ordering
    types = [e.get("type") for e in recorder.events]
    assert "architecture_node_added" in types
    assert "user_input_required" in types
    assert "node_config_resumed" in types
    assert types.index("architecture_node_added") < types.index("user_input_required")
    assert types.index("user_input_required") < types.index("node_config_resumed")


@pytest.mark.integration
def test_wait_for_input_false_returns_immediately_without_pausing(
    authenticated_client, monkeypatch
):
    """``wait_for_input=False`` should:
      * NOT emit ``user_input_required``
      * NOT pause the agent (no submit needed)
      * Still emit ``architecture_node_added``
      * Return key names from the preset schema with ``deferred=True``
      * Persist a Container row with empty env_vars / secrets
    """
    from app.agent.tools import approval_manager as am
    from app.agent.tools.node_config import request_node_config as rnc

    am._manager = None

    recorder = _EventRecorder()
    monkeypatch.setattr(rnc, "get_pubsub", lambda: recorder)

    _, user_data = authenticated_client
    user_id = UUID(user_data["id"])
    loop = asyncio.new_event_loop()

    try:
        project_id = loop.run_until_complete(_create_project(user_id))

        async def _run_flow() -> dict:
            from sqlalchemy.ext.asyncio import (
                AsyncSession,
                async_sessionmaker,
                create_async_engine,
            )

            engine = create_async_engine(
                "postgresql+asyncpg://tesslate_test:testpass@localhost:5433/tesslate_test",
                pool_pre_ping=True,
            )
            Session = async_sessionmaker(
                engine, class_=AsyncSession, expire_on_commit=False
            )

            async with Session() as db:
                context = {
                    "db": db,
                    "project_id": project_id,
                    "user_id": user_id,
                    "task_id": "ff-task-1",
                    "chat_id": "ff-chat-1",
                }
                # No submitter background task — the call should return on its own.
                result = await asyncio.wait_for(
                    rnc.request_node_config_executor(
                        {
                            "node_name": "stripe",
                            "preset": "stripe",
                            "wait_for_input": False,
                        },
                        context,
                    ),
                    timeout=5.0,  # if we hang here the executor is still pausing
                )

            await engine.dispose()
            return result

        result = loop.run_until_complete(_run_flow())
    finally:
        loop.close()

    # --- Assertions ---
    assert result["success"] is True
    assert result["created"] is True
    assert result["deferred"] is True
    # Key names from the stripe preset; no values, no secrets
    assert set(result["configured_keys"]) == {
        "STRIPE_PUBLISHABLE_KEY",
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
    }
    assert set(result["secret_keys"]) == {
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
    }
    assert result["non_secret_values"] == {}
    assert result["updated_keys"] == []
    assert result["rotated_secrets"] == []

    types = [e.get("type") for e in recorder.events]
    assert "architecture_node_added" in types
    assert "user_input_required" not in types
    assert "node_config_resumed" not in types
