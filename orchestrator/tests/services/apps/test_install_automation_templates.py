"""Tests for ``installer._materialize_install_automations``.

Per v9: ``app_automation_templates`` rows are publish-time projections of
the manifest's ``automation_templates[]`` block. Each row is a *suggestion* —
the app cannot run schedules autonomously. Rows with
``is_default_enabled=True`` create real ``AutomationDefinition`` rows owned
by the installer at install time.

These tests pin the contract the installer offers callers:

* Default-enabled rows with valid trigger / action shapes produce one
  ``AutomationDefinition`` + ``AutomationTrigger`` + ``AutomationAction``
  row each, scoped to the install's runtime project.
* Default-disabled rows are skipped.
* Rows with malformed payloads (empty ``contract_template``, unknown
  ``trigger.kind``, unknown ``action.action_type``) are skipped with a
  warning rather than aborting the install — a bad template in the DB
  shouldn't block someone from installing the app.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncGenerator

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app import models, models_automations  # noqa: F401  -- register tables
from app.database import Base
from app.models import (
    PROJECT_KIND_APP_RUNTIME,
    AppVersion,
    MarketplaceApp,
    Project,
    Team,
    User,
)
from app.models_automations import (
    AppAutomationTemplate,
    AutomationAction,
    AutomationDefinition,
    AutomationTrigger,
)
from app.services.apps.installer import _materialize_install_automations


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        future=True,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db(db_engine) -> AsyncGenerator[AsyncSession, None]:
    maker = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session


@pytest_asyncio.fixture
async def install_context(db: AsyncSession):
    """Minimal install setup: user + team + project + app + version."""
    user_id = uuid.uuid4()
    db.add(
        User(
            id=user_id,
            email=f"u-{user_id}@example.com",
            hashed_password="x",
            is_active=True,
            is_superuser=False,
            is_verified=False,
            name="Installer",
            username=f"user-{user_id.hex[:10]}",
            slug=f"user-{user_id.hex[:10]}",
        )
    )
    team_id = uuid.uuid4()
    db.add(
        Team(
            id=team_id,
            slug=f"team-{team_id.hex[:10]}",
            name="T",
            is_personal=True,
            created_by_id=user_id,
        )
    )
    await db.flush()

    project_id = uuid.uuid4()
    project = Project(
        id=project_id,
        name="App Runtime",
        slug=f"app-rt-{project_id.hex[:6]}",
        owner_id=user_id,
        team_id=team_id,
        visibility="team",
        project_kind=PROJECT_KIND_APP_RUNTIME,
        volume_id=f"vol-{project_id.hex[:8]}",
    )
    db.add(project)
    await db.flush()

    app_row = MarketplaceApp(
        id=uuid.uuid4(),
        slug="testapp",
        name="Test App",
        category="utility",
        creator_user_id=user_id,
        state="approved",
    )
    db.add(app_row)
    await db.flush()
    version = AppVersion(
        id=uuid.uuid4(),
        app_id=app_row.id,
        version="1.0.0",
        manifest_schema_version="2026-05",
        manifest_json={"manifest_schema_version": "2026-05"},
        manifest_hash="x" * 64,
        feature_set_hash="y" * 64,
        approval_state="stage1_approved",
    )
    db.add(version)
    await db.flush()
    return {
        "user_id": user_id,
        "team_id": team_id,
        "project": project,
        "app_version_id": version.id,
    }


# ---------------------------------------------------------------------------
# Happy path.
# ---------------------------------------------------------------------------


async def test_materializes_default_enabled_template(
    db: AsyncSession, install_context
) -> None:
    db.add(
        AppAutomationTemplate(
            id=uuid.uuid4(),
            app_version_id=install_context["app_version_id"],
            name="Weekly digest",
            description="Send a weekly summary",
            trigger_config={"kind": "cron", "cron": "0 9 * * 1"},
            action_config={"action_type": "app.invoke", "alias": "build_digest"},
            delivery_config={},
            contract_template={"max_compute_tier": 1, "allowed_tools": ["http"]},
            is_default_enabled=True,
        )
    )
    await db.flush()

    created = await _materialize_install_automations(
        db,
        app_version_id=install_context["app_version_id"],
        installer_user_id=install_context["user_id"],
        team_id=install_context["team_id"],
        target_project_id=install_context["project"].id,
    )
    assert created == 1

    defns = (
        (
            await db.execute(
                select(AutomationDefinition).where(
                    AutomationDefinition.target_project_id
                    == install_context["project"].id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(defns) == 1
    defn = defns[0]
    assert defn.name == "Weekly digest"
    assert defn.owner_user_id == install_context["user_id"]
    assert defn.team_id == install_context["team_id"]
    assert defn.workspace_scope == "target_project"
    assert defn.contract == {"max_compute_tier": 1, "allowed_tools": ["http"]}
    assert defn.max_compute_tier == 1
    assert defn.is_active is True
    assert defn.depth == 0

    triggers = (
        (
            await db.execute(
                select(AutomationTrigger).where(
                    AutomationTrigger.automation_id == defn.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(triggers) == 1
    trig = triggers[0]
    assert trig.kind == "cron"
    # ``kind`` is stripped from ``config`` (it's a top-level column on the
    # trigger row); the rest of the config carries through.
    assert trig.config == {"cron": "0 9 * * 1"}

    actions = (
        (
            await db.execute(
                select(AutomationAction).where(AutomationAction.automation_id == defn.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(actions) == 1
    act = actions[0]
    assert act.action_type == "app.invoke"
    assert act.config == {"alias": "build_digest"}
    assert act.ordinal == 0


# ---------------------------------------------------------------------------
# Skip rules.
# ---------------------------------------------------------------------------


async def test_skips_default_disabled_templates(
    db: AsyncSession, install_context
) -> None:
    db.add(
        AppAutomationTemplate(
            id=uuid.uuid4(),
            app_version_id=install_context["app_version_id"],
            name="Opt-in only",
            trigger_config={"kind": "cron", "cron": "0 0 * * *"},
            action_config={"action_type": "app.invoke"},
            contract_template={"max_compute_tier": 0},
            is_default_enabled=False,
        )
    )
    await db.flush()

    created = await _materialize_install_automations(
        db,
        app_version_id=install_context["app_version_id"],
        installer_user_id=install_context["user_id"],
        team_id=install_context["team_id"],
        target_project_id=install_context["project"].id,
    )
    assert created == 0

    defns = (
        (
            await db.execute(
                select(AutomationDefinition).where(
                    AutomationDefinition.target_project_id
                    == install_context["project"].id
                )
            )
        )
        .scalars()
        .all()
    )
    assert defns == []


async def test_skips_template_with_empty_contract(
    db: AsyncSession,
    install_context,
    caplog,
) -> None:
    """``automation_definitions.contract`` is NOT NULL and the create-router
    rejects empty dicts. Mirror that gate at install time so a malformed
    template can't poison the install transaction with a CHECK violation."""
    db.add(
        AppAutomationTemplate(
            id=uuid.uuid4(),
            app_version_id=install_context["app_version_id"],
            name="Bad contract",
            trigger_config={"kind": "cron"},
            action_config={"action_type": "app.invoke"},
            contract_template={},  # empty
            is_default_enabled=True,
        )
    )
    await db.flush()

    with caplog.at_level(logging.WARNING, logger="app.services.apps.installer"):
        created = await _materialize_install_automations(
            db,
            app_version_id=install_context["app_version_id"],
            installer_user_id=install_context["user_id"],
            team_id=install_context["team_id"],
            target_project_id=install_context["project"].id,
        )
    assert created == 0
    assert any("empty contract_template" in rec.getMessage() for rec in caplog.records)


async def test_skips_template_with_invalid_trigger_kind(
    db: AsyncSession,
    install_context,
    caplog,
) -> None:
    db.add(
        AppAutomationTemplate(
            id=uuid.uuid4(),
            app_version_id=install_context["app_version_id"],
            name="Bad trigger",
            trigger_config={"kind": "telepathy"},  # not in the enum
            action_config={"action_type": "app.invoke"},
            contract_template={"max_compute_tier": 0},
            is_default_enabled=True,
        )
    )
    await db.flush()

    with caplog.at_level(logging.WARNING, logger="app.services.apps.installer"):
        created = await _materialize_install_automations(
            db,
            app_version_id=install_context["app_version_id"],
            installer_user_id=install_context["user_id"],
            team_id=install_context["team_id"],
            target_project_id=install_context["project"].id,
        )
    assert created == 0
    assert any("trigger.kind" in rec.getMessage() for rec in caplog.records)


async def test_skips_template_with_invalid_action_type(
    db: AsyncSession,
    install_context,
    caplog,
) -> None:
    db.add(
        AppAutomationTemplate(
            id=uuid.uuid4(),
            app_version_id=install_context["app_version_id"],
            name="Bad action",
            trigger_config={"kind": "cron"},
            action_config={"action_type": "psychic.summon"},
            contract_template={"max_compute_tier": 0},
            is_default_enabled=True,
        )
    )
    await db.flush()

    with caplog.at_level(logging.WARNING, logger="app.services.apps.installer"):
        created = await _materialize_install_automations(
            db,
            app_version_id=install_context["app_version_id"],
            installer_user_id=install_context["user_id"],
            team_id=install_context["team_id"],
            target_project_id=install_context["project"].id,
        )
    assert created == 0
    assert any("action.action_type" in rec.getMessage() for rec in caplog.records)


async def test_returns_zero_when_no_templates_for_version(
    db: AsyncSession, install_context
) -> None:
    created = await _materialize_install_automations(
        db,
        app_version_id=install_context["app_version_id"],
        installer_user_id=install_context["user_id"],
        team_id=install_context["team_id"],
        target_project_id=install_context["project"].id,
    )
    assert created == 0
