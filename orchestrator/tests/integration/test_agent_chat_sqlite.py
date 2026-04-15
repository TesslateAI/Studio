"""
Integration test: agent chat end-to-end against SQLite + LocalTaskQueue + LocalPubSub.

Boots the full FastAPI app with:
  - DEPLOYMENT_MODE=desktop  → LocalTaskQueue + LocalPubSub
  - SQLite DB migrated to head
  - A minimal stub agent runner that immediately yields one agent_step and one
    complete event — no real LLM call is made.

Assertions:
  1. POST /api/chat/agent/stream returns 200 and streams events.
  2. At least one `agent_step` event appears in the stream.
  3. A `done` event terminates the stream.
  4. AgentStep rows are written to the SQLite DB after the task drains.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _alembic_cfg(orchestrator_dir: Path) -> Config:
    cfg = Config(str(orchestrator_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(orchestrator_dir / "alembic"))
    return cfg


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def sqlite_url(tmp_path_factory: pytest.TempPathFactory) -> str:
    """Migrate a fresh SQLite DB to head and return the connection URL."""
    db_path = tmp_path_factory.mktemp("agent_chat") / "agent_chat.db"
    url = f"sqlite+aiosqlite:///{db_path}"

    orchestrator_dir = Path(__file__).resolve().parents[2]
    original_cwd = os.getcwd()
    os.chdir(orchestrator_dir)
    try:
        command.upgrade(_alembic_cfg(orchestrator_dir), "head")
    finally:
        os.chdir(original_cwd)

    return url


@pytest_asyncio.fixture
async def db_session(sqlite_url: str) -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(sqlite_url, future=True)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


# ---------------------------------------------------------------------------
# Stub agent that yields predictable events without an LLM
# ---------------------------------------------------------------------------


async def _stub_agent_run(message: str, context: dict) -> AsyncGenerator[dict, None]:
    """Minimal agent run: one step, then complete."""
    yield {
        "type": "agent_step",
        "data": {
            "iteration": 1,
            "thought": "Stub thought",
            "tool_calls": [],
            "tool_results": [],
            "response_text": "",
            "is_complete": False,
            "timestamp": "2024-01-01T00:00:00Z",
        },
    }
    yield {
        "type": "complete",
        "data": {
            "final_response": "Hello from stub",
            "iterations": 1,
            "tool_calls_made": 0,
            "completion_reason": "task_complete",
        },
    }


class _StubAgent:
    def __init__(self):
        self.tools = MagicMock()
        self.tools.register = MagicMock()

    async def run(self, message: str, context: dict):
        async for event in _stub_agent_run(message, context):
            yield event


# ---------------------------------------------------------------------------
# App fixture — desktop mode with SQLite + in-process queue
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def app(sqlite_url: str, monkeypatch: pytest.MonkeyPatch):
    """
    Return a FastAPI app instance wired to SQLite and LocalTaskQueue.

    We monkeypatch:
    - DATABASE_URL → SQLite
    - DEPLOYMENT_MODE → desktop (selects LocalTaskQueue + LocalPubSub)
    - LITELLM_API_BASE / LITELLM_MASTER_KEY → empty (no real LiteLLM)
    - _create_agent_runner → returns StubAgent (no real model call)
    - create_model_adapter → returns a lightweight mock
    """
    monkeypatch.setenv("DATABASE_URL", sqlite_url)
    monkeypatch.setenv("DEPLOYMENT_MODE", "desktop")
    monkeypatch.setenv("LITELLM_API_BASE", "")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "")
    monkeypatch.setenv("REDIS_URL", "")

    # Clear the settings cache so the monkeypatched env vars take effect.
    from app.config import get_settings

    get_settings.cache_clear()

    # Patch the agent runner factory so no LLM call is made.
    stub = _StubAgent()

    async def _fake_runner(agent_model, model_adapter, tools_override, settings):
        return stub

    async def _fake_model_adapter(**kwargs):
        return MagicMock()

    with (
        patch("app.worker._create_agent_runner", side_effect=_fake_runner),
        patch(
            "app.agent.models.create_model_adapter",
            new_callable=AsyncMock,
            return_value=MagicMock(),
        ),
        patch("app.routers.chat._create_agent_runner", side_effect=_fake_runner),
    ):
        # Import app AFTER env is set so config picks up the right values.
        from app.main import app as _app  # type: ignore[attr-defined]

        yield _app

    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_chat_streams_events(app, db_session: AsyncSession):
    """
    Full happy-path: chat/agent/stream returns a streamed SSE response with
    agent_step and done events; AgentStep rows appear in the DB.
    """
    from app.models import Chat, MarketplaceAgent, User

    # Seed minimal User + Chat + MarketplaceAgent so the worker can load them.
    user_id = uuid.uuid4()
    chat_id = uuid.uuid4()
    agent_id = uuid.uuid4()

    user = User(
        id=user_id,
        email=f"test-{user_id}@example.com",
        hashed_password="x",
        is_active=True,
    )
    chat = Chat(id=chat_id, user_id=user_id, title="Test Chat")
    agent = MarketplaceAgent(
        id=agent_id,
        name="StubAgent",
        slug="stub-agent",
        description="Test agent",
        agent_type="IterativeAgent",
        model="gpt-4o-mini",
        is_active=True,
        usage_count=0,
    )

    db_session.add_all([user, chat, agent])
    await db_session.commit()

    # Build a valid JWT for the test user.
    from app.auth import create_access_token

    token = create_access_token(data={"sub": str(user_id)})

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        async with client.stream(
            "POST",
            "/api/chat/agent/stream",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "chat_id": str(chat_id),
                "message": "Hello!",
                "agent_id": str(agent_id),
            },
        ) as resp:
            assert resp.status_code == 200

            events = []
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line or line == "data: [DONE]":
                    continue
                if line.startswith("data: "):
                    import contextlib

                    with contextlib.suppress(json.JSONDecodeError):
                        events.append(json.loads(line[6:]))

    # Basic event assertions.
    event_types = {e.get("type") for e in events}
    assert "agent_step" in event_types, f"No agent_step in events: {event_types}"
    assert "done" in event_types, f"No done event: {event_types}"

    # Allow the worker a moment to persist AgentStep rows.
    await asyncio.sleep(0.5)

    # Verify AgentStep rows were written to DB.
    from app.models import AgentStep

    result = await db_session.execute(select(AgentStep).where(AgentStep.chat_id == chat_id))
    steps = result.scalars().all()
    assert len(steps) >= 1, "Expected at least one AgentStep row in the DB"
    assert steps[0].step_data.get("thought") == "Stub thought"
