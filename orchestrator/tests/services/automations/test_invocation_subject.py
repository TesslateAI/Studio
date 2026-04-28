"""Phase 2 — unit tests for ``services.automations.invocation_subject``.

The resolver service is exercised against a SQLite database upgraded to
alembic ``head`` so the real ``invocation_subjects`` /
``automation_runs`` / ``spend_records`` tables are in play. We assert
on the persisted row shape directly: the resolved decision must be
visible on ``invocation_subjects`` (not just in the in-memory dataclass)
because every audit query joins through that row.

Test surface (matches the plan's checklist):

* installer default → opensail_credits with the user id as ref.
* parent_run inherits → debits parent's spent_so_far_usd.
* contract.payer_policy overrides app manifest default.
* budget envelope is the contract caps with parent remaining as the cap.
* settle_subject_spend writes a SpendRecord with invocation_subject_id.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, select
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
    db_path = tmp_path / "invocation_subject.db"
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
    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker
    asyncio.run(engine.dispose())


# ---------------------------------------------------------------------------
# Seed helpers — minimal rows so the resolver has something to chew on.
# ---------------------------------------------------------------------------


async def _seed_user(db) -> uuid.UUID:
    from sqlalchemy import insert as core_insert

    from app.models_auth import User

    user_id = uuid.uuid4()
    suffix = uuid.uuid4().hex[:8]
    await db.execute(
        core_insert(User.__table__).values(
            id=user_id,
            email=f"sub-{suffix}@example.com",
            hashed_password="x",
            is_active=True,
            is_superuser=False,
            is_verified=True,
            name="Subject Tester",
            username=f"u{suffix}",
            slug=f"u-{suffix}",
        )
    )
    await db.flush()
    return user_id


async def _seed_automation(
    db,
    *,
    owner_user_id: uuid.UUID,
    contract: dict[str, Any] | None = None,
    attribution_user_id: uuid.UUID | None = None,
    team_id: uuid.UUID | None = None,
) -> uuid.UUID:
    from app.models_automations import AutomationDefinition

    autom = AutomationDefinition(
        id=uuid.uuid4(),
        name="resolver-test",
        owner_user_id=owner_user_id,
        team_id=team_id,
        workspace_scope="none",
        contract=contract
        if contract is not None
        else {
            "allowed_tools": ["read_file"],
            "max_compute_tier": 0,
        },
        max_compute_tier=0,
        attribution_user_id=attribution_user_id,
        is_active=True,
    )
    db.add(autom)
    await db.flush()
    return autom.id


async def _seed_event(db, *, automation_id: uuid.UUID) -> uuid.UUID:
    from app.models_automations import AutomationEvent

    evt = AutomationEvent(
        id=uuid.uuid4(),
        automation_id=automation_id,
        payload={},
        trigger_kind="manual",
    )
    db.add(evt)
    await db.flush()
    return evt.id


async def _seed_run(
    db, *, automation_id: uuid.UUID, event_id: uuid.UUID
) -> uuid.UUID:
    from app.models_automations import AutomationRun

    run = AutomationRun(
        id=uuid.uuid4(),
        automation_id=automation_id,
        event_id=event_id,
        status="preflight",
    )
    db.add(run)
    await db.flush()
    return run.id


async def _seed_action(
    db,
    *,
    automation_id: uuid.UUID,
    action_type: str = "agent.run",
    config: dict[str, Any] | None = None,
    app_action_id: uuid.UUID | None = None,
) -> uuid.UUID:
    from app.models_automations import AutomationAction

    act = AutomationAction(
        id=uuid.uuid4(),
        automation_id=automation_id,
        ordinal=0,
        action_type=action_type,
        config=config or {},
        app_action_id=app_action_id,
    )
    db.add(act)
    await db.flush()
    return act.id


async def _seed_app_action_with_billing(
    db,
    *,
    payer_default: str,
    creator_user_id: uuid.UUID,
) -> uuid.UUID:
    """Insert a marketplace_apps + app_versions + app_actions chain.

    The resolver only reads ``app_actions.billing.ai_compute.payer_default``,
    but the FKs cascade up to ``app_versions`` and ``marketplace_apps`` so
    we have to create the parent rows too.
    """
    from app.models import AppVersion, MarketplaceApp
    from app.models_automations import AppAction

    suffix = uuid.uuid4().hex[:8]
    app = MarketplaceApp(
        id=uuid.uuid4(),
        slug=f"app-{suffix}",
        name="Test App",
        creator_user_id=creator_user_id,
    )
    db.add(app)
    await db.flush()

    version = AppVersion(
        id=uuid.uuid4(),
        app_id=app.id,
        version="0.1.0",
        manifest_schema_version="2026-05",
        manifest_json={"manifest_version": "2026-05"},
        manifest_hash=f"hash-{suffix}",
        feature_set_hash=f"feat-{suffix}",
    )
    db.add(version)
    await db.flush()

    action = AppAction(
        id=uuid.uuid4(),
        app_version_id=version.id,
        name="qualify_lead",
        handler={"kind": "hosted_agent"},
        billing={"ai_compute": {"payer_default": payer_default}},
    )
    db.add(action)
    await db.flush()
    return action.id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_installer_default_resolves_to_opensail_credits(session_maker) -> None:
    """No contract override + no app manifest → installer / opensail_credits."""
    from app.models_automations import AutomationDefinition, AutomationRun
    from app.services.automations.invocation_subject import (
        CreditSource,
        PayerPolicy,
        resolve_invocation_subject,
    )

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            automation_id = await _seed_automation(db, owner_user_id=user_id)
            event_id = await _seed_event(db, automation_id=automation_id)
            run_id = await _seed_run(
                db, automation_id=automation_id, event_id=event_id
            )
            await _seed_action(db, automation_id=automation_id)
            await db.commit()

        async with session_maker() as db:
            run = (
                await db.execute(
                    select(AutomationRun).where(AutomationRun.id == run_id)
                )
            ).scalar_one()
            automation = (
                await db.execute(
                    select(AutomationDefinition).where(
                        AutomationDefinition.id == automation_id
                    )
                )
            ).scalar_one()
            resolved = await resolve_invocation_subject(
                db, automation_run=run, automation=automation
            )
            await db.commit()
            return resolved, user_id

    resolved, user_id = asyncio.run(go())
    assert resolved.payer_policy == PayerPolicy.INSTALLER
    assert resolved.credit_source == CreditSource.OPENSAIL_CREDITS
    assert resolved.credit_source_ref == str(user_id)
    assert resolved.parent_run_id is None


@pytest.mark.unit
def test_parent_run_inherits_billing_and_debits_parent(session_maker) -> None:
    """payer_policy='parent_run' walks the chain; settle_subject_spend rolls up."""
    from app.models_automations import (
        AutomationDefinition,
        AutomationRun,
        InvocationSubject,
    )
    from app.services.automations.invocation_subject import (
        CreditSource,
        PayerPolicy,
        resolve_invocation_subject,
        settle_subject_spend,
    )

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            parent_autom_id = await _seed_automation(
                db,
                owner_user_id=user_id,
                contract={
                    "allowed_tools": ["read_file"],
                    "max_compute_tier": 0,
                    "max_spend_per_run_usd": "1.00",
                },
            )
            parent_event = await _seed_event(db, automation_id=parent_autom_id)
            parent_run_id = await _seed_run(
                db, automation_id=parent_autom_id, event_id=parent_event
            )
            await _seed_action(db, automation_id=parent_autom_id)

            child_autom_id = await _seed_automation(
                db,
                owner_user_id=user_id,
                contract={
                    "allowed_tools": ["read_file"],
                    "max_compute_tier": 0,
                },
            )
            child_event = await _seed_event(db, automation_id=child_autom_id)
            child_run_id = await _seed_run(
                db, automation_id=child_autom_id, event_id=child_event
            )
            await _seed_action(db, automation_id=child_autom_id)
            await db.commit()

        async with session_maker() as db:
            parent_run = (
                await db.execute(
                    select(AutomationRun).where(AutomationRun.id == parent_run_id)
                )
            ).scalar_one()
            parent_autom = (
                await db.execute(
                    select(AutomationDefinition).where(
                        AutomationDefinition.id == parent_autom_id
                    )
                )
            ).scalar_one()
            await resolve_invocation_subject(
                db, automation_run=parent_run, automation=parent_autom
            )
            await db.commit()

        async with session_maker() as db:
            child_run = (
                await db.execute(
                    select(AutomationRun).where(AutomationRun.id == child_run_id)
                )
            ).scalar_one()
            child_autom = (
                await db.execute(
                    select(AutomationDefinition).where(
                        AutomationDefinition.id == child_autom_id
                    )
                )
            ).scalar_one()
            child_resolved = await resolve_invocation_subject(
                db,
                automation_run=child_run,
                automation=child_autom,
                parent_run=parent_run,
            )

            # Spend on the child should bump the parent's running total.
            await settle_subject_spend(
                db,
                subject_id=child_resolved.id,
                spend_usd=Decimal("0.25"),
                dimension="ai_compute",
            )
            await db.commit()

        async with session_maker() as db:
            parent_subject = (
                await db.execute(
                    select(InvocationSubject)
                    .where(InvocationSubject.automation_run_id == parent_run_id)
                )
            ).scalar_one()
            child_subject = (
                await db.execute(
                    select(InvocationSubject).where(
                        InvocationSubject.id == child_resolved.id
                    )
                )
            ).scalar_one()
            parent_run_after = (
                await db.execute(
                    select(AutomationRun).where(AutomationRun.id == parent_run_id)
                )
            ).scalar_one()
            return (
                child_resolved,
                parent_subject,
                child_subject,
                parent_run_after,
                parent_run_id,
            )

    (
        child_resolved,
        parent_subject,
        child_subject,
        parent_run_after,
        parent_run_id,
    ) = asyncio.run(go())

    assert child_resolved.payer_policy == PayerPolicy.PARENT_RUN
    assert child_resolved.credit_source == CreditSource.PARENT_RUN
    assert child_resolved.credit_source_ref == str(parent_run_id)
    # Child's per-run cap is intersected with parent's remaining (1.00 - 0).
    assert child_resolved.budget_envelope.max_usd_per_run == Decimal("1.00")

    # The settle helper bumped both the child AND the parent's spent_so_far.
    assert Decimal(child_subject.spent_so_far_usd) == Decimal("0.25")
    assert Decimal(parent_subject.spent_so_far_usd) == Decimal("0.25")
    # Parent's run-level rollup column also bumped (denormalized for dashboards).
    assert Decimal(parent_run_after.spend_usd) == Decimal("0.25")


@pytest.mark.unit
def test_contract_overrides_app_manifest_default(session_maker) -> None:
    """contract.payer_policy beats app_action.billing.ai_compute.payer_default."""
    from app.models_automations import AutomationDefinition, AutomationRun
    from app.services.automations.invocation_subject import (
        CreditSource,
        PayerPolicy,
        resolve_invocation_subject,
    )

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            # App manifest says 'creator' pays, but contract overrides to 'team'.
            app_action_id = await _seed_app_action_with_billing(
                db, payer_default="creator", creator_user_id=user_id
            )
            team_id = uuid.uuid4()
            # Insert a team row so the FK constraint is satisfied.
            from sqlalchemy import insert as core_insert

            from app.models_team import Team

            await db.execute(
                core_insert(Team.__table__).values(
                    id=team_id,
                    name="Team A",
                    slug=f"team-{uuid.uuid4().hex[:8]}",
                    is_personal=False,
                )
            )
            automation_id = await _seed_automation(
                db,
                owner_user_id=user_id,
                team_id=team_id,
                contract={
                    "allowed_tools": ["read_file"],
                    "max_compute_tier": 0,
                    "payer_policy": "team",
                },
            )
            event_id = await _seed_event(db, automation_id=automation_id)
            run_id = await _seed_run(
                db, automation_id=automation_id, event_id=event_id
            )
            await _seed_action(
                db,
                automation_id=automation_id,
                action_type="app.invoke",
                app_action_id=app_action_id,
            )
            await db.commit()

        async with session_maker() as db:
            run = (
                await db.execute(
                    select(AutomationRun).where(AutomationRun.id == run_id)
                )
            ).scalar_one()
            autom = (
                await db.execute(
                    select(AutomationDefinition).where(
                        AutomationDefinition.id == automation_id
                    )
                )
            ).scalar_one()
            resolved = await resolve_invocation_subject(
                db, automation_run=run, automation=autom
            )
            await db.commit()
            return resolved, team_id

    resolved, team_id = asyncio.run(go())
    assert resolved.payer_policy == PayerPolicy.TEAM
    assert resolved.credit_source == CreditSource.TEAM_CREDITS
    assert resolved.credit_source_ref == str(team_id)


@pytest.mark.unit
def test_budget_envelope_from_contract(session_maker) -> None:
    """Per-run + per-day caps are read off the contract verbatim."""
    from app.models_automations import AutomationDefinition, AutomationRun
    from app.services.automations.invocation_subject import (
        resolve_invocation_subject,
    )

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            automation_id = await _seed_automation(
                db,
                owner_user_id=user_id,
                contract={
                    "allowed_tools": ["read_file"],
                    "max_compute_tier": 0,
                    "max_spend_per_run_usd": "0.50",
                    "max_spend_per_day_usd": "5.00",
                },
            )
            event_id = await _seed_event(db, automation_id=automation_id)
            run_id = await _seed_run(
                db, automation_id=automation_id, event_id=event_id
            )
            await _seed_action(db, automation_id=automation_id)
            await db.commit()

        async with session_maker() as db:
            run = (
                await db.execute(
                    select(AutomationRun).where(AutomationRun.id == run_id)
                )
            ).scalar_one()
            autom = (
                await db.execute(
                    select(AutomationDefinition).where(
                        AutomationDefinition.id == automation_id
                    )
                )
            ).scalar_one()
            resolved = await resolve_invocation_subject(
                db, automation_run=run, automation=autom
            )
            await db.commit()
            return resolved

    resolved = asyncio.run(go())
    assert resolved.budget_envelope.max_usd_per_run == Decimal("0.50")
    assert resolved.budget_envelope.max_usd_per_day == Decimal("5.00")


@pytest.mark.unit
def test_settle_writes_spend_record_with_subject_id(session_maker) -> None:
    """settle_subject_spend stamps invocation_subject_id on the SpendRecord row."""
    from app.models import SpendRecord
    from app.models_automations import (
        AutomationDefinition,
        AutomationRun,
        InvocationSubject,
    )
    from app.services.automations.invocation_subject import (
        resolve_invocation_subject,
        settle_subject_spend,
    )

    async def go():
        async with session_maker() as db:
            user_id = await _seed_user(db)
            automation_id = await _seed_automation(db, owner_user_id=user_id)
            event_id = await _seed_event(db, automation_id=automation_id)
            run_id = await _seed_run(
                db, automation_id=automation_id, event_id=event_id
            )
            await _seed_action(db, automation_id=automation_id)
            await db.commit()

        async with session_maker() as db:
            run = (
                await db.execute(
                    select(AutomationRun).where(AutomationRun.id == run_id)
                )
            ).scalar_one()
            autom = (
                await db.execute(
                    select(AutomationDefinition).where(
                        AutomationDefinition.id == automation_id
                    )
                )
            ).scalar_one()
            resolved = await resolve_invocation_subject(
                db, automation_run=run, automation=autom
            )
            await settle_subject_spend(
                db,
                subject_id=resolved.id,
                spend_usd=Decimal("0.10"),
                dimension="ai_compute",
                record_kwargs={"meta": {"request_id": "abc-123"}},
            )
            await db.commit()

        async with session_maker() as db:
            spend_rows = (
                await db.execute(
                    select(SpendRecord).where(
                        SpendRecord.invocation_subject_id == resolved.id
                    )
                )
            ).scalars().all()
            subject_row = (
                await db.execute(
                    select(InvocationSubject).where(
                        InvocationSubject.id == resolved.id
                    )
                )
            ).scalar_one()
            return spend_rows, subject_row

    spend_rows, subject_row = asyncio.run(go())
    assert len(spend_rows) == 1
    spend = spend_rows[0]
    assert spend.invocation_subject_id == subject_row.id
    assert spend.dimension == "ai_compute"
    assert Decimal(spend.amount_usd) == Decimal("0.10")
    assert spend.payer == "installer"
    assert spend.installer_user_id is not None
    assert spend.automation_run_id == subject_row.automation_run_id
    # Subject's running total bumped in lockstep.
    assert Decimal(subject_row.spent_so_far_usd) == Decimal("0.10")
