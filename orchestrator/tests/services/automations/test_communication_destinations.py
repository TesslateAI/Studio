"""Phase 4 — unit tests for ``services.automations.communication_destinations``.

Exercises the CRUD service against a SQLite database upgraded to alembic
``head`` so the real ``communication_destinations`` table (including its
CHECK constraints + the FK on ``automation_delivery_targets``) is in
play. Mirrors the fixture pattern used by ``test_dispatcher.py`` /
``test_invocation_subject.py`` so a single ``alembic upgrade head`` per
test gives us the full schema chain.

Coverage matrix:

* create → row persists with the supplied ``kind`` / ``name`` / config.
* create with bad kind → ``InvalidDestinationKind``.
* create with bad formatting policy → ``InvalidFormattingPolicy``.
* create with missing channel_config → ``ChannelConfigNotFound``.
* create with channel_config owned by another user → ``ChannelConfigNotFound``.
* update name + config + formatting_policy → mutates only the patched fields.
* list_for_user → returns owner rows + team rows, excludes other users'.
* destination_in_use → counts only ACTIVE referencing automations.
* delete refuses when in-use; ``force=True`` deletes anyway.
* delete with FK from delivery_targets → cascade-removes the edge row.
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
from sqlalchemy import event, insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


# ---------------------------------------------------------------------------
# Fixtures (mirror tests/services/automations/test_dispatcher.py)
# ---------------------------------------------------------------------------


def _install_sqlite_now(engine) -> None:
    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_conn, _record):  # noqa: ARG001
        dbapi_conn.create_function(
            "now", 0, lambda: datetime.now(UTC).isoformat(sep=" ")
        )


def _alembic_cfg() -> Config:
    orchestrator_dir = Path(__file__).resolve().parents[3]
    cfg = Config(str(orchestrator_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(orchestrator_dir / "alembic"))
    return cfg


@pytest.fixture
def migrated_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    db_path = tmp_path / "comm_destinations.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DEPLOYMENT_MODE", "desktop")

    from app.config import get_settings

    get_settings.cache_clear()
    orchestrator_dir = Path(__file__).resolve().parents[3]
    original = os.getcwd()
    os.chdir(orchestrator_dir)
    try:
        command.upgrade(_alembic_cfg(), "head")
    finally:
        os.chdir(original)
    yield url
    get_settings.cache_clear()


@pytest.fixture
def session_maker(migrated_sqlite: str):
    engine = create_async_engine(migrated_sqlite, future=True)
    _install_sqlite_now(engine)
    # SQLite needs FK enforcement turned on per-connection so the FK from
    # automation_delivery_targets → communication_destinations actually
    # CASCADEs in tests.
    @event.listens_for(engine.sync_engine, "connect")
    def _enable_fks(dbapi_conn, _record):  # noqa: ARG001
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker
    asyncio.run(engine.dispose())


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _seed_user(db) -> uuid.UUID:
    from app.models_auth import User

    user_id = uuid.uuid4()
    suffix = uuid.uuid4().hex[:8]
    await db.execute(
        insert(User.__table__).values(
            id=user_id,
            email=f"cd-{suffix}@example.com",
            hashed_password="x",
            is_active=True,
            is_superuser=False,
            is_verified=True,
            name="CD Tester",
            username=f"u{suffix}",
            slug=f"u-{suffix}",
        )
    )
    await db.flush()
    return user_id


async def _seed_channel_config(
    db, *, user_id: uuid.UUID, name: str = "test-slack"
) -> uuid.UUID:
    from app.models import ChannelConfig

    config_id = uuid.uuid4()
    cc = ChannelConfig(
        id=config_id,
        user_id=user_id,
        channel_type="slack",
        name=name,
        credentials="encrypted-blob",
        webhook_secret="sekret-" + uuid.uuid4().hex[:16],
        is_active=True,
    )
    db.add(cc)
    await db.flush()
    return config_id


async def _seed_automation(
    db,
    *,
    owner_user_id: uuid.UUID,
    is_active: bool = True,
) -> uuid.UUID:
    from app.models_automations import AutomationDefinition

    autom = AutomationDefinition(
        id=uuid.uuid4(),
        name="cd-test",
        owner_user_id=owner_user_id,
        workspace_scope="none",
        contract={"allowed_tools": ["read_file"], "max_compute_tier": 0},
        max_compute_tier=0,
        is_active=is_active,
    )
    db.add(autom)
    await db.flush()
    return autom.id


async def _seed_delivery_target(
    db, *, automation_id: uuid.UUID, destination_id: uuid.UUID
) -> uuid.UUID:
    from app.models_automations import AutomationDeliveryTarget

    target = AutomationDeliveryTarget(
        id=uuid.uuid4(),
        automation_id=automation_id,
        destination_id=destination_id,
        ordinal=0,
        on_failure={"kind": "drop"},
        artifact_filter="all",
    )
    db.add(target)
    await db.flush()
    return target.id


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_create_persists_row(session_maker) -> None:
    from app.models_automations import CommunicationDestination
    from app.services.automations import communication_destinations as svc

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            cc_id = await _seed_channel_config(db, user_id=user_id)
            row = await svc.create_destination(
                db,
                owner_user_id=user_id,
                channel_config_id=cc_id,
                kind="slack_channel",
                name=" #standup ",
                config={"chat_id": "C123"},
                formatting_policy="text",
            )
            await db.commit()

            # Re-load to confirm persistence
            loaded = (
                await db.execute(
                    select(CommunicationDestination).where(
                        CommunicationDestination.id == row.id
                    )
                )
            ).scalar_one()
            assert loaded.kind == "slack_channel"
            assert loaded.name == "#standup"  # whitespace stripped
            assert loaded.config == {"chat_id": "C123"}
            assert loaded.owner_user_id == user_id
            assert loaded.channel_config_id == cc_id
            assert loaded.formatting_policy == "text"
            assert loaded.last_used_at is None

    asyncio.run(go())


@pytest.mark.unit
def test_create_rejects_invalid_kind(session_maker) -> None:
    from app.services.automations import communication_destinations as svc

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            cc_id = await _seed_channel_config(db, user_id=user_id)
            with pytest.raises(svc.InvalidDestinationKind):
                await svc.create_destination(
                    db,
                    owner_user_id=user_id,
                    channel_config_id=cc_id,
                    kind="instagram_dm",
                    name="bogus",
                )

    asyncio.run(go())


@pytest.mark.unit
def test_create_rejects_invalid_formatting_policy(session_maker) -> None:
    from app.services.automations import communication_destinations as svc

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            cc_id = await _seed_channel_config(db, user_id=user_id)
            with pytest.raises(svc.InvalidFormattingPolicy):
                await svc.create_destination(
                    db,
                    owner_user_id=user_id,
                    channel_config_id=cc_id,
                    kind="slack_channel",
                    name="ok",
                    formatting_policy="emoji_soup",
                )

    asyncio.run(go())


@pytest.mark.unit
def test_create_requires_existing_channel_config(session_maker) -> None:
    from app.services.automations import communication_destinations as svc

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            with pytest.raises(svc.ChannelConfigNotFound):
                await svc.create_destination(
                    db,
                    owner_user_id=user_id,
                    channel_config_id=uuid.uuid4(),
                    kind="slack_channel",
                    name="ghost",
                )

    asyncio.run(go())


@pytest.mark.unit
def test_create_refuses_other_users_channel_config(session_maker) -> None:
    """A user cannot back a destination with someone else's channel."""
    from app.services.automations import communication_destinations as svc

    async def go():
        async with session_maker() as db:
            owner_id = await _seed_user(db)
            other_id = await _seed_user(db)
            cc_id = await _seed_channel_config(db, user_id=other_id)
            with pytest.raises(svc.ChannelConfigNotFound):
                await svc.create_destination(
                    db,
                    owner_user_id=owner_id,
                    channel_config_id=cc_id,
                    kind="slack_channel",
                    name="not-mine",
                )

    asyncio.run(go())


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_update_patches_only_supplied_fields(session_maker) -> None:
    from app.services.automations import communication_destinations as svc

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            cc_id = await _seed_channel_config(db, user_id=user_id)
            row = await svc.create_destination(
                db,
                owner_user_id=user_id,
                channel_config_id=cc_id,
                kind="slack_channel",
                name="#orig",
                config={"chat_id": "C1"},
                formatting_policy="text",
            )
            await db.commit()

            # Update only the name — config + formatting policy unchanged.
            await svc.update_destination(db, destination=row, name="#renamed")
            await db.commit()
            assert row.name == "#renamed"
            assert row.config == {"chat_id": "C1"}
            assert row.formatting_policy == "text"

            # Now update config + formatting policy together.
            await svc.update_destination(
                db,
                destination=row,
                config={"chat_id": "C2", "thread_id": "T9"},
                formatting_policy="blocks",
            )
            await db.commit()
            assert row.config == {"chat_id": "C2", "thread_id": "T9"}
            assert row.formatting_policy == "blocks"

    asyncio.run(go())


@pytest.mark.unit
def test_update_rejects_bad_formatting_policy(session_maker) -> None:
    from app.services.automations import communication_destinations as svc

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            cc_id = await _seed_channel_config(db, user_id=user_id)
            row = await svc.create_destination(
                db,
                owner_user_id=user_id,
                channel_config_id=cc_id,
                kind="email",
                name="dailies",
            )
            await db.commit()
            with pytest.raises(svc.InvalidFormattingPolicy):
                await svc.update_destination(
                    db, destination=row, formatting_policy="screaming"
                )

    asyncio.run(go())


# ---------------------------------------------------------------------------
# list_for_user
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_list_for_user_includes_owner_only_when_no_team(session_maker) -> None:
    from app.services.automations import communication_destinations as svc

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            other_id = await _seed_user(db)
            cc_id = await _seed_channel_config(db, user_id=user_id)
            other_cc_id = await _seed_channel_config(
                db, user_id=other_id, name="other-slack"
            )

            mine = await svc.create_destination(
                db,
                owner_user_id=user_id,
                channel_config_id=cc_id,
                kind="slack_channel",
                name="#mine",
            )
            # Other user's destination — must NOT appear in our list.
            await svc.create_destination(
                db,
                owner_user_id=other_id,
                channel_config_id=other_cc_id,
                kind="slack_channel",
                name="#theirs",
            )
            await db.commit()

            rows = await svc.list_for_user(db, user_id=user_id, team_ids=())
            ids = {r.id for r in rows}
            assert mine.id in ids
            assert len(rows) == 1

    asyncio.run(go())


@pytest.mark.unit
def test_list_for_user_filter_by_channel_config(session_maker) -> None:
    from app.services.automations import communication_destinations as svc

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            cc_a = await _seed_channel_config(db, user_id=user_id, name="a")
            cc_b = await _seed_channel_config(db, user_id=user_id, name="b")

            await svc.create_destination(
                db,
                owner_user_id=user_id,
                channel_config_id=cc_a,
                kind="slack_channel",
                name="#a-1",
            )
            await svc.create_destination(
                db,
                owner_user_id=user_id,
                channel_config_id=cc_a,
                kind="slack_channel",
                name="#a-2",
            )
            await svc.create_destination(
                db,
                owner_user_id=user_id,
                channel_config_id=cc_b,
                kind="slack_channel",
                name="#b-1",
            )
            await db.commit()

            rows = await svc.list_for_user(
                db, user_id=user_id, team_ids=(), channel_config_id=cc_a
            )
            assert len(rows) == 2
            assert {r.channel_config_id for r in rows} == {cc_a}

    asyncio.run(go())


# ---------------------------------------------------------------------------
# destination_in_use + delete
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_destination_in_use_counts_only_active_automations(session_maker) -> None:
    from app.services.automations import communication_destinations as svc

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            cc_id = await _seed_channel_config(db, user_id=user_id)
            dest = await svc.create_destination(
                db,
                owner_user_id=user_id,
                channel_config_id=cc_id,
                kind="slack_channel",
                name="#hot",
            )
            active_a = await _seed_automation(db, owner_user_id=user_id)
            active_b = await _seed_automation(db, owner_user_id=user_id)
            paused = await _seed_automation(
                db, owner_user_id=user_id, is_active=False
            )
            await _seed_delivery_target(
                db, automation_id=active_a, destination_id=dest.id
            )
            await _seed_delivery_target(
                db, automation_id=active_b, destination_id=dest.id
            )
            await _seed_delivery_target(
                db, automation_id=paused, destination_id=dest.id
            )
            await db.commit()

            count = await svc.destination_in_use(db, dest.id)
            assert count == 2  # paused automation does not count

    asyncio.run(go())


@pytest.mark.unit
def test_delete_refuses_when_in_use_then_force_deletes(session_maker) -> None:
    from app.models_automations import (
        AutomationDeliveryTarget,
        CommunicationDestination,
    )
    from app.services.automations import communication_destinations as svc

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            cc_id = await _seed_channel_config(db, user_id=user_id)
            dest = await svc.create_destination(
                db,
                owner_user_id=user_id,
                channel_config_id=cc_id,
                kind="telegram_chat",
                name="incidents",
            )
            autom_id = await _seed_automation(db, owner_user_id=user_id)
            await _seed_delivery_target(
                db, automation_id=autom_id, destination_id=dest.id
            )
            await db.commit()

            # Refuses without force.
            with pytest.raises(svc.DestinationInUse) as exc_info:
                await svc.delete_destination(db, destination=dest)
            assert exc_info.value.count == 1

            # Force deletes — and the FK on automation_delivery_targets
            # cascades the edge row away with it.
            await svc.delete_destination(db, destination=dest, force=True)
            await db.commit()

            still_there = (
                await db.execute(
                    select(CommunicationDestination).where(
                        CommunicationDestination.id == dest.id
                    )
                )
            ).scalar_one_or_none()
            assert still_there is None

            # Cascade verification: the edge row pointing at the deleted
            # destination should be gone too.
            edges = (
                await db.execute(
                    select(AutomationDeliveryTarget).where(
                        AutomationDeliveryTarget.destination_id == dest.id
                    )
                )
            ).scalars().all()
            assert edges == []

    asyncio.run(go())


# ---------------------------------------------------------------------------
# touch_last_used
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_touch_last_used_stamps_timestamp(session_maker) -> None:
    from app.services.automations import communication_destinations as svc

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            cc_id = await _seed_channel_config(db, user_id=user_id)
            dest = await svc.create_destination(
                db,
                owner_user_id=user_id,
                channel_config_id=cc_id,
                kind="webhook",
                name="ops",
                config={"webhook_url": "https://example.com/hook"},
            )
            await db.commit()
            assert dest.last_used_at is None

            await svc.touch_last_used(db, destination=dest)
            await db.commit()
            assert dest.last_used_at is not None

    asyncio.run(go())
