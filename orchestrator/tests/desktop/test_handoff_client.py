"""Unit coverage for the handoff client skeleton."""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def _alembic_cfg() -> Config:
    orchestrator_dir = Path(__file__).resolve().parents[2]
    cfg = Config(str(orchestrator_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(orchestrator_dir / "alembic"))
    return cfg


@pytest.fixture
def maker_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "handoff.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
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

    engine = create_async_engine(url, future=True)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker
    asyncio.run(engine.dispose())
    get_settings.cache_clear()


def test_push_round_trips_ticket(maker_fixture) -> None:
    from app.services.agent_tickets import create_ticket
    from app.services.handoff_client import HandoffBundle, push

    project_id = uuid.uuid4()

    async def _run():
        async with maker_fixture() as s:
            ticket = await create_ticket(
                s,
                project_id=project_id,
                title="feature work",
                goal_ancestry=["root-mission"],
            )
            await s.commit()
            bundle = await push(s, ticket_id=ticket.id)
            return ticket.id, bundle

    ticket_id, bundle = asyncio.run(_run())
    assert isinstance(bundle, HandoffBundle)
    assert bundle.ticket_id == str(ticket_id)
    assert bundle.title == "feature work"
    assert bundle.goal_ancestry == ["root-mission"]
    assert bundle.trajectory_events == []
    assert bundle.diff == ""
    assert bundle.skill_bindings == []


def test_push_missing_ticket_raises(maker_fixture) -> None:
    from app.services.handoff_client import push

    async def _run():
        async with maker_fixture() as s:
            await push(s, ticket_id=uuid.uuid4())

    with pytest.raises(LookupError):
        asyncio.run(_run())


def test_pull_creates_local_ticket_with_ancestry(maker_fixture) -> None:
    from app.services.handoff_client import HandoffBundle, pull

    project_id = uuid.uuid4()
    bundle = HandoffBundle(
        ticket_id=str(uuid.uuid4()),
        title="carry-over",
        goal_ancestry=["root-mission"],
    )

    async def _run():
        async with maker_fixture() as s:
            ticket = await pull(
                s,
                cloud_task_id="cloud-123",
                bundle=bundle,
                project_id=project_id,
            )
            return ticket

    ticket = asyncio.run(_run())
    assert ticket.title == "carry-over"
    assert ticket.project_id == project_id
    assert "root-mission" in ticket.goal_ancestry
    assert "cloud:cloud-123" in ticket.goal_ancestry
