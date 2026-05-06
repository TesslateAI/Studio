"""Pause/resume integration test for the ``request_workspace`` agent tool.

Modeled on ``tests/integration/test_node_config_flow.py``: spins up the
real ``PendingUserInputManager``, monkeypatches the pubsub helper to a
recorder, and drives the executor against a SQLite-backed alembic
migration. A background coroutine simulates the user submitting via the
router contract after the tool has parked.

Covers:

* ``request_workspace`` emits ``workspace_attach_required`` with the
  candidate list, then resumes on ``submit_input`` with the chosen
  action.
* ``action='attach'`` sets ``Chat.project_id`` and mutates the agent's
  ``context`` dict in place — ``project_id``, ``volume_id``,
  ``compute_tier`` are visible to a downstream tool that reads from
  ``context``.
* Delegated subagent runs (``parent_task_id`` set) are gated.
* Timeout returns ``cancelled=True``.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def _install_sqlite_now(engine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_conn, _record):
        dbapi_conn.create_function("now", 0, lambda: datetime.now(UTC).isoformat(sep=" "))


def _alembic_cfg() -> Config:
    orchestrator_dir = Path(__file__).resolve().parents[2]
    cfg = Config(str(orchestrator_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(orchestrator_dir / "alembic"))
    return cfg


@pytest.fixture
def migrated_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "wa.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("OPENSAIL_HOME", str(tmp_path / "studio-home"))
    monkeypatch.setenv("DEPLOYMENT_MODE", "desktop")

    from app.config import get_settings

    get_settings.cache_clear()
    orchestrator_dir = Path(__file__).resolve().parents[2]
    original = os.getcwd()
    os.chdir(orchestrator_dir)
    try:
        command.upgrade(_alembic_cfg(), "head")
    finally:
        os.chdir(original)
    yield url
    get_settings.cache_clear()


class _Recorder:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def publish_agent_event(self, task_id: str, event: dict) -> None:
        self.events.append(event)


async def _seed_user_chat_and_workspace(maker, with_workspace: bool):
    """Insert a User → personal Team → optional workspace Project → Chat
    chain. Returns ``(user_id, chat_id, target_project_id_or_None)``.
    """
    from app.models import Chat, Project
    from app.models_auth import User
    from app.models_team import Team, TeamMembership

    async with maker() as db:
        u_handle = f"u{uuid.uuid4().hex[:8]}"
        user = User(
            id=uuid.uuid4(),
            name="t",
            username=u_handle,
            slug=u_handle,
            email=f"user-{uuid.uuid4().hex[:6]}@example.com",
            hashed_password="x",
            is_active=True,
        )
        db.add(user)
        await db.flush()

        team = Team(
            id=uuid.uuid4(),
            name="personal",
            slug=f"personal-{uuid.uuid4().hex[:6]}",
            is_personal=True,
            created_by_id=user.id,
        )
        db.add(team)
        await db.flush()
        membership = TeamMembership(
            id=uuid.uuid4(),
            team_id=team.id,
            user_id=user.id,
            role="admin",
            is_active=True,
        )
        db.add(membership)
        user.default_team_id = team.id

        target_id = None
        if with_workspace:
            target = Project(
                id=uuid.uuid4(),
                name="kb-target",
                slug=f"kb-{uuid.uuid4().hex[:6]}",
                owner_id=user.id,
                team_id=team.id,
                project_kind="workspace",
                compute_tier="none",
                environment_status="active",
                created_via="empty",
            )
            db.add(target)
            await db.flush()
            target_id = target.id

        chat = Chat(
            id=uuid.uuid4(),
            user_id=user.id,
            project_id=None,
            origin="standalone",
            title="t",
        )
        db.add(chat)
        await db.commit()
        return user.id, chat.id, target_id


def test_workspace_attach_pause_and_resume_via_attach(
    migrated_sqlite, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Full pause/resume: tool emits ``workspace_attach_required``, the
    submit path delivers the response, the tool resumes, and the chat is
    linked. Verifies ``context`` is mutated in place.
    """
    from app.agent.tools import approval_manager as am
    from app.agent.tools.workspace_ops import request_workspace as rw

    am._manager = None
    manager = am.get_pending_input_manager()

    recorder = _Recorder()
    monkeypatch.setattr(rw, "get_pubsub", lambda: recorder)

    engine = create_async_engine(migrated_sqlite, future=True)
    _install_sqlite_now(engine)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    loop = asyncio.new_event_loop()

    try:
        user_id, chat_id, target_id = loop.run_until_complete(
            _seed_user_chat_and_workspace(maker, with_workspace=True)
        )

        async def _flow() -> dict:
            async with maker() as db:

                async def _submitter() -> None:
                    for _ in range(400):
                        ev = next(
                            (
                                e
                                for e in recorder.events
                                if e.get("type") == "workspace_attach_required"
                            ),
                            None,
                        )
                        if ev is not None:
                            input_id = ev["data"]["input_id"]
                            response = {
                                "action": "attach",
                                "project_id": str(target_id),
                            }
                            manager.submit_input(input_id, response)
                            return
                        await asyncio.sleep(0.01)
                    raise AssertionError("workspace_attach_required never emitted")

                submitter = asyncio.create_task(_submitter())
                ctx = {
                    "db": db,
                    "user_id": user_id,
                    "chat_id": chat_id,
                    "task_id": "wa-task-1",
                }
                result = await rw.request_workspace_executor({"reason": "save notes"}, ctx)
                await submitter

                # Sanity: Chat.project_id was set
                from app.models import Chat as ChatM

                fresh_chat = await db.get(ChatM, chat_id)
                assert fresh_chat.project_id == target_id

                # context mutated in place
                assert ctx["project_id"] == target_id
                # volume_id may be None on a freshly-created empty workspace —
                # we don't assert a specific value, just that the key was set.
                assert "volume_id" in ctx
                assert ctx["compute_tier"] == "none"

                return result

        result = loop.run_until_complete(_flow())
    finally:
        loop.close()
        asyncio.run(engine.dispose())

    assert result["success"] is True
    assert "project_id" in result
    types = [e.get("type") for e in recorder.events]
    assert "workspace_attach_required" in types
    assert "workspace_attach_resumed" in types
    assert types.index("workspace_attach_required") < types.index("workspace_attach_resumed")


def test_workspace_attach_gated_for_delegated_runs(
    migrated_sqlite, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Delegated runs (``parent_task_id`` set) must refuse — there is no
    human in the loop. The tool returns an error before any pubsub event.
    """
    from app.agent.tools import approval_manager as am
    from app.agent.tools.workspace_ops import request_workspace as rw

    am._manager = None
    recorder = _Recorder()
    monkeypatch.setattr(rw, "get_pubsub", lambda: recorder)

    engine = create_async_engine(migrated_sqlite, future=True)
    _install_sqlite_now(engine)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    loop = asyncio.new_event_loop()
    try:
        user_id, chat_id, _ = loop.run_until_complete(
            _seed_user_chat_and_workspace(maker, with_workspace=False)
        )

        async def _run():
            async with maker() as db:
                ctx = {
                    "db": db,
                    "user_id": user_id,
                    "chat_id": chat_id,
                    "task_id": "wa-delegated",
                    "parent_task_id": "parent-123",
                }
                return await rw.request_workspace_executor({}, ctx)

        result = loop.run_until_complete(_run())
    finally:
        loop.close()
        asyncio.run(engine.dispose())

    assert result["success"] is False
    assert recorder.events == []


def test_workspace_attach_cancel_returns_cancelled(
    migrated_sqlite, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ``__cancelled__`` sentinel from the manager surfaces as
    ``cancelled=True`` on the tool result.
    """
    from app.agent.tools import approval_manager as am
    from app.agent.tools.workspace_ops import request_workspace as rw

    am._manager = None
    manager = am.get_pending_input_manager()
    recorder = _Recorder()
    monkeypatch.setattr(rw, "get_pubsub", lambda: recorder)

    engine = create_async_engine(migrated_sqlite, future=True)
    _install_sqlite_now(engine)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    loop = asyncio.new_event_loop()
    try:
        user_id, chat_id, _ = loop.run_until_complete(
            _seed_user_chat_and_workspace(maker, with_workspace=False)
        )

        async def _flow():
            async with maker() as db:

                async def _canceller():
                    for _ in range(400):
                        ev = next(
                            (
                                e
                                for e in recorder.events
                                if e.get("type") == "workspace_attach_required"
                            ),
                            None,
                        )
                        if ev is not None:
                            manager.cancel_input(ev["data"]["input_id"])
                            return
                        await asyncio.sleep(0.01)
                    raise AssertionError("never emitted")

                cancel_task = asyncio.create_task(_canceller())
                ctx = {
                    "db": db,
                    "user_id": user_id,
                    "chat_id": chat_id,
                    "task_id": "wa-cancel",
                }
                result = await rw.request_workspace_executor({}, ctx)
                await cancel_task
                return result

        result = loop.run_until_complete(_flow())
    finally:
        loop.close()
        asyncio.run(engine.dispose())

    assert result["success"] is True
    assert result.get("cancelled") is True
